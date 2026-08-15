# Handoff — estado al 2026-08-14

Dónde quedó el proyecto y qué conviene saber antes de tocar nada.

## Estado

`main` en `f9de6f0`, con las ocho variables integradas. 247 pruebas pasando en
1 s, sin red. El pipeline completo corre de punta a punta y el dashboard
levanta.

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

Queda una deuda anotada y sin hacer, del tipo caro de este repo — el número
equivocado que no lanza nada:

- **`accumulate_decay` no tiene cubierta la frontera exacta del corte.** Ningún
  test pone un punto a exactamente `DECAY_CUTOFF_M`, así que mutar `<=` por `<`
  sobrevive con la suite entera en verde. Se detectó al arreglar el mismo hueco
  en `nearest_decay`, y se dejó fuera de aquella rama a propósito: es
  preexistente y afecta a cuatro variables, no solo a la que se estaba
  agregando. Merece su propia rama.

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
- **Los bordes de GAM salen bajos.** DENUE se filtra por alcaldía, no por
  geometría, así que negocios a menos de 800 m de un hexágono no cuentan si están
  del otro lado del límite. Medido: 76 de 724 hexágonos pierden más de un
  atractor, el peor subestimado 7.5×. No se arregla con este archivo, que solo
  cubre CDMX.
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
de los ocho; mutar los cazó todos.

**pyarrow está fijado en `<22` y no es capricho.** La 25.0.0 revienta el
dashboard con SIGSEGV dentro del hilo de scripts de Streamlit, de forma
intermitente: 3 de cada 5 arranques. El comentario en `pyproject.toml` explica
cómo re-evaluarlo — 6+ corridas seguidas sin código 139. **Una sola corrida no
prueba nada con un fallo intermitente**, que es la trampa que costó cinco
diagnósticos equivocados.

**No mandes scripts largos a background.** Cuatro agentes ya perdieron su trabajo
así: el proceso muere con su padre. `03_denue.py` tarda varios minutos (45 MB de
descarga, 260 MB de CSV, ~1.1 GB de pico de memoria) y hay que correrlo en primer
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
