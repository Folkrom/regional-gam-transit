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
