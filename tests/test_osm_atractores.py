"""Parseo de atractores de OSM: tipos, coordenadas y exclusiones."""

from rtgam.sources.osm import ATTRACTOR_COLUMNS, attractors_from_overpass


def nodo(osm_id, tags, lat=19.5, lon=-99.1):
    return {"type": "node", "id": osm_id, "lat": lat, "lon": lon, "tags": tags}


def via(osm_id, tags, lat=19.5, lon=-99.1):
    return {"type": "way", "id": osm_id, "center": {"lat": lat, "lon": lon}, "tags": tags}


def relacion(osm_id, tags, lat=19.5, lon=-99.1):
    return {
        "type": "relation",
        "id": osm_id,
        "center": {"lat": lat, "lon": lon},
        "tags": tags,
    }


def test_las_columnas_son_las_del_contrato():
    frame = attractors_from_overpass({"elements": [nodo(1, {"leisure": "park"})]})
    assert list(frame.columns) == ATTRACTOR_COLUMNS


def test_una_relation_con_center_entra():
    # El Bosque de San Juan de Aragon existe SOLO como relation. Si esta prueba
    # pasa por accidente porque el codigo trata todo igual, mejor; lo que no
    # puede es faltar.
    payload = {
        "elements": [
            relacion(9, {"leisure": "park", "name": "Bosque de San Juan de Aragon"})
        ]
    }
    frame = attractors_from_overpass(payload)
    assert len(frame) == 1
    assert frame.iloc[0]["name"] == "Bosque de San Juan de Aragon"
    assert frame.iloc[0]["lat"] == 19.5


def test_un_way_usa_su_center_y_un_node_sus_propias_coordenadas():
    payload = {
        "elements": [
            via(1, {"leisure": "park"}, lat=19.51, lon=-99.11),
            nodo(2, {"amenity": "marketplace"}, lat=19.52, lon=-99.12),
        ]
    }
    frame = attractors_from_overpass(payload)
    assert sorted(frame["lat"].tolist()) == [19.51, 19.52]


def test_se_excluye_el_suelo_de_conservacion():
    # La Sierra de Guadalupe suele venir etiquetada como parque Y como area
    # protegida. Es ladera, no plaza.
    payload = {
        "elements": [
            relacion(1, {"leisure": "park", "boundary": "protected_area"}),
            relacion(2, {"leisure": "nature_reserve"}),
            via(3, {"leisure": "park", "natural": "wood"}),
            via(4, {"leisure": "park", "name": "Parque de barrio"}),
        ]
    }
    frame = attractors_from_overpass(payload)
    assert len(frame) == 1
    assert frame.iloc[0]["name"] == "Parque de barrio"


def test_se_descartan_los_elementos_sin_coordenadas():
    payload = {
        "elements": [
            {"type": "relation", "id": 1, "tags": {"leisure": "park"}},
            nodo(2, {"leisure": "park"}),
        ]
    }
    assert len(attractors_from_overpass(payload)) == 1


def test_el_tipo_distingue_espacio_publico_de_transporte():
    payload = {
        "elements": [
            nodo(1, {"leisure": "park"}),
            nodo(2, {"railway": "station"}),
            nodo(3, {"amenity": "marketplace"}),
        ]
    }
    frame = attractors_from_overpass(payload)
    kinds = set(frame["osm_kind"])
    assert kinds == {"park", "station", "marketplace"}


def test_un_elemento_sin_etiqueta_conocida_no_entra():
    payload = {"elements": [nodo(1, {"highway": "bus_stop"})]}
    assert len(attractors_from_overpass(payload)) == 0


def test_un_payload_vacio_da_un_frame_vacio_con_columnas():
    frame = attractors_from_overpass({"elements": []})
    assert len(frame) == 0
    assert list(frame.columns) == ATTRACTOR_COLUMNS


def test_las_estaciones_se_deduplican_por_nombre_pero_los_parques_no():
    # OSM suele traer un nodo Y un way para la misma estacion, a metros de
    # distancia: Martin Carrera aparece dos veces separada 2.8 m. transporte.py
    # ya deduplica por eso, y esta fuente usa las mismas tres etiquetas de
    # transporte.
    #
    # Los parques NO se deduplican: los nombres de parque, jardin y cancha en
    # GAM son genericos y se repiten entre sitios genuinamente distintos, asi
    # que deduplicar por nombre borraria atractores reales.
    payload = {
        "elements": [
            nodo(1, {"railway": "station", "name": "Martin Carrera"}, lat=19.5000),
            via(2, {"railway": "station", "name": "Martin Carrera"}, lat=19.50003),
            via(3, {"leisure": "park", "name": "Parque Recreativo"}, lat=19.51),
            via(4, {"leisure": "park", "name": "Parque Recreativo"}, lat=19.52),
        ]
    }
    frame = attractors_from_overpass(payload)
    estaciones = frame[frame["osm_kind"] == "station"]
    parques = frame[frame["osm_kind"] == "park"]
    assert len(estaciones) == 1, "un nodo y un way de la misma estacion son un atractor"
    assert len(parques) == 2, "los nombres genericos de parque no se deduplican"


def test_las_estaciones_sin_nombre_no_se_pierden():
    # Sin nombre no hay con que deduplicar, y descartarlas perderia paradas
    # reales. Se dejan todas.
    payload = {
        "elements": [
            nodo(1, {"public_transport": "station"}),
            via(2, {"public_transport": "station"}, lat=19.6),
        ]
    }
    assert len(attractors_from_overpass(payload)) == 2


def test_precedencia_de_etiquetas_cuando_un_elemento_tiene_varias():
    # Una plaza con tianguis permanente es real en CDMX: place=square + amenity=marketplace.
    # El orden de ATTRACTOR_TAGS fija cual gana. Marketplace viene antes que square
    # porque un atractor comercial (generador de afluencia por transacciones) es mas
    # funcional y relevante para ubicar una cafeteria que el hecho geometrico de ser
    # una plaza. La senal de trafico de una plaza COMO marketplace es mas fuerte.
    payload = {
        "elements": [
            nodo(1, {"place": "square", "amenity": "marketplace", "name": "Tianguis de GAM"}),
        ]
    }
    frame = attractors_from_overpass(payload)
    assert len(frame) == 1
    assert frame.iloc[0]["osm_kind"] == "marketplace"
