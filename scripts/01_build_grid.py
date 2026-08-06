"""Construye el grid H3 de la alcaldia Gustavo A. Madero.

Salida: data/processed/gam_hexes.parquet (hex_id, lat, lon)

Uso:
    uv run python scripts/01_build_grid.py [--force]
"""

import argparse
import math
from pathlib import Path

from rtgam.boundary import fetch_gam_polygon
from rtgam.geo import H3_RESOLUTION, hex_centroids, hexes_for_polygon

ROOT = Path(__file__).resolve().parents[1]
RAW_BOUNDARY = ROOT / "data" / "raw" / "gam_boundary.geojson"
OUTPUT = ROOT / "data" / "processed" / "gam_hexes.parquet"

# Area media de una celda H3 resolucion 9, en km2.
H3_RES9_CELL_KM2 = 0.105


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-descargar aunque exista cache")
    args = parser.parse_args()

    polygon = fetch_gam_polygon(RAW_BOUNDARY, force=args.force)
    hexes = hexes_for_polygon(polygon, resolution=H3_RESOLUTION)
    centroids = hex_centroids(hexes)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    centroids.to_parquet(OUTPUT)

    minx, miny, maxx, maxy = polygon.bounds
    # Un grado de latitud son ~111 km, pero uno de longitud se encoge con el
    # coseno de la latitud: a 19.5 grados vale ~104.6 km, no 111.
    lat_mid = math.radians((miny + maxy) / 2)
    area_km2 = polygon.area * 111.0 * (111.0 * math.cos(lat_mid))
    print(f"Poligono GAM: {polygon.geom_type}, area aprox {area_km2:.1f} km2")
    print(f"Bounding box: lon [{minx:.4f}, {maxx:.4f}]  lat [{miny:.4f}, {maxy:.4f}]")
    # h3.geo_to_cells usa contencion por centro: una celda del borde cuyo
    # centro cae fuera del poligono se descarta. Por eso los hexagonos cubren
    # menos area que el poligono, y conviene imprimir ambas cifras.
    covered_km2 = len(centroids) * H3_RES9_CELL_KM2
    print(f"Hexagonos H3 res {H3_RESOLUTION}: {len(centroids)}")
    print(f"Area cubierta por hexagonos: {covered_km2:.1f} km2 "
          f"({covered_km2 / area_km2 * 100:.0f}% del poligono; el resto son "
          f"celdas del borde descartadas por contencion por centro)")
    print(f"Escrito: {OUTPUT}")


if __name__ == "__main__":
    main()
