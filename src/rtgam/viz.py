"""Utilidades de visualizacion compartidas por el dashboard."""

import h3
import pandas as pd

NORM_SUFFIX = "_norm"


def hex_polygon_latlon(hex_id: str) -> list[tuple[float, float]]:
    """Vertices de una celda H3 en orden (lat, lon), como los quiere Folium.

    h3.cell_to_boundary ya devuelve (lat, lon), al reves de la convencion
    GeoJSON. No invertirlo.
    """
    return [(lat, lon) for lat, lon in h3.cell_to_boundary(hex_id)]


def rescore(scores: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Recalcula el score a partir de las columnas ya normalizadas.

    Es solo un producto punto sobre columnas que ya estan en 0-1, asi que
    mover un slider en el dashboard es instantaneo y no requiere volver a
    correr el pipeline.
    """
    total = pd.Series(0.0, index=scores.index)
    for column, weight in weights.items():
        norm_column = f"{column}{NORM_SUFFIX}"
        if norm_column in scores.columns:
            total = total + weight * scores[norm_column]
    return total
