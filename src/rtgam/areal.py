"""Reparto areal: cuanta parte de un poligono cae en cada hexagono.

Es una primitiva al mismo nivel que geo.py y red.py. No sabe que es un AGEB
ni que columnas produce el score: reparte poligonos entre poligonos.

No se reproyecta a UTM. Las areas se usan como PROPORCIONES -numerador y
denominador salen de la misma interseccion- asi que el factor de escala de la
latitud se cancela en el cociente. Es la misma logica por la que geo.py usa
haversine en vez de pyproj.
"""

import h3
import pandas as pd
from shapely.geometry import Polygon
from shapely.strtree import STRtree


def hex_polygons(hexes: pd.DataFrame) -> dict[str, Polygon]:
    """Poligono de cada celda H3, en coordenadas (lon, lat).

    hexes: indexado por hex_id. Las columnas no se usan; solo el indice.

    h3.cell_to_boundary devuelve tuplas (lat, lon) y shapely espera (x, y),
    es decir (lon, lat). Invertirlas no lanza nada: produce poligonos en el
    hemisferio equivocado que no intersectan ningun AGEB, y las dos columnas
    de la fuente salen en cero sin una sola excepcion.
    """
    return {
        hex_id: Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(hex_id)])
        for hex_id in hexes.index
    }


def area_weights(
    hex_polys: dict[str, Polygon],
    source_polys: dict[str, Polygon],
) -> pd.DataFrame:
    """Fraccion del area de cada poligono origen que cae en cada hexagono.

    Devuelve un DataFrame indexado por hex_id, con una columna por clave de
    source_polys. El valor [h, s] es el area de la interseccion entre s y h,
    dividida entre el area total de s.

    La propiedad que hace correcto todo lo que viene despues: cada COLUMNA
    suma como mucho 1.0, y suma exactamente 1.0 cuando el poligono origen esta
    enteramente cubierto por los hexagonos. Eso es lo que conserva la
    poblacion al repartirla.

    Un poligono que sobresale de la reticula reparte solo la parte cubierta y
    el resto se pierde a proposito: re-escalar a 1.0 inventaria poblacion
    dentro de GAM que en realidad vive fuera.

    Se usa un STRtree para no cruzar 724 x 305 pares uno por uno, el mismo
    patron que drop_nested en sources/osm.py.
    """
    hex_ids = list(hex_polys)
    index = pd.Index(hex_ids, name="hex_id")

    if not source_polys:
        return pd.DataFrame(index=index)

    figures = [hex_polys[h] for h in hex_ids]
    tree = STRtree(figures)

    columns = {}
    for key, source in source_polys.items():
        total = source.area
        column = [0.0] * len(hex_ids)
        if total > 0:
            for position in tree.query(source):
                shared = figures[position].intersection(source).area
                if shared > 0:
                    column[position] = shared / total
        columns[key] = column

    return pd.DataFrame(columns, index=index)
