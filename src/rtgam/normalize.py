"""Normalizacion de variables antes de combinarlas en el score."""

import numpy as np
import pandas as pd


def log1p_minmax(s: pd.Series) -> pd.Series:
    """Aplica log(1+x) y escala el resultado al rango [0, 1].

    log1p doma la cola larga de la afluencia, donde una estacion como Indios
    Verdes aplastaria a todas las demas bajo un min-max crudo. El min-max
    posterior deja todas las variables en la misma escala, lo que hace que los
    pesos del score sean comparables entre si.

    Casos borde: si la serie es constante (incluida la de puros ceros) devuelve
    ceros en vez de NaN, porque max - min seria cero. Los valores negativos se
    recortan a cero: ninguna variable del score puede ser negativa, asi que un
    negativo es dato sucio, y log1p por debajo de -1 produce NaN.
    """
    if len(s) == 0:
        return s.astype(float)

    values = np.log1p(s.astype(float).clip(lower=0.0))
    low, high = values.min(), values.max()
    if not np.isfinite(low) or not np.isfinite(high) or high == low:
        return pd.Series(0.0, index=s.index)
    return (values - low) / (high - low)
