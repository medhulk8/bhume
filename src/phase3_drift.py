"""Phase 3 + 4 — Block-grow chamfer + GP drift field.

Run from kit/:
    uv run python ../src/phase3_drift.py [vadnerbhairav|malatavadi|both]

Outputs:
  - docs/phase3_scores.md    (score table)
  - data/<village>/predictions_phase3.geojson
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from shapely.ops import transform as shp_transform, unary_union

# kit imports
sys.path.insert(0, str(Path(__file__).parent.parent / "kit"))
import bhume.io as bio
from bhume.score import score as _score_fn

# src imports
sys.path.insert(0, str(Path(__file__).parent))
import graph as G
import matching as M
import drift_field as DF
from evidence import build_evidence_patch

VILLAGES = ["vadnerbhairav", "malatavadi"]
DATA_ROOT = Path(__file__).parent.parent / "data"
DOCS_ROOT = Path(__file__).parent.parent / "docs"

# Confidence from GP std: sigma=0 → high conf. Scaled to metres.
GP_SIGMA_SCALE_M = 5.0   # 1 std of GP uncertainty maps to this confidence penalty


def utm_crs_from_village(village) -> str:
    centroid = village.plots.geometry.unary_union.centroid
    lon = centroid.x
    return f"EPSG:{32600 + int((lon + 180) // 6) + 1}"


def _to_utm(geom, utm_crs):
    to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    return shp_transform(lambda xs, ys, z=None: to_utm.transform(xs, ys), geom)


def _to_4326(geom, utm_crs):
    to_4326 = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)
    return shp_transform(lambda xs, ys, z=None: to_4326.transform(xs, ys), geom)


def _translate_geom(geom_4326, dx_m: float, dy_m: float, utm_crs: str):
    """Translate all vertices by (dx_m, dy_m) in UTM metres."""
    to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    to_4326 = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)
    def _tr(xs, ys, z=None):
        ux, uy = to_utm.transform(xs, ys)
        return to_4326.transform([u + dx_m for u in ux], [u + dy_m for u in uy])
    return shp_transform(_tr, geom_4326)


def run_village(village_name: str, em_iter: int = 0) -> gpd.GeoDataFrame:
    """Full Phase 3+4 pipeline for one village.

    em_iter: which EM iteration this is (0=first, 1=second). Hard cap 2.
    """
    t0 = time.time()
    village = bio.load(DATA_ROOT / village_name)
    plots = village.plots  # GDF indexed by plot_number, EPSG:4326

    utm_crs = utm_crs_from_village(village)
    plots_u = plots.to_crs(utm_crs)

    imagery_src_ctx = __import__("rasterio").open(village.imagery_path)
    imagery_src = imagery_src_ctx
    img_crs = imagery_src.crs.to_string()

    to_img = Transformer.from_crs("EPSG:4326", img_crs, always_xy=True)
    to_4326 = Transformer.from_crs(img_crs, "EPSG:4326", always_xy=True)

    def f_img(geom):
        return shp_transform(lambda xs, ys, z=None: to_img.transform(xs, ys), geom)
    def f_4326(geom):
        return shp_transform(lambda xs, ys, z=None: to_4326.transform(xs, ys), geom)

    boundaries_path = village.boundaries_path

    print(f"\n{'='*60}")
    print(f"PHASE 3 — {village_name} (EM iter {em_iter})")
    print(f"{'='*60}")
    print(f"  Plots: {len(plots):,} | UTM: {utm_crs}")

    # 1. Adjacency graph
    print("  Building adjacency graph...")
    adj = G.build_adjacency(plots, utm_crs)
    areas_m2 = G.plot_areas_utm(plots, utm_crs)
    all_areas = [v for v in areas_m2.values() if v > 0]
    median_area = float(np.median(all_areas)) if all_areas else 5000.0
    print(f"  Adjacency built. Median area: {median_area:.0f} m²")

    # 2. Block-grow + chamfer matching
    print("  Block-grow + chamfer matching...")
    already_assigned: set[str] = set()
    block_assignments: dict[str, list[str]] = {}  # plot → block members

    # Sort by area descending (larger plots → higher budget → seed first)
    pns_sorted = sorted(plots.index.tolist(), key=lambda pn: areas_m2.get(pn, 0), reverse=True)

    anchors: list[DF.Anchor] = []
    chamfer_results: dict[str, dict] = {}  # plot → chamfer result

    n = len(pns_sorted)
    for i, seed_pn in enumerate(pns_sorted):
        if i % 200 == 0:
            print(f"  [{village_name}] block-grow {i}/{n} ...")

        if seed_pn in already_assigned:
            continue

        block = M.grow_block(
            seed_pn, adj, plots, plots_u,
            imagery_src, boundaries_path, f_img,
            median_area, already_assigned
        )

        # Chamfer on merged block
        result = M.chamfer_block(block, plots, imagery_src, boundaries_path,
                                  f_img, f_4326, img_crs)

        # Assign result to all plots in block
        for pn in block:
            chamfer_results[pn] = result
            block_assignments[pn] = block
            already_assigned.add(pn)

        # Build anchor from block centroid (only high-confidence blocks)
        if not result["is_flagged"] and result["p2sp_ratio"] < 0.85:
            # Centroid of merged block in UTM
            merged_u = unary_union([plots_u.loc[pn, "geometry"]
                                    for pn in block if pn in plots_u.index])
            if merged_u and not merged_u.is_empty:
                cx = merged_u.centroid.x
                cy = merged_u.centroid.y
                conf = float(np.clip(1.0 - result["p2sp_ratio"], 0.0, 1.0))
                anchors.append(DF.Anchor(
                    plot_number=seed_pn,
                    cx_m=cx, cy_m=cy,
                    dx_m=result["dx_m"], dy_m=result["dy_m"],
                    confidence=conf
                ))

    print(f"  Chamfer done. Anchors collected: {len(anchors)}")

    # 3. Build drift field
    print("  Building drift field...")
    fields = DF.build_drift_field(anchors, utm_crs, detect_sheet_seams=True)
    print(f"  Drift field: {len(fields)} sheet(s)")
    for df in fields:
        print(f"    Sheet {df.sheet_id}: {len(df.anchors)} anchors")

    # 4. Assemble predictions
    rows = []
    n_corrected = 0
    n_flagged = 0

    for pn in plots.index:
        geom_4326 = plots.loc[pn, "geometry"]
        if geom_4326 is None or geom_4326.is_empty:
            n_flagged += 1
            rows.append({
                "plot_number": pn,
                "status": "flagged",
                "confidence": 0.0,
                "geometry": geom_4326,
                "method_note": "empty geometry",
            })
            continue

        result = chamfer_results.get(pn)

        # Flag conditions
        flag_reason = ""
        if result is None:
            flag_reason = "no chamfer result"
        elif result["is_flagged"]:
            flag_reason = result.get("flag_reason", "chamfer flagged")
        else:
            # Physical cap check: block grew too large
            block = block_assignments.get(pn, [pn])
            block_area = sum(areas_m2.get(b, 0) for b in block)
            if block_area > M.PHYSICAL_CAP_FACTOR * median_area:
                flag_reason = f"physical cap hit (block area {block_area:.0f} m²)"

        geom_u = _to_utm(geom_4326, utm_crs)
        cx_m = geom_u.centroid.x
        cy_m = geom_u.centroid.y

        # If chamfer flagged this plot, try the drift field as rescue
        if flag_reason and fields:
            gp_dx, gp_dy, gp_std = DF.assign_sheet(cx_m, cy_m, fields).predict(cx_m, cy_m)
            shift_m = float(np.sqrt(gp_dx**2 + gp_dy**2))
            if gp_std > GP_SIGMA_SCALE_M * 1.5 or shift_m < 0.5:
                # GP too uncertain or negligible shift — stay flagged
                n_flagged += 1
                rows.append({
                    "plot_number": pn,
                    "status": "flagged",
                    "confidence": 0.0,
                    "geometry": geom_4326,
                    "method_note": flag_reason,
                })
                continue
            # GP can rescue this plot
            corrected_4326 = _translate_geom(geom_4326, gp_dx, gp_dy, utm_crs)
            gp_conf = float(np.clip(1.0 - gp_std / GP_SIGMA_SCALE_M, 0.1, 0.6))
            n_corrected += 1
            rows.append({
                "plot_number": pn,
                "status": "corrected",
                "confidence": round(gp_conf, 4),
                "geometry": corrected_4326,
                "method_note": f"GP-rescued (chamfer flagged: {flag_reason}) gp_std={gp_std:.1f}m",
            })
            continue

        if flag_reason:
            n_flagged += 1
            rows.append({
                "plot_number": pn,
                "status": "flagged",
                "confidence": 0.0,
                "geometry": geom_4326,
                "method_note": flag_reason,
            })
            continue

        # Hybrid correction: high-confidence chamfer → use it directly;
        # low-confidence → trust the GP drift field interpolation.
        # Phase 1 showed greedy chamfer is excellent (IoU 0.912) when P2SP < 0.75.
        # GP field should only override when chamfer is uncertain.
        p2sp_ratio = result["p2sp_ratio"]
        CHAMFER_TRUST_P2SP = 0.75  # below this → trust chamfer over GP

        if p2sp_ratio < CHAMFER_TRUST_P2SP:
            # High-confidence chamfer — use its shift directly
            dx_m = result["dx_m"]
            dy_m = result["dy_m"]
            corrected_4326 = _translate_geom(geom_4326, dx_m, dy_m, utm_crs)
            std_m = max(1.0, p2sp_ratio * 3.0)
            method = f"chamfer-direct dx={dx_m:.1f}m dy={dy_m:.1f}m p2sp={p2sp_ratio:.3f}"
        elif fields:
            # Uncertain chamfer — interpolate from drift field
            corrected_4326, std_m = DF.apply_field(geom_4326, cx_m, cy_m, fields, utm_crs)
            method = f"GP-interp p2sp={p2sp_ratio:.3f} gp_std={std_m:.1f}m"
        else:
            # No field — use chamfer anyway
            dx_m = result["dx_m"]
            dy_m = result["dy_m"]
            corrected_4326 = _translate_geom(geom_4326, dx_m, dy_m, utm_crs)
            std_m = 5.0
            method = f"chamfer-fallback dx={dx_m:.1f}m dy={dy_m:.1f}m"

        # Confidence: combine P2SP and GP uncertainty
        chamfer_conf = float(np.clip(1.0 - p2sp_ratio, 0.0, 1.0))
        gp_conf_penalty = float(np.clip(std_m / GP_SIGMA_SCALE_M, 0.0, 0.5))
        confidence = float(np.clip(chamfer_conf - gp_conf_penalty, 0.01, 0.99))

        shift_m = float(np.sqrt(result["dx_m"]**2 + result["dy_m"]**2))
        if shift_m < 1.0:
            confidence = min(confidence, 0.3)

        n_corrected += 1
        rows.append({
            "plot_number": pn,
            "status": "corrected",
            "confidence": round(confidence, 4),
            "geometry": corrected_4326,
            "method_note": method,
        })

    imagery_src.close()

    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326").set_index("plot_number")
    print(f"  corrected={n_corrected}  flagged={n_flagged}")
    elapsed = time.time() - t0
    print(f"  Elapsed: {elapsed:.1f}s ({elapsed/len(plots):.3f}s/plot)")
    return gdf


def score_and_print(gdf: gpd.GeoDataFrame, village_name: str, label: str):
    village = bio.load(DATA_ROOT / village_name)
    sc = _score_fn(gdf.reset_index(), village)
    print(f"\n=== {village_name} · {label} ===")
    print(sc)
    return sc


def main():
    targets = sys.argv[1:] if len(sys.argv) > 1 else VILLAGES
    if targets == ["both"]:
        targets = VILLAGES

    scores = {}

    for vname in targets:
        if vname not in VILLAGES:
            print(f"Unknown village: {vname}. Choose from {VILLAGES}.")
            continue

        gdf = run_village(vname, em_iter=0)

        out_path = DATA_ROOT / vname / "predictions_phase3.geojson"
        bio.write_predictions(out_path, gdf.reset_index())
        print(f"  Written: {out_path}")

        sc = score_and_print(gdf, vname, "Phase 3 block-grow+GP")
        scores[vname] = sc

        # EM iteration 1 (only if time allows — hard cap)
        # Skipped for now: re-run with GP prior as search-range bias

    # Write score summary
    _write_scores_md(scores, targets)


def _write_scores_md(scores: dict, targets: list):
    lines = ["# Phase 3 Scores — Block-Grow + GP Drift Field\n"]
    for vname, sc in scores.items():
        lines.append(f"## {vname}\n")
        lines.append(f"```\n{sc}\n```\n")
    out = DOCS_ROOT / "phase3_scores.md"
    out.write_text("\n".join(lines))
    print(f"\nScores written to {out}")


if __name__ == "__main__":
    main()
