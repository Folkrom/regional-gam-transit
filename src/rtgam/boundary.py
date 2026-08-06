"""Obtencion del poligono de la alcaldia Gustavo A. Madero.

Se usa Nominatim de OpenStreetMap en vez del portal de datos de la CDMX porque
devuelve el poligono listo en GeoJSON con una sola peticion, sin API key y sin
depender de una URL de descarga que cambia entre versiones del portal.
"""

import json
from pathlib import Path

import requests
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from rtgam import USER_AGENT

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
GAM_NOMINATIM_QUERY = "Gustavo A. Madero, Ciudad de Mexico, Mexico"


def polygon_from_nominatim_geojson(payload: dict) -> BaseGeometry:
    """Extrae el poligono de la primera feature de una respuesta de Nominatim."""
    features = payload.get("features", [])
    if not features:
        raise ValueError("Nominatim devolvio sin resultados para la consulta")

    geometry = features[0]["geometry"]
    if geometry["type"] not in ("Polygon", "MultiPolygon"):
        raise ValueError(
            f"Nominatim devolvio {geometry['type']}, que no es un poligono. "
            "Revisa la consulta o descarga el limite a mano."
        )
    return shape(geometry)


def fetch_gam_polygon(cache_path: Path, force: bool = False) -> BaseGeometry:
    """Descarga el poligono de GAM, con cache en disco.

    Si `cache_path` existe y `force` es falso, no toca la red.

    El orden importa: se valida ANTES de escribir la cache. Al reves, una
    respuesta 200 con geometria inservible quedaria persistida y envenenaria
    todas las corridas siguientes, que releerian el mismo payload malo y
    fallarian igual sin explicar por que.
    """
    if cache_path.exists() and not force:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"La cache {cache_path} esta corrupta o truncada. "
                f"Borrala o corre con --force para volver a descargar. ({error})"
            ) from error
        return polygon_from_nominatim_geojson(payload)

    response = requests.get(
        NOMINATIM_URL,
        params={
            "q": GAM_NOMINATIM_QUERY,
            "format": "geojson",
            "polygon_geojson": 1,
            "limit": 1,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()

    polygon = polygon_from_nominatim_geojson(payload)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return polygon
