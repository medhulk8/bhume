"""Bake imagery.tif into static XYZ web tiles (no GDAL CLI needed).

imagery.tif is already EPSG:3857, so XYZ (web-mercator) tiles are a pure
windowed resample — no reprojection. Outputs RGBA PNGs; pixels outside the
imagery extent are transparent so village edges feather cleanly.

Per-village max zoom = native resolution (baking deeper = upsampled blur).
MapLibre over-zooms the deepest real tile client-side for close inspection.

Usage (from kit/):
    uv run python ../src/bake_tiles.py            # bake all villages
    uv run python ../src/bake_tiles.py --count    # dry-run: tile counts only

Writes web/public/tiles/<village>/{z}/{x}/{y}.png
"""

from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
from PIL import Image

ROOT = Path(__file__).parent.parent
OUT_ROOT = ROOT / "web" / "public" / "tiles"

ORIGIN = 20037508.342789244          # web-mercator half-extent (m)
WORLD = 2 * ORIGIN
TILE = 256

# native zoom: vadnerbhairav 1.19 m/px -> z17, malatavadi 0.60 m/px -> z18
MIN_Z = 13
MAX_Z = {"vadnerbhairav": 17, "malatavadi": 18}


def tile_bounds(x: int, y: int, z: int):
    ts = WORLD / (2 ** z)
    minx = -ORIGIN + x * ts
    maxx = -ORIGIN + (x + 1) * ts
    maxy = ORIGIN - y * ts
    miny = ORIGIN - (y + 1) * ts
    return minx, miny, maxx, maxy


def tile_range(left, bottom, right, top, z):
    ts = WORLD / (2 ** z)
    x0 = int((left + ORIGIN) // ts)
    x1 = int((right + ORIGIN) // ts)
    y0 = int((ORIGIN - top) // ts)
    y1 = int((ORIGIN - bottom) // ts)
    return x0, x1, y0, y1


def bake_village(slug: str, src_path: Path, count_only: bool) -> int:
    total = 0
    with rasterio.open(src_path) as src:
        b = src.bounds
        for z in range(MIN_Z, MAX_Z[slug] + 1):
            x0, x1, y0, y1 = tile_range(b.left, b.bottom, b.right, b.top, z)
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    total += 1
                    if count_only:
                        continue
                    minx, miny, maxx, maxy = tile_bounds(x, y, z)
                    win = from_bounds(minx, miny, maxx, maxy, src.transform)
                    rgb = src.read(
                        indexes=[1, 2, 3], window=win, out_shape=(3, TILE, TILE),
                        boundless=True, fill_value=0, resampling=Resampling.bilinear,
                    )
                    alpha = src.read_masks(
                        1, window=win, out_shape=(TILE, TILE), boundless=True,
                        resampling=Resampling.nearest,
                    )
                    if not alpha.any():
                        total -= 1
                        continue  # tile fully outside imagery — skip
                    # boundless read_masks returns bool — scale to 0/255 for PNG alpha
                    alpha = (alpha.astype(bool).astype(np.uint8)) * 255
                    arr = np.dstack([rgb[0], rgb[1], rgb[2], alpha]).astype(np.uint8)
                    out = OUT_ROOT / slug / str(z) / str(x)
                    out.mkdir(parents=True, exist_ok=True)
                    Image.fromarray(arr, "RGBA").save(out / f"{y}.png", optimize=True)
            if not count_only:
                print(f"    z{z}: tiles through {total}")
    return total


def main():
    count_only = "--count" in sys.argv
    for slug in ("vadnerbhairav", "malatavadi"):
        src = ROOT / "data" / slug / "imagery.tif"
        print(f"=== {slug} (z{MIN_Z}-{MAX_Z[slug]}) ===")
        n = bake_village(slug, src, count_only)
        print(f"  {'would write' if count_only else 'wrote'} {n} tiles\n")


if __name__ == "__main__":
    main()
