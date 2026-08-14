"""Une las fuentes, normaliza y calcula el score compuesto.

Entrada: data/processed/gam_hexes.parquet + cualquier <fuente>.parquet presente
Salida:  data/processed/hex_features.parquet (crudo)
         data/processed/hex_scores.parquet (normalizado + score)

Corre con las fuentes que existan. Con solo transporte.parquet ya produce un
mapa valido.

Uso:
    uv run python scripts/99_score.py
"""

from pathlib import Path

import pandas as pd

from rtgam.score import compute_score, load_weights, merge_features

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
HEXES = PROCESSED / "gam_hexes.parquet"
FEATURES_OUT = PROCESSED / "hex_features.parquet"
SCORES_OUT = PROCESSED / "hex_scores.parquet"

# Una entrada por fuente. Agregar una fuente nueva es agregar una linea aqui.
SOURCE_FILES = [
    "transporte.parquet",
    "denue.parquet",
    "osm.parquet",
    "censo.parquet",
]


def main() -> None:
    hexes = pd.read_parquet(HEXES)

    frames = []
    for filename in SOURCE_FILES:
        path = PROCESSED / filename
        if path.exists():
            frame = pd.read_parquet(path)
            frames.append(frame)
            print(f"Fuente cargada: {filename}  columnas {list(frame.columns)}")
        else:
            print(f"Fuente ausente, se omite: {filename}")

    features = merge_features(hexes, frames)
    features.to_parquet(FEATURES_OUT)

    weights = load_weights()
    scores = compute_score(features, weights)

    used = [c for c in weights if c in features.columns]
    ignored = [c for c in weights if c not in features.columns]
    print()
    print(f"Variables en el score: {used}")
    if ignored:
        print(f"Variables sin datos aun: {ignored}")

    sin_peso = [c for c in features.columns if c not in weights]
    if sin_peso:
        print(f"AVISO: columnas sin peso en weights.yaml, excluidas del score: {sin_peso}")

    scores.to_parquet(SCORES_OUT)

    print()
    print(f"Hexagonos: {len(scores)}")
    print(f"score  min {scores['score'].min():.4f}  media {scores['score'].mean():.4f}  max {scores['score'].max():.4f}")
    print("Top 10 hexagonos:")
    print(scores.nlargest(10, "score").to_string())
    print(f"Escrito: {FEATURES_OUT}")
    print(f"Escrito: {SCORES_OUT}")


if __name__ == "__main__":
    main()
