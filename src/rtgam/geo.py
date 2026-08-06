"""Primitivas geoespaciales: distancia, grid H3 y kernel de decaimiento."""

from collections.abc import Iterable

import h3
import numpy as np
import pandas as pd

EARTH_RADIUS_M = 6_371_008.8
H3_RESOLUTION = 9


def haversine_m(lat1, lon1, lat2, lon2):
    """Distancia de circulo maximo en metros.

    Acepta escalares o arrays de numpy y respeta broadcasting, lo que permite
    construir una matriz (n_hexagonos, n_puntos) en una sola llamada.

    Se usa haversine en vez de reproyectar a UTM porque a distancias menores a
    un kilometro el error es despreciable y evita depender de pyproj.
    """
    lat1, lon1, lat2, lon2 = (np.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def hexes_for_polygon(polygon, resolution: int = H3_RESOLUTION) -> set[str]:
    """Celdas H3 cuyo centro cae dentro del poligono.

    `polygon` es cualquier objeto con __geo_interface__ (shapely sirve).
    h3.geo_to_cells respeta la convencion GeoJSON de lon/lat.
    """
    return h3.geo_to_cells(polygon, resolution)


def hex_centroids(hexes: Iterable[str]) -> pd.DataFrame:
    """DataFrame indexado por hex_id con el centroide de cada celda.

    Ordenado por hex_id para que la salida sea deterministica entre corridas.
    Ojo: h3.cell_to_latlng devuelve (lat, lon), no (lon, lat).
    """
    rows = [(h, *h3.cell_to_latlng(h)) for h in sorted(hexes)]
    return pd.DataFrame(rows, columns=["hex_id", "lat", "lon"]).set_index("hex_id")
