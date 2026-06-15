"""Phase 3 — Block-grow chamfer matching.

Evidence budget model (from docs/phase0_findings.md):
    budget(block) = mean_evidence_along_outer_perimeter × outer_perimeter_length_m

Block-grow threshold (Vadnerbhairav gold standard, Gemini-derived, adapted to [0,1] units):
    Vadnerbhairav median plot: ~350m perimeter, mean evidence ~0.6 → budget ~210
    SOLO_BUDGET_THRESHOLD = 200   (normalized-evidence × metres)

Block grows over adjacency graph (BFS by budget-per-area-added) until:
  - budget ≥ SOLO_BUDGET_THRESHOLD, OR
  - outer area ≥ PHYSICAL_CAP_FACTOR × village_median_area → flag

Chamfer uses outer-perimeter pixels only; interior shared-edge pixels
are down-weighted by INTERIOR_EDGE_WEIGHT (those bunds are often invisible).
"""

from __future__ import annotations

import warnings
from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from shapely.affinity import translate
from shapely.ops import transform as shp_transform_crs, unary_union

from evidence import build_evidence_patch, build_dt, outline_pixels, score_dt_shift

SOLO_BUDGET_THRESHOLD = 200.0   # normalized_evidence × perimeter_metres
PHYSICAL_CAP_FACTOR   = 10.0   # max block area = this × village median plot area
SEARCH_RADIUS_M       = 28.0   # from Phase 0: max drift magnitude × 1.5
SEARCH_STEP_M         = 1.0
FINE_RADIUS_M         = 3.0
FINE_STEP_M           = 0.25
P2SP_EXCLUSION_M      = 5.0
INTERIOR_EDGE_WEIGHT  = 0.3    # down-weight interior bund pixels in block chamfer


def _utm_crs(geom_4326) -> str:
    lon = geom_4326.centroid.x
    return f"EPSG:{32600 + int((lon + 180) // 6) + 1}"


def _make_transformers(src_crs: str, img_crs: str):
    to_img = Transformer.from_crs(src_crs, img_crs, always_xy=True)
    to_src = Transformer.from_crs(img_crs, src_crs, always_xy=True)
    def f_img(geom):
        return shp_transform_crs(lambda xs, ys, z=None: to_img.transform(xs, ys), geom)
    def f_src(geom):
        return shp_transform_crs(lambda xs, ys, z=None: to_src.transform(xs, ys), geom)
    return f_img, f_src


def evidence_budget(imagery_src, boundaries_path, geom_4326,
                    f_img, pad_m: float = SEARCH_RADIUS_M + 10.0) -> float:
    """Estimate evidence budget for a single plot outline.

    Samples evidence pixels along the plot boundary in a narrow band.
    Returns mean_evidence × outer_perimeter_m.
    """
    geom_img = f_img(geom_4326)
    evidence, win_transform = build_evidence_patch(imagery_src, boundaries_path,
                                                   geom_img, pad_m)
    if evidence is None:
        return 0.0
    H, W = evidence.shape
    base_rows, base_cols = outline_pixels(geom_img, win_transform, H, W)
    if len(base_rows) < 5:
        return 0.0
    mean_ev = float(np.mean(evidence[base_rows, base_cols]))

    utm = _utm_crs(geom_4326)
    geom_u = shp_transform_crs(
        lambda xs, ys, z=None: Transformer.from_crs("EPSG:4326", utm, always_xy=True).transform(xs, ys),
        geom_4326
    )
    perimeter_m = float(geom_u.length)
    return mean_ev * perimeter_m


def grow_block(seed_pn: str, adj: dict[str, set[str]],
               plots_4326: gpd.GeoDataFrame, plots_u: gpd.GeoDataFrame,
               imagery_src, boundaries_path, f_img,
               village_median_area_m2: float,
               already_assigned: set[str]) -> list[str]:
    """BFS block-grow from seed_pn until budget ≥ SOLO_BUDGET_THRESHOLD or cap hit.

    Neighbours added in order of budget-per-area-added (greedy).
    already_assigned: plots already claimed by another block — skip them.
    Returns list of plot_numbers in the block (including seed).
    """
    physical_cap = PHYSICAL_CAP_FACTOR * village_median_area_m2

    block = [seed_pn]
    block_set = {seed_pn}
    frontier = set(adj.get(seed_pn, set())) - block_set - already_assigned

    def block_outer_perimeter():
        from graph import outer_perimeter as _op
        return _op(block, plots_u)

    def block_area():
        geoms = [plots_u.loc[pn, "geometry"] for pn in block
                 if pn in plots_u.index and plots_u.loc[pn, "geometry"] is not None]
        if not geoms:
            return 0.0
        return float(unary_union(geoms).area)

    def current_budget():
        # Evidence budget of the merged outer perimeter
        merged_geom_u = unary_union([plots_u.loc[pn, "geometry"] for pn in block
                                     if pn in plots_u.index])
        merged_4326 = shp_transform_crs(
            lambda xs, ys, z=None: Transformer.from_crs(
                str(plots_u.crs), "EPSG:4326", always_xy=True).transform(xs, ys),
            merged_geom_u
        )
        return evidence_budget(imagery_src, boundaries_path, merged_4326, f_img)

    while True:
        budget = current_budget()
        if budget >= SOLO_BUDGET_THRESHOLD:
            break
        if block_area() >= physical_cap:
            break   # hit cap — caller flags this plot
        if not frontier:
            break

        # Pick neighbour with highest budget-per-area-added
        best_pn = None
        best_ratio = -1.0
        for candidate in list(frontier):
            if candidate not in plots_u.index:
                continue
            c_geom = plots_u.loc[candidate, "geometry"]
            if c_geom is None:
                continue
            c_area = float(c_geom.area)
            if c_area < 1.0:
                continue
            c_4326 = plots_4326.loc[candidate, "geometry"] if candidate in plots_4326.index else None
            if c_4326 is None:
                continue
            c_budget = evidence_budget(imagery_src, boundaries_path, c_4326, f_img)
            ratio = c_budget / c_area
            if ratio > best_ratio:
                best_ratio = ratio
                best_pn = candidate

        if best_pn is None:
            break
        block.append(best_pn)
        block_set.add(best_pn)
        frontier.discard(best_pn)
        frontier |= (set(adj.get(best_pn, set())) - block_set - already_assigned)

    return block


def chamfer_block(block_pns: list[str], plots_4326: gpd.GeoDataFrame,
                  imagery_src, boundaries_path, f_img, f_4326,
                  img_crs: str) -> dict:
    """Run chamfer matching on a block (list of plot_numbers).

    Uses the outer perimeter of the merged block.
    Returns dict with: dx_m, dy_m, p2sp_ratio, score, is_flagged, flag_reason.
    """
    # Merge block geometry in imagery CRS
    geoms_img = []
    for pn in block_pns:
        if pn not in plots_4326.index:
            continue
        geom_4326 = plots_4326.loc[pn, "geometry"]
        if geom_4326 is None or geom_4326.is_empty:
            continue
        geoms_img.append(f_img(geom_4326))

    if not geoms_img:
        return {"dx_m": 0, "dy_m": 0, "p2sp_ratio": 1.0,
                "score": 0.0, "is_flagged": True, "flag_reason": "no valid geometries in block"}

    merged_img = unary_union(geoms_img)
    merged_4326 = f_4326(merged_img)

    pad_m = SEARCH_RADIUS_M + 10.0
    evidence, win_transform = build_evidence_patch(imagery_src, boundaries_path, merged_img, pad_m)
    if evidence is None:
        return {"dx_m": 0, "dy_m": 0, "p2sp_ratio": 1.0,
                "score": 0.0, "is_flagged": True, "flag_reason": "no imagery overlap for block"}

    dt = build_dt(evidence)
    dt_max = float(dt.max()) if dt.max() > 0 else float(sum(evidence.shape))
    H, W = evidence.shape

    if dt_max < 1e-6:
        return {"dx_m": 0, "dy_m": 0, "p2sp_ratio": 1.0,
                "score": 0.0, "is_flagged": True, "flag_reason": "flat DT for block"}

    base_rows, base_cols = outline_pixels(merged_img, win_transform, H, W)
    if len(base_rows) < 5:
        return {"dx_m": 0, "dy_m": 0, "p2sp_ratio": 1.0,
                "score": 0.0, "is_flagged": True, "flag_reason": "block outline too small"}

    px_w = abs(win_transform.a)
    px_h = abs(win_transform.e)

    # Coarse grid
    steps = np.arange(-SEARCH_RADIUS_M, SEARCH_RADIUS_M + SEARCH_STEP_M, SEARCH_STEP_M)
    gdx, gdy = np.meshgrid(steps, steps)
    gdx, gdy = gdx.ravel(), gdy.ravel()
    in_circle = np.sqrt(gdx**2 + gdy**2) <= SEARCH_RADIUS_M
    gdx, gdy = gdx[in_circle], gdy[in_circle]

    gdcol = (gdx / px_w).astype(np.int32)
    gdrow = (-gdy / px_h).astype(np.int32)

    scores = np.array([score_dt_shift(dt, base_rows, base_cols, dr, dc)
                       for dr, dc in zip(gdrow, gdcol)])

    if np.min(scores) >= dt_max * 0.99:
        return {"dx_m": 0, "dy_m": 0, "p2sp_ratio": 1.0,
                "score": 0.0, "is_flagged": True, "flag_reason": "flat DT landscape for block"}

    best_idx = int(np.argmin(scores))
    best_dx, best_dy = gdx[best_idx], gdy[best_idx]

    # Fine search
    fine_steps = np.arange(-FINE_RADIUS_M, FINE_RADIUS_M + FINE_STEP_M, FINE_STEP_M)
    fdx_g, fdy_g = np.meshgrid(best_dx + fine_steps, best_dy + fine_steps)
    fdx, fdy = fdx_g.ravel(), fdy_g.ravel()
    in_fine = np.sqrt((fdx - best_dx)**2 + (fdy - best_dy)**2) <= FINE_RADIUS_M
    fdx, fdy = fdx[in_fine], fdy[in_fine]
    fdcol = (fdx / px_w).astype(np.int32)
    fdrow = (-fdy / px_h).astype(np.int32)

    fine_scores = np.array([score_dt_shift(dt, base_rows, base_cols, dr, dc)
                             for dr, dc in zip(fdrow, fdcol)])
    best_fi = int(np.argmin(fine_scores))
    final_dx = fdx[best_fi]
    final_dy = fdy[best_fi]
    final_score = fine_scores[best_fi]

    # Lowe's P2SP ratio
    all_dx = np.concatenate([gdx, fdx])
    all_dy = np.concatenate([gdy, fdy])
    all_sc = np.concatenate([scores, fine_scores])
    dist_from_best = np.sqrt((all_dx - final_dx)**2 + (all_dy - final_dy)**2)
    outside = dist_from_best > P2SP_EXCLUSION_M

    if outside.sum() == 0 or final_score < 1e-6:
        p2sp = 1.0
    else:
        second = float(np.min(all_sc[outside]))
        p2sp = final_score / second if second > 1e-6 else 1.0

    return {
        "dx_m": float(final_dx),
        "dy_m": float(final_dy),
        "p2sp_ratio": float(p2sp),
        "score": float(final_score),
        "is_flagged": False,
        "flag_reason": "",
    }
