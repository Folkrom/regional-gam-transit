import json

import pytest
from shapely.geometry import MultiPolygon, Polygon

from rtgam.boundary import polygon_from_nominatim_geojson


def _feature(geometry):
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": geometry}]}


def test_parses_polygon():
    payload = _feature(
        {
            "type": "Polygon",
            "coordinates": [[[-99.15, 19.50], [-99.10, 19.50], [-99.10, 19.55], [-99.15, 19.55], [-99.15, 19.50]]],
        }
    )
    poly = polygon_from_nominatim_geojson(payload)
    assert isinstance(poly, Polygon)
    assert poly.bounds == (-99.15, 19.50, -99.10, 19.55)


def test_parses_multipolygon():
    payload = _feature(
        {
            "type": "MultiPolygon",
            "coordinates": [
                [[[-99.15, 19.50], [-99.14, 19.50], [-99.14, 19.51], [-99.15, 19.50]]],
                [[[-99.12, 19.52], [-99.11, 19.52], [-99.11, 19.53], [-99.12, 19.52]]],
            ],
        }
    )
    poly = polygon_from_nominatim_geojson(payload)
    assert isinstance(poly, MultiPolygon)
    assert len(poly.geoms) == 2


def test_empty_response_raises_clear_error():
    with pytest.raises(ValueError, match="sin resultados"):
        polygon_from_nominatim_geojson({"type": "FeatureCollection", "features": []})


def test_point_geometry_raises_clear_error():
    """Nominatim devuelve un punto si no encontro poligono; eso es un fallo,
    no un area de estudio."""
    payload = _feature({"type": "Point", "coordinates": [-99.1, 19.5]})
    with pytest.raises(ValueError, match="no es un poligono"):
        polygon_from_nominatim_geojson(payload)
