"""Fuente 2: competencia y atractores comerciales desde el DENUE de INEGI.

Entrada: se descarga sola (45 MB) + data/processed/gam_hexes.parquet
Salida:  data/processed/denue.parquet
Auxiliar: data/interim/competencia_denue.csv (revisable a mano)

Uso:
    uv run python scripts/03_denue.py [--force]
"""

import argparse
from pathlib import Path

import pandas as pd

from rtgam.sources.denue import (
    COFFEE_PATTERN,
    fetch_denue_csv,
    load_gam,
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

    csv_path = fetch_denue_csv(RAW, force=args.force)
    gam = load_gam(csv_path)
    print(f"Establecimientos en GAM: {len(gam):,}")

    competencia, atractores = split_competencia_atractores(gam)
    print(f"  competencia (cafeterias): {len(competencia):,}")
    print(f"  atractores (comercio de calle): {len(atractores):,}")

    COMPETENCIA_REVISION.parent.mkdir(parents=True, exist_ok=True)
    competencia[["nom_estab", "codigo_act", "lat", "lon"]].to_csv(
        COMPETENCIA_REVISION, index=False
    )
    print(f"Lista de competencia para revisar a mano: {COMPETENCIA_REVISION}")
    print(f"  el patron de nombres usado fue: {COFFEE_PATTERN[:60]}...")

    hexes = pd.read_parquet(HEXES)
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
