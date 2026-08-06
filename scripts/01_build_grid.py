"""Construye el grid H3 de la alcaldia Gustavo A. Madero.

Salida: data/processed/gam_hexes.parquet (hex_id, lat, lon)

Uso:
    uv run python scripts/01_build_grid.py [--force]
"""

import argparse
from pathlib import Path

from rtgam.boundary import fetch_gam_polygon
from rtgam.geo import H3_RESOLUTION, hex_centroids, hexes_for_polygon

ROOT = Path(__file__).resolve().parents[1]
RAW_BOUNDARY = ROOT / "data" / "raw" / "gam_boundary.geojson"
OUTPUT = ROOT / "data" / "processed" / "gam_hexes.parquet"


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
    print(f"Poligono GAM: {polygon.geom_type}, area aprox {polygon.area * 111**2:.1f} km2")
    print(f"Bounding box: lon [{minx:.4f}, {maxx:.4f}]  lat [{miny:.4f}, {maxy:.4f}]")
    print(f"Hexagonos H3 res {H3_RESOLUTION}: {len(centroids)}")
    print(f"Escrito: {OUTPUT}")


if __name__ == "__main__":
    main()
