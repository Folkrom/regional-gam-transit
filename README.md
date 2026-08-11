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

## Qué significa el score

Suma ponderada de variables normalizadas a 0-1, sin cota superior, útil solo
para ordenar. Los pesos se ajustan en `config/weights.yaml` y en los sliders
del dashboard.

## Zonas donde los números NO son confiables

- Solo el Metro publica afluencia por estación. Metrobús, Cablebús, Tren
  Ligero y Trolebús solo dan totales por línea. El Cablebús Línea 1 corre
  entero dentro de GAM y sirve a Cuautepec, así que ese corredor aparece con
  menos flujo del que realmente tiene.
- Las distancias son euclidianas y no conocen barreras. El cerro del
  Chiquihuite, el Río de los Remedios y la autopista México-Pachuca hacen
  que los hexágonos detrás de ellas salgan sobrevalorados.
- De las **siete** variables de `config/weights.yaml` hay datos de cinco:
  `flujo_transporte`, `competencia`, `atractores_denue`,
  `accesibilidad_peatonal` (OSM, alcance a 800 m por la red) y
  `atractores_osm` (OSM, espacio publico y transporte). Faltan dos:
  `densidad_pob` y `nivel_socioeconomico` (los aporta el censo).
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
  vigente (`data/raw/osm_atractores_geom.json`): 39 de los 1,300 atractores
  pasan de 400 m de extensión. 1,181 de ellos tienen polígono; los demás son
  nodos sueltos, que no tienen extensión que subestimar.
- **Lo anidado ya no cuenta aparte**, pero la regla es geométrica y por lo
  tanto imperfecta. Un atractor cuyo punto cae dentro del polígono de otro
  *estrictamente mayor* se descarta: eso quitó 499 de 1,776 atractores (28%) y
  dejó 1,300. El Deportivo Hermanos Galeana contaba 59 veces (58 canchas
  mapeadas aparte) y ahora cuenta una; el Oceanía pasó de 31 a 1. Lo que la
  regla no ve: una cancha cuyo centroide caiga *fuera* del polígono de su
  parque —por un contorno mal digitalizado— sigue contando doble, y un
  contenedor mapeado como nodo suelto no absorbe a nadie, porque un punto no
  contiene nada.
- La regla se lleva un caso que no es subdivisión: la estación de Metro
  **Deportivo 18 de Marzo** cae dentro del polígono del deportivo homónimo y
  deja de contar como atractor. Es la única estación de GAM en esa situación.
  Su afluencia sigue contando en `flujo_transporte`, así que el hexágono no
  queda ciego; hacerle una excepción a las estaciones costaba más que el caso.
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
