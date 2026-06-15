# Phase 6 — Confidence Calibration

## Method (leakage-free, learned weights)

Synthetic displacement-recovery → LogisticRegression → IsotonicRegression → P(IoU ≥ 0.5).

1. **Drift field** rebuilt from Phase 3 Pass-1 block anchors.
2. **Leakage-free shift sampler**: GMM (BIC-selected k∈{1,2,3}) fit on RAW anchor shift
   vectors (dx,dy) — independent of the GP spatial field. (Earlier version sampled
   injected truth from GP_field(loc), which leaked into the agree_m feature → AUC inflated.)
3. **Stratified sampling**: ~80 plots/regime (tiny/small/medium/large).
4. **Displacement-recovery test** (image-grounded — earlier version had no displacement,
   so accuracy-vs-injected-truth was near-random):
   - Reference chamfer on plot as-is → image-derived truth landing `L`.
   - Displace `L` by GMM-sampled shift `d` → `disp`.
   - Re-chamfer `disp`; corrected = disp + recovery shift. Accurate iff IoU(corrected, L) ≥ 0.5.
5. **Features** (raw, NOT hand-weighted): `[p2sp, agree_m, gp_std, |log(area_ratio)|]`.
   `agree_m = |net_shift − GP_field(loc)|`. No leakage: net_shift = injection (GMM) +
   image-driven recovery; GP only enters as the comparison reference.
6. **LogisticRegression** (class_weight=balanced) learns weights → 1D probability.
7. **IsotonicRegression** on the LR probability enforces monotone calibration.

## Honest AUC (5-fold cross-validated, no train-on-test)

| Village | Cross-val AUC | Train-fit AUC | Synth samples (accurate) |
|---|---|---|---|
| vadnerbhairav | **0.709** | 0.743 | 298 (194 = 65%) |
| malatavadi | **0.814** | 0.835 | 277 (157 = 57%) |

(Leaky earlier version reported 0.813 / 0.730 — discard those.)

## Learned weights (standardized) — the empirical payoff

| Feature | Vadnerbhairav | Malatavadi |
|---|---|---|
| agree_m | **−0.730** | **−1.522** |
| abs_log_area_ratio | −0.585 | −0.081 |
| gp_std | +0.064 | +0.543 ⚠ |
| p2sp | −0.043 | +0.018 |

**Findings:**
- **agree_m (chamfer-GP agreement) is the dominant signal in both villages** — and the
  LR learned it, we didn't hand-set it. In malatavadi it's a razor (−1.52): the dense
  grid produces many false peaks that strongly disagree with the GP field.
- **P2SP is near-worthless once agreement is present** (|w| ≤ 0.04). Empirically confirms
  the Phase-1 diagnosis: P2SP measures peak sharpness, not correctness.
- **area_ratio matters in vadnerbhairav (−0.585), not malatavadi (−0.08)** — large open
  fields with bad area ratios are unreliable; dense parcels already near 1.0.
- **gp_std weight is +0.54 in malatavadi (wrong sign)** — flagged risk; likely collinearity
  with agree_m. Small vs agree_m magnitude but worth watching.

## Open risk — synthetic vs real disagreement (malatavadi)

| Village | Synth cross-val AUC | Real-truth Spearman | Real-truth AUC |
|---|---|---|---|
| vadnerbhairav | 0.709 | +0.765 | — (3/3 + above acc) |
| malatavadi | 0.814 | **−0.866** | **0.250** |

Malatavadi's synthetic calibration looks excellent (0.814) but the 3 real example truths
show INVERTED confidence (Spearman −0.866). With n=3, one point flips the sign — statistically
near-meaningless — but it's a genuine red flag that synthetic ≠ real on dense parcels.
Cannot resolve with 3 points; flagged for video/writeup as known limitation.

## Anti-overfit note

Calibration NEVER tuned to the 9 example truths. Synthetic set built from the village's
own drift field + Phase-0 regime distribution. The 9 truths used only for final reporting.

Artifacts: `docs/reliability_<village>.png`, `docs/calibration_<village>.pkl`,
`data/<village>/predictions_calibrated.geojson`.
