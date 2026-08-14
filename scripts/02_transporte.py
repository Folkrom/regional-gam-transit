"""Fuente 1: afluencia y presencia de transporte sobre los hexagonos.

Entrada:  data/raw/afluencia_*.csv, data/processed/gam_hexes.parquet
Salida:   data/processed/transporte.parquet
Auxiliar: data/interim/station_name_map.csv (revisable a mano)

Uso:
    uv run python scripts/02_transporte.py [--force] [--year 2025]
"""

import argparse
import glob
from pathlib import Path

import pandas as pd

from rtgam.sources.transporte import (
    fetch_stations,
    fix_mojibake,
    propose_name_map,
    to_hex_features,
    weekday_mean_by_station,
)

ROOT = Path(__file__).resolve().parents[1]
HEXES = ROOT / "data" / "processed" / "gam_hexes.parquet"
STATIONS_CACHE = ROOT / "data" / "raw" / "osm_stations.json"
NAME_MAP = ROOT / "data" / "interim" / "station_name_map.csv"
OUTPUT = ROOT / "data" / "processed" / "transporte.parquet"
OUTPUT_VIEJO = ROOT / "data" / "processed" / "flujo_transporte.parquet"

# Nombres verificados contra el CSV real del portal de la CDMX.
DATE_COL = "fecha"
STATION_COL = "estacion"
VALUE_COL = "afluencia"

# LIMITACION CONOCIDA DE LA FUENTE
# Solo el Metro (STC) publica afluencia por estacion. Metrobus, Cablebus,
# Tren Ligero y Trolebus publican unicamente totales por linea, asi que no
# se pueden repartir sobre hexagonos sin inventar el reparto.
#
# Por eso esta fuente emite dos columnas y no una: flujo_transporte mide
# volumen y solo existe para el Metro, y presencia_transporte mide cercania
# a una estacion de riel o cable, que si existe para todos. El corredor del
# Cablebus Linea 1 tenia flujo exactamente cero en sus 91 hexagonos (los que
# tienen presencia de una estacion clase cable y flujo_transporte en cero).
#
# Lo que sigue sin haber es cuanta gente usa el Cablebus: la presencia dice
# que la estacion esta ahi, no que este llena.

# Buffer de 1 km alrededor de GAM: una estacion justo afuera del limite
# alimenta hexagonos de GAM de verdad, y filtrarla dejaria el borde
# falsamente muerto. Un grado de latitud son ~111 km.
BUFFER_DEG = 1000.0 / 111_000.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-descargar aunque exista cache")
    parser.add_argument("--year", type=int, default=2025, help="ultimo ano completo")
    args = parser.parse_args()

    hexes = pd.read_parquet(HEXES)

    bbox = (
        hexes["lat"].min() - BUFFER_DEG,
        hexes["lon"].min() - BUFFER_DEG,
        hexes["lat"].max() + BUFFER_DEG,
        hexes["lon"].max() + BUFFER_DEG,
    )
    osm_stations = fetch_stations(bbox, STATIONS_CACHE, force=args.force)
    print(f"Estaciones en OSM dentro de GAM + 1 km: {len(osm_stations)}")

    csv_paths = sorted(glob.glob(str(ROOT / "data" / "raw" / "afluencia_*.csv")))
    if not csv_paths:
        raise SystemExit(
            "No hay data/raw/afluencia_*.csv. Ver README.md: se baja a mano "
            "de https://datos.cdmx.gob.mx"
        )
    daily = pd.concat([pd.read_csv(path) for path in csv_paths], ignore_index=True)
    daily[STATION_COL] = daily[STATION_COL].map(fix_mojibake)

    # Reportar fechas ilegibles antes de filtrar. Sobre 1.17 millones de filas,
    # un cambio de formato en el portal se comeria parte de la muestra sin que
    # nada avisara.
    unparsed = int(pd.to_datetime(daily[DATE_COL], errors="coerce").isna().sum())
    if unparsed:
        print(f"AVISO: {unparsed} filas con fecha ilegible, excluidas "
              f"({unparsed / len(daily) * 100:.2f}% del total)")

    afluencia = weekday_mean_by_station(
        daily, year=args.year, date_col=DATE_COL, station_col=STATION_COL, value_col=VALUE_COL
    )
    print(f"Estaciones con afluencia en {args.year}: {len(afluencia)}")

    if NAME_MAP.exists():
        name_map = pd.read_csv(NAME_MAP)
        print(f"Usando mapa de nombres revisado: {NAME_MAP}")
    else:
        name_map = propose_name_map(afluencia["afluencia_name"], osm_stations["osm_name"])
        NAME_MAP.parent.mkdir(parents=True, exist_ok=True)
        name_map.to_csv(NAME_MAP, index=False)
        print(f"Mapa de nombres propuesto escrito en {NAME_MAP} — REVISALO A MANO")

    merged = (
        afluencia.merge(name_map, on="afluencia_name", how="left")
        .merge(osm_stations, on="osm_name", how="inner")
    )

    dropped = len(afluencia) - len(merged)
    if dropped:
        missing = set(afluencia["afluencia_name"]) - set(merged["afluencia_name"])
        print(f"AVISO: {dropped} estaciones sin coordenada, excluidas:")
        for name in sorted(missing):
            print(f"  - {name}")

    pendientes = name_map["osm_name"].isna().sum()
    if pendientes > 0:
        print(f"Pendientes de revision humana en {NAME_MAP}: {pendientes}")

    features = to_hex_features(hexes, merged, osm_stations)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(OUTPUT)

    # El parquet cambio de nombre. Si el viejo sobrevive, 99_score.py NO lo
    # carga (ya no esta en SOURCE_FILES), pero queda un archivo obsoleto
    # pareciendo dato vigente. Se borra.
    if OUTPUT_VIEJO.exists():
        OUTPUT_VIEJO.unlink()
        print(f"Borrado el parquet viejo: {OUTPUT_VIEJO}")

    flow = features["flujo_transporte"]
    pres = features["presencia_transporte"]
    print()
    print(f"Hexagonos: {len(flow)}  con flujo > 0: {(flow > 0).sum()}")
    print(f"flujo      min {flow.min():.1f}  media {flow.mean():.1f}  max {flow.max():.1f}")
    print(f"Hexagonos con presencia > 0: {(pres > 0).sum()}")
    print(f"presencia  min {pres.min():.4f}  media {pres.mean():.4f}  max {pres.max():.4f}")

    por_clase = osm_stations["osm_class"].value_counts(dropna=False)
    print(f"Estaciones por clase: {por_clase.to_dict()}")

    solo_presencia = int(((pres > 0) & (flow == 0)).sum())
    print(f"Hexagonos que solo la presencia ve (flujo cero): {solo_presencia}")

    print("Top 5 por flujo:")
    print(flow.nlargest(5).to_string())
    print(f"Escrito: {OUTPUT}")


if __name__ == "__main__":
    main()
