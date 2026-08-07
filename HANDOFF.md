# Handoff — estado al 2026-08-06

Dónde quedó el proyecto y qué conviene saber antes de tocar nada.

## Estado

`main` en `de8974e`, con la rebanada vertical y la fuente DENUE ya integradas.
104 pruebas pasando en 0.6 s, sin red. El pipeline completo corre de punta a punta
y el dashboard levanta.

**Cobertura del score: 706 de 724 hexágonos.** Arrancó en 218 con solo la fuente
de transporte; DENUE cubrió el 70% de GAM que estaba invisible.

| variable | fuente | estado |
|---|---|---|
| `flujo_transporte` | afluencia del Metro | ✅ |
| `competencia` | DENUE, SCIAN 722515 filtrado | ✅ |
| `atractores_denue` | DENUE, sectores 46/72/61/62/71 | ✅ |
| `accesibilidad_peatonal` | OSM | ❌ falta |
| `atractores_osm` | OSM | ❌ falta |
| `densidad_pob` | censo AGEB | ❌ falta |
| `nivel_socioeconomico` | censo AGEB | ❌ falta |

Score máximo actual: `0.3883`. Los hexágonos top caen alrededor de Indios Verdes,
Martín Carrera y La Raza.

## Cómo correrlo

```bash
uv sync --extra dev
uv run pytest -q
uv run python scripts/01_build_grid.py
uv run python scripts/02_transporte.py
uv run python scripts/03_denue.py
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

**OSM es la fuente recomendada**, y responde literal la pregunta que abrió esta
línea de trabajo: en qué calles camina más gente.

La técnica es centralidad de intermediación (*betweenness*) sobre la red peatonal
descargada con `osmnx`: qué tramos están en más rutas cortas entre puntos. La
literatura de *space syntax* la valida como predictor de volumen peatonal real, y
cubre el 100% del territorio. Aporta dos columnas: `accesibilidad_peatonal` y
`atractores_osm`. Es la única fuente que agrega dependencias nuevas
(`osmnx` + `networkx`).

El censo AGEB es la otra pendiente. Aporta `densidad_pob` y
`nivel_socioeconomico`, y es la primera que necesita `geopandas`, porque hay que
repartir población de polígonos AGEB a hexágonos por intersección de área.

Hay una tercera idea barata que quedó anotada y sin hacer: usar **presencia** de
estación como variable separada de **volumen**. Ya están descargadas las 117
estaciones de OSM y solo 43 cruzaron con afluencia; las otras 74 —Cablebús,
Metrobús, trolebús— tienen coordenadas aunque no tengamos sus números. Taparía
el punto ciego de Cuautepec.

## Dónde los números NO son confiables

Esto importa más que el score. Está también en el README, y conviene releerlo
antes de sacar conclusiones del mapa.

- **Cuautepec sale subrepresentado.** Solo el Metro publica afluencia por
  estación; Metrobús, Cablebús, Tren Ligero y Trolebús solo dan totales por
  línea. El Cablebús Línea 1 corre entero dentro de GAM y aporta cero. No se
  repartió el total de línea entre sus estaciones a propósito: parecería dato y
  sería suposición.
- **Los bordes de GAM salen bajos.** DENUE se filtra por alcaldía, no por
  geometría, así que negocios a menos de 800 m de un hexágono no cuentan si están
  del otro lado del límite. Medido: 76 de 724 hexágonos pierden más de un
  atractor, el peor subestimado 7.5×. No se arregla con este archivo, que solo
  cubre CDMX.
- **Las distancias son euclidianas.** El Chiquihuite, el Río de los Remedios y la
  autopista México-Pachuca no existen para el modelo, así que los hexágonos
  detrás de ellos salen sobrevalorados.
- **No hay ground truth.** Esto prioriza dónde mirar, no predice que un negocio
  funcione.

## Trampas conocidas

Cosas que ya costaron caro y conviene no repetir.

**Los datos abiertos mienten en silencio.** El CSV del Metro viene con doble
codificación UTF-8: 52 de 163 estaciones llegaban como `AragÃ³n`, y el join las
perdía sin error. El de DENUE es `latin-1`, no utf-8. El zip de DENUE trae tres
CSV y `diccionario_de_datos/` va antes que `conjunto_de_datos/` alfabéticamente,
así que tomar el primero devolvía el diccionario. **Antes de diseñar sobre una
fuente nueva, ábrela y míralas.**

**Cuidado con las pruebas que pasan por la razón equivocada.** Pasó tres veces:
una prueba de encoding que escribía y leía con la misma constante, unas pruebas
de haversine que nunca ejercitaban el término del coseno, y una prueba de patrón
cuyos nombres cruzaban por otra alternativa. Si una prueba fija algo, rómpelo a
propósito y confirma que falla.

**pyarrow está fijado en `<22` y no es capricho.** La 25.0.0 revienta el
dashboard con SIGSEGV dentro del hilo de scripts de Streamlit, de forma
intermitente: 3 de cada 5 arranques. El comentario en `pyproject.toml` explica
cómo re-evaluarlo — 6+ corridas seguidas sin código 139. **Una sola corrida no
prueba nada con un fallo intermitente**, que es la trampa que costó cinco
diagnósticos equivocados.

**No mandes scripts largos a background.** Tres agentes perdieron su trabajo así:
el proceso muere con su padre. `03_denue.py` tarda varios minutos (45 MB de
descarga, 260 MB de CSV, ~1.1 GB de pico de memoria) y hay que correrlo en primer
plano.

## Convenciones

- Identificadores en inglés; docstrings, comentarios y salida de scripts en
  español.
- Commits **sin** trailer de coautoría y sin footer de Claude Code.
- Las fuentes emiten valores **crudos**; la normalización ocurre una sola vez, en
  `99_score.py`.
- Cada fuente es dueña exclusiva de sus columnas. Agregar una es un módulo nuevo
  en `src/rtgam/sources/`, un script numerado y una línea en `SOURCE_FILES`. Se
  verificó con DENUE: entró sin tocar una sola línea de código existente.
- Validar **antes** de escribir caché, nunca al revés. Se corrigió tres veces por
  no hacerlo.
- El kernel es fijo: `exp(-d/300)`, cero pasados 800 m.

## Documentos

Specs y planes en `docs/superpowers/`. Los specs registran cada decisión con su
alternativa descartada y el dato que la sostiene, que es lo útil cuando alguien
pregunte por qué el score no pondera por tamaño de establecimiento (respuesta:
concentraría 26.8% de la variable en Costco y Liverpool, que son destinos de
coche).
