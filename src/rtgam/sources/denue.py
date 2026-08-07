"""Fuente 2: unidades economicas del DENUE de INEGI.

Aporta dos columnas al score: `competencia` (cafeterias existentes) y
`atractores_denue` (comercio que genera peaton de calle).

El archivo se descarga entero para CDMX (462,732 unidades) y se filtra a GAM
en la lectura, para no cargar el resto en memoria.
"""

import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

from rtgam import USER_AGENT
from rtgam.geo import accumulate_decay

DENUE_URL = "https://www.inegi.org.mx/contenidos/masiva/denue/denue_09_csv.zip"
DENUE_TIMEOUT_S = 300

# El CSV de DENUE viene en latin-1, no en utf-8. Verificado leyendo el archivo
# real: en utf-8 revienta con UnicodeDecodeError.
DENUE_ENCODING = "latin-1"

GAM_MUNICIPIO = "Gustavo A. Madero"

# De las 42 columnas del archivo solo se leen estas cinco. Las demas son
# domicilio desglosado, telefono, correo y web, que no se usan.
USECOLS = ["nom_estab", "codigo_act", "per_ocu", "municipio", "latitud", "longitud"]


def load_gam(csv_path: str | Path) -> pd.DataFrame:
    """Lee el CSV de DENUE y devuelve solo los establecimientos de GAM.

    Renombra latitud/longitud a lat/lon, que es lo que espera
    accumulate_decay, y descarta las filas sin coordenada: no se pueden
    ubicar, y un NaN llegaria hasta el reparto espacial, que lanza.
    """
    frame = pd.read_csv(
        csv_path, encoding=DENUE_ENCODING, usecols=USECOLS, low_memory=False
    )
    frame = frame[frame["municipio"].astype(str) == GAM_MUNICIPIO]
    if frame.empty:
        raise ValueError(
            f"Ninguna fila con municipio == {GAM_MUNICIPIO!r}. Si INEGI cambio "
            f"la escritura del nombre, ambas variables saldrian en cero sin que "
            f"nada fallara, y el score las reportaria como presentes."
        )
    frame = frame.rename(columns={"latitud": "lat", "longitud": "lon"})
    frame = frame.dropna(subset=["lat", "lon"])
    return frame.drop(columns=["municipio"]).reset_index(drop=True)


def fetch_denue_csv(cache_dir: Path, force: bool = False) -> Path:
    """Descarga el DENUE de CDMX y devuelve la ruta del CSV extraido.

    El zip son 45 MB y el CSV extraido 248 MB, asi que se cachean en disco y
    no se vuelven a bajar salvo con force.

    El zip se escribe DESPUES de comprobar que abre y trae un CSV dentro. Al
    reves, una respuesta 200 con contenido inservible quedaria persistida y
    envenenaria todas las corridas siguientes.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "denue_09_csv.zip"

    if zip_path.exists() and not force:
        try:
            with zipfile.ZipFile(zip_path) as zf:
                name = _first_csv(zf)
                return _extract(zf, name, cache_dir)
        except zipfile.BadZipFile as error:
            raise ValueError(
                f"La cache {zip_path} esta corrupta o truncada. Borrala o "
                f"corre con --force para volver a descargar. ({error})"
            ) from error

    response = requests.get(
        DENUE_URL, headers={"User-Agent": USER_AGENT}, timeout=DENUE_TIMEOUT_S
    )
    response.raise_for_status()

    content = response.content
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        name = _first_csv(zf)

    zip_path.write_bytes(content)
    with zipfile.ZipFile(zip_path) as zf:
        return _extract(zf, name, cache_dir, overwrite=True)


def _first_csv(zf: zipfile.ZipFile) -> str:
    """Nombre del CSV de datos dentro del zip.

    El zip trae el CSV bajo conjunto_de_datos/ junto con un diccionario de
    datos (diccionario_de_datos/) y metadatos (metadatos/). Ordenados
    alfabeticamente "diccionario_de_datos" va ANTES que "conjunto_de_datos",
    asi que tomar el primer .csv a secas agarra el diccionario, no los datos:
    se vio en la corrida real contra el zip de INEGI. Se prefiere el que vive
    bajo conjunto_de_datos/, y solo si ninguno califica se cae al primero.
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

    # Sin fallback a names[0]. El zip real trae tres CSV y, alfabeticamente,
    # diccionario_de_datos va ANTES que conjunto_de_datos: tomar el primero
    # devolvia el diccionario en vez de los datos, y nada fallaba. Caer al
    # primero otra vez seria repetir el bug en silencio.
    raise ValueError(
        f"Ningun .csv del zip vive bajo conjunto_de_datos/. Encontrados: "
        f"{names}. Si INEGI cambio la estructura del zip, hay que revisar "
        f"cual archivo son los datos antes de seguir."
    )


def _extract(
    zf: zipfile.ZipFile, name: str, cache_dir: Path, overwrite: bool = False
) -> Path:
    """Extrae el CSV del zip a cache_dir.

    `overwrite` existe para el camino de descarga fresca: si se bajo un zip
    nuevo pero se conserva el CSV extraido de antes, el llamador recibiria en
    silencio los datos viejos, que es justo lo que --force venia a evitar.
    """
    destination = cache_dir / "denue_gam.csv"
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
# paleterias". En GAM son 1026 establecimientos y solo 296 parecen cafe: el
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
