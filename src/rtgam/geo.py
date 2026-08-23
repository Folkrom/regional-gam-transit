"""Primitivas geoespaciales: distancia, grid H3 y kernel de decaimiento."""

import math
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

# Radio circunscrito de una celda res 9 y anillos que hay que abrir alrededor
# de la rejilla para no perder ningun punto dentro del corte. Ambos medidos
# sobre una celda real de GAM.
H3_RES9_CIRCUMRADIUS_M = 217.9
COLLAR_RINGS = 3


def bbox_with_margin(
    bounds: tuple[float, float, float, float], margin_m: float = DECAY_CUTOFF_M
) -> tuple[float, float, float, float]:
    """Bounding box de Overpass -sur, oeste, norte, este- con margen en metros.

    `bounds` viene de shapely en su orden: (oeste, sur, este, norte). Los dos
    ordenes existen y no son intercambiables; convertirlos aqui evita que cada
    script lo haga a mano.

    El margen no es decorativo: sin el, la consulta corta justo en el limite y
    un parque o una calle a 300 m del borde no existen para el modelo, que es
    el mismo bug del borde que DENUE tenia por filtrar por municipio. Medido
    sobre la red peatonal, con margen de 800 m siete hexagonos de 724 ganan mas
    de 5% de alcance y el peor 1.81x (2,061 a 3,722 m).

    Un grado de latitud son ~111 km, pero uno de longitud se encoge con el
    coseno de la latitud: usar 111 para los dos dejaria el margen en longitud
    corto justo donde hace falta.
    """
    oeste, sur, este, norte = bounds
    d_lat = margin_m / 111_000.0
    lat_mid = math.radians((sur + norte) / 2)
    d_lon = margin_m / (111_000.0 * math.cos(lat_mid))
    return (sur - d_lat, oeste - d_lon, norte + d_lat, este + d_lon)


def cells_near_grid(hexes: Iterable[str], rings: int = COLLAR_RINGS) -> set[str]:
    """Celdas de la rejilla mas el collar de `rings` anillos a su alrededor.

    Sirve para recortar una fuente ANTES de repartirla: un establecimiento
    cuya celda no esta aqui no puede estar a menos de DECAY_CUTOFF_M de ningun
    centroide, asi que aportaria exactamente cero y solo engorda la matriz.

    Tres anillos no es un numero elegido a ojo. Un punto a 800 m de un
    centroide vive en una celda cuyo centro esta a lo mas 800 + 217.9 = 1017.9
    m de el, y el anillo 4 empieza en 1291.7 m: ninguna celda a esa distancia
    puede contener un punto dentro del corte. Medido tambien por el otro lado
    -contra un filtro por caja envolvente, que trae 45% mas puntos- las dos
    columnas de DENUE salen identicas hasta 1e-13.

    Recortar por municipio en vez de por distancia es lo que producia el bug
    del borde: un negocio a 300 m cruzando la calle no contaba por estar del
    otro lado de una linea administrativa.
    """
    collar: set[str] = set()
    for hex_id in hexes:
        collar.update(h3.grid_disk(hex_id, rings))
    return collar


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


def nearest_decay(
    centroids: pd.DataFrame,
    points: pd.DataFrame,
    tau: float = DECAY_TAU_M,
    cutoff: float = DECAY_CUTOFF_M,
) -> pd.Series:
    """Decaimiento exp(-d/tau) del punto MAS CERCANO, no la suma de todos.

    Los puntos mas alla de `cutoff` metros dan exactamente cero.

    centroids: indexado por hex_id, columnas lat y lon.
    points:    columnas lat y lon. No lleva columna de valor: esto mide
               presencia, y la presencia no pondera.
    Devuelve:  Series de floats en [0, 1] alineada con el indice de
               `centroids`.

    Es la hermana de accumulate_decay, no un modo suyo. La suma cuenta
    puntos, y OSM parte una estacion en tantos nodos como quiera el
    mapeador: La Raza son tres nodos en el mismo anden. Con el maximo, tres
    nodos colocados dan lo mismo que uno, sin dedup y sin umbral que
    justificar. La inmunidad al conteo doble es estructural.
    """
    if len(points) == 0:
        return pd.Series(0.0, index=centroids.index)

    distances = haversine_m(
        centroids["lat"].to_numpy()[:, None],
        centroids["lon"].to_numpy()[:, None],
        points["lat"].to_numpy()[None, :],
        points["lon"].to_numpy()[None, :],
    )
    weights = np.where(distances <= cutoff, np.exp(-distances / tau), 0.0)
    return pd.Series(weights.max(axis=1), index=centroids.index)
