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
                nombre = _primer_csv(zf)
                return _extraer(zf, nombre, cache_dir)
        except zipfile.BadZipFile as error:
            raise ValueError(
                f"La cache {zip_path} esta corrupta o truncada. Borrala o "
                f"corre con --force para volver a descargar. ({error})"
            ) from error

    response = requests.get(
        DENUE_URL, headers={"User-Agent": USER_AGENT}, timeout=DENUE_TIMEOUT_S
    )
    response.raise_for_status()

    contenido = response.content
    with zipfile.ZipFile(io.BytesIO(contenido)) as zf:
        nombre = _primer_csv(zf)

    zip_path.write_bytes(contenido)
    with zipfile.ZipFile(zip_path) as zf:
        return _extraer(zf, nombre, cache_dir)


def _primer_csv(zf: zipfile.ZipFile) -> str:
    """Nombre del primer .csv dentro del zip.

    El zip trae el CSV bajo conjunto_de_datos/ junto con diccionarios y
    metadatos, y la ruta exacta cambia entre versiones del archivo.
    """
    nombres = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    if not nombres:
        raise ValueError(
            f"El zip de DENUE no trae ningun .csv adentro. Contenido: "
            f"{zf.namelist()[:5]}"
        )
    return nombres[0]


def _extraer(zf: zipfile.ZipFile, nombre: str, cache_dir: Path) -> Path:
    destino = cache_dir / "denue_gam.csv"
    if not destino.exists():
        destino.write_bytes(zf.read(nombre))
    return destino
