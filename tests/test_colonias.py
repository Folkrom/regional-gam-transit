import json

import pandas as pd
import pytest

from rtgam.colonias import (
    GAM_NOMDT,
    SIN_COLONIA,
    assign_colonia,
    colonias_from_geojson,
    fetch_colonias,
)


def _cuadro(x0, y0, x1, y1):
    return {
        "type": "Polygon",
        "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]],
    }


def _feature(cve, nombre, geometry, alcaldia=GAM_NOMDT):
    return {
        "type": "Feature",
        "properties": {"NOMDT": alcaldia, "CVEUT": cve, "NOMUT": nombre},
        "geometry": geometry,
    }


def _payload(*features):
    return {"type": "FeatureCollection", "features": list(features)}


def _centroides(*puntos):
    """puntos: (hex_id, lat, lon). Ojo con el orden: el GeoJSON va (lon, lat)."""
    return pd.DataFrame(
        {"lat": [p[1] for p in puntos], "lon": [p[2] for p in puntos]},
        index=pd.Index([p[0] for p in puntos], name="hex_id"),
    )


def test_filtra_a_la_alcaldia_pedida():
    payload = _payload(
        _feature("05-001", "LINDAVISTA", _cuadro(-99.14, 19.48, -99.12, 19.50)),
        _feature("02-001", "AGUILERA", _cuadro(-99.20, 19.48, -99.18, 19.50), "AZCAPOTZALCO"),
    )
    colonias = colonias_from_geojson(payload)
    assert [c.nombre for c in colonias] == ["LINDAVISTA"]


def test_ordena_por_clave_aunque_el_geojson_venga_revuelto():
    """El orden desempata en assign_colonia, asi que no puede depender del
    orden en que el portal haya escrito las features."""
    payload = _payload(
        _feature("05-009", "ZONA ESCOLAR", _cuadro(-99.14, 19.48, -99.12, 19.50)),
        _feature("05-002", "ARAGON", _cuadro(-99.10, 19.48, -99.08, 19.50)),
    )
    assert [c.cve for c in colonias_from_geojson(payload)] == ["05-002", "05-009"]


def test_acepta_multipolygon():
    """Cuatro de las 232 colonias de GAM son MultiPolygon."""
    geometry = {
        "type": "MultiPolygon",
        "coordinates": [
            _cuadro(-99.14, 19.48, -99.13, 19.49)["coordinates"],
            _cuadro(-99.11, 19.48, -99.10, 19.49)["coordinates"],
        ],
    }
    (colonia,) = colonias_from_geojson(_payload(_feature("05-001", "PARTIDA", geometry)))
    assert len(colonia.poligono.geoms) == 2


def test_alcaldia_sin_coincidencias_falla_en_vez_de_devolver_lista_vacia():
    """`Gustavo A. Madero` con acentos y minusculas no coincide con NOMDT.
    Sin esta guardia el pipeline escribiria un parquet vacio sin quejarse."""
    payload = _payload(_feature("05-001", "LINDAVISTA", _cuadro(-99.14, 19.48, -99.12, 19.50)))
    with pytest.raises(ValueError, match="mayusculas"):
        colonias_from_geojson(payload, alcaldia="Gustavo A. Madero")


def test_payload_sin_features_falla():
    with pytest.raises(ValueError, match="features"):
        colonias_from_geojson({"type": "FeatureCollection", "features": []})


def test_clave_repetida_falla():
    """Asignar por clave con duplicados perderia un poligono en silencio."""
    payload = _payload(
        _feature("05-001", "LINDAVISTA", _cuadro(-99.14, 19.48, -99.12, 19.50)),
        _feature("05-001", "LINDAVISTA II", _cuadro(-99.10, 19.48, -99.08, 19.50)),
    )
    with pytest.raises(ValueError, match="05-001"):
        colonias_from_geojson(payload)


def test_geometria_que_no_delimita_falla():
    """Un punto no tiene interior: point-in-polygon contra el da siempre falso
    y la colonia quedaria muda en vez de rota."""
    payload = _payload(
        _feature("05-001", "LINDAVISTA", {"type": "Point", "coordinates": [-99.13, 19.49]})
    )
    with pytest.raises(ValueError, match="no delimita"):
        colonias_from_geojson(payload)


def _dos_colonias():
    payload = _payload(
        _feature("05-001", "LINDAVISTA", _cuadro(-99.14, 19.48, -99.12, 19.50)),
        _feature("05-002", "ARAGON", _cuadro(-99.10, 19.48, -99.08, 19.50)),
    )
    return colonias_from_geojson(payload)


def test_asigna_cada_hexagono_a_la_colonia_que_lo_contiene():
    centroids = _centroides(("a", 19.49, -99.13), ("b", 19.49, -99.09))
    out = assign_colonia(centroids, _dos_colonias())
    assert out.loc["a", "colonia"] == "LINDAVISTA"
    assert out.loc["a", "cve"] == "05-001"
    assert out.loc["b", "colonia"] == "ARAGON"


def test_hexagono_fuera_de_toda_colonia_sale_como_sin_colonia():
    """Son 12 de 724 y no se tiran: el dashboard los ofrece con esta etiqueta."""
    centroids = _centroides(("huerfano", 19.60, -99.30))
    out = assign_colonia(centroids, _dos_colonias())
    assert out.loc["huerfano", "colonia"] == SIN_COLONIA
    assert out.loc["huerfano", "cve"] == ""


def test_la_salida_conserva_todos_los_hexagonos_y_su_orden():
    centroids = _centroides(
        ("a", 19.49, -99.13), ("huerfano", 19.60, -99.30), ("b", 19.49, -99.09)
    )
    out = assign_colonia(centroids, _dos_colonias())
    assert list(out.index) == ["a", "huerfano", "b"]
    assert out.index.name == "hex_id"
    assert list(out.columns) == ["cve", "colonia"]


def test_no_basta_la_caja_envolvente_del_indice_espacial():
    """El STRtree descarta por bounding box, no por el poligono. Este centroide
    cae en la caja de la colonia en L pero en la muesca, fuera del poligono:
    sin la comprobacion `covers` se le asignaria igual."""
    ele = {
        "type": "Polygon",
        "coordinates": [
            [
                [-99.14, 19.48], [-99.10, 19.48], [-99.10, 19.49],
                [-99.13, 19.49], [-99.13, 19.52], [-99.14, 19.52], [-99.14, 19.48],
            ]
        ],
    }
    colonias = colonias_from_geojson(_payload(_feature("05-001", "ELE", ele)))
    en_la_muesca = _centroides(("a", 19.51, -99.11))
    assert colonias[0].poligono.bounds[0] < -99.11 < colonias[0].poligono.bounds[2]
    assert assign_colonia(en_la_muesca, colonias).loc["a", "colonia"] == SIN_COLONIA


def test_centroide_en_el_borde_compartido_cae_en_la_clave_mas_baja():
    """Dos colonias que comparten el borde en lon -99.12: `contains` dejaria
    huerfano un centroide que si pertenece a una de las dos."""
    payload = _payload(
        _feature("05-002", "ARAGON", _cuadro(-99.12, 19.48, -99.10, 19.50)),
        _feature("05-001", "LINDAVISTA", _cuadro(-99.14, 19.48, -99.12, 19.50)),
    )
    colonias = colonias_from_geojson(payload)
    en_el_borde = _centroides(("a", 19.49, -99.12))
    out = assign_colonia(en_el_borde, colonias)
    assert out.loc["a", "cve"] == "05-001"


def test_sin_colonias_no_revienta_y_marca_todo_huerfano():
    centroids = _centroides(("a", 19.49, -99.13))
    out = assign_colonia(centroids, [])
    assert out.loc["a", "colonia"] == SIN_COLONIA


def test_sin_hexagonos_devuelve_la_tabla_vacia():
    vacio = pd.DataFrame({"lat": [], "lon": []}, index=pd.Index([], name="hex_id"))
    out = assign_colonia(vacio, _dos_colonias())
    assert len(out) == 0
    assert list(out.columns) == ["cve", "colonia"]


def test_la_cache_corrupta_lo_dice_en_vez_de_reventar_al_parsear(tmp_path):
    cache = tmp_path / "colonias.json"
    cache.write_text('{"type": "FeatureColl', encoding="utf-8")
    with pytest.raises(ValueError, match="corrupta o truncada"):
        fetch_colonias(cache)


def test_la_cache_se_lee_sin_tocar_la_red(tmp_path, monkeypatch):
    def prohibido(*args, **kwargs):
        raise AssertionError("fetch_colonias fue a la red teniendo cache")

    monkeypatch.setattr("rtgam.colonias.requests.get", prohibido)
    cache = tmp_path / "colonias.json"
    cache.write_text(
        json.dumps(
            _payload(_feature("05-001", "LINDAVISTA", _cuadro(-99.14, 19.48, -99.12, 19.50)))
        ),
        encoding="utf-8",
    )
    assert [c.nombre for c in fetch_colonias(cache)] == ["LINDAVISTA"]


def test_no_se_cachea_un_payload_que_no_sirve(tmp_path, monkeypatch):
    """Se valida ANTES de escribir: un payload inservible cacheado envenenaria
    todas las corridas siguientes, que lo releerian y fallarian igual."""

    class Respuesta:
        def raise_for_status(self):
            pass

        def json(self):
            return {"type": "FeatureCollection", "features": []}

    monkeypatch.setattr("rtgam.colonias.requests.get", lambda *a, **k: Respuesta())
    cache = tmp_path / "colonias.json"
    with pytest.raises(ValueError, match="features"):
        fetch_colonias(cache)
    assert not cache.exists()
