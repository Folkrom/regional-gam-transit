# Fuente OSM: accesibilidad peatonal y atractores — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Producir `data/processed/osm.parquet` con `accesibilidad_peatonal` (metros de calle caminable alcanzables en 800 m de red) y `atractores_osm` (espacio público y transporte), sin tocar código existente.

**Architecture:** Dos módulos nuevos. `src/rtgam/red.py` es una primitiva al nivel de `geo.py`: arma un grafo de calles desde una respuesta de Overpass y calcula alcance por Dijkstra acotado. `src/rtgam/sources/osm.py` es la fuente: consulta Overpass, parsea atractores y emite las dos columnas crudas. El script `scripts/04_osm.py` los une. Como solo hay 724 orígenes, el grafo NO se simplifica: cada nodo OSM es un nodo del grafo.

**Tech Stack:** Python 3.12, pandas, numpy, networkx (dependencia nueva), requests, pytest.

**Spec:** `docs/superpowers/specs/2026-08-09-osm-accesibilidad-atractores-design.md`

## Global Constraints

- Identificadores en inglés; docstrings, comentarios y salida de scripts en **español sin acentos** (así está el resto del repo).
- Commits **sin** trailer de coautoría y **sin** footer de Claude Code.
- Las fuentes emiten valores **crudos**. La normalización ocurre una sola vez, en `99_score.py`. No normalizar aquí.
- Cada fuente es dueña exclusiva de sus columnas. Esta fuente posee exactamente `accesibilidad_peatonal` y `atractores_osm`, ya presentes en `config/weights.yaml` con pesos 0.10 y 0.05.
- **Validar ANTES de escribir caché, nunca al revés.** Ya se corrigió tres veces en este proyecto por hacerlo al revés.
- Kernel fijo para atractores: `exp(-d/300)`, cero pasados 800 m, vía `rtgam.geo.accumulate_decay`. No inventar otro kernel.
- Corte de la red: **800 m**. Enganche máximo del centroide a un nodo: **500 m**.
- `User-Agent` obligatorio en toda petición, tomado de `rtgam.USER_AGENT`. Sin él Overpass responde 406.
- Dependencia nueva permitida: **solo `networkx`**. Nada de `osmnx`, `geopandas`, `scikit-learn`, `pyproj` ni `rtree`.
- Las pruebas **no tocan la red** y usan fixtures sintéticos.
- No mandar scripts largos a background: mueren con su proceso padre.
- No usar `git add -A`. Agregar archivos por nombre.

---

## Estructura de archivos

| archivo | responsabilidad |
|---|---|
| `src/rtgam/red.py` | Primitiva de red: armar grafo desde payload de Overpass, alcance por Dijkstra acotado, enganche de centroides a nodos. Sin nada específico de esta fuente. |
| `src/rtgam/sources/osm.py` | La fuente: consultas Overpass, descarga con caché validada, parseo de atractores, `to_hex_features`. |
| `scripts/04_osm.py` | Orquesta: bbox, descarga, grafo, alcance, atractores, parquet, diagnóstico impreso. |
| `tests/test_red_grafo.py` | Armado del grafo. |
| `tests/test_red_alcance.py` | Alcance y enganche. |
| `tests/test_osm_fetch.py` | Descarga, validación y caché. |
| `tests/test_osm_atractores.py` | Parseo y exclusiones de atractores. |
| `tests/test_osm_hexes.py` | Contrato de `to_hex_features`. |

## Datos verificados contra el servidor real

Hechos ya medidos. No hay que volver a comprobarlos, pero el código depende de ellos:

- `out geom;` devuelve para cada `way` las claves `nodes` (ids) y `geometry` (coordenadas) **alineadas por índice**. Confirmado: `len(nodes) == len(geometry)`.
- Los ids de nodo se **comparten** entre vías, así que reusar el id como clave del grafo conecta la red sola. En una muestra de 75 vías: 502 referencias de nodo, 384 únicas.
- El bbox de GAM es `19.4448,-99.1770,19.5928,-99.0509` (sur, oeste, norte, este).
- En ese bbox hay **33,449 vías caminables**. Esperar del orden de 170-200 mil nodos y 40-60 MB de JSON.
- El **Bosque de San Juan de Aragón existe solo como `relation`**. Una consulta de puros `way` lo pierde sin lanzar nada.
- Overpass devuelve **HTTP 200 con cuerpo HTML** cuando está saturado. Ocurrió tres veces. `raise_for_status()` no lo detecta.

---

### Task 1: Grafo de calles desde Overpass

**Files:**
- Create: `src/rtgam/red.py`
- Modify: `pyproject.toml:6-26` (agregar `networkx` a `dependencies`)
- Test: `tests/test_red_grafo.py`

**Interfaces:**
- Consumes: `rtgam.geo.haversine_m(lat1, lon1, lat2, lon2)` — acepta escalares o arrays.
- Produces: `build_graph(payload: dict) -> networkx.Graph`. Nodos son ids enteros de OSM con atributos `lat` y `lon` (float). Aristas tienen atributo `length` en metros (float).

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/test_red_grafo.py`:

```python
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
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `uv run pytest tests/test_red_grafo.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'rtgam.red'`

- [ ] **Step 3: Agregar networkx a las dependencias**

En `pyproject.toml`, dentro de `dependencies`, después de la línea `"numpy>=1.26",`, agregar:

```toml
    # Solo para el grafo de calles de la fuente OSM: Dijkstra acotado desde los
    # 724 centroides. Es Python puro, sin extensiones compiladas. Se prefirio
    # sobre osmnx, que hace lo mismo mejor pero arrastra geopandas, pyproj,
    # rtree y scikit-learn, y cachea por su cuenta en paralelo al patron del
    # proyecto.
    "networkx>=3.0",
```

Luego correr: `uv sync --extra dev`

- [ ] **Step 4: Implementar `build_graph`**

Crear `src/rtgam/red.py`:

```python
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
```

- [ ] **Step 5: Correr las pruebas**

Run: `uv run pytest tests/test_red_grafo.py -v`
Expected: PASS, 7 pruebas.

- [ ] **Step 6: Probar que la prueba del coseno tiene dientes**

Cambiar temporalmente en `src/rtgam/geo.py:25` el término `np.cos(lat1) * np.cos(lat2)` por `1.0`, correr `uv run pytest tests/test_red_grafo.py -v` y confirmar que `test_la_longitud_de_la_arista_es_la_distancia_real` **falla**. Revertir el cambio.

Este proyecto ya escribió tres pruebas que pasaban por la razón equivocada. El paso existe para no escribir la cuarta.

- [ ] **Step 7: Commit**

```bash
git add src/rtgam/red.py tests/test_red_grafo.py pyproject.toml uv.lock
git commit -m "feat: armar el grafo de calles desde una respuesta de Overpass"
```

---

### Task 2: Alcance por la red

**Files:**
- Modify: `src/rtgam/red.py` (agregar constantes y `reach_m`)
- Test: `tests/test_red_alcance.py`

**Interfaces:**
- Consumes: `build_graph(payload) -> nx.Graph` de la Task 1; nodos con `lat`/`lon`, aristas con `length`.
- Produces: `WALK_CUTOFF_M = 800.0`, `MAX_SNAP_M = 500.0`, `reach_m(graph, source, cutoff=WALK_CUTOFF_M) -> float`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/test_red_alcance.py`:

```python
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
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `uv run pytest tests/test_red_alcance.py -v`
Expected: FAIL con `ImportError: cannot import name 'WALK_CUTOFF_M'`

- [ ] **Step 3: Implementar `reach_m`**

Agregar a `src/rtgam/red.py`, después de `build_graph`:

```python
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
```

- [ ] **Step 4: Correr las pruebas**

Run: `uv run pytest tests/test_red_alcance.py -v`
Expected: PASS, 6 pruebas.

- [ ] **Step 5: Probar que la regla de "ambos extremos" tiene dientes**

Cambiar temporalmente `graph.subgraph(reachable.keys())` por `graph.edges(reachable.keys())` sumando esas aristas (que incluye las de un solo extremo dentro), correr las pruebas y confirmar que `test_una_arista_con_un_extremo_fuera_del_corte_no_suma` **falla**. Revertir.

- [ ] **Step 6: Commit**

```bash
git add src/rtgam/red.py tests/test_red_alcance.py
git commit -m "feat: alcance por la red con Dijkstra acotado"
```

---

### Task 3: Enganche de centroides y alcance por hexágono

**Files:**
- Modify: `src/rtgam/red.py` (agregar `snap_to_nodes` y `reach_from_snapped`)
- Test: `tests/test_red_alcance.py` (agregar casos)

**Interfaces:**
- Consumes: `reach_m(graph, source, cutoff)`, `MAX_SNAP_M`, `WALK_CUTOFF_M` de la Task 2.
- Produces:
  - `snap_to_nodes(graph, centroids, max_snap_m=MAX_SNAP_M, chunk=50) -> pd.Series` — indexada como `centroids`, valores id de nodo o `None` si no hubo enganche.
  - `reach_from_snapped(graph, snapped, cutoff=WALK_CUTOFF_M) -> pd.Series` — indexada como `snapped`, floats, sin NaN.

Son dos funciones y no una porque el enganche es la parte cara: 200 mil nodos por 724 centroides. El script necesita la Series de enganches para reportar los hexágonos sin calle cerca, **y** necesita el alcance. Con una sola función tendría que enganchar dos veces.

**No agregues una función `reach_by_hex` que las componga.** Se consideró y se quitó: nadie la llamaría más que las pruebas, y una función que solo existe para ser probada es código muerto.
  - `centroids` es un DataFrame indexado por `hex_id` con columnas `lat` y `lon`, igual que devuelve `rtgam.geo.hex_centroids`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar al final de `tests/test_red_alcance.py`:

```python
import pandas as pd

from rtgam.red import MAX_SNAP_M, reach_from_snapped, snap_to_nodes


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
    cent = centroides([("a", 19.50005, -99.09995)])
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
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `uv run pytest tests/test_red_alcance.py -v`
Expected: FAIL con `ImportError: cannot import name 'snap_to_nodes'`

- [ ] **Step 3: Implementar `snap_to_nodes` y `reach_from_snapped`**

Agregar al final de `src/rtgam/red.py`:

```python
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
```

- [ ] **Step 4: Correr las pruebas**

Run: `uv run pytest tests/test_red_alcance.py -v`
Expected: PASS, 15 pruebas.

- [ ] **Step 5: Correr toda la suite**

Run: `uv run pytest -q`
Expected: PASS, sin regresiones.

- [ ] **Step 6: Commit**

```bash
git add src/rtgam/red.py tests/test_red_alcance.py
git commit -m "feat: enganche de centroides al grafo y alcance por hexagono"
```

---

### Task 4: Descarga desde Overpass con caché validada

**Files:**
- Create: `src/rtgam/sources/osm.py`
- Test: `tests/test_osm_fetch.py`

**Interfaces:**
- Consumes: `rtgam.USER_AGENT`.
- Produces:
  - `OVERPASS_URLS: tuple[str, ...]`, `OVERPASS_TIMEOUT_S = 180`, `OVERPASS_RETRIES = 3`
  - `build_network_query(bbox: tuple[float, float, float, float]) -> str`
  - `build_attractor_query(bbox: tuple[float, float, float, float]) -> str`
  - `validate_payload(payload: dict) -> dict` — lanza `ValueError` si no sirve
  - `fetch_overpass(query: str, cache_path: Path, force: bool = False) -> dict`
  - `bbox` en el orden de Overpass: `(sur, oeste, norte, este)`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/test_osm_fetch.py`:

```python
"""Descarga desde Overpass: consultas, validacion y cache."""

import json

import pytest

from rtgam.sources.osm import (
    build_attractor_query,
    build_network_query,
    fetch_overpass,
    validate_payload,
)

BBOX = (19.4448, -99.1770, 19.5928, -99.0509)


def test_la_consulta_de_red_excluye_las_vias_rapidas():
    query = build_network_query(BBOX)
    assert "motorway" in query
    assert "trunk" in query
    # El bbox va en el orden de Overpass: sur, oeste, norte, este.
    assert "19.4448,-99.177,19.5928,-99.0509" in query.replace(" ", "")


def test_la_consulta_de_atractores_pide_nwr_no_solo_way():
    # El Bosque de San Juan de Aragon existe SOLO como relation. Una consulta
    # de puros `way` lo pierde sin lanzar nada, que es la firma de bug que mas
    # ha costado en este proyecto.
    query = build_attractor_query(BBOX)
    assert "nwr" in query
    assert "way[" not in query
    assert "out tags center" in query


def test_la_consulta_de_atractores_no_pide_suelo_de_conservacion():
    query = build_attractor_query(BBOX)
    assert "nature_reserve" not in query
    assert "protected_area" not in query


def test_un_payload_sin_elements_lanza():
    with pytest.raises(ValueError, match="elements"):
        validate_payload({"version": 0.6})


def test_un_remark_de_error_lanza():
    # Overpass a veces responde 200 con JSON valido, elements vacio y el error
    # metido en `remark`. Cachear eso envenena todas las corridas siguientes.
    payload = {"elements": [], "remark": "runtime error: Query timed out"}
    with pytest.raises(ValueError, match="remark"):
        validate_payload(payload)


def test_un_payload_bueno_pasa_tal_cual():
    payload = {"elements": [{"type": "node", "id": 1}]}
    assert validate_payload(payload) is payload


def test_un_cuerpo_html_con_status_200_no_deja_cache(tmp_path, monkeypatch):
    """Overpass saturado responde 200 con HTML. raise_for_status no lo ve."""

    class RespuestaHtml:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    def falso_post(*args, **kwargs):
        return RespuestaHtml()

    monkeypatch.setattr("rtgam.sources.osm.requests.post", falso_post)
    monkeypatch.setattr("rtgam.sources.osm.time.sleep", lambda _s: None)

    cache = tmp_path / "osm.json"
    with pytest.raises(RuntimeError):
        fetch_overpass("[out:json];out count;", cache)

    assert not cache.exists(), "no debe quedar cache de una respuesta inservible"


def test_una_cache_valida_no_toca_la_red(tmp_path, monkeypatch):
    def explota(*args, **kwargs):
        raise AssertionError("no deberia pedir nada a la red")

    monkeypatch.setattr("rtgam.sources.osm.requests.post", explota)

    cache = tmp_path / "osm.json"
    cache.write_text(json.dumps({"elements": [{"type": "node", "id": 7}]}))

    payload = fetch_overpass("[out:json];out count;", cache)
    assert payload["elements"][0]["id"] == 7


def test_una_cache_corrupta_lanza_con_el_remedio(tmp_path):
    cache = tmp_path / "osm.json"
    cache.write_text("{esto no es json")
    with pytest.raises(ValueError, match="--force"):
        fetch_overpass("[out:json];out count;", cache)
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `uv run pytest tests/test_osm_fetch.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'rtgam.sources.osm'`

- [ ] **Step 3: Implementar el módulo**

Crear `src/rtgam/sources/osm.py`:

```python
"""Fuente 3: accesibilidad peatonal y atractores de espacio publico desde OSM.

La frontera con DENUE es explicita: DENUE es comercio privado, OSM es lo que el
registro de negocios no ve. Parques, plazas, deportivos, mercados publicos y
paradas de transporte.
"""

import json
import time
from pathlib import Path

import requests

from rtgam import USER_AGENT

OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OVERPASS_TIMEOUT_S = 180
OVERPASS_RETRIES = 3

# Vias que no son caminables. Se excluyen por regex en la consulta para no
# bajar 33 mil vias y filtrarlas despues.
EXCLUDED_HIGHWAY = "motorway|motorway_link|trunk|trunk_link|construction|proposed|raceway"


def build_network_query(bbox: tuple[float, float, float, float]) -> str:
    """Consulta Overpass para la red caminable dentro de un bounding box.

    bbox en el orden que espera Overpass: (sur, oeste, norte, este).

    Pide `out geom;` porque el armado del grafo necesita las dos cosas: los ids
    de nodo, para que las vias se conecten solas al compartirlos, y las
    coordenadas, para medir la longitud de cada arista.

    El bbox se usa tal cual, sin recortar a la geometria de GAM: la red no se
    corta en el limite politico, y dejar la traza de las alcaldias vecinas es
    lo que hace que el alcance de los hexagonos de orilla salga correcto.
    """
    south, west, north, east = bbox
    box = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:{OVERPASS_TIMEOUT_S}];
way["highway"]["highway"!~"{EXCLUDED_HIGHWAY}"]["area"!~"yes"]({box});
out geom;
"""


def build_attractor_query(bbox: tuple[float, float, float, float]) -> str:
    """Consulta Overpass para espacio publico y paradas de transporte.

    `nwr` y no `way`: el Bosque de San Juan de Aragon existe SOLO como relation,
    y una consulta de puros `way` lo pierde sin lanzar nada.

    `out tags center` devuelve el centroide ya calculado para ways y relations,
    y las coordenadas propias para los nodos sueltos.

    El suelo de conservacion no se pide: la Sierra de Guadalupe es ladera, no
    plaza, y meterla pondria un atractor enorme sobre los hexagonos con menos
    banqueta de la alcaldia.

    Las tres etiquetas de transporte son las mismas que ya usa transporte.py,
    para no introducir un universo distinto de paradas.
    """
    south, west, north, east = bbox
    box = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:{OVERPASS_TIMEOUT_S}];
(
  nwr["leisure"~"^(park|garden|pitch|playground|sports_centre)$"]({box});
  nwr["amenity"="marketplace"]({box});
  nwr["place"="square"]({box});
  nwr["railway"="station"]({box});
  nwr["aerialway"="station"]({box});
  nwr["public_transport"="station"]({box});
);
out tags center;
"""


def validate_payload(payload: dict) -> dict:
    """Comprueba que una respuesta de Overpass sirve, antes de cachearla.

    Overpass saturado responde HTTP 200 de dos maneras inservibles: con un
    cuerpo HTML, que revienta al parsear, y con JSON valido que trae `elements`
    vacio y el error dentro de `remark`. La segunda pasa cualquier
    raise_for_status y cualquier json(), asi que hay que mirarla a mano.
    """
    if not isinstance(payload, dict) or "elements" not in payload:
        raise ValueError(
            "La respuesta de Overpass no trae 'elements'. No es una respuesta "
            "util y no se va a cachear."
        )

    remark = payload.get("remark", "")
    if remark:
        raise ValueError(
            f"Overpass respondio 200 pero con un remark de error: {remark}. "
            f"El servidor esta saturado; reintenta mas tarde."
        )

    return payload


def fetch_overpass(query: str, cache_path: Path, force: bool = False) -> dict:
    """Descarga una consulta de Overpass, con cache en disco y espejos.

    El orden importa y no es negociable: se valida ANTES de escribir la cache.
    Al reves, una respuesta 200 inservible queda persistida y envenena todas
    las corridas siguientes, que releen el mismo payload malo.
    """
    if cache_path.exists() and not force:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"La cache {cache_path} esta corrupta o truncada. "
                f"Borrala o corre con --force para volver a descargar. ({error})"
            ) from error
        return validate_payload(payload)

    last_error: Exception | None = None
    for attempt in range(OVERPASS_RETRIES):
        for url in OVERPASS_URLS:
            try:
                response = requests.post(
                    url,
                    data={"data": query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=OVERPASS_TIMEOUT_S,
                )
                response.raise_for_status()
                payload = validate_payload(response.json())
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(json.dumps(payload), encoding="utf-8")
                return payload
            except requests.HTTPError as error:
                # Un 4xx que no sea 429 es un bug de nuestra consulta, no una
                # falla transitoria: reintentarlo solo castiga a un servidor
                # gratuito y retrasa el error real.
                status = error.response.status_code if error.response is not None else None
                if status is not None and 400 <= status < 500 and status != 429:
                    raise
                last_error = error
            except (requests.RequestException, ValueError) as error:
                last_error = error

        if attempt < OVERPASS_RETRIES - 1:
            backoff = 5 * (2**attempt)
            print(f"Overpass fallo ({last_error}); reintento en {backoff}s")
            time.sleep(backoff)

    raise RuntimeError(
        f"Overpass fallo tras {OVERPASS_RETRIES} intentos en {len(OVERPASS_URLS)} espejos"
    ) from last_error
```

- [ ] **Step 4: Correr las pruebas**

Run: `uv run pytest tests/test_osm_fetch.py -v`
Expected: PASS, 9 pruebas.

- [ ] **Step 5: Probar que la prueba de la caché tiene dientes**

Mover temporalmente el `cache_path.write_text(...)` a **antes** de `validate_payload(response.json())` (usando `response.text`), correr las pruebas y confirmar que `test_un_cuerpo_html_con_status_200_no_deja_cache` **falla**. Revertir.

- [ ] **Step 6: Commit**

```bash
git add src/rtgam/sources/osm.py tests/test_osm_fetch.py
git commit -m "feat: consultas de Overpass y descarga con cache validada"
```

---

### Task 5: Parseo de atractores

**Files:**
- Modify: `src/rtgam/sources/osm.py` (agregar `ATTRACTOR_COLUMNS`, `EXCLUDED_TAGS`, `attractor_kind`, `attractors_from_overpass`)
- Test: `tests/test_osm_atractores.py`

**Interfaces:**
- Consumes: nada de tareas previas más allá del propio módulo.
- Produces: `attractors_from_overpass(payload: dict) -> pd.DataFrame` con columnas `["osm_kind", "name", "lat", "lon"]` y un `RangeIndex` limpio.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/test_osm_atractores.py`:

```python
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
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `uv run pytest tests/test_osm_atractores.py -v`
Expected: FAIL con `ImportError: cannot import name 'ATTRACTOR_COLUMNS'`

- [ ] **Step 3: Implementar el parseo**

Agregar a `src/rtgam/sources/osm.py`. Primero el import de pandas junto a los demás:

```python
import pandas as pd
```

Después, tras `build_attractor_query`:

```python
ATTRACTOR_COLUMNS = ["osm_kind", "name", "lat", "lon"]

# Suelo de conservacion. La Sierra de Guadalupe viene etiquetada a la vez como
# parque y como area protegida, asi que no basta con no pedirla: hay que
# descartarla explicitamente al parsear.
EXCLUDED_TAGS = {
    "boundary": {"protected_area"},
    "leisure": {"nature_reserve"},
    "natural": {"wood", "scrub", "heath"},
}

# Etiqueta -> tipo de atractor. El orden importa: el primero que cruce gana.
ATTRACTOR_TAGS = (
    ("leisure", {"park", "garden", "pitch", "playground", "sports_centre"}),
    ("amenity", {"marketplace"}),
    ("place", {"square"}),
    ("railway", {"station"}),
    ("aerialway", {"station"}),
    ("public_transport", {"station"}),
)


def attractor_kind(tags: dict) -> str | None:
    """Tipo de atractor de un elemento, o None si no es ninguno.

    Devuelve el valor de la etiqueta, no la etiqueta: un parque es "park" y una
    estacion es "station", que es lo que sirve para el conteo por tipo que el
    script imprime.
    """
    for key, values in EXCLUDED_TAGS.items():
        if tags.get(key) in values:
            return None

    for key, values in ATTRACTOR_TAGS:
        value = tags.get(key)
        if value in values:
            return value

    return None


def attractors_from_overpass(payload: dict) -> pd.DataFrame:
    """Convierte una respuesta de Overpass en un DataFrame de atractores.

    Acepta node, way y relation. Los nodos traen lat/lon propias; ways y
    relations traen `center`, porque la consulta pide `out tags center`.

    Un elemento sin coordenadas no se puede ubicar en el mapa, asi que se
    descarta.
    """
    rows = []
    for element in payload.get("elements", []):
        kind = attractor_kind(element.get("tags", {}))
        if kind is None:
            continue

        if "lat" in element and "lon" in element:
            lat, lon = element["lat"], element["lon"]
        elif "center" in element:
            lat, lon = element["center"]["lat"], element["center"]["lon"]
        else:
            continue

        name = element.get("tags", {}).get("name", "")
        rows.append((kind, name, float(lat), float(lon)))

    return pd.DataFrame(rows, columns=ATTRACTOR_COLUMNS)
```

- [ ] **Step 4: Correr las pruebas**

Run: `uv run pytest tests/test_osm_atractores.py -v`
Expected: PASS, 8 pruebas.

- [ ] **Step 5: Probar que la exclusión tiene dientes**

Comentar temporalmente el bucle de `EXCLUDED_TAGS` en `attractor_kind`, correr las pruebas y confirmar que `test_se_excluye_el_suelo_de_conservacion` **falla** contando 4 en vez de 1. Revertir.

- [ ] **Step 6: Commit**

```bash
git add src/rtgam/sources/osm.py tests/test_osm_atractores.py
git commit -m "feat: parseo de atractores de OSM con exclusion de conservacion"
```

---

### Task 6: Contrato `to_hex_features`

**Files:**
- Modify: `src/rtgam/sources/osm.py` (agregar `to_hex_features`)
- Test: `tests/test_osm_hexes.py`

**Interfaces:**
- Consumes: `rtgam.geo.accumulate_decay(centroids, points, value_col, tau, cutoff) -> pd.Series`; `attractors_from_overpass` de la Task 5; `reach_from_snapped` de la Task 3.
- Produces: `to_hex_features(gam_hexes: pd.DataFrame, alcance: pd.Series, atractores: pd.DataFrame) -> pd.DataFrame` indexado por `hex_id` con exactamente las columnas `accesibilidad_peatonal` y `atractores_osm`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/test_osm_hexes.py`:

```python
"""Contrato de la fuente OSM: exactamente dos columnas, crudas y sin NaN."""

import pandas as pd
import pytest

from rtgam.sources.osm import to_hex_features


def hexes():
    frame = pd.DataFrame(
        [("h1", 19.5000, -99.1000), ("h2", 19.5200, -99.1200)],
        columns=["hex_id", "lat", "lon"],
    )
    return frame.set_index("hex_id")


def test_devuelve_exactamente_las_dos_columnas_de_esta_fuente():
    features = to_hex_features(
        hexes(),
        pd.Series([100.0, 200.0], index=["h1", "h2"]),
        pd.DataFrame(columns=["osm_kind", "name", "lat", "lon"]),
    )
    assert list(features.columns) == ["accesibilidad_peatonal", "atractores_osm"]
    assert list(features.index) == ["h1", "h2"]


def test_el_alcance_pasa_crudo_sin_normalizar():
    # La normalizacion ocurre una sola vez, en 99_score.py. Si esta fuente
    # normalizara, el score la contaria dos veces.
    features = to_hex_features(
        hexes(),
        pd.Series([1234.5, 0.0], index=["h1", "h2"]),
        pd.DataFrame(columns=["osm_kind", "name", "lat", "lon"]),
    )
    assert features.loc["h1", "accesibilidad_peatonal"] == pytest.approx(1234.5)


def test_cada_atractor_vale_uno():
    # Un atractor encima del centroide de h1 aporta exp(0) = 1.
    atractores = pd.DataFrame(
        [("park", "Parque", 19.5000, -99.1000)],
        columns=["osm_kind", "name", "lat", "lon"],
    )
    features = to_hex_features(
        hexes(), pd.Series([0.0, 0.0], index=["h1", "h2"]), atractores
    )
    assert features.loc["h1", "atractores_osm"] == pytest.approx(1.0, abs=0.01)


def test_un_atractor_lejano_no_aporta():
    # ~0.05 grados de latitud son ~5.5 km, muy pasado el corte de 800 m.
    atractores = pd.DataFrame(
        [("park", "Lejano", 19.5500, -99.1000)],
        columns=["osm_kind", "name", "lat", "lon"],
    )
    features = to_hex_features(
        hexes(), pd.Series([0.0, 0.0], index=["h1", "h2"]), atractores
    )
    assert features["atractores_osm"].sum() == pytest.approx(0.0)


def test_sin_atractores_da_ceros_y_no_nan():
    features = to_hex_features(
        hexes(),
        pd.Series([0.0, 0.0], index=["h1", "h2"]),
        pd.DataFrame(columns=["osm_kind", "name", "lat", "lon"]),
    )
    assert not features.isna().any().any()


def test_un_alcance_desalineado_lanza():
    # Reindexar en silencio convertiria un bug de indice en ceros plausibles.
    # merge_features ya aprendio esta leccion: hueco de join y cero real no son
    # lo mismo.
    with pytest.raises(ValueError, match="indice"):
        to_hex_features(
            hexes(),
            pd.Series([100.0], index=["h1"]),
            pd.DataFrame(columns=["osm_kind", "name", "lat", "lon"]),
        )
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `uv run pytest tests/test_osm_hexes.py -v`
Expected: FAIL con `ImportError: cannot import name 'to_hex_features'`

- [ ] **Step 3: Implementar `to_hex_features`**

Agregar el import junto a los demás en `src/rtgam/sources/osm.py`:

```python
from rtgam.geo import accumulate_decay
```

Y al final del módulo:

```python
def to_hex_features(
    gam_hexes: pd.DataFrame,
    alcance: pd.Series,
    atractores: pd.DataFrame,
) -> pd.DataFrame:
    """Emite las dos columnas que esta fuente posee.

    gam_hexes:  indexado por hex_id, columnas lat y lon.
    alcance:    Series indexada por hex_id, metros de calle alcanzables.
    atractores: columnas osm_kind, name, lat, lon.
    Devuelve:   DataFrame indexado por hex_id con accesibilidad_peatonal y
                atractores_osm, en valores CRUDOS y sin normalizar.

    Cada atractor vale 1.0, igual que cada establecimiento en DENUE, donde
    ponderar por tamano resulto contraproducente: los gigantes eran destinos de
    coche y concentraban una cuarta parte de la variable.
    """
    if not alcance.index.equals(gam_hexes.index):
        raise ValueError(
            "El indice del alcance no coincide con el de los hexagonos. "
            "Reindexar en silencio convertiria un bug de indice en ceros "
            "plausibles, que es peor que fallar."
        )

    puntos = atractores.assign(peso=1.0)
    return pd.DataFrame(
        {
            "accesibilidad_peatonal": alcance.astype(float),
            "atractores_osm": accumulate_decay(gam_hexes, puntos, value_col="peso"),
        }
    )
```

- [ ] **Step 4: Correr las pruebas**

Run: `uv run pytest tests/test_osm_hexes.py -v`
Expected: PASS, 6 pruebas.

- [ ] **Step 5: Correr toda la suite**

Run: `uv run pytest -q`
Expected: PASS, sin regresiones.

- [ ] **Step 6: Commit**

```bash
git add src/rtgam/sources/osm.py tests/test_osm_hexes.py
git commit -m "feat: contrato de la fuente OSM con las dos columnas crudas"
```

---

### Task 7: Script `04_osm.py` y documentación

**Files:**
- Create: `scripts/04_osm.py`
- Modify: `README.md` (tabla de variables y orden de corrida)
- Modify: `HANDOFF.md` (estado y pendientes)

**Interfaces:**
- Consumes: `rtgam.boundary.fetch_gam_polygon(cache_path, force) -> BaseGeometry`; `rtgam.red.build_graph`, `snap_to_nodes`, `reach_from_snapped`; `rtgam.sources.osm.build_network_query`, `build_attractor_query`, `fetch_overpass`, `attractors_from_overpass`, `to_hex_features`.
- Produces: `data/processed/osm.parquet`. `99_score.py` ya lista ese nombre en `SOURCE_FILES`, así que no hay que tocarlo.

**Nota de ejecución:** la descarga de la red son 40-60 MB de JSON y Overpass tarda. **Correr en primer plano**, nunca en background: tres agentes ya perdieron su trabajo así, porque el proceso muere con su padre.

- [ ] **Step 1: Escribir el script**

Crear `scripts/04_osm.py`:

```python
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

import pandas as pd

from rtgam.boundary import fetch_gam_polygon
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
```

- [ ] **Step 2: Correr el script de verdad**

Run: `uv run python scripts/04_osm.py`

En **primer plano**. Verificar en la salida:
- el grafo tiene del orden de 150-250 mil nodos (si trae menos de 50 mil, el filtro de vías está mal);
- `accesibilidad_peatonal` tiene señal en casi los 724 hexágonos;
- los hexágonos sin enganche son pocos, y caen en el norte (laderas de la Sierra de Guadalupe);
- entre los atractores aparece el Bosque de San Juan de Aragón.

Comprobar lo último explícitamente:

```bash
uv run python -c "
import json
p=json.load(open('data/raw/osm_atractores.json'))
from rtgam.sources.osm import attractors_from_overpass
a=attractors_from_overpass(p)
print(a[a['name'].str.contains('Arag', na=False)][['osm_kind','name']].to_string())
"
```

Expected: el Bosque de San Juan de Aragón aparece en la lista.

- [ ] **Step 3: Correr el score y confirmar que el seam aguantó**

Run: `uv run python scripts/99_score.py`

Expected: la salida menciona `Fuente cargada: osm.parquet` con las dos columnas, y el score sube de las 3 variables actuales a 5. **Sin haber tocado `99_score.py`, `config/weights.yaml`, `geo.py` ni el dashboard.**

- [ ] **Step 4: Correr toda la suite**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Actualizar el README**

En `README.md`, en la tabla de variables, cambiar las filas de `accesibilidad_peatonal` y `atractores_osm` de pendientes a presentes, nombrando la fuente: "OSM, alcance a 800 m por la red" y "OSM, espacio publico y transporte".

En el orden de corrida, agregar `uv run python scripts/04_osm.py` entre `03_denue.py` y `99_score.py`.

En la sección de limitaciones, agregar las tres del spec, con sus cifras:
- los polígonos grandes van por su centroide (43 de 1,679 pasan de 400 m de extensión; el Bosque de San Juan de Aragón mide ~1.3 km y sale subestimado);
- los atractores siguen en distancia euclidiana, solo `accesibilidad_peatonal` usa la red;
- OSM es colaborativo y su cobertura es desigual, así que una colonia poco mapeada sale baja por falta de mapeadores, no de banquetas.

- [ ] **Step 6: Actualizar el HANDOFF**

En `HANDOFF.md`: marcar las dos variables como hechas en la tabla, actualizar la cobertura y el score máximo con las cifras reales de la corrida, agregar `04_osm.py` al orden de corrida, y dejar el censo AGEB como único pendiente.

- [ ] **Step 7: Commit**

```bash
git add scripts/04_osm.py README.md HANDOFF.md
git commit -m "feat: script de la fuente OSM y documentacion actualizada"
```

---

## Verificación final

- [ ] `uv run pytest -q` pasa completo.
- [ ] `data/processed/osm.parquet` existe con las dos columnas.
- [ ] `git diff --stat main` no toca `scripts/99_score.py`, `config/weights.yaml`, `src/rtgam/geo.py`, `src/rtgam/score.py` ni `app/dashboard.py`. Si los toca, el seam no aguantó y hay que entender por qué.
- [ ] Ningún commit trae trailer de coautoría: `git log main..HEAD --format=%b | grep -i "co-authored"` no devuelve nada.
