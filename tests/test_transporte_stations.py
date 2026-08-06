import pytest

from rtgam.sources.transporte import normalize_name, stations_from_overpass


def test_normalize_strips_accents_and_case():
    assert normalize_name("Instituto del Petróleo") == "instituto del petroleo"


def test_normalize_strips_punctuation_and_collapses_spaces():
    assert normalize_name("La Villa-Basílica") == "la villa basilica"
    assert normalize_name("  Martín   Carrera ") == "martin carrera"


def test_parses_nodes_with_lat_lon():
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 19.50, "lon": -99.10, "tags": {"name": "Potrero"}},
        ]
    }
    df = stations_from_overpass(payload)
    assert list(df.columns) == ["osm_name", "lat", "lon"]
    assert df.iloc[0]["osm_name"] == "Potrero"
    assert df.iloc[0]["lat"] == 19.50


def test_parses_ways_using_center():
    """Overpass devuelve `center` en vez de lat/lon para ways y relations."""
    payload = {
        "elements": [
            {"type": "way", "id": 2, "center": {"lat": 19.51, "lon": -99.11}, "tags": {"name": "La Raza"}},
        ]
    }
    df = stations_from_overpass(payload)
    assert len(df) == 1
    assert df.iloc[0]["lat"] == 19.51


def test_skips_elements_without_name():
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 19.50, "lon": -99.10, "tags": {}},
            {"type": "node", "id": 2, "lat": 19.51, "lon": -99.11, "tags": {"name": "Potrero"}},
        ]
    }
    df = stations_from_overpass(payload)
    assert len(df) == 1
    assert df.iloc[0]["osm_name"] == "Potrero"


def test_skips_elements_without_coordinates():
    payload = {"elements": [{"type": "relation", "id": 3, "tags": {"name": "Sin geometria"}}]}
    assert len(stations_from_overpass(payload)) == 0


def test_deduplicates_by_name_keeping_first():
    """OSM suele tener un nodo y un way para la misma estacion."""
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 19.50, "lon": -99.10, "tags": {"name": "Potrero"}},
            {"type": "way", "id": 2, "center": {"lat": 19.5001, "lon": -99.1001}, "tags": {"name": "Potrero"}},
        ]
    }
    df = stations_from_overpass(payload)
    assert len(df) == 1
    assert df.iloc[0]["lat"] == 19.50


def test_empty_payload_returns_empty_frame_with_columns():
    df = stations_from_overpass({"elements": []})
    assert len(df) == 0
    assert list(df.columns) == ["osm_name", "lat", "lon"]
