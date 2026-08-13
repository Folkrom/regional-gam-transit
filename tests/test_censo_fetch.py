"""Descarga del censo y de los poligonos, con cache y validacion."""

import io
import json
import zipfile

import pytest
import requests

from rtgam import USER_AGENT
from rtgam.sources import censo


class RespuestaFalsa:
    def __init__(self, content=b"", payload=None, status=200):
        self.content = content
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"status {self.status_code}")
            error.response = self
            raise error

    def json(self):
        if self._payload is None:
            raise ValueError("no es json")
        return self._payload


def zip_del_censo(filas="MUN,AGEB,MZA,POBTOT\n005,0012,000,100\n"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("x/diccionario_de_datos/diccionario.csv", "a,b\n1,2\n")
        zf.writestr("x/conjunto_de_datos/datos.csv", filas)
    return buffer.getvalue()


def geojson_de(features):
    return {"type": "FeatureCollection", "features": features}


def feature(cve_ageb, cve_mun="005"):
    return {
        "type": "Feature",
        "properties": {"CVE_AGEB": cve_ageb, "CVE_MUN": cve_mun},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        },
    }


def test_los_poligonos_se_filtran_a_gam():
    payload = geojson_de([feature("0012"), feature("1716", cve_mun="010")])
    polygons = censo.polygons_from_geojson(payload)
    assert set(polygons) == {"0012"}


def test_un_geojson_sin_features_lanza_y_no_se_cachea(tmp_path, monkeypatch):
    cache = tmp_path / "ageb.geojson"
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: RespuestaFalsa(payload={"type": "X"})
    )
    with pytest.raises(ValueError):
        censo.fetch_ageb_polygons(cache)
    assert not cache.exists(), "un payload inservible no se persiste"


def test_un_geojson_sin_ageb_de_gam_lanza(tmp_path, monkeypatch):
    # Si la CDMX cambia la clave de alcaldia, GAM saldria vacia y las dos
    # columnas en cero sin que nada fallara.
    payload = geojson_de([feature("1716", cve_mun="010")])
    monkeypatch.setattr(requests, "get", lambda *a, **k: RespuestaFalsa(payload=payload))
    with pytest.raises(ValueError, match="GAM"):
        censo.fetch_ageb_polygons(tmp_path / "ageb.geojson")


def test_la_peticion_del_geojson_manda_el_user_agent(tmp_path, monkeypatch):
    vistos = {}

    def falso_get(url, **kwargs):
        vistos.update(kwargs)
        return RespuestaFalsa(payload=geojson_de([feature("0012")]))

    monkeypatch.setattr(requests, "get", falso_get)
    censo.fetch_ageb_polygons(tmp_path / "ageb.geojson")
    assert vistos["headers"]["User-Agent"] == USER_AGENT


def test_el_geojson_valido_si_se_cachea_y_se_relee(tmp_path, monkeypatch):
    cache = tmp_path / "ageb.geojson"
    payload = geojson_de([feature("0012")])
    monkeypatch.setattr(requests, "get", lambda *a, **k: RespuestaFalsa(payload=payload))
    censo.fetch_ageb_polygons(cache)
    assert cache.exists()

    def no_llamar(*a, **k):
        raise AssertionError("con cache no debe volver a descargar")

    monkeypatch.setattr(requests, "get", no_llamar)
    polygons = censo.fetch_ageb_polygons(cache)
    assert set(polygons) == {"0012"}


def test_force_vuelve_a_descargar_aunque_haya_cache(tmp_path, monkeypatch):
    cache = tmp_path / "ageb.geojson"
    cache.write_text(json.dumps(geojson_de([feature("9999")])), encoding="utf-8")
    payload = geojson_de([feature("0012")])
    monkeypatch.setattr(requests, "get", lambda *a, **k: RespuestaFalsa(payload=payload))
    polygons = censo.fetch_ageb_polygons(cache, force=True)
    assert set(polygons) == {"0012"}


def test_una_cache_de_geojson_corrupta_lanza_con_instrucciones(tmp_path):
    cache = tmp_path / "ageb.geojson"
    cache.write_text("{no es json", encoding="utf-8")
    with pytest.raises(ValueError, match="force"):
        censo.fetch_ageb_polygons(cache)


def test_el_censo_lee_el_csv_de_conjunto_de_datos_no_el_diccionario(
    tmp_path, monkeypatch
):
    # El zip trae tres CSV y, alfabeticamente, diccionario_de_datos va ANTES
    # que conjunto_de_datos. Tomar el primero devuelve el diccionario.
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: RespuestaFalsa(content=zip_del_censo())
    )
    frame = censo.fetch_censo(tmp_path)
    assert "POBTOT" in frame.columns


def test_el_censo_se_lee_como_texto_para_no_perder_las_claves(tmp_path, monkeypatch):
    # "0012" leido como numero se vuelve 12 y deja de cruzar con la geometria.
    filas = "MUN,AGEB,MZA,POBTOT\n005,0012,000,100\n"
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: RespuestaFalsa(content=zip_del_censo(filas))
    )
    frame = censo.fetch_censo(tmp_path)
    assert frame.loc[0, "AGEB"] == "0012"


def test_un_zip_del_censo_invalido_no_deja_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: RespuestaFalsa(content=b"esto no es un zip")
    )
    with pytest.raises(ValueError):
        censo.fetch_censo(tmp_path)
    assert not (tmp_path / "censo_ageb_09.zip").exists()


def test_la_peticion_del_censo_manda_el_user_agent(tmp_path, monkeypatch):
    vistos = {}

    def falso_get(url, **kwargs):
        vistos.update(kwargs)
        return RespuestaFalsa(content=zip_del_censo())

    monkeypatch.setattr(requests, "get", falso_get)
    censo.fetch_censo(tmp_path)
    assert vistos["headers"]["User-Agent"] == USER_AGENT
