"""Fuente 1: afluencia de transporte publico.

Las coordenadas de las estaciones salen de OpenStreetMap via Overpass, no del
portal de la CDMX: una sola consulta cubre Metro, Tren Ligero, Metrobus y
Cablebus, sin API key y sin perseguir shapefiles distintos por sistema.
"""

import difflib
import json
import re
import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests

from rtgam import USER_AGENT
from rtgam.geo import accumulate_decay

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_S = 180
OVERPASS_RETRIES = 3

STATION_COLUMNS = ["osm_name", "lat", "lon"]


def normalize_name(name: str) -> str:
    """Forma canonica de un nombre de estacion para poder compararlo.

    Minusculas, sin acentos, sin puntuacion, espacios colapsados. Necesario
    porque el CSV de afluencia y OSM escriben los nombres distinto:
    "La Villa-Basilica" contra "La Villa Basílica".
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    no_punctuation = re.sub(r"[^a-z0-9 ]", " ", lowered)
    return re.sub(r"\s+", " ", no_punctuation).strip()


def stations_from_overpass(payload: dict) -> pd.DataFrame:
    """Convierte una respuesta de Overpass en un DataFrame de estaciones.

    Los elementos sin nombre o sin coordenadas se descartan: no se pueden
    cruzar con la afluencia ni ubicar en el mapa. Se deduplica por nombre
    porque OSM suele tener un nodo y un way para la misma estacion.
    """
    rows = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        name = tags.get("name")
        if not name:
            continue

        if "lat" in element and "lon" in element:
            lat, lon = element["lat"], element["lon"]
        elif "center" in element:
            lat, lon = element["center"]["lat"], element["center"]["lon"]
        else:
            continue

        rows.append((name, float(lat), float(lon)))

    df = pd.DataFrame(rows, columns=STATION_COLUMNS)
    return df.drop_duplicates(subset="osm_name", keep="first").reset_index(drop=True)


def build_overpass_query(bbox: tuple[float, float, float, float]) -> str:
    """Consulta Overpass para estaciones dentro de un bounding box.

    bbox en el orden que espera Overpass: (sur, oeste, norte, este).
    aerialway=station cubre el Cablebus, que en GAM importa mucho: la Linea 1
    esta enteramente dentro de la alcaldia.
    """
    south, west, north, east = bbox
    box = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:{OVERPASS_TIMEOUT_S}];
(
  nwr["railway"="station"]({box});
  nwr["aerialway"="station"]({box});
  nwr["public_transport"="station"]({box});
);
out center tags;
"""


def fetch_stations(
    bbox: tuple[float, float, float, float],
    cache_path: Path,
    force: bool = False,
) -> pd.DataFrame:
    """Descarga las estaciones con cache en disco y reintentos.

    Overpass es un servidor gratuito y devuelve 429 bajo carga, por eso el
    backoff exponencial.
    Igual que en boundary.py, la cache se escribe DESPUES de parsear, nunca
    antes: un payload inservible persistido se releeria en cada corrida.
    """
    if cache_path.exists() and not force:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"La cache {cache_path} esta corrupta o truncada. "
                f"Borrala o corre con --force para volver a descargar. ({error})"
            ) from error
        return stations_from_overpass(payload)

    query = build_overpass_query(bbox)
    last_error: Exception | None = None
    for attempt in range(OVERPASS_RETRIES):
        try:
            response = requests.post(
                OVERPASS_URL,
                data={"data": query},
                headers={"User-Agent": USER_AGENT},
                timeout=OVERPASS_TIMEOUT_S,
            )
            response.raise_for_status()
            payload = response.json()
            stations = stations_from_overpass(payload)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
            return stations
        except requests.HTTPError as error:
            # Un 4xx que no sea 429 es un bug de nuestra consulta, no una falla
            # transitoria. Reintentarlo tres veces solo castiga a un servidor
            # gratuito y retrasa el error real quince segundos.
            status = error.response.status_code if error.response is not None else None
            if status is not None and 400 <= status < 500 and status != 429:
                raise
            last_error = error
        except (requests.RequestException, ValueError) as error:
            last_error = error

        if attempt < OVERPASS_RETRIES - 1:
            backoff = 5 * (2**attempt)
            print(f"Overpass fallo ({last_error}); reintento en {backoff}s")
            time.sleep(backoff)

    raise RuntimeError(f"Overpass fallo tras {OVERPASS_RETRIES} intentos") from last_error


def fix_mojibake(name: str) -> str:
    """Repara nombres que llegaron como UTF-8 decodificado dos veces.

    El CSV de afluencia del Metro trae una parte de los nombres
    doblemente codificados: "AragÃ³n" en vez de "Aragón". Reinterpretar
    esos bytes como latin-1 y volver a decodificarlos como UTF-8 restaura
    el nombre original.

    Es idempotente: un nombre ya correcto (sin mojibake) no tiene una
    reinterpretacion valida en UTF-8 y se devuelve sin tocar.
    """
    try:
        return name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


NAME_MATCH_CUTOFF = 0.85


def weekday_mean_by_station(
    daily: pd.DataFrame,
    year: int,
    date_col: str,
    station_col: str,
    value_col: str,
) -> pd.DataFrame:
    """Promedio de afluencia en dia habil por estacion, para un ano dado.

    Los nombres de columna se pasan como argumentos porque cada sistema
    (Metro, Metrobus, STE) publica su CSV con encabezados distintos.

    Solo lunes a viernes: mezclar el domingo borra la senal que distingue una
    zona de oficinas de una residencial, que es justo lo que interesa para una
    cafeteria.
    """
    frame = daily.copy()
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame = frame.dropna(subset=[date_col])

    is_target_year = frame[date_col].dt.year == year
    is_weekday = frame[date_col].dt.weekday < 5
    frame = frame[is_target_year & is_weekday]

    grouped = frame.groupby(station_col)[value_col].mean().reset_index()
    grouped.columns = ["afluencia_name", "afluencia_habil"]
    return grouped


def propose_name_map(
    afluencia_names,
    osm_names,
    cutoff: float = NAME_MATCH_CUTOFF,
) -> pd.DataFrame:
    """Propone el cruce entre nombres del CSV de afluencia y nombres de OSM.

    Es una propuesta, no la verdad: la salida se revisa a mano y se corrige
    antes de usarse. Los nombres sin match quedan con osm_name en None para
    que salten a la vista.

    Compara sobre la forma normalizada, asi que acentos y guiones no estorban.

    Un solo umbral de similaridad no alcanza: "Deportivo 18 de Marzo" contra
    "18 de Marzo" (el caso real que motiva esta funcion) puntua 0.69, mientras
    que "Obrera" contra "Potrero" puntua 0.62. Cualquier corte que acepte al
    primero acepta tambien al segundo, y el segundo es basura: son estaciones
    en alcaldias distintas, a varios kilometros. Por eso se resuelve en tres
    pasos, cada uno mas permisivo que el anterior, y el primero que produce
    una respuesta gana:

    1. Igualdad exacta sobre el nombre normalizado.
    2. Contencion de subcadena, solo si hay una unica estacion de OSM que
       contenga (o este contenida en) el nombre. Con varias candidatas no se
       puede saber cual es la correcta sin ver el mapa, asi que se deja sin
       cruzar.
    3. Similaridad difusa con un umbral alto (NAME_MATCH_CUTOFF), como ultimo
       recurso para los nombres que ni son iguales ni uno contiene al otro.
    """
    normalized_osm = {normalize_name(name): name for name in osm_names}

    rows = []
    for name in sorted(afluencia_names):
        key = normalize_name(name)

        # 1. Igualdad exacta ya normalizada. Gana siempre, y es lo que salva a
        #    "Aragon", "Bosque de Aragon" y "Villa de Aragon" de pisarse entre
        #    ellas: las tres son estaciones distintas y reales.
        if key in normalized_osm:
            rows.append((name, normalized_osm[key], 1.0))
            continue

        # 2. Contencion de subcadena, solo si es UNICA. Esto es lo que cruza
        #    "Deportivo 18 de Marzo" con "18 de Marzo", que puntua apenas 0.69
        #    y no pasaria ningun umbral sano. Si hay varias candidatas la
        #    dejamos sin cruzar: que decida un humano, no el desempate.
        contained = sorted(
            {osm for osm_key, osm in normalized_osm.items()
             if key in osm_key or osm_key in key}
        )
        if len(contained) == 1:
            rows.append((name, contained[0], 0.9))
            continue
        if len(contained) > 1:
            rows.append((name, None, 0.0))
            continue

        # 3. Similaridad difusa, con umbral alto. El 0.6 original cruzaba
        #    "Obrera" con "Potrero" (0.62) y "Zapata" con "La Pastora" (0.62),
        #    mandando afluencia de estaciones de otras alcaldias a hexagonos
        #    de GAM. Eso no es un cruce flojo: es dato inventado.
        best_osm, best_score = None, 0.0
        for osm_key, osm in normalized_osm.items():
            score = difflib.SequenceMatcher(None, key, osm_key).ratio()
            if score > best_score:
                best_osm, best_score = osm, score
        if best_score >= cutoff:
            rows.append((name, best_osm, best_score))
        else:
            rows.append((name, None, 0.0))

    return pd.DataFrame(rows, columns=["afluencia_name", "osm_name", "similarity"])


def to_hex_features(gam_hexes: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame:
    """Reparte la afluencia de las estaciones sobre los hexagonos.

    gam_hexes: indexado por hex_id, columnas lat y lon.
    stations:  columnas lat, lon y afluencia_habil.
    Devuelve:  DataFrame indexado por hex_id con la unica columna que esta
               fuente posee, flujo_transporte, en valor crudo y sin normalizar.
    """
    flow = accumulate_decay(gam_hexes, stations, value_col="afluencia_habil")
    return pd.DataFrame({"flujo_transporte": flow})
