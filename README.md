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
uv run python scripts/99_score.py
uv run streamlit run app/dashboard.py
```

## Revisión manual

Tras la primera corrida de `02`, revisar `data/interim/station_name_map.csv`.
Solo se cruzan automáticamente los nombres idénticos; el resto trae
candidatos para llenar a mano.

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
- De seis variables previstas solo hay datos de una. DENUE, OSM y censo
  faltan.
- No hay ground truth: esto prioriza dónde mirar, no predice que un negocio
  funcione.
