"""Fuente 2: unidades economicas del DENUE de INEGI.

Aporta dos columnas al score: `competencia` (cafeterias existentes) y
`atractores_denue` (comercio que genera peaton de calle).

Se descargan tres archivos y se recortan por DISTANCIA a la rejilla, no por
municipio. Filtrar por municipio era el bug del borde: un negocio a 300 m
cruzando la calle no contaba por estar del otro lado de una linea
administrativa. Medido sobre GAM, 219 de 724 hexagonos perdian mas de un
atractor y el peor salia subestimado 12.2 veces.
"""

import io
import zipfile
from collections.abc import Iterable
from pathlib import Path

import h3
import pandas as pd
import requests

from rtgam import USER_AGENT
from rtgam.geo import H3_RESOLUTION, accumulate_decay

DENUE_BASE_URL = "https://www.inegi.org.mx/contenidos/masiva/denue/"
DENUE_TIMEOUT_S = 300

# CDMX (09) y Estado de Mexico (15). GAM colinda al norte y al oriente con
# Tlalnepantla de Baz y Ecatepec de Morelos, y ese lado pesa mas que el de
# CDMX: aporta 147 hexagonos con mas de un atractor ganado, contra 76 del
# resto de la ciudad.
#
# Edomex viene partido en dos archivos, y el corte NO es por municipio: los
# dos traen los mismos 125 municipios. Quedarse con el primero perderia ~40%
# de cada municipio fronterizo -13,701 de los 33,393 establecimientos de
# Tlalnepantla, por ejemplo- sin un solo error, solo con numeros mas chicos.
DENUE_PARTES = ("denue_09_csv", "denue_15_1_csv", "denue_15_2_csv")

# El CSV de DENUE viene en latin-1, no en utf-8. Verificado leyendo el archivo
# real: en utf-8 revienta con UnicodeDecodeError.
DENUE_ENCODING = "latin-1"

# De las 42 columnas del archivo solo se leen estas seis. Las demas son
# domicilio desglosado, telefono, correo y web, que no se usan.
USECOLS = ["nom_estab", "codigo_act", "per_ocu", "municipio", "latitud", "longitud"]


def load_cerca_de_gam(
    csv_paths: Iterable[str | Path], collar: set[str]
) -> pd.DataFrame:
    """Lee los CSV de DENUE y devuelve lo que cae dentro o cerca de la rejilla.

    `collar` sale de geo.cells_near_grid: las celdas de GAM mas tres anillos.
    Un establecimiento fuera de ahi esta a mas de 800 m de todo centroide y
    aportaria cero, asi que descartarlo no cambia ninguna cifra y evita cargar
    a memoria el resto de dos entidades.

    Cada archivo se recorta al leerlo y solo despues se concatenan: juntar
    primero los tres completos serian 1.3 millones de filas en memoria a la
    vez, para quedarse con 79 mil.

    Renombra latitud/longitud a lat/lon, que es lo que espera accumulate_decay,
    y descarta las filas sin coordenada: no se pueden ubicar, y un NaN llegaria
    hasta el reparto espacial, que lanza.
    """
    frames = [_load_one(path, collar) for path in csv_paths]
    if not frames:
        raise ValueError("No se paso ningun CSV de DENUE que leer.")

    frame = pd.concat(frames, ignore_index=True)
    if frame.empty:
        raise ValueError(
            "Ningun establecimiento del DENUE cayo dentro del collar de la "
            "rejilla. Con la rejilla de GAM eso no puede pasar: revisa que los "
            "CSV sean los de las entidades correctas y que traigan coordenadas."
        )
    return frame


def _load_one(csv_path: str | Path, collar: set[str]) -> pd.DataFrame:
    frame = pd.read_csv(
        csv_path, encoding=DENUE_ENCODING, usecols=USECOLS, low_memory=False
    )
    frame = frame.rename(columns={"latitud": "lat", "longitud": "lon"})
    frame = frame.dropna(subset=["lat", "lon"])
    celdas = [
        h3.latlng_to_cell(lat, lon, H3_RESOLUTION)
        for lat, lon in zip(frame["lat"], frame["lon"])
    ]
    return frame[[celda in collar for celda in celdas]].reset_index(drop=True)


def fetch_denue_csvs(cache_dir: Path, force: bool = False) -> list[Path]:
    """Descarga las tres partes del DENUE y devuelve sus CSV extraidos.

    En orden: CDMX, y las dos mitades del Estado de Mexico. Las tres hacen
    falta; ver DENUE_PARTES para por que la segunda mitad no es opcional.
    """
    return [fetch_denue_csv(cache_dir, parte, force=force) for parte in DENUE_PARTES]


def fetch_denue_csv(cache_dir: Path, parte: str, force: bool = False) -> Path:
    """Descarga una parte del DENUE y devuelve la ruta del CSV extraido.

    Los zips van de 30 a 50 MB y los CSV extraidos de 160 a 260 MB, asi que se
    cachean en disco y no se vuelven a bajar salvo con force.

    `parte` es el nombre del archivo sin extension, tal cual lo publica INEGI
    (`denue_09_csv`), y da nombre tanto al zip cacheado como al CSV extraido:
    con tres partes en el mismo directorio, un nombre fijo haria que la ultima
    pisara a las anteriores y las tres corridas leyeran la misma entidad.

    El zip se escribe DESPUES de comprobar que abre y trae un CSV dentro. Al
    reves, una respuesta 200 con contenido inservible quedaria persistida y
    envenenaria todas las corridas siguientes.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / f"{parte}.zip"
    csv_name = f"{parte}.csv"

    if zip_path.exists() and not force:
        try:
            with zipfile.ZipFile(zip_path) as zf:
                name = first_csv(zf)
                return _extract(zf, name, cache_dir, csv_name)
        except zipfile.BadZipFile as error:
            raise ValueError(
                f"La cache {zip_path} esta corrupta o truncada. Borrala o "
                f"corre con --force para volver a descargar. ({error})"
            ) from error

    response = requests.get(
        f"{DENUE_BASE_URL}{parte}.zip",
        headers={"User-Agent": USER_AGENT},
        timeout=DENUE_TIMEOUT_S,
    )
    response.raise_for_status()

    content = response.content
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        name = first_csv(zf)

    zip_path.write_bytes(content)
    with zipfile.ZipFile(zip_path) as zf:
        return _extract(zf, name, cache_dir, csv_name, overwrite=True)


def first_csv(zf: zipfile.ZipFile) -> str:
    """Nombre del CSV de datos dentro del zip.

    El zip trae el CSV bajo conjunto_de_datos/ junto con un diccionario de
    datos (diccionario_de_datos/) y metadatos (metadatos/). Cual sale primero
    en namelist() depende del orden interno del zip, no del alfabeto, asi que
    tomar el primer .csv a secas es una loteria: puede agarrar el diccionario
    en vez de los datos. Se exige explicitamente el que vive bajo
    conjunto_de_datos/, y se lanza si ninguno califica en vez de caer al
    primero.
    """
    names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    if not names:
        raise ValueError(
            f"El zip de DENUE no trae ningun .csv adentro. Contenido: "
            f"{zf.namelist()[:5]}"
        )
    for name in names:
        if "conjunto_de_datos" in name:
            return name

    # Sin fallback a names[0]. El zip real trae tres CSV y cual sale primero
    # en namelist() depende del orden interno del zip, no del alfabeto: tomar
    # el primero es una loteria que puede devolver el diccionario en vez de
    # los datos, y nada fallaba. Caer al primero otra vez seria repetir el
    # bug en silencio.
    raise ValueError(
        f"Ningun .csv del zip vive bajo conjunto_de_datos/. Encontrados: "
        f"{names}. Si INEGI cambio la estructura del zip, hay que revisar "
        f"cual archivo son los datos antes de seguir."
    )


def _extract(
    zf: zipfile.ZipFile,
    name: str,
    cache_dir: Path,
    csv_name: str,
    overwrite: bool = False,
) -> Path:
    """Extrae el CSV del zip a cache_dir.

    `overwrite` existe para el camino de descarga fresca: si se bajo un zip
    nuevo pero se conserva el CSV extraido de antes, el llamador recibiria en
    silencio los datos viejos, que es justo lo que --force venia a evitar.
    """
    destination = cache_dir / csv_name
    esperado = zf.getinfo(name).file_size
    completo = destination.exists() and destination.stat().st_size == esperado
    if overwrite or not completo:
        destination.write_bytes(zf.read(name))
    return destination


COMPETENCIA_SCIAN = "722515"

# Sectores SCIAN que generan peaton de banqueta. Quedan fuera manufactura,
# mayoreo y transporte: negocios reales, pero nadie camina frente a ellos.
#   46 comercio al menudeo   23,120 en GAM
#   72 alojamiento y comida   6,410
#   62 salud                  2,744
#   61 educativos             1,399
#   71 esparcimiento            568
ATTRACTOR_SECTORS = ("46", "72", "61", "62", "71")

# SCIAN 722515 es "cafeterias, fuentes de sodas, neverias, refresquerias y
# paleterias". En GAM eran 1026 establecimientos y solo 296 parecian cafe: el
# resto son paleterias, aguas y puestos de antojitos. Usar el codigo crudo
# inflaria la competencia 3.5 veces y castigaria justo las zonas de mucho
# peaton, que es lo contrario de lo que el score busca.
#
# CAFF esta a proposito: la primera version se comio AMOATO CAFFE EXPRESS.
#
# TOSTADOR y no TOSTAD: TOSTAD tambien matchea TOSTADAS, que es antojito y
# no cafe. CIELITO QUERIDO y no CIELITO: CIELITO tambien matchea Cielito
# Lindo, nombre comun de restaurante. Medido sobre GAM, ninguna de las dos
# formas cortas aportaba un solo match propio (los 5 nombres que atrapaban
# tambien contienen CAFE), asi que acotarlas quita riesgo sin perder nada.
#
# Es un criterio editorial, no un hecho. Por eso 03_denue.py escribe la lista
# de cruzados a data/interim/ para revision humana.
COFFEE_PATTERN = (
    r"CAF[EÉ]|CAFF|COFFEE|ESPRESSO|EXPRESSO|CAPPUCC|CAPUCH|BARIST|"
    r"TOSTADOR|STARBUCK|CIELITO QUERIDO|ITALIAN COFFEE|PUNTA DEL CIELO|MOKA|MOCCA|LATTE"
)


def split_competencia_atractores(
    gam: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parte los establecimientos de GAM en competencia y atractores.

    Competencia: SCIAN 722515 cuyo nombre matchea el patron de cafe.
    Atractores:  sectores de calle, MENOS los de competencia.

    Cada establecimiento cae en exactamente uno de los dos conjuntos, o en
    ninguno. Nunca en ambos.
    """
    codigo = gam["codigo_act"].astype(str)
    nombre = gam["nom_estab"].astype(str).str.upper()

    es_cafe = codigo.str.startswith(COMPETENCIA_SCIAN) & nombre.str.contains(
        COFFEE_PATTERN, regex=True, na=False
    )
    es_sector_calle = codigo.str[:2].isin(ATTRACTOR_SECTORS)

    competencia = gam[es_cafe]
    atractores = gam[es_sector_calle & ~es_cafe]
    return competencia.reset_index(drop=True), atractores.reset_index(drop=True)


PESO_COL = "peso"


def to_hex_features(
    gam_hexes: pd.DataFrame,
    competencia: pd.DataFrame,
    atractores: pd.DataFrame,
) -> pd.DataFrame:
    """Reparte los establecimientos sobre los hexagonos con el kernel del proyecto.

    Cada establecimiento vale 1: la suma ponderada de unos ES el conteo con
    decaimiento, asi que no hace falta codigo nuevo de reparto espacial.

    No se pondera por personal ocupado a proposito. Medido sobre GAM, hacerlo
    concentraria 26.8% de la variable en el top 1%, dominado por Costco y
    Liverpool, que son destinos de coche y no traen peaton de banqueta.

    Devuelve un DataFrame indexado por hex_id con las UNICAS dos columnas que
    esta fuente posee, en valores crudos y sin normalizar.
    """
    return pd.DataFrame(
        {
            "competencia": accumulate_decay(
                gam_hexes, competencia.assign(**{PESO_COL: 1.0}), PESO_COL
            ),
            "atractores_denue": accumulate_decay(
                gam_hexes, atractores.assign(**{PESO_COL: 1.0}), PESO_COL
            ),
        }
    )
