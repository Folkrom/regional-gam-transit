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
  Juan de Aragón (~1.3 km de largo) sale subestimado. Cuántos polígonos pasan
  de 400 m de extensión no se midió sobre la corrida vigente (1,789
  atractores, sin geometría: la consulta pide `out tags center` a propósito,
  para no bajar de más). El único dato disponible es de una extracción aparte
  hecha durante el diseño, con una consulta de puros `way` y `out geom` sobre
  una población distinta de 1,679 polígonos con geometría (sin nodos sueltos
  ni relations): 43 de esos 1,679 pasaban de 400 m. Sirve como orden de
  magnitud de que el problema existe, no como conteo de los 1,789 atractores
  reales de esta corrida.
- Las canchas y juegos dentro de un parque cuentan aparte, así que un
  deportivo con ocho canchas suma nueve atractores. Sobre los 1,789 atractores
  reales de esta corrida (`data/raw/osm_atractores.json`), 663 son `pitch` y
  149 son `playground`: 812 en total, 45.4% del conteo. Cuántos de esos caen
  *dentro* de un parque, jardín o deportivo mayor no se puede recalcular
  contra esta población porque haría falta la geometría de los polígonos
  contenedores, que esta consulta no descarga. El único dato de anidamiento
  que existe es de la misma extracción aparte de 1,679 polígonos con
  geometría mencionada arriba: ahí, 297 (17.7%) de los `pitch`/`playground`
  tenían su centroide dentro de un parque, jardín o deportivo mayor. Es orden
  de magnitud, no una cifra de la corrida actual; no se recalculó, ni se
  extrapoló con una regla de tres, porque no hay geometría con la que
  medirla. Se deja así a propósito —una cancha de barrio sí es un destino
  peatonal real— pero el patrón, cuando existe, significa que la variable
  premia en parte lo finamente que OSM tenga mapeado un sitio, no solo cuánta
  gente lo camina.
- Los atractores siguen en distancia euclidiana; solo `accesibilidad_peatonal`
  usa la red.
- La red de OSM no es una sola pieza: son 112 componentes, y aunque la mayor
  tiene 134,545 de los 135,894 nodos, el resto son calles reales digitalizadas
  sin unirlas al resto. El centroide se engancha al nodo más cercano en línea
  recta, sin mirar en qué componente cae, así que un hexágono junto a uno de
  esos fragmentos sale con un alcance dos órdenes de magnitud por debajo del
  real. En esta corrida le pasa a **1 de los 724**: `894995b9053ffff` (San Juan
  de Aragón) se engancha a un fragmento de 13 nodos y obtiene 648.7 m, el
  mínimo del conjunto, contra una mediana de 24,223 m. Y no afecta solo a ese
  hexágono: la normalización es min-max, así que ese mínimo falso ancla el piso
  de toda la columna. La regla de enganche se dejó como está —es la
  especificada—, pero `scripts/04_osm.py` ahora imprime cuántos hexágonos
  quedaron fuera de la componente mayor y con qué tamaño de componente, para
  que la condición no pase en silencio.
- OSM es colaborativo y su cobertura es desigual, así que una colonia poco
  mapeada sale baja por falta de mapeadores, no de banquetas.
- No hay ground truth: esto prioriza dónde mirar, no predice que un negocio
  funcione.
