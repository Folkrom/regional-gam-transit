import zipfile
from pathlib import Path

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


def _escribir_csv(tmp_path: Path) -> Path:
    ruta = tmp_path / "denue.csv"
    ruta.write_bytes("\n".join(FILAS).encode(DENUE_ENCODING))
    return ruta


def test_lee_en_latin1_sin_romper_acentos(tmp_path):
    """El CSV de DENUE viene en latin-1. Leerlo como utf-8 lo rompe.

    Esta prueba existe por lo que costo el mojibake del CSV del Metro: un
    encoding mal leido que no fallo, solo perdio un tercio de los datos en
    silencio.
    """
    df = load_gam(_escribir_csv(tmp_path))
    nombres = set(df["nom_estab"])
    assert "CAFÉ MARTÍNEZ" in nombres
    assert "PAPELERÍA SOLÍS" in nombres


def test_filtra_solo_gam(tmp_path):
    df = load_gam(_escribir_csv(tmp_path))
    assert len(df) == 2
    assert "TIENDA DE OTRA ALCALDÍA" not in set(df["nom_estab"])


def test_renombra_coordenadas_a_lat_lon(tmp_path):
    """accumulate_decay espera lat/lon; DENUE los llama latitud/longitud."""
    df = load_gam(_escribir_csv(tmp_path))
    assert "lat" in df.columns
    assert "lon" in df.columns
    assert "latitud" not in df.columns
    assert df.iloc[0]["lat"] == pytest.approx(19.50)


def test_descarta_filas_sin_coordenadas(tmp_path):
    """En GAM no hay ninguna hoy, pero una fila sin coordenada no se puede
    ubicar y arrastraria un NaN hasta accumulate_decay, que lanza."""
    ruta = tmp_path / "denue.csv"
    filas = FILAS + ["4,SIN UBICACION,461110,0 a 5 personas,Gustavo A. Madero,,"]
    ruta.write_bytes("\n".join(filas).encode(DENUE_ENCODING))
    df = load_gam(ruta)
    assert len(df) == 2
    assert not df[["lat", "lon"]].isna().any().any()


def test_municipio_esperado_es_constante():
    assert GAM_MUNICIPIO == "Gustavo A. Madero"


def test_cache_corrupta_nombra_el_archivo_y_el_remedio(tmp_path, monkeypatch):
    """Una cache truncada debe decir cual archivo y como salir del problema."""
    cache = tmp_path / "denue_09_csv.zip"
    cache.write_bytes(b"no soy un zip")

    def explota(*args, **kwargs):
        raise AssertionError("no debe tocar la red habiendo cache")

    monkeypatch.setattr(requests, "get", explota)

    with pytest.raises(ValueError, match="corrupta o truncada"):
        fetch_denue_csv(tmp_path)


def test_zip_sin_csv_adentro_falla_claro(tmp_path):
    """Un zip valido pero sin CSV es respuesta inservible, no cache buena."""
    cache = tmp_path / "denue_09_csv.zip"
    with zipfile.ZipFile(cache, "w") as zf:
        zf.writestr("leeme.txt", "sin datos")

    with pytest.raises(ValueError, match="ningun .csv"):
        fetch_denue_csv(tmp_path)
