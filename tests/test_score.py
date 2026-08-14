import pandas as pd
import pytest

from rtgam.score import compute_score, load_weights


@pytest.fixture
def features():
    return pd.DataFrame(
        {
            "flujo_transporte": [0.0, 100.0, 1000.0],
            "competencia": [0.0, 0.0, 50.0],
        },
        index=pd.Index(["a", "b", "c"], name="hex_id"),
    )


def test_produces_norm_columns_and_score(features):
    out = compute_score(features, {"flujo_transporte": 1.0, "competencia": -1.0})
    assert "flujo_transporte_norm" in out.columns
    assert "competencia_norm" in out.columns
    assert "score" in out.columns
    assert out.index.tolist() == ["a", "b", "c"]


def test_competition_subtracts(features):
    """Con el mismo flujo, mas competencia debe bajar el score."""
    rival = features.copy()
    rival.loc["c", "flujo_transporte"] = 100.0  # empata con 'b'
    out = compute_score(rival, {"flujo_transporte": 1.0, "competencia": -1.0})
    assert out.loc["c", "score"] < out.loc["b", "score"]


def test_missing_columns_are_skipped_not_errors(features):
    """99_score.py corre con las fuentes que existan; las que faltan se ignoran."""
    weights = {"flujo_transporte": 1.0, "densidad_pob": 0.5, "competencia": -1.0}
    out = compute_score(features, weights)
    assert "densidad_pob_norm" not in out.columns
    assert "score" in out.columns
    assert not out["score"].isna().any()


def test_empty_hex_does_not_win(features):
    out = compute_score(features, {"flujo_transporte": 1.0, "competencia": -1.0})
    assert out["score"].idxmax() != "a"


def test_weight_of_zero_removes_influence(features):
    out = compute_score(features, {"flujo_transporte": 0.0, "competencia": -1.0})
    assert out.loc["a", "score"] == pytest.approx(out.loc["b", "score"])


def test_load_weights_reads_config_file():
    weights = load_weights()
    assert weights["flujo_transporte"] == 0.25
    assert weights["presencia_transporte"] == 0.10
    assert weights["competencia"] == -0.10
    assert weights["competencia"] < 0, "la competencia debe restar"


def test_load_weights_covers_every_spec_variable():
    weights = load_weights()
    expected = {
        "flujo_transporte",
        "presencia_transporte",
        "densidad_pob",
        "nivel_socioeconomico",
        "accesibilidad_peatonal",
        "atractores_denue",
        "atractores_osm",
        "competencia",
    }
    assert set(weights) == expected
