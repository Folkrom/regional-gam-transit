# Análisis de flujo peatonal para ubicación de cafetería en Gustavo A. Madero

**Fecha:** 2026-08-05
**Estado:** aprobado
**Alcance:** Fase 1 — alcaldía Gustavo A. Madero (GAM), CDMX

## Problema

Identificar las mejores ubicaciones para abrir una cafetería de especialidad en GAM,
combinando tráfico peatonal estimado con variables de contexto (población, perfil
socioeconómico, accesibilidad, atractores, competencia).

Restricción dura: **solo datos abiertos y gratuitos**. Nada que requiera billing,
tarjeta o API key de pago. En particular, nada de Google Places API.

Objetivo secundario: servir como ejercicio práctico de Python geoespacial para un
desarrollador con background en Go/backend.

## Decisiones de diseño

Cinco decisiones tomadas durante el diseño, con su razón:

### 1. Unidad geográfica: H3 resolución 9

Hexágonos de ~0.105 km², diámetro ~350 m. GAM (~95 km²) produce ~900 celdas.

**Por qué:** el tamaño coincide con el radio de caminata a una cafetería (~2 min desde
el centro del hexágono). La rejilla es uniforme, así que comparar el score de dos celdas
es justo.

**Alternativa descartada:** AGEB de INEGI. Los datos del censo pegarían directo sin
interpolación, pero los polígonos son irregulares (de 2 a 40 manzanas) y comparar el
score de un AGEB de 0.04 km² contra uno de 2.3 km² está sesgado.

**Costo aceptado:** los datos del censo vienen por AGEB, hay que repartirlos a los
hexágonos proporcionalmente al área de intersección.

### 2. Reparto espacial: decaimiento exponencial euclidiano

La afluencia es un dato puntual (por estación); el score es por hexágono. Se reparte con:

```
peso = exp(-d / 300)    para d <= 800 m
peso = 0                para d >  800 m
```

donde `d` es la distancia en metros entre el centroide del hexágono y la estación.
Un hexágono acumula la suma ponderada de todas las estaciones dentro del radio.

| distancia | peso  |
|-----------|-------|
| 0 m       | 1.00  |
| 200 m     | 0.51  |
| 400 m     | 0.26  |
| 800 m     | 0.07  |
| > 800 m   | 0     |

**Por qué:** solo requiere `h3` + `numpy`. El corte a 800 m equivale a ~10 min caminando.

**Alternativa descartada:** isócronas reales sobre la red peatonal de OSM (`osmnx` +
`networkx`). Más fiel, pero agrega descarga pesada, minutos de cómputo y superficie de
fallo en fase 1.

**Mentira conocida y aceptada:** el modelo ignora barreras físicas. En Cuautepec el cerro
del Chiquihuite, el Río de los Remedios y la autopista México-Pachuca hacen que la
distancia euclidiana subestime el trayecto real. Los hexágonos detrás de una barrera van
a salir sobrevalorados. Documentado, no corregido en fase 1.

### 3. Corte temporal: promedio de día hábil del último año completo (2025)

Filtrar lunes a viernes del año 2025, promediar por estación.

**Por qué:** una sola columna, fácil de auditar, y coincide con el patrón de consumo de
cafetería (café de camino al trabajo). El CSV diario crudo se conserva en `data/raw/`,
así que agregar otros cortes después es barato.

**Alternativa descartada:** separar hábil y fin de semana en dos variables. Distinguiría
zona de oficinas de zona destino (Basílica, Martín Carrera), pero agrega una variable más
que normalizar y explicar. YAGNI en fase 1.

### 4. Competencia: conteo ponderado por distancia, resta lineal

Se reusa el mismo kernel `exp(-d/300)` de las estaciones. Cada cafetería cercana suma su
peso; el total se normaliza y se resta del score.

**Por qué:** cero maquinaria nueva. La saturación relativa emerge sola — un hexágono con
mucho flujo y mucha competencia todavía puede quedar arriba, porque el flujo lo compensa.

**Alternativa descartada:** competencia per cápita (`n_cafes / demanda`). Es la métrica
clásica de site-selection, pero acopla variables que ya están en el score por separado,
lo que produce doble conteo y vuelve difícil explicar el efecto de mover un peso.

### 5. Normalización: log1p + min-max

`minmax(log(1 + x))` por columna. Todas las variables terminan en el rango 0-1.

**Por qué:** la afluencia está muy sesgada a la derecha (Indios Verdes aplasta al resto).
`log1p` doma la cola larga; `minmax` deja todas las variables en la misma escala, así que
los pesos son comparables entre sí.

**Alternativa descartada:** z-score sobre valor crudo. Con esta cola, Indios Verdes sale
en z≈+8 y el 90% de los hexágonos queda apiñado entre -0.3 y -0.1. Además el rango no
está acotado, así que un peso de 0.3 no significa lo mismo entre variables.

## Arquitectura

Scripts numerados sobre capas de datos en disco. Sin orquestador, sin PostGIS, sin
backend separado.

```
regional-transit/
├── config/
│   └── weights.yaml             # pesos ajustables
├── data/
│   ├── raw/                     # descargas tal cual, read-only
│   ├── interim/                 # limpio, por fuente
│   └── processed/               # hex_features.parquet, hex_scores.parquet
├── src/
│   ├── geo.py                   # grid H3 de GAM + kernel de decaimiento
│   ├── normalize.py             # log1p + minmax
│   ├── score.py                 # combina pesos
│   └── sources/
│       ├── transporte.py
│       ├── denue.py
│       ├── osm.py
│       └── censo.py
├── scripts/
│   ├── 01_build_grid.py
│   ├── 02_transporte.py
│   ├── 03_denue.py
│   ├── 04_osm.py
│   ├── 05_censo.py
│   └── 99_score.py
├── app/
│   └── dashboard.py             # Streamlit
├── tests/
└── pyproject.toml
```

**Por qué scripts y no notebooks:** el estado oculto de un notebook hace doloroso
re-ejecutar de cero, y el dashboard necesita código reutilizable que viva fuera del
notebook de todos modos.

**Por qué no orquestador (Prefect/Dagster):** sobre-ingeniería para ~900 hexágonos y
4 fuentes.

## Esquema de datos

### `data/processed/hex_features.parquet`

Una fila por hexágono (~900). Valores **crudos**, sin normalizar.

| columna | tipo | fuente | signo en el score |
|---------|------|--------|-------------------|
| `hex_id` | str | grid H3 res 9 | clave primaria |
| `flujo_transporte` | float | afluencia CDMX | + |
| `densidad_pob` | float | censo AGEB | + |
| `nivel_socioeconomico` | float | censo AGEB | + |
| `accesibilidad_peatonal` | float | OSM | + |
| `atractores_denue` | float | DENUE (oficinas, escuelas, coworkings) | + |
| `atractores_osm` | float | OSM (parques, universidades, plazas) | + |
| `competencia` | float | DENUE | **−** |

Los atractores están partidos en dos columnas a propósito: si DENUE y OSM escribieran la
misma columna, dos scripts serían dueños del mismo dato y se rompería el contrato de
propiedad única. Cada fuente es dueña exclusiva de sus columnas.

La geometría **no** se guarda. Se regenera de `hex_id` con `h3.cell_to_boundary()`.
Parquet más chico y cero riesgo de que geometría e ID se desincronicen.

La normalización ocurre una sola vez, en `99_score.py`. Las fuentes nunca normalizan.

### `data/processed/hex_scores.parquet`

Mismo índice `hex_id`, con las columnas ya normalizadas (sufijo `_norm`) más la columna
`score` final. Es lo único que lee el dashboard.

### Contrato de cada fuente

Cada módulo en `src/sources/` expone una función con la misma firma:

```python
def to_hex_features(gam_hexes: set[str]) -> pd.DataFrame:
    """Devuelve un DataFrame indexado por hex_id con SOLO sus columnas."""
```

El merge es un join por `hex_id`. Agregar una fuente nueva significa un archivo nuevo y
una línea en el merge; no toca nada existente.

### `config/weights.yaml`

```yaml
weights:
  flujo_transporte: 0.35
  densidad_pob: 0.15
  nivel_socioeconomico: 0.15
  accesibilidad_peatonal: 0.10
  atractores_denue: 0.10
  atractores_osm: 0.05
  competencia: -0.10
```

Valores iniciales, calibrados a mano para el perfil "cafetería": el flujo de transporte
pondera más porque el caso de uso es café de camino al trabajo. Ajustables sin tocar código.

El score es `sum(w_i * x_norm_i)`, con `w_competencia` negativo. Los pesos **no** tienen
que sumar 1: como todas las variables ya están en 0-1, lo que importa es su proporción
relativa, no la suma. El score resultante no está acotado a 0-1 y no hace falta que lo
esté — solo se usa para ordenar hexágonos.

## Flujo de datos

```
01_build_grid.py    poligono GAM -> h3.polygon_to_cells(res=9) -> gam_hexes.parquet (~900)
02_transporte.py    CSV afluencia + coords estaciones -> kernel -> flujo_transporte
03_denue.py         DENUE GAM -> competencia + atractores_denue
04_osm.py           Overpass -> accesibilidad_peatonal + atractores_osm
05_censo.py         AGEB -> densidad_pob + nivel_socioeconomico (reparto por área)
99_score.py         merge -> log1p+minmax -> pesos -> hex_scores.parquet
```

Los scripts 02 a 05 son **independientes entre sí**. Cada uno corre solo y se valida antes
de pasar al siguiente. `99_score.py` funciona con las columnas que existan: con solo
`flujo_transporte` ya produce un mapa válido. Esto da un pipeline end-to-end vivo desde la
primera fuente, que es el criterio de éxito de la fase 1.

## Fuentes de datos

Todas gratuitas, sin API key de pago.

| fuente | qué aporta | acceso |
|--------|-----------|--------|
| Portal de Datos Abiertos CDMX | afluencia diaria Metro, Metrobús, STE (Cablebús L1, Tren Ligero, Trolebús) | CSV directo |
| Ubicación de estaciones (datos.cdmx / OSM) | coordenadas para el join | shapefile / Overpass |
| INEGI DENUE | negocios existentes: competencia (SCIAN 722515) y atractores (oficinas, escuelas, coworkings) | descarga directa, sin key |
| INEGI Marco Geoestadístico + Censo | polígonos AGEB, población, perfil socioeconómico | descarga directa |
| OpenStreetMap vía Overpass API | infraestructura peatonal, POIs | HTTP, sin key |

Nota: el Cablebús Línea 1 (Indios Verdes–Cuautepec) está enteramente dentro de GAM y su
afluencia vive en el dataset del STE, no en el del Metro.

## Manejo de errores

- **Caché de descargas:** todo se guarda en `data/raw/`. Si el archivo existe, no se
  re-descarga. Flag `--force` para refrescar.
- **Overpass:** timeout de 180 s, reintento con backoff exponencial (3 intentos). Es un
  servidor gratuito y devuelve 429 bajo carga.
- **Estación sin coordenada:** warning, se excluye, y se reporta cuántas quedaron fuera.
  Nunca falla en silencio.
- **Resumen de validación:** cada script imprime al terminar el número de filas, cuántos
  hexágonos tienen valor > 0, min/máx/media y el top 5. Ese es el punto de control humano
  antes de correr la siguiente fuente.

## Dashboard

Streamlit con un mapa de Folium embebido.

- Lee `hex_scores.parquet`, que ya trae las columnas normalizadas.
- Los sliders de peso solo hacen producto punto sobre columnas ya normalizadas:
  recálculo instantáneo, sin re-correr el pipeline.
- Mapa coroplético: `hex_id` → polígono vía `h3.cell_to_boundary()`, color por `score`.
- Tabla top-20 al lado, con el desglose por variable — para ver **por qué** ganó un
  hexágono, no solo que ganó.

## Pruebas

pytest, con un fixture sintético de 10 hexágonos y 3 estaciones. Sin red.

- `geo.py`: el kernel decae según la fórmula; a más de 800 m devuelve exactamente 0; un
  hexágono acumula correctamente la suma de varias estaciones.
- `normalize.py`: casos borde — columna toda en cero, columna con un solo valor único
  (no debe dividir entre cero).
- `score.py`: la competencia resta; un hexágono sin datos no gana.

Las descargas se mockean. No hay pruebas que dependen de red.

## Riesgos declarados

1. **El CSV de afluencia no trae coordenadas.** Trae nombre de estación y línea. Requiere
   cruzarlo contra un segundo dataset de ubicaciones. Los nombres van a diferir entre
   fuentes ("Deportivo 18 de Marzo" vs "18 de Marzo"). Se asume reconciliación manual de
   ~30 estaciones. Acotado, pero no gratis. La tabla de equivalencias vive en
   `data/interim/` y se versiona.

2. **Buffer de 1 km fuera del límite de GAM.** Una estación en Cuauhtémoc a 300 m de la
   frontera alimenta hexágonos de GAM reales. Filtrar estaciones por "dentro de GAM"
   dejaría el borde sur falsamente muerto. El filtro es GAM + 1 km.

3. **SCIAN 722515 es amplio:** "cafeterías, fuentes de sodas, neverías, refresquerías y
   paleterías". Una paletería no compite con café de especialidad, así que la competencia
   va a salir inflada. Mitigación: filtrar además por nombre del establecimiento
   (café/coffee/espresso/tostador) y reportar ambos conteos para poder comparar.

4. **Sin ground truth.** No hay forma de validar que el score predice éxito real de un
   negocio. El entregable es una herramienta de exploración priorizada, no una predicción.
   El desglose por variable en el dashboard existe justamente para que el juicio humano
   audite cada resultado.

## Criterio de éxito de la fase 1

Pipeline end-to-end funcional para GAM: grid H3 construido, al menos la fuente de
transporte ingerida y validada, score compuesto calculado, y dashboard de Streamlit
mostrando el mapa de calor con desglose por variable. Las fuentes 2 a 4 se agregan
incrementalmente sobre ese pipeline ya vivo.

Prioridad explícita: simplicidad sobre completitud.

## Fuera de alcance

- Otras alcaldías de CDMX (fase posterior)
- PostGIS o cualquier base de datos
- Isócronas sobre red peatonal real
- Backend separado o frontend custom
- Series temporales / estacionalidad
- Cualquier fuente de datos de pago
