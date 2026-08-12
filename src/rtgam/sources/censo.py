"""Fuente 4: densidad de poblacion y nivel socioeconomico del censo 2020.

Es la ultima fuente del score. Aporta `densidad_pob` y
`nivel_socioeconomico`, repartiendo los 305 AGEB de GAM sobre los 724
hexagonos por interseccion de area.

Los poligonos salen del portal de datos abiertos de la CDMX en GeoJSON y no
del shapefile del INEGI, y esa eleccion evita geopandas: un GeoJSON lo lee
json y lo convierte shapely, que ya es dependencia desde la fuente OSM. Son
los mismos poligonos del Marco Geoestadistico 2020, republicados.
"""

import h3
import numpy as np
import pandas as pd

from rtgam.areal import area_weights, hex_polygons

GAM_MUN = "005"

# Nombre del componente, columna del numerador, columna del denominador.
# El denominador None significa que la columna se usa tal cual, sin ser tasa.
NSE_COMPONENTS = (
    ("internet", "VPH_INTER", "VIVPAR_HAB"),
    ("automovil", "VPH_AUTOM", "VIVPAR_HAB"),
    ("escolaridad", "GRAPROES", None),
)

AGEB_COLUMNS = ["cve_ageb", "pobtot", "internet", "automovil", "escolaridad"]


def to_numeric(series: pd.Series) -> pd.Series:
    """Convierte a float dejando NaN donde el censo marco confidencial.

    El INEGI marca lo confidencial con un asterisco literal, no con celda
    vacia. pd.to_numeric con errors="coerce" lo vuelve NaN, que es lo
    correcto; lo que nunca hay que hacer despues es rellenarlo con cero. Un
    cero es un dato -diria "aqui nadie tiene internet"- y con normalizacion
    min-max ancla el piso de la columna para los 724 hexagonos.
    """
    return pd.to_numeric(series, errors="coerce")


def ageb_from_censo(frame: pd.DataFrame) -> pd.DataFrame:
    """Filas a nivel AGEB de GAM, con la poblacion y los tres componentes.

    Devuelve un DataFrame indexado por cve_ageb con pobtot, internet,
    automovil y escolaridad. Los componentes vienen en NaN donde no hay dato.

    El filtro es por clave y no por el texto de NOM_LOC. Da exactamente las
    mismas 305 filas -medido- y comparar cadenas con acentos es la clase de
    cruce que ya costo caro en este proyecto.

    Las claves de AGEB se quedan como texto: "014A" existe en GAM, y leer la
    columna como numero convertiria "0012" en "12.0", que deja de cruzar con
    la geometria.
    """
    rows = frame[
        (frame["MUN"] == GAM_MUN)
        & (frame["MZA"] == "000")
        & (frame["AGEB"] != "0000")
    ].copy()

    out = pd.DataFrame(index=pd.Index(rows["AGEB"].astype(str), name="cve_ageb"))
    out["pobtot"] = to_numeric(rows["POBTOT"]).to_numpy()

    viviendas = to_numeric(rows["VIVPAR_HAB"]).to_numpy()
    # Sin viviendas particulares habitadas no hay tasa que calcular, y el cero
    # no es "cero por ciento": es que el censo no levanto el cuestionario de
    # vivienda. El AGEB 0154 de GAM tiene 8,184 habitantes en vivienda
    # colectiva, cero viviendas particulares y GRAPROES 0.00. Tomado literal
    # seria el AGEB mas pobre de la alcaldia y, como la normalizacion es
    # min-max, anclaria el piso de la columna para los 724 hexagonos.
    # La guardia va ANTES de dividir: el 0/0 de numpy avisa y sigue.
    sin_viviendas = ~(viviendas > 0)

    for name, numerator, denominator in NSE_COMPONENTS:
        values = to_numeric(rows[numerator]).to_numpy()
        if denominator is not None:
            values = np.divide(
                values,
                viviendas,
                out=np.full(len(values), np.nan),
                where=~sin_viviendas,
            )
        out[name] = np.where(sin_viviendas, np.nan, values)

    return out


def _scale_unit(values: pd.Series) -> pd.Series:
    """Escala una serie al rango [0, 1] ignorando los NaN.

    Los NaN se quedan NaN: son dato faltante, no un valor bajo.

    Si la serie es constante devuelve 0.5 donde hay dato, no NaN. Sin
    variacion ningun AGEB esta arriba ni abajo de otro, y un NaN aqui
    contaminaria el promedio del indice entero por un componente que
    simplemente no discrimina.
    """
    low, high = values.min(), values.max()
    if not np.isfinite(low) or not np.isfinite(high) or high == low:
        return pd.Series(
            np.where(values.notna(), 0.5, np.nan), index=values.index, dtype=float
        )
    return (values - low) / (high - low)


def nse_index(ageb: pd.DataFrame) -> pd.Series:
    """Indice de nivel socioeconomico, en [0, 1], o NaN si no hay ningun dato.

    Promedio de tres senales escaladas: porcentaje de viviendas con internet,
    porcentaje con automovil y anios de escolaridad. Ninguna sirve sola:
    internet se satura donde ya casi todos tienen conexion, el automovil sube
    en la periferia mal servida de transporte -Cuautepec y el norte de GAM- y
    la escolaridad va una generacion rezagada. Tres errores en tres
    direcciones distintas se cancelan en parte; uno solo, no.

    Promedia solo los componentes presentes. Dividir siempre entre tres
    castigaria a un AGEB por un dato que el INEGI no publico, no por ser mas
    pobre.

    Sale escalado y no crudo, contra la convencion del resto de las fuentes.
    Es deliberado y esta aprobado en el spec: promediar un porcentaje (0 a 1)
    con anios de escolaridad (0.00 a 15.87 en GAM) exige ponerlos en la misma
    escala antes, o la escolaridad domina por su magnitud y no por su
    importancia. 99_score.py volvera a normalizar la columna, lo que sobre un
    valor ya en [0, 1] solo lo reescala.
    """
    names = [name for name, _, _ in NSE_COMPONENTS]
    scaled = pd.DataFrame(
        {name: _scale_unit(ageb[name]) for name in names}, index=ageb.index
    )
    return scaled.mean(axis=1, skipna=True)


MIN_COVERAGE = 0.01


def to_hex_features(
    gam_hexes: pd.DataFrame,
    ageb: pd.DataFrame,
    polygons: dict,
) -> pd.DataFrame:
    """Emite las dos columnas que esta fuente posee.

    gam_hexes: indexado por hex_id, columnas lat y lon.
    ageb:      indexado por cve_ageb, columnas pobtot, internet, automovil y
               escolaridad.
    polygons:  cve_ageb -> Polygon, con exactamente las mismas claves que ageb.
    Devuelve:  DataFrame indexado por hex_id con densidad_pob (cruda, en
               hab/km2) y nivel_socioeconomico (escalado 0-1, ver nse_index).

    Las dos columnas se reparten con ponderaciones DISTINTAS, y confundirlas
    no lanza nada:

    - densidad_pob va por AREA. Si el 38% del area de un AGEB cae en un
      hexagono, ese hexagono recibe el 38% de su poblacion.
    - nivel_socioeconomico va pesado por la POBLACION asignada. Un hexagono
      que toca un pedazo grande y despoblado de un AGEB -un parque, un panteon,
      una vialidad- no debe dejar que ese pedazo vote igual que una manzana
      llena. El NSE es un atributo de personas, no de terreno.
    """
    if set(polygons) != set(ageb.index):
        faltan_poligono = sorted(set(ageb.index) - set(polygons))[:5]
        faltan_censo = sorted(set(polygons) - set(ageb.index))[:5]
        raise ValueError(
            f"Las claves de AGEB no coinciden entre censo y geometria. "
            f"Con censo y sin poligono: {faltan_poligono}. Con poligono y sin "
            f"censo: {faltan_censo}. Rellenar convertiria un hueco de datos en "
            f"un descampado plausible."
        )

    weights = area_weights(hex_polygons(gam_hexes), polygons)
    weights = weights[list(ageb.index)]

    poblacion = weights @ ageb["pobtot"].to_numpy(dtype=float)

    cubierto = weights.sum(axis=1)
    sin_cobertura = cubierto[cubierto < MIN_COVERAGE]
    if len(sin_cobertura):
        raise ValueError(
            f"{len(sin_cobertura)} hexagonos quedaron sin cobertura de AGEB, "
            f"por ejemplo {list(sin_cobertura.index[:5])}. Una densidad de 0.0 "
            f"seria el hexagono mas despoblado de la alcaldia sin que nada lo "
            f"dijera."
        )

    nse = nse_index(ageb)
    # El peso del NSE es la poblacion asignada, no el area: un pedazo grande y
    # despoblado no debe pesar como uno chico y lleno. Los AGEB sin NSE quedan
    # fuera del promedio en vez de entrar como cero, que los hundiria.
    aporte = weights.mul(ageb["pobtot"].to_numpy(dtype=float), axis=1)
    con_nse = aporte.loc[:, nse.notna().to_numpy()]
    valores = nse.dropna().to_numpy(dtype=float)

    total_nse = con_nse.sum(axis=1)
    sin_nse = total_nse[total_nse <= 0]
    if len(sin_nse):
        raise ValueError(
            f"{len(sin_nse)} hexagonos no tocan ningun AGEB con nivel "
            f"socioeconomico, por ejemplo {list(sin_nse.index[:5])}. Un 0.0 "
            f"seria el hexagono mas pobre de la alcaldia sin que nada lo dijera."
        )

    promedio = (con_nse @ valores) / total_nse

    area_km2 = pd.Series(
        {hex_id: h3.cell_area(hex_id, "km^2") for hex_id in gam_hexes.index}
    )

    return pd.DataFrame(
        {
            "densidad_pob": poblacion / area_km2,
            "nivel_socioeconomico": promedio,
        }
    )
