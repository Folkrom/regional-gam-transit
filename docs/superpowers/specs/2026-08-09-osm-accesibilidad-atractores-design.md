# Fuente OSM: accesibilidad peatonal y atractores de espacio público

**Fecha:** 2026-08-09
**Estado:** aprobado
**Alcance:** tercera fuente del score de GAM, después de transporte y DENUE

## Problema

El score cubre 706 de 724 hexágonos, pero las dos variables que lo llenan miden
lo mismo desde dos ángulos: cuánta gente pasa y cuántos negocios hay. Ninguna
mide la **calle**.

Esta fuente responde la pregunta que abrió esta línea de trabajo — en qué calles
camina más gente — y aporta las dos columnas que faltan del lado de OSM:
`accesibilidad_peatonal` y `atractores_osm`.

## Restricción heredada

Solo datos abiertos y gratuitos. OSM vía Overpass cumple: sin API key, sin
registro.

## Contexto que cambió la recomendación del handoff

El handoff proponía **centralidad de intermediación global** con `osmnx`. Medido,
esa ruta tiene dos problemas.

**Costo.** Overpass reporta **33,449 vías caminables** en el bbox de GAM
(19.4448,-99.1770,19.5928,-99.0509; el bbox incluye pedazos de Azcapotzalco,
Cuauhtémoc y Ecatepec, GAM sola ronda las 20 mil). El grafo resultante es del
orden de 20 mil intersecciones y 50 mil aristas. Betweenness exacta con
`networkx` es O(V·E): un Dijkstra por nodo. Estimación, no medición: **horas**.
Choca de frente con la regla del proyecto de no mandar scripts largos a
background.

**Sesgo de borde, otra vez.** Betweenness global sobre un grafo recortado en el
límite de GAM infla las rutas que cruzan el corte y hunde los corredores reales
que continúan afuera. Es el mismo defecto ya documentado para DENUE, y aquí sería
peor porque afecta la topología, no solo el conteo.

## Decisiones de diseño

### 1. `accesibilidad_peatonal` es alcance a 800 m por la red

**Decisión:** desde el centroide de cada hexágono, **metros de calle caminable
alcanzables recorriendo 800 m por la red**.

Es *reach centrality* de Urban Network Analysis (Sevtsuk), validada contra volumen
peatonal. Se interpreta directo: cuánta traza caminable hay a diez minutos.

El costo se desploma por una razón estructural: hay **724 orígenes**, no 20 mil.
Cada Dijkstra va acotado a 800 m, así que explora unos pocos miles de nodos. 724
corridas son segundos.

**Alternativa descartada:** betweenness aproximada con k pivotes al azar. Mide
movimiento de paso, que es lo que la literatura de space syntax liga a volumen
peatonal, pero cuesta minutos por corrida, necesita semilla fija porque los
pivotes son aleatorios, y arrastra el sesgo de borde.

**Alternativa descartada:** densidad de intersecciones por hexágono. Prácticamente
gratis, y en el metaanálisis de Ewing y Cervero es el correlato construido más
fuerte con caminar. Se descarta porque no distingue una retícula conectada de una
encerrada entre una barrera y una vía rápida — que es justo la geografía de GAM.

### 2. Sin simplificación topológica del grafo

Como solo hay 724 orígenes, no hace falta detectar intersecciones ni colapsar
nodos de paso.

**Decisión:** cada nodo OSM es un nodo del grafo; cada par consecutivo de nodos
dentro de una vía es una arista con peso `haversine_m`. Los nodos compartidos
entre vías conectan el grafo solos, porque OSM reutiliza el mismo id.

Esto borra la parte del trabajo donde este proyecto ha parido números malos en
silencio: no hay heurística de intersección que equivocar. El grafo queda en unos
200 mil nodos, y a Dijkstra acotado le da igual.

**Alcance** = suma de los pesos de las aristas con **ambos** extremos dentro del
corte. Ambos, no uno: una arista de 400 m que sale del radio no cuenta como calle
alcanzada.

### 3. Primera medida en distancia de red

Vale más que la variable misma. Hasta hoy todo el proyecto mide en línea recta, y
está documentado como limitación: el Chiquihuite, el Río de los Remedios y la
autopista México-Pachuca no existen para el modelo.

El alcance por la red sí los ve. Un hexágono al otro lado del río solo llega por
los puentes, y su alcance baja solo.

### 4. Enganche del centroide al grafo, con guardia

El centroide de un hexágono no cae sobre un nodo. Se pega al nodo más cercano.

**Decisión:** si el nodo más cercano queda a más de **500 m**, el alcance es 0, el
hexágono se cuenta y se imprime para revisión humana. No se pega a la fuerza.

Un centroide a más de 500 m de cualquier calle está en el cerro o en el relleno;
engancharlo al otro lado de una barrera fabricaría accesibilidad donde no hay.

**Costo de memoria, declarado por adelantado.** Buscar el nodo más cercano son 200
mil nodos × 724 centroides. En una sola matriz son ~1.2 GB, y `haversine_m`
mantiene unas seis vivas a la vez — unos 7 GB. Se calcula **por bloques de
hexágonos**. La cifra viene de la medición que ya se hizo en DENUE, donde el pico
real fue 1.1 GB contra los 198 MB que se habían estimado a ojo.

### 5. `atractores_osm` es espacio público y transporte

La frontera con DENUE tiene que ser explícita o las dos columnas cuentan lo mismo:
**DENUE es comercio privado; OSM es lo que el registro de negocios no ve.**

**Decisión:** entran parques, jardines, canchas, juegos infantiles, deportivos,
mercados públicos, plazas y paradas de transporte.

**Alternativa descartada:** todo `amenity`/`shop`/`leisure` de OSM. Más cobertura,
pero se traslapa fuerte con DENUE: el mismo comercio contado dos veces en dos
columnas con pesos distintos. El spec de DENUE ya rechazó el doble conteo por esto.

### 6. Fuera: suelo de conservación

**Decisión:** se excluyen `natural=wood`, `boundary=protected_area` y
`leisure=nature_reserve`.

La Sierra de Guadalupe es ladera, no plaza. Meterla pondría un atractor enorme
sobre los hexágonos con menos banqueta de toda la alcaldía.

### 7. Conteo simple, mismo kernel

**Decisión:** cada atractor vale **1.0 en su centroide**, con el kernel de siempre:
`exp(-d/300)`, cero pasados 800 m, vía `accumulate_decay`.

Idéntico al precedente de DENUE, donde ponderar por tamaño resultó
contraproducente.

### 8. El doble conteo con `flujo_transporte` es deliberado

Una estación del Metro suma en las dos columnas: afluencia en una, presencia en la
otra.

**Decisión:** se acepta. Son señales distintas — cuánta gente usa la estación
contra que la estación exista — con pesos muy distintos (0.35 contra 0.05).

Y es el mecanismo que destapa **Cuautepec**, el punto ciego documentado del
proyecto: el Cablebús Línea 1 corre entero dentro de GAM, no publica afluencia por
estación y hoy aporta cero. Sus coordenadas sí existen. La presencia las usa.

La propiedad única sigue rigiendo *dentro* de cada fuente, como en DENUE. Entre
fuentes, transporte es dueño del volumen y OSM de la presencia.

## Fuente de datos

| | |
|---|---|
| Endpoint | `https://overpass-api.de/api/interpreter`, con espejo `https://overpass.kumi.systems/api/interpreter` |
| API key | ninguna |
| bbox | `19.4448,-99.1770,19.5928,-99.0509`, derivado de `data/raw/gam_boundary.geojson` |
| Caché | `data/raw/osm_red_peatonal.json` y `data/raw/osm_atractores.json` |

El bbox se usa **con el buffer que ya trae**: es el rectángulo envolvente de GAM,
así que incluye traza de las alcaldías vecinas. Eso es deseable, no un descuido —
la red no se corta en el límite político y el alcance de los hexágonos de orilla
sale correcto.

### La consulta pide `nwr`, no `way`

Medido hoy: el **Bosque de San Juan de Aragón existe solo como `relation`**. Una
consulta de puros `way` lo pierde sin lanzar nada. En el bbox hay 6 relations y 96
nodos sueltos además de los 1,679 polígonos.

**La consulta de atractores usa `nwr` con `out tags center`.** Overpass devuelve el
centroide ya calculado para ways y relations, y las coordenadas propias para nodos.

Vías caminables: se excluyen `motorway`, `trunk`, sus enlaces, `construction`,
`proposed` y `raceway`.

## Arquitectura

Módulo `src/rtgam/sources/osm.py` y script `scripts/04_osm.py`, mismo contrato que
las dos fuentes anteriores:

```python
def to_hex_features(gam_hexes: pd.DataFrame, alcance: pd.Series, atractores: pd.DataFrame) -> pd.DataFrame:
    """Indexado por hex_id, con SOLO las columnas que esta fuente posee."""
```

Salida: `data/processed/osm.parquet` con `accesibilidad_peatonal` y
`atractores_osm`, en valores **crudos**. La normalización sigue ocurriendo una sola
vez, en `99_score.py`.

### El seam ya está listo

`99_score.py` lista `osm.parquet` en `SOURCE_FILES` y `config/weights.yaml` ya tiene
`accesibilidad_peatonal: 0.10` y `atractores_osm: 0.05`. Aparece el archivo y entra
al score **sin tocar código existente**, como se verificó con DENUE.

### Dependencias

Una nueva: **`networkx`**, Python puro, sin extensiones compiladas.

`osmnx` se descarta pese a hacer el armado del grafo mejor: arrastra `geopandas`,
`scikit-learn`, `pyproj` y `rtree`, y su valor agregado es sobre todo proyección y
simplificación topológica, que aquí no se usan. Además cachea a su manera, en
paralelo al patrón del proyecto. `geopandas` sigue reservado para el censo AGEB.

## Manejo de errores

**Overpass responde HTTP 200 con cuerpo HTML de error.** Ocurrió tres veces
mientras se escribía este spec: `Dispatcher_Client::request_read_and_idx::timeout`
llega con status 200. Un `raise_for_status()` no lo detecta.

De ahí las reglas:

- **Validar que el cuerpo parsea como JSON y trae `elements` ANTES de escribir la
  caché.** Nunca al revés. Ya corregido tres veces en este proyecto por no hacerlo.
- Un cuerpo que no parsea lanza `ValueError` nombrando el endpoint y el remedio.
- `User-Agent` obligatorio, de `src/rtgam/__init__.py`. Sin él, Overpass responde
  406 — ya medido contra el servidor real.
- Reintento con el espejo alterno antes de rendirse.
- Caché existente se reutiliza; flag `--force` para re-descargar.

## Validación de la salida real

- `accesibilidad_peatonal` debe cubrir **casi los 724 hexágonos**. Si cubre poco,
  el filtro de vías o el enganche fallaron.
- **El Bosque de San Juan de Aragón debe aparecer entre los atractores.** Es la
  guardia contra la regresión de consultar solo `way`.
- El script imprime, para revisión humana: nodos y aristas del grafo, atractores por
  tipo, hexágonos sin enganche (nodo más cercano a más de 500 m), y el top 5 de cada
  variable.

## Pruebas

pytest, fixtures sintéticos, sin red.

- **Construcción del grafo:** una vía de 3 nodos produce 2 aristas, con las
  longitudes de haversine correctas.
- **Alcance:** grafo sintético con respuesta conocida a mano.
- **Corte:** un nodo a 900 m por la red queda fuera; uno a 700 m entra.
- **Arista a medias:** una arista con un extremo dentro y otro fuera del corte no
  suma.
- **Relations:** fixture con un elemento `relation` que trae `center`. Falla si el
  código solo maneja `way`.
- **Cuerpo HTML con status 200:** debe lanzar, y **no** debe dejar caché escrita.
- **Enganche:** un centroide a 600 m del nodo más cercano da alcance 0 y se reporta.
- **Contrato:** `to_hex_features` devuelve exactamente dos columnas, sin NaN,
  indexado como el grid.

Las pruebas de relations y de cuerpo HTML existen por lo que costaron sus gemelas:
el mojibake del CSV del Metro y el zip de DENUE cuyo primer archivo alfabético era
el diccionario de datos. Las dos fallaron igual — número equivocado, nada lanzado.

## Criterio de éxito

`osm.parquet` producido, las dos variables entrando al score sin tocar
`99_score.py`, y `accesibilidad_peatonal` con señal en casi los 724 hexágonos.

## Dónde los números NO van a ser confiables

- **Polígonos grandes representados por su centroide.** Medido: la extensión mediana
  es de 50 m y solo **43 de 1,679 polígonos pasan de 400 m**. Pero el Bosque de San
  Juan de Aragón mide ~1.3 km, así que sus orillas —por donde la gente entra— caen
  fuera del corte de 800 m desde su centroide, y sale subestimado. Muestrear el
  perímetro serviría al 2.6% de los casos y agrega una rama; se prefiere la
  limitación documentada.
- **Los atractores siguen en distancia euclidiana.** Solo `accesibilidad_peatonal`
  usa la red, por consistencia con transporte y DENUE. La contradicción es
  deliberada y vale nombrarla.
- **OSM es colaborativo.** La cobertura es desigual, y una colonia poco mapeada sale
  baja por falta de mapeadores, no de banquetas. Al revés que DENUE, donde el censo
  económico cubre parejo.
- **El alcance mide oferta de calle, no gente.** Una traza densa e industrial puntúa
  alto sin peatón. Por eso pesa 0.10 y no más.

## Fuera de alcance

- Censo AGEB: densidad de población y perfil socioeconómico. Es la última fuente
  pendiente y la primera que necesita `geopandas`.
- Betweenness, exacta o aproximada.
- Muestreo del perímetro de polígonos grandes.
- Distancia de red para los atractores.
- Pendiente del terreno, que en las laderas de GAM importa para caminar.
