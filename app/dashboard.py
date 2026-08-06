"""Dashboard de puntuacion de ubicaciones para cafeteria en GAM.

Uso:
    uv run streamlit run app/dashboard.py
"""

from pathlib import Path

import branca.colormap as cm
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from rtgam.score import load_weights
from rtgam.viz import hex_polygon_latlon, rescore

ROOT = Path(__file__).resolve().parents[1]
SCORES = ROOT / "data" / "processed" / "hex_scores.parquet"

GAM_CENTER = (19.52, -99.11)

st.set_page_config(page_title="Cafeteria GAM", layout="wide")


@st.cache_data
def load_scores() -> pd.DataFrame:
    return pd.read_parquet(SCORES)


def main() -> None:
    st.title("Atractivo de ubicacion para cafeteria — Gustavo A. Madero")

    if not SCORES.exists():
        st.error(f"Falta {SCORES}. Corre primero: uv run python scripts/99_score.py")
        return

    scores = load_scores()
    default_weights = load_weights()

    st.sidebar.header("Pesos")
    st.sidebar.caption(
        "Solo las variables con datos cargados aparecen aqui. "
        "El recalculo es instantaneo: las columnas ya estan normalizadas."
    )

    weights = {}
    for name, default in default_weights.items():
        if f"{name}_norm" not in scores.columns:
            continue
        weights[name] = st.sidebar.slider(name, -1.0, 1.0, float(default), 0.05)

    if not weights:
        st.warning("No hay ninguna variable con datos. Corre los scripts de ingestion.")
        return

    scores = scores.copy()
    scores["score"] = rescore(scores, weights)

    left, right = st.columns([3, 2])

    with left:
        colormap = cm.linear.YlOrRd_09.scale(
            float(scores["score"].min()), float(scores["score"].max())
        )
        fmap = folium.Map(location=GAM_CENTER, zoom_start=12, tiles="cartodbpositron")

        for hex_id, row in scores.iterrows():
            folium.Polygon(
                locations=hex_polygon_latlon(hex_id),
                color=None,
                fill=True,
                fill_color=colormap(row["score"]),
                fill_opacity=0.6,
                tooltip=f"{hex_id}<br>score {row['score']:.3f}",
            ).add_to(fmap)

        colormap.add_to(fmap)
        st_folium(fmap, height=600, use_container_width=True)

    with right:
        st.subheader("Top 20 hexagonos")
        norm_columns = [c for c in scores.columns if c.endswith("_norm")]
        st.dataframe(
            scores.nlargest(20, "score")[["score"] + norm_columns].round(3),
            use_container_width=True,
        )
        st.caption(
            "Las columnas _norm muestran por que gano cada hexagono, no solo que gano. "
            "Sin ground truth, el juicio humano sobre este desglose es la validacion."
        )


if __name__ == "__main__":
    main()
