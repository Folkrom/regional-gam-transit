"""Combinacion de variables normalizadas en el score compuesto."""

from pathlib import Path

import pandas as pd
import yaml

from rtgam.normalize import log1p_minmax

DEFAULT_WEIGHTS_PATH = Path(__file__).resolve().parents[2] / "config" / "weights.yaml"


def load_weights(path: str | Path = DEFAULT_WEIGHTS_PATH) -> dict[str, float]:
    """Lee los pesos del YAML de configuracion."""
    with open(path, encoding="utf-8") as fh:
        return {k: float(v) for k, v in yaml.safe_load(fh)["weights"].items()}


def compute_score(features: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    """Normaliza cada variable y las combina en un score ponderado.

    Devuelve un DataFrame con una columna `<variable>_norm` por cada peso cuya
    variable exista en `features`, mas la columna `score`.

    Las variables ausentes se saltan en silencio a proposito: el pipeline se
    construye fuente por fuente, y `99_score.py` debe producir un mapa valido
    con las columnas que ya existan, aunque falten las demas.

    El signo vive en el peso, no aqui: `competencia` lleva peso negativo en
    config/weights.yaml y por eso resta.
    """
    out = pd.DataFrame(index=features.index)
    score = pd.Series(0.0, index=features.index)

    for column, weight in weights.items():
        if column not in features.columns:
            continue
        normalized = log1p_minmax(features[column])
        out[f"{column}_norm"] = normalized
        score = score + weight * normalized

    out["score"] = score
    return out
