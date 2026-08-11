"""Descarga desde Overpass: consultas, validacion y cache."""

import json

import pytest
import requests

from rtgam.sources.osm import (
    build_attractor_query,
    build_network_query,
    fetch_overpass,
    validate_payload,
)

BBOX = (19.4448, -99.1770, 19.5928, -99.0509)


def test_la_consulta_de_red_excluye_las_vias_rapidas():
    query = build_network_query(BBOX)
    assert "motorway" in query
    assert "trunk" in query
    # El bbox va en el orden de Overpass: sur, oeste, norte, este.
    assert "19.4448,-99.177,19.5928,-99.0509" in query.replace(" ", "")


def test_la_consulta_de_atractores_pide_nwr_no_solo_way():
    # El Bosque de San Juan de Aragon existe SOLO como relation. Una consulta
    # de puros `way` lo pierde sin lanzar nada, que es la firma de bug que mas
    # ha costado en este proyecto.
    query = build_attractor_query(BBOX)
    assert "nwr" in query
    assert "way[" not in query
    assert "out tags center" in query


def test_la_consulta_de_atractores_no_pide_suelo_de_conservacion():
    query = build_attractor_query(BBOX)
    assert "nature_reserve" not in query
    assert "protected_area" not in query


def test_un_payload_sin_elements_lanza():
    with pytest.raises(ValueError, match="elements"):
        validate_payload({"version": 0.6})


def test_un_remark_de_error_lanza():
    # Overpass a veces responde 200 con JSON valido, elements vacio y el error
    # metido en `remark`. Cachear eso envenena todas las corridas siguientes.
    payload = {"elements": [], "remark": "runtime error: Query timed out"}
    with pytest.raises(ValueError, match="remark"):
        validate_payload(payload)


def test_un_payload_bueno_pasa_tal_cual():
    payload = {"elements": [{"type": "node", "id": 1}]}
    assert validate_payload(payload) is payload


def test_un_cuerpo_html_con_status_200_no_deja_cache(tmp_path, monkeypatch):
    """Overpass saturado responde 200 con HTML. raise_for_status no lo ve."""

    class RespuestaHtml:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    def falso_post(*args, **kwargs):
        return RespuestaHtml()

    monkeypatch.setattr("rtgam.sources.osm.requests.post", falso_post)
    monkeypatch.setattr("rtgam.sources.osm.time.sleep", lambda _s: None)

    cache = tmp_path / "osm.json"
    with pytest.raises(RuntimeError):
        fetch_overpass("[out:json];out count;", cache)

    assert not cache.exists(), "no debe quedar cache de una respuesta inservible"


def test_una_cache_valida_no_toca_la_red(tmp_path, monkeypatch):
    def explota(*args, **kwargs):
        raise AssertionError("no deberia pedir nada a la red")

    monkeypatch.setattr("rtgam.sources.osm.requests.post", explota)

    cache = tmp_path / "osm.json"
    cache.write_text(json.dumps({"elements": [{"type": "node", "id": 7}]}))

    payload = fetch_overpass("[out:json];out count;", cache)
    assert payload["elements"][0]["id"] == 7


def test_una_cache_corrupta_lanza_con_el_remedio(tmp_path):
    cache = tmp_path / "osm.json"
    cache.write_text("{esto no es json")
    with pytest.raises(ValueError, match="--force"):
        fetch_overpass("[out:json];out count;", cache)


def test_un_400_se_propaga_sin_reintentar(tmp_path, monkeypatch):
    """Un error 4xx propio (excepto 429) se propaga sin reintentar."""

    class Respuesta400:
        status_code = 400

        def raise_for_status(self):
            error = requests.HTTPError()
            error.response = self
            raise error

    post_call_count = 0

    def falso_post(*args, **kwargs):
        nonlocal post_call_count
        post_call_count += 1
        return Respuesta400()

    monkeypatch.setattr("rtgam.sources.osm.requests.post", falso_post)

    cache = tmp_path / "osm.json"
    with pytest.raises(requests.HTTPError):
        fetch_overpass("[out:json];out count;", cache)

    # Se intenta una sola vez (1 espejo antes de fallar)
    assert post_call_count == 1, f"Esperaba 1 llamada a post para 400, got {post_call_count}"


def test_un_429_reintenta_hasta_agotar(tmp_path, monkeypatch):
    """Un error 429 se reintenta hasta agotar OVERPASS_RETRIES * OVERPASS_URLS."""

    class Respuesta429:
        status_code = 429

        def raise_for_status(self):
            error = requests.HTTPError()
            error.response = self
            raise error

    post_call_count = 0
    sleep_call_count = 0

    def falso_post(*args, **kwargs):
        nonlocal post_call_count
        post_call_count += 1
        return Respuesta429()

    def falso_sleep(_s):
        nonlocal sleep_call_count
        sleep_call_count += 1

    monkeypatch.setattr("rtgam.sources.osm.requests.post", falso_post)
    monkeypatch.setattr("rtgam.sources.osm.time.sleep", falso_sleep)

    cache = tmp_path / "osm.json"
    with pytest.raises(RuntimeError, match="fallo tras"):
        fetch_overpass("[out:json];out count;", cache)

    # 3 intentos × 2 espejos = 6 llamadas a post
    assert post_call_count == 6, f"Esperaba 6 llamadas a post (3 intentos × 2 espejos), got {post_call_count}"

    # 2 llamadas a sleep (despues del intento 0 y 1, no despues del 2)
    assert sleep_call_count == 2, f"Esperaba 2 llamadas a sleep (entre intentos), got {sleep_call_count}"
