"""Fuente 3: accesibilidad peatonal y atractores de espacio publico desde OSM.

La frontera con DENUE es explicita: DENUE es comercio privado, OSM es lo que el
registro de negocios no ve. Parques, plazas, deportivos, mercados publicos y
paradas de transporte.
"""

import json
import time
from pathlib import Path

import requests

from rtgam import USER_AGENT

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
    """Consulta Overpass para espacio publico y paradas de transporte.

    `nwr` y no `way`: el Bosque de San Juan de Aragon existe SOLO como relation,
    y una consulta de puros `way` lo pierde sin lanzar nada.

    `out tags center` devuelve el centroide ya calculado para ways y relations,
    y las coordenadas propias para los nodos sueltos.

    El suelo de conservacion no se pide: la Sierra de Guadalupe es ladera, no
    plaza, y meterla pondria un atractor enorme sobre los hexagonos con menos
    banqueta de la alcaldia.

    Las tres etiquetas de transporte son las mismas que ya usa transporte.py,
    para no introducir un universo distinto de paradas.
    """
    south, west, north, east = bbox
    box = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:{OVERPASS_TIMEOUT_S}];
(
  nwr["leisure"~"^(park|garden|pitch|playground|sports_centre)$"]({box});
  nwr["amenity"="marketplace"]({box});
  nwr["place"="square"]({box});
  nwr["railway"="station"]({box});
  nwr["aerialway"="station"]({box});
  nwr["public_transport"="station"]({box});
);
out tags center;
"""


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
