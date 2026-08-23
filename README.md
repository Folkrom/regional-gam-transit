# regional-transit

## Qué es

Análisis de flujo peatonal para ubicar una cafetería de especialidad en la
alcaldía Gustavo A. Madero, CDMX. Rejilla H3 resolución 9, 724 hexágonos.

## Requisitos

Python 3.12 y `uv`.

```bash
uv sync --extra dev
```

## Datos que hay que bajar a mano

`data/raw/afluencia_metro.csv`, la afluencia diaria del Metro por estación,
del portal de datos abiertos de la CDMX en `https://datos.cdmx.gob.mx`
(buscar "afluencia"). Columnas esperadas:

```
fecha, anio, mes, linea, estacion, afluencia
```

Todo lo demás se descarga solo.

## Orden de ejecución

```bash
uv run python scripts/01_build_grid.py
uv run python scripts/02_transporte.py
uv run python scripts/03_denue.py
uv run python scripts/04_osm.py
uv run python scripts/05_censo.py
uv run python scripts/06_colonias.py
uv run python scripts/99_score.py
uv run streamlit run app/dashboard.py
```

## Revisión manual

Tras la primera corrida de `02`, revisar `data/interim/station_name_map.csv`.
Solo se cruzan automáticamente los nombres idénticos; el resto trae
candidatos para llenar a mano.

Tras la primera corrida de `03`, revisar `data/interim/competencia_denue.csv`.
La lista de cafeterías se arma con un patrón de nombres sobre el código SCIAN
722515, que es criterio editorial y no un hecho: ese código mezcla cafeterías
con paleterías y puestos de antojitos.

## Filtro por colonia

`06_colonias.py` es opcional y no alimenta el score: baja las colonias del
IECM 2019 del portal de la CDMX y escribe `data/processed/hex_colonias.parquet`
con la colonia de cada hexágono. Con ese archivo presente, el dashboard suma un
multiselect que **esconde** hexágonos; sin él, el dashboard funciona igual y lo
dice en la barra lateral.

Es un filtro de vista: los scores, la escala de color y el `rank` se calculan
siempre contra los 724 hexágonos de toda la alcaldía, así que el puesto 219
sigue siendo el 219 con cualquier filtro puesto. Re-normalizar dentro del
subconjunto se descartó a propósito: estiraría cada variable a 0-1 dentro de
las colonias elegidas, lo que re-ordena los hexágonos y amplifica ruido al
rango completo.

Las colonias no filtran ninguna fuente, solo los candidatos. Una cafetería a
300 m cruzando la calle compite igual aunque esté en otra colonia.

Granularidad: la colonia mediana de GAM son 3 hexágonos, así que el filtro
sirve para "estas cinco colonias" y se queda corto para "en cuál esquina de
esta colonia". 194 de las 232 colonias tienen al menos un hexágono; las 38
restantes son más chicas que una celda res 9 (0.105 km²) y no se listan. Los
12 hexágonos que no caen en ninguna colonia aparecen como `(sin colonia)`.

## Qué significa el score

Suma ponderada de variables normalizadas a 0-1, sin cota superior, útil solo
para ordenar. Los pesos se ajustan en `config/weights.yaml` y en los sliders
del dashboard.

## Zonas donde los números NO son confiables

- Solo el Metro publica afluencia por estación. Metrobús, Cablebús, Tren
  Ligero y Trolebús solo dan totales por línea. Por eso el transporte entra
  al score con dos variables: `flujo_transporte` (volumen, solo Metro) y
  `presencia_transporte` (cercanía a una estación de riel o cable, que sí
  cubre el Cablebús).
- `presencia_transporte` dice que **existe** una estación, no cuánta gente la
  usa. Un Cablebús con 5,000 pasajeros al día y uno con 50,000 puntúan igual.
- El corredor del Cablebús Línea 1 —91 de los 724 hexágonos, los que tienen
  cerca una estación de clase cable y `flujo_transporte` en cero— tenía un rank
  promedio de 454.6 de 724 antes de esta variable; con ella pasa a 376.0.
  Sube, pero **ninguno de los 91 entra al top 100**: el mejor hexágono del
  corredor queda en el puesto 219. Su `nivel_socioeconomico` medio (0.37)
  sigue por debajo del promedio de GAM (0.44) —eso es un hecho del censo, no
  un artefacto del score—, aunque su `atractores_denue` y `atractores_osm`
  medios salen por *encima* del promedio de GAM: el corredor no está
  comercialmente vacío, solo tiene menos NSE.
- Las distancias son euclidianas y no conocen barreras. El cerro del
  Chiquihuite, el Río de los Remedios y la autopista México-Pachuca hacen
  que los hexágonos detrás de ellas salgan sobrevalorados.
- De las **ocho** variables de `config/weights.yaml` hay datos de las ocho:
  `flujo_transporte`, `presencia_transporte`, `competencia`,
  `atractores_denue`, `accesibilidad_peatonal` (OSM, alcance a 800 m por la
  red), `atractores_osm` (OSM, solo espacio público), `densidad_pob` y
  `nivel_socioeconomico` (las dos últimas del censo AGEB 2020).
- El reparto de `densidad_pob` es por área: supone que la población de un
  AGEB se distribuye pareja dentro de su polígono. Es falso donde hay un
  parque, un panteón o una zona industrial grande: esos hexágonos salen con
  población que en realidad está concentrada al lado.
- El censo es de 2020, seis años atrás.
- El 3.1% de la población de GAM (36,272 de 1,173,351 habitantes) cae fuera
  de la retícula de hexágonos: los AGEB tocan el borde de la alcaldía y
  ceden área —y población— a territorio que la rejilla no cubre.
- `nivel_socioeconomico` es un índice compuesto de tres proxies —internet,
  automóvil, escolaridad—, no un dato del censo ni una medición de ingreso.
  Sirve para ordenar hexágonos entre sí, no para afirmar el nivel de nadie.
- La columna `nivel_socioeconomico` sale escalada 0-1 y no cruda, contra la
  convención del resto de las fuentes.
- Seis hexágonos de 724 no tocan ningún AGEB con nivel socioeconómico
  medido: cinco caen sobre el AGEB `0718`, que tiene población cero, y uno
  sobre el `1928`, confidencial. Su `nivel_socioeconomico` es el promedio
  simple del de sus vecinos inmediatos. Ahí la columna describe al
  vecindario, no a quien ocupa el polígono —que en cinco de los seis casos
  no es nadie—. Su `densidad_pob` sí es la real, cero incluido.
- DENUE se filtra por alcaldía, no por geometría, así que los negocios justo
  afuera del límite de GAM no cuentan aunque estén a menos de 800 m de un
  hexágono. Medido: 76 de los 724 hexágonos pierden más de un atractor y 33
  pierden más del 20% de su valor; el peor caso queda subestimado 7.5 veces.
  Afecta sobre todo el borde sur, contra Cuauhtémoc y Venustiano Carranza.
  Arreglarlo del todo no es posible con este archivo, que solo cubre la CDMX:
  los bordes norte y oriente, contra Tlalnepantla, Ecatepec y Nezahualcóyotl,
  seguirían ciegos.
- Los polígonos grandes de OSM van por su centroide, así que el Bosque de San
  Juan de Aragón (~1.3 km de largo) sale subestimado. Medido sobre la corrida
  vigente (`data/raw/osm_atractores_geom.json`): 56 de los 1,218 atractores
  pasan de 400 m de extensión (diagonal del bounding box). 1,148 de ellos
  tienen polígono; los 70 restantes son nodos sueltos, que no tienen
  extensión que subestimar.
- **Lo anidado ya no cuenta aparte**, pero la regla es geométrica y por lo
  tanto imperfecta. Un atractor cuyo punto cae dentro del polígono de otro
  *estrictamente mayor* se descarta: eso quitó 470 de 1,688 atractores (28%) y
  dejó 1,218. El Deportivo Hermanos Galeana trae 59 atractores mapeados
  aparte —56 canchas, 2 juegos infantiles y un jardín— y contaba 60 veces;
  ahora cuenta una. El Oceanía pasó de 31 a 1. Lo que la
  regla no ve: una cancha cuyo centroide caiga *fuera* del polígono de su
  parque —por un contorno mal digitalizado— sigue contando doble, y un
  contenedor mapeado como nodo suelto no absorbe a nadie, porque un punto no
  contiene nada.
- La estación de Metro **Deportivo 18 de Marzo** cae dentro del polígono del
  deportivo homónimo. Antes de que las estaciones salieran de
  `atractores_osm`, eso la hacía perder su lugar como atractor por la regla
  de anidamiento; ahora ya no aplica: las estaciones ni se piden en la
  consulta de atractores, viven aparte en `presencia_transporte`
  (`nearest_decay`), así que el caso quedó resuelto sin necesitar una
  excepción.
- Los atractores siguen en distancia euclidiana; solo `accesibilidad_peatonal`
  usa la red.
- La red de OSM no es una sola pieza: son 112 componentes, y la mayor tiene
  134,545 de los 135,894 nodos. El resto son calles reales digitalizadas sin
  unirlas a nada. **El enganche solo considera la componente mayor**, porque
  medir alcance sobre un fragmento suelto mide el hueco de OSM y no la
  caminabilidad: antes de esto, `894995b9053ffff` (San Juan de Aragón) se
  enganchaba a un fragmento de 13 nodos y obtenía 648.7 m —el mínimo del
  conjunto, contra una mediana de 24,223 m— cuando un nodo 53 m más lejos daba
  17,579 m. Como la normalización es min-max, ese mínimo falso anclaba el piso
  de la columna entera. El piso real quedó en 1,056.6 m. La guardia de los
  500 m no se relajó: si el nodo más cercano de la componente mayor queda más
  lejos, el hexágono se queda sin enganche.
- OSM es colaborativo y su cobertura es desigual, así que una colonia poco
  mapeada sale baja por falta de mapeadores, no de banquetas.
- No hay ground truth: esto prioriza dónde mirar, no predice que un negocio
  funcione.
