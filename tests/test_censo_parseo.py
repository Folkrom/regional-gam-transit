"""Parseo del censo: confidenciales, viviendas colectivas e indice NSE."""

import warnings

import pandas as pd
import pytest

from rtgam.sources.censo import (
    AGEB_COLUMNS,
    ageb_from_censo,
    nse_index,
    to_numeric,
)


def fila(ageb, pobtot, vivpar, inter, autom, graproes, mun="005", mza="000"):
    """Una fila del CSV del INEGI, con solo las columnas que se usan."""
    return {
        "MUN": mun,
        "AGEB": ageb,
        "MZA": mza,
        "POBTOT": pobtot,
        "VIVPAR_HAB": vivpar,
        "VPH_INTER": inter,
        "VPH_AUTOM": autom,
        "GRAPROES": graproes,
    }


def censo(filas):
    return pd.DataFrame(filas, dtype=str)


def test_to_numeric_convierte_el_asterisco_en_nan_no_en_cero():
    # El censo marca lo confidencial con "*" literal. Un fillna(0) despues lo
    # volveria pobreza inventada, y con min-max eso ancla el piso de la
    # columna para los 724 hexagonos.
    serie = pd.Series(["1.5", "*", "3.0"])
    resultado = to_numeric(serie)
    assert resultado.iloc[0] == pytest.approx(1.5)
    assert pd.isna(resultado.iloc[1])
    assert resultado.iloc[2] == pytest.approx(3.0)


def test_solo_entran_las_filas_de_gam_a_nivel_ageb():
    frame = censo(
        [
            fila("0012", "100", "30", "20", "10", "9.5"),
            fila("0012", "50", "15", "10", "5", "9.5", mza="001"),  # manzana
            fila("0000", "999", "300", "200", "100", "9.0"),  # total de localidad
            fila("0027", "200", "60", "40", "20", "10.0", mun="010"),  # otra alcaldia
        ]
    )
    ageb = ageb_from_censo(frame)
    assert list(ageb.index) == ["0012"]


def test_las_columnas_son_las_del_contrato():
    frame = censo([fila("0012", "100", "30", "20", "10", "9.5")])
    ageb = ageb_from_censo(frame)
    assert ageb.index.name == "cve_ageb"
    assert list(ageb.columns) == [c for c in AGEB_COLUMNS if c != "cve_ageb"]


def test_las_tasas_se_calculan_sobre_las_viviendas_habitadas():
    frame = censo([fila("0012", "100", "40", "30", "10", "9.5")])
    ageb = ageb_from_censo(frame)
    assert ageb.loc["0012", "internet"] == pytest.approx(0.75)
    assert ageb.loc["0012", "automovil"] == pytest.approx(0.25)
    assert ageb.loc["0012", "escolaridad"] == pytest.approx(9.5)
    assert ageb.loc["0012", "pobtot"] == pytest.approx(100.0)


def test_un_componente_confidencial_queda_en_nan_pero_la_poblacion_no():
    # Caso real: el AGEB 1646 de GAM, 7 habitantes, internet y automovil
    # confidenciales pero escolaridad presente.
    frame = censo([fila("1646", "7", "4", "*", "*", "8.14")])
    ageb = ageb_from_censo(frame)
    assert pd.isna(ageb.loc["1646", "internet"])
    assert pd.isna(ageb.loc["1646", "automovil"])
    assert ageb.loc["1646", "escolaridad"] == pytest.approx(8.14)
    assert ageb.loc["1646", "pobtot"] == pytest.approx(7.0)


def test_vivienda_colectiva_no_entra_al_nse_pero_su_poblacion_si_cuenta():
    # Caso real: el AGEB 0154 de GAM. 8,184 habitantes en vivienda colectiva y
    # CERO viviendas particulares. El censo los cuenta en POBTOT pero no les
    # levanta el cuestionario de vivienda, asi que GRAPROES sale 0.00: parece
    # un dato y no lo es. Tomado literal seria el AGEB mas pobre de GAM y, con
    # min-max, anclaria el piso de la columna para los 724 hexagonos.
    frame = censo([fila("0154", "8184", "0", "0", "0", "0.00")])
    ageb = ageb_from_censo(frame)
    assert ageb.loc["0154", "pobtot"] == pytest.approx(8184.0)
    assert pd.isna(ageb.loc["0154", "internet"])
    assert pd.isna(ageb.loc["0154", "automovil"])
    assert pd.isna(ageb.loc["0154", "escolaridad"])


def test_vivienda_colectiva_no_dispara_un_runtimewarning_de_numpy():
    # El 0/0 de numpy avisa y sigue. Si el aviso aparece, la division se esta
    # haciendo antes de la guardia y el NaN sale por accidente, no por diseno.
    frame = censo([fila("0154", "8184", "0", "0", "0", "0.00")])
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        ageb_from_censo(frame)


def test_las_viviendas_habitadas_confidenciales_tambien_anulan_el_nse():
    # Caso real: el AGEB 1928 de GAM. Sin denominador no hay tasa que calcular.
    frame = censo([fila("1928", "14", "*", "*", "*", "*")])
    ageb = ageb_from_censo(frame)
    assert ageb.loc["1928", "pobtot"] == pytest.approx(14.0)
    assert ageb[["internet", "automovil", "escolaridad"]].isna().all(axis=None)


def test_las_claves_de_ageb_con_letra_se_conservan_como_texto():
    # El AGEB "014A" existe en GAM. Leido como numero se pierde, y leido como
    # float el "0012" se vuelve "12.0" y deja de cruzar con la geometria.
    frame = censo([fila("014A", "100", "30", "20", "10", "9.5")])
    ageb = ageb_from_censo(frame)
    assert list(ageb.index) == ["014A"]


def test_el_indice_escala_cada_componente_entre_cero_y_uno():
    ageb = pd.DataFrame(
        {
            "internet": [0.2, 0.6, 1.0],
            "automovil": [0.1, 0.3, 0.5],
            "escolaridad": [8.0, 10.0, 12.0],
        },
        index=pd.Index(["a", "b", "c"], name="cve_ageb"),
    )
    nse = nse_index(ageb)
    assert nse.loc["a"] == pytest.approx(0.0)
    assert nse.loc["c"] == pytest.approx(1.0)
    assert nse.loc["b"] == pytest.approx(0.5)


def test_el_indice_promedia_solo_los_componentes_presentes():
    # Con dos de tres, divide entre dos. Dividir siempre entre tres castigaria
    # a un AGEB por un dato que el INEGI no publico, no por ser mas pobre.
    ageb = pd.DataFrame(
        {
            "internet": [0.0, 1.0, 1.0],
            "automovil": [0.0, 1.0, 1.0],
            "escolaridad": [8.0, 12.0, float("nan")],
        },
        index=pd.Index(["a", "b", "c"], name="cve_ageb"),
    )
    nse = nse_index(ageb)
    assert nse.loc["c"] == pytest.approx(1.0)


def test_un_ageb_sin_ningun_componente_queda_en_nan_no_en_cero():
    ageb = pd.DataFrame(
        {
            "internet": [0.2, float("nan")],
            "automovil": [0.4, float("nan")],
            "escolaridad": [9.0, float("nan")],
        },
        index=pd.Index(["a", "vacio"], name="cve_ageb"),
    )
    nse = nse_index(ageb)
    assert pd.isna(nse.loc["vacio"])


def test_un_componente_constante_no_produce_nan_en_el_indice():
    # Si todos los AGEB tienen el mismo valor, max - min es cero. Dividir daria
    # NaN y contaminaria el indice entero.
    ageb = pd.DataFrame(
        {
            "internet": [0.5, 0.5],
            "automovil": [0.2, 0.8],
            "escolaridad": [9.0, 11.0],
        },
        index=pd.Index(["a", "b"], name="cve_ageb"),
    )
    nse = nse_index(ageb)
    assert not nse.isna().any()
