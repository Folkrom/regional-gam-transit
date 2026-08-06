import numpy as np
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


def test_merge_raises_on_nan_from_a_source(hexes):
    """Un NaN de la fuente no es un hueco del join.

    Rellenar los dos con cero esconde un bug de datos detras de un valor que
    parece legitimo, y ese cero entra al score sin que nada avise.
    """
    sucia = pd.DataFrame({"flujo_transporte": [10.0, np.nan]}, index=hexes.index)
    with pytest.raises(ValueError, match="NaN"):
        merge_features(hexes, [sucia])


def test_merge_ignores_hexes_outside_the_grid(hexes):
    """Una fuente con hexagonos ajenos no debe agrandar la malla."""
    ajena = pd.DataFrame(
        {"flujo_transporte": [1.0, 2.0, 99.0]},
        index=pd.Index(["a", "b", "fuera_de_gam"], name="hex_id"),
    )
    out = merge_features(hexes, [ajena])
    assert len(out) == 2
    assert "fuera_de_gam" not in out.index


def test_merge_with_no_sources_returns_empty_columns(hexes):
    out = merge_features(hexes, [])
    assert len(out) == 2
    assert list(out.columns) == []
