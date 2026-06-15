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
5. **Features** (raw, NOT hand-weighted): `[agree_m, |log(area_ratio)|]`.
   `agree_m = |net_shift − GP_field(loc)|`. No leakage: net_shift = injection (GMM) +
   image-driven recovery; GP only enters as the comparison reference.
   gp_std and p2sp DROPPED: gp_std had a wrong-sign multicollinearity artifact (+0.54,
   coupled with agree_m); p2sp weight ≈0 (measures sharpness not correctness). Dropping
   both raised vadnerbhairav AUC (0.709→0.721) and left malatavadi flat (0.814→0.804).
6. **LogisticRegression** (class_weight=balanced) learns weights → 1D probability.
7. **IsotonicRegression** on the LR probability enforces monotone calibration.

## Honest AUC (5-fold cross-validated, no train-on-test) — FINAL 2-feature model

| Village | Cross-val AUC | Train-fit AUC | Synth samples (accurate) |
|---|---|---|---|
| vadnerbhairav | **0.721** | 0.744 | 298 (194 = 65%) |
| malatavadi | **0.804** | 0.815 | 277 (157 = 57%) |

(4-feature version: 0.709 / 0.814. Leaky version: 0.813 / 0.730 — both discarded.)

## Learned weights (standardized) — FINAL 2-feature model

| Feature | Vadnerbhairav | Malatavadi |
|---|---|---|
| agree_m | **−0.723** | **−1.414** |
| abs_log_area_ratio | −0.577 | −0.086 |

**Findings:**
- **agree_m (chamfer-GP agreement) is the dominant signal in both villages** — LR learned
  it, we didn't hand-set it. In malatavadi it's a razor (−1.41): the dense grid produces
  catastrophic failures (snap to neighbor's plot) that disagree sharply with the GP field.
- **P2SP dropped — empirically near-worthless** (weight ≈0 in 4-feature run). Confirms the
  Phase-1 diagnosis: P2SP measures peak sharpness, not correctness.
- **gp_std dropped** — wrong-sign (+0.54) multicollinearity artifact with agree_m; would
  reward high-uncertainty guesses on unseen villages.
- **area_ratio matters in vadnerbhairav (−0.577), not malatavadi (−0.086)** — large open
  fields with bad area ratios are unreliable; dense parcels already near 1.0.
- Dropping the two dead features RAISED vadnerbhairav AUC (0.709→0.721) and left malatavadi
  flat (0.814→0.804) — confirming they were noise/artifact, not signal.

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
