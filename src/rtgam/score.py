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


def merge_features(
    gam_hexes: pd.DataFrame, feature_frames: list[pd.DataFrame]
) -> pd.DataFrame:
    """Une las columnas de todas las fuentes sobre el grid completo de GAM.

    Los hexagonos que una fuente no cubre quedan en cero, no en NaN: la
    ausencia de dato aqui significa ausencia del fenomeno (cero estaciones
    cerca, cero competencia), no dato faltante.

    Un NaN que trae la fuente NO es un hueco del join: rellenar los dos con
    cero borra la diferencia entre "hexagono ausente" y "bug de datos". Si
    una fuente cubre un hexagono y aun asi calculo NaN, eso es un bug, igual
    que en accumulate_decay. Se falla ruidoso.

    Se descartan lat y lon: la geometria se regenera de hex_id, y guardarla
    en la tabla de features la duplicaria con riesgo de desincronizarse.
    """
    out = pd.DataFrame(index=gam_hexes.index)
    for frame in feature_frames:
        # Un NaN que trae la fuente NO es lo mismo que un hueco del join, y
        # rellenar los dos con cero borra la diferencia. Si una fuente cubre
        # un hexagono y aun asi calculo NaN, eso es un bug de datos, igual que
        # en accumulate_decay. Se falla ruidoso antes de que el cero mentiroso
        # entre al score.
        missing = int(frame.isna().sum().sum())
        if missing:
            raise ValueError(
                f"La fuente con columnas {list(frame.columns)} trae {missing} "
                "valores NaN en hexagonos que si cubre. Un hueco del join se "
                "rellena con cero; un NaN de la fuente es un bug de datos."
            )
        # reindex con fill_value rellena SOLO las etiquetas que la fuente no
        # tiene. Los hexagonos que si cubre llegan con su valor tal cual.
        out = out.join(frame.reindex(gam_hexes.index, fill_value=0.0), how="left")
    return out
