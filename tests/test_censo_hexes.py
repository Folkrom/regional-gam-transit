"""Las dos columnas del contrato: densidad y nivel socioeconomico."""

import h3
import pandas as pd
import pytest
from shapely.geometry import Polygon

from rtgam.areal import hex_polygons
from rtgam.sources.censo import to_hex_features


def hexes_de(*ids):
    filas = [(h, *h3.cell_to_latlng(h)) for h in ids]
    return pd.DataFrame(filas, columns=["hex_id", "lat", "lon"]).set_index("hex_id")


def ageb_frame(filas):
    """filas: (cve_ageb, pobtot, internet, automovil, escolaridad)."""
    frame = pd.DataFrame(
        filas, columns=["cve_ageb", "pobtot", "internet", "automovil", "escolaridad"]
    )
    return frame.set_index("cve_ageb")


def poligono_de(hex_id, escala=1.0):
    """Poligono centrado en un hexagono, escalado desde su centroide."""
    lat, lon = h3.cell_to_latlng(hex_id)
    puntos = [(lo, la) for la, lo in h3.cell_to_boundary(hex_id)]
    return Polygon(
        [(lon + (x - lon) * escala, lat + (y - lat) * escala) for x, y in puntos]
    )


UNO = h3.latlng_to_cell(19.50, -99.10, 9)
DOS = h3.latlng_to_cell(19.52, -99.12, 9)


def test_las_columnas_son_exactamente_las_dos_del_contrato():
    hexes = hexes_de(UNO)
    ageb = ageb_frame([("a", 1000.0, 0.5, 0.3, 10.0)])
    features = to_hex_features(hexes, ageb, {"a": poligono_de(UNO)})
    assert list(features.columns) == ["densidad_pob", "nivel_socioeconomico"]
    assert list(features.index) == [UNO]


def test_la_densidad_es_poblacion_entre_kilometros_cuadrados():
    # Un AGEB que cubre exactamente un hexagono le entrega toda su poblacion.
    hexes = hexes_de(UNO)
    ageb = ageb_frame([("a", 1000.0, 0.5, 0.3, 10.0)])
    features = to_hex_features(hexes, ageb, {"a": poligono_de(UNO)})
    esperado = 1000.0 / h3.cell_area(UNO, "km^2")
    assert features.loc[UNO, "densidad_pob"] == pytest.approx(esperado, rel=1e-6)


def test_un_ageb_que_cubre_dos_hexagonos_reparte_su_poblacion_entre_ambos():
    # La conservacion exacta se prueba en test_areal; aqui se comprueba que
    # to_hex_features usa esos pesos y no le entrega la poblacion entera a
    # cada hexagono por separado.
    hexes = hexes_de(UNO, DOS)
    ageb = ageb_frame([("a", 1000.0, 0.5, 0.3, 10.0)])
    features = to_hex_features(hexes, ageb, {"a": poligono_de(UNO, escala=6.0)})
    area_km2 = h3.cell_area(UNO, "km^2")
    repartida = (features["densidad_pob"] * area_km2).sum()
    assert repartida < 1000.0, "el poligono se sale de los dos hexagonos"
    assert (features["densidad_pob"] > 0).all(), "los dos deben recibir gente"


def test_el_nse_pesa_por_poblacion_no_por_area():
    # El hexagono toca dos AGEB. El "rico" le aporta MAS AREA pero MENOS gente;
    # el "pobre" le aporta menos area y mucha mas gente. El resultado debe
    # inclinarse al pobre. Sin esta prueba, cambiar el peso de poblacion por
    # area pasaria inadvertido: los dos dan un numero plausible.
    hexes = hexes_de(UNO)
    ageb = ageb_frame(
        [
            ("rico", 10.0, 1.0, 1.0, 15.0),
            ("pobre", 5000.0, 0.0, 0.0, 6.0),
        ]
    )
    polygons = {
        "rico": poligono_de(UNO, escala=0.9),
        "pobre": poligono_de(UNO, escala=0.3),
    }
    features = to_hex_features(hexes, ageb, polygons)
    assert features.loc[UNO, "nivel_socioeconomico"] < 0.3


def test_un_ageb_sin_nse_no_arrastra_el_promedio_hacia_cero():
    # El AGEB de vivienda colectiva aporta poblacion pero no tiene NSE. Si
    # entrara como 0.0, hundiria el hexagono; debe quedar fuera del promedio.
    hexes = hexes_de(UNO)
    ageb = ageb_frame(
        [
            ("normal", 1000.0, 0.8, 0.6, 12.0),
            ("colectiva", 8184.0, float("nan"), float("nan"), float("nan")),
        ]
    )
    polygons = {
        "normal": poligono_de(UNO, escala=0.5),
        "colectiva": poligono_de(UNO, escala=0.5),
    }
    features = to_hex_features(hexes, ageb, polygons)
    solo_normal = to_hex_features(
        hexes, ageb.loc[["normal"]], {"normal": polygons["normal"]}
    )
    assert features.loc[UNO, "nivel_socioeconomico"] == pytest.approx(
        solo_normal.loc[UNO, "nivel_socioeconomico"]
    )


def test_la_poblacion_de_un_ageb_sin_nse_si_cuenta_para_densidad():
    hexes = hexes_de(UNO)
    ageb = ageb_frame([("colectiva", 8184.0, float("nan"), float("nan"), float("nan"))])
    features = to_hex_features(hexes, ageb, {"colectiva": poligono_de(UNO)})
    assert features.loc[UNO, "densidad_pob"] > 0.0


def test_la_salida_no_trae_nan():
    # merge_features lanza ante cualquier NaN de una fuente, y con razon.
    hexes = hexes_de(UNO, DOS)
    ageb = ageb_frame([("a", 1000.0, 0.5, 0.3, 10.0)])
    features = to_hex_features(hexes, ageb, {"a": poligono_de(UNO, escala=6.0)})
    assert not features.isna().any().any()


def test_un_desajuste_de_claves_lanza_en_vez_de_rellenar():
    # Un AGEB con censo pero sin poligono no tendria donde aterrizar; uno con
    # poligono pero sin censo pintaria un hueco como si fuera un descampado.
    hexes = hexes_de(UNO)
    ageb = ageb_frame([("a", 1000.0, 0.5, 0.3, 10.0)])
    with pytest.raises(ValueError, match="claves"):
        to_hex_features(hexes, ageb, {"b": poligono_de(UNO)})


def test_un_hexagono_sin_cobertura_lanza_en_vez_de_salir_en_cero():
    # En GAM hoy no pasa —cero de 724— pero el dia que pase, una densidad de
    # 0.0 seria el hexagono mas despoblado de la alcaldia sin que nada lo
    # dijera.
    hexes = hexes_de(UNO, DOS)
    ageb = ageb_frame([("a", 1000.0, 0.5, 0.3, 10.0)])
    with pytest.raises(ValueError, match="sin cobertura"):
        to_hex_features(hexes, ageb, {"a": poligono_de(UNO)})


def test_un_hexagono_cubierto_pero_sin_nse_lanza():
    hexes = hexes_de(UNO)
    ageb = ageb_frame([("colectiva", 100.0, float("nan"), float("nan"), float("nan"))])
    with pytest.raises(ValueError, match="nivel socioeconomico"):
        to_hex_features(hexes, ageb, {"colectiva": poligono_de(UNO)})
