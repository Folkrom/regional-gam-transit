"""Fuente 3: accesibilidad peatonal y atractores de espacio publico desde OSM.

Entrada: se descarga sola (Overpass) + data/processed/gam_hexes.parquet
Salida:  data/processed/osm.parquet

Uso:
    uv run python scripts/04_osm.py [--force]

Tarda varios minutos: la red caminable de GAM son ~33 mil vias. Correr en
primer plano, no en background.
"""

import argparse
from pathlib import Path

import networkx as nx
import pandas as pd

from rtgam.boundary import fetch_gam_polygon
from rtgam.red import (
    MAX_SNAP_M,
    WALK_CUTOFF_M,
    build_graph,
    component_size_by_hex,
    reach_from_snapped,
    snap_to_nodes,
)
from rtgam.sources.osm import (
    attractors_from_overpass,
    build_attractor_query,
    build_network_query,
    fetch_overpass,
    to_hex_features,
)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BOUNDARY = RAW / "gam_boundary.geojson"
RED_CACHE = RAW / "osm_red_peatonal.json"
ATRACTORES_CACHE = RAW / "osm_atractores.json"
HEXES = ROOT / "data" / "processed" / "gam_hexes.parquet"
OUTPUT = ROOT / "data" / "processed" / "osm.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-descargar aunque exista cache"
    )
    args = parser.parse_args()

    polygon = fetch_gam_polygon(BOUNDARY)
    minx, miny, maxx, maxy = polygon.bounds
    # Overpass espera (sur, oeste, norte, este); shapely da (oeste, sur, este, norte).
    bbox = (miny, minx, maxy, maxx)
    print(f"Bounding box: {bbox[0]:.4f},{bbox[1]:.4f},{bbox[2]:.4f},{bbox[3]:.4f}")

    print("Descargando la red caminable (son decenas de MB, tarda)...")
    red = fetch_overpass(build_network_query(bbox), RED_CACHE, force=args.force)
    graph = build_graph(red)
    print(f"Grafo: {graph.number_of_nodes():,} nodos, {graph.number_of_edges():,} aristas")

    print("Descargando atractores...")
    payload = fetch_overpass(
        build_attractor_query(bbox), ATRACTORES_CACHE, force=args.force
    )

    # Guardia contra la regresion de consultar solo `way`. El Bosque de San Juan
    # de Aragon existe SOLO como relation, asi que si el parseo dejara de
    # aceptarlas, el conteo de relations caeria a cero y el parque mas grande de
    # la alcaldia desapareceria del mapa sin que nada fallara.
    relations = sum(1 for e in payload["elements"] if e.get("type") == "relation")
    if relations == 0:
        raise ValueError(
            "Overpass no devolvio ni una relation. La consulta debe usar `nwr`, "
            "no `way`: los parques grandes de GAM son relations."
        )

    atractores = attractors_from_overpass(payload)
    print(f"Atractores: {len(atractores):,} (de {relations} relations en el payload)")
    print(atractores["osm_kind"].value_counts().to_string())

    hexes = pd.read_parquet(HEXES)

    # El enganche se calcula UNA vez y se reusa: es la parte cara del script,
    # 200 mil nodos por 724 centroides.
    enganches = snap_to_nodes(graph, hexes)
    sin_enganche = int(enganches.isna().sum())
    print(
        f"Hexagonos sin calle a menos de {MAX_SNAP_M:.0f} m: {sin_enganche} de {len(hexes)}"
    )

    # El enganche va al nodo mas cercano en linea recta, sin mirar a que
    # componente pertenece. Un centroide que cae junto a un fragmento suelto de
    # OSM sale con un alcance dos ordenes de magnitud por debajo del real, sin
    # que nada lance. No se cambia la regla; se imprime a quien le paso.
    mayor = max((len(c) for c in nx.connected_components(graph)), default=0)
    tamanos = component_size_by_hex(graph, enganches)
    fuera = tamanos[(tamanos > 0) & (tamanos < mayor)].sort_values()
    print(
        f"Componente mayor del grafo: {mayor:,} nodos de "
        f"{graph.number_of_nodes():,} ({nx.number_connected_components(graph)} componentes)"
    )
    print(
        f"Hexagonos enganchados FUERA de la componente mayor: {len(fuera)} de {len(hexes)}"
    )
    for hex_id, tamano in fuera.items():
        print(f"  {hex_id}: componente de {tamano} nodos (su alcance sale subestimado)")

    print(f"Calculando alcance a {WALK_CUTOFF_M:.0f} m por la red...")
    alcance = reach_from_snapped(graph, enganches)

    features = to_hex_features(hexes, alcance, atractores)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(OUTPUT)

    print()
    for columna in ["accesibilidad_peatonal", "atractores_osm"]:
        serie = features[columna]
        print(
            f"{columna}: {(serie > 0).sum()} de {len(serie)} hexagonos con senal "
            f"| media {serie.mean():.2f} | max {serie.max():.2f}"
        )
    print()
    print("Top 5 por accesibilidad_peatonal:")
    print(features.nlargest(5, "accesibilidad_peatonal").to_string())
    print(f"Escrito: {OUTPUT}")


if __name__ == "__main__":
    main()
