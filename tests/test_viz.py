import pandas as pd
import pytest

from rtgam.viz import hex_polygon_latlon, rescore


def test_polygon_has_six_vertices():
    """Un hexagono H3 tiene 6 lados; solo los pentagonos de la esfera tienen 5,
    y ninguno cae en CDMX."""
    verts = hex_polygon_latlon("894995aa653ffff")
    assert len(verts) == 6


def test_polygon_is_lat_lon_order_for_folium():
    """Folium espera (lat, lon). h3.cell_to_boundary ya devuelve ese orden,
    pero conviene fijarlo con una prueba para que nadie lo 'arregle'."""
    verts = hex_polygon_latlon("894995aa653ffff")
    lat, lon = verts[0]
    assert 19.0 < lat < 20.0, "la latitud de CDMX ronda 19.x"
    assert -100.0 < lon < -98.0, "la longitud de CDMX ronda -99.x"


def test_rescore_uses_normalized_columns():
    scores = pd.DataFrame(
        {"flujo_transporte_norm": [0.0, 1.0], "competencia_norm": [0.0, 1.0], "score": [0.0, 0.25]},
        index=pd.Index(["a", "b"], name="hex_id"),
    )
    out = rescore(scores, {"flujo_transporte": 1.0, "competencia": -1.0})
    assert out["a"] == pytest.approx(0.0)
    assert out["b"] == pytest.approx(0.0)


def test_rescore_reacts_to_weight_change():
    scores = pd.DataFrame(
        {"flujo_transporte_norm": [0.5], "competencia_norm": [0.0], "score": [0.175]},
        index=pd.Index(["a"], name="hex_id"),
    )
    assert rescore(scores, {"flujo_transporte": 1.0})["a"] == pytest.approx(0.5)
    assert rescore(scores, {"flujo_transporte": 2.0})["a"] == pytest.approx(1.0)


def test_rescore_ignores_weights_without_norm_column():
    scores = pd.DataFrame(
        {"flujo_transporte_norm": [0.5], "score": [0.175]},
        index=pd.Index(["a"], name="hex_id"),
    )
    out = rescore(scores, {"flujo_transporte": 1.0, "densidad_pob": 5.0})
    assert out["a"] == pytest.approx(0.5)
