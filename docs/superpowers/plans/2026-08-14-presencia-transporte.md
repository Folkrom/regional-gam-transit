# Presencia de transporte — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar `presencia_transporte`, una variable que mide cercanía a la estación de riel o cable más cercana, para que el corredor del Cablebús Línea 1 —hoy con `flujo_transporte` exactamente cero— deje de ser invisible para el score.

**Architecture:** Una primitiva nueva en `geo.py` (`nearest_decay`, máximo del kernel en vez de suma), un clasificador de estaciones por estructura de etiqueta en `transporte.py`, la fuente 1 emitiendo dos columnas en vez de una, y las estaciones saliendo de `atractores_osm` para que no cuenten dos veces.

**Tech Stack:** Python 3, pandas, numpy, h3-py, shapely, pytest. Sin geopandas, sin PostGIS, sin dependencias nuevas.

**Spec:** `docs/superpowers/specs/2026-08-14-presencia-transporte-design.md`

## Global Constraints

- Comentarios y docstrings del código fuente **en español SIN acentos**. Markdown (README, HANDOFF, specs) **con acentos**.
- Nada de dependencias nuevas. No geopandas, no PostGIS, no APIs de pago.
- `tau = 300.0` metros, `cutoff = 800.0` metros. Son `DECAY_TAU_M` y `DECAY_CUTOFF_M`, ya definidas en `src/rtgam/geo.py`. No se introducen constantes nuevas.
- El **nombre de columna** `flujo_transporte` NO cambia. Solo cambia el nombre del **archivo** parquet.
- Los valores de `flujo_transporte` deben quedar **idénticos** a los de hoy. Cualquier cambio numérico en esa columna es un defecto, no un efecto secundario.
- Precedencia de clase de estación, determinista y no dependiente del orden del payload: `cable` > `riel` > descartada.
- Nunca `git add -A`. Agregar archivos por ruta explícita.
- Nunca agregar `Co-Authored-By` ni pie de Claude Code a los commits.
- Los tests corren con `uv run pytest`. La suite entera está verde hoy (222 tests) y debe seguirlo al final de cada tarea.

---

### Task 1: `nearest_decay` en geo.py

**Files:**
- Modify: `src/rtgam/geo.py` (al final, después de `accumulate_decay`)
- Test: `tests/test_geo.py`

**Interfaces:**
- Consumes: `haversine_m`, `DECAY_TAU_M`, `DECAY_CUTOFF_M` de `rtgam.geo`
- Produces: `nearest_decay(centroids: pd.DataFrame, points: pd.DataFrame, tau: float = DECAY_TAU_M, cutoff: float = DECAY_CUTOFF_M) -> pd.Series` — Series de floats alineada al índice de `centroids`, valores en `[0, 1]`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_geo.py`:

```python
def test_nearest_decay_toma_el_maximo_no_la_suma():
    # Tres puntos colocados a 300 m contra uno solo a 300 m: el maximo es
    # identico, la suma seria el triple. Las distancias estan elegidas para
    # que suma y maximo NO coincidan por casualidad.
    centroids = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index(["a"], name="hex_id")
    )
    uno = pd.DataFrame({"lat": [19.5 + 300 / 111_000], "lon": [-99.1]})
    tres = pd.DataFrame(
        {"lat": [19.5 + 300 / 111_000] * 3, "lon": [-99.1] * 3}
    )
    assert nearest_decay(centroids, uno)["a"] == pytest.approx(
        nearest_decay(centroids, tres)["a"]
    )


def test_nearest_decay_es_el_mas_cercano_no_el_ultimo():
    # El punto lejano va PRIMERO en el frame: si la implementacion se quedara
    # con el ultimo en vez de con el maximo, este test lo cacha.
    centroids = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index(["a"], name="hex_id")
    )
    points = pd.DataFrame(
        {"lat": [19.5 + 700 / 111_000, 19.5 + 100 / 111_000], "lon": [-99.1, -99.1]}
    )
    esperado = np.exp(-100.0 / 300.0)
    assert nearest_decay(centroids, points)["a"] == pytest.approx(esperado, rel=1e-3)


def test_nearest_decay_corta_a_800_metros():
    centroids = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index(["a"], name="hex_id")
    )
    lejos = pd.DataFrame({"lat": [19.5 + 900 / 111_000], "lon": [-99.1]})
    assert nearest_decay(centroids, lejos)["a"] == 0.0


def test_nearest_decay_sin_puntos_da_ceros_alineados():
    centroids = pd.DataFrame(
        {"lat": [19.5, 19.6], "lon": [-99.1, -99.2]},
        index=pd.Index(["a", "b"], name="hex_id"),
    )
    out = nearest_decay(centroids, pd.DataFrame(columns=["lat", "lon"]))
    assert list(out.index) == ["a", "b"]
    assert (out == 0.0).all()


def test_nearest_decay_en_el_punto_exacto_vale_uno():
    centroids = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index(["a"], name="hex_id")
    )
    encima = pd.DataFrame({"lat": [19.5], "lon": [-99.1]})
    assert nearest_decay(centroids, encima)["a"] == pytest.approx(1.0)
```

Si `numpy` no está importado como `np` en `tests/test_geo.py`, agregarlo. Agregar `nearest_decay` al import de `rtgam.geo` que ya existe en ese archivo.

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest tests/test_geo.py -k nearest_decay -v`
Expected: FAIL con `ImportError: cannot import name 'nearest_decay'`

- [ ] **Step 3: Implementar**

Agregar al final de `src/rtgam/geo.py`:

```python
def nearest_decay(
    centroids: pd.DataFrame,
    points: pd.DataFrame,
    tau: float = DECAY_TAU_M,
    cutoff: float = DECAY_CUTOFF_M,
) -> pd.Series:
    """Decaimiento exp(-d/tau) del punto MAS CERCANO, no la suma de todos.

    Los puntos mas alla de `cutoff` metros dan exactamente cero.

    centroids: indexado por hex_id, columnas lat y lon.
    points:    columnas lat y lon. No lleva columna de valor: esto mide
               presencia, y la presencia no pondera.
    Devuelve:  Series de floats en [0, 1] alineada con el indice de
               `centroids`.

    Es la hermana de accumulate_decay, no un modo suyo. La suma cuenta
    puntos, y OSM parte una estacion en tantos nodos como quiera el
    mapeador: La Raza son tres nodos en el mismo anden. Con el maximo, tres
    nodos colocados dan lo mismo que uno, sin dedup y sin umbral que
    justificar. La inmunidad al conteo doble es estructural.
    """
    if len(points) == 0:
        return pd.Series(0.0, index=centroids.index)

    distances = haversine_m(
        centroids["lat"].to_numpy()[:, None],
        centroids["lon"].to_numpy()[:, None],
        points["lat"].to_numpy()[None, :],
        points["lon"].to_numpy()[None, :],
    )
    weights = np.where(distances <= cutoff, np.exp(-distances / tau), 0.0)
    return pd.Series(weights.max(axis=1), index=centroids.index)
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `uv run pytest tests/test_geo.py -v && uv run pytest`
Expected: PASS, suite completa verde.

- [ ] **Step 5: Commit**

```bash
git add src/rtgam/geo.py tests/test_geo.py
git commit -m "feat: nearest_decay, el decaimiento del punto mas cercano"
```

---

### Task 2: Clasificar estaciones por estructura de etiqueta

**Files:**
- Modify: `src/rtgam/sources/transporte.py` (`STATION_COLUMNS`, `stations_from_overpass`, función nueva `station_class`)
- Test: `tests/test_transporte_stations.py`

**Interfaces:**
- Produces: `station_class(tags: dict) -> str | None` — devuelve `"cable"`, `"riel"` o `None`
- Produces: `stations_from_overpass(payload: dict) -> pd.DataFrame` con columnas `["osm_name", "lat", "lon", "osm_class"]`. `osm_class` es `"cable"`, `"riel"` o `None`.

**Contexto:** `stations_from_overpass` hoy deduplica por `osm_name` con `keep="first"` y devuelve `["osm_name", "lat", "lon"]`. La clase NO puede salir del elemento que sobrevive al dedup: un mismo nombre puede llegar como un nodo con `railway=station` y un way con solo `public_transport=station`, y cuál queda primero depende del orden del payload de Overpass. La clase de un nombre es la más específica entre todos los elementos que comparten ese nombre. Las coordenadas siguen saliendo del primer elemento, exactamente como hoy — eso es lo que mantiene `flujo_transporte` idéntico.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_transporte_stations.py`:

```python
def test_station_class_aerialway_es_cable():
    assert station_class({"aerialway": "station"}) == "cable"


def test_station_class_railway_es_riel():
    assert station_class({"railway": "station"}) == "riel"


def test_station_class_solo_public_transport_no_clasifica():
    # Los CETRAM, los paraderos de RTP y las terminales foraneas traen solo
    # esta etiqueta. Un paradero de camion no es una estacion.
    assert station_class({"public_transport": "station"}) is None


def test_station_class_cable_gana_a_riel():
    # Ninguna estacion real de GAM trae las dos, pero la regla tiene que ser
    # determinista igual, no depender del orden en que se lean las llaves.
    tags = {"aerialway": "station", "railway": "station"}
    assert station_class(tags) == "cable"


def test_station_class_riel_gana_a_public_transport():
    tags = {"public_transport": "station", "railway": "station"}
    assert station_class(tags) == "riel"


def test_station_class_sin_etiquetas_no_clasifica():
    assert station_class({}) is None
    assert station_class({"railway": "halt"}) is None


def test_la_clase_sale_de_todos_los_elementos_del_mismo_nombre():
    # El elemento generico va PRIMERO y sobrevive al dedup. Si la clase
    # saliera del sobreviviente, esta estacion de Metro quedaria sin
    # clasificar y desapareceria de la presencia sin que fallara nada.
    payload = {
        "elements": [
            {
                "tags": {"name": "Potrero", "public_transport": "station"},
                "lat": 19.50,
                "lon": -99.13,
            },
            {
                "tags": {"name": "Potrero", "railway": "station"},
                "lat": 19.51,
                "lon": -99.14,
            },
        ]
    }
    out = stations_from_overpass(payload)
    assert len(out) == 1
    assert out.loc[0, "osm_class"] == "riel"
    # Las coordenadas siguen siendo las del primero: flujo_transporte no
    # puede moverse por este cambio.
    assert out.loc[0, "lat"] == pytest.approx(19.50)


def test_una_estacion_sin_clase_queda_con_osm_class_nulo():
    payload = {
        "elements": [
            {
                "tags": {"name": "CETRAM Indios Verdes", "public_transport": "station"},
                "lat": 19.49,
                "lon": -99.12,
            }
        ]
    }
    out = stations_from_overpass(payload)
    assert len(out) == 1
    assert out.loc[0, "osm_class"] is None
```

Agregar `station_class` al import de `rtgam.sources.transporte` en ese archivo. Verificar que `pytest` esté importado.

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest tests/test_transporte_stations.py -v`
Expected: FAIL con `ImportError: cannot import name 'station_class'`

- [ ] **Step 3: Implementar**

En `src/rtgam/sources/transporte.py`, cambiar la constante:

```python
STATION_COLUMNS = ["osm_name", "lat", "lon"]
```

por:

```python
STATION_COLUMNS = ["osm_name", "lat", "lon", "osm_class"]

# Etiqueta -> clase de estacion, en orden de precedencia: la primera que
# cruce gana. cable antes que riel para que un elemento con las dos salga
# cable siempre, sin depender del orden de las llaves del diccionario.
STATION_CLASSES = (
    ("aerialway", "cable"),
    ("railway", "riel"),
)

# Orden de especificidad para resolver la clase de un nombre que llega en
# varios elementos. Mas alto gana.
CLASS_RANK = {None: 0, "riel": 1, "cable": 2}
```

Agregar la función, justo después de `normalize_name`:

```python
def station_class(tags: dict) -> str | None:
    """Clase de una estacion segun la estructura de sus etiquetas.

    Devuelve "cable", "riel" o None.

    Se clasifica por etiqueta y no por la cadena de `network` porque el
    valor de `network` en OSM es texto libre y en GAM aparece escrito de
    media docena de maneras distintas.

    public_transport=station a solas NO clasifica: en GAM son exactamente
    los CETRAM, los paraderos de RTP y las terminales de autobus foraneo.
    Un CETRAM casi siempre esta colocado con la estacion de Metro que le da
    nombre, asi que contarlo suma presencia donde ya hay. Y un paradero de
    camion en GAM lo hay en todas partes: contarlos borraria el poder de la
    variable para distinguir.
    """
    for key, clase in STATION_CLASSES:
        if tags.get(key) == "station":
            return clase
    return None
```

Reemplazar el cuerpo de `stations_from_overpass` por:

```python
def stations_from_overpass(payload: dict) -> pd.DataFrame:
    """Convierte una respuesta de Overpass en un DataFrame de estaciones.

    Los elementos sin nombre o sin coordenadas se descartan: no se pueden
    cruzar con la afluencia ni ubicar en el mapa. Se deduplica por nombre
    porque OSM suele tener un nodo y un way para la misma estacion.

    La clase NO sale del elemento que sobrevive al dedup, sale de la mas
    especifica entre todos los que comparten el nombre. Un mismo nombre
    llega como un nodo con railway=station y un way con solo
    public_transport=station, y cual queda primero depende del orden del
    payload: sacar la clase del sobreviviente dejaria estaciones de Metro
    sin clasificar segun el humor del servidor.

    Las coordenadas si salen del primero, igual que siempre. Esa es la
    razon de que flujo_transporte no se mueva ni un decimal por este
    cambio.
    """
    rows = []
    for element in payload.get("elements", []):
        tags = element.get("tags", {})
        name = tags.get("name")
        if not name:
            continue

        if "lat" in element and "lon" in element:
            lat, lon = element["lat"], element["lon"]
        elif "center" in element:
            lat, lon = element["center"]["lat"], element["center"]["lon"]
        else:
            continue

        rows.append((name, float(lat), float(lon), station_class(tags)))

    df = pd.DataFrame(rows, columns=STATION_COLUMNS)
    if df.empty:
        return df

    mejor = (
        df.assign(_rank=df["osm_class"].map(CLASS_RANK))
        .sort_values("_rank", ascending=False)
        .drop_duplicates(subset="osm_name", keep="first")
        .set_index("osm_name")["osm_class"]
    )
    df = df.drop_duplicates(subset="osm_name", keep="first").reset_index(drop=True)
    df["osm_class"] = df["osm_name"].map(mejor)
    return df
```

Nota: `sort_values` de pandas es estable, así que entre dos elementos del mismo rango gana el que venía primero.

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `uv run pytest tests/test_transporte_stations.py -v && uv run pytest`
Expected: PASS, suite completa verde.

- [ ] **Step 5: Commit**

```bash
git add src/rtgam/sources/transporte.py tests/test_transporte_stations.py
git commit -m "feat: clasificar estaciones en cable, riel o descartada"
```

---

### Task 3: La fuente 1 emite dos columnas

**Files:**
- Modify: `src/rtgam/sources/transporte.py` (`to_hex_features`, import de `geo`)
- Modify: `scripts/02_transporte.py`
- Modify: `scripts/99_score.py:27-32`
- Test: `tests/test_transporte_afluencia.py`

**Interfaces:**
- Consumes: `nearest_decay` de `rtgam.geo` (Task 1); la columna `osm_class` de `stations_from_overpass` (Task 2)
- Produces: `to_hex_features(gam_hexes: pd.DataFrame, con_afluencia: pd.DataFrame, estaciones: pd.DataFrame) -> pd.DataFrame` con columnas `flujo_transporte` y `presencia_transporte`

**Contexto crítico sobre la firma.** Hoy es `to_hex_features(gam_hexes, stations)`, y ese `stations` es el resultado del `merge(..., how="inner")` con la afluencia del Metro: **solo las estaciones que cruzaron con el CSV**, 19 dentro de GAM. Pasarle eso a la presencia la dejaría con exactamente el mismo punto ciego que se está arreglando — el Cablebús no cruza con nada y no estaría ahí. Por eso la firma toma dos frames de estaciones: el merge para el flujo, y el crudo de `fetch_stations` para la presencia.

- [ ] **Step 1: Escribir los tests que fallan**

Los tests que ya existen en `tests/test_transporte_afluencia.py` y llaman a `to_hex_features` con dos argumentos hay que actualizarlos a la firma nueva, pasando el frame de estaciones. Además, agregar:

```python
def test_la_presencia_no_depende_de_la_afluencia():
    # Este es el test que ancla el arreglo entero. Una estacion de cable que
    # no cruza con ningun nombre del CSV del Metro —el Cablebus, exactamente—
    # tiene que producir presencia mayor que cero. Sin este test, la
    # regresion que deshace el arreglo pasa desapercibida.
    hexes = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index(["a"], name="hex_id")
    )
    con_afluencia = pd.DataFrame(columns=["lat", "lon", "afluencia_habil"])
    estaciones = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1], "osm_class": ["cable"]}
    )
    out = to_hex_features(hexes, con_afluencia, estaciones)
    assert out.loc["a", "flujo_transporte"] == 0.0
    assert out.loc["a", "presencia_transporte"] == pytest.approx(1.0)


def test_las_estaciones_sin_clase_no_dan_presencia():
    hexes = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index(["a"], name="hex_id")
    )
    con_afluencia = pd.DataFrame(columns=["lat", "lon", "afluencia_habil"])
    estaciones = pd.DataFrame(
        {
            "lat": [19.5, 19.5],
            "lon": [-99.1, -99.1],
            "osm_class": ["cable", None],
        }
    )
    # El CETRAM colocado encima no agrega nada: el maximo ya es 1.0.
    out = to_hex_features(hexes, con_afluencia, estaciones)
    assert out.loc["a", "presencia_transporte"] == pytest.approx(1.0)


def test_sin_estaciones_de_riel_ni_cable_lanza():
    hexes = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index(["a"], name="hex_id")
    )
    con_afluencia = pd.DataFrame(columns=["lat", "lon", "afluencia_habil"])
    estaciones = pd.DataFrame({"lat": [19.5], "lon": [-99.1], "osm_class": [None]})
    with pytest.raises(ValueError, match="riel ni cable"):
        to_hex_features(hexes, con_afluencia, estaciones)


def test_sin_estaciones_de_cable_lanza():
    hexes = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index(["a"], name="hex_id")
    )
    con_afluencia = pd.DataFrame(columns=["lat", "lon", "afluencia_habil"])
    estaciones = pd.DataFrame({"lat": [19.5], "lon": [-99.1], "osm_class": ["riel"]})
    with pytest.raises(ValueError, match="cable"):
        to_hex_features(hexes, con_afluencia, estaciones)


def test_el_flujo_no_cambia_al_agregar_la_presencia():
    # El mismo fixture de siempre: la columna de volumen tiene que dar el
    # mismo numero que daba antes de esta tarea.
    hexes = pd.DataFrame(
        {"lat": [19.5, 19.6], "lon": [-99.1, -99.2]},
        index=pd.Index(["a", "b"], name="hex_id"),
    )
    con_afluencia = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1], "afluencia_habil": [1000.0]}
    )
    estaciones = pd.DataFrame(
        {"lat": [19.5, 19.5], "lon": [-99.1, -99.1], "osm_class": ["riel", "cable"]}
    )
    out = to_hex_features(hexes, con_afluencia, estaciones)
    assert out.loc["a", "flujo_transporte"] == pytest.approx(1000.0, rel=1e-6)
    assert out.loc["b", "flujo_transporte"] == 0.0
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest tests/test_transporte_afluencia.py -v`
Expected: FAIL — `TypeError` por la firma, y los tests de guardas por `ValueError` no lanzado.

- [ ] **Step 3: Implementar**

En `src/rtgam/sources/transporte.py`, cambiar el import:

```python
from rtgam.geo import accumulate_decay
```

por:

```python
from rtgam.geo import accumulate_decay, nearest_decay
```

Reemplazar `to_hex_features` entero por:

```python
# Las clases que cuentan como presencia de transporte.
CLASES_CON_PRESENCIA = ("riel", "cable")


def to_hex_features(
    gam_hexes: pd.DataFrame,
    con_afluencia: pd.DataFrame,
    estaciones: pd.DataFrame,
) -> pd.DataFrame:
    """Emite las dos columnas que esta fuente posee.

    gam_hexes:     indexado por hex_id, columnas lat y lon.
    con_afluencia: el cruce con el CSV del Metro. Columnas lat, lon y
                   afluencia_habil.
    estaciones:    la salida cruda de fetch_stations. Columnas lat, lon y
                   osm_class.
    Devuelve:      DataFrame indexado por hex_id con flujo_transporte y
                   presencia_transporte, en valores CRUDOS y sin normalizar.

    Son dos frames y no uno a proposito. `con_afluencia` es un merge
    interno: solo trae las estaciones que cruzaron con el CSV, que son las
    del Metro. Medir la presencia sobre ese frame la dejaria con el mismo
    punto ciego que esta variable existe para arreglar, porque el Cablebus
    no cruza con nada.

    `estaciones` cubre el bbox completo, GAM mas 1 km. Una estacion justo
    afuera del limite alimenta hexagonos de GAM de verdad, y filtrarla
    dejaria el borde falsamente muerto.
    """
    presentes = estaciones[estaciones["osm_class"].isin(CLASES_CON_PRESENCIA)]

    # Una guarda, no una comodidad. Si OSM cambia el esquema de etiquetas,
    # la variable saldria toda en cero y el score la reportaria como
    # presente y funcionando: el numero equivocado que no lanza nada.
    if presentes.empty:
        raise ValueError(
            "Ninguna estacion clasifico como riel ni cable. O el payload de "
            "OSM viene vacio, o cambiaron las etiquetas. presencia_transporte "
            "saldria toda en cero sin que nada avisara."
        )

    if not (presentes["osm_class"] == "cable").any():
        raise ValueError(
            "No hay ninguna estacion de cable. El Cablebus Linea 1 corre "
            "entero dentro de GAM y es el motivo de esta variable: perderlo "
            "deja el punto ciego donde estaba, con apariencia de arreglado."
        )

    return pd.DataFrame(
        {
            "flujo_transporte": accumulate_decay(
                gam_hexes, con_afluencia, value_col="afluencia_habil"
            ),
            "presencia_transporte": nearest_decay(gam_hexes, presentes),
        }
    )
```

En `scripts/02_transporte.py`:

Cambiar la línea 1 del docstring y la línea 4:

```python
"""Fuente 1: afluencia y presencia de transporte sobre los hexagonos.

Entrada:  data/raw/afluencia_*.csv, data/processed/gam_hexes.parquet
Salida:   data/processed/transporte.parquet
```

Cambiar `OUTPUT`:

```python
OUTPUT = ROOT / "data" / "processed" / "transporte.parquet"
OUTPUT_VIEJO = ROOT / "data" / "processed" / "flujo_transporte.parquet"
```

Reemplazar el bloque `LIMITACION CONOCIDA DE LA FUENTE` (líneas 36-45) por:

```python
# LIMITACION CONOCIDA DE LA FUENTE
# Solo el Metro (STC) publica afluencia por estacion. Metrobus, Cablebus,
# Tren Ligero y Trolebus publican unicamente totales por linea, asi que no
# se pueden repartir sobre hexagonos sin inventar el reparto.
#
# Por eso esta fuente emite dos columnas y no una: flujo_transporte mide
# volumen y solo existe para el Metro, y presencia_transporte mide cercania
# a una estacion de riel o cable, que si existe para todos. El corredor del
# Cablebus Linea 1 tenia flujo exactamente cero en sus 74 hexagonos.
#
# Lo que sigue sin haber es cuanta gente usa el Cablebus: la presencia dice
# que la estacion esta ahi, no que este llena.
```

Reemplazar el bloque final de `main` (desde `features = to_hex_features(...)` hasta el último `print`) por:

```python
    features = to_hex_features(hexes, merged, osm_stations)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(OUTPUT)

    # El parquet cambio de nombre. Si el viejo sobrevive, 99_score.py NO lo
    # carga (ya no esta en SOURCE_FILES), pero queda un archivo obsoleto
    # pareciendo dato vigente. Se borra.
    if OUTPUT_VIEJO.exists():
        OUTPUT_VIEJO.unlink()
        print(f"Borrado el parquet viejo: {OUTPUT_VIEJO}")

    flow = features["flujo_transporte"]
    pres = features["presencia_transporte"]
    print()
    print(f"Hexagonos: {len(flow)}  con flujo > 0: {(flow > 0).sum()}")
    print(f"flujo      min {flow.min():.1f}  media {flow.mean():.1f}  max {flow.max():.1f}")
    print(f"Hexagonos con presencia > 0: {(pres > 0).sum()}")
    print(f"presencia  min {pres.min():.4f}  media {pres.mean():.4f}  max {pres.max():.4f}")

    por_clase = osm_stations["osm_class"].value_counts(dropna=False)
    print(f"Estaciones por clase: {por_clase.to_dict()}")

    solo_presencia = int(((pres > 0) & (flow == 0)).sum())
    print(f"Hexagonos que solo la presencia ve (flujo cero): {solo_presencia}")

    print("Top 5 por flujo:")
    print(flow.nlargest(5).to_string())
    print(f"Escrito: {OUTPUT}")
```

En `scripts/99_score.py`, cambiar la entrada de `SOURCE_FILES`:

```python
SOURCE_FILES = [
    "transporte.parquet",
    "denue.parquet",
    "osm.parquet",
    "censo.parquet",
]
```

y en el docstring del archivo, la línea 7-8:

```
Corre con las fuentes que existan. Con solo transporte.parquet ya produce un
mapa valido.
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `uv run pytest tests/test_transporte_afluencia.py -v && uv run pytest`
Expected: PASS, suite completa verde.

- [ ] **Step 5: Commit**

```bash
git add src/rtgam/sources/transporte.py scripts/02_transporte.py scripts/99_score.py tests/test_transporte_afluencia.py
git commit -m "feat: presencia_transporte, la variable que si ve al Cablebus"
```

---

### Task 4: Sacar las estaciones de `atractores_osm`

**Files:**
- Modify: `src/rtgam/sources/osm.py` (`build_attractor_query`, `ATTRACTOR_TAGS`, `attractors_from_overpass`, docstrings de `drop_nested` y `to_hex_features`)
- Test: `tests/test_osm_atractores.py`, `tests/test_osm_fetch.py`

**Contexto:** Las estaciones cuentan hoy dentro de `atractores_osm`: 84 de 1,300 atractores (6.5%). Dejarlo así deja dos sliders del dashboard moviendo la misma señal. Al quitarlas, el bloque de dedup por nombre de `attractors_from_overpass` —que solo aplica a `osm_kind == "station"`— queda muerto y se va con ellas. **No hace falta re-descargar:** la caché existente sigue sirviendo porque el parseo simplemente deja de reconocer esos elementos.

- [ ] **Step 1: Escribir el test que falla**

Agregar a `tests/test_osm_atractores.py`:

```python
def test_las_estaciones_ya_no_son_atractores():
    # Las estaciones viven en presencia_transporte. Contarlas tambien aqui
    # pondria dos sliders del dashboard moviendo la misma senal.
    payload = {
        "elements": [
            {
                "type": "node",
                "tags": {"name": "Potrero", "railway": "station"},
                "lat": 19.50,
                "lon": -99.13,
            },
            {
                "type": "node",
                "tags": {"name": "Cablebus Tlalpexco", "aerialway": "station"},
                "lat": 19.55,
                "lon": -99.15,
            },
            {
                "type": "node",
                "tags": {"name": "CETRAM Indios Verdes", "public_transport": "station"},
                "lat": 19.49,
                "lon": -99.12,
            },
            {
                "type": "node",
                "tags": {"name": "Parque Tepeyac", "leisure": "park"},
                "lat": 19.48,
                "lon": -99.11,
            },
        ]
    }
    out = attractors_from_overpass(payload)
    assert list(out["osm_kind"]) == ["park"]


def test_la_consulta_de_atractores_ya_no_pide_estaciones():
    query = build_attractor_query((19.4, -99.2, 19.6, -99.0))
    assert "railway" not in query
    assert "aerialway" not in query
    assert "public_transport" not in query
    assert "leisure" in query
```

Si `tests/test_osm_fetch.py` o `tests/test_osm_atractores.py` tienen tests que dependen de que las estaciones sean atractores (buscar `station` en los dos archivos), actualizarlos: el comportamiento correcto ahora es que no lo son.

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest tests/test_osm_atractores.py -v`
Expected: FAIL — `assert ['station', 'station', 'station', 'park'] == ['park']`

- [ ] **Step 3: Implementar**

En `src/rtgam/sources/osm.py`:

Reemplazar `build_attractor_query` (docstring y consulta) por:

```python
def build_attractor_query(bbox: tuple[float, float, float, float]) -> str:
    """Consulta Overpass para espacio publico.

    `nwr` y no `way`: el Bosque de San Juan de Aragon existe SOLO como relation,
    y una consulta de puros `way` lo pierde sin lanzar nada.

    `out geom` y no `out tags center`: hace falta el poligono completo, no solo
    un punto, para saber que atractores estan DENTRO de otro. Un `center` no
    contiene nada. Cuesta 1.1 MB en vez de 293 KB, que no es costo.

    El suelo de conservacion no se pide: la Sierra de Guadalupe es ladera, no
    plaza, y meterla pondria un atractor enorme sobre los hexagonos con menos
    banqueta de la alcaldia.

    Las estaciones tampoco se piden, y esto cambio: antes si. Viven en
    presencia_transporte, que las mide con el maximo del kernel en vez de la
    suma. Contarlas aqui tambien ponia dos sliders del dashboard moviendo la
    misma senal, 84 de 1,300 atractores.
    """
    south, west, north, east = bbox
    box = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:{OVERPASS_TIMEOUT_S}];
(
  nwr["leisure"~"^(park|garden|pitch|playground|sports_centre)$"]({box});
  nwr["amenity"="marketplace"]({box});
  nwr["place"="square"]({box});
);
out geom;
"""
```

Reemplazar `ATTRACTOR_TAGS`:

```python
# Etiqueta -> tipo de atractor. El orden importa: el primero que cruce gana.
# Las estaciones NO estan aqui: son presencia_transporte, no espacio publico.
ATTRACTOR_TAGS = (
    ("leisure", {"park", "garden", "pitch", "playground", "sports_centre"}),
    ("amenity", {"marketplace"}),
    ("place", {"square"}),
)
```

En `attractors_from_overpass`, quitar del docstring los tres párrafos sobre el dedup de estaciones (desde "Las estaciones se deduplican por nombre" hasta el final del docstring) y reemplazar el final de la función:

```python
    frame = drop_nested(pd.DataFrame(rows, columns=ATTRACTOR_COLUMNS), polygons)
    repetida = (
        (frame["osm_kind"] == "station")
        & (frame["name"] != "")
        & frame.duplicated(subset=["osm_kind", "name"], keep="first")
    )
    return frame[~repetida].reset_index(drop=True)
```

por:

```python
    frame = drop_nested(pd.DataFrame(rows, columns=ATTRACTOR_COLUMNS), polygons)
    return frame.reset_index(drop=True)
```

El dedup por nombre solo aplicaba a `osm_kind == "station"`. Sin estaciones queda muerto. Los demás tipos NO se deduplican a propósito: los nombres de parque, jardín y cancha en GAM son genéricos y se repiten entre sitios genuinamente distintos.

En el docstring de `drop_nested`, la frase que cita conteos de estaciones ("43 jardines dentro de su parque, **23 estaciones dentro de otra estacion**, 5 mercados dentro de otro mercado") ya no puede citar estaciones. Recontar contra los datos reales:

```bash
uv run python -c "
import json
from pathlib import Path
from collections import Counter
from rtgam.sources.osm import attractor_kind, element_polygon, ATTRACTOR_COLUMNS, drop_nested
import pandas as pd
payload = json.loads(Path('data/raw/osm_attractors.json').read_text())
rows, polys = [], []
for e in payload['elements']:
    k = attractor_kind(e.get('tags', {}))
    if k is None: continue
    p = element_polygon(e)
    if p is not None: lat, lon = p.centroid.y, p.centroid.x
    elif 'lat' in e: lat, lon = e['lat'], e['lon']
    else: continue
    rows.append((k, e.get('tags', {}).get('name',''), float(lat), float(lon))); polys.append(p)
antes = pd.DataFrame(rows, columns=ATTRACTOR_COLUMNS)
despues = drop_nested(antes, polys)
print('total', len(antes), 'sobreviven', len(despues), 'anidados', len(antes)-len(despues))
print(Counter(antes.loc[~antes.index.isin(despues.index), 'osm_kind']))
"
```

Actualizar el docstring con los números que imprima, incluyendo el total de atractores en la frase "499 de 1,776 atractores (28%)". Si el Deportivo Hermanos Galeana sigue trayendo 58 canchas, ese ejemplo se queda.

Actualizar también el docstring de `to_hex_features` en `osm.py` si menciona transporte, y el docstring del módulo (línea 1-6), que dice "Parques, plazas, deportivos, mercados publicos y paradas de transporte" — quitar las paradas.

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `uv run pytest tests/test_osm_atractores.py tests/test_osm_fetch.py -v && uv run pytest`
Expected: PASS, suite completa verde.

- [ ] **Step 5: Commit**

```bash
git add src/rtgam/sources/osm.py tests/test_osm_atractores.py tests/test_osm_fetch.py
git commit -m "fix: las estaciones salen de atractores_osm, ya viven en presencia"
```

---

### Task 5: Pesos, corrida real y documentación

**Files:**
- Modify: `config/weights.yaml`
- Modify: `README.md` (secciones "Orden de ejecución" y "Zonas donde los números NO son confiables")
- Modify: `HANDOFF.md:18` (tabla de variables) y `HANDOFF.md:122`

**Contexto:** Esta tarea corre el pipeline completo contra los datos reales y escribe en la documentación los números que salgan, no los del spec. Los del spec son las mediciones previas y sirven de referencia para detectar una desviación grande, no para copiarse.

- [ ] **Step 1: Actualizar los pesos**

En `config/weights.yaml`:

```yaml
weights:
  flujo_transporte: 0.25
  presencia_transporte: 0.10
  densidad_pob: 0.15
  nivel_socioeconomico: 0.15
  accesibilidad_peatonal: 0.10
  atractores_denue: 0.10
  atractores_osm: 0.05
  competencia: -0.10
```

Y agregar al comentario de cabecera, después del párrafo que ya existe:

```yaml
# El transporte pesa 0.35 repartido entre dos variables que responden
# preguntas distintas: flujo_transporte es cuanta gente pasa (afluencia del
# Metro, la unica publicada por estacion) y presencia_transporte es si hay
# estacion (geometria de OSM, que si cubre el Cablebus). El total del bloque
# no subio: si presencia entrara encima de un flujo intacto, diluiria en
# silencio el peso relativo de las otras cinco variables.
```

- [ ] **Step 2: Correr el pipeline completo**

```bash
uv run python scripts/02_transporte.py
uv run python scripts/04_osm.py
uv run python scripts/99_score.py
```

`04_osm.py` usa la caché, no re-descarga. Anotar de la salida: hexágonos con presencia > 0, hexágonos que solo la presencia ve, estaciones por clase, el total de atractores de OSM después de quitar las estaciones, y el score máximo.

**Comprobación obligatoria:** `flujo_transporte` no puede haberse movido. Antes de correr, guardar una copia; después, comparar:

```bash
uv run python -c "
import pandas as pd
viejo = pd.read_parquet('/tmp/flujo_antes.parquet')['flujo_transporte']
nuevo = pd.read_parquet('data/processed/transporte.parquet')['flujo_transporte']
print('identicos:', viejo.equals(nuevo.reindex(viejo.index)))
"
```

(La copia se hace con `cp data/processed/flujo_transporte.parquet /tmp/flujo_antes.parquet` ANTES del paso anterior, porque `02_transporte.py` borra el archivo viejo.) Si no son idénticos, es un defecto: parar y reportarlo.

- [ ] **Step 3: Medir el efecto en el corredor del Cablebús**

```bash
uv run python -c "
import pandas as pd
s = pd.read_parquet('data/processed/hex_scores.parquet')
f = pd.read_parquet('data/processed/hex_features.parquet')
rank = s['score'].rank(ascending=False)
corredor = f['presencia_transporte'] > 0
print('hexagonos con presencia:', int(corredor.sum()))
print('rank medio de los que tienen presencia y flujo cero:',
      rank[(f['presencia_transporte'] > 0) & (f['flujo_transporte'] == 0)].mean())
print('score max:', s['score'].max())
"
```

- [ ] **Step 4: Actualizar README.md**

En "Zonas donde los números NO son confiables", reemplazar el primer bullet por tres:

```markdown
- Solo el Metro publica afluencia por estación. Metrobús, Cablebús, Tren
  Ligero y Trolebús solo dan totales por línea. Por eso el transporte entra
  al score con dos variables: `flujo_transporte` (volumen, solo Metro) y
  `presencia_transporte` (cercanía a una estación de riel o cable, que sí
  cubre el Cablebús).
- `presencia_transporte` dice que **existe** una estación, no cuánta gente la
  usa. Un Cablebús con 5,000 pasajeros al día y uno con 50,000 puntúan igual.
- El corredor del Cablebús Línea 1 pasa del tercio bajo al medio del ranking,
  no al top. Sigue teniendo menos densidad comercial y menos NSE que el
  corredor de Insurgentes Norte, y eso es un hecho, no un artefacto.
```

Cambiar el bullet de las siete variables a **ocho**, agregando `presencia_transporte` a la lista y corrigiendo la descripción de `atractores_osm` (ya no incluye transporte):

```markdown
- De las **ocho** variables de `config/weights.yaml` hay datos de las ocho:
  `flujo_transporte`, `presencia_transporte`, `competencia`,
  `atractores_denue`, `accesibilidad_peatonal` (OSM, alcance a 800 m por la
  red), `atractores_osm` (OSM, solo espacio público), `densidad_pob` y
  `nivel_socioeconomico` (las dos últimas del censo AGEB 2020).
```

- [ ] **Step 5: Actualizar HANDOFF.md**

En la tabla de la línea 18, agregar la fila de `presencia_transporte`. En la línea 122, actualizar la nota (habla de estaciones cuya afluencia "sigue en `flujo_transporte`") para que refleje que las estaciones ya no son atractores de OSM. Leer el contexto de esas líneas antes de editarlas.

- [ ] **Step 6: Correr la suite completa**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add config/weights.yaml README.md HANDOFF.md
git commit -m "feat: el transporte pesa 0.35 repartido entre volumen y presencia"
```

---

## Self-Review

**Cobertura del spec:** `nearest_decay` → Task 1. `station_class` y `osm_class` con precedencia por nombre → Task 2. Firma de tres argumentos, dos columnas, las dos guardas, renombre del parquet, `SOURCE_FILES` → Task 3. Traslape con `atractores_osm` (query, `ATTRACTOR_TAGS`, dedup muerto, docstrings recontados) → Task 4. Pesos, mediciones reales, limitaciones en el README → Task 5.

**Consistencia de tipos:** `nearest_decay(centroids, points, tau, cutoff)` sin `value_col`, definida en Task 1 y consumida en Task 3 con dos argumentos. `station_class(tags) -> str | None` definida en Task 2, usada dentro de `stations_from_overpass` en la misma tarea. `osm_class` con valores `"cable"`, `"riel"`, `None`, producida en Task 2 y filtrada en Task 3 con `CLASES_CON_PRESENCIA = ("riel", "cable")`.

**Riesgo conocido:** los tests que ya existen en `tests/test_transporte_afluencia.py` llaman a `to_hex_features` con dos argumentos y hay que migrarlos en Task 3. Está anotado en su Step 1.
