"""Fuente 3: accesibilidad peatonal y atractores de espacio publico desde OSM.

La frontera con DENUE es explicita: DENUE es comercio privado, OSM es lo que el
registro de negocios no ve. Parques, plazas, deportivos y mercados publicos.
"""

import json
import time
from pathlib import Path

import pandas as pd
import requests
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree

from rtgam import USER_AGENT
from rtgam.geo import accumulate_decay

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OVERPASS_TIMEOUT_S = 180
OVERPASS_RETRIES = 3

# Vias que no son caminables. Se excluyen por regex en la consulta para no
# bajar 33 mil vias y filtrarlas despues.
EXCLUDED_HIGHWAY = "motorway|motorway_link|trunk|trunk_link|construction|proposed|raceway"


def build_network_query(bbox: tuple[float, float, float, float]) -> str:
    """Consulta Overpass para la red caminable dentro de un bounding box.

    bbox en el orden que espera Overpass: (sur, oeste, norte, este).

    Pide `out geom;` porque el armado del grafo necesita las dos cosas: los ids
    de nodo, para que las vias se conecten solas al compartirlos, y las
    coordenadas, para medir la longitud de cada arista.

    El bbox se usa tal cual, sin recortar a la geometria de GAM: la red no se
    corta en el limite politico, y dejar la traza de las alcaldias vecinas es
    lo que hace que el alcance de los hexagonos de orilla salga correcto.
    """
    south, west, north, east = bbox
    box = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:{OVERPASS_TIMEOUT_S}];
way["highway"]["highway"!~"{EXCLUDED_HIGHWAY}"]["area"!~"yes"]({box});
out geom;
"""


def build_attractor_query(bbox: tuple[float, float, float, float]) -> str:
    """Consulta Overpass para espacio publico.

    `nwr` y no `way`: el Bosque de San Juan de Aragon existe SOLO como relation,
    y una consulta de puros `way` lo pierde sin lanzar nada.

    `out geom` y no `out tags center`: hace falta el poligono completo, no solo
    un punto, para saber que atractores estan DENTRO de otro. Un `center` no
    contiene nada. Cuesta 1.1 MB en vez de 293 KB, que no es costo.

    El suelo de conservacion no se pide: la Sierra de Guadalupe es ladera, no
    plaza, y meterla pondria un atractor enorme sobre los hexagonos con menos
    banqueta de la alcaldia.

    Las estaciones tampoco se piden, y esto cambio: antes si. Viven en
    presencia_transporte, que las mide con el maximo del kernel en vez de la
    suma. Contarlas aqui tambien ponia dos sliders del dashboard moviendo la
    misma senal, 84 de 1,300 atractores.
    """
    south, west, north, east = bbox
    box = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:{OVERPASS_TIMEOUT_S}];
(
  nwr["leisure"~"^(park|garden|pitch|playground|sports_centre)$"]({box});
  nwr["amenity"="marketplace"]({box});
  nwr["place"="square"]({box});
);
out geom;
"""


ATTRACTOR_COLUMNS = ["osm_kind", "name", "lat", "lon"]

# Suelo de conservacion. La Sierra de Guadalupe viene etiquetada a la vez como
# parque y como area protegida, asi que no basta con no pedirla: hay que
# descartarla explicitamente al parsear.
EXCLUDED_TAGS = {
    "boundary": {"protected_area"},
    "leisure": {"nature_reserve"},
    "natural": {"wood", "scrub", "heath"},
}

# Etiqueta -> tipo de atractor. El orden importa: el primero que cruce gana.
# Las estaciones NO estan aqui: son presencia_transporte, no espacio publico.
ATTRACTOR_TAGS = (
    ("leisure", {"park", "garden", "pitch", "playground", "sports_centre"}),
    ("amenity", {"marketplace"}),
    ("place", {"square"}),
)


def attractor_kind(tags: dict) -> str | None:
    """Tipo de atractor de un elemento, o None si no es ninguno.

    Devuelve el valor de la etiqueta, no la etiqueta: un parque es "park" y un
    mercado es "marketplace", que es lo que sirve para el conteo por tipo que
    el script imprime.
    """
    for key, values in EXCLUDED_TAGS.items():
        if tags.get(key) in values:
            return None

    for key, values in ATTRACTOR_TAGS:
        value = tags.get(key)
        if value in values:
            return value

    return None


def element_polygon(element: dict) -> Polygon | None:
    """Poligono de un elemento pedido con `out geom`, o None si no lo tiene.

    Un way trae `geometry`, una lista de puntos. Una relation trae `members`,
    cada uno con su propia `geometry`: el poligono de la relation es la union
    de los anillos de sus miembros. Los roles outer/inner se ignoran, asi que
    un parque con un hueco adentro sale sin el hueco. Para lo unico que se usa
    el poligono —saber que cae dentro de que— el hueco no cambia nada, y
    armarlo bien seria reimplementar el ensamblado de multipoligonos de OSM.

    Los anillos con menos de cuatro puntos no cierran una figura. Los invalidos
    (que se cruzan a si mismos, comunes en OSM) se reparan con buffer(0), el
    truco estandar de shapely.

    Un nodo no tiene poligono y devuelve None: puede quedar contenido en otro
    atractor, pero no puede contener a nadie.
    """

    def anillo(puntos) -> Polygon | None:
        if not puntos or len(puntos) < 4:
            return None
        try:
            poligono = Polygon([(p["lon"], p["lat"]) for p in puntos])
        except (TypeError, ValueError):
            return None
        if not poligono.is_valid:
            poligono = poligono.buffer(0)
        if poligono.is_empty or poligono.area == 0 or not isinstance(poligono, Polygon):
            return None
        return poligono

    if "geometry" in element:
        return anillo(element["geometry"])

    if "members" in element:
        anillos = [
            figura
            for miembro in element["members"]
            if (figura := anillo(miembro.get("geometry"))) is not None
        ]
        if not anillos:
            return None
        unido = unary_union(anillos)
        # Una relation con miembros sueltos da un MultiPolygon. El casco convexo
        # lo vuelve un poligono, que es lo que necesita la prueba de contencion.
        return unido if isinstance(unido, Polygon) else unido.convex_hull

    return None


def drop_nested(frame: pd.DataFrame, polygons: list) -> pd.DataFrame:
    """Quita los atractores que caen dentro de otro atractor mas grande.

    frame:    columnas osm_kind, name, lat, lon.
    polygons: alineado por posicion con frame; None para lo que no es poligono.

    Un deportivo con ocho canchas mapeadas aparte contaba nueve veces, y la
    cancha no es un destino distinto del deportivo que la contiene: es el mismo
    sitio digitalizado con mas detalle. Medido en GAM (sin estaciones, que ya
    no se piden): 470 de 1,688 atractores (28%) caen dentro de otro. El
    Deportivo Hermanos Galeana trae 56 canchas y contaba 57 veces.

    El contenedor tiene que ser ESTRICTAMENTE mayor. Dos poligonos del mismo
    tamano que se traslapan son dos sitios distintos mal digitalizados, no uno
    dentro de otro; sin la comparacion de area, cual sobrevive dependeria del
    orden del payload.

    La regla vale para todos los tipos, no solo canchas: 43 jardines dentro de
    su parque, 6 parques dentro de otro parque, 5 mercados dentro de otro
    mercado. Es la misma subdivision del mismo espacio publico con otro nombre.
    """
    if frame.empty:
        return frame

    con_poligono = [(i, p) for i, p in enumerate(polygons) if p is not None]
    if not con_poligono:
        return frame

    posiciones = [i for i, _ in con_poligono]
    figuras = [p for _, p in con_poligono]
    areas = [p.area for p in figuras]
    tree = STRtree(figuras)

    puntos = [Point(lon, lat) for lat, lon in zip(frame["lat"], frame["lon"])]
    area_propia = dict(zip(posiciones, areas))

    anidado = []
    for i, punto in enumerate(puntos):
        propia = area_propia.get(i, 0.0)
        contenido = False
        for j in tree.query(punto):
            if posiciones[j] == i or areas[j] <= propia:
                continue
            if figuras[j].contains(punto):
                contenido = True
                break
        anidado.append(contenido)

    return frame[~pd.Series(anidado, index=frame.index)]


def attractors_from_overpass(payload: dict) -> pd.DataFrame:
    """Convierte una respuesta de Overpass en un DataFrame de atractores.

    Acepta node, way y relation. Un nodo se ubica en sus propias coordenadas;
    un way o una relation, en el centroide de su geometria.

    Un elemento sin coordenadas no se puede ubicar en el mapa, asi que se
    descarta.

    Lo que cae dentro de un atractor mayor no cuenta aparte: ver drop_nested.
    """
    rows = []
    polygons = []
    for element in payload.get("elements", []):
        kind = attractor_kind(element.get("tags", {}))
        if kind is None:
            continue

        polygon = element_polygon(element)
        if polygon is not None:
            centroid = polygon.centroid
            lat, lon = centroid.y, centroid.x
        elif "lat" in element and "lon" in element:
            lat, lon = element["lat"], element["lon"]
        else:
            continue

        name = element.get("tags", {}).get("name", "")
        rows.append((kind, name, float(lat), float(lon)))
        polygons.append(polygon)

    frame = drop_nested(pd.DataFrame(rows, columns=ATTRACTOR_COLUMNS), polygons)
    return frame.reset_index(drop=True)


def validate_payload(payload: dict) -> dict:
    """Comprueba que una respuesta de Overpass sirve, antes de cachearla.

    Overpass saturado responde HTTP 200 de dos maneras inservibles: con un
    cuerpo HTML, que revienta al parsear, y con JSON valido que trae `elements`
    vacio y el error dentro de `remark`. La segunda pasa cualquier
    raise_for_status y cualquier json(), asi que hay que mirarla a mano.
    """
    if not isinstance(payload, dict) or "elements" not in payload:
        raise ValueError(
            "La respuesta de Overpass no trae 'elements'. No es una respuesta "
            "util y no se va a cachear."
        )

    remark = payload.get("remark", "")
    if remark:
        raise ValueError(
            f"Overpass respondio 200 pero con un remark de error: {remark}. "
            f"El servidor esta saturado; reintenta mas tarde."
        )

    return payload


def fetch_overpass(query: str, cache_path: Path, force: bool = False) -> dict:
    """Descarga una consulta de Overpass, con cache en disco y espejos.

    El orden importa y no es negociable: se valida ANTES de escribir la cache.
    Al reves, una respuesta 200 inservible queda persistida y envenena todas
    las corridas siguientes, que releen el mismo payload malo.
    """
    if cache_path.exists() and not force:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"La cache {cache_path} esta corrupta o truncada. "
                f"Borrala o corre con --force para volver a descargar. ({error})"
            ) from error
        return validate_payload(payload)

    last_error: Exception | None = None
    for attempt in range(OVERPASS_RETRIES):
        for url in OVERPASS_URLS:
            try:
                response = requests.post(
                    url,
                    data={"data": query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=OVERPASS_TIMEOUT_S,
                )
                response.raise_for_status()
                payload = validate_payload(response.json())
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(payload), encoding="utf-8")
                return payload
            except requests.HTTPError as error:
                # Un 4xx que no sea 429 es un bug de nuestra consulta, no una
                # falla transitoria: reintentarlo solo castiga a un servidor
                # gratuito y retrasa el error real.
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

    raise RuntimeError(
        f"Overpass fallo tras {OVERPASS_RETRIES} intentos en {len(OVERPASS_URLS)} espejos"
    ) from last_error


def to_hex_features(
    gam_hexes: pd.DataFrame,
    alcance: pd.Series,
    atractores: pd.DataFrame,
) -> pd.DataFrame:
    """Emite las dos columnas que esta fuente posee.

    gam_hexes:  indexado por hex_id, columnas lat y lon.
    alcance:    Series indexada por hex_id, metros de calle alcanzables.
    atractores: columnas osm_kind, name, lat, lon.
    Devuelve:   DataFrame indexado por hex_id con accesibilidad_peatonal y
                atractores_osm, en valores CRUDOS y sin normalizar.

    Cada atractor vale 1.0, igual que cada establecimiento en DENUE, donde
    ponderar por tamano resulto contraproducente: los gigantes eran destinos de
    coche y concentraban una cuarta parte de la variable.
    """
    if not alcance.index.equals(gam_hexes.index):
        raise ValueError(
            "El indice del alcance no coincide con el de los hexagonos. "
            "Reindexar en silencio convertiria un bug de indice en ceros "
            "plausibles, que es peor que fallar."
        )

    puntos = atractores.assign(peso=1.0)
    return pd.DataFrame(
        {
            "accesibilidad_peatonal": alcance.astype(float),
            "atractores_osm": accumulate_decay(gam_hexes, puntos, value_col="peso"),
        }
    )
