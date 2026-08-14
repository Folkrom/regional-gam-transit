# Presencia de transporte: diseño

**Fecha:** 2026-08-14
**Fuente:** 1 (transporte), ampliada
**Variable nueva:** `presencia_transporte`

## Problema

El score de GAM tiene un punto ciego conocido y documentado desde el primer
día, en el comentario `LIMITACION CONOCIDA DE LA FUENTE` de
`scripts/02_transporte.py`: solo el Metro (STC) publica afluencia por
estación. El Cablebús Línea 1 corre entero dentro de la alcaldía y sirve a
Cuautepec, y aporta **cero** a `flujo_transporte`.

Medido contra los datos reales: **los 74 hexágonos que están a 800 m o menos
de una estación del Cablebús L1 tienen hoy `flujo_transporte` exactamente
cero.** Su rank medio es 447 de 724. No es que el modelo los considere y los
descarte: es que no los ve.

La causa es que la única variable de transporte del score mide **volumen**, y
el volumen solo existe para un sistema. Un hexágono junto a una estación de
Cablebús y un hexágono en medio de la nada son indistinguibles.

## Qué se construye

Una segunda variable, `presencia_transporte`: **qué tan cerca está el
hexágono de la estación de riel o cable más cercana**.

```
presencia_transporte(h) = max sobre estaciones e de:
    exp(-d(h, e) / 300)   si d(h, e) <= 800
    0                      si d(h, e) >  800
```

Valor crudo en `[0, 1]`. Sin estaciones cerca, cero. `tau = 300 m` y
`cutoff = 800 m` son las constantes `DECAY_TAU_M` y `DECAY_CUTOFF_M` que ya
usa todo el proyecto; no se introducen parámetros nuevos.

La variable responde a una pregunta distinta de `flujo_transporte`:

| variable | pregunta | fuente del dato |
|---|---|---|
| `flujo_transporte` | ¿cuánta gente pasa por aquí? | afluencia diaria del STC |
| `presencia_transporte` | ¿hay estación aquí? | geometría de OSM |

## Dónde vive

En la fuente 1 (`src/rtgam/sources/transporte.py`), no en una fuente nueva.

Esa fuente **ya descarga las 117 estaciones del bbox** y las cachea en
`data/raw/osm_stations.json`. Reusarla significa cero descargas nuevas,
cero consultas a Overpass, y —lo que importa más— **una sola definición de
dónde están las estaciones**. Dos fuentes independientes pidiendo las mismas
etiquetas ya produjeron un universo distinto una vez en este repo: el
docstring de `osm.py::build_attractor_query` documenta que pedir las mismas
etiquetas no basta si el parseo difiere.

La fuente 1 pasa a emitir dos columnas, igual que DENUE, OSM y censo.

Consecuencia: el parquet `flujo_transporte.parquet` se renombra a
`transporte.parquet`, consistente con `denue/osm/censo.parquet`, que ya se
llaman por la fuente y no por una de sus columnas. **El archivo viejo hay
que borrarlo**: si sobrevive, `SOURCE_FILES` cargaría los dos y
`merge_features` recibiría `flujo_transporte` dos veces.

El **nombre de columna** `flujo_transporte` NO cambia. Aparece en
`weights.yaml`, en el dashboard, en cuatro archivos de tests y en los
parquets ya escritos. Renombrarlo no compra nada.

## Qué cuenta como estación

Por **estructura de etiqueta**, no por cadenas de `network` ni por nombre:

| regla OSM | clase | en GAM |
|---|---|---|
| `aerialway=station` | `cable` | 7 |
| `railway=station` | `riel` | 23 |
| solo `public_transport=station` | descartada | 24 |

Las 7 de cable son el Cablebús L1 completo más el Mexicable en Indios Verdes.
Las 23 de riel son todas STC Metro. Las 24 descartadas son exactamente los
CETRAM, los paraderos de RTP y las terminales de autobús foráneo.

Por qué se descartan: un CETRAM es un intercambiador de superficie sin
infraestructura fija propia, casi siempre **colocado con la estación de Metro
que le da nombre**. Contarlo suma un punto de presencia donde ya hay uno. Y
un paradero de RTP es una parada de camión: si esos cuentan como "estación",
la variable deja de discriminar, porque en GAM hay paradas de camión en todas
partes.

Regla de precedencia cuando un elemento trae varias etiquetas: **cable gana a
riel, riel gana a descartada**. Ninguna estación real de GAM trae
`aerialway=station` y `railway=station` a la vez, pero la regla tiene que ser
determinista de todos modos, no depender del orden del payload.

### Dedup y su interacción con `flujo_transporte`

`stations_from_overpass` ya deduplica por `osm_name` con `keep="first"`,
porque OSM trae un nodo y un way para la misma estación.

La clase **no** puede salir del elemento que sobrevive al dedup: un mismo
nombre puede llegar como un nodo con `railway=station` y un way con solo
`public_transport=station`, y cuál queda primero depende del orden del
payload de Overpass.

Regla: la clase de un nombre es **la más específica de todos los elementos
que comparten ese nombre**, calculada antes de descartar duplicados. Las
coordenadas siguen saliendo del primer elemento, exactamente como hoy.

Esto es deliberado y es la parte que más importa de esta sección: **el camino
de `flujo_transporte` queda bit a bit idéntico.** La variable de volumen no
se toca. Si la implementación descubre que algún valor de `flujo_transporte`
cambia, eso es un defecto, no un efecto secundario aceptable.

## Por qué `max` y no suma

`accumulate_decay`, la primitiva que ya existe, **suma**. Sumar unos
decaídos cuenta puntos, y OSM parte una estación en tantos nodos como quiera
el mapeador. `La Raza` son tres nodos en el mismo andén. `Deportivo 18 de
Marzo`, otros tres. Con suma cobran triple, y son justo los nodos de
transbordo que ya cobran alto por volumen: la variable nueva reforzaría lo
que la vieja ya premia, que es lo contrario de para qué se agrega.

Con `max`, tres nodos colocados dan lo mismo que uno. **Sin dedup, sin
umbral de distancia que justificar, y sin importar cómo OSM decida partirlos
mañana.** La inmunidad es estructural, no una limpieza que hay que mantener.

Honestidad sobre esta elección, medida: `max` y suma correlacionan **0.990**
en el orden global de los 724 hexágonos. El valor de `max` no es cambiar el
mapa; es no mentir en los cuatro sitios de transbordo. Se elige por
corrección, no por impacto.

## Traslape con `atractores_osm`

Las estaciones cuentan hoy dentro de `atractores_osm`: **84 de 1,300
atractores (6.5%)**. Dejarlo así dejaría dos sliders del dashboard moviendo
la misma señal, y el usuario que suba "atractores" para pedir más espacio
público estaría subiendo transporte sin saberlo.

Las estaciones salen de `osm.py`:

- se quitan las tres entradas de estación de `ATTRACTOR_TAGS`
- se quitan las tres de `build_attractor_query`, para no bajar lo que ya no
  se usa
- el bloque de dedup por nombre de `attractors_from_overpass` (que solo
  aplica a `osm_kind == "station"`) queda muerto y se elimina con ellas
- los docstrings que citan conteos de estaciones (`drop_nested` menciona "23
  estaciones dentro de otra estación") se recuentan contra los datos reales

`atractores_osm` queda siendo lo que su nombre dice: espacio público y
comercio de calle. No hace falta re-descargar: la caché existente sigue
sirviendo, porque el parseo simplemente deja de reconocer esos elementos.

## Pesos

En `config/weights.yaml`:

```yaml
  flujo_transporte: 0.25       # antes 0.35
  presencia_transporte: 0.10   # nueva
```

El bloque de transporte sigue pesando **0.35 en total**, repartido entre
volumen y presencia. Así el peso relativo de las otras cinco variables no se
diluye en silencio, que es lo que pasaría si `presencia_transporte` entrara
con 0.10 encima de un `flujo_transporte` intacto.

## Guardas

Contra el bug característico de este repo: **el número equivocado que no
lanza nada.**

1. **Cero estaciones de riel o cable clasificadas → lanzar.** Si OSM cambia
   el esquema de etiquetas, la variable saldría toda en cero y el score la
   reportaría como presente y funcionando.
2. **Cero estaciones de cable → lanzar.** El Cablebús es el motivo entero de
   la variable. Perderlo en silencio deja el punto ciego exactamente donde
   estaba, con la apariencia de haberlo arreglado.

Ambas van en `to_hex_features`, junto al reparto, no en el script: una
prueba tiene que poder dispararlas.

## Qué logra, medido

| | hoy | con la variable |
|---|---|---|
| hexágonos con señal de transporte | 218 de 724 | **299** |
| corredor Cablebús L1 (74 hexágonos) | flujo exactamente cero | presencia media 0.2185 |
| rank medio de ese corredor | 447 de 724 | **363** |
| correlación de rank global | — | 0.9805 |
| score máximo | 0.7590 | 0.7249 |

Los **cinco hexágonos que más suben en toda GAM son los cinco del Cablebús**:
611→321, 528→274, 471→236, 494→266, 531→306.

## Qué NO logra

Va en el README, no solo aquí.

- **Ninguno de los 74 hexágonos del Cablebús entra al top 100.** Esta
  variable mueve Cuautepec del tercio bajo al medio. No lo vuelve ganador, y
  no debería: la zona sigue teniendo menos densidad comercial y menos NSE que
  el corredor de Insurgentes Norte.
- **La variable dice que existe una estación, no cuánta gente la usa.** Un
  Cablebús con 5,000 pasajeros al día y uno con 50,000 puntúan igual. No hay
  afluencia por estación publicada para nada que no sea Metro, y este diseño
  no la inventa.
- **`max` frente a suma correlaciona 0.990.** La inmunidad al conteo doble
  es una corrección puntual en cuatro sitios, no un cambio de mapa.

## Componentes

### `src/rtgam/geo.py` — `nearest_decay`

Primitiva nueva, hermana de `accumulate_decay`:

```python
def nearest_decay(centroids, points, tau=DECAY_TAU_M, cutoff=DECAY_CUTOFF_M) -> pd.Series
```

Devuelve, por hexágono, `max(exp(-d/tau))` sobre los puntos dentro de
`cutoff`; cero si no hay ninguno. Sin `value_col`: la presencia no pondera,
por eso es presencia. Con `points` vacío devuelve ceros alineados al índice.

No se generaliza `accumulate_decay` con un parámetro `how="sum"|"max"`. Son
dos funciones cortas que comparten la matriz de distancias; un parámetro de
modo obliga a cada lector a resolver cuál de los dos comportamientos tiene
delante.

### `src/rtgam/sources/transporte.py`

- `station_class(tags) -> str | None` — `"cable"`, `"riel"` o `None`
- `stations_from_overpass` gana la columna `osm_class`, con la regla de
  precedencia por nombre descrita arriba
- `to_hex_features` emite las dos columnas y aplica las dos guardas

**La firma cambia, y no es cosmético.** Hoy es
`to_hex_features(gam_hexes, stations)`, donde `stations` es el resultado del
`merge(..., how="inner")` con la afluencia: **solo las estaciones que
cruzaron con el CSV del Metro**, 19 dentro de GAM. Pasarle eso a la presencia
la dejaría con exactamente el mismo punto ciego que se está arreglando — el
Cablebús no cruza con nada y no estaría ahí.

Pasa a ser:

```python
def to_hex_features(gam_hexes, con_afluencia, estaciones) -> pd.DataFrame
```

- `con_afluencia`: el merge de hoy, columnas `lat`, `lon`,
  `afluencia_habil` → `flujo_transporte`
- `estaciones`: la salida cruda de `fetch_stations`, columnas `lat`, `lon`,
  `osm_class`, filtrada a riel y cable → `presencia_transporte`

Las dos guardas se evalúan sobre `estaciones`.

`estaciones` cubre el bbox completo, GAM más 1 km, no solo la alcaldía. Es
correcto y es el mismo criterio que ya rige para el flujo: una estación justo
afuera del límite alimenta hexágonos de GAM de verdad, y filtrarla dejaría el
borde falsamente muerto.

### `src/rtgam/sources/osm.py`

Se quitan las estaciones, según la sección de traslape.

### `scripts/02_transporte.py` y `scripts/99_score.py`

Renombre del parquet, borrado del viejo, y las estadísticas de la columna
nueva impresas junto a las de flujo.

## Pruebas

Con dientes, no de humo:

- **`max` no es suma:** tres puntos colocados contra uno suelto, con
  distancias elegidas para que la suma y el máximo no coincidan por
  casualidad. Un test donde ambas den lo mismo no prueba nada — es
  exactamente el defecto que apareció en la revisión del censo, donde ningún
  test distinguía media de mediana porque el fixture tenía dos valores
  simétricos.
- **El corte a 800 m:** un punto a 801 m aporta cero, uno a 799 m aporta
  `exp(-799/300)`.
- **Clasificación:** `aerialway` da cable, `railway` da riel, solo
  `public_transport` da `None`, y un elemento con `aerialway` y
  `public_transport` da cable.
- **Precedencia por nombre:** dos elementos con el mismo nombre, el
  específico segundo en el payload, y la clase sale específica.
- **La presencia no depende de la afluencia:** una estación que no cruza con
  ningún nombre del CSV produce presencia mayor que cero. Este es el test que
  ancla el arreglo entero; sin él, la regresión que lo deshace pasa
  desapercibida.
- **`flujo_transporte` intacto:** el mismo fixture antes y después da el
  mismo valor.
- **Las dos guardas disparan** con su fixture respectivo.
- **`atractores_osm` sin estaciones:** un payload con una estación y un
  parque produce un solo atractor.

## Alternativas descartadas

**Conteo de estaciones en el hexágono, sin decaimiento.** Más simple de
explicar, pero una estación a 50 m y una a 750 m del centroide valen igual, y
en H3 res-9 (~380 m de lado) eso es la diferencia entre estar enfrente y
estar a tres cuadras.

**Sumar el decaimiento (reusar `accumulate_decay` sin tocar nada).** Cero
código nuevo, pero cuenta dos y tres veces las estaciones de transbordo, que
son justo las que ya puntúan alto. Descartada por lo dicho arriba.

**Una fuente nueva, `estaciones.py`.** Separación más limpia en el papel,
pero duplica la descarga, la caché y —el riesgo real— la definición de qué es
una estación.

**Inventar afluencia para el Cablebús repartiendo el total de línea entre sus
estaciones.** Sí existe el total por línea. Repartirlo por partes iguales
inventa el dato, y el número inventado entraría al score con el mismo peso
que el medido, sin que nada distinguiera uno de otro. Este proyecto ya tomó
la decisión contraria en `weekday_mean_by_station` y en el mapa de nombres:
antes que adivinar, no cruzar.
