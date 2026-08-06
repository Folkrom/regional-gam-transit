import numpy as np
import pandas as pd
import pytest

from rtgam.normalize import log1p_minmax


def test_scales_to_zero_one():
    s = pd.Series([0.0, 10.0, 100.0, 1000.0])
    out = log1p_minmax(s)
    assert out.min() == pytest.approx(0.0)
    assert out.max() == pytest.approx(1.0)


def test_preserves_order():
    s = pd.Series([5.0, 1.0, 100.0, 20.0])
    out = log1p_minmax(s)
    assert out.rank().tolist() == s.rank().tolist()


def test_tames_long_tail():
    """El motivo de existir de log1p: el valor extremo no aplasta al resto.

    Con min-max crudo, 31000 sobre un maximo de 120000 daria 0.26. Con log1p
    queda por arriba de 0.85, que refleja mejor que ambas son estaciones grandes.
    """
    s = pd.Series([120_000.0, 31_000.0, 12_000.0, 6_500.0, 0.0])
    out = log1p_minmax(s)
    assert out.iloc[0] == pytest.approx(1.0)
    assert out.iloc[1] > 0.85


def test_all_zeros_returns_zeros_not_nan():
    s = pd.Series([0.0, 0.0, 0.0])
    out = log1p_minmax(s)
    assert out.tolist() == [0.0, 0.0, 0.0]
    assert not out.isna().any()


def test_single_unique_value_returns_zeros_not_nan():
    """max == min haria dividir entre cero."""
    s = pd.Series([42.0, 42.0, 42.0])
    out = log1p_minmax(s)
    assert out.tolist() == [0.0, 0.0, 0.0]
    assert not out.isna().any()


def test_negatives_are_clipped_to_zero():
    """log1p de un valor menor que -1 es NaN; ninguna variable del score
    puede ser negativa, asi que un negativo es dato sucio y se recorta."""
    s = pd.Series([-5.0, 0.0, 10.0])
    out = log1p_minmax(s)
    assert not out.isna().any()
    assert out.iloc[0] == pytest.approx(0.0)


def test_preserves_index():
    s = pd.Series([1.0, 2.0], index=pd.Index(["a", "b"], name="hex_id"))
    out = log1p_minmax(s)
    assert out.index.tolist() == ["a", "b"]
    assert out.index.name == "hex_id"


def test_empty_series_returns_empty():
    out = log1p_minmax(pd.Series([], dtype=float))
    assert len(out) == 0
