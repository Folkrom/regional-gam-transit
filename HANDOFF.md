# Handoff — estado al 2026-08-23

Dónde quedó el proyecto y qué conviene saber antes de tocar nada.

## Estado

`main` en `b00a95a`, con las ocho variables integradas y el filtro por colonia
del dashboard (PR #9). Encima, sin mergear todavía, el arreglo del bug del borde
de DENUE. 276 pruebas pasando en 1 s, sin red. El pipeline completo
corre de punta a punta y el dashboard levanta.

**Cobertura del score: 724 de 724 hexágonos.** Arrancó en 218 con solo la fuente
de transporte; DENUE cubrió el 70% de GAM que estaba invisible, y OSM cerró los
últimos 18: su red peatonal enganchó los 724 centroides sin excepción (0
hexágonos sin calle a menos de 500 m).

| variable | fuente | estado |
|---|---|---|
| `flujo_transporte` | afluencia del Metro | ✅ |
| `presencia_transporte` | OSM, cercania a estacion de riel o cable | ✅ |
| `competencia` | DENUE, SCIAN 722515 filtrado | ✅ |
| `atractores_denue` | DENUE, sectores 46/72/61/62/71 | ✅ |
| `accesibilidad_peatonal` | OSM, alcance a 800 m por la red | ✅ |
| `atractores_osm` | OSM, solo espacio publico | ✅ |
| `densidad_pob` | censo AGEB | ✅ |
| `nivel_socioeconomico` | censo AGEB | ✅ |

Score máximo actual: `0.7210` (era `0.5136` con cinco variables, y `0.7552` con
siete, antes de repartir el peso del transporte entre volumen y presencia).

`atractores_osm` sale de 1,218 atractores, ya **sin estaciones**: se fueron a
`presencia_transporte` y ni siquiera se piden en la consulta de Overpass.
Contaban en las dos variables —84 de 1,300— y eso ponía dos sliders del
dashboard moviendo la misma señal.

Una sola regla los recorta ahora, y importa:

- **Anidamiento.** Un atractor cuyo punto cae dentro del polígono de otro
  *estrictamente mayor* no cuenta aparte: son 470 de 1,688 (28%). El Deportivo
  Hermanos Galeana trae 59 atractores mapeados por separado —56 canchas, 2
  juegos infantiles y un jardín— y contaba 60 veces. Por eso la consulta pide
  `out geom` y no `out tags center`: un centro no contiene nada. La caché se
  llama `osm_atractores_geom.json`, con nombre distinto al de la vieja a
  propósito — reusar aquella dejaría de detectar el anidamiento en silencio.

El dedup por nombre que había aquí murió con las estaciones: solo aplicaba a
ellas. Los demás tipos **nunca** se dedup por nombre, y es deliberado: los
nombres de parque y cancha en GAM son genéricos y se repiten entre sitios
genuinamente distintos. `transporte.py` conserva su propio dedup por nombre,
que es el que importa ahora.

## Cómo correrlo

```bash
uv sync --extra dev
uv run pytest -q
uv run python scripts/01_build_grid.py
uv run python scripts/02_transporte.py
uv run python scripts/03_denue.py
uv run python scripts/04_osm.py
uv run python scripts/05_censo.py
uv run python scripts/06_colonias.py
uv run python scripts/99_score.py
uv run streamlit run app/dashboard.py
```

`data/` está en `.gitignore`, así que en un clone limpio hay que volver a correr
todo. Lo único que se baja a mano es `data/raw/afluencia_metro.csv`, del portal
de datos abiertos de la CDMX; DENUE y el límite de GAM se descargan solos.

Dos archivos de revisión humana, ambos en `data/interim/`:
`station_name_map.csv` (versionado, tus ediciones se conservan y alimentan la
siguiente corrida) y `competencia_denue.csv` (**no** versionado, se regenera en
cada corrida, así que editarlo no sirve de nada).

## Lo siguiente

**Las ocho variables ya tienen datos; no queda fuente pendiente.** El censo
AGEB aportó `densidad_pob` y `nivel_socioeconomico` sin necesitar `geopandas`:
el reparto de población de polígonos AGEB a hexágonos por intersección de área
se hizo con `shapely` puro, igual que el resto del stack.

`presencia_transporte` fue la última en entrar y **no necesitó fuente nueva**:
reusa las 117 estaciones que `transporte.py` ya descargaba. La fuente 1 emite
dos columnas, y su parquet se llama ahora `transporte.parquet`, no
`flujo_transporte.parquet`.

(OSM ya quedó integrado: `accesibilidad_peatonal` y `atractores_osm` salen de
`scripts/04_osm.py`. La técnica es Dijkstra acotado a 800 m sobre el grafo de
calles descargado de Overpass, en `networkx` puro, sin `osmnx` — se prefirió
así porque `osmnx` arrastra `geopandas`, `pyproj`, `rtree` y `scikit-learn` y
cachea por su cuenta en paralelo al patrón del proyecto. No es *betweenness*:
es alcance, metros de calle recorribles desde el centroide del hexágono.)

**No queda deuda anotada.** Las dos que había —`fetch_stations` cacheando la
respuesta de Overpass sin mirar `remark`, y la frontera exacta del corte sin
test en `accumulate_decay`— se cerraron en sus ramas (PR #7 y #8).

**Deuda anotada: el margen del bbox de OSM.** Está descrita arriba, en la lista
de dónde los números no son confiables. Es el mismo bug del borde que DENUE ya
tiene arreglado, en versión suave y todavía sin medir: la consulta de
comprobación a Overpass no terminó en 10 minutos y se abandonó a propósito en
vez de anotar una cifra inventada.

### El bug del borde de DENUE: arreglado

Cerrado el 2026-08-23. DENUE ya no se recorta por municipio sino por distancia
a la rejilla, y se bajan también los archivos del Estado de México.

**Lo que estaba mal.** `load_gam` se quedaba con `municipio == "Gustavo A.
Madero"`, así que una cafetería a 300 m cruzando la calle no contaba. Medido
ahora contra el filtro nuevo: **219 de 724 hexágonos** ganan más de un atractor
y el peor estaba subestimado **12.2×** (`894995b9427ffff`: 22.9 contra 171.0).
La cifra vieja del README —76 hexágonos, 7.5×— sólo veía el lado de CDMX,
porque era lo único que el archivo de la entidad 09 permitía ver.

**El recorte nuevo es un collar H3, no una caja.** `geo.cells_near_grid` abre
tres anillos alrededor de cada celda de la rejilla. Tres no es a ojo: un punto a
800 m de un centroide vive en una celda cuyo centro está a lo más 800 + 217.9 =
1017.9 m, y el anillo 4 empieza en 1291.7 m. Contra un filtro por caja
envolvente, que trae 45% más puntos, las dos columnas salen idénticas hasta
1e-13; el collar deja la matriz de reparto en 304 MB por arreglo en vez de 550.

**Qué entra ahora.** 79,948 establecimientos dentro del collar, de los cuales
29,026 están fuera de GAM: Tlalnepantla 9,000, Venustiano Carranza 6,054,
Nezahualcóyotl 4,631, Azcapotzalco 3,332, Cuauhtémoc 3,284, Ecatepec 2,725.
`competencia` pasó de 296 a 422 establecimientos y `atractores_denue` de 33,945
a 52,924.

**El efecto en el ranking es menor de lo que sugiere el 12.2×**, y conviene
saberlo: el máximo y la media del score no se movieron en cuatro decimales, 9
hexágonos de 724 se mueven más de 50 puestos y sólo uno más de 100 (148). La
razón es la normalización min-max: los atractores subieron en casi todos lados,
así que el orden relativo cambia poco. 18 de los 20 primeros siguen en el top
20. Lo que se arregló no es el podio, es que los hexágonos del borde ya no
mienten sobre cuánto comercio tienen cerca.

### Filtro por colonia: hecho

Implementado el 2026-08-23, en `src/rtgam/colonias.py`, `scripts/06_colonias.py`
y el multiselect del dashboard. Diseñado el 2026-08-15; los números medidos
entonces salieron idénticos al correrlo.

**Qué es y qué no es.** Un **filtro de vista**: eliges colonias y el mapa
esconde el resto. Los scores **no** se recalculan, y tampoco el `rank` ni la
escala de color, que se fijan sobre los 724 hexágonos antes de filtrar. Alcance
y resolución son ejes distintos, y esto solo toca el primero — la rejilla se
queda en H3 res 9.

Se descartó a propósito re-normalizar dentro del subconjunto. `log1p_minmax`
corre sobre las filas que le des, así que filtrar antes de normalizar estira
cada variable a 0-1 dentro de las colonias elegidas: re-ordena, y si el
subconjunto tiene `competencia` casi uniforme, amplifica ruido al rango
completo. Filtrando después, el score sigue significando "contra toda GAM" y el
rank 219 sigue siendo 219.

**La trampa que se evitó: no filtrar las fuentes, solo los candidatos.** Una
cafetería a 300 m cruzando la calle compite igual aunque esté en otra colonia.
Filtrar DENUE u OSM por colonia reproduciría el bug del borde que costó
arreglar —219 de 724 hexágonos, el peor subestimado 12.2×— y ahí pegaría más
fuerte: los bordes de colonia suman mucho más perímetro que el de la alcaldía.

**Fuente.** `coloniascdmx` del portal de datos de la CDMX, Colonias del IECM
2019. GeoJSON de 6 MB, CRS84, sin llave, cacheado en
`data/raw/colonias_cdmx.geojson`:

```
https://datos.cdmx.gob.mx/dataset/04a1900a-0c2f-41ed-94dc-3d2d5bad4065/resource/8070ee81-9111-437e-a3dd-0c3cc6dce9f4/download/colonias-cdmx-.json
```

1,814 colonias en la CDMX; `NOMDT` trae la alcaldía en mayúsculas sin acentos
(`GUSTAVO A. MADERO`), `NOMUT` el nombre y `CVEUT` la clave. En GAM no hay
claves ni nombres repetidos, y 4 de las 232 colonias son MultiPolygon. Ojo con
el aviso de `boundary.py`: las URLs de este portal cambian entre versiones, así
que si esa muere hay que volver a buscarla por la API CKAN
(`/api/3/action/package_show?id=coloniascdmx`). OSM quedó descartada por
medición: 15 polígonos contra 430 nodos `place=neighbourhood` en el bbox de
GAM — las colonias de la CDMX están mapeadas como puntos.

**Lo que imprime el script, medido:**

- **12 hexágonos (1.7%) no caen en ninguna colonia.** Entran al selector como
  `(sin colonia)`; no se tiran en silencio.
- **194 colonias tienen al menos un hexágono; 38 no tienen ninguno.** Mediana
  de 3 hexágonos por colonia, y 50 con exactamente uno.
- Las 38 vacías son las diminutas —área mediana 0.041 km² contra 0.105 de una
  celda res 9, la mayor 0.145, y entre todas 1.8 km²— y **no se listan**: un
  selector que ofrece una colonia y devuelve un mapa vacío es peor que uno que
  no la ofrece.

`hex_colonias.parquet` (`hex_id`, `cve`, `colonia`) es archivo aparte a
propósito: no es columna de `gam_hexes.parquet` ni entra a `SOURCE_FILES`,
porque no es variable del score y ahí adentro `99_score.py` intentaría
normalizar una etiqueta. Lo lee solo el dashboard, que sin ese archivo funciona
igual y lo dice en la barra lateral.

**Lo que este filtro no resuelve.** Con 3 hexágonos por colonia mediana sirve
para "estas cinco colonias" y se queda corto para "dentro de esta colonia, cuál
esquina". Bajar a res 10 daría más alfileres, no más conocimiento: el piso del
AGEB y el tau de 300 m no se mueven, así que los hijos heredarían valores casi
idénticos al del hexágono padre. Esa es una decisión de campo, no de dato.

## Dónde los números NO son confiables

Esto importa más que el score. Está también en el README, y conviene releerlo
antes de sacar conclusiones del mapa.

- **Cuautepec sigue subrepresentado, pero ya no invisible.** Solo el Metro
  publica afluencia por estación; Metrobús, Cablebús, Tren Ligero y Trolebús
  solo dan totales por línea, y no se repartió el total entre estaciones a
  propósito: parecería dato y sería suposición. `presencia_transporte` tapa la
  parte que sí se puede tapar sin inventar nada — que la estación existe. Los
  91 hexágonos del corredor del Cablebús Línea 1 tenían `flujo_transporte`
  exactamente cero y un rank medio de 454.6 de 724; ahora quedan en 376.0.
  **Ninguno entra al top 100**: el mejor queda en el puesto 219. La variable
  dice que hay estación, no cuánta gente la usa.
- **Los bordes de GAM ya no salen bajos en DENUE** (arreglado el 2026-08-23,
  ver abajo). Quedan dos restos. Uno: DENUE se baja por entidad completa, así
  que si el área de estudio tocara Hidalgo habría que sumar esa entidad a
  `DENUE_PARTES`. Dos, y sin medir: **OSM se pide con el bounding box exacto
  del polígono de GAM, sin margen** (`scripts/04_osm.py:55-57`), así que
  `atractores_osm` y `accesibilidad_peatonal` conservan una versión suave del
  mismo bug —un parque a 300 m del borde norte no existe para el modelo—. El
  arreglo es sumarle 800 m al bbox y volver a correr `04`, con el costo de
  re-bajar los 17.6 MB de la red peatonal.
- **Las distancias son euclidianas.** El Chiquihuite, el Río de los Remedios y la
  autopista México-Pachuca no existen para el modelo, así que los hexágonos
  detrás de ellos salen sobrevalorados.
- **La red de OSM tiene fragmentos sueltos, y por eso el enganche los ignora.**
  El grafo son 112 componentes; la mayor tiene 134,545 de 135,894 nodos y el
  resto son calles reales que nadie unió al resto. `894995b9053ffff` se
  enganchaba a un fragmento de 13 nodos y salía con 648.7 m —el mínimo del
  conjunto, contra una mediana de 24,223 m— cuando un nodo 53 m más lejos daba
  17,579 m; como la normalización es min-max, ese mínimo falso anclaba el piso
  de la columna entera. Ahora `snap_to_nodes` solo considera la componente
  mayor y el piso quedó en 1,056.6 m. La guardia de los 500 m sigue igual.
- **La regla de anidamiento es geométrica y deja huecos.** Una cancha cuyo
  centroide caiga fuera del polígono de su parque, por un contorno mal
  digitalizado, sigue contando doble; un contenedor mapeado como nodo suelto no
  absorbe nada. Ya no se lleva ningún caso de estación: las estaciones salieron
  por completo de `atractores_osm` (ni se piden en la consulta), así que la
  estación **Deportivo 18 de Marzo**, dentro del deportivo homónimo, no
  depende de esta regla para seguir contando — vive en `presencia_transporte`,
  aparte.
- **No hay ground truth.** Esto prioriza dónde mirar, no predice que un negocio
  funcione.

## Trampas conocidas

Cosas que ya costaron caro y conviene no repetir.

**Los datos abiertos mienten en silencio.** El CSV del Metro viene con doble
codificación UTF-8: 52 de 163 estaciones llegaban como `AragÃ³n`, y el join las
perdía sin error. El de DENUE es `latin-1`, no utf-8. El zip de DENUE trae tres
CSV y tomar el primero devolvía el diccionario de datos en vez de los datos —
no por orden alfabético, que iría al revés (`c` < `d`), sino porque el orden lo
manda la estructura interna del zip. **Antes de diseñar sobre una fuente nueva,
ábrela y míralas.**

**Cuidado con las pruebas que pasan por la razón equivocada.** Es *la* trampa
recurrente de este proyecto y ya lleva nueve apariciones. Las primeras tres: una
prueba de encoding que escribía y leía con la misma constante, unas de haversine
que nunca ejercitaban el término del coseno, y una de patrón cuyos nombres
cruzaban por otra alternativa. Después, en el censo, ningún test distinguía
`mean` de `median` porque el fixture tenía dos vecinos simétricos. Y en la rama
de `presencia_transporte`, cuatro más: la frontera del corte a 800 m (todos los
puntos caían lejos), la precedencia cable-sobre-riel (nunca se enfrentaban),
una estación de riel sola (el fixture la colocaba encima de una de cable y el
máximo lo enmascaraba), y `place=square` como atractor (nadie lo probaba solo).
La novena es la misma frontera del corte, pero en `accumulate_decay`: se anotó
como deuda al taparla en `nearest_decay` y se cerró en su propia rama.

El patrón es siempre el mismo: **el fixture hace coincidir el camino correcto
con el incorrecto**, así que la prueba no puede distinguirlos. En los nueve
casos la implementación estaba bien; lo que faltaba era el test que la anclara.

Por eso las revisiones de este repo se hacen **mutando el código real** y
confirmando que la suite se pone roja, no leyendo el diff. Leer no cazó ninguno
de los nueve; mutar los cazó todos.

**Un archivo partido en dos no se parte por donde crees.** El DENUE del Estado
de México viene en `denue_15_1_csv.zip` y `denue_15_2_csv.zip`, y el corte **no
es por municipio**: los dos traen los mismos 125 municipios. Quedarse con el
primero pierde ~40% de cada municipio fronterizo —13,701 de los 33,393 de
Tlalnepantla— sin un solo error, sólo con números más chicos. Es la misma
familia que el diccionario de datos dentro del zip de DENUE: la estructura del
archivo no se adivina, se mira.

**El `.pyc` viejo puede fingir que una mutación sobrevivió.** Python invalida
el bytecode comparando el mtime del fuente **en segundos enteros**, así que dos
ediciones dentro del mismo segundo —mutar y restaurar en el mismo comando, que
es justo como se revisan estas ramas— pueden hacer que corra el código anterior.
Ya pasó en la rama de colonias: una mutación salió "sobrevivida" con la suite en
verde y era bytecode rancio. Corre las mutaciones con `PYTHONDONTWRITEBYTECODE=1`.
Y ojo con el error simétrico, peor: una restauración que parece dejar la suite en
rojo hace creer que el código bueno está roto.

**pyarrow está fijado en `<22` y no es capricho.** La 25.0.0 revienta el
dashboard con SIGSEGV dentro del hilo de scripts de Streamlit, de forma
intermitente: 3 de cada 5 arranques. El comentario en `pyproject.toml` explica
cómo re-evaluarlo — 6+ corridas seguidas sin código 139. **Una sola corrida no
prueba nada con un fallo intermitente**, que es la trampa que costó cinco
diagnósticos equivocados.

**No mandes scripts largos a background.** Cuatro agentes ya perdieron su trabajo
así: el proceso muere con su padre. `03_denue.py` tarda un rato (126 MB de
descarga en tres zips, 700 MB de CSV extraídos) y hay que correrlo en primer
plano. Le pasó otra vez a `04_osm.py`: un timeout de shell de 600 s movió la
corrida a segundo plano y el proceso murió con ella. La descarga de la red
peatonal (17.6 MB de JSON) sí alcanzó a completarse y quedó en caché antes de
morir, así que la siguiente corrida no la repitió; la de atractores (mucho más
chica) se bajó aparte, como comando propio, y el resto del pipeline corrió en
un tercer paso ya con las dos cachés en disco.

**El censo AGEB trae dos trampas propias:**

1. **Vivienda colectiva.** El AGEB `0154` tiene `VIVPAR_HAB == 0` con 8,184
   habitantes: el `0/0` que resulta al calcular un promedio por vivienda lo
   resuelve numpy con `nan` y un warning, no con una excepción, y el
   `GRAPROES = 0.00` que queda ahí parece un dato válido sin serlo.
2. **AGEB de población cero.** `0718` y `1078` tienen `POBTOT = 0`. Un
   hexágono cuyo único AGEB es uno de esos no tiene NSE propio **ni
   población que ponderar**, y el promedio pesado por población da `0/0`. Es
   el caso que bloqueó la primera corrida real de esta fuente.

## Convenciones

- Identificadores en inglés; docstrings, comentarios y salida de scripts en
  español.
- Commits **sin** trailer de coautoría y sin footer de Claude Code.
- Las fuentes emiten valores **crudos**; la normalización ocurre una sola vez, en
  `99_score.py`.
- Cada fuente es dueña exclusiva de sus columnas. Agregar una es un módulo nuevo
  en `src/rtgam/sources/`, un script numerado y una línea en `SOURCE_FILES`. Se
  verificó con DENUE: entró sin tocar una sola línea de código existente.
- Una etiqueta no es una variable. `hex_colonias.parquet` tiene módulo y script
  numerado como una fuente, pero **no** entra a `SOURCE_FILES`: `99_score.py`
  intentaría normalizar un nombre de colonia. Lo lee solo el dashboard.
- Validar **antes** de escribir caché, nunca al revés. Se corrigió cuatro veces
  por no hacerlo. La comprobación vive en `src/rtgam/overpass.py`, fuera de las
  fuentes, precisamente porque tenerla en una sola dejó a la otra arrastrando la
  misma falla durante toda su vida. También se valida **al leer** la caché: un
  payload malo pudo quedar en disco de una versión anterior del código.
- El kernel es fijo: `exp(-d/300)`, cero pasados 800 m. Dos primitivas lo
  aplican y **no son intercambiables**: `accumulate_decay` **suma** sobre todos
  los puntos —cuenta cosas, y por eso pondera— y `nearest_decay` toma el
  **máximo** —mide cercanía al más cercano, no lleva columna de valor, y es
  inmune por construcción a que OSM parta un mismo sitio en varios nodos—.
  Elegir la equivocada no falla: da un número plausible.

## Documentos

Specs y planes en `docs/superpowers/`. Los specs registran cada decisión con su
alternativa descartada y el dato que la sostiene, que es lo útil cuando alguien
pregunte por qué el score no pondera por tamaño de establecimiento (respuesta:
concentraría 26.8% de la variable en Costco y Liverpool, que son destinos de
coche).
