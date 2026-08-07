# Fuente DENUE: competencia y atractores comerciales

**Fecha:** 2026-08-06
**Estado:** aprobado
**Alcance:** segunda fuente del score de GAM, después de afluencia de transporte

## Problema

El score actual solo tiene una variable, `flujo_transporte`, y cubre **218 de 724
hexágonos (30%)**. Los otros 506 están en cero: invisibles para el modelo. El mapa
son islas alrededor de estaciones del Metro, con GAM apagado en medio.

DENUE aporta dos variables que cubren el territorio completo y atacan justo ese hueco.

## Restricción heredada

Solo datos abiertos y gratuitos. DENUE cumple: descarga directa, sin API key ni
registro.

## Contexto que cambió un supuesto del spec original

El spec de la rebanada vertical definía `atractores_denue` como "oficinas, escuelas,
coworkings". Medido contra los datos reales de GAM, ese recorte captura 2,212 de
50,927 establecimientos — el 4%.

**GAM no es alcaldía de oficinas.** Su distribución real por sector:

| sector SCIAN | descripción | establecimientos |
|---|---|---|
| 46 | comercio al menudeo | 23,120 |
| 81 | otros servicios | 8,558 |
| 72 | alojamiento y comida | 6,410 |
| 62 | salud | 2,744 |
| 31/32/33 | manufactura | 3,640 |
| 61 | educativos | 1,399 |
| 43 | comercio al mayoreo | 1,310 |
| 54 | profesionales y oficinas | 813 |
| 71 | esparcimiento | 568 |

La historia peatonal de GAM es el comercio de calle, no el corredor de oficinas. El
spec original se escribió pensando en una ciudad genérica; este lo ajusta al
territorio real.

## Decisiones de diseño

### 1. Competencia: SCIAN 722515 filtrado por nombre

SCIAN 722515 es "cafeterías, fuentes de sodas, neverías, refresquerías y paleterías".
En GAM son 1,026 establecimientos, y al mirarlos se ve que el código está contaminado
para nuestro propósito:

| | n | % |
|---|---|---|
| parecen café | 296 | 29% |
| paleterías, aguas, nieves | 301 | 29% |
| ni uno ni otro | 429 | 42% |

Los "ambiguos" no son ambiguos al leer los nombres: `ANTOJITOS BETY`,
`ALL YOU CAN EAT`, `ALVRIS FRIES`, `FUENTE DE SODAS PEPE`. Son puestos de comida.

Usar el código crudo inflaría la competencia **3.5×** y castigaría precisamente las
zonas de mucho peatón, que es lo contrario de lo que el modelo busca.

**Decisión:** solo los 296 que matchean el patrón de café cuentan como competencia.

**Alternativa descartada:** usar los 1,026 sin filtrar. Cero criterio propio, pero
trata un puesto de antojitos como rival de una cafetería de especialidad.

### 2. Los no-café no se descartan: pasan a atractores

Una paletería no te compite, pero sí te trae peatón. Una cuadra con veinte puestos de
comida tiene más gente caminando que una vacía.

**Decisión:** los 730 restantes de 722515 suman como atractor. Nada se tira.

**Alternativa descartada:** ignorarlos. Más simple de auditar, pero tira señal real de
actividad en banqueta.

### 3. Atractores: sectores que generan peatón de calle

**Decisión:** sectores SCIAN 46 (menudeo), 72 (comida), 61 (educativos), 62 (salud) y
71 (esparcimiento). 34,241 establecimientos.

Quedan fuera manufactura, mayoreo y transporte: son negocios reales, pero no generan
gente caminando en la banqueta.

**Alternativa descartada:** incluir los 50,927. Cero criterio, pero mete una bodega de
mayoreo con el mismo peso que una panadería.

### 4. Conteo simple, sin ponderar por tamaño

DENUE trae `per_ocu` (personal ocupado) en siete buckets. Ponderar por ese campo es
tentador, y medido resulta contraproducente: **el top 1% acumularía 26.8% de la
variable**, dominado por Liverpool Parque Tepeyac, Costco Lindavista y Supercenter
Tepeyac.

Esos gigantes son destinos de **coche**, no de banqueta. Costco no trae peatón, trae
estacionamiento. Ponderar por empleo convertiría la variable en "cercanía a plaza
comercial", que para una cafetería es la señal equivocada.

**Decisión:** cada establecimiento vale 1. La variable mide densidad comercial, que es
lo que hace una calle caminable.

**Alternativa descartada:** ponderar con tope en 20. Punto medio razonable, pero el
tope es un número sin justificación y agrega una perilla más que calibrar.

### 5. Propiedad única: cada establecimiento aporta a una sola columna

Los 296 de competencia **no** cuentan además como atractor. Contarlos en ambas
cancelaría parcialmente la señal de competencia y haría difícil explicar el efecto de
mover un peso.

`atractores_denue` = 34,241 − 296 = **33,945**.

### 6. Mismo kernel que transporte

`exp(-d/300)`, cero pasados 800 m, vía `accumulate_decay` con valor 1.0 por
establecimiento. La suma ponderada de unos **es** el conteo con decaimiento, así que no
hay código nuevo de reparto espacial.

**Alternativas descartadas:** un radio más corto para competencia (dos kernels que
calibrar, con números salidos de la intuición) y el conteo dentro del hexágono sin
decaimiento (bordes duros: un café a 20 m del límite no contaría y uno a 300 m dentro
sí).

## Fuente de datos

| | |
|---|---|
| URL | `https://www.inegi.org.mx/contenidos/masiva/denue/denue_09_csv.zip` |
| Tamaño | 45 MB comprimido, 248 MB el CSV |
| Contenido | 462,732 unidades económicas de CDMX; 50,927 en GAM |
| API key | ninguna |
| **Encoding** | **`latin-1`**, verificado leyendo el archivo real. No es utf-8. |
| Coordenadas | `latitud` / `longitud`, **cero faltantes en GAM** |

El filtro a GAM se aplica **en la lectura**, para no cargar las 462 mil filas de CDMX
en memoria.

### Patrón de nombres de café

Vive en una constante visible del módulo, no enterrado en una función:

```
CAFE|CAFÉ|CAFF|COFFEE|ESPRESSO|EXPRESSO|CAPPUCC|CAPUCH|BARIST|
TOSTAD|STARBUCK|CIELITO|ITALIAN COFFEE|PUNTA DEL CIELO|MOKA|MOCCA|LATTE
```

`CAFF` es deliberado: la primera versión del patrón se comió `AMOATO CAFFE EXPRESS`.

Es un criterio editorial, no un hecho. El script escribe
`data/interim/competencia_denue.csv` con los 296 nombres cruzados para revisión
humana, igual que `station_name_map.csv`.

## Arquitectura

Módulo `src/rtgam/sources/denue.py` y script `scripts/03_denue.py`, mismo contrato que
la fuente de transporte:

```python
def to_hex_features(gam_hexes: pd.DataFrame, establecimientos: pd.DataFrame) -> pd.DataFrame:
    """Indexado por hex_id, con SOLO las columnas que esta fuente posee."""
```

Salida: `data/processed/denue.parquet` con `competencia` y `atractores_denue`, en
valores **crudos**. La normalización sigue ocurriendo una sola vez, en `99_score.py`.

### El seam ya está listo

`99_score.py` lista `denue.parquet` en `SOURCE_FILES` y `config/weights.yaml` ya tiene
`competencia: -0.10` y `atractores_denue: 0.10`. Aparece el archivo y entra al score
sin tocar código existente.

### Costo de memoria declarado

Pico de memoria medido en la corrida real: **~1.1 GB**, no los 198 MB que estimé al
principio. La cuenta ingenua asume una matriz viva; `haversine_m` mantiene unas seis
del mismo tamaño a la vez (dlat, dlon, los senos al cuadrado, `a`, la raíz, el arcoseno).
Cabe en una máquina normal, pero la cifra existe justamente para que quien lea sepa si
le cabe, así que vale la medida y no la estimación.

## Manejo de errores

Mismos patrones ya establecidos y corregidos en el proyecto:

- El zip se cachea en `data/raw/`. Si existe, no se re-descarga. Flag `--force`.
- **Validar antes de escribir la caché**, nunca al revés. Corregido ya en `boundary.py`
  y en `fetch_stations` tras encontrar que el orden inverso envenena la caché.
- Caché corrupta lanza `ValueError` nombrando el archivo y el remedio.
- `accumulate_decay` ya lanza si el valor trae NaN. Aquí el valor es 1.0 constante, así
  que no debería dispararse; si lo hace, es un bug de construcción.

## Validación de la salida real

- `atractores_denue` debe cubrir **casi los 724 hexágonos**. Ese es el objetivo entero:
  hoy 506 están en cero. Si cubre poco, el filtro de sector falló.
- `competencia` en bastantes menos: son 296 establecimientos concentrados.
- El script imprime, para revisión humana: establecimientos en GAM, cuántos a cada
  columna, hexágonos con señal en cada una, y el top 5 de cada variable.

## Pruebas

pytest, fixtures sintéticos, sin red y sin leer el CSV real.

- **Filtro de café:** `STARBUCKS LINDAVISTA` cruza, `AMOATO CAFFE EXPRESS` cruza,
  `AGUAS DE FRUTAS` no cruza.
- **Filtro de sector:** 46 entra, 43 (mayoreo) no entra.
- **Propiedad única:** ningún establecimiento aparece en ambas columnas.
- **Contrato:** `to_hex_features` devuelve exactamente dos columnas, sin NaN, indexado
  como el grid.
- **Encoding:** fixture escrito en latin-1 con acentos, que falla si alguien lo lee
  como utf-8.

Esa última prueba existe por lo que costó el mojibake del CSV del Metro: un encoding
mal leído que no falló, solo perdió un tercio de las estaciones en silencio.

## Criterio de éxito

`denue.parquet` producido, las dos variables entrando al score sin tocar
`99_score.py`, y la cobertura del mapa subiendo de 218 hexágonos a la gran mayoría de
los 724.

## Fuera de alcance

- Centralidad de la red peatonal (OSM + osmnx) — es la siguiente fuente y la que más
  se parece a "en qué calles camina más gente".
- Censo AGEB: densidad de población y perfil socioeconómico.
- Presencia de estaciones no-Metro como variable separada de volumen, que taparía el
  punto ciego de Cuautepec.
- Ponderar atractores por tamaño de establecimiento.
