# Fuente censo AGEB: densidad de población y nivel socioeconómico

**Fecha:** 2026-08-11
**Estado:** aprobado
**Alcance:** cuarta y última fuente del score de GAM, después de transporte, DENUE y OSM

## Problema

De las siete variables de `config/weights.yaml` hay datos de cinco. Faltan
`densidad_pob` y `nivel_socioeconomico`, que juntas pesan **0.30** — el bloque
más grande después de `flujo_transporte`.

Hasta ahora el score sabe cuánta gente *pasa* por un hexágono y cuántos negocios
hay, pero no sabe cuánta gente **vive** ahí ni con qué capacidad de gasto. Para
ubicar una cafetería de especialidad, esa es la mitad que falta: una zona con
mucho tránsito y poca residencia vende café de paso, no de fin de semana.

Con esta fuente el score queda completo.

## Restricción heredada

Solo datos abiertos y gratuitos. Las dos fuentes cumplen: sin API key, sin
registro, sin tarjeta.

## Datos

| archivo | tamaño | origen |
|---|---|---|
| `censo_ageb_09.zip` | 13.0 MB (44 MB al descomprimir) | INEGI, datos abiertos AGEB-manzana CPV 2020 |
| `ageb_cdmx.geojson` | 7.5 MB | portal de datos abiertos CDMX, Marco Geoestadístico 2020 del INEGI |

URLs verificadas con `HTTP 200` y `Content-Length` real:

```
https://www.inegi.org.mx/contenidos/programas/ccpv/2020/datosabiertos/ageb_manzana/ageb_mza_urbana_09_cpv2020_csv.zip
https://datos.cdmx.gob.mx/dataset/d2ccf6ae-fdf4-407c-a15f-e7dfac2d509d/resource/7b0b7a89-d92e-46ec-9286-018e849f8123/download/lmites-de-ageb-urbanas-en-la-ciudad-de-mxico.json
```

El GeoJSON del portal de la CDMX se prefirió sobre el shapefile del Marco
Geoestadístico del INEGI por una razón concreta: **evita `geopandas`**. Un
GeoJSON lo lee `json` y lo convierte `shapely`, que ya es dependencia del
proyecto desde la fuente OSM. El `HANDOFF.md` anticipaba que esta fuente sería
la primera en necesitar `geopandas`; con este archivo, no lo es. Son los mismos
polígonos del Marco Geoestadístico 2020, republicados por el gobierno de la
CDMX.

**Ninguna dependencia nueva.**

### Selección de filas del censo

El CSV trae 230 columnas y una fila por manzana, más filas de totales a varios
niveles. Las filas a nivel AGEB son:

```python
(csv["MUN"] == "005") & (csv["MZA"] == "000") & (csv["AGEB"] != "0000")
```

Da **305 filas**, que es exactamente el número de AGEB de GAM.

Se descartó filtrar además por el texto de `NOM_LOC` (`"Total AGEB"`). Da el
mismo resultado —305 con filtro y sin él, medido— y comparar cadenas con acentos
y mayúsculas es justo la clase de cruce que ya costó caro en este proyecto: el
mojibake del CSV del Metro y el cruce difuso que metía afluencia de otra
alcaldía. Si dos filtros dan lo mismo, gana el que compara claves.

### El cruce entre censo y geometría es exacto

Medido: **305 AGEB en el censo, 305 en la geometría, 0 de un lado sin el otro.**

Ese cruce no es un supuesto, es una **guardia**: si algún día no cuadra, la
fuente lanza. Nunca rellena. Un AGEB con censo pero sin polígono no tendría
dónde aterrizar; uno con polígono pero sin censo pintaría un hueco de población
como si fuera un descampado real.

## Arquitectura

Igual que las tres fuentes anteriores: una primitiva geométrica sin conocimiento
del dominio, más un módulo de fuente que sí lo tiene.

```
src/rtgam/areal.py            primitiva: reparto areal entre poligonos
src/rtgam/sources/censo.py    fuente: descarga, parseo, indice, dos columnas
scripts/05_censo.py           orquestacion
```

`censo.parquet` **ya está** en `SOURCE_FILES` de `scripts/99_score.py`. La cuarta
fuente entra sin tocar `99_score.py`, `weights.yaml`, `geo.py`, `score.py` ni el
dashboard. Es la cuarta vez que se prueba ese seam.

### `src/rtgam/areal.py` — la primitiva

Al mismo nivel que `geo.py` y `red.py`. No sabe qué es un AGEB ni qué columnas
produce el score.

```python
def hex_polygons(hexes: pd.DataFrame) -> dict[str, Polygon]:
    """Poligono de cada celda H3, en lon/lat."""

def area_weights(
    hex_polys: dict[str, Polygon],
    source_polys: dict[str, Polygon],
) -> pd.DataFrame:
    """Fraccion del area de cada poligono origen que cae en cada hexagono.

    Devuelve un DataFrame indexado por hex_id, con una columna por clave de
    origen. Cada COLUMNA suma como mucho 1.0: es el reparto de ese poligono
    entre los hexagonos que lo tocan.
    """
```

La propiedad que hace correcto todo lo demás: **cada columna suma como mucho
1.0**, y suma exactamente 1.0 cuando el polígono origen está enteramente
cubierto por hexágonos. Eso es lo que conserva la población.

Se usa un `STRtree` de shapely para no cruzar 724 × 305 pares. Mismo patrón que
`drop_nested` en `osm.py`.

**No se reproyecta a UTM.** Las áreas se usan solo como **proporciones**
—numerador y denominador salen de la misma intersección— y a esta latitud el
factor de escala se cancela en el cociente. El área del hexágono en km², que sí
es una magnitud absoluta, la da `h3.cell_area(hex_id, "km^2")` directo, sin
geometría de por medio. Es la misma lógica por la que `geo.py` usa haversine en
vez de pyproj.

### `src/rtgam/sources/censo.py` — la fuente

```python
CENSO_URL = "..."          # zip del INEGI
AGEB_GEOJSON_URL = "..."   # GeoJSON del portal CDMX
GAM_MUN = "005"

NSE_COMPONENTS = (
    ("internet",    "VPH_INTER", "VIVPAR_HAB"),   # tasa
    ("automovil",   "VPH_AUTOM", "VIVPAR_HAB"),   # tasa
    ("escolaridad", "GRAPROES",  None),           # valor directo
)

def fetch_censo(cache_path, force=False) -> pd.DataFrame
def fetch_ageb_polygons(cache_path, force=False) -> dict[str, Polygon]
def to_numeric(series) -> pd.Series          # "*" -> NaN
def nse_index(ageb: pd.DataFrame) -> pd.Series
def to_hex_features(gam_hexes, ageb, polygons) -> pd.DataFrame
```

`to_hex_features` devuelve un DataFrame indexado por `hex_id` con exactamente
dos columnas: `densidad_pob` y `nivel_socioeconomico`. Contrato de fuente
intacto.

## `nivel_socioeconomico`: el índice de tres señales

El censo no publica "nivel socioeconómico". Hay que aproximarlo.

**La decisión: promedio de tres señales, cada una escalada 0-1 sobre los 305
AGEB de GAM.**

| señal | columnas | qué capta |
|---|---|---|
| % viviendas con internet | `VPH_INTER / VIVPAR_HAB` | consumo discrecional |
| % viviendas con automóvil | `VPH_AUTOM / VIVPAR_HAB` | patrimonio del hogar |
| escolaridad promedio | `GRAPROES` | capital educativo |

Escolaridad (`GRAPROES`) va de 0.00 a 15.87 años en los 305 AGEB; entre los que
pasan de 100 habitantes, la mediana es 11.27. Los ceros no son escolaridad cero:
ver la sección de viviendas colectivas más abajo.

Se rechazó usar **una sola** columna. Cada una falla de una manera distinta, y
esa es precisamente la razón de mezclarlas:

- **Internet** se satura. Donde casi todas las viviendas ya tienen conexión,
  deja de distinguir entre colonias, y sube con hogares jóvenes aunque no tengan
  más ingreso.
- **Automóvil** sube en la periferia mal servida de transporte, donde el coche
  es necesidad y no lujo. En GAM eso importa: Cuautepec y el norte tienen menos
  transporte que el corredor de Insurgentes Norte.
- **Escolaridad** va una generación rezagada. Una colonia que se gentrificó hace
  diez años todavía mide bajo.

Tres errores en tres direcciones distintas se cancelan parcialmente; uno solo,
no. Es la lógica de los índices tipo AMAI, reducida a lo que el censo publica
gratis.

### La excepción al contrato de valores crudos, y por qué se acepta

El proyecto tiene una regla firme: **las fuentes emiten valores crudos, la
normalización ocurre una sola vez en `99_score.py`**. Este índice la rompe, y no
hay forma de evitarlo: promediar un porcentaje (0-1) con años de escolaridad
(0.00 a 15.87) exige ponerlos en la misma escala **antes** de promediar. Sin
escalar, la escolaridad domina el promedio por su magnitud, no por su
importancia.

Las alternativas se consideraron y se descartaron:

- **Emitir tres columnas** y dejar que `weights.yaml` cargue tres pesos. Cambia
  el contrato de siete variables, toca el núcleo y le pide al usuario calibrar
  tres pesos donde antes había uno. Contradice el diseño del score.
- **Emitir el promedio sin escalar.** Sería un número que parece un índice y no
  lo es: la escolaridad aportaría ~90% de la varianza por su rango.

La excepción se acepta y se documenta. `99_score.py` volverá a normalizar la
columna, lo que sobre un valor ya en 0-1 solo lo reescala; no la corrompe.

## `densidad_pob`

```
densidad_pob = población asignada al hexágono / h3.cell_area(hex_id, "km^2")
```

La población asignada sale del reparto areal: cada AGEB reparte sus `POBTOT`
entre los hexágonos que lo tocan, en proporción al área compartida.

Se dividió entre el área para que sea **densidad** y no conteo: todos los
hexágonos H3 de resolución 9 tienen casi la misma área, pero dividir deja
explícito qué mide la variable y hace la columna comparable si alguna vez cambia
la resolución.

### Medido sobre los datos reales de GAM

| | |
|---|---|
| población del censo en GAM | 1,173,351 |
| población que aterriza en la retícula | **1,137,079 (96.9%)** |
| hexágonos sin ningún AGEB encima | **0 de 724** |
| cobertura de área por hexágono | mediana 1.000, mínima 0.428 |
| hexágonos con menos de 50% cubierto | 3 |
| densidad mediana | 13,238 hab/km² |
| densidad máxima | 33,806 hab/km² |

El 3.1% que se pierde son pedazos de AGEB del borde que sobresalen del área
cubierta por los hexágonos. No es un error del reparto: es que la retícula H3 no
cubre exactamente el mismo polígono que la suma de los AGEB.

**Cero hexágonos sin cobertura** es un resultado importante: significa que el
problema de "qué valor le pongo a un hexágono sin datos de censo" **no existe en
GAM**, y no hace falta inventar una regla de relleno. Se verifica en cada
corrida, no se asume.

## El reparto al hexágono: dos ponderaciones distintas

Esta es la parte donde es fácil equivocarse en silencio.

**`densidad_pob` se reparte por área.** Si el 38% del área de un AGEB cae en un
hexágono, ese hexágono recibe el 38% de su población.

**`nivel_socioeconomico` se promedia pesado por la población asignada, NO por el
área.** Un hexágono que toca un pedazo grande y despoblado de un AGEB (un parque,
un panteón, una vialidad) no debe dejar que ese pedazo vote igual que una
manzana llena de gente. El NSE es un atributo de personas, no de terreno.

Ejemplo del reparto de población:

```
AGEB 0135: 4,716 hab
  -> hex A recibe 38% del area = 1,792 hab
  -> hex B recibe 41% del area = 1,934 hab
  -> hex C recibe 21% del area =   990 hab
                                 -------
                                   4,716   (se conserva)
```

## Valores confidenciales: el `*`

El censo marca como confidencial con un asterisco literal, **no con celda
vacía**. Un `pd.to_numeric(errors="coerce")` los vuelve NaN correctamente, pero
un `fillna(0)` después los convertiría en pobreza inventada.

En GAM son exactamente **dos AGEB**, que juntos suman 21 habitantes:

| AGEB | POBTOT | VIVPAR_HAB | GRAPROES | VPH_INTER | VPH_AUTOM |
|---|---|---|---|---|---|
| 1646 | 7 | 4 | 8.14 | `*` | `*` |
| 1928 | 14 | `*` | `*` | `*` | `*` |

**La regla:**

- `*` → NaN en ese componente.
- El índice promedia los componentes que **sí** tenga. El AGEB 1646 promedia
  solo escolaridad.
- Un AGEB sin **ningún** componente (1928) queda con `nivel_socioeconomico`
  NaN a nivel AGEB, y por lo tanto **queda fuera del promedio pesado** de los
  hexágonos que lo tocan: no aporta ni arrastra.
- Su población **sí** cuenta completa para `densidad_pob`. `POBTOT` no es
  confidencial en ninguno de los dos casos.
- **Un `*` nunca se vuelve 0.** Un cero es un dato: diría "aquí nadie tiene
  internet". Con normalización min-max, un cero falso ancla el piso de la
  columna y mueve a los 724 hexágonos — exactamente el bug que acaba de
  corregirse en la fuente OSM con el fragmento suelto de red.

La columna que sale a parquet **no puede traer NaN**: `merge_features` lanza
ante cualquier NaN de una fuente, y con razón. Como cero hexágonos quedan sin
cobertura y solo un AGEB de 14 habitantes carece de índice, en la práctica todos
los hexágonos tienen al menos un AGEB con NSE. La fuente lo verifica y lanza si
no se cumple, en vez de rellenar.

## Viviendas colectivas: el cero que no es un cero

El `*` no es la única trampa. Medido en GAM: **tres AGEB tienen
`VIVPAR_HAB = 0`**, viviendas particulares habitadas cero. Y uno de ellos no
está vacío.

| AGEB | POBTOT | VIVPAR_HAB | GRAPROES | VPH_INTER | VPH_AUTOM |
|---|---|---|---|---|---|
| 0154 | **8,184** | 0 | 0.00 | 0 | 0 |
| 0718 | 0 | 0 | 0.00 | 0 | 0 |
| 1078 | 0 | 0 | 0.00 | 0 | 0 |

El AGEB 0154 tiene **8,184 habitantes y ninguna vivienda particular**: es
población en vivienda colectiva. El censo la cuenta en `POBTOT` pero no le
levanta el cuestionario de vivienda, así que todas las columnas `VPH_*` y
`GRAPROES` salen en cero.

Dos problemas distintos, los dos silenciosos:

1. **División entre cero.** `VPH_INTER / VIVPAR_HAB` es `0 / 0`. En numpy eso da
   `nan` con un warning, no una excepción. Sin guardia, entra al índice y se
   propaga.
2. **El cero de `GRAPROES` parece un dato.** No dice "escolaridad cero", dice
   "no se preguntó". Tomado literalmente, este AGEB sería el más pobre de GAM
   por goleada, y con normalización min-max **anclaría el piso de la columna**
   para los 724 hexágonos. Es el mismo bug que el fragmento suelto de red que se
   acaba de corregir en la fuente OSM, con otra cara.

**La regla:** un AGEB con `VIVPAR_HAB == 0` se trata igual que uno con `*` —sus
tres componentes son NaN y queda fuera del promedio de NSE—, pero **su población
sí cuenta completa** para `densidad_pob`. Las 8,184 personas del AGEB 0154 están
ahí de verdad y pesan en la densidad; lo que no existe es su nivel
socioeconómico medido.

Esto se descubrió midiendo, no leyendo el diccionario de datos. Es la razón por
la que este proyecto mide antes de escribir código.

## Manejo de errores

Mismo criterio que las tres fuentes anteriores, ya probado:

- **Validar antes de escribir caché.** Un zip truncado o un GeoJSON sin
  `features` no se persiste. Se corrigió tres veces en este proyecto por no
  hacerlo.
- **Caché en disco** en `data/raw/`, con `--force` para re-descargar.
- **`User-Agent` obligatorio** en toda petición saliente.
- **Falla ruidosa ante desajuste de claves** entre censo y geometría.
- **Falla ruidosa si algún hexágono queda sin cobertura**, en vez de rellenar
  con cero o con la mediana.
- **Falla ruidosa si algún hexágono no toca ningún AGEB con NSE.** Hoy no pasa
  en GAM —solo dos AGEB carecen de índice, y ambos están rodeados de AGEB
  normales—, pero el día que pase, un 0.0 sería el hexágono más pobre de la
  alcaldía sin que nada lo dijera.

## Pruebas

Ninguna toca la red. Cuadrados sintéticos como fixtures, igual que en la fuente
OSM.

Con dientes de verdad —cada una debe ponerse roja si se rompe a propósito el
comportamiento que fija:

1. **La población se conserva.** Los pesos de un AGEB repartido entre varios
   hexágonos suman 1.0.
2. **Un AGEB que sobresale de la retícula reparte solo la fracción cubierta**, y
   sus pesos suman menos de 1.0.
3. **`*` no se vuelve 0.** Un AGEB con `VPH_INTER = "*"` promedia los otros dos
   componentes; el índice no baja.
4. **El índice promedia solo los componentes presentes**, no divide siempre
   entre tres.
5. **Un AGEB con `VIVPAR_HAB = 0` no entra al NSE con ceros**, y su población sí
   cuenta para densidad. Fixture con el caso real: 8,184 habitantes, cero
   viviendas. Sin esta prueba, el `0/0` y el `GRAPROES = 0.00` se cuelan como el
   AGEB más pobre de la alcaldía.
6. **La división entre cero no produce NaN en la salida ni un `RuntimeWarning`
   de numpy.**
7. **El NSE pesa por población, no por área.** Fixture con un hexágono que toca
   un AGEB rico y despoblado y otro pobre y denso: el resultado debe inclinarse
   al denso. Sin esta prueba, cambiar el peso de población por área pasaría
   inadvertido.
8. **Un desajuste de claves lanza**, no rellena.
9. **La salida no trae NaN.**
10. **Las columnas son exactamente las dos del contrato.**
11. **El escalado del índice está acotado a 0-1.**
12. **Un hexágono sin cobertura lanza**, en vez de salir con densidad 0.
13. **Un hexágono cuyos AGEB no tienen NSE lanza**, en vez de salir con 0.0.

## Limitaciones que van al README

- **El reparto areal supone población repartida pareja dentro del AGEB.** Es
  falso donde hay un parque, un panteón o una zona industrial grande: esos
  hexágonos salen con población que en realidad está concentrada al lado.
- **El censo es de 2020**, seis años atrás. La CDMX cambió, sobre todo donde
  hubo desarrollo inmobiliario.
- **El 3.1% de la población de GAM cae fuera de la retícula** (36,272 de
  1,173,351), en los bordes de AGEB que sobresalen.
- **`nivel_socioeconomico` es un índice compuesto, no un dato del censo.** Tres
  proxies promediados no son una medición de ingreso. Sirve para ordenar
  hexágonos entre sí, no para afirmar el nivel de nadie.
- **Los 8,184 habitantes en vivienda colectiva del AGEB 0154 cuentan para
  densidad pero no tienen NSE.** Los hexágonos que lo tocan promedian su nivel
  socioeconómico solo con los AGEB vecinos. Es correcto —no hay dato— pero
  significa que ahí el NSE describe al vecindario, no a quien realmente ocupa
  ese polígono.
- **La columna sale escalada 0-1, no cruda**, contra la convención del resto de
  las fuentes. Es la excepción documentada arriba.

## Fuera de alcance

- Reparto dasimétrico (usar edificaciones o uso de suelo para repartir mejor que
  por área). Es la mejora natural si el reparto areal resulta insuficiente, y
  necesita una fuente de datos que hoy no está.
- Censos anteriores o series de tiempo.
- Ingreso: el censo no lo publica a nivel AGEB.
- Datos a nivel manzana. Están en el mismo CSV y darían más resolución, pero
  multiplican por 30 las filas y traen muchos más confidenciales.
- `geopandas`. No hace falta con el GeoJSON.

## Corrección medida en la implementación

La sección "Valores confidenciales: el `*`" afirmaba que «solo un AGEB de 14
habitantes carece de índice» y que «en la práctica todos los hexágonos tienen
al menos un AGEB con NSE». Medido contra los datos reales: son **cuatro** AGEB
sin índice (`0154`, `0718`, `1078`, `1928`), y **seis** hexágonos de 724 no
tocan ninguno con NSE. La premisa era falsa.

La causa que el diseño no contempló: AGEB con **población cero**. `0718` y
`1078` tienen `POBTOT = 0`, así que el promedio pesado por población no tiene
qué ponderar — no es que falte el dato de NSE, es que no hay habitante al que
atribuírselo.

La resolución fue implementar el respaldo por vecinos de anillo 1 que la
sección de limitaciones ya prometía: un hexágono sin AGEB con NSE propio toma
el promedio simple del NSE de sus vecinos inmediatos que sí lo tengan, leyendo
del estado original. La guarda sobrevive para el caso en que ningún vecino
tenga valor tampoco; ahí sí lanza.

La frase de la sección de limitaciones sobre que "los hexágonos que tocan
vivienda colectiva promedian con los AGEB vecinos" describía mal el mecanismo.
El promedio ponderado por población ya excluye de por sí a los AGEB sin NSE,
sin necesidad de respaldo alguno: el AGEB `0154` (vivienda colectiva, 8,184
habitantes) simplemente no aporta al promedio de sus hexágonos, que se calcula
igual con los AGEB vecinos que sí tienen NSE y población que ponderar. El
respaldo por vecinos solo entra cuando **no queda ningún** AGEB con NSE que
tocar, que es un caso distinto y más raro: cinco de los seis hexágonos afectados
caen sobre el AGEB `0718`, de población cero, y uno sobre el `1928`,
confidencial.
