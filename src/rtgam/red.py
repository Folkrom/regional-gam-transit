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


def snap_to_nodes(
    graph: nx.Graph,
    centroids: pd.DataFrame,
    max_snap_m: float = MAX_SNAP_M,
    chunk: int = 50,
) -> pd.Series:
    """Engancha cada centroide al nodo del grafo mas cercano.

    centroids: indexado por hex_id, columnas lat y lon.
    Devuelve: Series alineada con centroids, con el id del nodo o None si el
              mas cercano quedo a mas de max_snap_m.

    El None no es un descuido, es la guardia: un centroide a mas de 500 m de
    cualquier calle esta en el cerro o en el relleno. Engancharlo a la fuerza
    fabricaria accesibilidad al otro lado de una barrera, que es justo el tipo
    de numero equivocado y silencioso que ya costo caro en este proyecto.

    Va por bloques de hexagonos a proposito. La matriz completa serian 200 mil
    nodos por 724 centroides, ~1.2 GB, y haversine_m mantiene unas seis vivas a
    la vez: unos 7 GB. En DENUE ya se midio que el pico real de ese patron es
    muy superior a la cuenta ingenua.
    """
    if graph.number_of_nodes() == 0 or len(centroids) == 0:
        return pd.Series([None] * len(centroids), index=centroids.index, dtype=object)

    node_ids = list(graph.nodes)
    node_lat = np.array([graph.nodes[n]["lat"] for n in node_ids], dtype=float)
    node_lon = np.array([graph.nodes[n]["lon"] for n in node_ids], dtype=float)

    hex_lat = centroids["lat"].to_numpy(dtype=float)
    hex_lon = centroids["lon"].to_numpy(dtype=float)

    matched: list = []
    for start in range(0, len(centroids), chunk):
        block_lat = hex_lat[start : start + chunk]
        block_lon = hex_lon[start : start + chunk]
        distances = haversine_m(
            block_lat[:, None], block_lon[:, None], node_lat[None, :], node_lon[None, :]
        )
        nearest = distances.argmin(axis=1)
        nearest_distance = distances[np.arange(len(block_lat)), nearest]
        for position, distance in zip(nearest, nearest_distance):
            matched.append(node_ids[position] if distance <= max_snap_m else None)

    return pd.Series(matched, index=centroids.index, dtype=object)


def component_size_by_hex(graph: nx.Graph, snapped: pd.Series) -> pd.Series:
    """Nodos de la componente conexa a la que se engancho cada hexagono.

    snapped: Series indexada por hex_id, con el id del nodo o None.
    Devuelve: Series alineada con snapped, con el numero de nodos de la
              componente del nodo enganchado; 0 para los hexagonos sin
              enganche.

    Es diagnostico, no correccion. snap_to_nodes engancha al nodo mas cercano
    en linea recta sin mirar a que componente pertenece, y OSM trae fragmentos:
    calles reales digitalizadas sin unirlas al resto de la red. Un centroide
    que cae junto a uno de esos fragmentos recibe un alcance dos ordenes de
    magnitud por debajo del real —plausible, sin excepcion y sin aviso—, y como
    la normalizacion es min-max, ese minimo falso mueve tambien a los demas
    hexagonos.

    La regla de enganche NO se cambia: "el nodo mas cercano a menos de 500 m"
    es la especificada, y re-engancharla a la componente mayor moveria todos
    los numeros de la fuente bajo una regla que nadie aprobo. Lo que se hace es
    volver visible la condicion, que es la preferencia de este proyecto ante un
    numero plausible pero equivocado.
    """
    size_by_node: dict = {}
    for component in nx.connected_components(graph):
        size = len(component)
        for node in component:
            size_by_node[node] = size

    values = [0 if node is None else size_by_node.get(node, 0) for node in snapped]
    return pd.Series(values, index=snapped.index, dtype=int)


def reach_from_snapped(
    graph: nx.Graph, snapped: pd.Series, cutoff: float = WALK_CUTOFF_M
) -> pd.Series:
    """Alcance de cada hexagono a partir de su nodo ya enganchado.

    Va separada del enganche porque enganchar es la parte cara —200 mil nodos
    por 724 centroides— y el script necesita las dos cosas: la Series de
    enganches, para reportar cuantos hexagonos se quedaron sin calle cerca, y
    el alcance. Con una sola funcion habria que engancharlos dos veces.

    Los hexagonos sin enganche dan 0.0, no NaN: merge_features lanza ante
    cualquier NaN de una fuente, y aqui el cero es informacion real (no hay
    calle a menos de 500 m), no un hueco de join.
    """
    values = [
        0.0 if node is None else reach_m(graph, node, cutoff=cutoff) for node in snapped
    ]
    return pd.Series(values, index=snapped.index, dtype=float)
