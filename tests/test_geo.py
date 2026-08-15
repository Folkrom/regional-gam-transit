import numpy as np
import pandas as pd
import pytest
from shapely.geometry import Polygon

from rtgam.geo import (
    DECAY_CUTOFF_M,
    DECAY_TAU_M,
    accumulate_decay,
    haversine_m,
    hex_centroids,
    hexes_for_polygon,
    nearest_decay,
)


def test_haversine_zero_distance():
    assert haversine_m(19.5, -99.1, 19.5, -99.1) == pytest.approx(0.0, abs=1e-6)


def test_haversine_known_distance():
    """Un grado de latitud son ~111.2 km en cualquier meridiano."""
    d = haversine_m(19.0, -99.1, 20.0, -99.1)
    assert d == pytest.approx(111_195, rel=0.001)


def test_haversine_applies_latitude_cosine():
    """Un grado de longitud se encoge con el coseno de la latitud.

    Sin esta prueba, una haversine a la que le falte el termino
    cos(lat1)*cos(lat2) pasa todas las demas: las otras comparan puntos con
    la misma longitud, donde ese termino se multiplica por sin(0) y desaparece.
    A lat 19.5 la diferencia es 104,817 m contra 111,195 m — 6%.
    """
    d = haversine_m(19.5, -99.5, 19.5, -98.5)
    assert d == pytest.approx(104_817, rel=0.001)


def test_haversine_broadcasts():
    """La matriz hexagonos x puntos depende de este broadcasting."""
    lats = np.array([[19.5], [19.6]])
    lons = np.array([[-99.1], [-99.1]])
    plats = np.array([[19.5, 19.6]])
    plons = np.array([[-99.1, -99.1]])
    d = haversine_m(lats, lons, plats, plons)
    assert d.shape == (2, 2)
    assert d[0, 0] == pytest.approx(0.0, abs=1e-6)
    assert d[1, 1] == pytest.approx(0.0, abs=1e-6)


def test_hexes_for_polygon_returns_res9_cells():
    poly = Polygon(
        [(-99.15, 19.50), (-99.10, 19.50), (-99.10, 19.55), (-99.15, 19.55)]
    )
    cells = hexes_for_polygon(poly, resolution=9)
    assert len(cells) > 100
    assert all(isinstance(c, str) for c in cells)
    assert isinstance(cells, set)


def test_hex_centroids_indexed_and_sorted():
    poly = Polygon(
        [(-99.15, 19.50), (-99.14, 19.50), (-99.14, 19.51), (-99.15, 19.51)]
    )
    cells = hexes_for_polygon(poly, resolution=9)
    df = hex_centroids(cells)
    assert df.index.name == "hex_id"
    assert list(df.columns) == ["lat", "lon"]
    assert len(df) == len(cells)
    assert list(df.index) == sorted(cells)
    # Los centroides caen dentro del area de interes.
    assert df["lat"].between(19.49, 19.52).all()
    assert df["lon"].between(-99.16, -99.13).all()


def _centroid_at(lat, lon, hex_id="h1"):
    return pd.DataFrame({"lat": [lat], "lon": [lon]}, index=pd.Index([hex_id], name="hex_id"))


def test_decay_at_zero_distance_is_full_value():
    centroids = _centroid_at(19.5, -99.1)
    points = pd.DataFrame({"lat": [19.5], "lon": [-99.1], "afluencia": [1000.0]})
    out = accumulate_decay(centroids, points, "afluencia")
    assert out["h1"] == pytest.approx(1000.0, rel=1e-6)


def test_decay_matches_formula_at_400m():
    """400 m al norte: peso esperado exp(-400/300) = 0.2636."""
    centroids = _centroid_at(19.5, -99.1)
    lat_400m_north = 19.5 + 400.0 / 111_195.0
    points = pd.DataFrame({"lat": [lat_400m_north], "lon": [-99.1], "afluencia": [1000.0]})
    out = accumulate_decay(centroids, points, "afluencia")
    assert out["h1"] == pytest.approx(1000.0 * np.exp(-400.0 / DECAY_TAU_M), rel=0.01)


def test_beyond_cutoff_is_exactly_zero():
    centroids = _centroid_at(19.5, -99.1)
    lat_1500m_north = 19.5 + 1500.0 / 111_195.0
    points = pd.DataFrame({"lat": [lat_1500m_north], "lon": [-99.1], "afluencia": [1000.0]})
    out = accumulate_decay(centroids, points, "afluencia")
    assert out["h1"] == 0.0


def test_accumulate_decay_incluye_la_frontera_exacta_del_corte():
    # Hermano del mismo test de nearest_decay. Ningun otro test pone un punto
    # a exactamente `cutoff`, asi que mutar `<=` por `<` sobrevivia con la
    # suite entera en verde, y afecta a las cuatro variables que suman:
    # flujo_transporte, competencia, atractores_denue y atractores_osm.
    #
    # La aproximacion 800/111_000 grados NO cae en 800.0 m exactos, asi que
    # se pasa como `cutoff` la distancia REAL que haversine_m calcula para el
    # punto: mismo calculo, deterministico, y dentro de accumulate_decay
    # `distances` sale exactamente igual a `cutoff`.
    centroids = _centroid_at(19.5, -99.1)
    punto = pd.DataFrame(
        {"lat": [19.5 + 800 / 111_000], "lon": [-99.1], "afluencia": [1000.0]}
    )
    cutoff_exacto = haversine_m(19.5, -99.1, punto["lat"][0], punto["lon"][0])
    out = accumulate_decay(centroids, punto, "afluencia", cutoff=cutoff_exacto)
    assert out["h1"] == pytest.approx(1000.0 * np.exp(-cutoff_exacto / DECAY_TAU_M))
    assert out["h1"] > 0.0


def test_accumulates_multiple_points():
    """Dos estaciones identicas y coincidentes suman el doble."""
    centroids = _centroid_at(19.5, -99.1)
    points = pd.DataFrame(
        {"lat": [19.5, 19.5], "lon": [-99.1, -99.1], "afluencia": [1000.0, 500.0]}
    )
    out = accumulate_decay(centroids, points, "afluencia")
    assert out["h1"] == pytest.approx(1500.0, rel=1e-6)


def test_nan_value_raises_instead_of_poisoning_every_hexagon():
    """Un NaN no ensucia un hexagono: los ensucia todos.

    El producto punto hace 0.0 * NaN = NaN, asi que un hexagono fuera del
    corte de 800 m tambien sale NaN. Verificado: con una estacion en NaN, un
    hexagono a 90 km quedaba NaN. Por eso se falla ruidoso en vez de repartir.
    """
    centroids = _centroid_at(19.5, -99.1)
    points = pd.DataFrame(
        {"lat": [19.5, 19.51], "lon": [-99.1, -99.1], "afluencia": [1000.0, np.nan]}
    )
    with pytest.raises(ValueError, match="NaN"):
        accumulate_decay(centroids, points, "afluencia")


def test_empty_points_returns_zeros_not_error():
    centroids = _centroid_at(19.5, -99.1)
    points = pd.DataFrame({"lat": [], "lon": [], "afluencia": []})
    out = accumulate_decay(centroids, points, "afluencia")
    assert list(out) == [0.0]
    assert out.index.tolist() == ["h1"]


def test_output_aligned_with_centroid_index():
    centroids = pd.DataFrame(
        {"lat": [19.50, 19.60], "lon": [-99.1, -99.1]},
        index=pd.Index(["a", "b"], name="hex_id"),
    )
    points = pd.DataFrame({"lat": [19.50], "lon": [-99.1], "afluencia": [1000.0]})
    out = accumulate_decay(centroids, points, "afluencia")
    assert out.index.tolist() == ["a", "b"]
    assert out["a"] > 0.0
    assert out["b"] == 0.0  # ~11 km, muy por fuera del corte


def test_cutoff_constant_is_800():
    assert DECAY_CUTOFF_M == 800.0
    assert DECAY_TAU_M == 300.0


def test_nearest_decay_toma_el_maximo_no_la_suma():
    # Tres puntos colocados a 300 m contra uno solo a 300 m: el maximo es
    # identico, la suma seria el triple. Las distancias estan elegidas para
    # que suma y maximo NO coincidan por casualidad.
    centroids = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index(["a"], name="hex_id")
    )
    uno = pd.DataFrame({"lat": [19.5 + 300 / 111_000], "lon": [-99.1]})
    tres = pd.DataFrame(
        {"lat": [19.5 + 300 / 111_000] * 3, "lon": [-99.1] * 3}
    )
    assert nearest_decay(centroids, uno)["a"] == pytest.approx(
        nearest_decay(centroids, tres)["a"]
    )


def test_nearest_decay_es_el_mas_cercano_no_el_ultimo():
    # El punto lejano va PRIMERO en el frame: si la implementacion se quedara
    # con el ultimo en vez de con el maximo, este test lo cacha.
    centroids = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index(["a"], name="hex_id")
    )
    points = pd.DataFrame(
        {"lat": [19.5 + 700 / 111_000, 19.5 + 100 / 111_000], "lon": [-99.1, -99.1]}
    )
    esperado = np.exp(-100.0 / 300.0)
    assert nearest_decay(centroids, points)["a"] == pytest.approx(esperado, rel=1e-3)


def test_nearest_decay_corta_a_800_metros():
    centroids = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index(["a"], name="hex_id")
    )
    lejos = pd.DataFrame({"lat": [19.5 + 900 / 111_000], "lon": [-99.1]})
    assert nearest_decay(centroids, lejos)["a"] == 0.0


def test_nearest_decay_sin_puntos_da_ceros_alineados():
    centroids = pd.DataFrame(
        {"lat": [19.5, 19.6], "lon": [-99.1, -99.2]},
        index=pd.Index(["a", "b"], name="hex_id"),
    )
    out = nearest_decay(centroids, pd.DataFrame(columns=["lat", "lon"]))
    assert list(out.index) == ["a", "b"]
    assert (out == 0.0).all()


def test_nearest_decay_en_el_punto_exacto_vale_uno():
    centroids = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index(["a"], name="hex_id")
    )
    encima = pd.DataFrame({"lat": [19.5], "lon": [-99.1]})
    assert nearest_decay(centroids, encima)["a"] == pytest.approx(1.0)


def test_nearest_decay_incluye_la_frontera_exacta_del_corte():
    # La aproximacion 800/111_000 grados NO cae en 800.0 m exactos: seria un
    # test que pasa por casualidad con cualquiera de las dos comparaciones
    # (<= o <). En vez de eso, se fija un punto arbitrario y se pasa como
    # `cutoff` la distancia REAL que haversine_m calcula para ese punto —
    # mismo calculo, deterministico, asi que dentro de nearest_decay
    # `distances` sale exactamente igual a `cutoff`. Esto obliga a la
    # comparacion `<=`: si mutara a `<`, el punto quedaria excluido y el
    # resultado seria 0.0 en vez de exp(-cutoff/tau).
    centroids = pd.DataFrame(
        {"lat": [19.5], "lon": [-99.1]}, index=pd.Index(["a"], name="hex_id")
    )
    punto = pd.DataFrame({"lat": [19.5 + 800 / 111_000], "lon": [-99.1]})
    cutoff_exacto = haversine_m(19.5, -99.1, punto["lat"][0], punto["lon"][0])
    out = nearest_decay(centroids, punto, cutoff=cutoff_exacto)
    assert out["a"] == pytest.approx(np.exp(-cutoff_exacto / 300.0))
    assert out["a"] > 0.0
