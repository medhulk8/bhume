"""BhuMe cadastral boundary correction — single end-to-end entry point.

    uv run python ../src/predict.py <village_dir>

Writes <village_dir>/predictions.geojson (contract-valid EPSG:4326).

Pipeline (one drift-field build, one imagery handle, windowed reads only):
  1. Adjacency graph (shared vertices + Delaunay backstop).
  2. Pass 1 — block-grow chamfer → RANSAC-purified anchors → per-sheet GP drift field.
  3. Pass 2 — greedy per-plot chamfer (sharp single-plot peaks for per-plot correction).
  4. Calibration — synthetic displacement-recovery → LogisticRegression → isotonic
     (trained on-the-fly per village so it generalises to unseen villages).
  5. Decision layer:
       - shift < LEAVE_ALONE_M  → OMIT  (restraint: likely a control plot; no penalty/credit)
       - area ratio outside band → FLAG  (area mismatch — don't drag)
       - greedy fails + GP uncertain → FLAG
       - else → CORRECTED, confidence = calibration model.

Runtime target: < 7 min/village. Memory: full rasters never loaded — only ~60 m patches.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from shapely.ops import transform as shp_transform, unary_union

sys.path.insert(0, str(Path(__file__).parent.parent / "kit"))
sys.path.insert(0, str(Path(__file__).parent))

import bhume.io as bio
import graph as G
import matching as M
import drift_field as DF
import calibrate as C

LEAVE_ALONE_M   = 5.0    # shift below this → omit (restraint; scorer CONTROL_SHIFT_M=5.0)
AREA_RATIO_BAND = (0.7, 1.4)   # outside → flag (Phase 0)
GREEDY_TRUST_P2SP = 0.80       # greedy P2SP below this → trust greedy over GP
GP_RESCUE_MAX_STD = 6.0        # GP std above this → too uncertain to rescue → flag
GP_FALLBACK_AGREE_M = M.SEARCH_RADIUS_M  # agree_m for GP-fallback plots (no chamfer agreement)


def _utm_crs_from_village(village) -> str:
    centroid = village.plots.geometry.union_all().centroid
    lon = centroid.x
    return f"EPSG:{32600 + int((lon + 180) // 6) + 1}"


def _translate_geom(geom_4326, dx_m, dy_m, utm_crs):
    to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    to_4326 = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)
    def _tr(xs, ys, z=None):
        ux, uy = to_utm.transform(xs, ys)
        return to_4326.transform([u + dx_m for u in ux], [u + dy_m for u in uy])
    return shp_transform(_tr, geom_4326)


def predict(village_dir: str) -> gpd.GeoDataFrame:
    t0 = time.time()
    village_path = Path(village_dir)
    village = bio.load(village_path)
    plots = village.plots
    utm_crs = _utm_crs_from_village(village)
    plots_u = plots.to_crs(utm_crs)

    print(f"\n{'='*60}")
    print(f"PREDICT — {village.slug}")
    print(f"{'='*60}")
    print(f"  Plots: {len(plots):,} | UTM: {utm_crs}")

    # Single imagery handle for the whole run (windowed reads only)
    img_src = rasterio.open(village.imagery_path)
    img_crs = img_src.crs.to_string()
    to_img = Transformer.from_crs("EPSG:4326", img_crs, always_xy=True)
    to_4326_t = Transformer.from_crs(img_crs, "EPSG:4326", always_xy=True)
    def f_img(g): return shp_transform(lambda xs, ys, z=None: to_img.transform(xs, ys), g)
    def f_4326(g): return shp_transform(lambda xs, ys, z=None: to_4326_t.transform(xs, ys), g)
    bnd = village.boundaries_path

    areas_m2 = G.plot_areas_utm(plots, utm_crs)
    all_areas = [v for v in areas_m2.values() if v > 0]
    median_area = float(np.median(all_areas)) if all_areas else 5000.0

    # --- 1. Adjacency graph ---
    print("  [1/5] Adjacency graph...")
    adj = G.build_adjacency(plots, utm_crs)

    # --- 2. Pass 1: block-grow → anchors → drift field (built ONCE) ---
    print("  [2/5] Pass 1 block-grow → drift field...")
    already: set[str] = set()
    pns_by_area = sorted(plots.index.tolist(), key=lambda pn: areas_m2.get(pn, 0), reverse=True)
    anchors: list[DF.Anchor] = []
    n = len(pns_by_area)
    for i, seed in enumerate(pns_by_area):
        if i % 400 == 0:
            print(f"      block-grow {i}/{n}")
        if seed in already:
            continue
        block = M.grow_block(seed, adj, plots, plots_u, img_src, bnd, f_img, median_area, already)
        res = M.chamfer_block(block, plots, img_src, bnd, f_img, f_4326, img_crs)
        for pn in block:
            already.add(pn)
        if not res["is_flagged"] and res["p2sp_ratio"] < 0.85:
            merged = unary_union([plots_u.loc[pn, "geometry"] for pn in block if pn in plots_u.index])
            if merged and not merged.is_empty:
                anchors.append(DF.Anchor(
                    plot_number=seed, cx_m=merged.centroid.x, cy_m=merged.centroid.y,
                    dx_m=res["dx_m"], dy_m=res["dy_m"],
                    confidence=float(np.clip(1.0 - res["p2sp_ratio"], 0.0, 1.0))))
    fields = DF.build_drift_field(anchors, utm_crs, detect_sheet_seams=True)
    print(f"      anchors={len(anchors)} sheets={len(fields)}")

    # --- 3. Pass 2: greedy per-plot chamfer ---
    print("  [3/5] Pass 2 greedy per-plot chamfer...")
    greedy: dict[str, dict] = {}
    for i, pn in enumerate(plots.index):
        if i % 400 == 0:
            print(f"      greedy {i}/{n}")
        geom = plots.loc[pn, "geometry"]
        if geom is None or geom.is_empty:
            continue
        greedy[pn] = M.chamfer_geom(geom, img_src, bnd, f_img, f_4326, img_crs)

    # --- 4. Calibration trained on-the-fly (reuses the cached field) ---
    print("  [4/5] Calibration (synthetic displacement-recovery → LR → isotonic)...")
    samples = C.build_calibration_set(village.slug, fields, utm_crs, village=village)
    model = None
    if len(samples) >= 20:
        model = C.CalibrationModel().fit(samples)
        print(f"      LR weights: {model.weights()}")
    else:
        print(f"      too few samples ({len(samples)}) — confidence falls back to 1-p2sp")

    # --- 5. Decision layer + assembly ---
    print("  [5/5] Decision layer...")
    rows = []
    n_corr = n_flag = n_omit = 0

    for pn in plots.index:
        geom = plots.loc[pn, "geometry"]
        if geom is None or geom.is_empty:
            n_omit += 1
            continue

        geom_u = plots_u.loc[pn, "geometry"]
        cx_m, cy_m = geom_u.centroid.x, geom_u.centroid.y
        ar = float(np.clip(C._area_ratio(plots.loc[pn], drawn_area_m2=areas_m2.get(pn)), 0.3, 3.0))

        g = greedy.get(pn)
        gp_dx, gp_dy, gp_std = (0.0, 0.0, GP_RESCUE_MAX_STD)
        if fields:
            gp_dx, gp_dy, gp_std = DF.assign_sheet(cx_m, cy_m, fields).predict(cx_m, cy_m)

        # Choose shift source
        if g is not None and not g["is_flagged"] and g["p2sp_ratio"] < GREEDY_TRUST_P2SP:
            dx_m, dy_m = g["dx_m"], g["dy_m"]
            p2sp = g["p2sp_ratio"]
            agree_m = float(np.sqrt((dx_m - gp_dx)**2 + (dy_m - gp_dy)**2))
            src = "greedy"
        elif fields and gp_std <= GP_RESCUE_MAX_STD:
            dx_m, dy_m = gp_dx, gp_dy
            p2sp = 1.0
            agree_m = GP_FALLBACK_AGREE_M  # no independent chamfer agreement → conservative
            src = "gp"
        else:
            # No trustworthy correction → flag
            n_flag += 1
            rows.append({"plot_number": pn, "status": "flagged", "confidence": 0.0,
                         "geometry": geom, "method_note": "no confident correction (greedy+GP failed)"})
            continue

        shift_m = float(np.sqrt(dx_m**2 + dy_m**2))

        # Restraint: tiny shift → omit (likely already-correct control plot)
        if shift_m < LEAVE_ALONE_M:
            n_omit += 1
            continue

        # Area mismatch → flag (don't drag a plot whose drawn area disagrees with records)
        if not (AREA_RATIO_BAND[0] <= ar <= AREA_RATIO_BAND[1]):
            n_flag += 1
            rows.append({"plot_number": pn, "status": "flagged", "confidence": 0.0,
                         "geometry": geom, "method_note": f"area ratio {ar:.2f} outside band"})
            continue

        # Corrected — apply shift, calibrated confidence
        corrected = _translate_geom(geom, dx_m, dy_m, utm_crs)
        if model is not None:
            conf = model.predict(p2sp, agree_m, gp_std, ar)
        else:
            conf = float(np.clip(1.0 - p2sp, 0.05, 0.95))
        n_corr += 1
        rows.append({"plot_number": pn, "status": "corrected", "confidence": round(conf, 4),
                     "geometry": corrected,
                     "method_note": f"{src} dx={dx_m:.1f}m dy={dy_m:.1f}m agree={agree_m:.1f}m ar={ar:.2f}"})

    img_src.close()

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    elapsed = time.time() - t0
    print(f"\n  corrected={n_corr}  flagged={n_flag}  omitted={n_omit}")
    print(f"  Elapsed: {elapsed:.1f}s ({elapsed/len(plots):.3f}s/plot)")
    return gdf


def main():
    if len(sys.argv) < 2:
        print("usage: predict.py <village_dir>")
        sys.exit(1)
    village_dir = sys.argv[1]
    gdf = predict(village_dir)
    out = Path(village_dir) / "predictions.geojson"
    bio.write_predictions(out, gdf)
    print(f"  Written: {out}")

    # Score if example truths exist
    try:
        from bhume.score import score as _score
        village = bio.load(Path(village_dir))
        sc = _score(gdf, village)
        print(f"\n=== {village.slug} · final predictions ===")
        print(sc)
    except Exception as e:
        print(f"  (scoring skipped: {e})")


if __name__ == "__main__":
    main()
