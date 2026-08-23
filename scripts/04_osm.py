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
from rtgam.geo import DECAY_CUTOFF_M, bbox_with_margin
from rtgam.red import (
    MAX_SNAP_M,
    WALK_CUTOFF_M,
    build_graph,
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
# El margen del bbox va en el NOMBRE de la cache a proposito. Con el nombre de
# antes, una cache bajada sin margen se reusaria tal cual bajo el codigo nuevo:
# el margen quedaria escrito en la consulta y ausente en los datos, sin que
# nada fallara y con el bug del borde intacto.
RED_CACHE = RAW / "osm_red_peatonal_800m.json"
# Nombre distinto al de la cache vieja a proposito. Aquella se bajo con
# `out tags center` y no trae poligonos: reusarla dejaria de detectar el
# anidamiento y devolveria los 1,776 atractores sin colapsar, en silencio.
ATRACTORES_CACHE = RAW / "osm_atractores_geom_800m.json"
HEXES = ROOT / "data" / "processed" / "gam_hexes.parquet"
OUTPUT = ROOT / "data" / "processed" / "osm.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-descargar aunque exista cache"
    )
    args = parser.parse_args()

    polygon = fetch_gam_polygon(BOUNDARY)
    # Con el margen de 800 m: una calle o un parque justo afuera del limite
    # sirven igual a un hexagono del borde. Sin el, la consulta reproduce el
    # bug que DENUE tenia por filtrar por municipio.
    bbox = bbox_with_margin(polygon.bounds)
    print(f"Bounding box +{DECAY_CUTOFF_M:.0f} m: "
          f"{bbox[0]:.4f},{bbox[1]:.4f},{bbox[2]:.4f},{bbox[3]:.4f}")

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

    # Guardia contra volver a `out tags center`. Sin poligonos no hay forma de
    # saber que atractor cae dentro de cual, y el anidamiento regresaria sin que
    # nada fallara: el Deportivo Hermanos Galeana volveria a contar 59 veces.
    con_geometria = sum(
        1 for e in payload["elements"] if e.get("geometry") or e.get("members")
    )
    if con_geometria == 0:
        raise ValueError(
            "Ningun elemento trae geometria. La consulta debe pedir `out geom`, "
            "no `out tags center`: sin poligonos no se detecta el anidamiento."
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

    # Los nodos fuera de la componente mayor no se usan para enganchar: son
    # fragmentos de OSM, calles digitalizadas sin unir al resto de la red, y el
    # alcance medido sobre uno de ellos mide el hueco, no la caminabilidad.
    mayor = max((len(c) for c in nx.connected_components(graph)), default=0)
    print(
        f"Componente mayor del grafo: {mayor:,} nodos de "
        f"{graph.number_of_nodes():,} ({nx.number_connected_components(graph)} componentes). "
        f"El resto no se usa para enganchar."
    )

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
