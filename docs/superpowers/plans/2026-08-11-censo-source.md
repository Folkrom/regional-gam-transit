# Fuente censo AGEB: densidad y nivel socioeconómico — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Aportar las dos últimas variables del score de GAM —`densidad_pob` y `nivel_socioeconomico`— repartiendo el censo 2020 del INEGI desde los 305 AGEB de la alcaldía a los 724 hexágonos H3, por intersección de área.

**Architecture:** Una primitiva geométrica nueva (`src/rtgam/areal.py`) que reparte cualquier polígono entre hexágonos sin saber nada del dominio, más un módulo de fuente (`src/rtgam/sources/censo.py`) que descarga, limpia y produce exactamente dos columnas. `censo.parquet` ya está registrado en `SOURCE_FILES` de `scripts/99_score.py`: la fuente entra sin tocar el núcleo.

**Tech Stack:** pandas, shapely (ya es dependencia desde la fuente OSM), h3, requests. **Ninguna dependencia nueva** — en particular, NO se agrega geopandas.

**Spec:** `docs/superpowers/specs/2026-08-11-censo-densidad-nse-design.md`

## Global Constraints

- **Identificadores en inglés. Docstrings y comentarios en español SIN acentos.** (La salida de los scripts sí lleva acentos.)
- **Ningún commit lleva trailer `Co-Authored-By` ni footer de Claude Code.** Regla dura del usuario.
- **Ninguna dependencia nueva.** No agregar geopandas, pyproj, rtree ni scikit-learn a `pyproject.toml`.
- **Validar ANTES de escribir caché, nunca al revés.** Se corrigió tres veces en este proyecto por no hacerlo.
- **`User-Agent` obligatorio** en toda petición saliente. Vive en `rtgam.USER_AGENT`, no se re-declara.
- **Las pruebas NUNCA tocan la red.** Todo va por fixtures sintéticos o monkeypatch.
- **No tocar** `src/rtgam/geo.py`, `src/rtgam/score.py`, `src/rtgam/normalize.py`, `scripts/99_score.py`, `config/weights.yaml` ni `app/`. Si un cambio parece exigirlo, es señal de que algo se diseñó mal: parar y reportar.
- **Contrato de fuente:** `to_hex_features()` devuelve un DataFrame indexado por `hex_id` con SOLO las columnas propias de esta fuente: `densidad_pob` y `nivel_socioeconomico`. Nada más.
- **Excepción documentada al contrato de valores crudos:** `nivel_socioeconomico` sale escalado 0-1 porque promediar porcentajes con años de escolaridad exige escala común. `densidad_pob` sí sale cruda (hab/km²). Esto está aprobado en el spec; no "corregirlo".
- **Nunca `git add -A`.** Se listan las rutas explícitamente.
- **Nunca mandar un script largo a background.** El proceso muere con su padre. Cinco agentes ya perdieron su trabajo así en este repo. Correr en primer plano con `timeout: 600000`.
- **Un `*` o un `VIVPAR_HAB == 0` NUNCA se convierte en `0.0`.** Con normalización min-max, un cero falso ancla el piso de la columna y mueve a los 724 hexágonos.

---

## Estructura de archivos

| archivo | responsabilidad |
|---|---|
| `src/rtgam/areal.py` | **crear.** Primitiva: polígonos de celdas H3 y reparto areal entre polígonos. No sabe qué es un AGEB. |
| `src/rtgam/sources/censo.py` | **crear.** Fuente: descarga, parseo del CSV, índice NSE, las dos columnas. |
| `scripts/05_censo.py` | **crear.** Orquestación y diagnóstico impreso. |
| `tests/test_areal.py` | **crear.** Reparto areal con cuadrados sintéticos. |
| `tests/test_censo_parseo.py` | **crear.** Confidenciales, viviendas colectivas, índice NSE. |
| `tests/test_censo_hexes.py` | **crear.** Contrato de columnas y ponderación por población. |
| `tests/test_censo_fetch.py` | **crear.** Descarga, caché y validación. |
| `README.md`, `HANDOFF.md` | **modificar.** Tabla de variables, orden de corrida, limitaciones. |

---

## Contexto del proyecto que el implementador necesita

**Cómo se ve un hexágono.** `data/processed/gam_hexes.parquet` está indexado por `hex_id` (string H3 resolución 9) con columnas `lat` y `lon` del centroide. Son 724 filas.

**Ojo con el orden de coordenadas.** `h3.cell_to_boundary(hex_id)` devuelve tuplas **(lat, lon)**. Shapely trabaja en **(x, y) = (lon, lat)**. Hay que invertirlas al construir el polígono. Este error no lanza: produce polígonos en el hemisferio equivocado que no intersectan nada, y todas las columnas salen en cero.

**El patrón de fuente ya establecido.** Mirar `src/rtgam/sources/denue.py` para el manejo de zip y caché, y `src/rtgam/sources/osm.py` para `STRtree` y validación antes de caché. Seguirlos, no inventar otro estilo.

**Por qué no se reproyecta.** Las áreas se usan como proporciones (numerador y denominador salen de la misma intersección), así que el factor de escala de la latitud se cancela. El área absoluta en km² la da `h3.cell_area(hex_id, "km^2")` — para GAM vale 0.12156802899339546 km², verificado.

---

## Task 1: Primitiva de reparto areal

**Files:**
- Create: `src/rtgam/areal.py`
- Test: `tests/test_areal.py`

**Interfaces:**
- Consumes: nada de tareas previas.
- Produces:
  - `hex_polygons(hexes: pd.DataFrame) -> dict[str, Polygon]`
  - `area_weights(hex_polys: dict[str, Polygon], source_polys: dict[str, Polygon]) -> pd.DataFrame`
    - Devuelve un DataFrame indexado por `hex_id` (mismo orden que `hex_polys`), con una columna por cada clave de `source_polys`. El valor `[h, s]` es la fracción del área de `s` que cae dentro de `h`. **Cada COLUMNA suma como mucho 1.0.**

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/test_areal.py`:

```python
"""Reparto areal: fraccion de cada poligono que cae en cada hexagono."""

import pandas as pd
import pytest
from shapely.geometry import Polygon

from rtgam.areal import area_weights, hex_polygons


def cuadro(x0, y0, lado):
    """Cuadrado con esquina inferior izquierda en (x0, y0), en grados."""
    return Polygon(
        [(x0, y0), (x0 + lado, y0), (x0 + lado, y0 + lado), (x0, y0 + lado)]
    )


def test_un_poligono_dentro_de_un_solo_hexagono_da_peso_uno():
    hexes = {"h1": cuadro(0, 0, 10)}
    fuentes = {"a": cuadro(2, 2, 1)}
    pesos = area_weights(hexes, fuentes)
    assert pesos.loc["h1", "a"] == pytest.approx(1.0)


def test_un_poligono_partido_en_dos_reparte_mitad_y_mitad():
    # El cuadro fuente va de x=8 a x=12; los hexagonos parten en x=10.
    hexes = {"izq": cuadro(0, 0, 10), "der": cuadro(10, 0, 10)}
    fuentes = {"a": Polygon([(8, 2), (12, 2), (12, 4), (8, 4)])}
    pesos = area_weights(hexes, fuentes)
    assert pesos.loc["izq", "a"] == pytest.approx(0.5)
    assert pesos.loc["der", "a"] == pytest.approx(0.5)


def test_los_pesos_de_un_poligono_cubierto_suman_uno():
    # Esta es LA propiedad que conserva la poblacion. Si esta prueba se cae,
    # la poblacion total deja de cuadrar con el censo.
    hexes = {"a": cuadro(0, 0, 10), "b": cuadro(10, 0, 10), "c": cuadro(0, 10, 10)}
    fuentes = {"p": Polygon([(5, 5), (15, 5), (15, 15), (5, 15)])}
    pesos = area_weights(hexes, fuentes)
    assert pesos["p"].sum() == pytest.approx(0.75)


def test_un_poligono_que_sobresale_suma_menos_de_uno():
    # Un AGEB del borde de GAM que se sale de la reticula: se reparte solo la
    # parte cubierta, y el resto se pierde a proposito. No se re-escala.
    hexes = {"h1": cuadro(0, 0, 10)}
    fuentes = {"a": Polygon([(8, 2), (18, 2), (18, 4), (8, 4)])}
    pesos = area_weights(hexes, fuentes)
    assert pesos.loc["h1", "a"] == pytest.approx(0.2)


def test_un_poligono_que_no_toca_nada_da_cero_no_nan():
    # Un NaN aqui se propagaria al producto con la poblacion y ensuciaria la
    # columna entera, no solo este hexagono.
    hexes = {"h1": cuadro(0, 0, 10)}
    fuentes = {"lejos": cuadro(100, 100, 1)}
    pesos = area_weights(hexes, fuentes)
    assert pesos.loc["h1", "lejos"] == pytest.approx(0.0)
    assert not pesos.isna().any().any()


def test_el_indice_y_las_columnas_son_los_de_entrada():
    hexes = {"h1": cuadro(0, 0, 10), "h2": cuadro(10, 0, 10)}
    fuentes = {"a": cuadro(1, 1, 1), "b": cuadro(11, 1, 1)}
    pesos = area_weights(hexes, fuentes)
    assert list(pesos.index) == ["h1", "h2"]
    assert list(pesos.columns) == ["a", "b"]


def test_sin_poligonos_fuente_da_un_frame_vacio_con_el_indice():
    hexes = {"h1": cuadro(0, 0, 10)}
    pesos = area_weights(hexes, {})
    assert list(pesos.index) == ["h1"]
    assert len(pesos.columns) == 0


def test_hex_polygons_usa_lon_lat_no_lat_lon():
    # h3.cell_to_boundary devuelve (lat, lon) y shapely espera (x, y) = (lon,
    # lat). Invertirlas no lanza: produce poligonos en el hemisferio
    # equivocado que no intersectan nada, y todas las columnas salen en cero.
    # GAM esta en lon ~-99, lat ~19.5.
    import h3

    real = h3.latlng_to_cell(19.5, -99.1, 9)
    hexes = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index([real], name="hex_id")
    )
    polys = hex_polygons(hexes)
    minx, miny, maxx, maxy = polys[real].bounds
    assert -100 < minx < -98, "la x debe ser longitud (~-99), no latitud"
    assert 19 < miny < 20, "la y debe ser latitud (~19.5), no longitud"


def test_hex_polygons_devuelve_uno_por_hexagono():
    import h3

    ids = [h3.latlng_to_cell(19.5, -99.1, 9), h3.latlng_to_cell(19.52, -99.12, 9)]
    hexes = pd.DataFrame(
        {"lat": [19.5, 19.52], "lon": [-99.1, -99.12]},
        index=pd.Index(ids, name="hex_id"),
    )
    polys = hex_polygons(hexes)
    assert set(polys) == set(ids)
    assert all(p.area > 0 for p in polys.values())
```

- [ ] **Step 2: Correr las pruebas y ver que fallan**

Run: `uv run python -m pytest tests/test_areal.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'rtgam.areal'`

- [ ] **Step 3: Escribir la implementación**

Crear `src/rtgam/areal.py`:

```python
"""Reparto areal: cuanta parte de un poligono cae en cada hexagono.

Es una primitiva al mismo nivel que geo.py y red.py. No sabe que es un AGEB
ni que columnas produce el score: reparte poligonos entre poligonos.

No se reproyecta a UTM. Las areas se usan como PROPORCIONES —numerador y
denominador salen de la misma interseccion— asi que el factor de escala de la
latitud se cancela en el cociente. Es la misma logica por la que geo.py usa
haversine en vez de pyproj.
"""

import h3
import pandas as pd
from shapely.geometry import Polygon
from shapely.strtree import STRtree


def hex_polygons(hexes: pd.DataFrame) -> dict[str, Polygon]:
    """Poligono de cada celda H3, en coordenadas (lon, lat).

    hexes: indexado por hex_id. Las columnas no se usan; solo el indice.

    h3.cell_to_boundary devuelve tuplas (lat, lon) y shapely espera (x, y),
    es decir (lon, lat). Invertirlas no lanza nada: produce poligonos en el
    hemisferio equivocado que no intersectan ningun AGEB, y las dos columnas
    de la fuente salen en cero sin una sola excepcion.
    """
    return {
        hex_id: Polygon([(lon, lat) for lat, lon in h3.cell_to_boundary(hex_id)])
        for hex_id in hexes.index
    }


def area_weights(
    hex_polys: dict[str, Polygon],
    source_polys: dict[str, Polygon],
) -> pd.DataFrame:
    """Fraccion del area de cada poligono origen que cae en cada hexagono.

    Devuelve un DataFrame indexado por hex_id, con una columna por clave de
    source_polys. El valor [h, s] es el area de la interseccion entre s y h,
    dividida entre el area total de s.

    La propiedad que hace correcto todo lo que viene despues: cada COLUMNA
    suma como mucho 1.0, y suma exactamente 1.0 cuando el poligono origen esta
    enteramente cubierto por los hexagonos. Eso es lo que conserva la
    poblacion al repartirla.

    Un poligono que sobresale de la reticula reparte solo la parte cubierta y
    el resto se pierde a proposito: re-escalar a 1.0 inventaria poblacion
    dentro de GAM que en realidad vive fuera.

    Se usa un STRtree para no cruzar 724 x 305 pares uno por uno, el mismo
    patron que drop_nested en sources/osm.py.
    """
    hex_ids = list(hex_polys)
    index = pd.Index(hex_ids, name="hex_id")

    if not source_polys:
        return pd.DataFrame(index=index)

    figures = [hex_polys[h] for h in hex_ids]
    tree = STRtree(figures)

    columns = {}
    for key, source in source_polys.items():
        total = source.area
        column = [0.0] * len(hex_ids)
        if total > 0:
            for position in tree.query(source):
                shared = figures[position].intersection(source).area
                if shared > 0:
                    column[position] = shared / total
        columns[key] = column

    return pd.DataFrame(columns, index=index)
```

- [ ] **Step 4: Correr las pruebas y ver que pasan**

Run: `uv run python -m pytest tests/test_areal.py -q`
Expected: PASS, 9 pruebas.

- [ ] **Step 5: Romper el código a propósito y confirmar que las pruebas se ponen rojas**

Este proyecto ya cazó tres pruebas que pasaban por la razón equivocada. No se confía en que una prueba tenga dientes: se comprueba.

Hacer cada mutación, correr `uv run python -m pytest tests/test_areal.py -q`, confirmar el fallo, y **revertirla** antes de la siguiente:

1. En `hex_polygons`, cambiar `[(lon, lat) for lat, lon in ...]` por `[(lat, lon) for lat, lon in ...]`.
   Debe fallar `test_hex_polygons_usa_lon_lat_no_lat_lon`.
2. En `area_weights`, cambiar `shared / total` por `shared / figures[position].area` (dividir entre el área del hexágono en vez de la del origen).
   Debe fallar `test_los_pesos_de_un_poligono_cubierto_suman_uno`.
3. En `area_weights`, cambiar `column = [0.0] * len(hex_ids)` por `column = [float("nan")] * len(hex_ids)`.
   Debe fallar `test_un_poligono_que_no_toca_nada_da_cero_no_nan`.

Si alguna mutación deja todo en verde, **la prueba no tiene dientes**: arreglar la prueba antes de seguir y reportarlo.

- [ ] **Step 6: Correr la suite entera**

Run: `uv run python -m pytest -q`
Expected: PASS. Antes de esta tarea eran 169; ahora deben ser 178.

- [ ] **Step 7: Commit**

```bash
git add src/rtgam/areal.py tests/test_areal.py
git commit -m "feat: primitiva de reparto areal entre poligonos y hexagonos"
```

---

## Task 2: Parseo del censo, confidenciales y viviendas colectivas

**Files:**
- Create: `src/rtgam/sources/censo.py`
- Test: `tests/test_censo_parseo.py`

**Interfaces:**
- Consumes: nada de la Task 1.
- Produces:
  - `GAM_MUN = "005"`
  - `NSE_COMPONENTS: tuple[tuple[str, str, str | None], ...]`
  - `AGEB_COLUMNS = ["cve_ageb", "pobtot", "internet", "automovil", "escolaridad"]`
  - `to_numeric(series: pd.Series) -> pd.Series`
  - `ageb_from_censo(frame: pd.DataFrame) -> pd.DataFrame` — indexado por `cve_ageb`, columnas `pobtot` (float), `internet`, `automovil`, `escolaridad` (float con NaN donde no hay dato)
  - `nse_index(ageb: pd.DataFrame) -> pd.Series` — indexada por `cve_ageb`, valores en [0, 1] o NaN

### Contexto de los datos, verificado contra el archivo real

El CSV del INEGI trae 230 columnas y una fila por manzana más filas de totales. Las columnas que importan:

| columna | qué es |
|---|---|
| `MUN` | clave de alcaldía; GAM es `"005"` |
| `AGEB` | clave del AGEB, 4 caracteres, puede traer letras (`"014A"`) |
| `MZA` | manzana; `"000"` marca la fila de total del AGEB |
| `POBTOT` | población total |
| `VIVPAR_HAB` | viviendas particulares habitadas |
| `VPH_INTER` | viviendas con internet |
| `VPH_AUTOM` | viviendas con automóvil |
| `GRAPROES` | grado promedio de escolaridad, en años |

Filtro de filas a nivel AGEB: `MUN == "005"` y `MZA == "000"` y `AGEB != "0000"`. Da **305 filas**.

**No filtrar por el texto de `NOM_LOC`.** Da el mismo resultado (305 con y sin), y comparar cadenas con acentos es la clase de cruce que ya costó caro aquí.

**Trampa 1 — los confidenciales.** El censo marca lo confidencial con el asterisco literal `"*"`, no con celda vacía. En GAM son dos AGEB:

| AGEB | POBTOT | VIVPAR_HAB | GRAPROES | VPH_INTER | VPH_AUTOM |
|---|---|---|---|---|---|
| 1646 | 7 | 4 | 8.14 | `*` | `*` |
| 1928 | 14 | `*` | `*` | `*` | `*` |

**Trampa 2 — las viviendas colectivas.** Tres AGEB traen `VIVPAR_HAB == 0`, y uno de ellos NO está vacío:

| AGEB | POBTOT | VIVPAR_HAB | GRAPROES | VPH_INTER | VPH_AUTOM |
|---|---|---|---|---|---|
| 0154 | **8,184** | 0 | 0.00 | 0 | 0 |
| 0718 | 0 | 0 | 0.00 | 0 | 0 |
| 1078 | 0 | 0 | 0.00 | 0 | 0 |

El AGEB 0154 tiene 8,184 habitantes en vivienda colectiva: el censo los cuenta en `POBTOT` pero no les levanta el cuestionario de vivienda. Eso produce `0 / 0` (numpy da `nan` con `RuntimeWarning`, no excepción) y un `GRAPROES` de `0.00` que **parece un dato y no lo es**. Tomado literal, ese AGEB sería el más pobre de GAM por goleada y anclaría el piso del min-max de los 724 hexágonos.

**La regla:** un AGEB con `VIVPAR_HAB` igual a cero, NaN o confidencial tiene sus **tres** componentes en NaN. Su población sí cuenta completa para densidad.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/test_censo_parseo.py`:

```python
"""Parseo del censo: confidenciales, viviendas colectivas e indice NSE."""

import warnings

import pandas as pd
import pytest

from rtgam.sources.censo import (
    AGEB_COLUMNS,
    ageb_from_censo,
    nse_index,
    to_numeric,
)


def fila(ageb, pobtot, vivpar, inter, autom, graproes, mun="005", mza="000"):
    """Una fila del CSV del INEGI, con solo las columnas que se usan."""
    return {
        "MUN": mun,
        "AGEB": ageb,
        "MZA": mza,
        "POBTOT": pobtot,
        "VIVPAR_HAB": vivpar,
        "VPH_INTER": inter,
        "VPH_AUTOM": autom,
        "GRAPROES": graproes,
    }


def censo(filas):
    return pd.DataFrame(filas, dtype=str)


def test_to_numeric_convierte_el_asterisco_en_nan_no_en_cero():
    # El censo marca lo confidencial con "*" literal. Un fillna(0) despues lo
    # volveria pobreza inventada, y con min-max eso ancla el piso de la
    # columna para los 724 hexagonos.
    serie = pd.Series(["1.5", "*", "3.0"])
    resultado = to_numeric(serie)
    assert resultado.iloc[0] == pytest.approx(1.5)
    assert pd.isna(resultado.iloc[1])
    assert resultado.iloc[2] == pytest.approx(3.0)


def test_solo_entran_las_filas_de_gam_a_nivel_ageb():
    frame = censo(
        [
            fila("0012", "100", "30", "20", "10", "9.5"),
            fila("0012", "50", "15", "10", "5", "9.5", mza="001"),  # manzana
            fila("0000", "999", "300", "200", "100", "9.0"),  # total de localidad
            fila("0027", "200", "60", "40", "20", "10.0", mun="010"),  # otra alcaldia
        ]
    )
    ageb = ageb_from_censo(frame)
    assert list(ageb.index) == ["0012"]


def test_las_columnas_son_las_del_contrato():
    frame = censo([fila("0012", "100", "30", "20", "10", "9.5")])
    ageb = ageb_from_censo(frame)
    assert ageb.index.name == "cve_ageb"
    assert list(ageb.columns) == [c for c in AGEB_COLUMNS if c != "cve_ageb"]


def test_las_tasas_se_calculan_sobre_las_viviendas_habitadas():
    frame = censo([fila("0012", "100", "40", "30", "10", "9.5")])
    ageb = ageb_from_censo(frame)
    assert ageb.loc["0012", "internet"] == pytest.approx(0.75)
    assert ageb.loc["0012", "automovil"] == pytest.approx(0.25)
    assert ageb.loc["0012", "escolaridad"] == pytest.approx(9.5)
    assert ageb.loc["0012", "pobtot"] == pytest.approx(100.0)


def test_un_componente_confidencial_queda_en_nan_pero_la_poblacion_no():
    # Caso real: el AGEB 1646 de GAM, 7 habitantes, internet y automovil
    # confidenciales pero escolaridad presente.
    frame = censo([fila("1646", "7", "4", "*", "*", "8.14")])
    ageb = ageb_from_censo(frame)
    assert pd.isna(ageb.loc["1646", "internet"])
    assert pd.isna(ageb.loc["1646", "automovil"])
    assert ageb.loc["1646", "escolaridad"] == pytest.approx(8.14)
    assert ageb.loc["1646", "pobtot"] == pytest.approx(7.0)


def test_vivienda_colectiva_no_entra_al_nse_pero_su_poblacion_si_cuenta():
    # Caso real: el AGEB 0154 de GAM. 8,184 habitantes en vivienda colectiva y
    # CERO viviendas particulares. El censo los cuenta en POBTOT pero no les
    # levanta el cuestionario de vivienda, asi que GRAPROES sale 0.00: parece
    # un dato y no lo es. Tomado literal seria el AGEB mas pobre de GAM y, con
    # min-max, anclaria el piso de la columna para los 724 hexagonos.
    frame = censo([fila("0154", "8184", "0", "0", "0", "0.00")])
    ageb = ageb_from_censo(frame)
    assert ageb.loc["0154", "pobtot"] == pytest.approx(8184.0)
    assert pd.isna(ageb.loc["0154", "internet"])
    assert pd.isna(ageb.loc["0154", "automovil"])
    assert pd.isna(ageb.loc["0154", "escolaridad"])


def test_vivienda_colectiva_no_dispara_un_runtimewarning_de_numpy():
    # El 0/0 de numpy avisa y sigue. Si el aviso aparece, la division se esta
    # haciendo antes de la guardia y el NaN sale por accidente, no por diseno.
    frame = censo([fila("0154", "8184", "0", "0", "0", "0.00")])
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        ageb_from_censo(frame)


def test_las_viviendas_habitadas_confidenciales_tambien_anulan_el_nse():
    # Caso real: el AGEB 1928 de GAM. Sin denominador no hay tasa que calcular.
    frame = censo([fila("1928", "14", "*", "*", "*", "*")])
    ageb = ageb_from_censo(frame)
    assert ageb.loc["1928", "pobtot"] == pytest.approx(14.0)
    assert ageb[["internet", "automovil", "escolaridad"]].isna().all(axis=None)


def test_las_claves_de_ageb_con_letra_se_conservan_como_texto():
    # El AGEB "014A" existe en GAM. Leido como numero se pierde, y leido como
    # float el "0012" se vuelve "12.0" y deja de cruzar con la geometria.
    frame = censo([fila("014A", "100", "30", "20", "10", "9.5")])
    ageb = ageb_from_censo(frame)
    assert list(ageb.index) == ["014A"]


def test_el_indice_escala_cada_componente_entre_cero_y_uno():
    ageb = pd.DataFrame(
        {
            "internet": [0.2, 0.6, 1.0],
            "automovil": [0.1, 0.3, 0.5],
            "escolaridad": [8.0, 10.0, 12.0],
        },
        index=pd.Index(["a", "b", "c"], name="cve_ageb"),
    )
    nse = nse_index(ageb)
    assert nse.loc["a"] == pytest.approx(0.0)
    assert nse.loc["c"] == pytest.approx(1.0)
    assert nse.loc["b"] == pytest.approx(0.5)


def test_el_indice_promedia_solo_los_componentes_presentes():
    # Con dos de tres, divide entre dos. Dividir siempre entre tres castigaria
    # a un AGEB por un dato que el INEGI no publico, no por ser mas pobre.
    ageb = pd.DataFrame(
        {
            "internet": [0.0, 1.0, 1.0],
            "automovil": [0.0, 1.0, 1.0],
            "escolaridad": [8.0, 12.0, float("nan")],
        },
        index=pd.Index(["a", "b", "c"], name="cve_ageb"),
    )
    nse = nse_index(ageb)
    assert nse.loc["c"] == pytest.approx(1.0)


def test_un_ageb_sin_ningun_componente_queda_en_nan_no_en_cero():
    ageb = pd.DataFrame(
        {
            "internet": [0.2, float("nan")],
            "automovil": [0.4, float("nan")],
            "escolaridad": [9.0, float("nan")],
        },
        index=pd.Index(["a", "vacio"], name="cve_ageb"),
    )
    nse = nse_index(ageb)
    assert pd.isna(nse.loc["vacio"])


def test_un_componente_constante_no_produce_nan_en_el_indice():
    # Si todos los AGEB tienen el mismo valor, max - min es cero. Dividir daria
    # NaN y contaminaria el indice entero.
    ageb = pd.DataFrame(
        {
            "internet": [0.5, 0.5],
            "automovil": [0.2, 0.8],
            "escolaridad": [9.0, 11.0],
        },
        index=pd.Index(["a", "b"], name="cve_ageb"),
    )
    nse = nse_index(ageb)
    assert not nse.isna().any()
```

- [ ] **Step 2: Correr las pruebas y ver que fallan**

Run: `uv run python -m pytest tests/test_censo_parseo.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'rtgam.sources.censo'`

- [ ] **Step 3: Escribir la implementación**

Crear `src/rtgam/sources/censo.py`:

```python
"""Fuente 4: densidad de poblacion y nivel socioeconomico del censo 2020.

Es la ultima fuente del score. Aporta `densidad_pob` y
`nivel_socioeconomico`, repartiendo los 305 AGEB de GAM sobre los 724
hexagonos por interseccion de area.

Los poligonos salen del portal de datos abiertos de la CDMX en GeoJSON y no
del shapefile del INEGI, y esa eleccion evita geopandas: un GeoJSON lo lee
json y lo convierte shapely, que ya es dependencia desde la fuente OSM. Son
los mismos poligonos del Marco Geoestadistico 2020, republicados.
"""

import numpy as np
import pandas as pd

GAM_MUN = "005"

# Nombre del componente, columna del numerador, columna del denominador.
# El denominador None significa que la columna se usa tal cual, sin ser tasa.
NSE_COMPONENTS = (
    ("internet", "VPH_INTER", "VIVPAR_HAB"),
    ("automovil", "VPH_AUTOM", "VIVPAR_HAB"),
    ("escolaridad", "GRAPROES", None),
)

AGEB_COLUMNS = ["cve_ageb", "pobtot", "internet", "automovil", "escolaridad"]


def to_numeric(series: pd.Series) -> pd.Series:
    """Convierte a float dejando NaN donde el censo marco confidencial.

    El INEGI marca lo confidencial con un asterisco literal, no con celda
    vacia. pd.to_numeric con errors="coerce" lo vuelve NaN, que es lo
    correcto; lo que nunca hay que hacer despues es rellenarlo con cero. Un
    cero es un dato —diria "aqui nadie tiene internet"— y con normalizacion
    min-max ancla el piso de la columna para los 724 hexagonos.
    """
    return pd.to_numeric(series, errors="coerce")


def ageb_from_censo(frame: pd.DataFrame) -> pd.DataFrame:
    """Filas a nivel AGEB de GAM, con la poblacion y los tres componentes.

    Devuelve un DataFrame indexado por cve_ageb con pobtot, internet,
    automovil y escolaridad. Los componentes vienen en NaN donde no hay dato.

    El filtro es por clave y no por el texto de NOM_LOC. Da exactamente las
    mismas 305 filas —medido— y comparar cadenas con acentos es la clase de
    cruce que ya costo caro en este proyecto.

    Las claves de AGEB se quedan como texto: "014A" existe en GAM, y leer la
    columna como numero convertiria "0012" en "12.0", que deja de cruzar con
    la geometria.
    """
    rows = frame[
        (frame["MUN"] == GAM_MUN)
        & (frame["MZA"] == "000")
        & (frame["AGEB"] != "0000")
    ].copy()

    out = pd.DataFrame(index=pd.Index(rows["AGEB"].astype(str), name="cve_ageb"))
    out["pobtot"] = to_numeric(rows["POBTOT"]).to_numpy()

    viviendas = to_numeric(rows["VIVPAR_HAB"]).to_numpy()
    # Sin viviendas particulares habitadas no hay tasa que calcular, y el cero
    # no es "cero por ciento": es que el censo no levanto el cuestionario de
    # vivienda. El AGEB 0154 de GAM tiene 8,184 habitantes en vivienda
    # colectiva, cero viviendas particulares y GRAPROES 0.00. Tomado literal
    # seria el AGEB mas pobre de la alcaldia y, como la normalizacion es
    # min-max, anclaria el piso de la columna para los 724 hexagonos.
    # La guardia va ANTES de dividir: el 0/0 de numpy avisa y sigue.
    sin_viviendas = ~(viviendas > 0)

    for name, numerator, denominator in NSE_COMPONENTS:
        values = to_numeric(rows[numerator]).to_numpy()
        if denominator is not None:
            values = np.divide(
                values,
                viviendas,
                out=np.full(len(values), np.nan),
                where=~sin_viviendas,
            )
        out[name] = np.where(sin_viviendas, np.nan, values)

    return out


def _scale_unit(values: pd.Series) -> pd.Series:
    """Escala una serie al rango [0, 1] ignorando los NaN.

    Los NaN se quedan NaN: son dato faltante, no un valor bajo.

    Si la serie es constante devuelve 0.5 donde hay dato, no NaN. Sin
    variacion ningun AGEB esta arriba ni abajo de otro, y un NaN aqui
    contaminaria el promedio del indice entero por un componente que
    simplemente no discrimina.
    """
    low, high = values.min(), values.max()
    if not np.isfinite(low) or not np.isfinite(high) or high == low:
        return pd.Series(
            np.where(values.notna(), 0.5, np.nan), index=values.index, dtype=float
        )
    return (values - low) / (high - low)


def nse_index(ageb: pd.DataFrame) -> pd.Series:
    """Indice de nivel socioeconomico, en [0, 1], o NaN si no hay ningun dato.

    Promedio de tres senales escaladas: porcentaje de viviendas con internet,
    porcentaje con automovil y anios de escolaridad. Ninguna sirve sola:
    internet se satura donde ya casi todos tienen conexion, el automovil sube
    en la periferia mal servida de transporte —Cuautepec y el norte de GAM— y
    la escolaridad va una generacion rezagada. Tres errores en tres
    direcciones distintas se cancelan en parte; uno solo, no.

    Promedia solo los componentes presentes. Dividir siempre entre tres
    castigaria a un AGEB por un dato que el INEGI no publico, no por ser mas
    pobre.

    Sale escalado y no crudo, contra la convencion del resto de las fuentes.
    Es deliberado y esta aprobado en el spec: promediar un porcentaje (0 a 1)
    con anios de escolaridad (0.00 a 15.87 en GAM) exige ponerlos en la misma
    escala antes, o la escolaridad domina por su magnitud y no por su
    importancia. 99_score.py volvera a normalizar la columna, lo que sobre un
    valor ya en [0, 1] solo lo reescala.
    """
    names = [name for name, _, _ in NSE_COMPONENTS]
    scaled = pd.DataFrame(
        {name: _scale_unit(ageb[name]) for name in names}, index=ageb.index
    )
    return scaled.mean(axis=1, skipna=True)
```

- [ ] **Step 4: Correr las pruebas y ver que pasan**

Run: `uv run python -m pytest tests/test_censo_parseo.py -q`
Expected: PASS, 13 pruebas.

- [ ] **Step 5: Romper el código a propósito y confirmar que las pruebas se ponen rojas**

Cada mutación por separado, revertir antes de la siguiente:

1. En `ageb_from_censo`, cambiar `sin_viviendas = ~(viviendas > 0)` por `sin_viviendas = np.isnan(viviendas)` (deja pasar el cero).
   Debe fallar `test_vivienda_colectiva_no_entra_al_nse_pero_su_poblacion_si_cuenta`.
2. En `to_numeric`, cambiar `errors="coerce"` por un `.fillna(0.0)` encima del resultado.
   Debe fallar `test_to_numeric_convierte_el_asterisco_en_nan_no_en_cero`.
3. En `nse_index`, cambiar `scaled.mean(axis=1, skipna=True)` por `scaled.fillna(0.0).mean(axis=1)`.
   Debe fallar `test_el_indice_promedia_solo_los_componentes_presentes`.
4. En `ageb_from_censo`, quitar el `.astype(str)` del índice.
   Debe fallar `test_las_claves_de_ageb_con_letra_se_conservan_como_texto` **o** ninguna: si ninguna falla, la prueba no tiene dientes con este fixture (que ya es texto). En ese caso, dejarlo anotado en el reporte — no es un fallo del código, es una prueba que solo protege contra una lectura mal configurada del CSV, y esa protección real vive en el `dtype=str` de la Task 4.

- [ ] **Step 6: Correr la suite entera**

Run: `uv run python -m pytest -q`
Expected: PASS, 191 pruebas.

- [ ] **Step 7: Commit**

```bash
git add src/rtgam/sources/censo.py tests/test_censo_parseo.py
git commit -m "feat: parseo del censo AGEB con guardias de confidencial y vivienda colectiva"
```

---

## Task 3: Las dos columnas del contrato

**Files:**
- Modify: `src/rtgam/sources/censo.py` (agregar al final)
- Test: `tests/test_censo_hexes.py`

**Interfaces:**
- Consumes:
  - `rtgam.areal.hex_polygons`, `rtgam.areal.area_weights` (Task 1)
  - `rtgam.sources.censo.nse_index` (Task 2)
- Produces:
  - `to_hex_features(gam_hexes: pd.DataFrame, ageb: pd.DataFrame, polygons: dict[str, Polygon]) -> pd.DataFrame` — indexado por `hex_id`, columnas exactamente `["densidad_pob", "nivel_socioeconomico"]`

### Las dos ponderaciones, que NO son la misma

Aquí es donde es fácil equivocarse en silencio:

- **`densidad_pob` se reparte por ÁREA.** Si el 38% del área de un AGEB cae en un hexágono, ese hexágono recibe el 38% de su población. Luego se divide entre `h3.cell_area(hex_id, "km^2")`.
- **`nivel_socioeconomico` se promedia pesado por la POBLACIÓN asignada, no por el área.** Un hexágono que toca un pedazo grande y despoblado de un AGEB —un parque, un panteón, una vialidad— no debe dejar que ese pedazo vote igual que una manzana llena. El NSE es un atributo de personas, no de terreno.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/test_censo_hexes.py`:

```python
"""Las dos columnas del contrato: densidad y nivel socioeconomico."""

import h3
import pandas as pd
import pytest
from shapely.geometry import Polygon

from rtgam.areal import hex_polygons
from rtgam.sources.censo import to_hex_features


def hexes_de(*ids):
    filas = [(h, *h3.cell_to_latlng(h)) for h in ids]
    return pd.DataFrame(filas, columns=["hex_id", "lat", "lon"]).set_index("hex_id")


def ageb_frame(filas):
    """filas: (cve_ageb, pobtot, internet, automovil, escolaridad)."""
    frame = pd.DataFrame(
        filas, columns=["cve_ageb", "pobtot", "internet", "automovil", "escolaridad"]
    )
    return frame.set_index("cve_ageb")


def poligono_de(hex_id, escala=1.0):
    """Poligono centrado en un hexagono, escalado desde su centroide."""
    lat, lon = h3.cell_to_latlng(hex_id)
    puntos = [(lo, la) for la, lo in h3.cell_to_boundary(hex_id)]
    return Polygon(
        [(lon + (x - lon) * escala, lat + (y - lat) * escala) for x, y in puntos]
    )


UNO = h3.latlng_to_cell(19.50, -99.10, 9)
DOS = h3.latlng_to_cell(19.52, -99.12, 9)


def test_las_columnas_son_exactamente_las_dos_del_contrato():
    hexes = hexes_de(UNO)
    ageb = ageb_frame([("a", 1000.0, 0.5, 0.3, 10.0)])
    features = to_hex_features(hexes, ageb, {"a": poligono_de(UNO)})
    assert list(features.columns) == ["densidad_pob", "nivel_socioeconomico"]
    assert list(features.index) == [UNO]


def test_la_densidad_es_poblacion_entre_kilometros_cuadrados():
    # Un AGEB que cubre exactamente un hexagono le entrega toda su poblacion.
    hexes = hexes_de(UNO)
    ageb = ageb_frame([("a", 1000.0, 0.5, 0.3, 10.0)])
    features = to_hex_features(hexes, ageb, {"a": poligono_de(UNO)})
    esperado = 1000.0 / h3.cell_area(UNO, "km^2")
    assert features.loc[UNO, "densidad_pob"] == pytest.approx(esperado, rel=1e-6)


def test_un_ageb_que_cubre_dos_hexagonos_reparte_su_poblacion_entre_ambos():
    # La conservacion exacta se prueba en test_areal; aqui se comprueba que
    # to_hex_features usa esos pesos y no le entrega la poblacion entera a
    # cada hexagono por separado.
    hexes = hexes_de(UNO, DOS)
    ageb = ageb_frame([("a", 1000.0, 0.5, 0.3, 10.0)])
    features = to_hex_features(hexes, ageb, {"a": poligono_de(UNO, escala=6.0)})
    area_km2 = h3.cell_area(UNO, "km^2")
    repartida = (features["densidad_pob"] * area_km2).sum()
    assert repartida < 1000.0, "el poligono se sale de los dos hexagonos"
    assert (features["densidad_pob"] > 0).all(), "los dos deben recibir gente"


def test_el_nse_pesa_por_poblacion_no_por_area():
    # El hexagono toca dos AGEB. El "rico" le aporta MAS AREA pero MENOS gente;
    # el "pobre" le aporta menos area y mucha mas gente. El resultado debe
    # inclinarse al pobre. Sin esta prueba, cambiar el peso de poblacion por
    # area pasaria inadvertido: los dos dan un numero plausible.
    hexes = hexes_de(UNO)
    ageb = ageb_frame(
        [
            ("rico", 10.0, 1.0, 1.0, 15.0),
            ("pobre", 5000.0, 0.0, 0.0, 6.0),
        ]
    )
    polygons = {
        "rico": poligono_de(UNO, escala=0.9),
        "pobre": poligono_de(UNO, escala=0.3),
    }
    features = to_hex_features(hexes, ageb, polygons)
    assert features.loc[UNO, "nivel_socioeconomico"] < 0.3


def test_un_ageb_sin_nse_no_arrastra_el_promedio_hacia_cero():
    # El AGEB de vivienda colectiva aporta poblacion pero no tiene NSE. Si
    # entrara como 0.0, hundiria el hexagono; debe quedar fuera del promedio.
    hexes = hexes_de(UNO)
    ageb = ageb_frame(
        [
            ("normal", 1000.0, 0.8, 0.6, 12.0),
            ("colectiva", 8184.0, float("nan"), float("nan"), float("nan")),
        ]
    )
    polygons = {
        "normal": poligono_de(UNO, escala=0.5),
        "colectiva": poligono_de(UNO, escala=0.5),
    }
    features = to_hex_features(hexes, ageb, polygons)
    solo_normal = to_hex_features(
        hexes, ageb.loc[["normal"]], {"normal": polygons["normal"]}
    )
    assert features.loc[UNO, "nivel_socioeconomico"] == pytest.approx(
        solo_normal.loc[UNO, "nivel_socioeconomico"]
    )


def test_la_poblacion_de_un_ageb_sin_nse_si_cuenta_para_densidad():
    hexes = hexes_de(UNO)
    ageb = ageb_frame([("colectiva", 8184.0, float("nan"), float("nan"), float("nan"))])
    features = to_hex_features(hexes, ageb, {"colectiva": poligono_de(UNO)})
    assert features.loc[UNO, "densidad_pob"] > 0.0


def test_la_salida_no_trae_nan():
    # merge_features lanza ante cualquier NaN de una fuente, y con razon.
    hexes = hexes_de(UNO, DOS)
    ageb = ageb_frame([("a", 1000.0, 0.5, 0.3, 10.0)])
    features = to_hex_features(hexes, ageb, {"a": poligono_de(UNO, escala=6.0)})
    assert not features.isna().any().any()


def test_un_desajuste_de_claves_lanza_en_vez_de_rellenar():
    # Un AGEB con censo pero sin poligono no tendria donde aterrizar; uno con
    # poligono pero sin censo pintaria un hueco como si fuera un descampado.
    hexes = hexes_de(UNO)
    ageb = ageb_frame([("a", 1000.0, 0.5, 0.3, 10.0)])
    with pytest.raises(ValueError, match="claves"):
        to_hex_features(hexes, ageb, {"b": poligono_de(UNO)})


def test_un_hexagono_sin_cobertura_lanza_en_vez_de_salir_en_cero():
    # En GAM hoy no pasa —cero de 724— pero el dia que pase, una densidad de
    # 0.0 seria el hexagono mas despoblado de la alcaldia sin que nada lo
    # dijera.
    hexes = hexes_de(UNO, DOS)
    ageb = ageb_frame([("a", 1000.0, 0.5, 0.3, 10.0)])
    with pytest.raises(ValueError, match="sin cobertura"):
        to_hex_features(hexes, ageb, {"a": poligono_de(UNO)})


def test_un_hexagono_cubierto_pero_sin_nse_lanza():
    hexes = hexes_de(UNO)
    ageb = ageb_frame([("colectiva", 100.0, float("nan"), float("nan"), float("nan"))])
    with pytest.raises(ValueError, match="nivel socioeconomico"):
        to_hex_features(hexes, ageb, {"colectiva": poligono_de(UNO)})
```

- [ ] **Step 2: Correr las pruebas y ver que fallan**

Run: `uv run python -m pytest tests/test_censo_hexes.py -q`
Expected: FAIL con `ImportError: cannot import name 'to_hex_features'`

- [ ] **Step 3: Escribir la implementación**

Agregar al final de `src/rtgam/sources/censo.py`. Añadir también los imports que faltan al principio del archivo (`from shapely.geometry import Polygon` no hace falta salvo para el type hint; sí hacen falta `h3` y las dos funciones de `rtgam.areal`):

```python
# Al principio del archivo, junto a los imports existentes:
# import h3
# from rtgam.areal import area_weights, hex_polygons


MIN_COVERAGE = 0.01


def to_hex_features(
    gam_hexes: pd.DataFrame,
    ageb: pd.DataFrame,
    polygons: dict,
) -> pd.DataFrame:
    """Emite las dos columnas que esta fuente posee.

    gam_hexes: indexado por hex_id, columnas lat y lon.
    ageb:      indexado por cve_ageb, columnas pobtot, internet, automovil y
               escolaridad.
    polygons:  cve_ageb -> Polygon, con exactamente las mismas claves que ageb.
    Devuelve:  DataFrame indexado por hex_id con densidad_pob (cruda, en
               hab/km2) y nivel_socioeconomico (escalado 0-1, ver nse_index).

    Las dos columnas se reparten con ponderaciones DISTINTAS, y confundirlas
    no lanza nada:

    - densidad_pob va por AREA. Si el 38% del area de un AGEB cae en un
      hexagono, ese hexagono recibe el 38% de su poblacion.
    - nivel_socioeconomico va pesado por la POBLACION asignada. Un hexagono
      que toca un pedazo grande y despoblado de un AGEB —un parque, un panteon,
      una vialidad— no debe dejar que ese pedazo vote igual que una manzana
      llena. El NSE es un atributo de personas, no de terreno.
    """
    if set(polygons) != set(ageb.index):
        faltan_poligono = sorted(set(ageb.index) - set(polygons))[:5]
        faltan_censo = sorted(set(polygons) - set(ageb.index))[:5]
        raise ValueError(
            f"Las claves de AGEB no coinciden entre censo y geometria. "
            f"Con censo y sin poligono: {faltan_poligono}. Con poligono y sin "
            f"censo: {faltan_censo}. Rellenar convertiria un hueco de datos en "
            f"un descampado plausible."
        )

    weights = area_weights(hex_polygons(gam_hexes), polygons)
    weights = weights[list(ageb.index)]

    poblacion = weights @ ageb["pobtot"].to_numpy(dtype=float)

    cubierto = weights.sum(axis=1)
    sin_cobertura = cubierto[cubierto < MIN_COVERAGE]
    if len(sin_cobertura):
        raise ValueError(
            f"{len(sin_cobertura)} hexagonos quedaron sin cobertura de AGEB, "
            f"por ejemplo {list(sin_cobertura.index[:5])}. Una densidad de 0.0 "
            f"seria el hexagono mas despoblado de la alcaldia sin que nada lo "
            f"dijera."
        )

    nse = nse_index(ageb)
    # El peso del NSE es la poblacion asignada, no el area: un pedazo grande y
    # despoblado no debe pesar como uno chico y lleno. Los AGEB sin NSE quedan
    # fuera del promedio en vez de entrar como cero, que los hundiria.
    aporte = weights.mul(ageb["pobtot"].to_numpy(dtype=float), axis=1)
    con_nse = aporte.loc[:, nse.notna().to_numpy()]
    valores = nse.dropna().to_numpy(dtype=float)

    total_nse = con_nse.sum(axis=1)
    sin_nse = total_nse[total_nse <= 0]
    if len(sin_nse):
        raise ValueError(
            f"{len(sin_nse)} hexagonos no tocan ningun AGEB con nivel "
            f"socioeconomico, por ejemplo {list(sin_nse.index[:5])}. Un 0.0 "
            f"seria el hexagono mas pobre de la alcaldia sin que nada lo dijera."
        )

    promedio = (con_nse @ valores) / total_nse

    area_km2 = pd.Series(
        {hex_id: h3.cell_area(hex_id, "km^2") for hex_id in gam_hexes.index}
    )

    return pd.DataFrame(
        {
            "densidad_pob": poblacion / area_km2,
            "nivel_socioeconomico": promedio,
        }
    )
```

- [ ] **Step 4: Correr las pruebas y ver que pasan**

Run: `uv run python -m pytest tests/test_censo_hexes.py -q`
Expected: PASS, 10 pruebas.

- [ ] **Step 5: Romper el código a propósito y confirmar que las pruebas se ponen rojas**

Cada mutación por separado, revertir antes de la siguiente:

1. Cambiar `aporte = weights.mul(ageb["pobtot"]...)` por `aporte = weights` (pesar por área en vez de por población).
   Debe fallar `test_el_nse_pesa_por_poblacion_no_por_area`.
2. Cambiar `con_nse = aporte.loc[:, nse.notna().to_numpy()]` y `valores = nse.dropna()...` por usar `nse.fillna(0.0)` completo.
   Debe fallar `test_un_ageb_sin_nse_no_arrastra_el_promedio_hacia_cero`.
3. Quitar el bloque `if set(polygons) != set(ageb.index)`.
   Debe fallar `test_un_desajuste_de_claves_lanza_en_vez_de_rellenar`.
4. Quitar el bloque de `sin_cobertura`.
   Debe fallar `test_un_hexagono_sin_cobertura_lanza_en_vez_de_salir_en_cero`.
5. Cambiar `poblacion / area_km2` por `poblacion` a secas.
   Debe fallar `test_la_densidad_es_poblacion_entre_kilometros_cuadrados`.

- [ ] **Step 6: Correr la suite entera**

Run: `uv run python -m pytest -q`
Expected: PASS, 201 pruebas.

- [ ] **Step 7: Commit**

```bash
git add src/rtgam/sources/censo.py tests/test_censo_hexes.py
git commit -m "feat: densidad y nivel socioeconomico repartidos por area a los hexagonos"
```

---

## Task 4: Descarga y caché

**Files:**
- Modify: `src/rtgam/sources/censo.py` (agregar)
- Modify: `src/rtgam/sources/denue.py` — renombrar `_first_csv` a `first_csv` (definición en la línea 94, usos en las líneas 72 y 87; ninguna prueba lo referencia)
- Test: `tests/test_censo_fetch.py`

**Interfaces:**
- Consumes: `ageb_from_censo` (Task 2).
- Produces:
  - `CENSO_URL`, `AGEB_GEOJSON_URL`, `CENSO_TIMEOUT_S`
  - `fetch_censo(cache_dir: Path, force: bool = False) -> pd.DataFrame` — el CSV crudo, `dtype=str`
  - `fetch_ageb_polygons(cache_path: Path, force: bool = False) -> dict[str, Polygon]` — solo los AGEB de GAM, clave `CVE_AGEB`
  - `polygons_from_geojson(payload: dict) -> dict[str, Polygon]`

### URLs verificadas contra el servidor real

```python
CENSO_URL = "https://www.inegi.org.mx/contenidos/programas/ccpv/2020/datosabiertos/ageb_manzana/ageb_mza_urbana_09_cpv2020_csv.zip"
AGEB_GEOJSON_URL = "https://datos.cdmx.gob.mx/dataset/d2ccf6ae-fdf4-407c-a15f-e7dfac2d509d/resource/7b0b7a89-d92e-46ec-9286-018e849f8123/download/lmites-de-ageb-urbanas-en-la-ciudad-de-mxico.json"
```

El zip son 13.0 MB y trae el CSV bajo `ageb_mza_urbana_09_cpv2020/conjunto_de_datos/`, junto con un diccionario de datos y metadatos. **Igual que en DENUE, ordenados alfabéticamente `diccionario_de_datos` va ANTES que `conjunto_de_datos`**: tomar el primer `.csv` a secas agarra el diccionario.

Reusar el helper de `denue.py` importándolo, en vez de copiar la lógica: es el mismo zip del mismo instituto con la misma estructura, y duplicarla significa arreglar el mismo bug dos veces. Como el helper es privado (`_first_csv`), **renombrarlo a `first_csv` en `denue.py` y actualizar sus dos usos ahí**, para no importar un nombre privado entre módulos. Es el único cambio permitido a `denue.py` en este plan, y no altera su comportamiento.

El GeoJSON son 7.5 MB, 2,431 features de toda la CDMX. Propiedades por feature: `CVEGEO`, `CVE_ENT`, `CVE_MUN`, `CVE_LOC`, `CVE_AGEB`. Los de GAM son los que tienen `CVE_MUN == "005"`: **305**, verificado.

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/test_censo_fetch.py`:

```python
"""Descarga del censo y de los poligonos, con cache y validacion."""

import io
import json
import zipfile

import pytest
import requests

from rtgam import USER_AGENT
from rtgam.sources import censo


class RespuestaFalsa:
    def __init__(self, content=b"", payload=None, status=200):
        self.content = content
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"status {self.status_code}")
            error.response = self
            raise error

    def json(self):
        if self._payload is None:
            raise ValueError("no es json")
        return self._payload


def zip_del_censo(filas="MUN,AGEB,MZA,POBTOT\n005,0012,000,100\n"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("x/diccionario_de_datos/diccionario.csv", "a,b\n1,2\n")
        zf.writestr("x/conjunto_de_datos/datos.csv", filas)
    return buffer.getvalue()


def geojson_de(features):
    return {"type": "FeatureCollection", "features": features}


def feature(cve_ageb, cve_mun="005"):
    return {
        "type": "Feature",
        "properties": {"CVE_AGEB": cve_ageb, "CVE_MUN": cve_mun},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        },
    }


def test_los_poligonos_se_filtran_a_gam():
    payload = geojson_de([feature("0012"), feature("1716", cve_mun="010")])
    polygons = censo.polygons_from_geojson(payload)
    assert set(polygons) == {"0012"}


def test_un_geojson_sin_features_lanza_y_no_se_cachea(tmp_path, monkeypatch):
    cache = tmp_path / "ageb.geojson"
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: RespuestaFalsa(payload={"type": "X"})
    )
    with pytest.raises(ValueError):
        censo.fetch_ageb_polygons(cache)
    assert not cache.exists(), "un payload inservible no se persiste"


def test_un_geojson_sin_ageb_de_gam_lanza(tmp_path, monkeypatch):
    # Si la CDMX cambia la clave de alcaldia, GAM saldria vacia y las dos
    # columnas en cero sin que nada fallara.
    payload = geojson_de([feature("1716", cve_mun="010")])
    monkeypatch.setattr(requests, "get", lambda *a, **k: RespuestaFalsa(payload=payload))
    with pytest.raises(ValueError, match="GAM"):
        censo.fetch_ageb_polygons(tmp_path / "ageb.geojson")


def test_la_peticion_del_geojson_manda_el_user_agent(tmp_path, monkeypatch):
    vistos = {}

    def falso_get(url, **kwargs):
        vistos.update(kwargs)
        return RespuestaFalsa(payload=geojson_de([feature("0012")]))

    monkeypatch.setattr(requests, "get", falso_get)
    censo.fetch_ageb_polygons(tmp_path / "ageb.geojson")
    assert vistos["headers"]["User-Agent"] == USER_AGENT


def test_el_geojson_valido_si_se_cachea_y_se_relee(tmp_path, monkeypatch):
    cache = tmp_path / "ageb.geojson"
    payload = geojson_de([feature("0012")])
    monkeypatch.setattr(requests, "get", lambda *a, **k: RespuestaFalsa(payload=payload))
    censo.fetch_ageb_polygons(cache)
    assert cache.exists()

    def no_llamar(*a, **k):
        raise AssertionError("con cache no debe volver a descargar")

    monkeypatch.setattr(requests, "get", no_llamar)
    polygons = censo.fetch_ageb_polygons(cache)
    assert set(polygons) == {"0012"}


def test_force_vuelve_a_descargar_aunque_haya_cache(tmp_path, monkeypatch):
    cache = tmp_path / "ageb.geojson"
    cache.write_text(json.dumps(geojson_de([feature("9999")])), encoding="utf-8")
    payload = geojson_de([feature("0012")])
    monkeypatch.setattr(requests, "get", lambda *a, **k: RespuestaFalsa(payload=payload))
    polygons = censo.fetch_ageb_polygons(cache, force=True)
    assert set(polygons) == {"0012"}


def test_una_cache_de_geojson_corrupta_lanza_con_instrucciones(tmp_path):
    cache = tmp_path / "ageb.geojson"
    cache.write_text("{no es json", encoding="utf-8")
    with pytest.raises(ValueError, match="force"):
        censo.fetch_ageb_polygons(cache)


def test_el_censo_lee_el_csv_de_conjunto_de_datos_no_el_diccionario(
    tmp_path, monkeypatch
):
    # El zip trae tres CSV y, alfabeticamente, diccionario_de_datos va ANTES
    # que conjunto_de_datos. Tomar el primero devuelve el diccionario.
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: RespuestaFalsa(content=zip_del_censo())
    )
    frame = censo.fetch_censo(tmp_path)
    assert "POBTOT" in frame.columns


def test_el_censo_se_lee_como_texto_para_no_perder_las_claves(tmp_path, monkeypatch):
    # "0012" leido como numero se vuelve 12 y deja de cruzar con la geometria.
    filas = "MUN,AGEB,MZA,POBTOT\n005,0012,000,100\n"
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: RespuestaFalsa(content=zip_del_censo(filas))
    )
    frame = censo.fetch_censo(tmp_path)
    assert frame.loc[0, "AGEB"] == "0012"


def test_un_zip_del_censo_invalido_no_deja_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: RespuestaFalsa(content=b"esto no es un zip")
    )
    with pytest.raises(ValueError):
        censo.fetch_censo(tmp_path)
    assert not (tmp_path / "censo_ageb_09.zip").exists()


def test_la_peticion_del_censo_manda_el_user_agent(tmp_path, monkeypatch):
    vistos = {}

    def falso_get(url, **kwargs):
        vistos.update(kwargs)
        return RespuestaFalsa(content=zip_del_censo())

    monkeypatch.setattr(requests, "get", falso_get)
    censo.fetch_censo(tmp_path)
    assert vistos["headers"]["User-Agent"] == USER_AGENT
```

- [ ] **Step 2: Correr las pruebas y ver que fallan**

Run: `uv run python -m pytest tests/test_censo_fetch.py -q`
Expected: FAIL con `AttributeError: module 'rtgam.sources.censo' has no attribute 'polygons_from_geojson'`

- [ ] **Step 3: Escribir la implementación**

Agregar a `src/rtgam/sources/censo.py`. Imports nuevos al principio: `io`, `json`, `zipfile`, `from pathlib import Path`, `import requests`, `from shapely.geometry import shape`, `from rtgam import USER_AGENT`, `from rtgam.sources.denue import first_csv`.

```python
CENSO_URL = (
    "https://www.inegi.org.mx/contenidos/programas/ccpv/2020/datosabiertos/"
    "ageb_manzana/ageb_mza_urbana_09_cpv2020_csv.zip"
)
AGEB_GEOJSON_URL = (
    "https://datos.cdmx.gob.mx/dataset/d2ccf6ae-fdf4-407c-a15f-e7dfac2d509d/"
    "resource/7b0b7a89-d92e-46ec-9286-018e849f8123/download/"
    "lmites-de-ageb-urbanas-en-la-ciudad-de-mxico.json"
)
CENSO_TIMEOUT_S = 300


def polygons_from_geojson(payload: dict) -> dict:
    """Poligonos de los AGEB de GAM, indexados por su clave de cuatro digitos.

    El GeoJSON del portal de la CDMX cubre las 2,431 AGEB de la ciudad; los de
    GAM son los que traen CVE_MUN igual a 005. Son 305, verificado contra el
    archivo real.
    """
    features = payload.get("features")
    if not features:
        raise ValueError(
            "El GeoJSON de AGEB no trae 'features'. No es una respuesta util y "
            "no se va a cachear."
        )

    polygons = {
        feature["properties"]["CVE_AGEB"]: shape(feature["geometry"])
        for feature in features
        if feature.get("properties", {}).get("CVE_MUN") == GAM_MUN
    }

    if not polygons:
        raise ValueError(
            f"Ningun AGEB con CVE_MUN == {GAM_MUN!r} en el GeoJSON. Si la CDMX "
            f"cambio la clave de alcaldia, GAM saldria vacia y las dos columnas "
            f"en cero sin que nada fallara."
        )
    return polygons


def fetch_ageb_polygons(cache_path: Path, force: bool = False) -> dict:
    """Descarga los poligonos de AGEB, con cache en disco.

    Se valida ANTES de escribir la cache. Al reves, una respuesta inservible
    queda persistida y envenena todas las corridas siguientes, que releen el
    mismo payload malo. Se corrigio tres veces en este proyecto por no hacerlo.
    """
    if cache_path.exists() and not force:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"La cache {cache_path} esta corrupta o truncada. Borrala o "
                f"corre con --force para volver a descargar. ({error})"
            ) from error
        return polygons_from_geojson(payload)

    response = requests.get(
        AGEB_GEOJSON_URL,
        headers={"User-Agent": USER_AGENT},
        timeout=CENSO_TIMEOUT_S,
    )
    response.raise_for_status()
    payload = response.json()

    polygons = polygons_from_geojson(payload)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return polygons


def fetch_censo(cache_dir: Path, force: bool = False) -> pd.DataFrame:
    """Descarga el censo por AGEB de la CDMX y devuelve el CSV crudo.

    Todo se lee como texto: "0012" leido como numero se vuelve 12 y deja de
    cruzar con la clave de la geometria, sin que nada falle.

    El zip se escribe DESPUES de comprobar que abre y trae el CSV de datos.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "censo_ageb_09.zip"

    if zip_path.exists() and not force:
        try:
            with zipfile.ZipFile(zip_path) as zf:
                return _read_censo_csv(zf)
        except zipfile.BadZipFile as error:
            raise ValueError(
                f"La cache {zip_path} esta corrupta o truncada. Borrala o "
                f"corre con --force para volver a descargar. ({error})"
            ) from error

    response = requests.get(
        CENSO_URL, headers={"User-Agent": USER_AGENT}, timeout=CENSO_TIMEOUT_S
    )
    response.raise_for_status()

    content = response.content
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            frame = _read_censo_csv(zf)
    except zipfile.BadZipFile as error:
        raise ValueError(
            f"La respuesta de {CENSO_URL} no es un zip valido. No se cachea. "
            f"({error})"
        ) from error

    zip_path.write_bytes(content)
    return frame


def _read_censo_csv(zf: zipfile.ZipFile) -> pd.DataFrame:
    """Lee el CSV de datos del zip, como texto.

    first_csv de denue.py ya resuelve el mismo problema: el zip del INEGI trae
    un diccionario de datos y unos metadatos junto a los datos, y ordenados
    alfabeticamente 'diccionario_de_datos' va ANTES que 'conjunto_de_datos'.
    """
    name = first_csv(zf)
    with zf.open(name) as handle:
        return pd.read_csv(handle, dtype=str, low_memory=False)
```

- [ ] **Step 4: Correr las pruebas y ver que pasan**

Run: `uv run python -m pytest tests/test_censo_fetch.py -q`
Expected: PASS, 12 pruebas.

- [ ] **Step 5: Romper el código a propósito y confirmar que las pruebas se ponen rojas**

Cada mutación por separado, revertir antes de la siguiente:

1. En `fetch_ageb_polygons`, mover `cache_path.write_text(...)` a **antes** de la llamada a `polygons_from_geojson`.
   Debe fallar `test_un_geojson_sin_features_lanza_y_no_se_cachea` **en la aserción del `cache.exists()`**, no solo en la excepción. Confirmar cuál aserción falla.
2. Quitar `headers={"User-Agent": USER_AGENT}` de cualquiera de las dos peticiones.
   Debe fallar la prueba de User-Agent correspondiente.
3. En `_read_censo_csv`, cambiar `dtype=str` por nada.
   Debe fallar `test_el_censo_se_lee_como_texto_para_no_perder_las_claves`.
4. En `fetch_censo`, mover `zip_path.write_bytes(content)` a antes del bloque `try`.
   Debe fallar `test_un_zip_del_censo_invalido_no_deja_cache`.

- [ ] **Step 6: Correr la suite entera**

Run: `uv run python -m pytest -q`
Expected: PASS, 213 pruebas.

- [ ] **Step 7: Commit**

```bash
git add src/rtgam/sources/censo.py tests/test_censo_fetch.py
git commit -m "feat: descarga del censo AGEB y de los poligonos con validacion previa"
```

---

## Task 5: Script, corrida real y documentación

**Files:**
- Create: `scripts/05_censo.py`
- Modify: `README.md`, `HANDOFF.md`

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: `data/processed/censo.parquet`.

**ADVERTENCIA:** este script descarga 13 MB + 7.5 MB y procesa un CSV de 44 MB. **Correr en PRIMER PLANO, con `timeout: 600000` en la llamada de Bash.** Un script largo en background muere con su proceso padre; ya le pasó a cinco agentes en este repo.

- [ ] **Step 1: Escribir el script**

Crear `scripts/05_censo.py`:

```python
"""Fuente 4: densidad de poblacion y nivel socioeconomico del censo 2020.

Entrada: se descargan solos (13 MB del INEGI + 7.5 MB de la CDMX)
         + data/processed/gam_hexes.parquet
Salida:  data/processed/censo.parquet

Uso:
    uv run python scripts/05_censo.py [--force]

Tarda un par de minutos: el CSV del censo son 44 MB. Correr en primer plano,
no en background.
"""

import argparse
from pathlib import Path

import pandas as pd

from rtgam.sources.censo import (
    ageb_from_censo,
    fetch_ageb_polygons,
    fetch_censo,
    nse_index,
    to_hex_features,
)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
GEOJSON_CACHE = RAW / "ageb_cdmx.geojson"
HEXES = ROOT / "data" / "processed" / "gam_hexes.parquet"
OUTPUT = ROOT / "data" / "processed" / "censo.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-descargar aunque exista cache"
    )
    args = parser.parse_args()

    print("Descargando el censo por AGEB (13 MB, el CSV son 44 MB)...")
    crudo = fetch_censo(RAW, force=args.force)
    ageb = ageb_from_censo(crudo)
    print(f"AGEB de GAM en el censo: {len(ageb)}")
    print(f"Poblacion total: {ageb['pobtot'].sum():,.0f}")

    print("Descargando los poligonos de AGEB (7.5 MB)...")
    polygons = fetch_ageb_polygons(GEOJSON_CACHE, force=args.force)
    print(f"AGEB de GAM con geometria: {len(polygons)}")

    # Guardia de cruce. Un AGEB con censo pero sin poligono no tiene donde
    # aterrizar; uno con poligono pero sin censo pintaria un hueco de datos
    # como si fuera un descampado real. to_hex_features vuelve a comprobarlo,
    # pero aqui el mensaje sale antes y con contexto.
    solo_censo = sorted(set(ageb.index) - set(polygons))
    solo_geo = sorted(set(polygons) - set(ageb.index))
    if solo_censo or solo_geo:
        raise ValueError(
            f"Las claves de AGEB no cuadran. Con censo y sin poligono: "
            f"{solo_censo[:5]}. Con poligono y sin censo: {solo_geo[:5]}."
        )

    nse = nse_index(ageb)
    sin_nse = ageb.index[nse.isna()]
    print(f"AGEB sin nivel socioeconomico: {len(sin_nse)} ({list(sin_nse)})")
    colectivas = ageb.index[ageb[["internet", "automovil", "escolaridad"]].isna().all(axis=1)]
    poblacion_colectiva = ageb.loc[colectivas, "pobtot"].sum()
    print(
        f"Poblacion en AGEB sin cuestionario de vivienda: "
        f"{poblacion_colectiva:,.0f} habitantes"
    )

    hexes = pd.read_parquet(HEXES)
    features = to_hex_features(hexes, ageb, polygons)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(OUTPUT)

    area_km2 = 0.12156802899339546  # H3 resolucion 9
    repartida = (features["densidad_pob"] * area_km2).sum()
    print()
    print(
        f"Poblacion repartida a la reticula: {repartida:,.0f} de "
        f"{ageb['pobtot'].sum():,.0f} ({repartida / ageb['pobtot'].sum():.1%})"
    )
    for columna in ["densidad_pob", "nivel_socioeconomico"]:
        serie = features[columna]
        print(
            f"{columna}: {(serie > 0).sum()} de {len(serie)} hexagonos con senal "
            f"| media {serie.mean():.4f} | min {serie.min():.4f} "
            f"| max {serie.max():.4f}"
        )
    print()
    print("Top 5 por densidad_pob:")
    print(features.nlargest(5, "densidad_pob").to_string())
    print(f"Escrito: {OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Correr el script de verdad**

Run: `uv run python scripts/05_censo.py`
**En PRIMER PLANO, con `timeout: 600000`.** No mandarlo a background.

Cifras esperadas, medidas durante el diseño contra los datos reales:

| | valor esperado |
|---|---|
| AGEB de GAM en el censo | 305 |
| AGEB de GAM con geometría | 305 |
| población total | 1,173,351 |
| población repartida a la retícula | ~1,137,079 (96.9%) |
| AGEB sin NSE | 3 (`0154`, `0718`, `1078`) más `1928` = 4 |
| población en vivienda colectiva | 8,184 |
| densidad mediana | ~13,238 hab/km² |
| densidad máxima | ~33,806 hab/km² |

**Reportar las cifras REALES que salgan, sean cuales sean, sin ajustarlas a esta tabla.** Si alguna difiere de forma material, decirlo explícitamente en el reporte: la tabla es una expectativa del diseño, no una verdad. En particular, el conteo de "AGEB sin NSE" combina dos causas distintas (confidencial y vivienda colectiva) y puede salir distinto.

Si el script lanza, **no ajustar la guardia para que pase**: la guardia es el producto. Reportar y parar.

- [ ] **Step 3: Correr el score completo**

Run: `uv run python scripts/99_score.py`
**En PRIMER PLANO.**

Debe imprimir las **siete** variables en el score y ninguna en "sin datos". Anotar el score máximo y compararlo con el anterior, que era `0.5136` con cinco variables.

- [ ] **Step 4: Verificar que el núcleo no se tocó**

Run: `git diff --stat main -- src/rtgam/geo.py src/rtgam/score.py src/rtgam/normalize.py scripts/99_score.py config/weights.yaml app/`
Expected: salida VACÍA. Si algo aparece ahí, es una violación de las Global Constraints: revertirlo y reportar.

- [ ] **Step 5: Actualizar la documentación**

En `README.md`:
- En la lista de limitaciones, quitar la línea que dice que hay datos de cinco de las siete variables y ponerla en **siete de siete**.
- Agregar las limitaciones de esta fuente, con las cifras REALES de la corrida:
  - El reparto areal supone población repartida pareja dentro del AGEB; es falso donde hay un parque, un panteón o una zona industrial grande.
  - El censo es de 2020, seis años atrás.
  - El X% de la población de GAM cae fuera de la retícula (poner la cifra real).
  - `nivel_socioeconomico` es un índice compuesto de tres proxies, no un dato del censo ni una medición de ingreso.
  - La columna sale escalada 0-1 y no cruda, contra la convención del resto de las fuentes.
  - Los habitantes en vivienda colectiva cuentan para densidad pero no tienen NSE; los hexágonos que los tocan promedian con los AGEB vecinos.

En `HANDOFF.md`:
- Tabla de variables: `densidad_pob` y `nivel_socioeconomico` pasan a ✅.
- Actualizar el score máximo con el real.
- En "Lo siguiente": el censo ya no es el pendiente. Lo que queda son las ideas anotadas: presencia de estación como variable separada del volumen, y la deuda de `transporte.py::fetch_stations`, que cachea `response.json()` crudo y nunca revisa `remark`.
- Agregar `uv run python scripts/05_censo.py` al orden de corrida, antes de `99_score.py`.
- Anotar en "Trampas conocidas" el hallazgo de vivienda colectiva: `VIVPAR_HAB == 0` con 8,184 habitantes, el `0/0` y el `GRAPROES = 0.00` que parece dato.

- [ ] **Step 6: Correr la suite entera una última vez**

Run: `uv run python -m pytest -q`
Expected: PASS, 213 pruebas.

- [ ] **Step 7: Commit**

```bash
git add scripts/05_censo.py README.md HANDOFF.md
git commit -m "feat: script del censo AGEB y documentacion actualizada"
```

---

## Self-review del plan

**Cobertura del spec:**

| requisito del spec | tarea |
|---|---|
| primitiva `areal.py` con `hex_polygons` y `area_weights` | 1 |
| cada columna de pesos suma como mucho 1.0 | 1 |
| no reproyectar | 1 |
| filtro de filas AGEB sin usar `NOM_LOC` | 2 |
| `*` → NaN, nunca 0 | 2 |
| `VIVPAR_HAB == 0` anula los tres componentes | 2 |
| sin `RuntimeWarning` por el `0/0` | 2 |
| índice de tres señales escaladas | 2 |
| promedia solo los componentes presentes | 2 |
| densidad por área, NSE por población | 3 |
| guardia de desajuste de claves | 3 y 5 |
| guardia de hexágono sin cobertura | 3 |
| guardia de hexágono sin NSE | 3 |
| salida sin NaN | 3 |
| dos columnas exactas | 3 |
| validar antes de cachear | 4 |
| `User-Agent` obligatorio | 4 |
| CSV leído como texto | 4 |
| CSV de `conjunto_de_datos`, no el diccionario | 4 |
| corrida real y cifras | 5 |
| limitaciones al README | 5 |

**Consistencia de tipos:** `ageb_from_censo` produce el DataFrame indexado por `cve_ageb` que consumen `nse_index` y `to_hex_features`. `hex_polygons` produce el dict que consume `area_weights`. `fetch_ageb_polygons` produce el dict que consume `to_hex_features`. `fetch_censo` produce el DataFrame crudo que consume `ageb_from_censo`.

**Conteo de pruebas acumulado:** 169 (antes) → 178 (T1) → 191 (T2) → 201 (T3) → 213 (T4) → 213 (T5, no agrega pruebas).
