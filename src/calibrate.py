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
    def _safe(v):
        try:
            f = float(v)
            return f if np.isfinite(f) else 0.0
        except (TypeError, ValueError):
            return 0.0
    recorded = _safe(plot_row.get("recorded_area_sqm", 0))
    pot_kharaba = _safe(plot_row.get("pot_kharaba_sqm", 0))
    denominator = recorded + pot_kharaba
    if denominator < 1.0:
        return 1.0
    geom = plot_row["geometry"]
    if geom is None or geom.is_empty:
        return 1.0
    drawn = geom.area * (111320 ** 2)  # rough m² from degrees (for ratio only)
    ratio = drawn / denominator
    return ratio if np.isfinite(ratio) else 1.0


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


def _fit_shift_sampler(fields: list[DF.DriftField]):
    """Fit a GMM over RAW anchor shift vectors (dx,dy) — independent of GP spatial field.

    This decouples synthetic-truth injection from the GP, avoiding the data-leakage
    where agree_m=|chamfer-GP| would be trivially small for injected GP-derived truths.
    Returns fitted GaussianMixture, or None if too few anchors.
    """
    from sklearn.mixture import GaussianMixture
    shifts = np.array([[a.dx_m, a.dy_m] for f in fields for a in f.anchors])
    if len(shifts) < 10:
        return None, shifts
    best = None
    for k in (1, 2, 3):
        if len(shifts) < k * 5:
            break
        try:
            gm = GaussianMixture(n_components=k, covariance_type="full", random_state=0)
            gm.fit(shifts)
            bic = gm.bic(shifts)
            if best is None or bic < best[0]:
                best = (bic, gm)
        except Exception:
            continue
    return (best[1] if best else None), shifts


def build_calibration_set(village_name: str, fields: list[DF.DriftField],
                           utm_crs: str, rng_seed: int = 42) -> list[dict]:
    """Generate synthetic calibration samples with LEAKAGE-FREE shift injection.

    Injected shift sampled from a GMM over RAW anchor shifts (not GP_field(location)),
    so the agree_m=|chamfer-GP| feature is tested on uncontaminated data.

    Key signal: chamfer-GP agreement. A correct chamfer recovers the injected shift;
    whether that agrees with the GP field at this location is then genuinely informative.

    Returns list of dicts: {p2sp, gp_std, agree_m, shift_m, area_ratio, regime, iou, accurate}.
    """
    import rasterio
    rng = np.random.default_rng(rng_seed)
    village = bio.load(DATA_ROOT / village_name)
    plots = village.plots
    plots_u = plots.to_crs(utm_crs)
    areas_m2 = {pn: row.geometry.area for pn, row in plots_u.iterrows()
                if row.geometry is not None and not row.geometry.is_empty}

    # Fit leakage-free shift sampler (GMM on raw anchor shifts)
    shift_gmm, raw_shifts = _fit_shift_sampler(fields)
    if shift_gmm is not None:
        print(f"  Shift sampler: GMM k={shift_gmm.n_components} on {len(raw_shifts)} anchor shifts")
    else:
        print(f"  Shift sampler: empirical resample on {len(raw_shifts)} anchor shifts")

    # Stratified sample by regime
    regime_plots: dict[str, list] = {r: [] for r in REGIMES}
    for pn, area in areas_m2.items():
        regime_plots[_classify_regime(area)].append(pn)

    sample_pns = []
    for regime in REGIMES:
        pool = regime_plots[regime]
        n = min(N_SYNTH_PER_REGIME, len(pool))
        sample_pns.extend(rng.choice(pool, size=n, replace=False).tolist())

    # Pre-sample injected shifts (leakage-free)
    n_needed = len(sample_pns)
    if shift_gmm is not None:
        injected_shifts, _ = shift_gmm.sample(n_needed)
        injected_shifts = rng.permutation(injected_shifts)  # decorrelate from GMM component order
    else:
        idx = rng.integers(0, len(raw_shifts), size=n_needed)
        injected_shifts = raw_shifts[idx] + rng.normal(0, INJECT_NOISE_M, size=(n_needed, 2))

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

        # GP field prediction at this location (for agree_m feature only)
        df = DF.assign_sheet(cx_m, cy_m, fields)
        gp_dx, gp_dy, gp_std = df.predict(cx_m, cy_m)

        # --- Displacement-recovery test (image-grounded, no displacement-vs-image bug) ---
        # Step 1: reference chamfer on the plot AS-IS → image-derived "truth" landing L.
        ref = M.chamfer_geom(geom_4326, img_src, village.boundaries_path, f_img, f_4326, img_crs)
        if ref["is_flagged"]:
            continue  # no real edge to anchor truth → skip (can't establish ground truth)
        L_4326 = _translate(geom_4326, ref["dx_m"], ref["dy_m"], utm_crs)

        # Step 2: displace by leakage-free injected shift d (GMM-sampled).
        inj_dx, inj_dy = float(injected_shifts[i][0]), float(injected_shifts[i][1])
        inj_dx = float(np.clip(inj_dx, -MAX_INJECT_SHIFT_M, MAX_INJECT_SHIFT_M))
        inj_dy = float(np.clip(inj_dy, -MAX_INJECT_SHIFT_M, MAX_INJECT_SHIFT_M))
        inj_mag = float(np.sqrt(inj_dx**2 + inj_dy**2))
        if inj_mag < MIN_INJECT_SHIFT_M:
            continue  # trivial displacement — chamfer recovers trivially, biases calibration
        disp_4326 = _translate(L_4326, inj_dx, inj_dy, utm_crs)  # move L away by d

        plot_row = plots.loc[pn]
        ar = _area_ratio(plot_row)

        # Step 3: chamfer on displaced plot — does it recover back to L?
        rec = M.chamfer_geom(disp_4326, img_src, village.boundaries_path, f_img, f_4326, img_crs)
        if rec["is_flagged"]:
            samples.append({
                "p2sp": 1.0, "gp_std": gp_std, "agree_m": M.SEARCH_RADIUS_M,
                "shift_m": inj_mag, "area_ratio": float(np.clip(ar, 0.3, 3.0)),
                "regime": regime, "iou": 0.0, "accurate": False,
            })
            continue

        corrected = _translate(disp_4326, rec["dx_m"], rec["dy_m"], utm_crs)
        iou_val = _iou(corrected, L_4326)
        accurate = iou_val >= 0.5

        # Net shift from original geom = injection + recovery. Compare to GP field at this loc.
        # No leakage: inj is GMM-sampled (not GP), recovery is image-driven, L is image-derived.
        net_dx = inj_dx + rec["dx_m"] + ref["dx_m"]
        net_dy = inj_dy + rec["dy_m"] + ref["dy_m"]
        agree_m = float(np.sqrt((net_dx - gp_dx)**2 + (net_dy - gp_dy)**2))

        samples.append({
            "p2sp":       rec["p2sp_ratio"],
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


FEATURE_NAMES = ["p2sp", "agree_m", "gp_std", "abs_log_area_ratio"]


def _feature_vector(p2sp: float, agree_m: float, gp_std: float, area_ratio: float) -> list[float]:
    """Raw feature vector for the logistic regression. No hand-set weights.

    abs(log(area_ratio)) is monotone: 0 at ratio=1 (good), larger = worse (either direction).
    LR learns the sign/magnitude of every weight from the synthetic labels.
    """
    def _fin(v, default):
        return float(v) if (v is not None and np.isfinite(v)) else default
    p2sp = _fin(p2sp, 1.0)
    agree_m = _fin(agree_m, 28.0)
    gp_std = _fin(gp_std, 5.0)
    ar = max(_fin(area_ratio, 1.0), 1e-3)
    return [p2sp, agree_m, gp_std, abs(float(np.log(ar)))]


class CalibrationModel:
    """LogisticRegression (learns feature weights) → IsotonicRegression (monotone calibration).

    Per Gemini directive: replace hand-coded score formula with a learned 1D logit,
    then enforce strict monotone calibration via isotonic on that logit.
    """
    def __init__(self):
        self.scaler = None
        self.lr = None
        self.iso = None

    def fit(self, samples: list[dict]):
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler

        X = np.array([_feature_vector(s["p2sp"], s["agree_m"], s["gp_std"], s["area_ratio"])
                      for s in samples])
        y = np.array([float(s["accurate"]) for s in samples])

        self.scaler = StandardScaler().fit(X)
        Xs = self.scaler.transform(X)
        self.lr = LogisticRegression(class_weight="balanced", max_iter=1000)
        self.lr.fit(Xs, y)

        logits = self.lr.predict_proba(Xs)[:, 1]
        self.iso = IsotonicRegression(increasing=True, out_of_bounds="clip")
        self.iso.fit(logits, y)
        return self

    def predict(self, p2sp: float, agree_m: float, gp_std: float, area_ratio: float) -> float:
        x = np.array([_feature_vector(p2sp, agree_m, gp_std, area_ratio)])
        xs = self.scaler.transform(x)
        logit = float(self.lr.predict_proba(xs)[0, 1])
        prob = float(self.iso.predict([logit])[0])
        return float(np.clip(prob, 0.01, 0.99))

    def logit_scores(self, samples: list[dict]) -> np.ndarray:
        """LR probability (pre-isotonic) for each sample — used for AUC eval."""
        X = np.array([_feature_vector(s["p2sp"], s["agree_m"], s["gp_std"], s["area_ratio"])
                      for s in samples])
        Xs = self.scaler.transform(X)
        return self.lr.predict_proba(Xs)[:, 1]

    def weights(self) -> dict:
        return {name: float(w) for name, w in zip(FEATURE_NAMES, self.lr.coef_[0])}


def recalibrate_predictions(village_name: str, model: CalibrationModel) -> gpd.GeoDataFrame:
    """Load Phase 3 predictions, replace confidence with calibrated P(IoU>=0.5)."""
    pred_path = DATA_ROOT / village_name / "predictions_phase3.geojson"
    gdf = gpd.read_file(pred_path)

    # area_ratio per plot from original village data
    village = bio.load(DATA_ROOT / village_name)
    ar_by_pn = {}
    for pn, row in village.plots.iterrows():
        ar_by_pn[str(pn)] = float(np.clip(_area_ratio(row), 0.3, 3.0))

    def _recalibrate_row(row):
        if row["status"] != "corrected":
            return row["confidence"]
        note = str(row.get("method_note", ""))
        p2sp = 1.0
        if "p2sp=" in note:
            try: p2sp = float(note.split("p2sp=")[1].split()[0])
            except Exception: pass
        gp_std = 5.0
        if "gp_std=" in note:
            try: gp_std = float(note.split("gp_std=")[1].split("m")[0])
            except Exception: pass
        elif "std=" in note:
            try: gp_std = float(note.split("std=")[1].split("m")[0])
            except Exception: pass
        agree_m = 28.0  # default: worst case (no agreement info, e.g. GP-rescue)
        if "agree=" in note:
            try: agree_m = float(note.split("agree=")[1].split("m")[0])
            except Exception: pass
        ar = ar_by_pn.get(str(row["plot_number"]), 1.0)
        return model.predict(p2sp, agree_m, gp_std, ar)

    gdf["confidence"] = gdf.apply(_recalibrate_row, axis=1)
    return gdf


def reliability_diagram(samples: list[dict], model: CalibrationModel,
                         village_name: str):
    """Save reliability diagram to docs/reliability_<village>.png."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return

    labels = np.array([float(s["accurate"]) for s in samples])
    calibrated = np.array([model.predict(s["p2sp"], s["agree_m"], s["gp_std"], s["area_ratio"])
                           for s in samples])

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

    # Build synthetic calibration set (leakage-free injection)
    samples = build_calibration_set(village_name, fields, utm_crs)
    if len(samples) < 20:
        print(f"  Too few samples ({len(samples)}) — skip calibration")
        return None

    # Fit LogisticRegression → Isotonic
    model = CalibrationModel().fit(samples)
    print(f"  LR feature weights (standardized): {model.weights()}")

    # Reliability diagram
    reliability_diagram(samples, model, village_name)

    # Honest AUC: 5-fold cross-validated on the LR logit (no train-on-test)
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import cross_val_predict
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    X = np.array([_feature_vector(s["p2sp"], s["agree_m"], s["gp_std"], s["area_ratio"]) for s in samples])
    y = np.array([float(s["accurate"]) for s in samples])
    labels = y
    if len(np.unique(labels)) == 2:
        Xs = StandardScaler().fit_transform(X)
        cv_prob = cross_val_predict(
            LogisticRegression(class_weight="balanced", max_iter=1000),
            Xs, y, cv=5, method="predict_proba")[:, 1]
        auc_cv = roc_auc_score(y, cv_prob)
        auc_train = roc_auc_score(y, model.logit_scores(samples))
        print(f"  Synthetic AUC: cross-val={auc_cv:.3f}  (train-fit={auc_train:.3f})")

    # Save calibration model
    cal_path = DOCS_ROOT / f"calibration_{village_name}.pkl"
    with open(cal_path, "wb") as f:
        pickle.dump({"model": model, "samples": len(samples)}, f)
    print(f"  Calibration saved → {cal_path}")

    # Re-calibrate predictions
    gdf = recalibrate_predictions(village_name, model)
    out_path = DATA_ROOT / village_name / "predictions_calibrated.geojson"
    gdf.to_file(out_path, driver="GeoJSON")
    print(f"  Calibrated predictions → {out_path}")

    sc = _score_fn(gdf, village)
    print(f"\n=== {village_name} · calibrated ===")
    print(sc)

    return model


if __name__ == "__main__":
    targets = sys.argv[1:] if len(sys.argv) > 1 else ["vadnerbhairav", "malatavadi"]
    if targets == ["both"]:
        targets = ["vadnerbhairav", "malatavadi"]
    for vname in targets:
        run_calibration(vname)
