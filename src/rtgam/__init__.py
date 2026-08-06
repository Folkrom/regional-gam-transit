"""Analisis de flujo peatonal para ubicacion de cafeteria en Gustavo A. Madero."""

# Nominatim y Overpass rechazan peticiones sin User-Agent identificable. Es
# politica de uso de ambos, no un detalle opcional: Overpass responde 406 Not
# Acceptable sin el. Vive aqui y no en cada modulo para no duplicar el literal.
USER_AGENT = "regional-transit-gam/0.1 (analisis academico de ubicacion)"
