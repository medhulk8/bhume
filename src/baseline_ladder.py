"""Phase 1 — Baseline ladder.

Three baselines run and scored in order:
  1. Identity   — move nothing (restraint reference, sets floor)
  2. MedianShift — kit's global_median_shift (naive village-wide translation)
  3. GreedyChamfer — per-plot chamfer matching on boundary evidence raster
                     (no drift field, no block growing — ablation row for Phase 3+)

Usage (from repo root):
    uv run --project kit src/baseline_ladder.py vadnerbhairav
    uv run --project kit src/baseline_ladder.py malatavadi
    uv run --project kit src/baseline_ladder.py both

Outputs:
    data/<village>/predictions_identity.geojson
    data/<village>/predictions_median_shift.geojson
    data/<village>/predictions_greedy_chamfer.geojson
    docs/baseline_scores.md   (appended)
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import cv2
import numpy as np
import geopandas as gpd
from shapely.affinity import translate
from shapely.geometry import mapping

warnings.filterwarnings("ignore")

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO / "kit"))

from bhume.io import load, write_predictions
from bhume.geo import open_imagery, patch_for_plot, geom_to_imagery_crs
from bhume.score import score
from bhume.baseline import global_median_shift

import rasterio

DATA = REPO / "data"
DOCS = REPO / "docs"

# ---------------------------------------------------------------------------
# Chamfer search parameters — from docs/phase0_findings.md
# ---------------------------------------------------------------------------
SEARCH_RADIUS_M = 28.0   # max observed drift magnitude × 1.5
SEARCH_STEP_M   = 1.0    # coarse grid step
FINE_STEP_M     = 0.25   # fine grid step (±3 steps around coarse best)
FINE_RADIUS_M   = 3.0    # fine search radius around coarse best
P2SP_EXCLUSION_M = 5.0   # mask radius around best peak when finding second peak (Lowe's ratio)

# ---------------------------------------------------------------------------
# Evidence pixel formula — from docs/phase0_findings.md
# ---------------------------------------------------------------------------
GAMMA = 0.9  # boundaries.tif discount vs Sobel when both fire at full strength


def build_evidence_raster(imagery_src, boundaries_path: Path | None,
                           geom_4326, pad_m: float = SEARCH_RADIUS_M + 10) -> tuple[np.ndarray, object]:
    """Build per-pixel evidence = max(sobel_norm, GAMMA × boundaries_norm).

    Returns (evidence HxW float32 in [0,1], window_transform).
    """
    from bhume.geo import geom_to_imagery_crs
    from rasterio.windows import from_bounds

    g = geom_to_imagery_crs(imagery_src, geom_4326)
    minx, miny, maxx, maxy = g.bounds
    left  = minx - pad_m; right  = maxx + pad_m
    bottom= miny - pad_m; top    = maxy + pad_m
    dl, db, dr, dt = imagery_src.bounds
    left, bottom = max(left, dl), max(bottom, db)
    right, top   = min(right, dr), min(top, dt)
    if right <= left or top <= bottom:
        return None, None

    window = from_bounds(left, bottom, right, top, transform=imagery_src.transform)
    rgb = imagery_src.read([1, 2, 3], window=window)   # (3, H, W)
    gray = cv2.cvtColor(np.transpose(rgb, (1, 2, 0)), cv2.COLOR_RGB2GRAY).astype(np.float32)

    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    sobel = np.sqrt(gx**2 + gy**2)
    sobel_max = sobel.max()
    sobel_norm = sobel / sobel_max if sobel_max > 0 else sobel

    evidence = sobel_norm.copy()

    if boundaries_path is not None and boundaries_path.exists():
        with rasterio.open(boundaries_path) as b_src:
            try:
                b_window = from_bounds(left, bottom, right, top, transform=b_src.transform)
                bnd_arr = b_src.read(1, window=b_window)
                # Resize to match imagery patch if shapes differ
                if bnd_arr.shape != gray.shape:
                    bnd_arr = cv2.resize(bnd_arr.astype(np.float32),
                                         (gray.shape[1], gray.shape[0]),
                                         interpolation=cv2.INTER_LINEAR)
                bnd_norm = bnd_arr.astype(np.float32) / 255.0
                # Max fusion — let either signal dominate
                evidence = np.maximum(sobel_norm, GAMMA * bnd_norm)
            except Exception:
                pass  # fall back to Sobel only

    win_transform = imagery_src.window_transform(window)
    img_crs = str(imagery_src.crs)
    return evidence.astype(np.float32), win_transform, img_crs


def build_distance_transform(evidence: np.ndarray, edge_threshold: float = 0.15) -> np.ndarray:
    """Compute distance transform of the evidence raster.

    Binarises evidence at edge_threshold → inverts → distance transform.
    Result: per-pixel distance (in pixels) to nearest detected edge.
    Lower DT value = closer to an edge = better chamfer score.
    Computed ONCE per patch; all candidate shifts sample from this single DT.
    """
    edges = (evidence >= edge_threshold).astype(np.uint8)
    # DT needs the background (non-edge) pixels to get distance to nearest edge
    not_edges = 1 - edges
    dt = cv2.distanceTransform(not_edges, cv2.DIST_L2, 5)  # O(N), exact L2
    return dt.astype(np.float32)


def sample_outline_on_dt(dt: np.ndarray, transform, geom_img_crs,
                          dx_m: float, dy_m: float) -> float:
    """Sample precomputed distance transform at outline pixels of shifted geometry.

    Returns trimmed-mean DT distance (LOWER = better alignment).
    Out-of-bounds pixels get penalised with dt.max() (worst possible distance).
    """
    import rasterio.features
    from shapely.affinity import translate as shp_translate

    shifted = shp_translate(geom_img_crs, xoff=dx_m, yoff=dy_m)
    H, W = dt.shape
    penalty = float(dt.max()) if dt.max() > 0 else float(H + W)

    try:
        burned = rasterio.features.rasterize(
            [(mapping(shifted), 1)],
            out_shape=(H, W), transform=transform, fill=0, dtype=np.uint8
        )
        kernel = np.ones((3, 3), np.uint8)
        eroded = cv2.erode(burned, kernel, iterations=1)
        outline_mask = (burned - eroded).astype(bool)
    except Exception:
        return penalty

    if outline_mask.sum() < 5:
        return penalty

    distances = dt[outline_mask]
    # Trim top 10% (furthest pixels — one occluded edge can't sink a good match)
    k = max(1, int(0.10 * len(distances)))
    trimmed = np.sort(distances)[:-k] if k < len(distances) else distances
    return float(np.mean(trimmed))


def greedy_chamfer_predict(village, confidence_floor: float = 0.3) -> gpd.GeoDataFrame:
    """Per-plot chamfer matching — no drift field, no block growing.

    Coarse grid search over SEARCH_RADIUS_M, then fine refinement.
    Confidence = Lowe's peak-to-second-peak ratio (1 - best/second_distinct_min).
    Plots with no evidence, flat DT landscape, or no second peak → flagged.
    """
    preds = []
    plots = village.plots

    # UTM for metre-based operations
    centroid_0 = plots.geometry.iloc[0].centroid
    utm = f"EPSG:{32600 + int((centroid_0.x + 180) // 6) + 1}"
    plots_u = plots.to_crs(utm)

    # Coarse search grid (metres)
    steps = np.arange(-SEARCH_RADIUS_M, SEARCH_RADIUS_M + SEARCH_STEP_M, SEARCH_STEP_M)
    grid_dx, grid_dy = np.meshgrid(steps, steps)
    grid_dx = grid_dx.ravel()
    grid_dy = grid_dy.ravel()
    # Restrict to circle
    in_circle = np.sqrt(grid_dx**2 + grid_dy**2) <= SEARCH_RADIUS_M
    grid_dx = grid_dx[in_circle]
    grid_dy = grid_dy[in_circle]

    print(f"  Chamfer grid: {len(grid_dx)} coarse positions per plot")

    with open_imagery(village.imagery_path) as img_src:
        img_crs = str(img_src.crs)
        # Reproject all plots to imagery CRS once — chamfer operates in metres
        from pyproj import Transformer
        from shapely.ops import transform as shp_transform_crs
        tf_to_img = Transformer.from_crs("EPSG:4326", img_crs, always_xy=True)
        tf_to_4326 = Transformer.from_crs(img_crs, "EPSG:4326", always_xy=True)

        def to_img(geom):
            return shp_transform_crs(lambda xs, ys, z=None: tf_to_img.transform(xs, ys), geom)

        def to_4326(geom):
            return shp_transform_crs(lambda xs, ys, z=None: tf_to_4326.transform(xs, ys), geom)

        for i, (pn, row) in enumerate(plots.iterrows()):
            if i % 200 == 0:
                print(f"  [{village.slug}] chamfer {i}/{len(plots)} ...")

            geom_4326 = row["geometry"]
            if geom_4326 is None or geom_4326.is_empty:
                preds.append(_flagged(pn, row, "empty geometry"))
                continue

            try:
                geom_img = to_img(geom_4326)
                evidence, win_transform, _ = build_evidence_raster(
                    img_src, village.boundaries_path, geom_4326
                )
            except Exception as e:
                preds.append(_flagged(pn, row, f"evidence build failed: {e}"))
                continue

            if evidence is None or evidence.size == 0:
                preds.append(_flagged(pn, row, "no imagery overlap"))
                continue

            # Compute DT once per patch — all candidates sample from this
            dt = build_distance_transform(evidence)
            dt_max = float(dt.max()) if dt.max() > 0 else float(sum(evidence.shape))

            if dt_max < 1e-6:
                preds.append(_flagged(pn, row, "no edges detected in patch"))
                continue

            # Coarse search — lower DT score = better
            scores = np.array([
                sample_outline_on_dt(dt, win_transform, geom_img, dx, dy)
                for dx, dy in zip(grid_dx, grid_dy)
            ])

            if np.min(scores) >= dt_max * 0.99:
                preds.append(_flagged(pn, row, "flat DT landscape — outline never near edges"))
                continue

            best_idx = int(np.argmin(scores))
            best_dx, best_dy = grid_dx[best_idx], grid_dy[best_idx]

            # Fine search around coarse best
            fine_steps = np.arange(-FINE_RADIUS_M, FINE_RADIUS_M + FINE_STEP_M, FINE_STEP_M)
            fine_dx_grid, fine_dy_grid = np.meshgrid(
                best_dx + fine_steps, best_dy + fine_steps
            )
            fine_dx = fine_dx_grid.ravel()
            fine_dy = fine_dy_grid.ravel()
            in_fine = np.sqrt((fine_dx - best_dx)**2 + (fine_dy - best_dy)**2) <= FINE_RADIUS_M
            fine_dx, fine_dy = fine_dx[in_fine], fine_dy[in_fine]

            fine_scores = np.array([
                sample_outline_on_dt(dt, win_transform, geom_img, dx, dy)
                for dx, dy in zip(fine_dx, fine_dy)
            ])
            best_fine_idx = int(np.argmin(fine_scores))
            final_dx = fine_dx[best_fine_idx]
            final_dy = fine_dy[best_fine_idx]
            final_score = fine_scores[best_fine_idx]

            # Confidence = Lowe's peak-to-second-peak ratio (lower DT = better match)
            # Mask ±P2SP_RADIUS_M around best, find second-best distinct minimum
            all_dx_combined = np.concatenate([grid_dx, fine_dx])
            all_dy_combined = np.concatenate([grid_dy, fine_dy])
            all_scores_combined = np.concatenate([scores, fine_scores])

            dist_from_best = np.sqrt((all_dx_combined - final_dx)**2 +
                                     (all_dy_combined - final_dy)**2)
            outside_mask = dist_from_best > P2SP_EXCLUSION_M
            if outside_mask.sum() == 0:
                # No second peak — treat as fully ambiguous
                preds.append(_flagged(pn, row, "no second peak to compute P2SP ratio"))
                continue

            second_best_score = float(np.min(all_scores_combined[outside_mask]))

            if second_best_score < 1e-6:
                # Second peak also perfect — completely ambiguous
                confidence = confidence_floor
            else:
                # ratio = best / second — close to 1 → ambiguous, close to 0 → unique
                ratio = final_score / second_best_score
                confidence = float(np.clip(1.0 - ratio, 0.0, 1.0))
                confidence = max(confidence, confidence_floor)

            # Skip if shift < 1m (control-plot safety)
            mag = np.sqrt(final_dx**2 + final_dy**2)
            if mag < 1.0:
                preds.append(_flagged(pn, row, f"shift negligible ({mag:.1f}m)"))
                continue

            # Apply shift in imagery CRS metres, then back to 4326
            shifted_img = translate(geom_img, xoff=final_dx, yoff=final_dy)
            shifted_geom = to_4326(shifted_img)

            preds.append({
                "plot_number": pn,
                "status": "corrected",
                "confidence": round(confidence, 4),
                "method_note": (
                    f"greedy_chamfer dx={final_dx:.1f}m dy={final_dy:.1f}m "
                    f"mag={mag:.1f}m p2sp_ratio={final_score/second_best_score:.3f}"
                ),
                "geometry": shifted_geom,
            })

    gdf = gpd.GeoDataFrame(preds, crs="EPSG:4326")
    return gdf[["plot_number", "status", "confidence", "method_note", "geometry"]]


def _flagged(pn: str, row, reason: str) -> dict:
    return {
        "plot_number": pn,
        "status": "flagged",
        "confidence": None,
        "method_note": reason,
        "geometry": row["geometry"],
    }


# ---------------------------------------------------------------------------
# Identity baseline — move nothing, flag everything
# ---------------------------------------------------------------------------
def identity_predict(village) -> gpd.GeoDataFrame:
    rows = []
    for pn, row in village.plots.iterrows():
        rows.append({
            "plot_number": pn,
            "status": "flagged",
            "confidence": None,
            "method_note": "identity: no correction attempted",
            "geometry": row["geometry"],
        })
    return gpd.GeoDataFrame(rows, crs="EPSG:4326")[
        ["plot_number", "status", "confidence", "method_note", "geometry"]
    ]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run_village(village_name: str):
    vpath = DATA / village_name
    if not vpath.exists():
        print(f"ERROR: {vpath} not found"); return

    v = load(vpath)
    print(f"\n{'='*60}")
    print(f"PHASE 1 BASELINES — {v.slug}")
    print(f"{'='*60}")

    results = {}

    # 1. Identity
    print("\n[1/3] Identity (move nothing)...")
    id_preds = identity_predict(v)
    id_path = vpath / "predictions_identity.geojson"
    write_predictions(id_path, id_preds)
    if v.example_truths is not None:
        sc = score(id_preds, v)
        print(sc)
        results["identity"] = sc
    else:
        print("  No example truths — skipping score")

    # 2. Median shift
    print("\n[2/3] Global median shift...")
    if v.example_truths is not None:
        ms_preds = global_median_shift(v, confidence=0.5)
        ms_path = vpath / "predictions_median_shift.geojson"
        write_predictions(ms_path, ms_preds)
        sc = score(ms_preds, v)
        print(sc)
        results["median_shift"] = sc
    else:
        print("  Skipped — needs example truths to estimate shift")

    # 3. Greedy chamfer
    print("\n[3/3] Greedy chamfer (no drift field, no block growing)...")
    gc_preds = greedy_chamfer_predict(v)
    gc_path = vpath / "predictions_greedy_chamfer.geojson"
    write_predictions(gc_path, gc_preds)
    if v.example_truths is not None:
        sc = score(gc_preds, v)
        print(sc)
        results["greedy_chamfer"] = sc
    n_corrected = (gc_preds["status"] == "corrected").sum()
    n_flagged   = (gc_preds["status"] == "flagged").sum()
    print(f"  corrected={n_corrected}  flagged={n_flagged}")

    # Write to docs/baseline_scores.md
    _write_scores_doc(v.slug, results, gc_preds)

    return results


def _write_scores_doc(slug: str, results: dict, gc_preds: gpd.GeoDataFrame):
    out = DOCS / "baseline_scores.md"
    lines = []
    if out.exists():
        lines = out.read_text().splitlines()

    header = f"\n## {slug}\n"
    table = "| Baseline | Median IoU pred | IoU official | Improvement | AUC | Notes |\n"
    table += "|---|---|---|---|---|---|\n"

    def row(name, sc):
        if sc is None:
            return f"| {name} | — | — | — | — | no truths |\n"
        mip = f"{sc.median_iou_pred:.3f}" if sc.median_iou_pred is not None else "—"
        mio = f"{sc.median_iou_official:.3f}" if sc.median_iou_official is not None else "—"
        mi  = f"{sc.median_improvement:.3f}" if sc.median_improvement is not None else "—"
        auc = f"{sc.auc_accurate_vs_conf:.3f}" if sc.auc_accurate_vs_conf is not None else "—"
        return f"| {name} | {mip} | {mio} | {mi} | {auc} | |\n"

    table += row("identity", results.get("identity"))
    table += row("median_shift", results.get("median_shift"))
    table += row("greedy_chamfer", results.get("greedy_chamfer"))

    gc_flag_note = ""
    if gc_preds is not None:
        n_c = (gc_preds["status"] == "corrected").sum()
        n_f = (gc_preds["status"] == "flagged").sum()
        gc_flag_note = f"\nGreedy chamfer: {n_c} corrected / {n_f} flagged\n"

    new_section = header + table + gc_flag_note
    out.write_text("\n".join(lines) + new_section)
    print(f"\n  Scores written to docs/baseline_scores.md")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "vadnerbhairav"
    if target == "both":
        run_village("vadnerbhairav")
        run_village("malatavadi")
    else:
        run_village(target)
