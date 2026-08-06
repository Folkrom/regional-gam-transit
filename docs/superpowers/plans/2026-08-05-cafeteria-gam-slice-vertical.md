# Cafetería GAM — Plan de Implementación (rebanada vertical)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir el pipeline end-to-end de puntuación de ubicaciones para cafetería en Gustavo A. Madero, desde el grid H3 hasta el dashboard interactivo, alimentado por la fuente de afluencia de transporte público.

**Architecture:** Scripts numerados sobre capas de datos en disco (`raw` → `interim` → `processed`). La lógica pura vive en el paquete `rtgam` y se prueba sin red; los scripts de `scripts/` solo orquestan descarga, llamada y escritura. El dashboard lee un único Parquet ya normalizado y recalcula el score en memoria con producto punto.

**Tech Stack:** Python 3.12, uv, h3 4.x, pandas, numpy, shapely, pyarrow, requests, PyYAML, Streamlit, Folium, pytest.

## Alcance de este plan

Este plan implementa el **criterio de éxito de la fase 1** del spec: grid H3 construido, fuente de transporte ingerida y validada, score compuesto calculado, y dashboard mostrando el mapa con desglose por variable.

Las fuentes 2 a 4 del spec (DENUE, OSM, censo AGEB) **no** están en este plan y necesitan el suyo. Razón: sus esquemas de columnas no se pueden conocer sin descargar e inspeccionar los archivos reales, y escribir código de parseo contra esquemas adivinados produciría pasos falsos. El diseño de este plan las deja enchufables sin tocar nada existente — `99_score.py` ya funciona con las columnas que existan, y agregar una fuente es un archivo nuevo más una línea en el merge. Se planean después de correr la Tarea 6 y ver los datos reales.

## Global Constraints

- **Solo datos abiertos y gratuitos.** Ninguna fuente que requiera API key de pago, billing o tarjeta. Prohibido Google Places API.
- **Python 3.12.** Gestor de entorno y dependencias: `uv`.
- **h3 >= 4.0.** La API v3 (`polyfill`, `h3_to_geo_boundary`, `geo_to_h3`) no existe en v4 y no debe usarse.
- **Resolución H3 fija: 9.**
- **Kernel de decaimiento fijo:** `exp(-d/300)` para `d <= 800` metros, `0` fuera. Constantes `DECAY_TAU_M = 300.0` y `DECAY_CUTOFF_M = 800.0`.
- **Normalización fija:** `minmax(log1p(x))` por columna, una sola vez, en `99_score.py`. Las fuentes escriben valores **crudos**.
- **`hex_features.parquet` no guarda geometría.** Se regenera de `hex_id`.
- **Propiedad única de columnas:** cada módulo de `src/rtgam/sources/` es dueño exclusivo de sus columnas. Dos fuentes nunca escriben la misma columna.
- **Ninguna prueba toca la red.** Todas usan fixtures sintéticos.
- **Commits sin trailer de coautoría.** No agregar `Co-Authored-By`.
- **Idioma:** identificadores en inglés (nombres de módulo, función, variable,
  constante y prueba). **Docstrings y comentarios en español**, igual que los
  mensajes de commit y la salida de los scripts. Es deliberado: el dueño del
  proyecto es hispanohablante y está usando esto para aprender Python
  geoespacial, así que la prosa que explica un concepto nuevo (H3, kernel de
  decaimiento, log1p) vale más en su idioma. El código de todas las tareas de
  este plan sigue ese patrón.

## Desviaciones respecto al spec

Dos, ambas deliberadas:

1. **El paquete vive en `src/rtgam/`, no en `src/` plano.** El spec lista `src/geo.py`. Un directorio `src/` plano no es importable como paquete sin hackear `sys.path`; anidar un nivel permite `uv pip install -e .` e imports limpios (`from rtgam.geo import ...`). Los archivos del spec mapean 1:1, solo un nivel más abajo.
2. **`h3.geo_to_cells()` en vez de `h3.polygon_to_cells()`.** Verificado contra h3 4.5.0: `geo_to_cells` acepta cualquier objeto con `__geo_interface__` (incluidos los de shapely) y respeta la convención GeoJSON lon/lat. Nota importante: `h3.cell_to_latlng()` y `h3.cell_to_boundary()` devuelven **(lat, lon)**, orden inverso a GeoJSON.

**No se usa geopandas en este plan.** shapely alcanza para la rebanada vertical. geopandas se agrega cuando entre el censo AGEB, que sí necesita intersección de áreas.

## Estructura de archivos

| Archivo | Responsabilidad |
|---------|-----------------|
| `pyproject.toml` | dependencias, config de pytest |
| `.gitignore` | excluye `data/`, `.venv/`, cachés |
| `config/weights.yaml` | pesos ajustables del score |
| `src/rtgam/geo.py` | distancia haversine, grid H3, kernel de decaimiento |
| `src/rtgam/normalize.py` | `log1p_minmax` |
| `src/rtgam/score.py` | carga de pesos, combinación en score |
| `src/rtgam/sources/transporte.py` | estaciones desde Overpass, afluencia desde CSV, mapa de nombres |
| `scripts/01_build_grid.py` | polígono de GAM → `gam_hexes.parquet` |
| `scripts/02_transporte.py` | → columna `flujo_transporte` |
| `scripts/99_score.py` | merge + normalización + pesos → `hex_scores.parquet` |
| `app/dashboard.py` | Streamlit + Folium |
| `tests/` | una prueba por módulo de `src/` |

---

### Task 1: Andamiaje del proyecto

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/rtgam/__init__.py`, `src/rtgam/sources/__init__.py`
- Test: `tests/test_env.py`

**Interfaces:**
- Consumes: nada
- Produces: paquete importable `rtgam`; entorno `.venv` con todas las dependencias

- [ ] **Step 1: Escribir la prueba que falla**

`tests/test_env.py`:

```python
import h3


def test_h3_is_v4():
    """La API v4 es un requisito duro: v3 usaba polyfill/geo_to_h3."""
    assert int(h3.__version__.split(".")[0]) >= 4
    assert hasattr(h3, "geo_to_cells")


def test_package_importable():
    import rtgam

    assert rtgam.__name__ == "rtgam"
```

- [ ] **Step 2: Correr la prueba y verificar que falla**

```bash
uv run pytest tests/test_env.py -v
```

Esperado: FAIL — no existe `pyproject.toml`, `uv run` no puede resolver el proyecto.

- [ ] **Step 3: Crear `pyproject.toml`**

```toml
[project]
name = "rtgam"
version = "0.1.0"
description = "Analisis de flujo peatonal para ubicacion de cafeteria en Gustavo A. Madero"
requires-python = ">=3.12"
dependencies = [
    "h3>=4.0",
    "pandas>=2.2",
    "numpy>=1.26",
    "shapely>=2.0",
    "pyarrow>=16.0",
    "requests>=2.32",
    "PyYAML>=6.0",
    "streamlit>=1.40",
    "folium>=0.17",
    "streamlit-folium>=0.23",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/rtgam"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 4: Crear `.gitignore`**

El archivo ya existe con la entrada `.superpowers/`; **conservarla** al escribir el resto:

```gitignore
.venv/
__pycache__/
*.pyc
.pytest_cache/
data/*
!data/.gitkeep
.streamlit/
.superpowers/
```

`data/*` y no `data/`: con la barra final git excluye el directorio y deja de
recursar dentro, asi que la negacion `!data/.gitkeep` nunca se evalua y el
archivo solo entra con `git add -f`. Con el glob la negacion si funciona.

El contenido de `data/` se ignora entero: son descargas y derivados,
reproducibles desde los scripts.
`.superpowers/` es scratch del proceso de ejecución, no del proyecto.

- [ ] **Step 5: Crear los archivos del paquete y las carpetas de datos**

```bash
mkdir -p src/rtgam/sources scripts app tests config
mkdir -p data/raw data/interim data/processed
touch src/rtgam/__init__.py src/rtgam/sources/__init__.py
touch data/.gitkeep
```

- [ ] **Step 6: Crear el entorno e instalar**

```bash
uv sync --extra dev
```

- [ ] **Step 7: Correr las pruebas y verificar que pasan**

```bash
uv run pytest tests/test_env.py -v
```

Esperado: PASS, 2 pruebas.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock .gitignore src tests data/.gitkeep
git commit -m "chore: andamiaje del proyecto con uv y pytest"
```

---

### Task 2: Grid H3 y distancia haversine

**Files:**
- Create: `src/rtgam/geo.py`
- Test: `tests/test_geo.py`

**Interfaces:**
- Consumes: nada
- Produces:
  - `haversine_m(lat1, lon1, lat2, lon2) -> np.ndarray | float` — distancia en metros, compatible con broadcasting de numpy
  - `hexes_for_polygon(polygon, resolution: int = 9) -> set[str]`
  - `hex_centroids(hexes: Iterable[str]) -> pd.DataFrame` — indexado por `hex_id`, columnas `lat` y `lon`, ordenado alfabéticamente por `hex_id`

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/test_geo.py`:

```python
import numpy as np
import pytest
from shapely.geometry import Polygon

from rtgam.geo import haversine_m, hex_centroids, hexes_for_polygon


def test_haversine_zero_distance():
    assert haversine_m(19.5, -99.1, 19.5, -99.1) == pytest.approx(0.0, abs=1e-6)


def test_haversine_known_distance():
    """Un grado de latitud son ~111.2 km en cualquier meridiano."""
    d = haversine_m(19.0, -99.1, 20.0, -99.1)
    assert d == pytest.approx(111_195, rel=0.001)


def test_haversine_applies_latitude_cosine():
    """Un grado de longitud se encoge con el coseno de la latitud.

    Sin esta prueba, una haversine a la que le falte el termino
    cos(lat1)*cos(lat2) pasa todas las demas: las otras comparan puntos con
    la misma longitud, donde ese termino se multiplica por sin(0) y desaparece.
    A lat 19.5 la diferencia es 104,817 m contra 111,195 m — 6%.
    """
    d = haversine_m(19.5, -99.5, 19.5, -98.5)
    assert d == pytest.approx(104_817, rel=0.001)


def test_haversine_broadcasts():
    """La matriz hexagonos x puntos depende de este broadcasting."""
    lats = np.array([[19.5], [19.6]])
    lons = np.array([[-99.1], [-99.1]])
    plats = np.array([[19.5, 19.6]])
    plons = np.array([[-99.1, -99.1]])
    d = haversine_m(lats, lons, plats, plons)
    assert d.shape == (2, 2)
    assert d[0, 0] == pytest.approx(0.0, abs=1e-6)
    assert d[1, 1] == pytest.approx(0.0, abs=1e-6)


def test_hexes_for_polygon_returns_res9_cells():
    poly = Polygon(
        [(-99.15, 19.50), (-99.10, 19.50), (-99.10, 19.55), (-99.15, 19.55)]
    )
    cells = hexes_for_polygon(poly, resolution=9)
    assert len(cells) > 100
    assert all(isinstance(c, str) for c in cells)


def test_hex_centroids_indexed_and_sorted():
    poly = Polygon(
        [(-99.15, 19.50), (-99.14, 19.50), (-99.14, 19.51), (-99.15, 19.51)]
    )
    cells = hexes_for_polygon(poly, resolution=9)
    df = hex_centroids(cells)
    assert df.index.name == "hex_id"
    assert list(df.columns) == ["lat", "lon"]
    assert len(df) == len(cells)
    assert list(df.index) == sorted(cells)
    # Los centroides caen dentro del area de interes.
    assert df["lat"].between(19.49, 19.52).all()
    assert df["lon"].between(-99.16, -99.13).all()
```

- [ ] **Step 2: Correr las pruebas y verificar que fallan**

```bash
uv run pytest tests/test_geo.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'rtgam.geo'`.

- [ ] **Step 3: Implementar `src/rtgam/geo.py`**

```python
"""Primitivas geoespaciales: distancia, grid H3 y kernel de decaimiento."""

from collections.abc import Iterable

import h3
import numpy as np
import pandas as pd

EARTH_RADIUS_M = 6_371_008.8
H3_RESOLUTION = 9


def haversine_m(lat1, lon1, lat2, lon2):
    """Distancia de circulo maximo en metros.

    Acepta escalares o arrays de numpy y respeta broadcasting, lo que permite
    construir una matriz (n_hexagonos, n_puntos) en una sola llamada.

    Se usa haversine en vez de reproyectar a UTM porque a distancias menores a
    un kilometro el error es despreciable y evita depender de pyproj.
    """
    lat1, lon1, lat2, lon2 = (np.radians(x) for x in (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def hexes_for_polygon(polygon, resolution: int = H3_RESOLUTION) -> set[str]:
    """Celdas H3 cuyo centro cae dentro del poligono.

    `polygon` es cualquier objeto con __geo_interface__ (shapely sirve).
    h3.geo_to_cells respeta la convencion GeoJSON de lon/lat.

    El set() no es decorativo: h3 4.5.0 devuelve una list, y el contrato de
    esta funcion es un set porque quien la consume espera unicidad garantizada
    y operadores de conjunto.
    """
    return set(h3.geo_to_cells(polygon, resolution))


def hex_centroids(hexes: Iterable[str]) -> pd.DataFrame:
    """DataFrame indexado por hex_id con el centroide de cada celda.

    Ordenado por hex_id para que la salida sea deterministica entre corridas.
    Ojo: h3.cell_to_latlng devuelve (lat, lon), no (lon, lat).
    """
    rows = [(h, *h3.cell_to_latlng(h)) for h in sorted(hexes)]
    return pd.DataFrame(rows, columns=["hex_id", "lat", "lon"]).set_index("hex_id")
```

- [ ] **Step 4: Correr las pruebas y verificar que pasan**

```bash
uv run pytest tests/test_geo.py -v
```

Esperado: PASS, 6 pruebas.

- [ ] **Step 5: Commit**

```bash
git add src/rtgam/geo.py tests/test_geo.py
git commit -m "feat: grid H3 y distancia haversine"
```

---

### Task 3: Kernel de decaimiento exponencial

**Files:**
- Modify: `src/rtgam/geo.py` (agregar al final)
- Modify: `tests/test_geo.py` (agregar al final)

**Interfaces:**
- Consumes: `haversine_m` y `hex_centroids` de la Tarea 2
- Produces:
  - Constantes `DECAY_TAU_M = 300.0`, `DECAY_CUTOFF_M = 800.0`
  - `accumulate_decay(centroids: pd.DataFrame, points: pd.DataFrame, value_col: str, tau: float = DECAY_TAU_M, cutoff: float = DECAY_CUTOFF_M) -> pd.Series` — Series de floats indexada igual que `centroids`

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar a `tests/test_geo.py`. Los imports van **fusionados en el bloque de
arriba del archivo**, no repetidos a media altura: `import pandas as pd` se
suma a los imports existentes, y `DECAY_CUTOFF_M, DECAY_TAU_M,
accumulate_decay` se agregan al `from rtgam.geo import ...` que ya está.

```python
# --- va en el bloque de imports de arriba, no aqui ---
# import pandas as pd
# from rtgam.geo import (
#     DECAY_CUTOFF_M, DECAY_TAU_M, accumulate_decay,
#     haversine_m, hex_centroids, hexes_for_polygon,
# )


def _centroid_at(lat, lon, hex_id="h1"):
    return pd.DataFrame({"lat": [lat], "lon": [lon]}, index=pd.Index([hex_id], name="hex_id"))


def test_decay_at_zero_distance_is_full_value():
    centroids = _centroid_at(19.5, -99.1)
    points = pd.DataFrame({"lat": [19.5], "lon": [-99.1], "afluencia": [1000.0]})
    out = accumulate_decay(centroids, points, "afluencia")
    assert out["h1"] == pytest.approx(1000.0, rel=1e-6)


def test_decay_matches_formula_at_400m():
    """400 m al norte: peso esperado exp(-400/300) = 0.2636."""
    centroids = _centroid_at(19.5, -99.1)
    lat_400m_north = 19.5 + 400.0 / 111_195.0
    points = pd.DataFrame({"lat": [lat_400m_north], "lon": [-99.1], "afluencia": [1000.0]})
    out = accumulate_decay(centroids, points, "afluencia")
    assert out["h1"] == pytest.approx(1000.0 * np.exp(-400.0 / DECAY_TAU_M), rel=0.01)


def test_beyond_cutoff_is_exactly_zero():
    centroids = _centroid_at(19.5, -99.1)
    lat_1500m_north = 19.5 + 1500.0 / 111_195.0
    points = pd.DataFrame({"lat": [lat_1500m_north], "lon": [-99.1], "afluencia": [1000.0]})
    out = accumulate_decay(centroids, points, "afluencia")
    assert out["h1"] == 0.0


def test_accumulates_multiple_points():
    """Dos estaciones identicas y coincidentes suman el doble."""
    centroids = _centroid_at(19.5, -99.1)
    points = pd.DataFrame(
        {"lat": [19.5, 19.5], "lon": [-99.1, -99.1], "afluencia": [1000.0, 500.0]}
    )
    out = accumulate_decay(centroids, points, "afluencia")
    assert out["h1"] == pytest.approx(1500.0, rel=1e-6)


def test_empty_points_returns_zeros_not_error():
    centroids = _centroid_at(19.5, -99.1)
    points = pd.DataFrame({"lat": [], "lon": [], "afluencia": []})
    out = accumulate_decay(centroids, points, "afluencia")
    assert list(out) == [0.0]
    assert out.index.tolist() == ["h1"]


def test_output_aligned_with_centroid_index():
    centroids = pd.DataFrame(
        {"lat": [19.50, 19.60], "lon": [-99.1, -99.1]},
        index=pd.Index(["a", "b"], name="hex_id"),
    )
    points = pd.DataFrame({"lat": [19.50], "lon": [-99.1], "afluencia": [1000.0]})
    out = accumulate_decay(centroids, points, "afluencia")
    assert out.index.tolist() == ["a", "b"]
    assert out["a"] > 0.0
    assert out["b"] == 0.0  # ~11 km, muy por fuera del corte


def test_cutoff_constant_is_800():
    assert DECAY_CUTOFF_M == 800.0
    assert DECAY_TAU_M == 300.0
```

- [ ] **Step 2: Correr las pruebas y verificar que fallan**

```bash
uv run pytest tests/test_geo.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'accumulate_decay'`.

- [ ] **Step 3: Implementar el kernel**

Agregar al final de `src/rtgam/geo.py`:

```python
DECAY_TAU_M = 300.0
DECAY_CUTOFF_M = 800.0


def accumulate_decay(
    centroids: pd.DataFrame,
    points: pd.DataFrame,
    value_col: str,
    tau: float = DECAY_TAU_M,
    cutoff: float = DECAY_CUTOFF_M,
) -> pd.Series:
    """Suma de los valores de `points` ponderados por exp(-d/tau).

    Los puntos mas alla de `cutoff` metros aportan exactamente cero.

    centroids: indexado por hex_id, columnas lat y lon.
    points:    columnas lat, lon y `value_col`.
    Devuelve:  Series de floats alineada con el indice de `centroids`.

    Construye la matriz completa (n_hexagonos, n_puntos). Para GAM son ~900
    hexagonos por unos miles de puntos como mucho, asi que cabe de sobra en
    memoria y evita cualquier bucle en Python.
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
    totals = weights @ points[value_col].to_numpy(dtype=float)
    return pd.Series(totals, index=centroids.index)
```

- [ ] **Step 4: Correr las pruebas y verificar que pasan**

```bash
uv run pytest tests/test_geo.py -v
```

Esperado: PASS, 13 pruebas (las 6 de la Tarea 2 más 7 nuevas).

- [ ] **Step 5: Commit**

```bash
git add src/rtgam/geo.py tests/test_geo.py
git commit -m "feat: kernel de decaimiento exponencial con corte a 800m"
```

---

### Task 4: Normalización log1p + min-max

**Files:**
- Create: `src/rtgam/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Consumes: nada
- Produces: `log1p_minmax(s: pd.Series) -> pd.Series` — floats en `[0, 1]`, mismo índice que la entrada

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/test_normalize.py`:

```python
import numpy as np
import pandas as pd
import pytest

from rtgam.normalize import log1p_minmax


def test_scales_to_zero_one():
    s = pd.Series([0.0, 10.0, 100.0, 1000.0])
    out = log1p_minmax(s)
    assert out.min() == pytest.approx(0.0)
    assert out.max() == pytest.approx(1.0)


def test_preserves_order():
    s = pd.Series([5.0, 1.0, 100.0, 20.0])
    out = log1p_minmax(s)
    assert out.rank().tolist() == s.rank().tolist()


def test_tames_long_tail():
    """El motivo de existir de log1p: el valor extremo no aplasta al resto.

    Con min-max crudo, 31000 sobre un maximo de 120000 daria 0.26. Con log1p
    queda por arriba de 0.85, que refleja mejor que ambas son estaciones grandes.
    """
    s = pd.Series([120_000.0, 31_000.0, 12_000.0, 6_500.0, 0.0])
    out = log1p_minmax(s)
    assert out.iloc[0] == pytest.approx(1.0)
    assert out.iloc[1] > 0.85


def test_all_zeros_returns_zeros_not_nan():
    s = pd.Series([0.0, 0.0, 0.0])
    out = log1p_minmax(s)
    assert out.tolist() == [0.0, 0.0, 0.0]
    assert not out.isna().any()


def test_single_unique_value_returns_zeros_not_nan():
    """max == min haria dividir entre cero."""
    s = pd.Series([42.0, 42.0, 42.0])
    out = log1p_minmax(s)
    assert out.tolist() == [0.0, 0.0, 0.0]
    assert not out.isna().any()


def test_negatives_are_clipped_to_zero():
    """log1p de un valor menor que -1 es NaN; ninguna variable del score
    puede ser negativa, asi que un negativo es dato sucio y se recorta."""
    s = pd.Series([-5.0, 0.0, 10.0])
    out = log1p_minmax(s)
    assert not out.isna().any()
    assert out.iloc[0] == pytest.approx(0.0)


def test_preserves_index():
    s = pd.Series([1.0, 2.0], index=pd.Index(["a", "b"], name="hex_id"))
    out = log1p_minmax(s)
    assert out.index.tolist() == ["a", "b"]
    assert out.index.name == "hex_id"


def test_empty_series_returns_empty():
    out = log1p_minmax(pd.Series([], dtype=float))
    assert len(out) == 0
```

- [ ] **Step 2: Correr las pruebas y verificar que fallan**

```bash
uv run pytest tests/test_normalize.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'rtgam.normalize'`.

- [ ] **Step 3: Implementar `src/rtgam/normalize.py`**

```python
"""Normalizacion de variables antes de combinarlas en el score."""

import numpy as np
import pandas as pd


def log1p_minmax(s: pd.Series) -> pd.Series:
    """Aplica log(1+x) y escala el resultado al rango [0, 1].

    log1p doma la cola larga de la afluencia, donde una estacion como Indios
    Verdes aplastaria a todas las demas bajo un min-max crudo. El min-max
    posterior deja todas las variables en la misma escala, lo que hace que los
    pesos del score sean comparables entre si.

    Casos borde: si la serie es constante (incluida la de puros ceros) devuelve
    ceros en vez de NaN, porque max - min seria cero. Los valores negativos se
    recortan a cero: ninguna variable del score puede ser negativa, asi que un
    negativo es dato sucio, y log1p por debajo de -1 produce NaN.
    """
    if len(s) == 0:
        return s.astype(float)

    values = np.log1p(s.astype(float).clip(lower=0.0))
    low, high = values.min(), values.max()
    if not np.isfinite(low) or not np.isfinite(high) or high == low:
        return pd.Series(0.0, index=s.index)
    return (values - low) / (high - low)
```

- [ ] **Step 4: Correr las pruebas y verificar que pasan**

```bash
uv run pytest tests/test_normalize.py -v
```

Esperado: PASS, 12 pruebas.

- [ ] **Step 5: Commit**

```bash
git add src/rtgam/normalize.py tests/test_normalize.py
git commit -m "feat: normalizacion log1p + minmax con casos borde"
```

---

### Task 5: Score compuesto y pesos configurables

**Files:**
- Create: `src/rtgam/score.py`, `config/weights.yaml`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: `log1p_minmax` de la Tarea 4
- Produces:
  - `DEFAULT_WEIGHTS_PATH: Path` — apunta a `config/weights.yaml`
  - `load_weights(path: str | Path = DEFAULT_WEIGHTS_PATH) -> dict[str, float]`
  - `compute_score(features: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame` — devuelve una columna `<var>_norm` por cada peso presente en `features`, más la columna `score`

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/test_score.py`:

```python
import pandas as pd
import pytest

from rtgam.score import compute_score, load_weights


@pytest.fixture
def features():
    return pd.DataFrame(
        {
            "flujo_transporte": [0.0, 100.0, 1000.0],
            "competencia": [0.0, 0.0, 50.0],
        },
        index=pd.Index(["a", "b", "c"], name="hex_id"),
    )


def test_produces_norm_columns_and_score(features):
    out = compute_score(features, {"flujo_transporte": 1.0, "competencia": -1.0})
    assert "flujo_transporte_norm" in out.columns
    assert "competencia_norm" in out.columns
    assert "score" in out.columns
    assert out.index.tolist() == ["a", "b", "c"]


def test_competition_subtracts(features):
    """Con el mismo flujo, mas competencia debe bajar el score."""
    rival = features.copy()
    rival.loc["c", "flujo_transporte"] = 100.0  # empata con 'b'
    out = compute_score(rival, {"flujo_transporte": 1.0, "competencia": -1.0})
    assert out.loc["c", "score"] < out.loc["b", "score"]


def test_missing_columns_are_skipped_not_errors(features):
    """99_score.py corre con las fuentes que existan; las que faltan se ignoran."""
    weights = {"flujo_transporte": 1.0, "densidad_pob": 0.5, "competencia": -1.0}
    out = compute_score(features, weights)
    assert "densidad_pob_norm" not in out.columns
    assert "score" in out.columns
    assert not out["score"].isna().any()


def test_empty_hex_does_not_win(features):
    out = compute_score(features, {"flujo_transporte": 1.0, "competencia": -1.0})
    assert out["score"].idxmax() != "a"


def test_weight_of_zero_removes_influence(features):
    out = compute_score(features, {"flujo_transporte": 0.0, "competencia": -1.0})
    assert out.loc["a", "score"] == pytest.approx(out.loc["b", "score"])


def test_load_weights_reads_config_file():
    weights = load_weights()
    assert weights["flujo_transporte"] == 0.35
    assert weights["competencia"] == -0.10
    assert weights["competencia"] < 0, "la competencia debe restar"


def test_load_weights_covers_every_spec_variable():
    weights = load_weights()
    expected = {
        "flujo_transporte",
        "densidad_pob",
        "nivel_socioeconomico",
        "accesibilidad_peatonal",
        "atractores_denue",
        "atractores_osm",
        "competencia",
    }
    assert set(weights) == expected
```

- [ ] **Step 2: Correr las pruebas y verificar que fallan**

```bash
uv run pytest tests/test_score.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'rtgam.score'`.

- [ ] **Step 3: Crear `config/weights.yaml`**

```yaml
# Pesos del score compuesto, calibrados a mano para el perfil "cafeteria".
# El flujo de transporte pesa mas porque el caso de uso es cafe de camino
# al trabajo.
#
# No tienen que sumar 1: como todas las variables ya estan normalizadas a
# 0-1, lo que importa es la proporcion relativa entre pesos. El score final
# no esta acotado y no hace falta que lo este, solo se usa para ordenar.
weights:
  flujo_transporte: 0.35
  densidad_pob: 0.15
  nivel_socioeconomico: 0.15
  accesibilidad_peatonal: 0.10
  atractores_denue: 0.10
  atractores_osm: 0.05
  competencia: -0.10
```

- [ ] **Step 4: Implementar `src/rtgam/score.py`**

```python
"""Combinacion de variables normalizadas en el score compuesto."""

from pathlib import Path

import pandas as pd
import yaml

from rtgam.normalize import log1p_minmax

DEFAULT_WEIGHTS_PATH = Path(__file__).resolve().parents[2] / "config" / "weights.yaml"


def load_weights(path: str | Path = DEFAULT_WEIGHTS_PATH) -> dict[str, float]:
    """Lee los pesos del YAML de configuracion."""
    with open(path, encoding="utf-8") as fh:
        return {k: float(v) for k, v in yaml.safe_load(fh)["weights"].items()}


def compute_score(features: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    """Normaliza cada variable y las combina en un score ponderado.

    Devuelve un DataFrame con una columna `<variable>_norm` por cada peso cuya
    variable exista en `features`, mas la columna `score`.

    Las variables ausentes se saltan en silencio a proposito: el pipeline se
    construye fuente por fuente, y `99_score.py` debe producir un mapa valido
    con las columnas que ya existan, aunque falten las demas.

    El signo vive en el peso, no aqui: `competencia` lleva peso negativo en
    config/weights.yaml y por eso resta.
    """
    out = pd.DataFrame(index=features.index)
    score = pd.Series(0.0, index=features.index)

    for column, weight in weights.items():
        if column not in features.columns:
            continue
        normalized = log1p_minmax(features[column])
        out[f"{column}_norm"] = normalized
        score = score + weight * normalized

    out["score"] = score
    return out
```

- [ ] **Step 5: Correr las pruebas y verificar que pasan**

```bash
uv run pytest tests/test_score.py -v
```

Esperado: PASS, 7 pruebas.

- [ ] **Step 6: Correr toda la suite**

```bash
uv run pytest -v
```

Esperado: PASS, 30 pruebas (2 de entorno + 13 de geo + 8 de normalize + 7 de score).

- [ ] **Step 7: Commit**

```bash
git add src/rtgam/score.py config/weights.yaml tests/test_score.py
git commit -m "feat: score compuesto con pesos configurables"
```

---

### Task 6: Construcción del grid de GAM

**Files:**
- Create: `src/rtgam/boundary.py`, `scripts/01_build_grid.py`
- Test: `tests/test_boundary.py`

**Interfaces:**
- Consumes: `hexes_for_polygon`, `hex_centroids` de la Tarea 2
- Produces:
  - `GAM_NOMINATIM_QUERY: str`
  - `polygon_from_nominatim_geojson(payload: dict) -> shapely.geometry.base.BaseGeometry` — parsea la respuesta ya descargada; sin red, por eso es testeable
  - `fetch_gam_polygon(cache_path: Path, force: bool = False) -> BaseGeometry` — descarga con caché
  - `data/processed/gam_hexes.parquet` — columnas `hex_id` (índice), `lat`, `lon`

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/test_boundary.py`:

```python
import json

import pytest
from shapely.geometry import MultiPolygon, Polygon

from rtgam.boundary import polygon_from_nominatim_geojson


def _feature(geometry):
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": geometry}]}


def test_parses_polygon():
    payload = _feature(
        {
            "type": "Polygon",
            "coordinates": [[[-99.15, 19.50], [-99.10, 19.50], [-99.10, 19.55], [-99.15, 19.55], [-99.15, 19.50]]],
        }
    )
    poly = polygon_from_nominatim_geojson(payload)
    assert isinstance(poly, Polygon)
    assert poly.bounds == (-99.15, 19.50, -99.10, 19.55)


def test_parses_multipolygon():
    payload = _feature(
        {
            "type": "MultiPolygon",
            "coordinates": [
                [[[-99.15, 19.50], [-99.14, 19.50], [-99.14, 19.51], [-99.15, 19.50]]],
                [[[-99.12, 19.52], [-99.11, 19.52], [-99.11, 19.53], [-99.12, 19.52]]],
            ],
        }
    )
    poly = polygon_from_nominatim_geojson(payload)
    assert isinstance(poly, MultiPolygon)
    assert len(poly.geoms) == 2


def test_empty_response_raises_clear_error():
    with pytest.raises(ValueError, match="sin resultados"):
        polygon_from_nominatim_geojson({"type": "FeatureCollection", "features": []})


def test_point_geometry_raises_clear_error():
    """Nominatim devuelve un punto si no encontro poligono; eso es un fallo,
    no un area de estudio."""
    payload = _feature({"type": "Point", "coordinates": [-99.1, 19.5]})
    with pytest.raises(ValueError, match="no es un poligono"):
        polygon_from_nominatim_geojson(payload)
```

- [ ] **Step 2: Correr las pruebas y verificar que fallan**

```bash
uv run pytest tests/test_boundary.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'rtgam.boundary'`.

- [ ] **Step 3: Implementar `src/rtgam/boundary.py`**

```python
"""Obtencion del poligono de la alcaldia Gustavo A. Madero.

Se usa Nominatim de OpenStreetMap en vez del portal de datos de la CDMX porque
devuelve el poligono listo en GeoJSON con una sola peticion, sin API key y sin
depender de una URL de descarga que cambia entre versiones del portal.
"""

import json
from pathlib import Path

import requests
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
GAM_NOMINATIM_QUERY = "Gustavo A. Madero, Ciudad de Mexico, Mexico"

# Nominatim rechaza peticiones sin User-Agent identificable. Es su politica
# de uso, no un detalle opcional.
USER_AGENT = "regional-transit-gam/0.1 (analisis academico de ubicacion)"


def polygon_from_nominatim_geojson(payload: dict) -> BaseGeometry:
    """Extrae el poligono de la primera feature de una respuesta de Nominatim."""
    features = payload.get("features", [])
    if not features:
        raise ValueError("Nominatim devolvio sin resultados para la consulta")

    geometry = features[0]["geometry"]
    if geometry["type"] not in ("Polygon", "MultiPolygon"):
        raise ValueError(
            f"Nominatim devolvio {geometry['type']}, que no es un poligono. "
            "Revisa la consulta o descarga el limite a mano."
        )
    return shape(geometry)


def fetch_gam_polygon(cache_path: Path, force: bool = False) -> BaseGeometry:
    """Descarga el poligono de GAM, con cache en disco.

    Si `cache_path` existe y `force` es falso, no toca la red.

    El orden importa: se valida ANTES de escribir la cache. Al reves, una
    respuesta 200 con geometria inservible quedaria persistida y envenenaria
    todas las corridas siguientes, que releerian el mismo payload malo y
    fallarian igual sin explicar por que.
    """
    if cache_path.exists() and not force:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"La cache {cache_path} esta corrupta o truncada. "
                f"Borrala o corre con --force para volver a descargar. ({error})"
            ) from error
        return polygon_from_nominatim_geojson(payload)

    response = requests.get(
        NOMINATIM_URL,
        params={
            "q": GAM_NOMINATIM_QUERY,
            "format": "geojson",
            "polygon_geojson": 1,
            "limit": 1,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()

    polygon = polygon_from_nominatim_geojson(payload)

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload), encoding="utf-8")
    return polygon
```

- [ ] **Step 4: Correr las pruebas y verificar que pasan**

```bash
uv run pytest tests/test_boundary.py -v
```

Esperado: PASS, 4 pruebas.

- [ ] **Step 5: Escribir `scripts/01_build_grid.py`**

```python
"""Construye el grid H3 de la alcaldia Gustavo A. Madero.

Salida: data/processed/gam_hexes.parquet (hex_id, lat, lon)

Uso:
    uv run python scripts/01_build_grid.py [--force]
"""

import argparse
import math
from pathlib import Path

from rtgam.boundary import fetch_gam_polygon
from rtgam.geo import H3_RESOLUTION, hex_centroids, hexes_for_polygon

ROOT = Path(__file__).resolve().parents[1]
RAW_BOUNDARY = ROOT / "data" / "raw" / "gam_boundary.geojson"
OUTPUT = ROOT / "data" / "processed" / "gam_hexes.parquet"

# Area media de una celda H3 resolucion 9, en km2.
H3_RES9_CELL_KM2 = 0.105


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-descargar aunque exista cache")
    args = parser.parse_args()

    polygon = fetch_gam_polygon(RAW_BOUNDARY, force=args.force)
    hexes = hexes_for_polygon(polygon, resolution=H3_RESOLUTION)
    centroids = hex_centroids(hexes)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    centroids.to_parquet(OUTPUT)

    minx, miny, maxx, maxy = polygon.bounds
    # Un grado de latitud son ~111 km, pero uno de longitud se encoge con el
    # coseno de la latitud: a 19.5 grados vale ~104.6 km, no 111.
    lat_mid = math.radians((miny + maxy) / 2)
    area_km2 = polygon.area * 111.0 * (111.0 * math.cos(lat_mid))
    print(f"Poligono GAM: {polygon.geom_type}, area aprox {area_km2:.1f} km2")
    print(f"Bounding box: lon [{minx:.4f}, {maxx:.4f}]  lat [{miny:.4f}, {maxy:.4f}]")
    # h3.geo_to_cells usa contencion por centro: una celda del borde cuyo
    # centro cae fuera del poligono se descarta. Por eso los hexagonos cubren
    # menos area que el poligono, y conviene imprimir ambas cifras.
    covered_km2 = len(centroids) * H3_RES9_CELL_KM2
    print(f"Hexagonos H3 res {H3_RESOLUTION}: {len(centroids)}")
    print(f"Area cubierta por hexagonos: {covered_km2:.1f} km2 "
          f"({covered_km2 / area_km2 * 100:.0f}% del poligono; el resto son "
          f"celdas del borde descartadas por contencion por centro)")
    print(f"Escrito: {OUTPUT}")
```

Agregar al final:

```python
if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Correr el script y validar la salida**

```bash
uv run python scripts/01_build_grid.py
```

Esperado: entre 700 y 1200 hexágonos. El spec estima ~900 para 95 km²; una prueba con un polígono de 29 km² dio 239 celdas, que extrapola a ~780. Un conteo fuera de ese rango significa que Nominatim devolvió el área equivocada — verificar el bounding box impreso: GAM debe caer aproximadamente en lon `[-99.19, -99.05]`, lat `[19.46, 19.59]`.

Si Nominatim devuelve un punto o el área equivocada, la salida alterna es descargar a mano el límite de las alcaldías desde `datos.cdmx.gob.mx`, guardarlo como `data/raw/gam_boundary.geojson` con la misma forma de `FeatureCollection`, y volver a correr el script — la caché lo tomará sin tocar la red.

- [ ] **Step 7: Commit**

```bash
git add src/rtgam/boundary.py scripts/01_build_grid.py tests/test_boundary.py
git commit -m "feat: grid H3 de GAM desde el limite de OpenStreetMap"
```

---

### Task 7: Coordenadas de estaciones desde Overpass

**Files:**
- Create: `src/rtgam/sources/transporte.py`
- Test: `tests/test_transporte_stations.py`

**Interfaces:**
- Consumes: nada de tareas previas
- Produces:
  - `normalize_name(name: str) -> str` — minúsculas, sin acentos, sin puntuación, espacios colapsados
  - `stations_from_overpass(payload: dict) -> pd.DataFrame` — columnas `osm_name`, `lat`, `lon`; sin red
  - `fetch_stations(bbox: tuple[float, float, float, float], cache_path: Path, force: bool = False) -> pd.DataFrame` — con caché y reintentos

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/test_transporte_stations.py`:

```python
import json
import time

import pytest
import requests

from rtgam.sources.transporte import (
    fetch_stations,
    normalize_name,
    stations_from_overpass,
)


def test_normalize_strips_accents_and_case():
    assert normalize_name("Instituto del Petróleo") == "instituto del petroleo"


def test_normalize_strips_punctuation_and_collapses_spaces():
    assert normalize_name("La Villa-Basílica") == "la villa basilica"
    assert normalize_name("  Martín   Carrera ") == "martin carrera"


def test_parses_nodes_with_lat_lon():
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 19.50, "lon": -99.10, "tags": {"name": "Potrero"}},
        ]
    }
    df = stations_from_overpass(payload)
    assert list(df.columns) == ["osm_name", "lat", "lon"]
    assert df.iloc[0]["osm_name"] == "Potrero"
    assert df.iloc[0]["lat"] == 19.50


def test_parses_ways_using_center():
    """Overpass devuelve `center` en vez de lat/lon para ways y relations."""
    payload = {
        "elements": [
            {"type": "way", "id": 2, "center": {"lat": 19.51, "lon": -99.11}, "tags": {"name": "La Raza"}},
        ]
    }
    df = stations_from_overpass(payload)
    assert len(df) == 1
    assert df.iloc[0]["lat"] == 19.51


def test_skips_elements_without_name():
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 19.50, "lon": -99.10, "tags": {}},
            {"type": "node", "id": 2, "lat": 19.51, "lon": -99.11, "tags": {"name": "Potrero"}},
        ]
    }
    df = stations_from_overpass(payload)
    assert len(df) == 1
    assert df.iloc[0]["osm_name"] == "Potrero"


def test_skips_elements_without_coordinates():
    payload = {"elements": [{"type": "relation", "id": 3, "tags": {"name": "Sin geometria"}}]}
    assert len(stations_from_overpass(payload)) == 0


def test_deduplicates_by_name_keeping_first():
    """OSM suele tener un nodo y un way para la misma estacion."""
    payload = {
        "elements": [
            {"type": "node", "id": 1, "lat": 19.50, "lon": -99.10, "tags": {"name": "Potrero"}},
            {"type": "way", "id": 2, "center": {"lat": 19.5001, "lon": -99.1001}, "tags": {"name": "Potrero"}},
        ]
    }
    df = stations_from_overpass(payload)
    assert len(df) == 1
    assert df.iloc[0]["lat"] == 19.50


def test_empty_payload_returns_empty_frame_with_columns():
    df = stations_from_overpass({"elements": []})
    assert len(df) == 0
    assert list(df.columns) == ["osm_name", "lat", "lon"]


BBOX = (19.4, -99.2, 19.6, -99.0)


def test_fetch_stations_uses_cache_without_touching_network(tmp_path, monkeypatch):
    cache = tmp_path / "osm_stations.json"
    cache.write_text(
        json.dumps(
            {"elements": [
                {"type": "node", "id": 1, "lat": 19.5, "lon": -99.1,
                 "tags": {"name": "Potrero"}}
            ]}
        ),
        encoding="utf-8",
    )

    def explode(*args, **kwargs):
        raise AssertionError("no debe tocar la red habiendo cache")

    monkeypatch.setattr(requests, "post", explode)

    df = fetch_stations(BBOX, cache)
    assert len(df) == 1
    assert df.iloc[0]["osm_name"] == "Potrero"


def test_fetch_stations_corrupt_cache_names_file_and_remedy(tmp_path):
    cache = tmp_path / "osm_stations.json"
    cache.write_text("no soy json", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupta o truncada"):
        fetch_stations(BBOX, cache)


def test_fetch_stations_raises_instead_of_returning_none(tmp_path, monkeypatch):
    """Agotar los reintentos debe lanzar, no devolver None.

    Task 8 espera un DataFrame; un None ahi reventaria mucho mas lejos del
    origen real del problema.
    """
    cache = tmp_path / "osm_stations.json"
    calls = []

    def always_fail(*args, **kwargs):
        calls.append(1)
        raise requests.ConnectionError("sin red")

    monkeypatch.setattr(requests, "post", always_fail)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="3 intentos"):
        fetch_stations(BBOX, cache)
    assert len(calls) == 3
    assert not cache.exists(), "sin respuesta valida no debe quedar cache escrita"


def test_fetch_stations_does_not_retry_a_client_error(tmp_path, monkeypatch):
    """Un 400 es consulta malformada: fallar rapido, no machacar el servidor."""
    cache = tmp_path / "osm_stations.json"
    calls = []

    class BadRequest:
        status_code = 400

        def raise_for_status(self):
            raise requests.HTTPError("400 Bad Request", response=self)

    def one_shot(*args, **kwargs):
        calls.append(1)
        return BadRequest()

    monkeypatch.setattr(requests, "post", one_shot)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    with pytest.raises(requests.HTTPError):
        fetch_stations(BBOX, cache)
    assert len(calls) == 1, "un 400 no se reintenta"
```

- [ ] **Step 2: Correr las pruebas y verificar que fallan**

```bash
uv run pytest tests/test_transporte_stations.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'rtgam.sources.transporte'`.

- [ ] **Step 3: Implementar la parte de estaciones**

`src/rtgam/sources/transporte.py`:

```python
"""Fuente 1: afluencia de transporte publico.

Las coordenadas de las estaciones salen de OpenStreetMap via Overpass, no del
portal de la CDMX: una sola consulta cubre Metro, Tren Ligero, Metrobus y
Cablebus, sin API key y sin perseguir shapefiles distintos por sistema.
"""

import json
import re
import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_S = 180
OVERPASS_RETRIES = 3

STATION_COLUMNS = ["osm_name", "lat", "lon"]


def normalize_name(name: str) -> str:
    """Forma canonica de un nombre de estacion para poder compararlo.

    Minusculas, sin acentos, sin puntuacion, espacios colapsados. Necesario
    porque el CSV de afluencia y OSM escriben los nombres distinto:
    "La Villa-Basilica" contra "La Villa Basílica".
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = decomposed.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    no_punctuation = re.sub(r"[^a-z0-9 ]", " ", lowered)
    return re.sub(r"\s+", " ", no_punctuation).strip()


def fix_mojibake(name: str) -> str:
    """Revierte el doble encodeo UTF-8 del CSV de afluencia del Metro.

    El portal publica el archivo con los bytes UTF-8 interpretados como
    latin-1 y vueltos a codificar, asi que "Aragon" con acento llega escrito
    "AragA-3n". Son 52 de 163 estaciones, el 32 por ciento.

    Sin revertirlo el join muere en silencio: normalize_name("AragA-3n") da
    "araga3n" y OSM dice "aragon". No falla nada, simplemente desaparece un
    tercio de las estaciones del mapa.

    Si la cadena ya esta bien, se devuelve intacta.
    """
    try:
        return name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return name


def stations_from_overpass(payload: dict) -> pd.DataFrame:
    """Convierte una respuesta de Overpass en un DataFrame de estaciones.

    Los elementos sin nombre o sin coordenadas se descartan: no se pueden
    cruzar con la afluencia ni ubicar en el mapa. Se deduplica por nombre
    porque OSM suele tener un nodo y un way para la misma estacion.
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

        rows.append((name, float(lat), float(lon)))

    df = pd.DataFrame(rows, columns=STATION_COLUMNS)
    return df.drop_duplicates(subset="osm_name", keep="first").reset_index(drop=True)


def build_overpass_query(bbox: tuple[float, float, float, float]) -> str:
    """Consulta Overpass para estaciones dentro de un bounding box.

    bbox en el orden que espera Overpass: (sur, oeste, norte, este).
    aerialway=station cubre el Cablebus, que en GAM importa mucho: la Linea 1
    esta enteramente dentro de la alcaldia.
    """
    south, west, north, east = bbox
    box = f"{south},{west},{north},{east}"
    return f"""
[out:json][timeout:{OVERPASS_TIMEOUT_S}];
(
  nwr["railway"="station"]({box});
  nwr["aerialway"="station"]({box});
  nwr["public_transport"="station"]({box});
);
out center tags;
"""


def fetch_stations(
    bbox: tuple[float, float, float, float],
    cache_path: Path,
    force: bool = False,
) -> pd.DataFrame:
    """Descarga las estaciones con cache en disco y reintentos.

    Overpass es un servidor gratuito y devuelve 429 bajo carga, por eso el
    backoff exponencial.
    Igual que en boundary.py, la cache se escribe DESPUES de parsear, nunca
    antes: un payload inservible persistido se releeria en cada corrida.
    """
    if cache_path.exists() and not force:
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"La cache {cache_path} esta corrupta o truncada. "
                f"Borrala o corre con --force para volver a descargar. ({error})"
            ) from error
        return stations_from_overpass(payload)

    query = build_overpass_query(bbox)
    last_error: Exception | None = None
    for attempt in range(OVERPASS_RETRIES):
        try:
            response = requests.post(
                OVERPASS_URL, data={"data": query}, timeout=OVERPASS_TIMEOUT_S
            )
            response.raise_for_status()
            payload = response.json()
            stations = stations_from_overpass(payload)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
            return stations
        except requests.HTTPError as error:
            # Un 4xx que no sea 429 es un bug de nuestra consulta, no una falla
            # transitoria. Reintentarlo tres veces solo castiga a un servidor
            # gratuito y retrasa el error real quince segundos.
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

    raise RuntimeError(f"Overpass fallo tras {OVERPASS_RETRIES} intentos") from last_error
```

- [ ] **Step 4: Correr las pruebas y verificar que pasan**

```bash
uv run pytest tests/test_transporte_stations.py -v
```

Esperado: PASS, 8 pruebas.

- [ ] **Step 5: Commit**

```bash
git add src/rtgam/sources/transporte.py tests/test_transporte_stations.py
git commit -m "feat: coordenadas de estaciones desde Overpass"
```

---

### Task 8: Afluencia, reconciliación de nombres y columna `flujo_transporte`

**Files:**
- Modify: `src/rtgam/sources/transporte.py` (agregar al final)
- Create: `scripts/02_transporte.py`
- Test: `tests/test_transporte_afluencia.py`

**Interfaces:**
- Consumes: `normalize_name`, `fetch_stations` de la Tarea 7; `accumulate_decay`, `hex_centroids` de las Tareas 2-3
- Produces:
  - `weekday_mean_by_station(daily: pd.DataFrame, year: int, date_col: str, station_col: str, value_col: str) -> pd.DataFrame` — columnas `afluencia_name`, `afluencia_habil`
  - `propose_name_map(afluencia_names, osm_names, cutoff: float = 0.6) -> pd.DataFrame` — columnas `afluencia_name`, `osm_name`, `similarity`
  - `to_hex_features(gam_hexes: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame` — indexado por `hex_id`, una columna `flujo_transporte`
  - `data/processed/flujo_transporte.parquet`

- [ ] **Step 1: Adquirir e inspeccionar el CSV de afluencia**

Este paso es manual porque el esquema de columnas del portal no se puede conocer sin ver el archivo.

1. Ir a `datos.cdmx.gob.mx` y buscar "afluencia". Los datasets relevantes son la afluencia diaria del Metro (STC), la de Metrobús y la del STE (Cablebús, Tren Ligero, Trolebús).
2. Descargar los CSV a `data/raw/` con nombres explícitos: `afluencia_metro.csv`, `afluencia_metrobus.csv`, `afluencia_ste.csv`.
3. Inspeccionar el esquema real:

```bash
uv run python -c "
import pandas as pd, glob
for path in sorted(glob.glob('data/raw/afluencia_*.csv')):
    df = pd.read_csv(path, nrows=5)
    print(path)
    print('  columnas:', list(df.columns))
    print('  filas ejemplo:'); print(df.head(2).to_string(index=False))
    print()
"
```

4. Anotar los nombres reales de las tres columnas que importan: fecha, estación y afluencia. Se pasan como argumentos a `weekday_mean_by_station`, así que el código no depende de adivinarlos.

- [ ] **Step 2: Escribir las pruebas que fallan**

Estas pruebas usan un CSV sintético, así que no dependen del esquema real ni de la red.

`tests/test_transporte_afluencia.py`:

```python
import pandas as pd
import pytest

from rtgam.sources.transporte import (
    fix_mojibake,
    normalize_name,
    propose_name_map,
    to_hex_features,
    weekday_mean_by_station,
)


@pytest.fixture
def daily():
    """2025-01-06 a 2025-01-12: lunes a domingo."""
    dates = pd.date_range("2025-01-06", "2025-01-12", freq="D")
    rows = []
    for date in dates:
        weekday = date.weekday() < 5
        rows.append({"fecha": date.strftime("%Y-%m-%d"), "estacion": "Potrero", "afluencia": 1000 if weekday else 200})
        rows.append({"fecha": date.strftime("%Y-%m-%d"), "estacion": "La Raza", "afluencia": 500 if weekday else 100})
    return pd.DataFrame(rows)


def test_fix_mojibake_restores_accents():
    assert fix_mojibake("Arag\u00c3\u00b3n") == "Arag\u00f3n"
    assert fix_mojibake("Instituto del Petr\u00c3\u00b3leo") == "Instituto del Petr\u00f3leo"


def test_fix_mojibake_leaves_clean_names_alone():
    """Idempotente: un nombre ya correcto no se debe estropear."""
    assert fix_mojibake("Potrero") == "Potrero"
    assert fix_mojibake("La Raza") == "La Raza"


def test_mojibake_breaks_the_join_without_the_fix():
    """La razon de existir de fix_mojibake, fijada como prueba."""
    roto = "Arag\u00c3\u00b3n"
    assert normalize_name(roto) != normalize_name("Arag\u00f3n")
    assert normalize_name(fix_mojibake(roto)) == normalize_name("Arag\u00f3n")


def test_weekday_mean_excludes_weekend(daily):
    out = weekday_mean_by_station(daily, year=2025, date_col="fecha", station_col="estacion", value_col="afluencia")
    potrero = out.set_index("afluencia_name").loc["Potrero", "afluencia_habil"]
    assert potrero == pytest.approx(1000.0), "el fin de semana no debe promediarse"


def test_weekday_mean_one_row_per_station(daily):
    out = weekday_mean_by_station(daily, year=2025, date_col="fecha", station_col="estacion", value_col="afluencia")
    assert len(out) == 2
    assert list(out.columns) == ["afluencia_name", "afluencia_habil"]


def test_weekday_mean_filters_by_year(daily):
    other = daily.copy()
    other["fecha"] = other["fecha"].str.replace("2025", "2024")
    combined = pd.concat([daily, other], ignore_index=True)
    out = weekday_mean_by_station(combined, year=2025, date_col="fecha", station_col="estacion", value_col="afluencia")
    assert len(out) == 2


def test_name_map_matches_exact():
    out = propose_name_map(["Potrero"], ["Potrero"])
    assert out.iloc[0]["osm_name"] == "Potrero"
    assert out.iloc[0]["similarity"] == pytest.approx(1.0)


def test_name_map_matches_across_accents():
    out = propose_name_map(["Instituto del Petroleo"], ["Instituto del Petróleo"])
    assert out.iloc[0]["osm_name"] == "Instituto del Petróleo"


def test_name_map_matches_partial_name():
    """El caso real del spec: el CSV dice una cosa y OSM otra."""
    out = propose_name_map(["Deportivo 18 de Marzo"], ["18 de Marzo"])
    assert out.iloc[0]["osm_name"] == "18 de Marzo"
    assert out.iloc[0]["similarity"] > 0.6


def test_name_map_leaves_unmatched_as_none():
    out = propose_name_map(["Estacion Inventada XYZ"], ["Potrero"])
    assert out.iloc[0]["osm_name"] is None


def test_to_hex_features_produces_single_column():
    hexes = pd.DataFrame(
        {"lat": [19.50, 19.70], "lon": [-99.10, -99.10]},
        index=pd.Index(["a", "b"], name="hex_id"),
    )
    stations = pd.DataFrame({"lat": [19.50], "lon": [-99.10], "afluencia_habil": [1000.0]})
    out = to_hex_features(hexes, stations)
    assert list(out.columns) == ["flujo_transporte"]
    assert out.index.tolist() == ["a", "b"]
    assert out.loc["a", "flujo_transporte"] == pytest.approx(1000.0, rel=1e-6)
    assert out.loc["b", "flujo_transporte"] == 0.0


def test_to_hex_features_with_no_stations_returns_zeros():
    hexes = pd.DataFrame({"lat": [19.50], "lon": [-99.10]}, index=pd.Index(["a"], name="hex_id"))
    stations = pd.DataFrame({"lat": [], "lon": [], "afluencia_habil": []})
    out = to_hex_features(hexes, stations)
    assert out.loc["a", "flujo_transporte"] == 0.0
```

- [ ] **Step 3: Correr las pruebas y verificar que fallan**

```bash
uv run pytest tests/test_transporte_afluencia.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'weekday_mean_by_station'`.

- [ ] **Step 4: Implementar la parte de afluencia**

Primero, mover los imports al bloque de arriba del archivo — Python permite
importar a media altura, pero dispersar imports esconde las dependencias del
módulo. Agregar `import difflib` al bloque de imports existente, quedando así:

```python
import difflib
import json
import re
import time
import unicodedata
from pathlib import Path

import pandas as pd
import requests

from rtgam.geo import accumulate_decay
```

Después, agregar al final de `src/rtgam/sources/transporte.py`:

```python
NAME_MATCH_CUTOFF = 0.6


def weekday_mean_by_station(
    daily: pd.DataFrame,
    year: int,
    date_col: str,
    station_col: str,
    value_col: str,
) -> pd.DataFrame:
    """Promedio de afluencia en dia habil por estacion, para un ano dado.

    Los nombres de columna se pasan como argumentos porque cada sistema
    (Metro, Metrobus, STE) publica su CSV con encabezados distintos.

    Solo lunes a viernes: mezclar el domingo borra la senal que distingue una
    zona de oficinas de una residencial, que es justo lo que interesa para una
    cafeteria.
    """
    frame = daily.copy()
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame = frame.dropna(subset=[date_col])

    is_target_year = frame[date_col].dt.year == year
    is_weekday = frame[date_col].dt.weekday < 5
    frame = frame[is_target_year & is_weekday]

    grouped = frame.groupby(station_col)[value_col].mean().reset_index()
    grouped.columns = ["afluencia_name", "afluencia_habil"]
    return grouped


def propose_name_map(
    afluencia_names,
    osm_names,
    cutoff: float = NAME_MATCH_CUTOFF,
) -> pd.DataFrame:
    """Propone el cruce entre nombres del CSV de afluencia y nombres de OSM.

    Es una propuesta, no la verdad: la salida se revisa a mano y se corrige
    antes de usarse. Los nombres sin match quedan con osm_name en None para
    que salten a la vista.

    Compara sobre la forma normalizada, asi que acentos y guiones no estorban.
    """
    normalized_osm = {normalize_name(name): name for name in osm_names}
    candidates = list(normalized_osm)

    rows = []
    for name in sorted(afluencia_names):
        key = normalize_name(name)
        matches = difflib.get_close_matches(key, candidates, n=1, cutoff=cutoff)
        if matches:
            similarity = difflib.SequenceMatcher(None, key, matches[0]).ratio()
            rows.append((name, normalized_osm[matches[0]], similarity))
        else:
            rows.append((name, None, 0.0))

    return pd.DataFrame(rows, columns=["afluencia_name", "osm_name", "similarity"])


def to_hex_features(gam_hexes: pd.DataFrame, stations: pd.DataFrame) -> pd.DataFrame:
    """Reparte la afluencia de las estaciones sobre los hexagonos.

    gam_hexes: indexado por hex_id, columnas lat y lon.
    stations:  columnas lat, lon y afluencia_habil.
    Devuelve:  DataFrame indexado por hex_id con la unica columna que esta
               fuente posee, flujo_transporte, en valor crudo y sin normalizar.
    """
    flow = accumulate_decay(gam_hexes, stations, value_col="afluencia_habil")
    return pd.DataFrame({"flujo_transporte": flow})
```

- [ ] **Step 5: Correr las pruebas y verificar que pasan**

```bash
uv run pytest tests/test_transporte_afluencia.py -v
```

Esperado: PASS, 12 pruebas.

- [ ] **Step 6: Escribir `scripts/02_transporte.py`**

Editar las tres constantes de columna arriba del archivo con los nombres reales anotados en el Step 1.

```python
"""Fuente 1: convierte la afluencia de transporte en la columna flujo_transporte.

Entrada:  data/raw/afluencia_*.csv, data/processed/gam_hexes.parquet
Salida:   data/processed/flujo_transporte.parquet
Auxiliar: data/interim/station_name_map.csv (revisable a mano)

Uso:
    uv run python scripts/02_transporte.py [--force] [--year 2025]
"""

import argparse
import glob
from pathlib import Path

import pandas as pd

from rtgam.sources.transporte import (
    fetch_stations,
    fix_mojibake,
    propose_name_map,
    to_hex_features,
    weekday_mean_by_station,
)

ROOT = Path(__file__).resolve().parents[1]
HEXES = ROOT / "data" / "processed" / "gam_hexes.parquet"
STATIONS_CACHE = ROOT / "data" / "raw" / "osm_stations.json"
NAME_MAP = ROOT / "data" / "interim" / "station_name_map.csv"
OUTPUT = ROOT / "data" / "processed" / "flujo_transporte.parquet"

# Nombres verificados contra el CSV real del portal de la CDMX.
DATE_COL = "fecha"
STATION_COL = "estacion"
VALUE_COL = "afluencia"

# LIMITACION CONOCIDA DE LA FUENTE
# Solo el Metro (STC) publica afluencia por estacion. Metrobus, Cablebus,
# Tren Ligero y Trolebus publican unicamente totales por linea, asi que no
# se pueden repartir sobre hexagonos sin inventar el reparto.
#
# Consecuencia concreta: el Cablebus Linea 1 corre entero dentro de GAM y
# sirve a Cuautepec, y aqui aporta cero. El corredor de Cuautepec va a
# aparecer con menos flujo del que realmente tiene, y cualquier conclusion
# de ubicacion en esa zona no es confiable mientras no exista una fuente
# por estacion.

# Buffer de 1 km alrededor de GAM: una estacion justo afuera del limite
# alimenta hexagonos de GAM de verdad, y filtrarla dejaria el borde
# falsamente muerto. Un grado de latitud son ~111 km.
BUFFER_DEG = 1000.0 / 111_000.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-descargar aunque exista cache")
    parser.add_argument("--year", type=int, default=2025, help="ultimo ano completo")
    args = parser.parse_args()

    hexes = pd.read_parquet(HEXES)

    bbox = (
        hexes["lat"].min() - BUFFER_DEG,
        hexes["lon"].min() - BUFFER_DEG,
        hexes["lat"].max() + BUFFER_DEG,
        hexes["lon"].max() + BUFFER_DEG,
    )
    osm_stations = fetch_stations(bbox, STATIONS_CACHE, force=args.force)
    print(f"Estaciones en OSM dentro de GAM + 1 km: {len(osm_stations)}")

    csv_paths = sorted(glob.glob(str(ROOT / "data" / "raw" / "afluencia_*.csv")))
    if not csv_paths:
        raise SystemExit("No hay data/raw/afluencia_*.csv. Ver el Step 1 de la Tarea 8.")
    daily = pd.concat([pd.read_csv(path) for path in csv_paths], ignore_index=True)
    daily[STATION_COL] = daily[STATION_COL].map(fix_mojibake)

    afluencia = weekday_mean_by_station(
        daily, year=args.year, date_col=DATE_COL, station_col=STATION_COL, value_col=VALUE_COL
    )
    print(f"Estaciones con afluencia en {args.year}: {len(afluencia)}")

    if NAME_MAP.exists():
        name_map = pd.read_csv(NAME_MAP)
        print(f"Usando mapa de nombres revisado: {NAME_MAP}")
    else:
        name_map = propose_name_map(afluencia["afluencia_name"], osm_stations["osm_name"])
        NAME_MAP.parent.mkdir(parents=True, exist_ok=True)
        name_map.to_csv(NAME_MAP, index=False)
        print(f"Mapa de nombres propuesto escrito en {NAME_MAP} — REVISALO A MANO")

    merged = (
        afluencia.merge(name_map, on="afluencia_name", how="left")
        .merge(osm_stations, on="osm_name", how="inner")
    )

    dropped = len(afluencia) - len(merged)
    if dropped:
        missing = set(afluencia["afluencia_name"]) - set(merged["afluencia_name"])
        print(f"AVISO: {dropped} estaciones sin coordenada, excluidas:")
        for name in sorted(missing):
            print(f"  - {name}")

    features = to_hex_features(hexes, merged)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(OUTPUT)

    flow = features["flujo_transporte"]
    print()
    print(f"Hexagonos: {len(flow)}  con flujo > 0: {(flow > 0).sum()}")
    print(f"min {flow.min():.1f}  media {flow.mean():.1f}  max {flow.max():.1f}")
    print("Top 5 hexagonos:")
    print(flow.nlargest(5).to_string())
    print(f"Escrito: {OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Correr el script y revisar el mapa de nombres**

```bash
uv run python scripts/02_transporte.py
```

Primera corrida: se escribe `data/interim/station_name_map.csv`. Abrirlo y revisar cada fila:
- `similarity` menor a 0.8 merece verificación manual.
- `osm_name` vacío significa que hay que buscar la estación en OSM y escribir el nombre a mano, o dejarla vacía si de verdad no existe.
- Corregir los cruces equivocados directamente en el CSV.

Volver a correr. El script toma el CSV revisado en vez de regenerarlo.

Validación: entre 25 y 45 estaciones deben quedar cruzadas (GAM tiene ~30 de Metro más Cablebús L1 y Metrobús). Entre 300 y 700 hexágonos con flujo mayor a cero. Si el conteo de hexágonos con flujo es cercano a cero, el cruce de nombres falló; si es cercano al total, el corte de 800 m no se está aplicando.

- [ ] **Step 8: Commit**

```bash
git add src/rtgam/sources/transporte.py scripts/02_transporte.py tests/test_transporte_afluencia.py
git commit -m "feat: columna flujo_transporte desde afluencia de transporte publico"
```

---

### Task 9: Merge y cálculo del score

**Files:**
- Create: `scripts/99_score.py`
- Test: `tests/test_merge.py`
- Modify: `src/rtgam/score.py` (agregar `merge_features`)

**Interfaces:**
- Consumes: `compute_score`, `load_weights` de la Tarea 5
- Produces:
  - `merge_features(gam_hexes: pd.DataFrame, feature_frames: list[pd.DataFrame]) -> pd.DataFrame`
  - `data/processed/hex_features.parquet`, `data/processed/hex_scores.parquet`

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/test_merge.py`:

```python
import pandas as pd
import pytest

from rtgam.score import merge_features


@pytest.fixture
def hexes():
    return pd.DataFrame(
        {"lat": [19.50, 19.51], "lon": [-99.10, -99.11]},
        index=pd.Index(["a", "b"], name="hex_id"),
    )


def test_merge_attaches_feature_columns(hexes):
    flow = pd.DataFrame({"flujo_transporte": [10.0, 20.0]}, index=hexes.index)
    out = merge_features(hexes, [flow])
    assert list(out.columns) == ["flujo_transporte"]
    assert out.loc["b", "flujo_transporte"] == 20.0


def test_merge_drops_lat_lon(hexes):
    """La geometria se regenera de hex_id; guardarla duplica y arriesga
    que se desincronice."""
    flow = pd.DataFrame({"flujo_transporte": [10.0, 20.0]}, index=hexes.index)
    out = merge_features(hexes, [flow])
    assert "lat" not in out.columns
    assert "lon" not in out.columns


def test_merge_multiple_sources(hexes):
    flow = pd.DataFrame({"flujo_transporte": [10.0, 20.0]}, index=hexes.index)
    comp = pd.DataFrame({"competencia": [1.0, 5.0]}, index=hexes.index)
    out = merge_features(hexes, [flow, comp])
    assert set(out.columns) == {"flujo_transporte", "competencia"}


def test_merge_keeps_all_hexes_filling_missing_with_zero(hexes):
    """Una fuente puede cubrir solo parte de GAM; los huecos son cero, no NaN."""
    partial = pd.DataFrame({"flujo_transporte": [10.0]}, index=pd.Index(["a"], name="hex_id"))
    out = merge_features(hexes, [partial])
    assert len(out) == 2
    assert out.loc["b", "flujo_transporte"] == 0.0
    assert not out.isna().any().any()


def test_merge_with_no_sources_returns_empty_columns(hexes):
    out = merge_features(hexes, [])
    assert len(out) == 2
    assert list(out.columns) == []
```

- [ ] **Step 2: Correr las pruebas y verificar que fallan**

```bash
uv run pytest tests/test_merge.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'merge_features'`.

- [ ] **Step 3: Implementar `merge_features`**

Agregar al final de `src/rtgam/score.py`:

```python
def merge_features(
    gam_hexes: pd.DataFrame, feature_frames: list[pd.DataFrame]
) -> pd.DataFrame:
    """Une las columnas de todas las fuentes sobre el grid completo de GAM.

    Los hexagonos que una fuente no cubre quedan en cero, no en NaN: la
    ausencia de dato aqui significa ausencia del fenomeno (cero estaciones
    cerca, cero competencia), no dato faltante.

    Se descartan lat y lon: la geometria se regenera de hex_id, y guardarla
    en la tabla de features la duplicaria con riesgo de desincronizarse.
    """
    out = pd.DataFrame(index=gam_hexes.index)
    for frame in feature_frames:
        out = out.join(frame, how="left")
    return out.fillna(0.0)
```

- [ ] **Step 4: Correr las pruebas y verificar que pasan**

```bash
uv run pytest tests/test_merge.py -v
```

Esperado: PASS, 6 pruebas.

- [ ] **Step 5: Escribir `scripts/99_score.py`**

```python
"""Une las fuentes, normaliza y calcula el score compuesto.

Entrada: data/processed/gam_hexes.parquet + cualquier <fuente>.parquet presente
Salida:  data/processed/hex_features.parquet (crudo)
         data/processed/hex_scores.parquet (normalizado + score)

Corre con las fuentes que existan. Con solo flujo_transporte ya produce un
mapa valido.

Uso:
    uv run python scripts/99_score.py
"""

from pathlib import Path

import pandas as pd

from rtgam.score import compute_score, load_weights, merge_features

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
HEXES = PROCESSED / "gam_hexes.parquet"
FEATURES_OUT = PROCESSED / "hex_features.parquet"
SCORES_OUT = PROCESSED / "hex_scores.parquet"

# Una entrada por fuente. Agregar una fuente nueva es agregar una linea aqui.
SOURCE_FILES = [
    "flujo_transporte.parquet",
    "denue.parquet",
    "osm.parquet",
    "censo.parquet",
]


def main() -> None:
    hexes = pd.read_parquet(HEXES)

    frames = []
    for filename in SOURCE_FILES:
        path = PROCESSED / filename
        if path.exists():
            frame = pd.read_parquet(path)
            frames.append(frame)
            print(f"Fuente cargada: {filename}  columnas {list(frame.columns)}")
        else:
            print(f"Fuente ausente, se omite: {filename}")

    features = merge_features(hexes, frames)
    features.to_parquet(FEATURES_OUT)

    weights = load_weights()
    scores = compute_score(features, weights)

    used = [c for c in weights if c in features.columns]
    ignored = [c for c in weights if c not in features.columns]
    print()
    print(f"Variables en el score: {used}")
    if ignored:
        print(f"Variables sin datos aun: {ignored}")

    scores.to_parquet(SCORES_OUT)

    print()
    print(f"Hexagonos: {len(scores)}")
    print(f"score  min {scores['score'].min():.4f}  media {scores['score'].mean():.4f}  max {scores['score'].max():.4f}")
    print("Top 10 hexagonos:")
    print(scores.nlargest(10, "score").to_string())
    print(f"Escrito: {FEATURES_OUT}")
    print(f"Escrito: {SCORES_OUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Correr el script y validar**

```bash
uv run python scripts/99_score.py
```

Esperado: reporta `flujo_transporte` como única variable en el score y las otras seis como ausentes. El `score` máximo debe ser `0.35` (el peso de `flujo_transporte` por su valor normalizado máximo de 1.0). Si el máximo no es 0.35, la normalización o los pesos están mal.

- [ ] **Step 7: Correr toda la suite**

```bash
uv run pytest -v
```

Esperado: PASS, 63 pruebas (30 + 4 de boundary + 12 de estaciones + 12 de afluencia + 5 de merge).

- [ ] **Step 8: Commit**

```bash
git add src/rtgam/score.py scripts/99_score.py tests/test_merge.py
git commit -m "feat: merge de fuentes y calculo del score compuesto"
```

---

### Task 10: Dashboard en Streamlit

**Files:**
- Create: `app/dashboard.py`, `src/rtgam/viz.py`
- Test: `tests/test_viz.py`

**Interfaces:**
- Consumes: `load_weights` de la Tarea 5; `data/processed/hex_scores.parquet` de la Tarea 9
- Produces:
  - `hex_polygon_latlon(hex_id: str) -> list[tuple[float, float]]` — vértices `(lat, lon)` listos para Folium
  - `rescore(scores: pd.DataFrame, weights: dict[str, float]) -> pd.Series`

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/test_viz.py`:

```python
import pandas as pd
import pytest

from rtgam.viz import hex_polygon_latlon, rescore


def test_polygon_has_six_vertices():
    """Un hexagono H3 tiene 6 lados; solo los pentagonos de la esfera tienen 5,
    y ninguno cae en CDMX."""
    verts = hex_polygon_latlon("894995aa653ffff")
    assert len(verts) == 6


def test_polygon_is_lat_lon_order_for_folium():
    """Folium espera (lat, lon). h3.cell_to_boundary ya devuelve ese orden,
    pero conviene fijarlo con una prueba para que nadie lo 'arregle'."""
    verts = hex_polygon_latlon("894995aa653ffff")
    lat, lon = verts[0]
    assert 19.0 < lat < 20.0, "la latitud de CDMX ronda 19.x"
    assert -100.0 < lon < -98.0, "la longitud de CDMX ronda -99.x"


def test_rescore_uses_normalized_columns():
    scores = pd.DataFrame(
        {"flujo_transporte_norm": [0.0, 1.0], "competencia_norm": [0.0, 1.0], "score": [0.0, 0.25]},
        index=pd.Index(["a", "b"], name="hex_id"),
    )
    out = rescore(scores, {"flujo_transporte": 1.0, "competencia": -1.0})
    assert out["a"] == pytest.approx(0.0)
    assert out["b"] == pytest.approx(0.0)


def test_rescore_reacts_to_weight_change():
    scores = pd.DataFrame(
        {"flujo_transporte_norm": [0.5], "competencia_norm": [0.0], "score": [0.175]},
        index=pd.Index(["a"], name="hex_id"),
    )
    assert rescore(scores, {"flujo_transporte": 1.0})["a"] == pytest.approx(0.5)
    assert rescore(scores, {"flujo_transporte": 2.0})["a"] == pytest.approx(1.0)


def test_rescore_ignores_weights_without_norm_column():
    scores = pd.DataFrame(
        {"flujo_transporte_norm": [0.5], "score": [0.175]},
        index=pd.Index(["a"], name="hex_id"),
    )
    out = rescore(scores, {"flujo_transporte": 1.0, "densidad_pob": 5.0})
    assert out["a"] == pytest.approx(0.5)
```

- [ ] **Step 2: Correr las pruebas y verificar que fallan**

```bash
uv run pytest tests/test_viz.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'rtgam.viz'`.

- [ ] **Step 3: Implementar `src/rtgam/viz.py`**

```python
"""Utilidades de visualizacion compartidas por el dashboard."""

import h3
import pandas as pd

NORM_SUFFIX = "_norm"


def hex_polygon_latlon(hex_id: str) -> list[tuple[float, float]]:
    """Vertices de una celda H3 en orden (lat, lon), como los quiere Folium.

    h3.cell_to_boundary ya devuelve (lat, lon), al reves de la convencion
    GeoJSON. No invertirlo.
    """
    return [(lat, lon) for lat, lon in h3.cell_to_boundary(hex_id)]


def rescore(scores: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Recalcula el score a partir de las columnas ya normalizadas.

    Es solo un producto punto sobre columnas que ya estan en 0-1, asi que
    mover un slider en el dashboard es instantaneo y no requiere volver a
    correr el pipeline.
    """
    total = pd.Series(0.0, index=scores.index)
    for column, weight in weights.items():
        norm_column = f"{column}{NORM_SUFFIX}"
        if norm_column in scores.columns:
            total = total + weight * scores[norm_column]
    return total
```

- [ ] **Step 4: Correr las pruebas y verificar que pasan**

```bash
uv run pytest tests/test_viz.py -v
```

Esperado: PASS, 6 pruebas.

- [ ] **Step 5: Escribir `app/dashboard.py`**

```python
"""Dashboard de puntuacion de ubicaciones para cafeteria en GAM.

Uso:
    uv run streamlit run app/dashboard.py
"""

from pathlib import Path

import branca.colormap as cm
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from rtgam.score import load_weights
from rtgam.viz import hex_polygon_latlon, rescore

ROOT = Path(__file__).resolve().parents[1]
SCORES = ROOT / "data" / "processed" / "hex_scores.parquet"

GAM_CENTER = (19.52, -99.11)

st.set_page_config(page_title="Cafeteria GAM", layout="wide")


@st.cache_data
def load_scores() -> pd.DataFrame:
    return pd.read_parquet(SCORES)


def main() -> None:
    st.title("Atractivo de ubicacion para cafeteria — Gustavo A. Madero")

    if not SCORES.exists():
        st.error(f"Falta {SCORES}. Corre primero: uv run python scripts/99_score.py")
        return

    scores = load_scores()
    default_weights = load_weights()

    st.sidebar.header("Pesos")
    st.sidebar.caption(
        "Solo las variables con datos cargados aparecen aqui. "
        "El recalculo es instantaneo: las columnas ya estan normalizadas."
    )

    weights = {}
    for name, default in default_weights.items():
        if f"{name}_norm" not in scores.columns:
            continue
        weights[name] = st.sidebar.slider(name, -1.0, 1.0, float(default), 0.05)

    if not weights:
        st.warning("No hay ninguna variable con datos. Corre los scripts de ingestion.")
        return

    scores = scores.copy()
    scores["score"] = rescore(scores, weights)

    left, right = st.columns([3, 2])

    with left:
        colormap = cm.linear.YlOrRd_09.scale(
            float(scores["score"].min()), float(scores["score"].max())
        )
        fmap = folium.Map(location=GAM_CENTER, zoom_start=12, tiles="cartodbpositron")

        for hex_id, row in scores.iterrows():
            folium.Polygon(
                locations=hex_polygon_latlon(hex_id),
                color=None,
                fill=True,
                fill_color=colormap(row["score"]),
                fill_opacity=0.6,
                tooltip=f"{hex_id}<br>score {row['score']:.3f}",
            ).add_to(fmap)

        colormap.add_to(fmap)
        st_folium(fmap, height=600, use_container_width=True)

    with right:
        st.subheader("Top 20 hexagonos")
        norm_columns = [c for c in scores.columns if c.endswith("_norm")]
        st.dataframe(
            scores.nlargest(20, "score")[["score"] + norm_columns].round(3),
            use_container_width=True,
        )
        st.caption(
            "Las columnas _norm muestran por que gano cada hexagono, no solo que gano. "
            "Sin ground truth, el juicio humano sobre este desglose es la validacion."
        )


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Agregar la dependencia faltante**

`branca` viene como dependencia transitiva de folium, pero se importa directo, así que se declara explícita:

```bash
uv add branca
```

- [ ] **Step 7: Correr el dashboard y validar visualmente**

```bash
uv run streamlit run app/dashboard.py
```

Verificar:
- El mapa dibuja los hexágonos sobre GAM, no en el océano ni en el hemisferio equivocado. Si aparecen rotados o desplazados, se invirtió el orden `(lat, lon)`.
- Las zonas calientes coinciden con corredores de transporte conocidos: Indios Verdes, Deportivo 18 de Marzo, Martín Carrera, La Raza.
- Mover el slider de `flujo_transporte` cambia el mapa al instante.
- La tabla top-20 muestra la columna `flujo_transporte_norm` con el desglose.

- [ ] **Step 8: Correr toda la suite**

```bash
uv run pytest -v
```

Esperado: PASS, 68 pruebas (63 + 5 de viz).

- [ ] **Step 9: Commit**

```bash
git add app/dashboard.py src/rtgam/viz.py tests/test_viz.py pyproject.toml uv.lock
git commit -m "feat: dashboard de Streamlit con mapa y pesos ajustables"
```

---

## Cómo correr todo desde cero

```bash
uv sync --extra dev
uv run pytest -v
uv run python scripts/01_build_grid.py
uv run python scripts/02_transporte.py     # revisar station_name_map.csv y repetir
uv run python scripts/99_score.py
uv run streamlit run app/dashboard.py
```

## Qué sigue

Con el pipeline vivo, cada fuente restante del spec es un módulo nuevo en
`src/rtgam/sources/`, un script numerado y una línea en `SOURCE_FILES`:

| script | módulo | columnas que posee |
|--------|--------|--------------------|
| `03_denue.py` | `sources/denue.py` | `competencia`, `atractores_denue` |
| `04_osm.py` | `sources/osm.py` | `accesibilidad_peatonal`, `atractores_osm` |
| `05_censo.py` | `sources/censo.py` | `densidad_pob`, `nivel_socioeconomico` |

Sus planes se escriben después de descargar e inspeccionar los archivos reales.
El censo AGEB es el único que agrega dependencia nueva (geopandas), porque
necesita intersección de áreas para repartir población de AGEB a hexágono.
