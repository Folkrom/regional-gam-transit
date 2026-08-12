"""Fuente 4: densidad de poblacion y nivel socioeconomico del censo 2020.

Es la ultima fuente del score. Aporta `densidad_pob` y
`nivel_socioeconomico`, repartiendo los 305 AGEB de GAM sobre los 724
hexagonos por interseccion de area.

Los poligonos salen del portal de datos abiertos de la CDMX en GeoJSON y no
del shapefile del INEGI, y esa eleccion evita geopandas: un GeoJSON lo lee
json y lo convierte shapely, que ya es dependencia desde la fuente OSM. Son
los mismos poligonos del Marco Geoestadistico 2020, republicados.
"""

import io
import json
import zipfile
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import requests
from shapely.geometry import shape

from rtgam import USER_AGENT
from rtgam.areal import area_weights, hex_polygons
from rtgam.sources.denue import first_csv

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


CENSO_URL = (
    "https://www.inegi.org.mx/contenidos/programas/ccpv/2020/datosabiertos/"
    "ageb_manzana/ageb_mza_urbana_09_cpv2020_csv.zip"
)
AGEB_GEOJSON_URL = (
    "https://datos.cdmx.gob.mx/dataset/d2ccf6ae-fdf4-407c-a15f-e7dfac2d509d/"
    "resource/7b0b7a89-d92e-46ec-9286-018e849f8123/download/"
    "lmites-de-ageb-urbanas-en-la-ciudad-de-mxico.json"
)
CENSO_TIMEOUT_S = 300


def polygons_from_geojson(payload: dict) -> dict:
    """Poligonos de los AGEB de GAM, indexados por su clave de cuatro digitos.

    El GeoJSON del portal de la CDMX cubre las 2,431 AGEB de la ciudad; los de
    GAM son los que traen CVE_MUN igual a 005. Son 305, verificado contra el
    archivo real.
    """
    features = payload.get("features")
    if not features:
        raise ValueError(
            "El GeoJSON de AGEB no trae 'features'. No es una respuesta util y "
            "no se va a cachear."
        )

    polygons = {
        feature["properties"]["CVE_AGEB"]: shape(feature["geometry"])
        for feature in features
        if feature.get("properties", {}).get("CVE_MUN") == GAM_MUN
    }

    if not polygons:
        raise ValueError(
            f"Ningun AGEB con CVE_MUN == {GAM_MUN!r} en el GeoJSON. Si la CDMX "
            f"cambio la clave de alcaldia, GAM saldria vacia y las dos columnas "
            f"en cero sin que nada fallara."
        )
    return polygons


def fetch_ageb_polygons(cache_path: Path, force: bool = False) -> dict:
    """Descarga los poligonos de AGEB, con cache en disco.

    Se valida ANTES de escribir la cache. Al reves, una respuesta inservible
    queda persistida y envenena todas las corridas siguientes, que releen el
    mismo payload malo. Se corrigio tres veces en este proyecto por no hacerlo.
    """
    if cache_path.exists() and not force:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"La cache {cache_path} esta corrupta o truncada. Borrala o "
                f"corre con --force para volver a descargar. ({error})"
            ) from error
        return polygons_from_geojson(payload)

    response = requests.get(
        AGEB_GEOJSON_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=CENSO_TIMEOUT_S,
    )
    response.raise_for_status()
    payload = response.json()

    polygons = polygons_from_geojson(payload)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return polygons


def fetch_censo(cache_dir: Path, force: bool = False) -> pd.DataFrame:
    """Descarga el censo por AGEB de la CDMX y devuelve el CSV crudo.

    Todo se lee como texto: "0012" leido como numero se vuelve 12 y deja de
    cruzar con la clave de la geometria, sin que nada falle.

    El zip se escribe DESPUES de comprobar que abre y trae el CSV de datos.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "censo_ageb_09.zip"

    if zip_path.exists() and not force:
        try:
            with zipfile.ZipFile(zip_path) as zf:
                return _read_censo_csv(zf)
        except zipfile.BadZipFile as error:
            raise ValueError(
                f"La cache {zip_path} esta corrupta o truncada. Borrala o "
                f"corre con --force para volver a descargar. ({error})"
            ) from error

    response = requests.get(
        CENSO_URL, headers={"User-Agent": USER_AGENT}, timeout=CENSO_TIMEOUT_S
    )
    response.raise_for_status()

    content = response.content
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            frame = _read_censo_csv(zf)
    except zipfile.BadZipFile as error:
        raise ValueError(
            f"La respuesta de {CENSO_URL} no es un zip valido. No se cachea. "
            f"({error})"
        ) from error

    zip_path.write_bytes(content)
    return frame


def _read_censo_csv(zf: zipfile.ZipFile) -> pd.DataFrame:
    """Lee el CSV de datos del zip, como texto.

    first_csv de denue.py ya resuelve el mismo problema: el zip del INEGI trae
    un diccionario de datos y unos metadatos junto a los datos, y ordenados
    alfabeticamente 'diccionario_de_datos' va ANTES que 'conjunto_de_datos'.
    """
    name = first_csv(zf)
    with zf.open(name) as handle:
        return pd.read_csv(handle, dtype=str, low_memory=False)
