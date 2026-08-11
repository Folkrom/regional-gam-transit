"""Parseo de atractores de OSM: tipos, coordenadas, exclusiones y anidamiento."""

import pytest

from rtgam.sources.osm import ATTRACTOR_COLUMNS, attractors_from_overpass


def cuadro(lat, lon, lado=0.001):
    """Anillo cerrado cuadrado centrado en (lat, lon), como lo da `out geom`.

    0.001 grados son ~111 m de lado, el tamano de un parque de barrio.
    """
    d = lado / 2
    esquinas = [
        (lat - d, lon - d),
        (lat - d, lon + d),
        (lat + d, lon + d),
        (lat + d, lon - d),
        (lat - d, lon - d),
    ]
    return [{"lat": la, "lon": lo} for la, lo in esquinas]


def nodo(osm_id, tags, lat=19.5, lon=-99.1):
    return {"type": "node", "id": osm_id, "lat": lat, "lon": lon, "tags": tags}


def via(osm_id, tags, lat=19.5, lon=-99.1, lado=0.001):
    return {
        "type": "way",
        "id": osm_id,
        "geometry": cuadro(lat, lon, lado),
        "tags": tags,
    }


def relacion(osm_id, tags, lat=19.5, lon=-99.1, lado=0.002):
    return {
        "type": "relation",
        "id": osm_id,
        "members": [
            {"type": "way", "role": "outer", "geometry": cuadro(lat, lon, lado)}
        ],
        "tags": tags,
    }


def test_las_columnas_son_las_del_contrato():
    frame = attractors_from_overpass({"elements": [nodo(1, {"leisure": "park"})]})
    assert list(frame.columns) == ATTRACTOR_COLUMNS


def test_una_relation_entra_con_la_geometria_de_sus_miembros():
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
    assert frame.iloc[0]["lat"] == pytest.approx(19.5)


def test_un_way_usa_el_centroide_de_su_geometria_y_un_node_sus_coordenadas():
    payload = {
        "elements": [
            via(1, {"leisure": "park"}, lat=19.51, lon=-99.11),
            nodo(2, {"amenity": "marketplace"}, lat=19.52, lon=-99.12),
        ]
    }
    frame = attractors_from_overpass(payload)
    assert sorted(frame["lat"].tolist()) == [pytest.approx(19.51), pytest.approx(19.52)]


def test_se_excluye_el_suelo_de_conservacion():
    # La Sierra de Guadalupe suele venir etiquetada como parque Y como area
    # protegida. Es ladera, no plaza.
    payload = {
        "elements": [
            relacion(1, {"leisure": "park", "boundary": "protected_area"}),
            relacion(2, {"leisure": "nature_reserve"}),
            via(3, {"leisure": "park", "natural": "wood"}),
            via(4, {"leisure": "park", "name": "Parque de barrio"}, lat=19.6),
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
            nodo(2, {"railway": "station"}, lat=19.6),
            nodo(3, {"amenity": "marketplace"}, lat=19.7),
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
    # Los parques NO se deduplican por nombre: los nombres de parque, jardin y
    # cancha en GAM son genericos y se repiten entre sitios genuinamente
    # distintos, asi que deduplicar por nombre borraria atractores reales.
    #
    # Las coordenadas van lejos entre si a proposito, para que lo que pruebe
    # esto sea el nombre y no el anidamiento geometrico.
    payload = {
        "elements": [
            nodo(1, {"railway": "station", "name": "Martin Carrera"}, lat=19.50),
            via(2, {"railway": "station", "name": "Martin Carrera"}, lat=19.60),
            via(3, {"leisure": "park", "name": "Parque Recreativo"}, lat=19.70),
            via(4, {"leisure": "park", "name": "Parque Recreativo"}, lat=19.80),
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


# --- Anidamiento -----------------------------------------------------------
#
# Medido sobre GAM: 499 de 1,776 atractores (28%) caen dentro de otro mayor.
# El Deportivo Hermanos Galeana trae 58 canchas mapeadas aparte, asi que contaba
# 59 veces; el Deportivo Oceania, 31. Sin esta regla, un deportivo aplasta la
# variable de sus hexagonos vecinos por la sola forma en que OSM lo digitalizo.


def test_una_cancha_dentro_de_un_parque_no_cuenta_aparte():
    payload = {
        "elements": [
            via(1, {"leisure": "park", "name": "Deportivo"}, lado=0.004),
            via(2, {"leisure": "pitch"}, lat=19.5005, lado=0.0004),
        ]
    }
    frame = attractors_from_overpass(payload)
    assert list(frame["osm_kind"]) == ["park"]


def test_un_deportivo_con_ocho_canchas_cuenta_una_vez():
    canchas = [
        via(i + 10, {"leisure": "pitch"}, lat=19.5000 + i * 0.0003, lado=0.0002)
        for i in range(8)
    ]
    payload = {
        "elements": [
            via(1, {"leisure": "sports_centre", "name": "Hermanos Galeana"}, lado=0.006),
            *canchas,
        ]
    }
    frame = attractors_from_overpass(payload)
    assert len(frame) == 1
    assert frame.iloc[0]["name"] == "Hermanos Galeana"


def test_una_cancha_fuera_de_todo_parque_si_cuenta():
    # El control positivo. Sin el, borrar todas las canchas pasaria la prueba de
    # arriba, y en GAM la mayoria de las canchas NO estan anidadas: son canchas
    # de colonia, atractores reales por si mismas.
    payload = {
        "elements": [
            via(1, {"leisure": "park", "name": "Parque"}, lado=0.004),
            via(2, {"leisure": "pitch", "name": "Cancha de la colonia"}, lat=19.6),
        ]
    }
    frame = attractors_from_overpass(payload)
    assert sorted(frame["osm_kind"]) == ["park", "pitch"]


def test_la_regla_no_es_solo_para_canchas():
    # 43 jardines dentro de su parque, 6 parques dentro de otro parque, 5
    # mercados dentro de otro mercado. Es la misma subdivision del mismo
    # espacio publico, con otro nombre.
    payload = {
        "elements": [
            via(1, {"leisure": "park", "name": "Parque grande"}, lado=0.004),
            via(2, {"leisure": "garden"}, lat=19.5005, lado=0.0004),
            via(3, {"place": "square"}, lat=19.4995, lado=0.0004),
        ]
    }
    frame = attractors_from_overpass(payload)
    assert list(frame["name"]) == ["Parque grande"]


def test_un_nodo_dentro_de_un_poligono_tambien_se_absorbe():
    # Muchos juegos infantiles estan mapeados como nodo suelto dentro del
    # parque que ya los contiene.
    payload = {
        "elements": [
            via(1, {"leisure": "park", "name": "Parque"}, lado=0.004),
            nodo(2, {"leisure": "playground"}, lat=19.5003),
        ]
    }
    frame = attractors_from_overpass(payload)
    assert list(frame["osm_kind"]) == ["park"]


def test_el_contenedor_tiene_que_ser_mayor_que_lo_contenido():
    # Dos poligonos del mismo tamano que se traslapan son dos sitios distintos
    # mal digitalizados, no uno dentro de otro. Sin la comparacion de area, la
    # regla se comeria a uno de los dos segun el orden del payload, que es
    # justo el tipo de resultado que cambia sin que nada falle.
    payload = {
        "elements": [
            via(1, {"leisure": "park", "name": "A"}, lado=0.001),
            via(2, {"leisure": "park", "name": "B"}, lado=0.001),
        ]
    }
    frame = attractors_from_overpass(payload)
    assert sorted(frame["name"]) == ["A", "B"]


def test_una_relation_absorbe_lo_que_tiene_dentro():
    # El Bosque de San Juan de Aragon es relation y trae canchas mapeadas
    # aparte. Si el poligono de la relation no se armara desde sus miembros,
    # no contendria nada y las canchas seguirian contando.
    payload = {
        "elements": [
            relacion(1, {"leisure": "park", "name": "Bosque"}, lado=0.006),
            via(2, {"leisure": "pitch"}, lat=19.5005, lado=0.0004),
        ]
    }
    frame = attractors_from_overpass(payload)
    assert list(frame["name"]) == ["Bosque"]


def test_un_parque_dentro_de_otro_deja_al_grande():
    # Cual sobrevive importa: el contenedor es la unidad que la gente visita.
    payload = {
        "elements": [
            via(1, {"leisure": "park", "name": "Chico"}, lat=19.5002, lado=0.0006),
            via(2, {"leisure": "park", "name": "Grande"}, lado=0.004),
        ]
    }
    frame = attractors_from_overpass(payload)
    assert list(frame["name"]) == ["Grande"]
