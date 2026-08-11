"""Contrato de la fuente OSM: exactamente dos columnas, crudas y sin NaN."""

import pandas as pd
import pytest

from rtgam.sources.osm import to_hex_features


def hexes():
    frame = pd.DataFrame(
        [("h1", 19.5000, -99.1000), ("h2", 19.5200, -99.1200)],
        columns=["hex_id", "lat", "lon"],
    )
    return frame.set_index("hex_id")


def test_devuelve_exactamente_las_dos_columnas_de_esta_fuente():
    features = to_hex_features(
        hexes(),
        pd.Series([100.0, 200.0], index=["h1", "h2"]),
        pd.DataFrame(columns=["osm_kind", "name", "lat", "lon"]),
    )
    assert list(features.columns) == ["accesibilidad_peatonal", "atractores_osm"]
    assert list(features.index) == ["h1", "h2"]


def test_el_alcance_pasa_crudo_sin_normalizar():
    # La normalizacion ocurre una sola vez, en 99_score.py. Si esta fuente
    # normalizara, el score la contaria dos veces.
    features = to_hex_features(
        hexes(),
        pd.Series([1234.5, 0.0], index=["h1", "h2"]),
        pd.DataFrame(columns=["osm_kind", "name", "lat", "lon"]),
    )
    assert features.loc["h1", "accesibilidad_peatonal"] == pytest.approx(1234.5)


def test_cada_atractor_vale_uno():
    # Un atractor encima del centroide de h1 aporta exp(0) = 1.
    atractores = pd.DataFrame(
        [("park", "Parque", 19.5000, -99.1000)],
        columns=["osm_kind", "name", "lat", "lon"],
    )
    features = to_hex_features(
        hexes(), pd.Series([0.0, 0.0], index=["h1", "h2"]), atractores
    )
    assert features.loc["h1", "atractores_osm"] == pytest.approx(1.0, abs=0.01)


def test_un_atractor_lejano_no_aporta():
    # ~0.05 grados de latitud son ~5.5 km, muy pasado el corte de 800 m.
    atractores = pd.DataFrame(
        [("park", "Lejano", 19.5500, -99.1000)],
        columns=["osm_kind", "name", "lat", "lon"],
    )
    features = to_hex_features(
        hexes(), pd.Series([0.0, 0.0], index=["h1", "h2"]), atractores
    )
    assert features["atractores_osm"].sum() == pytest.approx(0.0)


def test_sin_atractores_da_ceros_y_no_nan():
    features = to_hex_features(
        hexes(),
        pd.Series([0.0, 0.0], index=["h1", "h2"]),
        pd.DataFrame(columns=["osm_kind", "name", "lat", "lon"]),
    )
    assert not features.isna().any().any()


def test_un_alcance_desalineado_lanza():
    # Reindexar en silencio convertiria un bug de indice en ceros plausibles.
    # merge_features ya aprendio esta leccion: hueco de join y cero real no son
    # lo mismo.
    with pytest.raises(ValueError, match="indice"):
        to_hex_features(
            hexes(),
            pd.Series([100.0], index=["h1"]),
            pd.DataFrame(columns=["osm_kind", "name", "lat", "lon"]),
        )
