"""Fuente 4: densidad de poblacion y nivel socioeconomico del censo 2020.

Entrada: se descargan solos (13 MB del INEGI + 7.5 MB de la CDMX)
         + data/processed/gam_hexes.parquet
Salida:  data/processed/censo.parquet

Uso:
    uv run python scripts/05_censo.py [--force]

Tarda un par de minutos: el CSV del censo son 44 MB. Correr en primer plano,
no en background.
"""

import argparse
from pathlib import Path

import h3
import pandas as pd

from rtgam.sources.censo import (
    ageb_from_censo,
    fetch_ageb_polygons,
    fetch_censo,
    nse_index,
    to_hex_features,
)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
GEOJSON_CACHE = RAW / "ageb_cdmx.geojson"
HEXES = ROOT / "data" / "processed" / "gam_hexes.parquet"
OUTPUT = ROOT / "data" / "processed" / "censo.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-descargar aunque exista cache"
    )
    args = parser.parse_args()

    print("Descargando el censo por AGEB (13 MB, el CSV son 44 MB)...")
    crudo = fetch_censo(RAW, force=args.force)
    ageb = ageb_from_censo(crudo)
    print(f"AGEB de GAM en el censo: {len(ageb)}")
    print(f"Poblacion total: {ageb['pobtot'].sum():,.0f}")

    print("Descargando los poligonos de AGEB (7.5 MB)...")
    polygons = fetch_ageb_polygons(GEOJSON_CACHE, force=args.force)
    print(f"AGEB de GAM con geometria: {len(polygons)}")

    # Guardia de cruce. Un AGEB con censo pero sin poligono no tiene donde
    # aterrizar; uno con poligono pero sin censo pintaria un hueco de datos
    # como si fuera un descampado real. to_hex_features vuelve a comprobarlo,
    # pero aqui el mensaje sale antes y con contexto.
    solo_censo = sorted(set(ageb.index) - set(polygons))
    solo_geo = sorted(set(polygons) - set(ageb.index))
    if solo_censo or solo_geo:
        raise ValueError(
            f"Las claves de AGEB no cuadran. Con censo y sin poligono: "
            f"{solo_censo[:5]}. Con poligono y sin censo: {solo_geo[:5]}."
        )

    nse = nse_index(ageb)
    sin_nse = ageb.index[nse.isna()]
    print(f"AGEB sin nivel socioeconomico: {len(sin_nse)} ({list(sin_nse)})")
    colectivas = ageb.index[ageb[["internet", "automovil", "escolaridad"]].isna().all(axis=1)]
    poblacion_colectiva = ageb.loc[colectivas, "pobtot"].sum()
    print(
        f"Poblacion en AGEB sin ningun componente de NSE: "
        f"{poblacion_colectiva:,.0f} habitantes "
        f"(vivienda colectiva mas confidenciales)"
    )

    hexes = pd.read_parquet(HEXES)
    features = to_hex_features(hexes, ageb, polygons)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(OUTPUT)

    area_km2 = pd.Series(
        {hex_id: h3.cell_area(hex_id, "km^2") for hex_id in features.index}
    )
    repartida = (features["densidad_pob"] * area_km2).sum()
    print()
    print(
        f"Poblacion repartida a la reticula: {repartida:,.0f} de "
        f"{ageb['pobtot'].sum():,.0f} ({repartida / ageb['pobtot'].sum():.1%})"
    )
    for columna in ["densidad_pob", "nivel_socioeconomico"]:
        serie = features[columna]
        print(
            f"{columna}: {(serie > 0).sum()} de {len(serie)} hexagonos con senal "
            f"| media {serie.mean():.4f} | min {serie.min():.4f} "
            f"| max {serie.max():.4f}"
        )
    print()
    print("Top 5 por densidad_pob:")
    print(features.nlargest(5, "densidad_pob").to_string())
    print(f"Escrito: {OUTPUT}")


if __name__ == "__main__":
    main()
