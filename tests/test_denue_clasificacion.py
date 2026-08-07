import pandas as pd

from rtgam.sources.denue import ATTRACTOR_SECTORS, split_competencia_atractores


def _fila(nombre, codigo):
    return {"nom_estab": nombre, "codigo_act": codigo, "lat": 19.5, "lon": -99.1}


def test_cafeterias_cuentan_como_competencia():
    gam = pd.DataFrame([
        _fila("STARBUCKS LINDAVISTA", "722515"),
        _fila("ALEBRIJE CAFE", "722515"),
    ])
    competencia, _ = split_competencia_atractores(gam)
    assert len(competencia) == 2


def test_atrapa_caffe_con_doble_efe():
    """La primera version del patron se comio AMOATO CAFFE EXPRESS."""
    gam = pd.DataFrame([_fila("AMOATO CAFFE EXPRESS", "722515")])
    competencia, _ = split_competencia_atractores(gam)
    assert len(competencia) == 1


def test_no_confunde_tostadas_ni_cielito_lindo_con_cafeterias():
    """Dos colisiones reales del patron corto.

    TOSTAD matchea TOSTADAS, que es antojito. CIELITO matchea Cielito Lindo,
    nombre comun de restaurante. Ninguno de los dos es competencia para una
    cafeteria de especialidad.
    """
    gam = pd.DataFrame([
        _fila("TOSTADAS DOÑA MARY", "722515"),
        _fila("CIELITO LINDO", "722515"),
    ])
    competencia, atractores = split_competencia_atractores(gam)
    assert len(competencia) == 0
    assert len(atractores) == 2, "no compiten, pero si traen peaton"


def test_las_alternativas_acotadas_si_aportan_por_si_solas():
    """Nombres que SOLO cruzan por TOSTADOR o CIELITO QUERIDO.

    Ninguno contiene CAFE a proposito. Con nombres que si lo contienen la
    prueba pasaria por la primera linea del patron aunque alguien borrara
    estas dos alternativas, y no fijaria nada. Verificado: con el patron
    actual estos dos cruzan, y quitando las dos alternativas dejan de cruzar.
    """
    gam = pd.DataFrame([
        _fila("TOSTADOR LA ESPERANZA", "722515"),
        _fila("CIELITO QUERIDO", "722515"),
    ])
    competencia, _ = split_competencia_atractores(gam)
    assert len(competencia) == 2


def test_paleterias_y_antojitos_no_son_competencia():
    """SCIAN 722515 mezcla cafeterias con paleterias y puestos de comida.

    Medido sobre GAM: de 1026 establecimientos con ese codigo, solo 296
    parecen cafe. Usarlo crudo inflaria la competencia 3.5 veces.
    """
    gam = pd.DataFrame([
        _fila("AGUAS DE FRUTAS", "722515"),
        _fila("ANTOJITOS BETY", "722515"),
        _fila("PALETERIA LA MICHOACANA", "722515"),
    ])
    competencia, atractores = split_competencia_atractores(gam)
    assert len(competencia) == 0
    assert len(atractores) == 3, "no se tiran: traen peaton aunque no compitan"


def test_sectores_de_calle_son_atractores():
    gam = pd.DataFrame([
        _fila("PAPELERIA", "465311"),      # 46 menudeo
        _fila("PRIMARIA BENITO JUAREZ", "611121"),  # 61 educativos
        _fila("FARMACIA", "621331"),       # 62 salud
    ])
    _, atractores = split_competencia_atractores(gam)
    assert len(atractores) == 3


def test_mayoreo_y_manufactura_quedan_fuera():
    """Son negocios reales, pero no generan gente caminando en la banqueta."""
    gam = pd.DataFrame([
        _fila("BODEGA MAYORISTA", "431110"),   # 43 mayoreo
        _fila("TALLER DE COSTURA", "315210"),  # 31 manufactura
    ])
    competencia, atractores = split_competencia_atractores(gam)
    assert len(competencia) == 0
    assert len(atractores) == 0


def test_ningun_establecimiento_en_ambas_columnas():
    """Propiedad unica: cada uno aporta a UNA sola variable.

    Contar un cafe tambien como atractor cancelaria parcialmente la senal de
    competencia.
    """
    gam = pd.DataFrame([
        _fila("STARBUCKS LINDAVISTA", "722515"),
        _fila("AGUAS DE FRUTAS", "722515"),
        _fila("PAPELERIA", "465311"),
    ])
    competencia, atractores = split_competencia_atractores(gam)
    assert len(competencia) == 1
    assert len(atractores) == 2
    assert set(competencia["nom_estab"]) & set(atractores["nom_estab"]) == set()


def test_sectores_atractores_son_los_del_spec():
    assert ATTRACTOR_SECTORS == ("46", "72", "61", "62", "71")
