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
