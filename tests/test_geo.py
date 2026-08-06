import numpy as np
import pytest
from shapely.geometry import Polygon

from rtgam.geo import haversine_m, hex_centroids, hexes_for_polygon


def test_haversine_zero_distance():
    assert haversine_m(19.5, -99.1, 19.5, -99.1) == pytest.approx(0.0, abs=1e-6)


def test_haversine_known_distance():
    """Un grado de latitud son ~111.2 km en cualquier meridiano."""
    d = haversine_m(19.0, -99.1, 20.0, -99.1)
    assert d == pytest.approx(111_195, rel=0.001)


def test_haversine_broadcasts():
    """La matriz hexagonos x puntos depende de este broadcasting."""
    lats = np.array([[19.5], [19.6]])
    lons = np.array([[-99.1], [-99.1]])
    plats = np.array([[19.5, 19.6]])
    plons = np.array([[-99.1, -99.1]])
    d = haversine_m(lats, lons, plats, plons)
    assert d.shape == (2, 2)
    assert d[0, 0] == pytest.approx(0.0, abs=1e-6)
    assert d[1, 1] == pytest.approx(0.0, abs=1e-6)


def test_hexes_for_polygon_returns_res9_cells():
    poly = Polygon(
        [(-99.15, 19.50), (-99.10, 19.50), (-99.10, 19.55), (-99.15, 19.55)]
    )
    cells = hexes_for_polygon(poly, resolution=9)
    assert len(cells) > 100
    assert all(isinstance(c, str) for c in cells)


def test_hex_centroids_indexed_and_sorted():
    poly = Polygon(
        [(-99.15, 19.50), (-99.14, 19.50), (-99.14, 19.51), (-99.15, 19.51)]
    )
    cells = hexes_for_polygon(poly, resolution=9)
    df = hex_centroids(cells)
    assert df.index.name == "hex_id"
    assert list(df.columns) == ["lat", "lon"]
    assert len(df) == len(cells)
    assert list(df.index) == sorted(cells)
    # Los centroides caen dentro del area de interes.
    assert df["lat"].between(19.49, 19.52).all()
    assert df["lon"].between(-99.16, -99.13).all()
