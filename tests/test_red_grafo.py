"""Armado del grafo de calles a partir de una respuesta de Overpass."""

import pytest

from rtgam.red import build_graph


def _way(way_id, node_ids, coords):
    return {
        "type": "way",
        "id": way_id,
        "nodes": node_ids,
        "geometry": [{"lat": lat, "lon": lon} for lat, lon in coords],
        "tags": {"highway": "residential"},
    }


def test_una_via_de_tres_nodos_da_dos_aristas():
    payload = {
        "elements": [
            _way(1, [10, 11, 12], [(19.5, -99.100), (19.5, -99.099), (19.5, -99.098)])
        ]
    }
    graph = build_graph(payload)
    assert graph.number_of_nodes() == 3
    assert graph.number_of_edges() == 2


def test_la_longitud_de_la_arista_es_la_distancia_real():
    # 0.001 grados de longitud a 19.5 de latitud son ~104.8 m, no 111.
    # El coseno de la latitud es justo el termino que este proyecto ya rompio
    # una vez: unas pruebas de haversine que solo comparaban puntos en el mismo
    # meridiano pasaban con la formula mal.
    payload = {
        "elements": [_way(1, [10, 11], [(19.5, -99.100), (19.5, -99.099)])]
    }
    graph = build_graph(payload)
    assert graph[10][11]["length"] == pytest.approx(104.8, abs=0.5)


def test_los_nodos_guardan_sus_coordenadas():
    payload = {
        "elements": [_way(1, [10, 11], [(19.5, -99.100), (19.5, -99.099)])]
    }
    graph = build_graph(payload)
    assert graph.nodes[10]["lat"] == pytest.approx(19.5)
    assert graph.nodes[10]["lon"] == pytest.approx(-99.100)


def test_un_nodo_compartido_conecta_dos_vias():
    # Esta es la razon por la que no hace falta detectar intersecciones:
    # OSM reutiliza el id, asi que el grafo se conecta solo.
    payload = {
        "elements": [
            _way(1, [10, 11], [(19.5, -99.100), (19.5, -99.099)]),
            _way(2, [11, 12], [(19.5, -99.099), (19.5, -99.098)]),
        ]
    }
    graph = build_graph(payload)
    assert graph.number_of_nodes() == 3
    assert graph.number_of_edges() == 2
    assert graph.has_edge(10, 11) and graph.has_edge(11, 12)


def test_se_ignoran_los_elementos_sin_geometria():
    payload = {
        "elements": [
            {"type": "way", "id": 1, "nodes": [10, 11], "tags": {}},
            _way(2, [20, 21], [(19.5, -99.100), (19.5, -99.099)]),
        ]
    }
    graph = build_graph(payload)
    assert graph.number_of_nodes() == 2


def test_se_ignora_una_via_de_un_solo_nodo():
    payload = {"elements": [_way(1, [10], [(19.5, -99.100)])]}
    graph = build_graph(payload)
    assert graph.number_of_edges() == 0


def test_nodes_y_geometry_desalineados_lanzan():
    # Si Overpass cambia y deja de alinearlos, hay que enterarse con un error,
    # no con longitudes de arista silenciosamente equivocadas.
    payload = {
        "elements": [
            {
                "type": "way",
                "id": 1,
                "nodes": [10, 11, 12],
                "geometry": [{"lat": 19.5, "lon": -99.1}, {"lat": 19.5, "lon": -99.099}],
                "tags": {},
            }
        ]
    }
    with pytest.raises(ValueError, match="desalineadas"):
        build_graph(payload)
