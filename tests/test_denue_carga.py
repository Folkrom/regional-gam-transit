import io
import zipfile
from pathlib import Path

import pandas as pd
import pytest
import requests

from rtgam.sources.denue import (
    DENUE_ENCODING,
    GAM_MUNICIPIO,
    fetch_denue_csv,
    load_gam,
)

FILAS = [
    "id,nom_estab,codigo_act,per_ocu,municipio,latitud,longitud",
    "1,CAFÉ MARTÍNEZ,722515,0 a 5 personas,Gustavo A. Madero,19.50,-99.10",
    "2,PAPELERÍA SOLÍS,465311,0 a 5 personas,Gustavo A. Madero,19.51,-99.11",
    "3,TIENDA DE OTRA ALCALDÍA,461110,0 a 5 personas,Coyoacán,19.34,-99.16",
]


def _write_csv(tmp_path: Path) -> Path:
    # El literal "latin-1" va a proposito, NO la constante del modulo. Si se
    # usara DENUE_ENCODING en ambos lados, cambiarla a utf-8 haria que la
    # prueba escriba y lea con el mismo valor equivocado y siguiera pasando.
    path = tmp_path / "denue.csv"
    path.write_bytes("\n".join(FILAS).encode("latin-1"))
    return path


def test_lee_en_latin1_sin_romper_acentos(tmp_path):
    """El CSV de DENUE viene en latin-1. Leerlo como utf-8 lo rompe.

    Esta prueba existe por lo que costo el mojibake del CSV del Metro: un
    encoding mal leido que no fallo, solo perdio un tercio de los datos en
    silencio.
    """
    df = load_gam(_write_csv(tmp_path))
    nombres = set(df["nom_estab"])
    assert "CAFÉ MARTÍNEZ" in nombres
    assert "PAPELERÍA SOLÍS" in nombres


def test_filtra_solo_gam(tmp_path):
    df = load_gam(_write_csv(tmp_path))
    assert len(df) == 2
    assert "TIENDA DE OTRA ALCALDÍA" not in set(df["nom_estab"])


def test_renombra_coordenadas_a_lat_lon(tmp_path):
    """accumulate_decay espera lat/lon; DENUE los llama latitud/longitud."""
    df = load_gam(_write_csv(tmp_path))
    assert "lat" in df.columns
    assert "lon" in df.columns
    assert "latitud" not in df.columns
    assert df.iloc[0]["lat"] == pytest.approx(19.50)


def test_descarta_filas_sin_coordenadas(tmp_path):
    """En GAM no hay ninguna hoy, pero una fila sin coordenada no se puede
    ubicar y arrastraria un NaN hasta accumulate_decay, que lanza."""
    path = tmp_path / "denue.csv"
    rows = FILAS + ["4,SIN UBICACION,461110,0 a 5 personas,Gustavo A. Madero,,"]
    path.write_bytes("\n".join(rows).encode(DENUE_ENCODING))
    df = load_gam(path)
    assert len(df) == 2
    assert not df[["lat", "lon"]].isna().any().any()


def test_municipio_esperado_es_constante():
    assert GAM_MUNICIPIO == "Gustavo A. Madero"


def test_encoding_declarado_es_latin1():
    """Fija el valor. Sin esto, cambiarlo a utf-8 no rompe ninguna prueba."""
    assert DENUE_ENCODING == "latin-1"


def test_el_archivo_no_es_utf8(tmp_path):
    """Prueba con dientes: el mismo fixture leido como utf-8 debe reventar.

    Verificado contra el archivo real de INEGI, que lanza UnicodeDecodeError
    en utf-8. Si algun dia el portal publicara en utf-8, esta prueba falla y
    obliga a revisar, en vez de perder acentos en silencio.
    """
    path = _write_csv(tmp_path)
    with pytest.raises(UnicodeDecodeError):
        pd.read_csv(path, encoding="utf-8")


def test_cache_corrupta_nombra_el_archivo_y_el_remedio(tmp_path, monkeypatch):
    """Una cache truncada debe decir cual archivo y como salir del problema."""
    cache = tmp_path / "denue_09_csv.zip"
    cache.write_bytes(b"no soy un zip")

    def raises_error(*args, **kwargs):
        raise AssertionError("no debe tocar la red habiendo cache")

    monkeypatch.setattr(requests, "get", raises_error)

    with pytest.raises(ValueError, match="corrupta o truncada"):
        fetch_denue_csv(tmp_path)


def test_zip_sin_csv_adentro_falla_claro(tmp_path):
    """Un zip valido pero sin CSV es respuesta inservible, no cache buena."""
    cache = tmp_path / "denue_09_csv.zip"
    with zipfile.ZipFile(cache, "w") as zf:
        zf.writestr("leeme.txt", "sin datos")

    with pytest.raises(ValueError, match="ningun .csv"):
        fetch_denue_csv(tmp_path)


def _zip_bytes(content: str) -> bytes:
    """Zip en memoria con el CSV bajo conjunto_de_datos/, como el real."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("conjunto_de_datos/denue_inegi_09_.csv", content)
    return buffer.getvalue()


class _RespuestaFalsa:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        return None


def test_descarga_extrae_y_cachea(tmp_path, monkeypatch):
    """Camino feliz: baja, valida, escribe cache y devuelve el CSV extraido."""
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _RespuestaFalsa(_zip_bytes("col\nvalor"))
    )
    destination = fetch_denue_csv(tmp_path)
    assert destination.exists()
    assert (tmp_path / "denue_09_csv.zip").exists()
    assert destination.read_text(encoding="latin-1").startswith("col")


def test_force_reemplaza_el_csv_extraido(tmp_path, monkeypatch):
    """--force debe traer los datos nuevos, no el CSV extraido de antes.

    Sin overwrite, un zip nuevo convive con la extraccion vieja y el llamador
    recibe en silencio los datos anteriores, que es justo lo que --force
    venia a evitar.
    """
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _RespuestaFalsa(_zip_bytes("col\nviejo"))
    )
    primero = fetch_denue_csv(tmp_path)
    assert "viejo" in primero.read_text(encoding="latin-1")

    monkeypatch.setattr(
        requests, "get", lambda *a, **k: _RespuestaFalsa(_zip_bytes("col\nnuevo"))
    )
    segundo = fetch_denue_csv(tmp_path, force=True)
    assert "nuevo" in segundo.read_text(encoding="latin-1")
