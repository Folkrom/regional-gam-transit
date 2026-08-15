"""Lo que las dos fuentes que hablan con Overpass comparten.

Vive aparte de las fuentes porque no es de ninguna: es una propiedad del
servidor, y las dos que lo consultan —transporte.py y osm.py— tienen que
tratarlo igual. Cuando esta comprobacion existia en una sola de las dos, la
otra arrastro la misma falla durante toda su vida.
"""


def validate_payload(payload: dict) -> dict:
    """Comprueba que una respuesta de Overpass sirve, antes de cachearla.

    Overpass saturado responde HTTP 200 de dos maneras inservibles: con un
    cuerpo HTML, que revienta al parsear, y con JSON valido que trae `elements`
    vacio y el error dentro de `remark`. La segunda pasa cualquier
    raise_for_status y cualquier json(), asi que hay que mirarla a mano.
    """
    if not isinstance(payload, dict) or "elements" not in payload:
        raise ValueError(
            "La respuesta de Overpass no trae 'elements'. No es una respuesta "
            "util y no se va a cachear."
        )

    remark = payload.get("remark", "")
    if remark:
        raise ValueError(
            f"Overpass respondio 200 pero con un remark de error: {remark}. "
            f"El servidor esta saturado; reintenta mas tarde."
        )

    return payload
