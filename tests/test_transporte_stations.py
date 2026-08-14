import json
import time

import pytest
import requests

from rtgam.sources.transporte import (
    fetch_stations,
    normalize_name,
    station_class,
    stations_from_overpass,
)


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
    assert list(df.columns) == ["osm_name", "lat", "lon", "osm_class"]
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
    assert list(df.columns) == ["osm_name", "lat", "lon", "osm_class"]


def test_station_class_aerialway_es_cable():
    assert station_class({"aerialway": "station"}) == "cable"


def test_station_class_railway_es_riel():
    assert station_class({"railway": "station"}) == "riel"


def test_station_class_solo_public_transport_no_clasifica():
    # Los CETRAM, los paraderos de RTP y las terminales foraneas traen solo
    # esta etiqueta. Un paradero de camion no es una estacion.
    assert station_class({"public_transport": "station"}) is None


def test_station_class_cable_gana_a_riel():
    # Ninguna estacion real de GAM trae las dos, pero la regla tiene que ser
    # determinista igual, no depender del orden en que se lean las llaves.
    tags = {"aerialway": "station", "railway": "station"}
    assert station_class(tags) == "cable"


def test_station_class_riel_gana_a_public_transport():
    tags = {"public_transport": "station", "railway": "station"}
    assert station_class(tags) == "riel"


def test_station_class_sin_etiquetas_no_clasifica():
    assert station_class({}) is None
    assert station_class({"railway": "halt"}) is None


def test_la_clase_sale_de_todos_los_elementos_del_mismo_nombre():
    # El elemento generico va PRIMERO y sobrevive al dedup. Si la clase
    # saliera del sobreviviente, esta estacion de Metro quedaria sin
    # clasificar y desapareceria de la presencia sin que fallara nada.
    payload = {
        "elements": [
            {
                "tags": {"name": "Potrero", "public_transport": "station"},
                "lat": 19.50,
                "lon": -99.13,
            },
            {
                "tags": {"name": "Potrero", "railway": "station"},
                "lat": 19.51,
                "lon": -99.14,
            },
        ]
    }
    out = stations_from_overpass(payload)
    assert len(out) == 1
    assert out.loc[0, "osm_class"] == "riel"
    # Las coordenadas siguen siendo las del primero: flujo_transporte no
    # puede moverse por este cambio.
    assert out.loc[0, "lat"] == pytest.approx(19.50)


def test_una_estacion_sin_clase_queda_con_osm_class_nulo():
    payload = {
        "elements": [
            {
                "tags": {"name": "CETRAM Indios Verdes", "public_transport": "station"},
                "lat": 19.49,
                "lon": -99.12,
            }
        ]
    }
    out = stations_from_overpass(payload)
    assert len(out) == 1
    assert out.loc[0, "osm_class"] is None


BBOX = (19.4, -99.2, 19.6, -99.0)


def test_fetch_stations_uses_cache_without_touching_network(tmp_path, monkeypatch):
    cache = tmp_path / "osm_stations.json"
    cache.write_text(
        json.dumps(
            {"elements": [
                {"type": "node", "id": 1, "lat": 19.5, "lon": -99.1,
                 "tags": {"name": "Potrero"}}
            ]}
        ),
        encoding="utf-8",
    )

    def explode(*args, **kwargs):
        raise AssertionError("no debe tocar la red habiendo cache")

    monkeypatch.setattr(requests, "post", explode)

    df = fetch_stations(BBOX, cache)
    assert len(df) == 1
    assert df.iloc[0]["osm_name"] == "Potrero"


def test_fetch_stations_corrupt_cache_names_file_and_remedy(tmp_path):
    cache = tmp_path / "osm_stations.json"
    cache.write_text("no soy json", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupta o truncada"):
        fetch_stations(BBOX, cache)


def test_fetch_stations_raises_instead_of_returning_none(tmp_path, monkeypatch):
    """Agotar los reintentos debe lanzar, no devolver None.

    Task 8 espera un DataFrame; un None ahi reventaria mucho mas lejos del
    origen real del problema.
    """
    cache = tmp_path / "osm_stations.json"
    calls = []

    def always_fail(*args, **kwargs):
        calls.append(1)
        raise requests.ConnectionError("sin red")

    monkeypatch.setattr(requests, "post", always_fail)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="3 intentos"):
        fetch_stations(BBOX, cache)
    assert len(calls) == 3
    assert not cache.exists(), "sin respuesta valida no debe quedar cache escrita"


def test_fetch_stations_sends_a_user_agent(tmp_path, monkeypatch):
    """Overpass responde 406 a las peticiones sin User-Agent identificable.

    Verificado contra el servidor real: sin el header devuelve 406 Not
    Acceptable; con el, 200. Es su politica de uso, no un detalle opcional.
    """
    cache = tmp_path / "osm_stations.json"
    seen = {}

    class Ok:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"elements": []}

    def capture(*args, **kwargs):
        seen.update(kwargs.get("headers") or {})
        return Ok()

    monkeypatch.setattr(requests, "post", capture)
    fetch_stations(BBOX, cache)
    assert "User-Agent" in seen
    assert seen["User-Agent"], "el User-Agent no puede ir vacio"


def test_fetch_stations_does_not_retry_a_client_error(tmp_path, monkeypatch):
    """Un 400 es consulta malformada: fallar rapido, no machacar el servidor."""
    cache = tmp_path / "osm_stations.json"
    calls = []

    class BadRequest:
        status_code = 400

        def raise_for_status(self):
            raise requests.HTTPError("400 Bad Request", response=self)

    def one_shot(*args, **kwargs):
        calls.append(1)
        return BadRequest()

    monkeypatch.setattr(requests, "post", one_shot)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    with pytest.raises(requests.HTTPError):
        fetch_stations(BBOX, cache)
    assert len(calls) == 1, "un 400 no se reintenta"
