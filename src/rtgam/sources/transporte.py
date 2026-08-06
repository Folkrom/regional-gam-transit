"""Fuente 1: afluencia de transporte publico.

Las coordenadas de las estaciones salen de OpenStreetMap via Overpass, no del
portal de la CDMX: una sola consulta cubre Metro, Tren Ligero, Metrobus y
Cablebus, sin API key y sin perseguir shapefiles distintos por sistema.
"""

import json
import re
import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests

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
                OVERPASS_URL, data={"data": query}, timeout=OVERPASS_TIMEOUT_S
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
