"""Fuente 2: competencia y atractores comerciales desde el DENUE de INEGI.

Entrada: se descarga sola (126 MB en tres zips) + data/processed/gam_hexes.parquet
Salida:  data/processed/denue.parquet
Auxiliar: data/interim/competencia_denue.csv (revisable a mano)

Uso:
    uv run python scripts/03_denue.py [--force]
"""

import argparse
from pathlib import Path

import pandas as pd

from rtgam.geo import cells_near_grid
from rtgam.sources.denue import (
    COFFEE_PATTERN,
    fetch_denue_csvs,
    load_cerca_de_gam,
    split_competencia_atractores,
    to_hex_features,
)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
HEXES = ROOT / "data" / "processed" / "gam_hexes.parquet"
COMPETENCIA_REVISION = ROOT / "data" / "interim" / "competencia_denue.csv"
OUTPUT = ROOT / "data" / "processed" / "denue.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-descargar aunque exista cache"
    )
    args = parser.parse_args()

    hexes = pd.read_parquet(HEXES)
    collar = cells_near_grid(hexes.index)

    csv_paths = fetch_denue_csvs(RAW, force=args.force)
    cerca = load_cerca_de_gam(csv_paths, collar)
    print(f"Establecimientos dentro del collar de la rejilla: {len(cerca):,}")
    # El desglose por municipio es la evidencia de que el arreglo del borde
    # sigue vivo: si un dia vuelve a salir solo Gustavo A. Madero, el filtro
    # se rompio y las dos columnas saldrian bajas sin que nada lanzara.
    print("  por municipio:")
    for municipio, cuantos in cerca["municipio"].value_counts().head(8).items():
        print(f"    {municipio:24s} {cuantos:>7,}")

    competencia, atractores = split_competencia_atractores(cerca)
    print(f"  competencia (cafeterias): {len(competencia):,}")
    print(f"  atractores (comercio de calle): {len(atractores):,}")

    COMPETENCIA_REVISION.parent.mkdir(parents=True, exist_ok=True)
    # El municipio va en la lista de revision porque desde el arreglo del
    # borde hay competencia legitima fuera de GAM, y sin la columna parece
    # dato colado.
    competencia[["nom_estab", "codigo_act", "municipio", "lat", "lon"]].to_csv(
        COMPETENCIA_REVISION, index=False
    )
    print(f"Lista de competencia para revisar a mano: {COMPETENCIA_REVISION}")
    print(f"  el patron de nombres usado fue: {COFFEE_PATTERN[:60]}...")

    features = to_hex_features(hexes, competencia, atractores)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(OUTPUT)

    print()
    for columna in ["competencia", "atractores_denue"]:
        serie = features[columna]
        print(
            f"{columna}: {(serie > 0).sum()} de {len(serie)} hexagonos con senal "
            f"| media {serie.mean():.2f} | max {serie.max():.2f}"
        )
    print()
    print("Top 5 por atractores_denue:")
    print(features.nlargest(5, "atractores_denue").to_string())
    print(f"Escrito: {OUTPUT}")


if __name__ == "__main__":
    main()
