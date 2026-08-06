import pandas as pd
import pytest

from rtgam.sources.transporte import (
    fix_mojibake,
    normalize_name,
    propose_name_map,
    to_hex_features,
    weekday_mean_by_station,
)


def test_weekday_mean_sums_lines_before_averaging_days():
    """Una estacion de transbordo aparece una vez por linea el mismo dia.

    Promediar directo la parte a la mitad. Medido sobre los datos reales:
    Martin Carrera (lineas 4 y 6) daba 24,305 en vez de 48,609.
    """
    rows = []
    for fecha in ["2025-01-06", "2025-01-07"]:
        rows.append({"fecha": fecha, "estacion": "Martín Carrera", "linea": "Linea 4", "afluencia": 300})
        rows.append({"fecha": fecha, "estacion": "Martín Carrera", "linea": "Linea 6", "afluencia": 200})
        rows.append({"fecha": fecha, "estacion": "Potrero", "linea": "Linea 3", "afluencia": 100})
    out = weekday_mean_by_station(
        pd.DataFrame(rows), year=2025, date_col="fecha",
        station_col="estacion", value_col="afluencia",
    ).set_index("afluencia_name")
    assert out.loc["Martín Carrera", "afluencia_habil"] == pytest.approx(500.0)
    assert out.loc["Potrero", "afluencia_habil"] == pytest.approx(100.0)


@pytest.fixture
def daily():
    """2025-01-06 a 2025-01-12: lunes a domingo."""
    dates = pd.date_range("2025-01-06", "2025-01-12", freq="D")
    rows = []
    for date in dates:
        weekday = date.weekday() < 5
        rows.append({"fecha": date.strftime("%Y-%m-%d"), "estacion": "Potrero", "afluencia": 1000 if weekday else 200})
        rows.append({"fecha": date.strftime("%Y-%m-%d"), "estacion": "La Raza", "afluencia": 500 if weekday else 100})
    return pd.DataFrame(rows)


def test_fix_mojibake_restores_accents():
    assert fix_mojibake("AragÃ³n") == "Aragón"
    assert fix_mojibake("Instituto del PetrÃ³leo") == "Instituto del Petróleo"


def test_fix_mojibake_leaves_clean_names_alone():
    """Idempotente: un nombre ya correcto no se debe estropear."""
    assert fix_mojibake("Potrero") == "Potrero"
    assert fix_mojibake("La Raza") == "La Raza"


def test_mojibake_breaks_the_join_without_the_fix():
    """La razon de existir de fix_mojibake, fijada como prueba."""
    roto = "AragÃ³n"
    assert normalize_name(roto) != normalize_name("Aragón")
    assert normalize_name(fix_mojibake(roto)) == normalize_name("Aragón")


def test_weekday_mean_excludes_weekend(daily):
    out = weekday_mean_by_station(daily, year=2025, date_col="fecha", station_col="estacion", value_col="afluencia")
    potrero = out.set_index("afluencia_name").loc["Potrero", "afluencia_habil"]
    assert potrero == pytest.approx(1000.0), "el fin de semana no debe promediarse"


def test_weekday_mean_one_row_per_station(daily):
    out = weekday_mean_by_station(daily, year=2025, date_col="fecha", station_col="estacion", value_col="afluencia")
    assert len(out) == 2
    assert list(out.columns) == ["afluencia_name", "afluencia_habil"]


def test_weekday_mean_filters_by_year(daily):
    other = daily.copy()
    other["fecha"] = other["fecha"].str.replace("2025", "2024")
    combined = pd.concat([daily, other], ignore_index=True)
    out = weekday_mean_by_station(combined, year=2025, date_col="fecha", station_col="estacion", value_col="afluencia")
    assert len(out) == 2


def test_name_map_matches_exact():
    out = propose_name_map(["Potrero"], ["Potrero"])
    assert out.iloc[0]["osm_name"] == "Potrero"
    assert out.iloc[0]["similarity"] == pytest.approx(1.0)


def test_name_map_matches_across_accents():
    out = propose_name_map(["Instituto del Petroleo"], ["Instituto del Petróleo"])
    assert out.iloc[0]["osm_name"] == "Instituto del Petróleo"


def test_name_map_does_not_guess_partial_names():
    """Un nombre que no es identico queda para revision, con candidatos.

    Medido contra los datos reales: 23 de 25 estaciones clave de GAM cruzan
    exacto, y los unicos cruces que aportaba la heuristica eran falsos.
    """
    out = propose_name_map(["Deportivo 18 de Marzo"], ["18 de Marzo"])
    assert out.iloc[0]["osm_name"] is None
    assert "18 de Marzo" in out.iloc[0]["candidatos"]


def test_name_map_rejects_unrelated_stations():
    """El bug que motivo esta regla, fijado como prueba.

    Con el cutoff viejo de 0.6, Obrera (linea 8, Cuauhtemoc) cruzaba con
    Potrero (GAM) y Zapata (Benito Juarez) con La Pastora (GAM). La afluencia
    de media ciudad aterrizaba en hexagonos de GAM sin que nada fallara.
    """
    out = propose_name_map(["Obrera", "Zapata"], ["Potrero", "La Pastora"])
    assert out.set_index("afluencia_name").loc["Obrera", "osm_name"] is None
    assert out.set_index("afluencia_name").loc["Zapata", "osm_name"] is None


def test_name_map_exact_wins_over_similar_neighbours():
    """Aragon, Bosque de Aragon y Villa de Aragon son tres estaciones reales."""
    osm = ["Aragón", "Bosque de Aragón", "Villa de Aragón"]
    out = propose_name_map(["Aragón"], osm).set_index("afluencia_name")
    assert out.loc["Aragón", "osm_name"] == "Aragón"
    assert out.loc["Aragón", "similarity"] == 1.0


def test_name_map_does_not_match_substring_of_another_station():
    """"tlahuac" es subcadena de "cuitlahuac" por pura coincidencia."""
    out = propose_name_map(["Tláhuac"], ["Cuitláhuac"])
    assert out.iloc[0]["osm_name"] is None


def test_name_map_leaves_unmatched_as_none():
    out = propose_name_map(["Estacion Inventada XYZ"], ["Potrero"])
    assert out.iloc[0]["osm_name"] is None


def test_to_hex_features_produces_single_column():
    hexes = pd.DataFrame(
        {"lat": [19.50, 19.70], "lon": [-99.10, -99.10]},
        index=pd.Index(["a", "b"], name="hex_id"),
    )
    stations = pd.DataFrame({"lat": [19.50], "lon": [-99.10], "afluencia_habil": [1000.0]})
    out = to_hex_features(hexes, stations)
    assert list(out.columns) == ["flujo_transporte"]
    assert out.index.tolist() == ["a", "b"]
    assert out.loc["a", "flujo_transporte"] == pytest.approx(1000.0, rel=1e-6)
    assert out.loc["b", "flujo_transporte"] == 0.0


def test_to_hex_features_with_no_stations_returns_zeros():
    hexes = pd.DataFrame({"lat": [19.50], "lon": [-99.10]}, index=pd.Index(["a"], name="hex_id"))
    stations = pd.DataFrame({"lat": [], "lon": [], "afluencia_habil": []})
    out = to_hex_features(hexes, stations)
    assert out.loc["a", "flujo_transporte"] == 0.0
