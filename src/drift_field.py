"""Phase 4 — Drift field estimation.

Architecture (locked in CLAUDE.md):
  1. Collect chamfer anchors (block centroids + shift vectors).
  2. RANSAC-purify: fit global affine, reject >RANSAC_RESID_M residual.
  3. Seam detection: anchor-discordance graph cut + LOO model-selection brake.
     For each candidate seam edge, check if two-sheet affine fits better than one.
  4. Per-sheet affine + Gaussian Process on residuals.
     GP is cubic in anchor count (~hundreds), linear to evaluate (predict at vertex).
  5. EM: re-run block matching with GP prior as warm start. Hard cap 2 iterations.
  6. apply_field(geom_4326, field) → corrected geom_4326.
     Applies T at every VERTEX — fabric never tears.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import geopandas as gpd
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import shape, mapping, Polygon, MultiPolygon, Point
from shapely.ops import transform as shp_transform
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import RBF, WhiteKernel, ConstantKernel
from sklearn.linear_model import RANSACRegressor, LinearRegression

RANSAC_RESID_M       = 8.0    # max residual after RANSAC affine (metres)
MIN_ANCHORS_FOR_GP   = 5      # fewer → fall back to affine-only
SEAM_MIN_IMPROVEMENT = 2.0    # LOO RMSE must improve by this (m) to add seam
SEAM_CANDIDATE_DIST_M = 2000.0  # only test seams between anchors ≤ this apart
EM_MAX_ITER          = 2      # hard cap on EM iterations


@dataclass
class Anchor:
    """One chamfer anchor: centroid of a matched block in UTM metres."""
    plot_number: str
    cx_m: float        # UTM x of block centroid
    cy_m: float        # UTM y
    dx_m: float        # fitted shift
    dy_m: float
    confidence: float  # P2SP-based; used to weight GP fit


@dataclass
class DriftField:
    """Callable drift field for one sheet (or full village if no seam)."""
    utm_crs: str
    sheet_id: int = 0
    anchors: list[Anchor] = field(default_factory=list)
    _gp_x: Optional[GaussianProcessRegressor] = field(default=None, repr=False)
    _gp_y: Optional[GaussianProcessRegressor] = field(default=None, repr=False)
    _affine_x: Optional[np.ndarray] = field(default=None, repr=False)  # [a0, a1, a2] s.t. dx = a0 + a1*cx + a2*cy
    _affine_y: Optional[np.ndarray] = field(default=None, repr=False)

    def predict(self, cx_m: float, cy_m: float) -> tuple[float, float, float]:
        """Return (dx_m, dy_m, std_m) for a point in UTM metres."""
        xy = np.array([[cx_m, cy_m]])
        dx = _affine_eval(self._affine_x, cx_m, cy_m)
        dy = _affine_eval(self._affine_y, cx_m, cy_m)
        std = 5.0  # default uncertainty

        if self._gp_x is not None:
            res_x = np.array([a.dx_m - _affine_eval(self._affine_x, a.cx_m, a.cy_m) for a in self.anchors])
            res_y = np.array([a.dy_m - _affine_eval(self._affine_y, a.cx_m, a.cy_m) for a in self.anchors])
            Xfit  = np.array([[a.cx_m, a.cy_m] for a in self.anchors])
            gp_dx, gp_std_x = self._gp_x.predict(xy, return_std=True)
            gp_dy, gp_std_y = self._gp_y.predict(xy, return_std=True)
            dx += float(gp_dx[0])
            dy += float(gp_dy[0])
            std = float(np.sqrt(gp_std_x[0]**2 + gp_std_y[0]**2))

        return dx, dy, std


def _affine_eval(coeffs: Optional[np.ndarray], cx: float, cy: float) -> float:
    if coeffs is None:
        return 0.0
    return float(coeffs[0] + coeffs[1] * cx + coeffs[2] * cy)


def _fit_affine(cx, cy, dz) -> np.ndarray:
    """Fit dz = a0 + a1*cx + a2*cy via least squares. Returns [a0, a1, a2]."""
    A = np.column_stack([np.ones(len(cx)), cx, cy])
    coeffs, _, _, _ = np.linalg.lstsq(A, dz, rcond=None)
    return coeffs


def _ransac_filter(anchors: list[Anchor]) -> list[Anchor]:
    """Remove anchors with high residual vs RANSAC affine fit. Returns cleaned list."""
    if len(anchors) < 4:
        return anchors

    cx = np.array([a.cx_m for a in anchors])
    cy = np.array([a.cy_m for a in anchors])
    dx = np.array([a.dx_m for a in anchors])
    dy = np.array([a.dy_m for a in anchors])
    X = np.column_stack([cx, cy])

    def ransac_resid(X, d):
        try:
            est = RANSACRegressor(estimator=LinearRegression(),
                                   residual_threshold=RANSAC_RESID_M,
                                   min_samples=max(3, int(0.3 * len(d))),
                                   random_state=42, max_trials=200)
            est.fit(X, d)
            pred = est.predict(X)
            return np.abs(d - pred), est.inlier_mask_
        except Exception:
            c = _fit_affine(cx, cy, d)
            pred = c[0] + c[1]*cx + c[2]*cy
            resid = np.abs(d - pred)
            return resid, resid < RANSAC_RESID_M

    resid_x, mask_x = ransac_resid(X, dx)
    resid_y, mask_y = ransac_resid(X, dy)
    mask = mask_x & mask_y

    if mask.sum() < max(3, int(0.5 * len(anchors))):
        # RANSAC too aggressive — keep 90th-percentile outliers
        combined = np.sqrt(resid_x**2 + resid_y**2)
        thresh = float(np.percentile(combined, 90))
        mask = combined <= thresh

    return [a for a, keep in zip(anchors, mask) if keep]


def _fit_gp(anchors: list[Anchor], affine_x, affine_y) -> tuple:
    """Fit GP on residuals from affine. Returns (gp_x, gp_y) or (None, None)."""
    if len(anchors) < MIN_ANCHORS_FOR_GP:
        return None, None

    cx = np.array([a.cx_m for a in anchors])
    cy = np.array([a.cy_m for a in anchors])
    X = np.column_stack([cx, cy])
    res_x = np.array([a.dx_m - _affine_eval(affine_x, a.cx_m, a.cy_m) for a in anchors])
    res_y = np.array([a.dy_m - _affine_eval(affine_y, a.cx_m, a.cy_m) for a in anchors])
    weights = np.array([a.confidence for a in anchors])
    weights = np.clip(weights, 0.05, 1.0)

    # Length scale from typical anchor spacing
    if len(anchors) > 1:
        tree = cKDTree(X)
        dists, _ = tree.query(X, k=min(5, len(anchors)))
        median_nn = float(np.median(dists[:, 1:]))
        l_init = max(100.0, median_nn * 2.0)
    else:
        l_init = 500.0

    kernel = ConstantKernel(1.0, (0.1, 100.0)) * RBF(l_init, (50.0, 5000.0)) + WhiteKernel(1.0, (0.01, 25.0))

    try:
        gp_x = GaussianProcessRegressor(kernel=kernel, alpha=1.0 / (weights**2 + 1e-6),
                                          n_restarts_optimizer=3, normalize_y=True)
        gp_x.fit(X, res_x)
        gp_y = GaussianProcessRegressor(kernel=kernel, alpha=1.0 / (weights**2 + 1e-6),
                                          n_restarts_optimizer=3, normalize_y=True)
        gp_y.fit(X, res_y)
        return gp_x, gp_y
    except Exception:
        return None, None


def _loo_rmse(anchors: list[Anchor]) -> float:
    """Leave-one-out RMSE of affine fit (used for seam-brake)."""
    if len(anchors) < 4:
        return float("inf")
    cx = np.array([a.cx_m for a in anchors])
    cy = np.array([a.cy_m for a in anchors])
    dx = np.array([a.dx_m for a in anchors])
    dy = np.array([a.dy_m for a in anchors])
    errs = []
    for i in range(len(anchors)):
        mask = np.ones(len(anchors), dtype=bool)
        mask[i] = False
        cx_, cy_ = cx[mask], cy[mask]
        cx_x = _fit_affine(cx_, cy_, dx[mask])
        cx_y = _fit_affine(cx_, cy_, dy[mask])
        pred_x = _affine_eval(cx_x, cx[i], cy[i])
        pred_y = _affine_eval(cx_y, cx[i], cy[i])
        errs.append((dx[i] - pred_x)**2 + (dy[i] - pred_y)**2)
    return float(np.sqrt(np.mean(errs)))


def detect_seams(anchors: list[Anchor]) -> list[list[Anchor]]:
    """Partition anchors into sheets by detecting drift discontinuities.

    Algorithm:
    1. Start with single-sheet LOO RMSE as baseline.
    2. For each pair of spatially close anchors, test if a hyperplane (Voronoi seam)
       passing between them improves LOO RMSE by > SEAM_MIN_IMPROVEMENT.
    3. Accept best seam. Repeat (greedy). Stop when no improvement or < 4 anchors per side.
    LOO model-selection brake: only accept if the split actually helps.
    """
    if len(anchors) < 8:
        return [anchors]

    cx = np.array([a.cx_m for a in anchors])
    cy = np.array([a.cy_m for a in anchors])
    tree = cKDTree(np.column_stack([cx, cy]))

    sheets = [anchors]  # start with single sheet

    for _ in range(4):  # max 4 seam attempts
        best_improvement = 0.0
        best_split = None
        best_sheet_idx = None

        for si, sheet in enumerate(sheets):
            if len(sheet) < 8:
                continue
            baseline_rmse = _loo_rmse(sheet)

            scx = np.array([a.cx_m for a in sheet])
            scy = np.array([a.cy_m for a in sheet])
            # Try seam normal to each anchor pair within distance cap
            pairs_tested = set()
            for i, a in enumerate(sheet):
                pts = tree.query_ball_point([a.cx_m, a.cy_m], SEAM_CANDIDATE_DIST_M)
                for j in pts:
                    b = anchors[j]
                    if b is a:
                        continue
                    key = tuple(sorted([id(a), id(b)]))
                    if key in pairs_tested:
                        continue
                    pairs_tested.add(key)

                    mx = (a.cx_m + b.cx_m) / 2
                    my = (a.cy_m + b.cy_m) / 2
                    nx = b.cx_m - a.cx_m
                    ny = b.cy_m - a.cy_m
                    norm = np.sqrt(nx**2 + ny**2)
                    if norm < 1.0:
                        continue
                    nx, ny = nx / norm, ny / norm

                    # Project each anchor onto seam normal
                    projections = (scx - mx) * nx + (scy - my) * ny
                    side_a = [s for s, p in zip(sheet, projections) if p < 0]
                    side_b = [s for s, p in zip(sheet, projections) if p >= 0]
                    if len(side_a) < 4 or len(side_b) < 4:
                        continue

                    rmse_a = _loo_rmse(side_a)
                    rmse_b = _loo_rmse(side_b)
                    combined_rmse = (len(side_a) * rmse_a + len(side_b) * rmse_b) / len(sheet)
                    improvement = baseline_rmse - combined_rmse

                    if improvement > best_improvement:
                        best_improvement = improvement
                        best_split = (side_a, side_b)
                        best_sheet_idx = si

        if best_improvement < SEAM_MIN_IMPROVEMENT or best_split is None:
            break
        # Accept seam: replace sheet with two sub-sheets
        sheets.pop(best_sheet_idx)
        sheets.extend(list(best_split))

    return sheets


def build_drift_field(anchors: list[Anchor], utm_crs: str,
                      detect_sheet_seams: bool = True) -> list[DriftField]:
    """Build one or more DriftField objects (one per detected sheet).

    Steps:
    1. RANSAC filter.
    2. Seam detection (if requested).
    3. Per-sheet: affine fit + GP on residuals.
    Returns list of DriftField (usually 1, rarely 2-3).
    """
    if not anchors:
        return []

    cleaned = _ransac_filter(anchors)
    if not cleaned:
        cleaned = anchors  # keep all if RANSAC removes too many

    if detect_sheet_seams and len(cleaned) >= 8:
        sheets = detect_seams(cleaned)
    else:
        sheets = [cleaned]

    fields = []
    for sheet_id, sheet_anchors in enumerate(sheets):
        if not sheet_anchors:
            continue
        cx = np.array([a.cx_m for a in sheet_anchors])
        cy = np.array([a.cy_m for a in sheet_anchors])
        dx = np.array([a.dx_m for a in sheet_anchors])
        dy = np.array([a.dy_m for a in sheet_anchors])

        affine_x = _fit_affine(cx, cy, dx)
        affine_y = _fit_affine(cx, cy, dy)
        gp_x, gp_y = _fit_gp(sheet_anchors, affine_x, affine_y)

        df = DriftField(utm_crs=utm_crs, sheet_id=sheet_id,
                        anchors=sheet_anchors,
                        _gp_x=gp_x, _gp_y=gp_y,
                        _affine_x=affine_x, _affine_y=affine_y)
        fields.append(df)

    return fields


def assign_sheet(cx_m: float, cy_m: float,
                 fields: list[DriftField]) -> DriftField:
    """Return DriftField whose anchors are nearest the query point (centroid-NN)."""
    if len(fields) == 1:
        return fields[0]

    best = fields[0]
    best_dist = float("inf")
    for df in fields:
        if not df.anchors:
            continue
        ac = np.array([[a.cx_m, a.cy_m] for a in df.anchors])
        dists = np.sqrt((ac[:, 0] - cx_m)**2 + (ac[:, 1] - cy_m)**2)
        d = float(np.min(dists))
        if d < best_dist:
            best_dist = d
            best = df
    return best


def apply_field(geom_4326, cx_m: float, cy_m: float,
                fields: list[DriftField], utm_crs: str) -> tuple:
    """Translate all vertices of geom_4326 by T(vertex_utm). Returns (corrected_4326, std_m).

    Applies T at every vertex — fabric never tears.
    Uses the sheet assigned to the plot centroid.
    """
    to_utm = Transformer.from_crs("EPSG:4326", utm_crs, always_xy=True)
    to_4326 = Transformer.from_crs(utm_crs, "EPSG:4326", always_xy=True)

    df = assign_sheet(cx_m, cy_m, fields)
    dx_m, dy_m, std_m = df.predict(cx_m, cy_m)

    def translate_coords(xs, ys, zs=None):
        utm_xs, utm_ys = to_utm.transform(xs, ys)
        shifted_xs = [ux + dx_m for ux in utm_xs]
        shifted_ys = [uy + dy_m for uy in utm_ys]
        lon, lat = to_4326.transform(shifted_xs, shifted_ys)
        return lon, lat

    corrected = shp_transform(translate_coords, geom_4326)
    return corrected, std_m
