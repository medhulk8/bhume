"""Phase 2 (folded into Phase 3) — boundary evidence raster and distance transform.

Provides build_evidence_patch() and build_dt() for use by the Phase 3 matcher.
No standalone benchmarking — Phase 0 audit established the signal is good;
Phase 1 confirmed the adaptive threshold outperforms global threshold.

Evidence formula (locked in docs/phase0_findings.md):
    evidence_px = max(sobel_norm, GAMMA * boundaries_norm)
DT binarisation: adaptive per-patch top EDGE_TOP_PCT fraction of pixels as edges.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import rasterio
from rasterio.windows import from_bounds

GAMMA = 0.9            # boundaries.tif discount vs Sobel when both fire at full strength
EDGE_TOP_PCT = 0.15    # top fraction of evidence pixels become edges for DT


def build_evidence_patch(imagery_src, boundaries_path: Path | None,
                          geom_img_crs, pad_m: float) -> tuple[np.ndarray | None, object | None]:
    """Build per-pixel evidence raster for a geometry (already in imagery CRS).

    Returns (evidence HxW float32 [0,1], win_transform) or (None, None) on failure.
    evidence = max(sobel_norm, GAMMA * boundaries_norm) — max fusion, not linear sum.
    """
    minx, miny, maxx, maxy = geom_img_crs.bounds
    left   = minx - pad_m;  right = maxx + pad_m
    bottom = miny - pad_m;  top   = maxy + pad_m
    dl, db, dr, dt_bounds = imagery_src.bounds
    left, bottom = max(left, dl), max(bottom, db)
    right, top   = min(right, dr), min(top, dt_bounds)
    if right <= left or top <= bottom:
        return None, None

    window = from_bounds(left, bottom, right, top, transform=imagery_src.transform)
    try:
        rgb = imagery_src.read([1, 2, 3], window=window)
    except Exception:
        return None, None

    gray = cv2.cvtColor(np.transpose(rgb, (1, 2, 0)), cv2.COLOR_RGB2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    sobel = np.sqrt(gx**2 + gy**2)
    sobel_max = sobel.max()
    sobel_norm = sobel / sobel_max if sobel_max > 0 else sobel

    evidence = sobel_norm.copy()

    if boundaries_path is not None and boundaries_path.exists():
        try:
            with rasterio.open(boundaries_path) as b_src:
                b_window = from_bounds(left, bottom, right, top, transform=b_src.transform)
                bnd_arr = b_src.read(1, window=b_window).astype(np.float32)
                if bnd_arr.shape != gray.shape:
                    bnd_arr = cv2.resize(bnd_arr, (gray.shape[1], gray.shape[0]),
                                         interpolation=cv2.INTER_LINEAR)
                bnd_norm = bnd_arr / 255.0
                evidence = np.maximum(sobel_norm, GAMMA * bnd_norm)
        except Exception:
            pass

    win_transform = imagery_src.window_transform(window)
    return evidence.astype(np.float32), win_transform


def build_dt(evidence: np.ndarray) -> np.ndarray:
    """Distance transform from evidence raster.

    Per-patch adaptive threshold (top EDGE_TOP_PCT pixels = edges).
    Returns DT in pixels — lower = closer to a detected edge = better chamfer score.
    """
    threshold = float(np.percentile(evidence, 100.0 * (1.0 - EDGE_TOP_PCT)))
    edges = (evidence >= threshold).astype(np.uint8)
    not_edges = 1 - edges
    return cv2.distanceTransform(not_edges, cv2.DIST_L2, 5).astype(np.float32)


def outline_pixels(geom_img_crs, win_transform, H: int, W: int
                   ) -> tuple[np.ndarray, np.ndarray]:
    """Rasterise polygon outline once → (rows, cols) pixel arrays.

    These base coordinates are shifted by integer offsets in the inner loop —
    no rasterize call needed per candidate.
    """
    import rasterio.features
    from shapely.geometry import mapping

    try:
        burned = rasterio.features.rasterize(
            [(mapping(geom_img_crs), 1)],
            out_shape=(H, W), transform=win_transform, fill=0, dtype=np.uint8
        )
        kernel = np.ones((3, 3), np.uint8)
        eroded = cv2.erode(burned, kernel, iterations=1)
        rows, cols = np.where((burned - eroded) > 0)
        return rows.astype(np.int32), cols.astype(np.int32)
    except Exception:
        return np.array([], np.int32), np.array([], np.int32)


def score_dt_shift(dt: np.ndarray, base_rows: np.ndarray, base_cols: np.ndarray,
                   drow: int, dcol: int) -> float:
    """Sample DT at shifted outline coordinates. O(M) — no rasterize in inner loop.

    Returns trimmed-mean DT distance (LOWER = better). Out-of-bounds → dt.max() penalty.
    """
    H, W = dt.shape
    penalty = float(dt.max()) if dt.max() > 0 else float(H + W)
    if len(base_rows) < 5:
        return penalty

    rows = base_rows + drow
    cols = base_cols + dcol
    in_b = (rows >= 0) & (rows < H) & (cols >= 0) & (cols < W)
    distances = np.full(len(rows), penalty, dtype=np.float32)
    if in_b.sum() >= 5:
        distances[in_b] = dt[rows[in_b], cols[in_b]]

    k = max(1, int(0.10 * len(distances)))
    return float(np.mean(np.sort(distances)[:-k]))
