import pandas as pd
import pytest

from rtgam.score import merge_features


@pytest.fixture
def hexes():
    return pd.DataFrame(
        {"lat": [19.50, 19.51], "lon": [-99.10, -99.11]},
        index=pd.Index(["a", "b"], name="hex_id"),
    )


def test_merge_attaches_feature_columns(hexes):
    flow = pd.DataFrame({"flujo_transporte": [10.0, 20.0]}, index=hexes.index)
    out = merge_features(hexes, [flow])
    assert list(out.columns) == ["flujo_transporte"]
    assert out.loc["b", "flujo_transporte"] == 20.0


def test_merge_drops_lat_lon(hexes):
    """La geometria se regenera de hex_id; guardarla duplica y arriesga
    que se desincronice."""
    flow = pd.DataFrame({"flujo_transporte": [10.0, 20.0]}, index=hexes.index)
    out = merge_features(hexes, [flow])
    assert "lat" not in out.columns
    assert "lon" not in out.columns


def test_merge_multiple_sources(hexes):
    flow = pd.DataFrame({"flujo_transporte": [10.0, 20.0]}, index=hexes.index)
    comp = pd.DataFrame({"competencia": [1.0, 5.0]}, index=hexes.index)
    out = merge_features(hexes, [flow, comp])
    assert set(out.columns) == {"flujo_transporte", "competencia"}


def test_merge_keeps_all_hexes_filling_missing_with_zero(hexes):
    """Una fuente puede cubrir solo parte de GAM; los huecos son cero, no NaN."""
    partial = pd.DataFrame({"flujo_transporte": [10.0]}, index=pd.Index(["a"], name="hex_id"))
    out = merge_features(hexes, [partial])
    assert len(out) == 2
    assert out.loc["b", "flujo_transporte"] == 0.0
    assert not out.isna().any().any()


def test_merge_with_no_sources_returns_empty_columns(hexes):
    out = merge_features(hexes, [])
    assert len(out) == 2
    assert list(out.columns) == []
