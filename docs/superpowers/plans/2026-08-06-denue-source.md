# Fuente DENUE — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar la segunda fuente del score — competencia y atractores comerciales desde el DENUE de INEGI — subiendo la cobertura del mapa de 218 hexágonos a la gran mayoría de los 724.

**Architecture:** Un módulo `src/rtgam/sources/denue.py` con el mismo contrato que `sources/transporte.py`, más un script `scripts/03_denue.py` que orquesta. El reparto espacial reusa `accumulate_decay` sin código nuevo: la suma ponderada de unos es el conteo con decaimiento. `99_score.py` ya lista `denue.parquet` en `SOURCE_FILES`, así que la fuente entra al score sin tocar código existente.

**Tech Stack:** Python 3.12, uv, pandas, numpy, requests, pyarrow.

## Global Constraints

- **Solo datos abiertos y gratuitos.** DENUE se descarga sin API key ni registro.
- **Encoding del CSV de DENUE: `latin-1`.** Verificado leyendo el archivo real. NO es utf-8.
- **El kernel es fijo:** `exp(-d/300)`, cero pasados 800 m, vía `accumulate_decay`. No re-calibrar.
- **Las fuentes emiten valores CRUDOS.** La normalización ocurre una sola vez, en `99_score.py`.
- **Esta fuente posee exactamente dos columnas:** `competencia` y `atractores_denue`. Ninguna otra fuente las escribe.
- **Propiedad única por establecimiento:** cada uno aporta a UNA sola de las dos columnas, nunca a ambas.
- **Ninguna prueba toca la red ni lee el CSV real.** Todas usan fixtures sintéticos.
- **Validar antes de escribir la caché**, nunca al revés. El orden inverso envenena la caché; ya se corrigió dos veces en este proyecto (`boundary.py`, `fetch_stations`).
- **Imports en el bloque de arriba del archivo.** Un segundo bloque a media altura es defecto que este proyecto ya corrigió tres veces.
- **Idioma:** identificadores en inglés; docstrings, comentarios y salida de scripts en **español**. El dueño del proyecto es hispanohablante y usa esto para aprender Python geoespacial.
- **Commits sin trailer `Co-Authored-By` y sin footer de Claude Code.** Requisito explícito del usuario.
- **Usar `git -c user.name="folkrom" -c user.email="devdielreyes@gmail.com" commit ...`** — el repo no tiene identidad configurada.
- **Nunca `git add -A`** — una vez barrió un archivo de settings local al repo.

## Estado de partida

- 76 pruebas pasando.
- `src/rtgam/geo.py` expone `accumulate_decay(centroids, points, value_col, tau=300.0, cutoff=800.0) -> pd.Series`, alineada al índice de `centroids`, que **lanza `ValueError` si `points[value_col]` trae NaN**.
- `data/processed/gam_hexes.parquet`: 724 filas, índice `hex_id`, columnas `lat`/`lon`.
- `scripts/99_score.py` ya lista `denue.parquet` en `SOURCE_FILES`.
- `config/weights.yaml` ya tiene `competencia: -0.10` y `atractores_denue: 0.10`.

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `src/rtgam/sources/denue.py` | descarga, lectura en latin-1, clasificación, reparto |
| `scripts/03_denue.py` | orquesta y reporta para revisión humana |
| `tests/test_denue_carga.py` | descarga y lectura (Tarea 1) |
| `tests/test_denue_clasificacion.py` | competencia vs atractores (Tarea 2) |
| `tests/test_denue_hexes.py` | reparto espacial (Tarea 3) |

---

### Task 1: Descarga y lectura de DENUE

**Files:**
- Create: `src/rtgam/sources/denue.py`
- Test: `tests/test_denue_carga.py`

**Interfaces:**
- Consumes: nada de tareas previas
- Produces:
  - `DENUE_URL: str`, `DENUE_ENCODING = "latin-1"`, `GAM_MUNICIPIO = "Gustavo A. Madero"`
  - `USECOLS: list[str]`
  - `load_gam(csv_path: str | Path) -> pd.DataFrame` — columnas `nom_estab`, `codigo_act`, `per_ocu`, `lat`, `lon`; solo filas de GAM
  - `fetch_denue_csv(cache_dir: Path, force: bool = False) -> Path`

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/test_denue_carga.py`:

```python
import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest
import requests

from rtgam.sources.denue import (
    DENUE_ENCODING,
    GAM_MUNICIPIO,
    fetch_denue_csv,
    load_gam,
)

FILAS = [
    "id,nom_estab,codigo_act,per_ocu,municipio,latitud,longitud",
    "1,CAFÉ MARTÍNEZ,722515,0 a 5 personas,Gustavo A. Madero,19.50,-99.10",
    "2,PAPELERÍA SOLÍS,465311,0 a 5 personas,Gustavo A. Madero,19.51,-99.11",
    "3,TIENDA DE OTRA ALCALDÍA,461110,0 a 5 personas,Coyoacán,19.34,-99.16",
]


def _write_csv(tmp_path: Path) -> Path:
    # El literal "latin-1" va a proposito, NO la constante del modulo. Si se
    # usara DENUE_ENCODING en ambos lados, cambiarla a utf-8 haria que la
    # prueba escriba y lea con el mismo valor equivocado y siguiera pasando.
    path = tmp_path / "denue.csv"
    path.write_bytes("\n".join(FILAS).encode("latin-1"))
    return path


def test_lee_en_latin1_sin_romper_acentos(tmp_path):
    """El CSV de DENUE viene en latin-1. Leerlo como utf-8 lo rompe.

    Esta prueba existe por lo que costo el mojibake del CSV del Metro: un
    encoding mal leido que no fallo, solo perdio un tercio de los datos en
    silencio.
    """
    df = load_gam(_write_csv(tmp_path))
    nombres = set(df["nom_estab"])
    assert "CAFÉ MARTÍNEZ" in nombres
    assert "PAPELERÍA SOLÍS" in nombres


def test_filtra_solo_gam(tmp_path):
    df = load_gam(_write_csv(tmp_path))
    assert len(df) == 2
    assert "TIENDA DE OTRA ALCALDÍA" not in set(df["nom_estab"])


def test_renombra_coordenadas_a_lat_lon(tmp_path):
    """accumulate_decay espera lat/lon; DENUE los llama latitud/longitud."""
    df = load_gam(_write_csv(tmp_path))
    assert "lat" in df.columns
    assert "lon" in df.columns
    assert "latitud" not in df.columns
    assert df.iloc[0]["lat"] == pytest.approx(19.50)


def test_descarta_filas_sin_coordenadas(tmp_path):
    """En GAM no hay ninguna hoy, pero una fila sin coordenada no se puede
    ubicar y arrastraria un NaN hasta accumulate_decay, que lanza."""
    ruta = tmp_path / "denue.csv"
    filas = FILAS + ["4,SIN UBICACION,461110,0 a 5 personas,Gustavo A. Madero,,"]
    ruta.write_bytes("\n".join(filas).encode(DENUE_ENCODING))
    df = load_gam(ruta)
    assert len(df) == 2
    assert not df[["lat", "lon"]].isna().any().any()


def test_municipio_esperado_es_constante():
    assert GAM_MUNICIPIO == "Gustavo A. Madero"


def test_encoding_declarado_es_latin1():
    """Fija el valor. Sin esto, cambiarlo a utf-8 no rompe ninguna prueba."""
    assert DENUE_ENCODING == "latin-1"


def test_el_archivo_no_es_utf8(tmp_path):
    """Prueba con dientes: el mismo fixture leido como utf-8 debe reventar.

    Verificado contra el archivo real de INEGI, que lanza UnicodeDecodeError
    en utf-8. Si algun dia el portal publicara en utf-8, esta prueba falla y
    obliga a revisar, en vez de perder acentos en silencio.
    """
    path = _write_csv(tmp_path)
    with pytest.raises(UnicodeDecodeError):
        pd.read_csv(path, encoding="utf-8")


def test_cache_corrupta_nombra_el_archivo_y_el_remedio(tmp_path, monkeypatch):
    """Una cache truncada debe decir cual archivo y como salir del problema."""
    cache = tmp_path / "denue_09_csv.zip"
    cache.write_bytes(b"no soy un zip")

    def explota(*args, **kwargs):
        raise AssertionError("no debe tocar la red habiendo cache")

    monkeypatch.setattr(requests, "get", explota)

    with pytest.raises(ValueError, match="corrupta o truncada"):
        fetch_denue_csv(tmp_path)


def test_zip_sin_csv_adentro_falla_claro(tmp_path):
    """Un zip valido pero sin CSV es respuesta inservible, no cache buena."""
    cache = tmp_path / "denue_09_csv.zip"
    with zipfile.ZipFile(cache, "w") as zf:
        zf.writestr("leeme.txt", "sin datos")

    with pytest.raises(ValueError, match="ningun .csv"):
        fetch_denue_csv(tmp_path)


def _zip_bytes(contenido: str) -> bytes:
    """Zip en memoria con el CSV bajo conjunto_de_datos/, como el real."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("conjunto_de_datos/denue_inegi_09_.csv", contenido)
    return buffer.getvalue()


class _RespuestaFalsa:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


def test_descarga_extrae_y_cachea(tmp_path, monkeypatch):
    """Camino feliz: baja, valida, escribe cache y devuelve el CSV extraido."""
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _RespuestaFalsa(_zip_bytes("col\nvalor"))
    )
    destino = fetch_denue_csv(tmp_path)
    assert destino.exists()
    assert (tmp_path / "denue_09_csv.zip").exists()
    assert destino.read_text(encoding="latin-1").startswith("col")


def test_force_reemplaza_el_csv_extraido(tmp_path, monkeypatch):
    """--force debe traer los datos nuevos, no el CSV extraido de antes.

    Sin overwrite, un zip nuevo convive con la extraccion vieja y el llamador
    recibe en silencio los datos anteriores, que es justo lo que --force
    venia a evitar.
    """
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _RespuestaFalsa(_zip_bytes("col\nviejo"))
    )
    primero = fetch_denue_csv(tmp_path)
    assert "viejo" in primero.read_text(encoding="latin-1")

    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _RespuestaFalsa(_zip_bytes("col\nnuevo"))
    )
    segundo = fetch_denue_csv(tmp_path, force=True)
    assert "nuevo" in segundo.read_text(encoding="latin-1")
```

- [ ] **Step 2: Correr las pruebas y verificar que fallan**

```bash
uv run pytest tests/test_denue_carga.py -v
```

Esperado: FAIL con `ModuleNotFoundError: No module named 'rtgam.sources.denue'`.

- [ ] **Step 3: Implementar la parte de carga**

`src/rtgam/sources/denue.py`:

```python
"""Fuente 2: unidades economicas del DENUE de INEGI.

Aporta dos columnas al score: `competencia` (cafeterias existentes) y
`atractores_denue` (comercio que genera peaton de calle).

El archivo se descarga entero para CDMX (462,732 unidades) y se filtra a GAM
en la lectura, para no cargar el resto en memoria.
"""

import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

from rtgam import USER_AGENT

DENUE_URL = "https://www.inegi.org.mx/contenidos/masiva/denue/denue_09_csv.zip"
DENUE_TIMEOUT_S = 300

# El CSV de DENUE viene en latin-1, no en utf-8. Verificado leyendo el archivo
# real: en utf-8 revienta con UnicodeDecodeError.
DENUE_ENCODING = "latin-1"

GAM_MUNICIPIO = "Gustavo A. Madero"

# De las 42 columnas del archivo solo se leen estas cinco. Las demas son
# domicilio desglosado, telefono, correo y web, que no se usan.
USECOLS = ["nom_estab", "codigo_act", "per_ocu", "municipio", "latitud", "longitud"]


def load_gam(csv_path: str | Path) -> pd.DataFrame:
    """Lee el CSV de DENUE y devuelve solo los establecimientos de GAM.

    Renombra latitud/longitud a lat/lon, que es lo que espera
    accumulate_decay, y descarta las filas sin coordenada: no se pueden
    ubicar, y un NaN llegaria hasta el reparto espacial, que lanza.
    """
    frame = pd.read_csv(
        csv_path, encoding=DENUE_ENCODING, usecols=USECOLS, low_memory=False
    )
    frame = frame[frame["municipio"].astype(str) == GAM_MUNICIPIO]
    frame = frame.rename(columns={"latitud": "lat", "longitud": "lon"})
    frame = frame.dropna(subset=["lat", "lon"])
    return frame.drop(columns=["municipio"]).reset_index(drop=True)
```

- [ ] **Step 4: Correr las pruebas y verificar que pasan**

```bash
uv run pytest tests/test_denue_carga.py -v
```

Esperado: PASS, 7 pruebas (las de `load_gam` y encoding; las de `fetch_denue_csv` llegan en el Step 5).

- [ ] **Step 5: Agregar la descarga con caché, y sus dos pruebas**

Las dos pruebas de `fetch_denue_csv` del Step 1 fallan hasta aquí. Ninguna toca
la red: una usa solo la caché y la otra construye un zip en memoria.

Agregar al final de `src/rtgam/sources/denue.py`:

```python
def fetch_denue_csv(cache_dir: Path, force: bool = False) -> Path:
    """Descarga el DENUE de CDMX y devuelve la ruta del CSV extraido.

    El zip son 45 MB y el CSV extraido 248 MB, asi que se cachean en disco y
    no se vuelven a bajar salvo con force.

    El zip se escribe DESPUES de comprobar que abre y trae un CSV dentro. Al
    reves, una respuesta 200 con contenido inservible quedaria persistida y
    envenenaria todas las corridas siguientes.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    zip_path = cache_dir / "denue_09_csv.zip"

    if zip_path.exists() and not force:
        try:
            with zipfile.ZipFile(zip_path) as zf:
                name = _first_csv(zf)
                return _extract(zf, name, cache_dir)
        except zipfile.BadZipFile as error:
            raise ValueError(
                f"La cache {zip_path} esta corrupta o truncada. Borrala o "
                f"corre con --force para volver a descargar. ({error})"
            ) from error

    response = requests.get(
        DENUE_URL, headers={"User-Agent": USER_AGENT}, timeout=DENUE_TIMEOUT_S
    )
    response.raise_for_status()

    content = response.content
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        name = _first_csv(zf)

    zip_path.write_bytes(content)
    with zipfile.ZipFile(zip_path) as zf:
        return _extract(zf, name, cache_dir, overwrite=True)


def _first_csv(zf: zipfile.ZipFile) -> str:
    """Nombre del primer .csv dentro del zip.

    El zip trae el CSV bajo conjunto_de_datos/ junto con diccionarios y
    metadatos, y la ruta exacta cambia entre versiones del archivo.
    """
    names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
    if not names:
        raise ValueError(
            f"El zip de DENUE no trae ningun .csv adentro. Contenido: "
            f"{zf.namelist()[:5]}"
        )
    return names[0]


def _extract(
    zf: zipfile.ZipFile, name: str, cache_dir: Path, overwrite: bool = False
) -> Path:
    """Extrae el CSV del zip a cache_dir.

    `overwrite` existe para el camino de descarga fresca: si se bajo un zip
    nuevo pero se conserva el CSV extraido de antes, el llamador recibiria en
    silencio los datos viejos, que es justo lo que --force venia a evitar.
    """
    destination = cache_dir / "denue_gam.csv"
    if overwrite or not destination.exists():
        destination.write_bytes(zf.read(name))
    return destination
```

- [ ] **Step 6: Correr toda la suite**

```bash
uv run pytest -q
```

Esperado: PASS, 87 pruebas (76 previas + 11 nuevas).

- [ ] **Step 7: Commit**

```bash
git add src/rtgam/sources/denue.py tests/test_denue_carga.py
git commit -m "feat: descarga y lectura del DENUE de CDMX filtrada a GAM"
```

---

### Task 2: Clasificación en competencia y atractores

**Files:**
- Modify: `src/rtgam/sources/denue.py` (agregar al final)
- Test: `tests/test_denue_clasificacion.py`

**Interfaces:**
- Consumes: `load_gam` de la Tarea 1
- Produces:
  - `COFFEE_PATTERN: str`
  - `COMPETENCIA_SCIAN = "722515"`
  - `ATTRACTOR_SECTORS: tuple[str, ...]` = `("46", "72", "61", "62", "71")`
  - `split_competencia_atractores(gam: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]`

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/test_denue_clasificacion.py`:

```python
import pandas as pd

from rtgam.sources.denue import ATTRACTOR_SECTORS, split_competencia_atractores


def _fila(nombre, codigo):
    return {"nom_estab": nombre, "codigo_act": codigo, "lat": 19.5, "lon": -99.1}


def test_cafeterias_cuentan_como_competencia():
    gam = pd.DataFrame([
        _fila("STARBUCKS LINDAVISTA", "722515"),
        _fila("ALEBRIJE CAFE", "722515"),
    ])
    competencia, _ = split_competencia_atractores(gam)
    assert len(competencia) == 2


def test_atrapa_caffe_con_doble_efe():
    """La primera version del patron se comio AMOATO CAFFE EXPRESS."""
    gam = pd.DataFrame([_fila("AMOATO CAFFE EXPRESS", "722515")])
    competencia, _ = split_competencia_atractores(gam)
    assert len(competencia) == 1


def test_paleterias_y_antojitos_no_son_competencia():
    """SCIAN 722515 mezcla cafeterias con paleterias y puestos de comida.

    Medido sobre GAM: de 1026 establecimientos con ese codigo, solo 296
    parecen cafe. Usarlo crudo inflaria la competencia 3.5 veces.
    """
    gam = pd.DataFrame([
        _fila("AGUAS DE FRUTAS", "722515"),
        _fila("ANTOJITOS BETY", "722515"),
        _fila("PALETERIA LA MICHOACANA", "722515"),
    ])
    competencia, atractores = split_competencia_atractores(gam)
    assert len(competencia) == 0
    assert len(atractores) == 3, "no se tiran: traen peaton aunque no compitan"


def test_sectores_de_calle_son_atractores():
    gam = pd.DataFrame([
        _fila("PAPELERIA", "465311"),      # 46 menudeo
        _fila("PRIMARIA BENITO JUAREZ", "611121"),  # 61 educativos
        _fila("FARMACIA", "621331"),       # 62 salud
    ])
    _, atractores = split_competencia_atractores(gam)
    assert len(atractores) == 3


def test_mayoreo_y_manufactura_quedan_fuera():
    """Son negocios reales, pero no generan gente caminando en la banqueta."""
    gam = pd.DataFrame([
        _fila("BODEGA MAYORISTA", "431110"),   # 43 mayoreo
        _fila("TALLER DE COSTURA", "315210"),  # 31 manufactura
    ])
    competencia, atractores = split_competencia_atractores(gam)
    assert len(competencia) == 0
    assert len(atractores) == 0


def test_ningun_establecimiento_en_ambas_columnas():
    """Propiedad unica: cada uno aporta a UNA sola variable.

    Contar un cafe tambien como atractor cancelaria parcialmente la senal de
    competencia.
    """
    gam = pd.DataFrame([
        _fila("STARBUCKS LINDAVISTA", "722515"),
        _fila("AGUAS DE FRUTAS", "722515"),
        _fila("PAPELERIA", "465311"),
    ])
    competencia, atractores = split_competencia_atractores(gam)
    assert len(competencia) == 1
    assert len(atractores) == 2
    assert set(competencia["nom_estab"]) & set(atractores["nom_estab"]) == set()


def test_sectores_atractores_son_los_del_spec():
    assert ATTRACTOR_SECTORS == ("46", "72", "61", "62", "71")
```

- [ ] **Step 2: Correr las pruebas y verificar que fallan**

```bash
uv run pytest tests/test_denue_clasificacion.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'split_competencia_atractores'`.

- [ ] **Step 3: Implementar la clasificación**

Agregar al final de `src/rtgam/sources/denue.py`:

```python
COMPETENCIA_SCIAN = "722515"

# Sectores SCIAN que generan peaton de banqueta. Quedan fuera manufactura,
# mayoreo y transporte: negocios reales, pero nadie camina frente a ellos.
#   46 comercio al menudeo   23,120 en GAM
#   72 alojamiento y comida   6,410
#   62 salud                  2,744
#   61 educativos             1,399
#   71 esparcimiento            568
ATTRACTOR_SECTORS = ("46", "72", "61", "62", "71")

# SCIAN 722515 es "cafeterias, fuentes de sodas, neverias, refresquerias y
# paleterias". En GAM son 1026 establecimientos y solo 296 parecen cafe: el
# resto son paleterias, aguas y puestos de antojitos. Usar el codigo crudo
# inflaria la competencia 3.5 veces y castigaria justo las zonas de mucho
# peaton, que es lo contrario de lo que el score busca.
#
# CAFF esta a proposito: la primera version se comio AMOATO CAFFE EXPRESS.
#
# Es un criterio editorial, no un hecho. Por eso 03_denue.py escribe la lista
# de cruzados a data/interim/ para revision humana.
COFFEE_PATTERN = (
    r"CAF[EÉ]|CAFF|COFFEE|ESPRESSO|EXPRESSO|CAPPUCC|CAPUCH|BARIST|"
    r"TOSTAD|STARBUCK|CIELITO|ITALIAN COFFEE|PUNTA DEL CIELO|MOKA|MOCCA|LATTE"
)


def split_competencia_atractores(
    gam: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Parte los establecimientos de GAM en competencia y atractores.

    Competencia: SCIAN 722515 cuyo nombre matchea el patron de cafe.
    Atractores:  sectores de calle, MENOS los de competencia.

    Cada establecimiento cae en exactamente uno de los dos conjuntos, o en
    ninguno. Nunca en ambos.
    """
    codigo = gam["codigo_act"].astype(str)
    nombre = gam["nom_estab"].astype(str).str.upper()

    es_cafe = codigo.str.startswith(COMPETENCIA_SCIAN) & nombre.str.contains(
        COFFEE_PATTERN, regex=True, na=False
    )
    es_sector_calle = codigo.str[:2].isin(ATTRACTOR_SECTORS)

    competencia = gam[es_cafe]
    atractores = gam[es_sector_calle & ~es_cafe]
    return competencia.reset_index(drop=True), atractores.reset_index(drop=True)
```

- [ ] **Step 4: Correr las pruebas y verificar que pasan**

```bash
uv run pytest tests/test_denue_clasificacion.py -v
```

Esperado: PASS, 7 pruebas.

- [ ] **Step 5: Commit**

```bash
git add src/rtgam/sources/denue.py tests/test_denue_clasificacion.py
git commit -m "feat: clasificar DENUE en competencia y atractores"
```

---

### Task 3: Reparto espacial sobre el grid

**Files:**
- Modify: `src/rtgam/sources/denue.py` (agregar `import` arriba y la función al final)
- Test: `tests/test_denue_hexes.py`

**Interfaces:**
- Consumes: `split_competencia_atractores` de la Tarea 2; `accumulate_decay` de `rtgam.geo`
- Produces: `to_hex_features(gam_hexes: pd.DataFrame, competencia: pd.DataFrame, atractores: pd.DataFrame) -> pd.DataFrame` — indexado por `hex_id`, columnas exactamente `["competencia", "atractores_denue"]`

- [ ] **Step 1: Escribir las pruebas que fallan**

`tests/test_denue_hexes.py`:

```python
import pandas as pd
import pytest

from rtgam.sources.denue import to_hex_features


@pytest.fixture
def hexes():
    return pd.DataFrame(
        {"lat": [19.50, 19.70], "lon": [-99.10, -99.10]},
        index=pd.Index(["cerca", "lejos"], name="hex_id"),
    )


def _puntos(n, lat=19.50, lon=-99.10):
    return pd.DataFrame({"lat": [lat] * n, "lon": [lon] * n})


def test_devuelve_exactamente_las_dos_columnas(hexes):
    out = to_hex_features(hexes, _puntos(1), _puntos(2))
    assert list(out.columns) == ["competencia", "atractores_denue"]


def test_alineado_al_indice_del_grid(hexes):
    out = to_hex_features(hexes, _puntos(1), _puntos(2))
    assert out.index.tolist() == ["cerca", "lejos"]
    assert out.index.name == "hex_id"


def test_cuenta_establecimientos_con_decaimiento(hexes):
    """Cada establecimiento vale 1, asi que el hexagono que los contiene
    acumula su conteo. A 22 km el corte de 800 m deja exactamente cero."""
    out = to_hex_features(hexes, _puntos(3), _puntos(5))
    assert out.loc["cerca", "competencia"] == pytest.approx(3.0, rel=1e-6)
    assert out.loc["cerca", "atractores_denue"] == pytest.approx(5.0, rel=1e-6)
    assert out.loc["lejos", "competencia"] == 0.0
    assert out.loc["lejos", "atractores_denue"] == 0.0


def test_sin_establecimientos_devuelve_ceros_no_error(hexes):
    vacio = pd.DataFrame({"lat": [], "lon": []})
    out = to_hex_features(hexes, vacio, vacio)
    assert out["competencia"].tolist() == [0.0, 0.0]
    assert not out.isna().any().any()
```

- [ ] **Step 2: Correr las pruebas y verificar que fallan**

```bash
uv run pytest tests/test_denue_hexes.py -v
```

Esperado: FAIL con `ImportError: cannot import name 'to_hex_features'`.

- [ ] **Step 3: Implementar el reparto**

Agregar `from rtgam.geo import accumulate_decay` al bloque de imports de arriba del archivo (junto a `from rtgam import USER_AGENT`), y esta función al final:

```python
PESO_COL = "peso"


def to_hex_features(
    gam_hexes: pd.DataFrame,
    competencia: pd.DataFrame,
    atractores: pd.DataFrame,
) -> pd.DataFrame:
    """Reparte los establecimientos sobre los hexagonos con el kernel del proyecto.

    Cada establecimiento vale 1: la suma ponderada de unos ES el conteo con
    decaimiento, asi que no hace falta codigo nuevo de reparto espacial.

    No se pondera por personal ocupado a proposito. Medido sobre GAM, hacerlo
    concentraria 26.8% de la variable en el top 1%, dominado por Costco y
    Liverpool, que son destinos de coche y no traen peaton de banqueta.

    Devuelve un DataFrame indexado por hex_id con las UNICAS dos columnas que
    esta fuente posee, en valores crudos y sin normalizar.
    """
    return pd.DataFrame(
        {
            "competencia": accumulate_decay(
                gam_hexes, competencia.assign(**{PESO_COL: 1.0}), PESO_COL
            ),
            "atractores_denue": accumulate_decay(
                gam_hexes, atractores.assign(**{PESO_COL: 1.0}), PESO_COL
            ),
        }
    )
```

- [ ] **Step 4: Correr las pruebas y verificar que pasan**

```bash
uv run pytest tests/test_denue_hexes.py -v
```

Esperado: PASS, 4 pruebas.

- [ ] **Step 5: Correr toda la suite**

```bash
uv run pytest -q
```

Esperado: PASS, 98 pruebas (76 previas + 11 + 7 + 4).

- [ ] **Step 6: Commit**

```bash
git add src/rtgam/sources/denue.py tests/test_denue_hexes.py
git commit -m "feat: repartir establecimientos de DENUE sobre el grid H3"
```

---

### Task 4: Script de ingestión y corrida real

**Files:**
- Create: `scripts/03_denue.py`
- Modify: `README.md` (agregar el paso a la sección de orden de ejecución)

**Interfaces:**
- Consumes: todo lo de las Tareas 1-3
- Produces: `data/processed/denue.parquet`, `data/interim/competencia_denue.csv`

- [ ] **Step 1: Escribir `scripts/03_denue.py`**

```python
"""Fuente 2: competencia y atractores comerciales desde el DENUE de INEGI.

Entrada: se descarga sola (45 MB) + data/processed/gam_hexes.parquet
Salida:  data/processed/denue.parquet
Auxiliar: data/interim/competencia_denue.csv (revisable a mano)

Uso:
    uv run python scripts/03_denue.py [--force]
"""

import argparse
from pathlib import Path

import pandas as pd

from rtgam.sources.denue import (
    COFFEE_PATTERN,
    fetch_denue_csv,
    load_gam,
    split_competencia_atractores,
    to_hex_features,
)

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
HEXES = ROOT / "data" / "processed" / "gam_hexes.parquet"
COMPETENCIA_REVISION = ROOT / "data" / "interim" / "competencia_denue.csv"
OUTPUT = ROOT / "data" / "processed" / "denue.parquet"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-descargar aunque exista cache"
    )
    args = parser.parse_args()

    csv_path = fetch_denue_csv(RAW, force=args.force)
    gam = load_gam(csv_path)
    print(f"Establecimientos en GAM: {len(gam):,}")

    competencia, atractores = split_competencia_atractores(gam)
    print(f"  competencia (cafeterias): {len(competencia):,}")
    print(f"  atractores (comercio de calle): {len(atractores):,}")

    COMPETENCIA_REVISION.parent.mkdir(parents=True, exist_ok=True)
    competencia[["nom_estab", "codigo_act", "lat", "lon"]].to_csv(
        COMPETENCIA_REVISION, index=False
    )
    print(f"Lista de competencia para revisar a mano: {COMPETENCIA_REVISION}")
    print(f"  el patron de nombres usado fue: {COFFEE_PATTERN[:60]}...")

    hexes = pd.read_parquet(HEXES)
    features = to_hex_features(hexes, competencia, atractores)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    features.to_parquet(OUTPUT)

    print()
    for columna in ["competencia", "atractores_denue"]:
        serie = features[columna]
        print(
            f"{columna}: {(serie > 0).sum()} de {len(serie)} hexagonos con senal "
            f"| media {serie.mean():.2f} | max {serie.max():.2f}"
        )
    print()
    print("Top 5 por atractores_denue:")
    print(features.nlargest(5, "atractores_denue").to_string())
    print(f"Escrito: {OUTPUT}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Correr el script**

```bash
uv run python scripts/03_denue.py
```

La primera corrida descarga 45 MB y extrae 248 MB. Puede tardar varios minutos. **Correrlo en primer plano, nunca en background** — en este proyecto ya se perdió trabajo tres veces por mandar un script largo a background y que el proceso muriera con su padre.

- [ ] **Step 3: Validar la salida contra los rangos esperados**

Cifras medidas sobre los datos reales al escribir el spec:

| | esperado |
|---|---|
| establecimientos en GAM | ~50,927 |
| competencia | ~296 |
| atractores | ~33,945 |
| hexágonos con `atractores_denue` > 0 | **la gran mayoría de los 724** |
| hexágonos con `competencia` > 0 | bastantes menos |

El objetivo entero de esta fuente es la penúltima fila: hoy 506 hexágonos están en cero. Si `atractores_denue` cubre poco, el filtro de sector falló y hay que investigar, no ajustar el umbral.

- [ ] **Step 4: Revisar la lista de competencia**

Abrir `data/interim/competencia_denue.csv` y leer los ~296 nombres. Es un criterio editorial: buscar cafeterías reales que el patrón se haya comido, y falsos positivos que hayan entrado. Reportar lo que se encuentre; no hace falta corregir el patrón en esta tarea.

- [ ] **Step 5: Correr el score con la fuente nueva**

```bash
uv run python scripts/99_score.py
```

Debe reportar `flujo_transporte`, `competencia` y `atractores_denue` como variables en el score, y solo `densidad_pob`, `nivel_socioeconomico`, `accesibilidad_peatonal` y `atractores_osm` como ausentes.

El score máximo **ya no será 0.35**: con tres variables deja de ser el producto de un solo peso. Reportar el nuevo máximo y el nuevo top 10, y comparar contra el top 10 anterior — se espera que se muevan, porque el mapa deja de ser islas alrededor del Metro.

- [ ] **Step 6: Agregar el paso al README**

En la sección de orden de ejecución, insertar entre `02_transporte.py` y `99_score.py`:

```markdown
3. `uv run python scripts/03_denue.py` — descarga el DENUE de INEGI (45 MB) y
   calcula competencia y atractores comerciales. Tras la primera corrida,
   revisar `data/interim/competencia_denue.csv`: la lista de cafeterías se
   arma con un patrón de nombres, que es criterio editorial y no un hecho.
```

- [ ] **Step 7: Commit**

```bash
git add scripts/03_denue.py README.md
git commit -m "feat: script de ingestion del DENUE"
```

---

## Cómo correr todo desde cero

```bash
uv sync --extra dev
uv run pytest -v
uv run python scripts/01_build_grid.py
uv run python scripts/02_transporte.py     # revisar station_name_map.csv y repetir
uv run python scripts/03_denue.py          # revisar competencia_denue.csv
uv run python scripts/99_score.py
uv run streamlit run app/dashboard.py
```

## Qué sigue

| script | módulo | columnas que posee |
|---|---|---|
| `04_osm.py` | `sources/osm.py` | `accesibilidad_peatonal`, `atractores_osm` |
| `05_censo.py` | `sources/censo.py` | `densidad_pob`, `nivel_socioeconomico` |

La centralidad de la red peatonal —la que más se parece a "en qué calles camina
más gente"— entra con `04_osm.py` y es la única que agrega dependencia nueva
(`osmnx` + `networkx`).
