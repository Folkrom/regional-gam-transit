"""Colonias de la CDMX: descarga, filtro por alcaldia y asignacion a hexagonos.

Esto NO es una fuente del score. No produce ninguna variable, no entra a
SOURCE_FILES y nadie lo normaliza: solo etiqueta cada hexagono con la colonia
donde cae, para que el dashboard pueda esconder los que no interesan. El score
se calcula contra toda GAM y se queda igual con el filtro puesto.

Se usa el portal de datos de la CDMX y no OSM porque se midio: en el bbox de
GAM, OSM trae 15 poligonos de colonia contra 430 nodos `place=neighbourhood`.
Las colonias de la CDMX estan mapeadas como puntos, y un punto no delimita.

Ojo con el aviso de boundary.py: las URLs de este portal cambian entre
versiones. Si COLONIAS_URL muere, la clave del dataset (`coloniascdmx`) sigue
sirviendo para volver a encontrarla por la API CKAN:
https://datos.cdmx.gob.mx/api/3/action/package_show?id=coloniascdmx
"""

import json
from pathlib import Path
from typing import NamedTuple

import pandas as pd
import requests
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from rtgam import USER_AGENT

COLONIAS_URL = (
    "https://datos.cdmx.gob.mx/dataset/04a1900a-0c2f-41ed-94dc-3d2d5bad4065/"
    "resource/8070ee81-9111-437e-a3dd-0c3cc6dce9f4/download/colonias-cdmx-.json"
)

# El campo NOMDT trae la alcaldia en mayusculas y sin acentos. Escribirlo de
# otra forma no falla: filtra a cero colonias.
GAM_NOMDT = "GUSTAVO A. MADERO"

# Etiqueta de los hexagonos que no caen en ninguna colonia. Son 12 de 724 y
# entran al selector con este nombre en vez de desaparecer: un hexagono que el
# mapa no puede mostrar con ningun filtro puesto es peor que uno feo.
SIN_COLONIA = "(sin colonia)"


class Colonia(NamedTuple):
    cve: str
    nombre: str
    poligono: BaseGeometry


def colonias_from_geojson(payload: dict, alcaldia: str = GAM_NOMDT) -> list[Colonia]:
    """Colonias de una alcaldia, ordenadas por clave.

    El GeoJSON trae las 1,814 colonias de toda la CDMX; aqui se recorta a una
    alcaldia. Recortar la fuente por geometria propia seria trabajo de mas: el
    campo NOMDT ya dice a que alcaldia pertenece cada una.

    Falla ruidoso si la alcaldia no aparece: un nombre mal escrito produciria
    una lista vacia, el script escribiria un parquet sin filas y el dashboard
    ofreceria un selector vacio, todo sin una sola excepcion.
    """
    features = payload.get("features")
    if not features:
        raise ValueError(
            "El GeoJSON de colonias no trae 'features'. No es una respuesta "
            "util y no se va a cachear."
        )

    colonias = []
    for feature in features:
        properties = feature.get("properties", {})
        if properties.get("NOMDT") != alcaldia:
            continue

        geometry = feature.get("geometry") or {}
        if geometry.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError(
                f"La colonia {properties.get('NOMUT')!r} trae geometria "
                f"{geometry.get('type')!r}, que no delimita nada. Revisa la "
                "fuente antes de asignar hexagonos."
            )

        colonias.append(
            Colonia(
                cve=str(properties["CVEUT"]),
                nombre=str(properties["NOMUT"]),
                poligono=shape(geometry),
            )
        )

    if not colonias:
        raise ValueError(
            f"Ninguna colonia del GeoJSON tiene NOMDT == {alcaldia!r}. El campo "
            "va en mayusculas y sin acentos (GUSTAVO A. MADERO)."
        )

    claves = [c.cve for c in colonias]
    repetidas = sorted({c for c in claves if claves.count(c) > 1})
    if repetidas:
        raise ValueError(
            f"CVEUT repetida en {alcaldia}: {repetidas}. La clave identifica a "
            "la colonia; con duplicados, asignar por clave pierde poligonos en "
            "silencio."
        )

    # Ordenar deja deterministicos tanto la salida como el desempate de
    # assign_colonia entre dos poligonos que compartan un centroide.
    return sorted(colonias, key=lambda c: c.cve)


def fetch_colonias(
    cache_path: Path, force: bool = False, alcaldia: str = GAM_NOMDT
) -> list[Colonia]:
    """Descarga el GeoJSON de colonias de la CDMX, con cache en disco.

    Si `cache_path` existe y `force` es falso, no toca la red. Son 6 MB, asi
    que esto vive en su propio script y no colgado de 01_build_grid.py.

    Se valida ANTES de escribir la cache, igual que en boundary.py: una
    respuesta 200 con contenido inservible quedaria persistida y envenenaria
    todas las corridas siguientes.
    """
    if cache_path.exists() and not force:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"La cache {cache_path} esta corrupta o truncada. "
                f"Borrala o corre con --force para volver a descargar. ({error})"
            ) from error
        return colonias_from_geojson(payload, alcaldia)

    response = requests.get(
        COLONIAS_URL, headers={"User-Agent": USER_AGENT}, timeout=120
    )
    response.raise_for_status()
    payload = response.json()

    colonias = colonias_from_geojson(payload, alcaldia)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return colonias


def assign_colonia(centroids: pd.DataFrame, colonias: list[Colonia]) -> pd.DataFrame:
    """Colonia donde cae el centroide de cada hexagono.

    centroids: indexado por hex_id, columnas lat y lon.
    Devuelve:  DataFrame indexado por hex_id, columnas cve y colonia, con una
               fila por cada hexagono de `centroids` y en su mismo orden.

    Los hexagonos que no caen en ninguna colonia salen con cve vacia y colonia
    SIN_COLONIA. No se omiten: filtrarlos aqui los borraria del mapa sin que
    nadie lo pidiera.

    El STRtree solo descarta candidatos por caja envolvente, asi que despues
    hay que comprobar el poligono de verdad. Sin esa comprobacion, un hexagono
    junto a una colonia en forma de L se le asignaria igual.

    Se usa `covers` y no `contains` porque el borde cuenta: un centroide justo
    sobre la linea entre dos colonias pertenece a alguna, no a ninguna. Cuando
    dos la cubren gana la clave mas baja, y el desempate se toma con min sobre
    todos los candidatos, no quedandose con el primero que pase: STRtree.query
    no promete orden, asi que quedarse con el primero seria deterministico solo
    por casualidad.
    """
    if not colonias:
        return pd.DataFrame(
            {"cve": "", "colonia": SIN_COLONIA}, index=centroids.index, dtype=object
        )

    poligonos = [c.poligono for c in colonias]
    tree = STRtree(poligonos)

    claves, nombres = [], []
    for lat, lon in zip(centroids["lat"], centroids["lon"]):
        punto = Point(lon, lat)
        cubren = [p for p in tree.query(punto) if poligonos[p].covers(punto)]
        encontrada = colonias[min(cubren)] if cubren else None
        claves.append(encontrada.cve if encontrada else "")
        nombres.append(encontrada.nombre if encontrada else SIN_COLONIA)

    return pd.DataFrame(
        {"cve": claves, "colonia": nombres}, index=centroids.index
    )
