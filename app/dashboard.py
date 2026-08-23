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

from rtgam.colonias import SIN_COLONIA
from rtgam.score import load_weights
from rtgam.viz import hex_polygon_latlon, rescore

ROOT = Path(__file__).resolve().parents[1]
SCORES = ROOT / "data" / "processed" / "hex_scores.parquet"
COLONIAS = ROOT / "data" / "processed" / "hex_colonias.parquet"

GAM_CENTER = (19.52, -99.11)

st.set_page_config(page_title="Cafeteria GAM", layout="wide")


@st.cache_data
def load_scores() -> pd.DataFrame:
    return pd.read_parquet(SCORES)


@st.cache_data
def load_colonias() -> pd.DataFrame | None:
    """Etiqueta de colonia por hexagono, si scripts/06_colonias.py ya corrio."""
    if not COLONIAS.exists():
        return None
    return pd.read_parquet(COLONIAS)


def colonia_filter(scores: pd.DataFrame) -> pd.DataFrame:
    """Multiselect de colonias que esconde hexagonos del mapa.

    Es un filtro de VISTA y se aplica al final, sobre el frame ya puntuado:
    los scores no se recalculan. Filtrar antes de normalizar estiraria cada
    variable a 0-1 dentro del subconjunto elegido, lo que re-ordena los
    hexagonos y amplifica ruido al rango completo. Filtrando aqui, el score
    sigue significando "contra toda GAM" y el rank 219 sigue siendo 219.

    Las colonias sin ningun hexagono no se listan: 38 de las 232 de GAM son mas
    chicas que una celda res 9, y ofrecer una que devuelve un mapa vacio es
    peor que no ofrecerla. Los 12 hexagonos que no caen en ninguna colonia si
    aparecen, bajo la etiqueta de SIN_COLONIA.
    """
    colonias = load_colonias()
    st.sidebar.header("Colonias")
    if colonias is None:
        st.sidebar.caption(
            "Sin filtro por colonia. Para activarlo: "
            "uv run python scripts/06_colonias.py"
        )
        return scores

    etiquetas = colonias["colonia"].reindex(scores.index).fillna(SIN_COLONIA)
    opciones = sorted(etiquetas.unique())
    elegidas = st.sidebar.multiselect(
        "Mostrar solo", opciones, default=opciones, label_visibility="collapsed"
    )
    con_hexagonos = len([o for o in opciones if o != SIN_COLONIA])
    st.sidebar.caption(
        f"{con_hexagonos} colonias con al menos un hexagono. "
        "El filtro solo esconde: los scores siguen calculados contra toda GAM."
    )
    return scores[etiquetas.isin(elegidas)]


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
    # El rank se fija ANTES de filtrar, sobre los 724 hexagonos. Es el numero
    # que el filtro no debe mover: si se recalculara dentro del subconjunto,
    # cualquier colonia tendria su propio "puesto 1" y no querria decir nada.
    scores["rank"] = scores["score"].rank(ascending=False, method="min").astype(int)

    # La escala de color tambien se ancla al total, por lo mismo: un mapa
    # filtrado a colonias mediocres debe verse palido, no recolorearse hasta
    # que su mejor hexagono parezca el mejor de la alcaldia.
    colormap = cm.linear.YlOrRd_09.scale(
        float(scores["score"].min()), float(scores["score"].max())
    )

    vista = colonia_filter(scores)
    if vista.empty:
        st.warning("Ninguna colonia seleccionada.")
        return

    left, right = st.columns([3, 2])

    with left:
        fmap = folium.Map(location=GAM_CENTER, zoom_start=12, tiles="cartodbpositron")

        for hex_id, row in vista.iterrows():
            folium.Polygon(
                locations=hex_polygon_latlon(hex_id),
                color=None,
                fill=True,
                fill_color=colormap(row["score"]),
                fill_opacity=0.6,
                tooltip=f"{hex_id}<br>score {row['score']:.3f}<br>rank {row['rank']} de {len(scores)}",
            ).add_to(fmap)

        # Con un subconjunto chico el encuadre de toda GAM lo deja invisible.
        if len(vista) < len(scores):
            latitudes = [lat for h in vista.index for lat, _ in hex_polygon_latlon(h)]
            longitudes = [lon for h in vista.index for _, lon in hex_polygon_latlon(h)]
            fmap.fit_bounds(
                [[min(latitudes), min(longitudes)], [max(latitudes), max(longitudes)]]
            )

        colormap.add_to(fmap)
        st_folium(fmap, height=600, use_container_width=True)

    with right:
        st.subheader(f"Top 20 hexagonos de {len(vista)}")
        norm_columns = [c for c in scores.columns if c.endswith("_norm")]
        # width="stretch" reemplaza al use_container_width=True que Streamlit
        # deprecó. Ojo: el use_container_width de st_folium de arriba NO es el
        # mismo parámetro, es API propia de streamlit-folium y ahí sigue siendo
        # el correcto (su `width` son píxeles, no un modo de ancho).
        st.dataframe(
            vista.nlargest(20, "score")[["rank", "score"] + norm_columns].round(3),
            width="stretch",
        )
        st.caption(
            "Las columnas _norm muestran por que gano cada hexagono, no solo que gano. "
            "Sin ground truth, el juicio humano sobre este desglose es la validacion. "
            "`rank` es el puesto contra los 724 hexagonos de GAM, no dentro del filtro."
        )


if __name__ == "__main__":
    main()
