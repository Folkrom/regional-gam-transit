"""Las dos columnas del contrato: densidad y nivel socioeconomico."""

import h3
import pandas as pd
import pytest
from shapely.geometry import Polygon

from rtgam.areal import hex_polygons
from rtgam.sources.censo import MIN_COVERAGE, to_hex_features


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
DOS = h3.grid_ring(UNO, 1)[0]  # vecino inmediato, centroides a ~376 m


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
    # El hexagono lo cubren dos AGEB completos: "normal" satisface el
    # guardia de sin_nse (tiene los tres componentes), "colectiva" no tiene
    # ninguno. La poblacion de "colectiva" debe sumarse a la densidad aunque
    # quede fuera del promedio de nivel_socioeconomico. Cada poligono cubre
    # el hexagono entero, asi que cada AGEB le entrega su poblacion completa
    # -no hay reparto parcial que oscurezca cuanto aporta cada uno-.
    hexes = hexes_de(UNO)
    ageb = ageb_frame(
        [
            ("normal", 1000.0, 0.8, 0.6, 12.0),
            ("colectiva", 8184.0, float("nan"), float("nan"), float("nan")),
        ]
    )
    polygons = {"normal": poligono_de(UNO), "colectiva": poligono_de(UNO)}
    features = to_hex_features(hexes, ageb, polygons)
    solo_normal = to_hex_features(
        hexes, ageb.loc[["normal"]], {"normal": polygons["normal"]}
    )
    area_km2 = h3.cell_area(UNO, "km^2")
    # Cada poligono cubre el 100% del hexagono, asi que "colectiva" le
    # entrega sus 8184 habitantes completos; la densidad debe subir
    # exactamente esa poblacion entre el area del hexagono.
    esperado = solo_normal.loc[UNO, "densidad_pob"] + 8184.0 / area_km2
    assert features.loc[UNO, "densidad_pob"] == pytest.approx(esperado, rel=1e-6)


def test_la_salida_no_trae_nan():
    # merge_features lanza ante cualquier NaN de una fuente, y con razon. La
    # invariante mas importante que hay que proteger aqui es la ruta de
    # relleno: sin ella, con_dato.all() nunca es False y _nse_de_vecinos ni
    # se llama, dejando la garantia de "no NaN" verificada solo de rebote.
    # "lejos" y "vecino_lejos" son un segundo grupo, bien separado del grupo
    # UNO/DOS/"a" para que sus poligonos no se toquen entre si: "lejos" toca
    # un unico AGEB sin NSE, y su vecino inmediato "vecino_lejos" si tiene
    # NSE propio, asi que "lejos" pasa por el relleno y debe salir sin NaN.
    lejos = h3.grid_ring(UNO, 5)[0]
    vecino_lejos = h3.grid_ring(lejos, 1)[0]
    hexes = hexes_de(UNO, DOS, lejos, vecino_lejos)
    ageb = ageb_frame(
        [
            ("a", 1000.0, 0.5, 0.3, 10.0),
            ("lejos_sin_nse", 300.0, float("nan"), float("nan"), float("nan")),
            ("lejos_con_nse", 400.0, 0.6, 0.4, 9.0),
        ]
    )
    polygons = {
        "a": poligono_de(UNO, escala=6.0),
        "lejos_sin_nse": poligono_de(lejos),
        "lejos_con_nse": poligono_de(vecino_lejos),
    }
    features = to_hex_features(hexes, ageb, polygons)
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


def test_un_hexagono_dentro_de_un_ageb_enorme_no_dispara_la_guarda_de_cobertura():
    # "grande" es UNO escalado 12x desde su propio centroide: lo contiene por
    # completo, pero area(hex)/area(grande) = 1/144 queda muy por debajo de
    # MIN_COVERAGE. Con la formula vieja (weights.sum(axis=1), que suma
    # fracciones de AREA DEL AGEB y no del hexagono) esto disparaba la guarda
    # con datos perfectamente buenos; con la correcta la cobertura es 1.0.
    hexes = hexes_de(UNO)
    hex_poly = hex_polygons(hexes)[UNO]
    grande = poligono_de(UNO, escala=12.0)
    assert grande.contains(hex_poly), "el AGEB debe cubrir el hexagono entero"
    assert (hex_poly.area / grande.area) < MIN_COVERAGE, (
        "el hexagono debe ser una fraccion diminuta del AGEB"
    )

    ageb = ageb_frame([("grande", 1000.0, 0.5, 0.3, 10.0)])
    features = to_hex_features(hexes, ageb, {"grande": grande})
    esperado = (1000.0 / 144) / h3.cell_area(UNO, "km^2")
    assert features.loc[UNO, "densidad_pob"] == pytest.approx(esperado, rel=1e-6)


def test_un_hexagono_apenas_rozado_si_dispara_la_guarda_de_cobertura():
    # "rozado" esta centrado en DOS y escalado apenas lo suficiente (1.02x)
    # para clavar una esquina diminuta en UNO. Fija el umbral desde abajo: el
    # revisor bajo MIN_COVERAGE a 1e-12 y las 220 pruebas de entonces seguian
    # en verde, asi que nada probaba que la guarda dispare de verdad.
    hexes = hexes_de(UNO)
    hex_poly = hex_polygons(hexes)[UNO]
    rozado = poligono_de(DOS, escala=1.02)
    cubierto_real = hex_poly.intersection(rozado).area / hex_poly.area
    assert 0 < cubierto_real < MIN_COVERAGE, "el rozon debe ser real pero diminuto"

    ageb = ageb_frame([("rozado", 1000.0, 0.5, 0.3, 10.0)])
    with pytest.raises(ValueError, match=UNO):
        to_hex_features(hexes, ageb, {"rozado": rozado})


def test_un_hexagono_cubierto_pero_sin_nse_lanza():
    hexes = hexes_de(UNO)
    ageb = ageb_frame([("colectiva", 100.0, float("nan"), float("nan"), float("nan"))])
    with pytest.raises(ValueError, match="nivel socioeconomico"):
        to_hex_features(hexes, ageb, {"colectiva": poligono_de(UNO)})


def test_el_orden_de_polygons_no_desalinea_poblacion_ni_nse():
    # "A" cubre UNO por completo y no toca DOS; "B" cubre DOS por completo y
    # no toca UNO -sin traslape entre ellos-. El dict polygons se arma en el
    # orden inverso al indice de ageb (B antes que A). Si el codigo alineara
    # weights con ageb["pobtot"] por posicion en vez de por clave, la
    # poblacion y el NSE de A y B quedarian intercambiados entre los dos
    # hexagonos sin lanzar ninguna excepcion. Los valores se eligen bien
    # separados (900 vs 100, NSE 1.0 vs 0.0) para que un intercambio sea
    # inconfundible.
    hexes = hexes_de(UNO, DOS)
    ageb = ageb_frame(
        [
            ("A", 900.0, 1.0, 1.0, 15.0),
            ("B", 100.0, 0.0, 0.0, 3.0),
        ]
    )
    polygons = {"B": poligono_de(DOS), "A": poligono_de(UNO)}
    features = to_hex_features(hexes, ageb, polygons)

    # A y B no se traslapan (cada poligono coincide exactamente con un solo
    # hexagono), asi que cada hexagono recibe la poblacion y el NSE de un
    # unico AGEB, sin repartir. Con internet y automovil en {1.0, 0.0} y
    # escolaridad en {15.0, 3.0} para dos AGEB, _scale_unit manda a A a 1.0
    # en las tres componentes y a B a 0.0, asi que nse_index(A) = 1.0 y
    # nse_index(B) = 0.0 exactos.
    esperado_uno = 900.0 / h3.cell_area(UNO, "km^2")
    esperado_dos = 100.0 / h3.cell_area(DOS, "km^2")
    assert features.loc[UNO, "densidad_pob"] == pytest.approx(esperado_uno, rel=1e-6)
    assert features.loc[DOS, "densidad_pob"] == pytest.approx(esperado_dos, rel=1e-6)
    assert features.loc[UNO, "nivel_socioeconomico"] == pytest.approx(1.0)
    assert features.loc[DOS, "nivel_socioeconomico"] == pytest.approx(0.0)


def test_el_orden_no_desalinea_el_nse_con_un_ageb_nan_en_medio():
    # Tres AGEB: "A" cubre UNO, "C" cubre DOS, y "B" -el de en medio segun
    # ageb.index (A, B, C)- no tiene ningun componente de NSE y su poligono
    # cae en un tercer hexagono lejano que no toca ni UNO ni DOS. El dict
    # polygons se arma en un orden distinto al de ageb.index (C, A, B). Esto
    # ejercita especificamente el emparejamiento entre con_nse (que sigue el
    # orden de las columnas de weights tras el reordenamiento) y valores
    # (que sigue el orden de nse.dropna()): si esos dos quedaran
    # desalineados por posicion en vez de por clave, el NSE de A y C
    # terminaria intercambiado entre los hexagonos aunque B, el NaN de en
    # medio, ni siquiera los toque.
    hexes = hexes_de(UNO, DOS)
    tres = h3.grid_ring(UNO, 2)[0]
    ageb = ageb_frame(
        [
            ("A", 900.0, 1.0, 1.0, 15.0),
            ("B", 500.0, float("nan"), float("nan"), float("nan")),
            ("C", 100.0, 0.0, 0.0, 3.0),
        ]
    )
    polygons = {
        "C": poligono_de(DOS),
        "A": poligono_de(UNO),
        "B": poligono_de(tres),
    }
    features = to_hex_features(hexes, ageb, polygons)

    # B no toca ni UNO ni DOS (esta dos anillos lejos), asi que solo A
    # aporta a UNO y solo C aporta a DOS -sin importar que B sea NaN y este
    # en medio del indice-. Con solo A y C definiendo el rango de cada
    # componente, nse_index(A) = 1.0 y nse_index(C) = 0.0, igual que en la
    # prueba anterior.
    assert features.loc[UNO, "nivel_socioeconomico"] == pytest.approx(1.0)
    assert features.loc[DOS, "nivel_socioeconomico"] == pytest.approx(0.0)


def test_un_hexagono_sin_nse_propio_toma_el_promedio_de_sus_vecinos():
    # UNO solo toca un AGEB sin NSE (como el 0718 real, sin ningun
    # componente). v1 y v2 -vecinos inmediatos de UNO- si tienen NSE propio y
    # son los unicos dos AGEB con dato, asi que fijan los extremos de la
    # escala: v1 sale 1.0 y v2 sale 0.0. El promedio simple esperado es
    # (1.0 + 0.0) / 2 = 0.5.
    vecinos = h3.grid_ring(UNO, 1)
    v1, v2 = vecinos[0], vecinos[1]
    hexes = hexes_de(UNO, v1, v2)
    ageb = ageb_frame(
        [
            ("central", 1000.0, float("nan"), float("nan"), float("nan")),
            ("v1", 500.0, 1.0, 1.0, 15.0),
            ("v2", 500.0, 0.0, 0.0, 3.0),
        ]
    )
    polygons = {
        "central": poligono_de(UNO),
        "v1": poligono_de(v1),
        "v2": poligono_de(v2),
    }
    features = to_hex_features(hexes, ageb, polygons)
    assert features.loc[UNO, "nivel_socioeconomico"] == pytest.approx(0.5)


def test_el_relleno_por_vecinos_no_depende_del_orden():
    # UNO y DOS son vecinos mutuos y ninguno tiene NSE propio. w1 es vecino
    # de UNO pero NO de DOS; w2 es vecino de DOS pero NO de UNO -se descarta
    # con grid_ring para que cada uno solo pueda aportarle a su propio
    # hexagono-. w1 y w2 son los unicos dos AGEB con NSE real y fijan los
    # extremos de la escala: w1 sale 1.0 y w2 sale 0.0.
    #
    # Si el relleno leyera el resultado que se va rellenando en vez del
    # original, UNO se procesa antes que DOS segun el orden del indice, y
    # DOS terminaria promediando el 1.0 ya relleno de UNO junto con su propio
    # w2, dando 0.5 en vez de 0.0. Leyendo del original, DOS solo ve w2.
    ring_uno = h3.grid_ring(UNO, 1)
    ring_dos = h3.grid_ring(DOS, 1)
    assert DOS in ring_uno and UNO in ring_dos, "UNO y DOS deben ser vecinos mutuos"
    w1 = next(h for h in ring_uno if h != DOS and h not in ring_dos)
    w2 = next(h for h in ring_dos if h != UNO and h not in ring_uno)
    hexes = hexes_de(UNO, DOS, w1, w2)
    ageb = ageb_frame(
        [
            ("uno_nan", 1000.0, float("nan"), float("nan"), float("nan")),
            ("dos_nan", 1000.0, float("nan"), float("nan"), float("nan")),
            ("w1", 500.0, 1.0, 1.0, 15.0),
            ("w2", 500.0, 0.0, 0.0, 3.0),
        ]
    )
    polygons = {
        "uno_nan": poligono_de(UNO),
        "dos_nan": poligono_de(DOS),
        "w1": poligono_de(w1),
        "w2": poligono_de(w2),
    }
    features = to_hex_features(hexes, ageb, polygons)
    assert features.loc[UNO, "nivel_socioeconomico"] == pytest.approx(1.0)
    assert features.loc[DOS, "nivel_socioeconomico"] == pytest.approx(0.0)


def test_sin_ningun_vecino_con_nse_sigue_lanzando():
    # UNO y DOS son vecinos, y ninguno de los dos -ni ningun otro hexagono
    # incluido- toca un AGEB con NSE. No hay ningun vecino con dato al que
    # recurrir: debe lanzar, y el mensaje debe nombrar al hexagono.
    hexes = hexes_de(UNO, DOS)
    ageb = ageb_frame(
        [
            ("central", 1000.0, float("nan"), float("nan"), float("nan")),
            ("vecino", 800.0, float("nan"), float("nan"), float("nan")),
        ]
    )
    polygons = {"central": poligono_de(UNO), "vecino": poligono_de(DOS)}
    with pytest.raises(ValueError) as exc_info:
        to_hex_features(hexes, ageb, polygons)
    assert UNO in str(exc_info.value)


def test_el_relleno_no_altera_la_densidad():
    # UNO toca un unico AGEB "vacio" con pobtot 0 -como el 0718 real, cero
    # habitantes- y sin NSE propio. La densidad debe salir 0.0: ahi no vive
    # nadie, y eso es correcto. El NSE en cambio sale relleno del vecindario:
    # promedio simple de v1 (1.0) y v2 (0.0), o sea 0.5.
    vecinos = h3.grid_ring(UNO, 1)
    v1, v2 = vecinos[0], vecinos[1]
    hexes = hexes_de(UNO, v1, v2)
    ageb = ageb_frame(
        [
            ("vacio", 0.0, float("nan"), float("nan"), float("nan")),
            ("v1", 500.0, 1.0, 1.0, 15.0),
            ("v2", 500.0, 0.0, 0.0, 3.0),
        ]
    )
    polygons = {
        "vacio": poligono_de(UNO),
        "v1": poligono_de(v1),
        "v2": poligono_de(v2),
    }
    features = to_hex_features(hexes, ageb, polygons)
    assert features.loc[UNO, "densidad_pob"] == pytest.approx(0.0)
    assert features.loc[UNO, "nivel_socioeconomico"] == pytest.approx(0.5)


def test_un_hexagono_con_nse_propio_no_lo_toca_el_relleno():
    # UNO tiene NSE propio (via "u", el unico AGEB que lo toca) y DOS, su
    # vecino, no tiene NSE propio y necesita relleno. Los vecinos de DOS
    # presentes en el indice son UNO (1.0) y w (0.0), asi que DOS promedia
    # los dos y sale 0.5 -no "toma el de w" a secas-. "u" y "w" son los
    # unicos dos AGEB con NSE real y fijan los extremos de la escala: u sale
    # 1.0 y w sale 0.0. El punto de la prueba: el relleno de DOS usa, entre
    # otros, el valor ya calculado de UNO, pero eso no debe tocar el valor de
    # UNO mismo, que sigue siendo su propio ponderado (1.0), pase lo que pase
    # con DOS.
    ring_dos = h3.grid_ring(DOS, 1)
    w = next(h for h in ring_dos if h != UNO)
    hexes = hexes_de(UNO, DOS, w)
    ageb = ageb_frame(
        [
            ("u", 1000.0, 1.0, 1.0, 15.0),
            ("dos_nan", 800.0, float("nan"), float("nan"), float("nan")),
            ("w", 500.0, 0.0, 0.0, 3.0),
        ]
    )
    polygons = {
        "u": poligono_de(UNO),
        "dos_nan": poligono_de(DOS),
        "w": poligono_de(w),
    }
    features = to_hex_features(hexes, ageb, polygons)
    assert features.loc[UNO, "nivel_socioeconomico"] == pytest.approx(1.0)
    assert features.loc[DOS, "nivel_socioeconomico"] == pytest.approx(0.5)


def test_el_relleno_promedia_y_no_toma_la_mediana_de_los_vecinos():
    # UNO solo toca un AGEB sin NSE. v1, v2 y v3 son tres vecinos reales de
    # anillo 1 con NSE propio y valores ASIMETRICOS: 1.0, 0.9 y 0.0 -no
    # equiespaciados, para que promedio y mediana difieran de verdad-. Con
    # solo estos tres AGEB definiendo el rango de cada componente, nse_index
    # da exactamente esas fracciones (el mismo patron de extremos que fija
    # la escala en el resto del archivo). El promedio simple esperado es
    # (1.0 + 0.9 + 0.0) / 3 = 0.6333..., mientras que la mediana de
    # {0.0, 0.9, 1.0} es 0.9: con solo dos vecinos con dato -o uno solo- la
    # media y la mediana coinciden por definicion y ninguna prueba anterior
    # de este archivo distingue una de la otra.
    vecinos = h3.grid_ring(UNO, 1)
    v1, v2, v3 = vecinos[0], vecinos[1], vecinos[2]
    hexes = hexes_de(UNO, v1, v2, v3)
    ageb = ageb_frame(
        [
            ("central", 1000.0, float("nan"), float("nan"), float("nan")),
            ("v1", 500.0, 1.0, 1.0, 15.0),
            ("v2", 500.0, 0.9, 0.9, 13.5),
            ("v3", 500.0, 0.0, 0.0, 0.0),
        ]
    )
    polygons = {
        "central": poligono_de(UNO),
        "v1": poligono_de(v1),
        "v2": poligono_de(v2),
        "v3": poligono_de(v3),
    }
    features = to_hex_features(hexes, ageb, polygons)
    esperado = (1.0 + 0.9 + 0.0) / 3
    assert features.loc[UNO, "nivel_socioeconomico"] == pytest.approx(esperado)
