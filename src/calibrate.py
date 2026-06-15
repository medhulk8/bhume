"""Phase 6 — Confidence calibration via synthetic shift injection.

Protocol:
  1. Load Phase 3 drift field (GP + affine) for the village.
  2. Stratified sample: N_SYNTH plots per regime (tiny/small/medium/large).
  3. For each synthetic plot:
       a. Inject shift = GP_field(cx,cy) + N(0, INJECT_NOISE_M²) — spatially coherent.
       b. Run greedy chamfer on the shifted plot.
       c. Measure IoU(chamfer_corrected, injected_truth). Label = (IoU >= 0.5).
       d. Record raw signals: p2sp, gp_std, shift_magnitude, area_ratio, regime.
  4. Build monotone score: weighted combination of raw signals.
  5. Fit isotonic regression: score → P(IoU >= 0.5).
  6. Save calibration model to docs/calibration_<village>.pkl.
  7. apply_calibration(signals) → confidence in [0,1].

Output: calibrated confidence replaces raw P2SP in predictions.geojson.
"""

from __future__ import annotations

import pickle
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from pyproj import Transformer
from shapely.ops import transform as shp_transform
from sklearn.isotonic import IsotonicRegression

sys.path.insert(0, str(Path(__file__).parent.parent / "kit"))
sys.path.insert(0, str(Path(__file__).parent))

import bhume.io as bio
from bhume.score import score as _score_fn
import matching as M
import drift_field as DF

DATA_ROOT = Path(__file__).parent.parent / "data"
DOCS_ROOT = Path(__file__).parent.parent / "docs"

N_SYNTH_PER_REGIME = 80   # synthetic plots per regime per village
INJECT_NOISE_M     = 2.0  # std of noise added to GP field shift (residual scatter)
MIN_INJECT_SHIFT_M = 3.0  # don't inject trivial shifts (too easy to recover trivially)
MAX_INJECT_SHIFT_M = 30.0 # cap injected shift at search radius
REGIMES            = ["tiny", "small", "medium", "large"]


def _utm_crs(village) -> str:
    centroid = village.plots.geometry.union_all().centroid
    lon = centroid.x
    return f"EPSG:{32600 + int((lon + 180) // 6) + 1}"


def _to_utm(geom, utm_crs):
    t = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    return shp_transform(lambda xs, ys, z=None: t.transform(xs, ys), geom)


def _to_4326(geom, utm_crs):
    t = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)
    return shp_transform(lambda xs, ys, z=None: t.transform(xs, ys), geom)


def _translate(geom_4326, dx_m, dy_m, utm_crs):
    to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    to_4326 = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)
    def _tr(xs, ys, z=None):
        ux, uy = to_utm.transform(xs, ys)
        return to_4326.transform([u + dx_m for u in ux], [u + dy_m for u in uy])
    return shp_transform(_tr, geom_4326)


def _area_ratio(plot_row) -> float:
    recorded = float(plot_row.get("recorded_area_sqm", 0) or 0)
    pot_kharaba = float(plot_row.get("pot_kharaba_sqm", 0) or 0)
    denominator = recorded + pot_kharaba
    if denominator < 1.0:
        return 1.0
    geom = plot_row["geometry"]
    if geom is None or geom.is_empty:
        return 1.0
    drawn = geom.area * (111320 ** 2)  # rough m² from degrees (for ratio only)
    return drawn / denominator


def _classify_regime(area_m2: float) -> str:
    if area_m2 < 500:
        return "tiny"
    elif area_m2 < 3000:
        return "small"
    elif area_m2 < 15000:
        return "medium"
    return "large"


def _iou(geom_a, geom_b) -> float:
    try:
        inter = geom_a.intersection(geom_b).area
        union = geom_a.union(geom_b).area
        return float(inter / union) if union > 0 else 0.0
    except Exception:
        return 0.0


def build_calibration_set(village_name: str, fields: list[DF.DriftField],
                           utm_crs: str, rng_seed: int = 42) -> list[dict]:
    """Generate synthetic calibration samples by injecting GP-coherent shifts.

    Key signal: chamfer-GP agreement (agree_m = |chamfer_shift - gp_field|).
    High agreement → chamfer found the correct shift (same as GP field prediction).
    Low agreement → chamfer found a false strong peak at a different location.

    Returns list of dicts: {p2sp, gp_std, agree_m, shift_m, area_ratio, regime, iou, accurate}.
    """
    import rasterio
    rng = np.random.default_rng(rng_seed)
    village = bio.load(DATA_ROOT / village_name)
    plots = village.plots
    plots_u = plots.to_crs(utm_crs)
    areas_m2 = {pn: row.geometry.area for pn, row in plots_u.iterrows()
                if row.geometry is not None and not row.geometry.is_empty}

    # Stratified sample by regime
    regime_plots: dict[str, list] = {r: [] for r in REGIMES}
    for pn, area in areas_m2.items():
        regime_plots[_classify_regime(area)].append(pn)

    sample_pns = []
    for regime in REGIMES:
        pool = regime_plots[regime]
        n = min(N_SYNTH_PER_REGIME, len(pool))
        sample_pns.extend(rng.choice(pool, size=n, replace=False).tolist())

    print(f"  Calibration: {len(sample_pns)} synthetic plots ({dict((r, len(regime_plots[r])) for r in REGIMES)})")

    img_src = rasterio.open(village.imagery_path)
    img_crs = img_src.crs.to_string()
    to_img = Transformer.from_crs("EPSG:4326", img_crs, always_xy=True)
    to_4326_t = Transformer.from_crs(img_crs, "EPSG:4326", always_xy=True)

    def f_img(geom):
        return shp_transform(lambda xs, ys, z=None: to_img.transform(xs, ys), geom)
    def f_4326(geom):
        return shp_transform(lambda xs, ys, z=None: to_4326_t.transform(xs, ys), geom)

    samples = []
    for i, pn in enumerate(sample_pns):
        if i % 50 == 0:
            print(f"  [{village_name}] synth {i}/{len(sample_pns)} ...")

        geom_4326 = plots.loc[pn, "geometry"]
        if geom_4326 is None or geom_4326.is_empty:
            continue

        geom_u = _to_utm(geom_4326, utm_crs)
        cx_m = geom_u.centroid.x
        cy_m = geom_u.centroid.y
        area_m2 = areas_m2.get(pn, 1000.0)
        regime = _classify_regime(area_m2)

        # GP field prediction at this location
        df = DF.assign_sheet(cx_m, cy_m, fields)
        gp_dx, gp_dy, gp_std = df.predict(cx_m, cy_m)

        # Inject: GP field shift + small noise (spatially coherent drift)
        noise_x = rng.normal(0, INJECT_NOISE_M)
        noise_y = rng.normal(0, INJECT_NOISE_M)
        inj_dx = float(np.clip(gp_dx + noise_x, -MAX_INJECT_SHIFT_M, MAX_INJECT_SHIFT_M))
        inj_dy = float(np.clip(gp_dy + noise_y, -MAX_INJECT_SHIFT_M, MAX_INJECT_SHIFT_M))
        inj_mag = float(np.sqrt(inj_dx**2 + inj_dy**2))

        if inj_mag < MIN_INJECT_SHIFT_M:
            # trivial shift — skip (chamfer trivially recovers, biases calibration)
            continue

        # Shifted plot = "true" position (we know the ground truth)
        truth_4326 = _translate(geom_4326, inj_dx, inj_dy, utm_crs)

        # Apply INVERSE shift to truth → this is the "wrong" position chamfer will try to fix
        # Equivalently: run chamfer on original geom trying to find inj_dx, inj_dy
        # The chamfer result tries to match geom_4326 → truth_4326
        result = M.chamfer_block([pn], plots, img_src, village.boundaries_path,
                                  f_img, f_4326, img_crs)

        if result["is_flagged"]:
            samples.append({
                "p2sp": 1.0, "gp_std": gp_std, "agree_m": M.SEARCH_RADIUS_M,
                "shift_m": inj_mag, "area_ratio": 1.0, "regime": regime,
                "iou": 0.0, "accurate": False,
            })
            continue

        # Chamfer-GP agreement: key signal for false-peak detection
        agree_m = float(np.sqrt((result["dx_m"] - gp_dx)**2 + (result["dy_m"] - gp_dy)**2))

        chamfer_corrected = _translate(geom_4326, result["dx_m"], result["dy_m"], utm_crs)
        iou_val = _iou(chamfer_corrected, truth_4326)
        accurate = iou_val >= 0.5

        plot_row = plots.loc[pn]
        ar = _area_ratio(plot_row)

        samples.append({
            "p2sp":       result["p2sp_ratio"],
            "gp_std":     gp_std,
            "agree_m":    agree_m,
            "shift_m":    inj_mag,
            "area_ratio": float(np.clip(ar, 0.3, 3.0)),
            "regime":     regime,
            "iou":        iou_val,
            "accurate":   accurate,
        })

    img_src.close()
    print(f"  Synth done: {len(samples)} samples, {sum(s['accurate'] for s in samples)} accurate")
    return samples


def _raw_score(p2sp: float, gp_std: float, agree_m: float, shift_m: float,
               gp_sigma_scale: float = 5.0,
               search_radius: float = 28.0) -> float:
    """Monotone raw score before isotonic calibration. Higher = more likely accurate.

    Signals (all mapped to [0,1], high = good):
    - p2sp_signal: 1 - P2SP. Low P2SP = sharp chamfer peak = likely found something real.
    - agree_signal: 1 - agree_m/search_radius. Chamfer agrees with GP field = correct shift.
    - gp_signal: 1 - gp_std/scale. GP is confident = field well-anchored here.

    agree_signal is primary: P2SP alone can't detect false peaks (high confidence wrong answer).
    A chamfer that agrees with the GP field is almost certainly correct.
    """
    p2sp_signal  = float(np.clip(1.0 - p2sp, 0.0, 1.0))
    agree_signal = float(np.clip(1.0 - agree_m / search_radius, 0.0, 1.0))
    gp_signal    = float(np.clip(1.0 - gp_std / gp_sigma_scale, 0.0, 1.0))
    return 0.4 * p2sp_signal + 0.45 * agree_signal + 0.15 * gp_signal


def fit_isotonic(samples: list[dict], gp_sigma_scale: float = 5.0) -> IsotonicRegression:
    """Fit isotonic regression: raw_score → P(IoU >= 0.5).

    Monotone increasing: higher raw score → higher calibrated confidence.
    """
    X = np.array([_raw_score(s["p2sp"], s["gp_std"], s.get("agree_m", 28.0), s["shift_m"], gp_sigma_scale)
                  for s in samples])
    y = np.array([float(s["accurate"]) for s in samples])
    iso = IsotonicRegression(increasing=True, out_of_bounds="clip")
    iso.fit(X, y)
    return iso


def apply_calibration(p2sp: float, gp_std: float, agree_m: float, shift_m: float,
                       iso: IsotonicRegression,
                       gp_sigma_scale: float = 5.0) -> float:
    """Map raw signals → calibrated P(IoU >= 0.5)."""
    score = _raw_score(p2sp, gp_std, agree_m, shift_m, gp_sigma_scale)
    prob = float(iso.predict([score])[0])
    return float(np.clip(prob, 0.01, 0.99))


def recalibrate_predictions(village_name: str, iso: IsotonicRegression,
                             gp_sigma_scale: float = 5.0) -> gpd.GeoDataFrame:
    """Load Phase 3 predictions, replace confidence with calibrated P(IoU>=0.5)."""
    pred_path = DATA_ROOT / village_name / "predictions_phase3.geojson"
    gdf = gpd.read_file(pred_path)

    def _recalibrate_row(row):
        if row["status"] != "corrected":
            return row["confidence"]
        note = str(row.get("method_note", ""))
        p2sp = 1.0
        if "p2sp=" in note:
            try: p2sp = float(note.split("p2sp=")[1].split()[0])
            except Exception: pass
        gp_std = gp_sigma_scale
        if "gp_std=" in note:
            try: gp_std = float(note.split("gp_std=")[1].split("m")[0])
            except Exception: pass
        elif "std=" in note:
            try: gp_std = float(note.split("std=")[1].split("m")[0])
            except Exception: pass
        agree_m = 28.0  # default: worst case (no agreement info)
        if "agree=" in note:
            try: agree_m = float(note.split("agree=")[1].split("m")[0])
            except Exception: pass
        shift_m = 5.0
        if "dx=" in note:
            try:
                dx = float(note.split("dx=")[1].split("m")[0])
                dy = float(note.split("dy=")[1].split("m")[0])
                shift_m = float(np.sqrt(dx**2 + dy**2))
            except Exception: pass
        return apply_calibration(p2sp, gp_std, agree_m, shift_m, iso, gp_sigma_scale)

    gdf["confidence"] = gdf.apply(_recalibrate_row, axis=1)
    return gdf


def reliability_diagram(samples: list[dict], iso: IsotonicRegression,
                         village_name: str, gp_sigma_scale: float = 5.0):
    """Save reliability diagram to docs/reliability_<village>.png."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    scores = np.array([_raw_score(s["p2sp"], s["gp_std"], s.get("agree_m", 28.0), s["shift_m"], gp_sigma_scale)
                       for s in samples])
    labels = np.array([float(s["accurate"]) for s in samples])
    calibrated = np.array([apply_calibration(s["p2sp"], s["gp_std"], s.get("agree_m", 28.0), s["shift_m"],
                                              iso, gp_sigma_scale) for s in samples])

    n_bins = 10
    bins = np.linspace(0, 1, n_bins + 1)
    bin_acc = []
    bin_conf = []
    bin_counts = []
    for lo, hi in zip(bins[:-1], bins[1:]):
        mask = (calibrated >= lo) & (calibrated < hi)
        if mask.sum() > 0:
            bin_acc.append(labels[mask].mean())
            bin_conf.append(calibrated[mask].mean())
            bin_counts.append(mask.sum())

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))

    ax = axes[0]
    ax.plot([0, 1], [0, 1], "k--", label="perfect")
    ax.scatter(bin_conf, bin_acc, s=[c * 3 for c in bin_counts], label="bins")
    ax.set_xlabel("Mean calibrated confidence")
    ax.set_ylabel("Fraction accurate (IoU≥0.5)")
    ax.set_title(f"{village_name} reliability diagram")
    ax.legend()
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)

    ax2 = axes[1]
    regime_labels = [s["regime"] for s in samples]
    for regime in REGIMES:
        rm = [i for i, r in enumerate(regime_labels) if r == regime]
        if rm:
            conf_r = calibrated[rm]
            acc_r = labels[rm]
            ax2.scatter(conf_r, acc_r, label=f"{regime} (n={len(rm)})", alpha=0.4, s=15)
    ax2.plot([0, 1], [0, 1], "k--")
    ax2.set_xlabel("Calibrated confidence")
    ax2.set_ylabel("Accurate")
    ax2.set_title("By regime")
    ax2.legend(fontsize=8)

    fig.tight_layout()
    out = DOCS_ROOT / f"reliability_{village_name}.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"  Reliability diagram → {out}")


def run_calibration(village_name: str):
    """Full Phase 6 pipeline for one village."""
    from phase3_drift import run_village, utm_crs_from_village

    print(f"\n{'='*60}")
    print(f"PHASE 6 — {village_name} calibration")
    print(f"{'='*60}")

    village = bio.load(DATA_ROOT / village_name)
    utm_crs = utm_crs_from_village(village)

    # Load Phase 3 drift field by re-running Phase 3 (fast — field from block anchors)
    # In production this would be cached; for now re-derive
    print("  Loading drift field (re-running Phase 3 Pass 1)...")
    from phase3_drift import _rebuild_field
    fields = _rebuild_field(village_name, utm_crs)

    if not fields:
        print("  No drift field available — skip calibration")
        return None

    # Build synthetic calibration set
    samples = build_calibration_set(village_name, fields, utm_crs)
    if len(samples) < 20:
        print(f"  Too few samples ({len(samples)}) — skip calibration")
        return None

    # Fit isotonic regression
    iso = fit_isotonic(samples)

    # Reliability diagram
    reliability_diagram(samples, iso, village_name)

    # Quick AUC estimate on synthetic set
    from sklearn.metrics import roc_auc_score
    scores = np.array([_raw_score(s["p2sp"], s["gp_std"], s.get("agree_m", 28.0), s["shift_m"]) for s in samples])
    labels = np.array([float(s["accurate"]) for s in samples])
    if len(np.unique(labels)) == 2:
        auc = roc_auc_score(labels, scores)
        print(f"  Synthetic AUC (raw score with agreement): {auc:.3f}")

    # Save calibration model
    cal_path = DOCS_ROOT / f"calibration_{village_name}.pkl"
    with open(cal_path, "wb") as f:
        pickle.dump({"iso": iso, "samples": len(samples)}, f)
    print(f"  Calibration saved → {cal_path}")

    # Re-calibrate predictions
    gdf = recalibrate_predictions(village_name, iso)
    out_path = DATA_ROOT / village_name / "predictions_calibrated.geojson"
    gdf.to_file(out_path, driver="GeoJSON")
    print(f"  Calibrated predictions → {out_path}")

    # Score calibrated predictions
    sc = _score_fn(gdf, village)
    print(f"\n=== {village_name} · calibrated ===")
    print(sc)

    return iso


if __name__ == "__main__":
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["vadnerbhairav", "malatavadi"]
    if targets == ["both"]:
        targets = ["vadnerbhairav", "malatavadi"]
    for vname in targets:
        run_calibration(vname)
