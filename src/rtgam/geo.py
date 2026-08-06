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

    El set() no es decorativo: h3 4.5.0 devuelve una list, y el contrato de
    esta funcion es un set porque quien la consume espera unicidad garantizada
    y operadores de conjunto.
    """
    return set(h3.geo_to_cells(polygon, resolution))


def hex_centroids(hexes: Iterable[str]) -> pd.DataFrame:
    """DataFrame indexado por hex_id con el centroide de cada celda.

    Ordenado por hex_id para que la salida sea deterministica entre corridas.
    Ojo: h3.cell_to_latlng devuelve (lat, lon), no (lon, lat).
    """
    rows = [(h, *h3.cell_to_latlng(h)) for h in sorted(hexes)]
    return pd.DataFrame(rows, columns=["hex_id", "lat", "lon"]).set_index("hex_id")


DECAY_TAU_M = 300.0
DECAY_CUTOFF_M = 800.0


def accumulate_decay(
    centroids: pd.DataFrame,
    points: pd.DataFrame,
    value_col: str,
    tau: float = DECAY_TAU_M,
    cutoff: float = DECAY_CUTOFF_M,
) -> pd.Series:
    """Suma de los valores de `points` ponderados por exp(-d/tau).

    Los puntos mas alla de `cutoff` metros aportan exactamente cero.

    centroids: indexado por hex_id, columnas lat y lon.
    points:    columnas lat, lon y `value_col`.
    Devuelve:  Series de floats alineada con el indice de `centroids`.

    Construye la matriz completa (n_hexagonos, n_puntos). Para GAM son ~900
    hexagonos por unos miles de puntos como mucho, asi que cabe de sobra en
    memoria y evita cualquier bucle en Python.
    """
    if len(points) == 0:
        return pd.Series(0.0, index=centroids.index)

    # Un solo NaN aqui no ensucia un hexagono: los ensucia TODOS. El producto
    # punto multiplica cada peso por cada valor, y 0.0 * NaN sigue siendo NaN,
    # asi que hasta un hexagono a 90 km, muy fuera del corte, sale NaN. Falla
    # ruidoso: un NaN en la afluencia es un bug de datos que hay que ver.
    missing = int(points[value_col].isna().sum())
    if missing:
        raise ValueError(
            f"{value_col} trae {missing} valores NaN. El producto punto los "
            f"propagaria a los {len(centroids)} hexagonos, no solo a los "
            f"cercanos. Limpia la fuente antes de repartir."
        )

    distances = haversine_m(
        centroids["lat"].to_numpy()[:, None],
        centroids["lon"].to_numpy()[:, None],
        points["lat"].to_numpy()[None, :],
        points["lon"].to_numpy()[None, :],
    )
    weights = np.where(distances <= cutoff, np.exp(-distances / tau), 0.0)
    totals = weights @ points[value_col].to_numpy(dtype=float)
    return pd.Series(totals, index=centroids.index)
