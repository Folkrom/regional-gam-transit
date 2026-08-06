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

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
GAM_NOMINATIM_QUERY = "Gustavo A. Madero, Ciudad de Mexico, Mexico"

# Nominatim rechaza peticiones sin User-Agent identificable. Es su politica
# de uso, no un detalle opcional.
USER_AGENT = "regional-transit-gam/0.1 (analisis academico de ubicacion)"


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
    """
    if cache_path.exists() and not force:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    else:
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
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(payload), encoding="utf-8")

    return polygon_from_nominatim_geojson(payload)
