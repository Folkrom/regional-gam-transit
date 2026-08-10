"""Red peatonal: grafo de calles, alcance por la red y enganche de centroides.

Es una primitiva al mismo nivel que geo.py, no una fuente. No sabe nada de
hexagonos de GAM ni de columnas del score.

El grafo NO se simplifica topologicamente: cada nodo de OSM es un nodo del
grafo, sin colapsar los nodos de paso ni detectar intersecciones. Se puede
porque solo hay 724 origenes, no 200 mil: cada Dijkstra va acotado a 800 m y
explora unos pocos miles de nodos. Simplificar seria trabajo extra y, sobre
todo, una heuristica mas que equivocar.
"""

import networkx as nx
import numpy as np
import pandas as pd

from rtgam.geo import haversine_m


def build_graph(payload: dict) -> nx.Graph:
    """Arma el grafo de calles a partir de una respuesta de Overpass.

    Espera elementos `way` pedidos con `out geom;`, que traen `nodes` (ids) y
    `geometry` (coordenadas) alineados por indice. Verificado contra el
    servidor real.

    Los ids de nodo se comparten entre vias, asi que usarlos como clave conecta
    la red sola: no hace falta detectar intersecciones.

    Nodos: id de OSM, con atributos lat y lon.
    Aristas: atributo length en metros.
    """
    graph = nx.Graph()

    for element in payload.get("elements", []):
        if element.get("type") != "way":
            continue

        node_ids = element.get("nodes")
        geometry = element.get("geometry")
        if not node_ids or not geometry:
            continue

        if len(node_ids) != len(geometry):
            raise ValueError(
                f"La via {element.get('id')} trae nodes y geometry desalineadas "
                f"({len(node_ids)} contra {len(geometry)}). La consulta debe "
                f"pedir 'out geom;' y este codigo asume que van pareadas."
            )

        for node_id, point in zip(node_ids, geometry):
            graph.add_node(node_id, lat=float(point["lat"]), lon=float(point["lon"]))

        for a, b in zip(node_ids, node_ids[1:]):
            if a == b:
                continue
            length = float(
                haversine_m(
                    graph.nodes[a]["lat"],
                    graph.nodes[a]["lon"],
                    graph.nodes[b]["lat"],
                    graph.nodes[b]["lon"],
                )
            )
            graph.add_edge(a, b, length=length)

    return graph


# Mismo corte que el kernel de decaimiento de geo.py, pero medido por la red y
# no en linea recta. 800 m son unos diez minutos caminando.
WALK_CUTOFF_M = 800.0

# Si el nodo mas cercano a un centroide queda mas lejos que esto, el hexagono
# se reporta sin enganche en vez de pegarse a la fuerza. Ver snap_to_nodes.
MAX_SNAP_M = 500.0


def reach_m(graph: nx.Graph, source, cutoff: float = WALK_CUTOFF_M) -> float:
    """Metros de calle alcanzables desde `source` recorriendo `cutoff` por la red.

    Suma la longitud de las aristas con AMBOS extremos dentro del corte. Ambos,
    no uno: una arista de 400 m que se sale del radio no es calle alcanzada.
    El subgrafo inducido de networkx ya aplica exactamente esa regla.

    Es reach centrality de Urban Network Analysis. Se prefirio sobre
    betweenness porque betweenness exacta sobre este grafo son horas, y porque
    sobre un grafo recortado infla las rutas que cruzan el corte.
    """
    reachable = nx.single_source_dijkstra_path_length(
        graph, source, cutoff=cutoff, weight="length"
    )
    subgraph = graph.subgraph(reachable.keys())
    return float(sum(length for _, _, length in subgraph.edges(data="length")))
