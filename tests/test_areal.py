"""Reparto areal: fraccion de cada poligono que cae en cada hexagono."""

import pandas as pd
import pytest
from shapely.geometry import Polygon

from rtgam.areal import area_weights, hex_polygons


def cuadro(x0, y0, lado):
    """Cuadrado con esquina inferior izquierda en (x0, y0), en grados."""
    return Polygon(
        [(x0, y0), (x0 + lado, y0), (x0 + lado, y0 + lado), (x0, y0 + lado)]
    )


def test_un_poligono_dentro_de_un_solo_hexagono_da_peso_uno():
    hexes = {"h1": cuadro(0, 0, 10)}
    fuentes = {"a": cuadro(2, 2, 1)}
    pesos = area_weights(hexes, fuentes)
    assert pesos.loc["h1", "a"] == pytest.approx(1.0)


def test_un_poligono_partido_en_dos_reparte_mitad_y_mitad():
    # El cuadro fuente va de x=8 a x=12; los hexagonos parten en x=10.
    hexes = {"izq": cuadro(0, 0, 10), "der": cuadro(10, 0, 10)}
    fuentes = {"a": Polygon([(8, 2), (12, 2), (12, 4), (8, 4)])}
    pesos = area_weights(hexes, fuentes)
    assert pesos.loc["izq", "a"] == pytest.approx(0.5)
    assert pesos.loc["der", "a"] == pytest.approx(0.5)


def test_los_pesos_de_un_poligono_cubierto_suman_uno():
    # Esta es LA propiedad que conserva la poblacion. Si esta prueba se cae,
    # la poblacion total deja de cuadrar con el censo.
    hexes = {"a": cuadro(0, 0, 10), "b": cuadro(10, 0, 10), "c": cuadro(0, 10, 10)}
    fuentes = {"p": Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])}
    pesos = area_weights(hexes, fuentes)
    assert pesos["p"].sum() == pytest.approx(0.75)


def test_un_poligono_que_sobresale_suma_menos_de_uno():
    # Un AGEB del borde de GAM que se sale de la reticula: se reparte solo la
    # parte cubierta, y el resto se pierde a proposito. No se re-escala.
    hexes = {"h1": cuadro(0, 0, 10)}
    fuentes = {"a": Polygon([(8, 2), (18, 2), (18, 4), (8, 4)])}
    pesos = area_weights(hexes, fuentes)
    assert pesos.loc["h1", "a"] == pytest.approx(0.2)


def test_un_poligono_que_no_toca_nada_da_cero_no_nan():
    # Un NaN aqui se propagaria al producto con la poblacion y ensuciaria la
    # columna entera, no solo este hexagono.
    hexes = {"h1": cuadro(0, 0, 10)}
    fuentes = {"lejos": cuadro(100, 100, 1)}
    pesos = area_weights(hexes, fuentes)
    assert pesos.loc["h1", "lejos"] == pytest.approx(0.0)
    assert not pesos.isna().any().any()


def test_el_indice_y_las_columnas_son_los_de_entrada():
    hexes = {"h1": cuadro(0, 0, 10), "h2": cuadro(10, 0, 10)}
    fuentes = {"a": cuadro(1, 1, 1), "b": cuadro(11, 1, 1)}
    pesos = area_weights(hexes, fuentes)
    assert list(pesos.index) == ["h1", "h2"]
    assert list(pesos.columns) == ["a", "b"]


def test_sin_poligonos_fuente_da_un_frame_vacio_con_el_indice():
    hexes = {"h1": cuadro(0, 0, 10)}
    pesos = area_weights(hexes, {})
    assert list(pesos.index) == ["h1"]
    assert len(pesos.columns) == 0


def test_hex_polygons_usa_lon_lat_no_lat_lon():
    # h3.cell_to_boundary devuelve (lat, lon) y shapely espera (x, y) = (lon,
    # lat). Invertirlas no lanza: produce poligonos en el hemisferio
    # equivocado que no intersectan nada, y todas las columnas salen en cero.
    # GAM esta en lon ~-99, lat ~19.5.
    import h3

    real = h3.latlng_to_cell(19.5, -99.1, 9)
    hexes = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index([real], name="hex_id")
    )
    polys = hex_polygons(hexes)
    minx, miny, maxx, maxy = polys[real].bounds
    assert -100 < minx < -98, "la x debe ser longitud (~-99), no latitud"
    assert 19 < miny < 20, "la y debe ser latitud (~19.5), no longitud"


def test_hex_polygons_devuelve_uno_por_hexagono():
    import h3

    ids = [h3.latlng_to_cell(19.5, -99.1, 9), h3.latlng_to_cell(19.52, -99.12, 9)]
    hexes = pd.DataFrame(
        {"lat": [19.5, 19.52], "lon": [-99.1, -99.12]},
        index=pd.Index(ids, name="hex_id"),
    )
    polys = hex_polygons(hexes)
    assert set(polys) == set(ids)
    assert all(p.area > 0 for p in polys.values())
