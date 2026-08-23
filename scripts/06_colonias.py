"""Etiqueta cada hexagono de GAM con la colonia donde cae su centroide.

Entrada: data/processed/gam_hexes.parquet
Salida:  data/processed/hex_colonias.parquet (hex_id, cve, colonia)

Vive aparte de 01_build_grid.py porque son 6 MB de GeoJSON y no hay por que
re-bajarlos cada vez que se reconstruye la rejilla. Y su salida NO entra a
SOURCE_FILES: no es variable del score sino una etiqueta, y ahi adentro
99_score.py intentaria normalizar un nombre de colonia. Archivo aparte, leido
solo por el dashboard, radio de daño cero sobre el pipeline.

Uso:
    uv run python scripts/06_colonias.py [--force]
"""

import argparse
import math
from pathlib import Path

import pandas as pd

from rtgam.colonias import SIN_COLONIA, assign_colonia, fetch_colonias

ROOT = Path(__file__).resolve().parents[1]
RAW_COLONIAS = ROOT / "data" / "raw" / "colonias_cdmx.geojson"
HEXES = ROOT / "data" / "processed" / "gam_hexes.parquet"
OUTPUT = ROOT / "data" / "processed" / "hex_colonias.parquet"

# Area media de una celda H3 resolucion 9, en km2. La misma que 01_build_grid.
H3_RES9_CELL_KM2 = 0.105


def area_km2(poligono) -> float:
    """Area aproximada en km2, sin reproyectar.

    Un grado de latitud son ~111 km, pero uno de longitud se encoge con el
    coseno de la latitud. Es la misma cuenta de 01_build_grid.py: sirve para
    comparar tamaños, no para catastro.
    """
    _, miny, _, maxy = poligono.bounds
    lat_mid = math.radians((miny + maxy) / 2)
    return poligono.area * 111.0 * (111.0 * math.cos(lat_mid))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-descargar aunque exista cache")
    args = parser.parse_args()

    hexes = pd.read_parquet(HEXES)
    colonias = fetch_colonias(RAW_COLONIAS, force=args.force)
    asignacion = assign_colonia(hexes, colonias)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    asignacion.to_parquet(OUTPUT)

    con_hexagono = set(asignacion["cve"]) - {""}
    vacias = [c for c in colonias if c.cve not in con_hexagono]
    huerfanos = int((asignacion["colonia"] == SIN_COLONIA).sum())
    por_colonia = asignacion.loc[asignacion["cve"] != "", "cve"].value_counts()

    print(f"Colonias de GAM en la fuente: {len(colonias)}")
    print(f"Hexagonos: {len(asignacion)}")
    print(
        f"Sin colonia: {huerfanos} ({huerfanos / len(asignacion) * 100:.1f}%). "
        f"Van al selector como {SIN_COLONIA}, no se tiran."
    )
    print(
        f"Colonias con al menos un hexagono: {len(con_hexagono)}  "
        f"(mediana {por_colonia.median():.0f} hexagonos, "
        f"{int((por_colonia == 1).sum())} con uno solo)"
    )
    # Una colonia sin hexagonos no es un bug: h3 asigna por centro de celda, y
    # una colonia mas chica que una celda puede no contener ningun centro. El
    # dashboard no las lista, porque un selector que ofrece una colonia y
    # devuelve un mapa vacio es peor que uno que no la ofrece.
    if vacias:
        areas = sorted(area_km2(c.poligono) for c in vacias)
        mediana = areas[len(areas) // 2]
        print(
            f"Colonias sin ningun hexagono: {len(vacias)}  "
            f"(area mediana {mediana:.3f} km2 contra {H3_RES9_CELL_KM2} de una "
            f"celda res 9; la mayor {areas[-1]:.3f} km2, suman {sum(areas):.1f} km2). "
            "El dashboard no las lista."
        )
    print()
    print("Colonias con mas hexagonos:")
    print(
        asignacion[asignacion["cve"] != ""]["colonia"]
        .value_counts()
        .head(10)
        .to_string()
    )
    print(f"Escrito: {OUTPUT}")


if __name__ == "__main__":
    main()
