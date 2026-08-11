"""Alcance por la red: metros de calle alcanzables desde un nodo."""

import networkx as nx
import pytest

from rtgam.red import WALK_CUTOFF_M, reach_m


def camino(longitudes):
    """Grafo en linea: nodo 0 - 1 - 2 - ... con las longitudes dadas."""
    graph = nx.Graph()
    for i, length in enumerate(longitudes):
        graph.add_edge(i, i + 1, length=float(length))
    return graph


def test_alcance_dentro_del_corte_suma_todas_las_aristas():
    graph = camino([300, 300])
    assert reach_m(graph, 0, cutoff=800) == pytest.approx(600.0)


def test_una_arista_con_un_extremo_fuera_del_corte_no_suma():
    # Distancias desde 0: nodo1=300, nodo2=600, nodo3=900.
    # El nodo 3 queda fuera, asi que la arista 2-3 NO cuenta aunque su otro
    # extremo si este dentro. La regla es ambos extremos, no uno.
    graph = camino([300, 300, 300])
    assert reach_m(graph, 0, cutoff=800) == pytest.approx(600.0)


def test_subir_el_corte_incluye_la_arista_que_faltaba():
    graph = camino([300, 300, 300])
    assert reach_m(graph, 0, cutoff=1000) == pytest.approx(900.0)


def test_el_alcance_usa_la_distancia_por_la_red_no_la_linea_recta():
    # Dos nodos vecinos en el mapa pero unidos solo por un rodeo largo, que es
    # justo lo que pasa a los lados del Rio de los Remedios: se cruza por el
    # puente o no se cruza.
    graph = nx.Graph()
    graph.add_edge("a", "rodeo", length=700.0)
    graph.add_edge("rodeo", "b", length=700.0)
    assert reach_m(graph, "a", cutoff=800) == pytest.approx(700.0)


def test_un_nodo_aislado_alcanza_cero():
    graph = nx.Graph()
    graph.add_node("solo")
    assert reach_m(graph, "solo", cutoff=800) == pytest.approx(0.0)


def test_el_corte_por_defecto_son_800_metros():
    assert WALK_CUTOFF_M == 800.0


import pandas as pd

from rtgam.red import (
    MAX_SNAP_M,
    reach_from_snapped,
    snap_to_nodes,
)


def alcance_de(graph, cent):
    """Las dos partes juntas, tal como las encadena scripts/04_osm.py."""
    return reach_from_snapped(graph, snap_to_nodes(graph, cent))


def grafo_con_coords():
    """Dos calles separadas: una cerca del hexagono A, otra lejos."""
    graph = nx.Graph()
    graph.add_node(1, lat=19.5000, lon=-99.1000)
    graph.add_node(2, lat=19.5000, lon=-99.0990)  # ~104.8 m al este del 1
    graph.add_edge(1, 2, length=104.8)
    return graph


def centroides(filas):
    frame = pd.DataFrame(filas, columns=["hex_id", "lat", "lon"])
    return frame.set_index("hex_id")


def test_el_centroide_se_engancha_al_nodo_mas_cercano():
    graph = grafo_con_coords()
    cent = centroides([("a", 19.50005, -99.0990)])
    enganche = snap_to_nodes(graph, cent)
    assert enganche.loc["a"] == 2


def test_un_centroide_a_600_metros_no_se_engancha():
    # 0.0054 grados de latitud son ~600 m: pasado el umbral, pero cerca de el.
    # Un caso a 5 km probaria mucho menos.
    graph = grafo_con_coords()
    cent = centroides([("lejos", 19.50540, -99.1000)])
    enganche = snap_to_nodes(graph, cent)
    assert enganche.loc["lejos"] is None


def test_un_centroide_a_400_metros_si_se_engancha():
    # El control positivo del umbral. Sin esta prueba, un snap_to_nodes que
    # devolviera None siempre pasaria la prueba de arriba.
    graph = grafo_con_coords()
    cent = centroides([("cerca", 19.50360, -99.1000)])
    assert snap_to_nodes(graph, cent).loc["cerca"] == 1


def test_el_enganche_maximo_son_500_metros():
    assert MAX_SNAP_M == 500.0


def test_el_alcance_por_hexagono_respeta_el_enganche():
    graph = grafo_con_coords()
    cent = centroides(
        [("cerca", 19.50005, -99.09995), ("lejos", 19.50540, -99.1000)]
    )
    alcance = alcance_de(graph, cent)
    assert alcance.loc["cerca"] == pytest.approx(104.8)
    assert alcance.loc["lejos"] == pytest.approx(0.0)


def test_el_alcance_por_hexagono_no_trae_nan():
    # merge_features lanza si una fuente trae NaN, y con razon: un NaN en el
    # producto punto ensucia todos los hexagonos, no solo el suyo.
    graph = grafo_con_coords()
    cent = centroides([("a", 19.50005, -99.09995), ("b", 19.5100, -99.1000)])
    alcance = alcance_de(graph, cent)
    assert not alcance.isna().any()
    assert list(alcance.index) == ["a", "b"]


def test_el_troceado_no_cambia_el_resultado():
    # El calculo va por bloques para no armar una matriz de 200k nodos por 724
    # centroides de golpe. El tamano del bloque es una decision de memoria y no
    # debe alterar ni un resultado.
    graph = grafo_con_coords()
    cent = centroides([(f"h{i}", 19.50005, -99.09995) for i in range(7)])
    assert list(snap_to_nodes(graph, cent, chunk=1)) == list(
        snap_to_nodes(graph, cent, chunk=100)
    )


def test_un_grafo_vacio_da_alcance_cero_sin_lanzar():
    alcance = alcance_de(nx.Graph(), centroides([("a", 19.5, -99.1)]))
    assert alcance.loc["a"] == pytest.approx(0.0)


def grafo_con_isla():
    """Una calle de cuatro nodos y un fragmento suelto de dos, sin unir a ella.

    Es la forma real de OSM: calles digitalizadas sin conectar al resto de la
    red. En GAM el grafo trae 112 componentes.
    """
    graph = nx.Graph()
    for node_id, lon in enumerate([-99.1000, -99.0990, -99.0980, -99.0970], start=1):
        graph.add_node(node_id, lat=19.5000, lon=lon)
    for a, b in [(1, 2), (2, 3), (3, 4)]:
        graph.add_edge(a, b, length=104.8)

    graph.add_node(10, lat=19.5050, lon=-99.1000)
    graph.add_node(11, lat=19.5050, lon=-99.0990)
    graph.add_edge(10, 11, length=104.8)
    return graph


def grafo_con_isla_cercana():
    """La misma calle de cuatro nodos, con la isla a solo ~111 m al norte."""
    graph = nx.Graph()
    for node_id, lon in enumerate([-99.1000, -99.0990, -99.0980, -99.0970], start=1):
        graph.add_node(node_id, lat=19.5000, lon=lon)
    for a, b in [(1, 2), (2, 3), (3, 4)]:
        graph.add_edge(a, b, length=104.8)

    graph.add_node(10, lat=19.5010, lon=-99.0990)
    graph.add_node(11, lat=19.5010, lon=-99.0980)
    graph.add_edge(10, 11, length=104.8)
    return graph


def test_el_enganche_ignora_los_fragmentos_sueltos_de_la_red():
    # El centroide tiene la isla a ~5 m y la calle grande a ~106 m, y aun asi se
    # engancha a la calle grande. Medir alcance sobre un fragmento de dos nodos
    # no mide caminabilidad: mide un hueco de OSM. En GAM real esto le pasaba a
    # un hexagono, que se quedaba con 648 m de calle alcanzable cuando un nodo
    # 53 m mas lejos daba 17,579 m, y de paso anclaba el piso del min-max de
    # todos los demas.
    graph = grafo_con_isla_cercana()
    cent = centroides([("a", 19.50095, -99.0990)])
    assert snap_to_nodes(graph, cent).loc["a"] == 2


def test_el_alcance_sale_de_la_red_grande_no_del_fragmento():
    # El control del anterior: la isla daria 104.8 m, la calle grande 314.4.
    graph = grafo_con_isla_cercana()
    cent = centroides([("a", 19.50095, -99.0990)])
    assert alcance_de(graph, cent).loc["a"] == pytest.approx(314.4)


def test_la_guardia_de_500_metros_sigue_valiendo_sobre_la_componente_mayor():
    # Aqui la isla queda encima del centroide y la calle grande a ~556 m. No se
    # engancha a ninguna de las dos: preferir la componente mayor no autoriza a
    # cruzar medio kilometro de barranca para encontrarla.
    graph = grafo_con_isla()
    cent = centroides([("isla", 19.5050, -99.09995)])
    enganche = snap_to_nodes(graph, cent)
    assert enganche.loc["isla"] is None
    assert alcance_de(graph, cent).loc["isla"] == pytest.approx(0.0)
