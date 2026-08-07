import pandas as pd
import pytest

from rtgam.sources.denue import to_hex_features


@pytest.fixture
def hexes():
    return pd.DataFrame(
        {"lat": [19.50, 19.70], "lon": [-99.10, -99.10]},
        index=pd.Index(["cerca", "lejos"], name="hex_id"),
    )


def _puntos(n, lat=19.50, lon=-99.10):
    return pd.DataFrame({"lat": [lat] * n, "lon": [lon] * n})


def test_devuelve_exactamente_las_dos_columnas(hexes):
    out = to_hex_features(hexes, _puntos(1), _puntos(2))
    assert list(out.columns) == ["competencia", "atractores_denue"]


def test_alineado_al_indice_del_grid(hexes):
    out = to_hex_features(hexes, _puntos(1), _puntos(2))
    assert out.index.tolist() == ["cerca", "lejos"]
    assert out.index.name == "hex_id"


def test_cuenta_establecimientos_con_decaimiento(hexes):
    """Cada establecimiento vale 1, asi que el hexagono que los contiene
    acumula su conteo. A 22 km el corte de 800 m deja exactamente cero."""
    out = to_hex_features(hexes, _puntos(3), _puntos(5))
    assert out.loc["cerca", "competencia"] == pytest.approx(3.0, rel=1e-6)
    assert out.loc["cerca", "atractores_denue"] == pytest.approx(5.0, rel=1e-6)
    assert out.loc["lejos", "competencia"] == 0.0
    assert out.loc["lejos", "atractores_denue"] == 0.0


def test_sin_establecimientos_devuelve_ceros_no_error(hexes):
    vacio = pd.DataFrame({"lat": [], "lon": []})
    out = to_hex_features(hexes, vacio, vacio)
    assert out["competencia"].tolist() == [0.0, 0.0]
    assert not out.isna().any().any()
