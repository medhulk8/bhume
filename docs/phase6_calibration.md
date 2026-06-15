# Phase 6 — Confidence Calibration

## Method

Synthetic shift injection → isotonic regression → P(IoU ≥ 0.5).

1. **Drift field** rebuilt from Phase 3 Pass-1 block anchors (per village).
2. **Stratified sampling**: ~80 plots/regime (tiny/small/medium/large) per village.
3. **Injection** (Gemini directive — spatially coherent, NOT uniform scatter):
   `injected_shift = GP_field(cx,cy) + N(0, 2m²)`. Truth = original geometry translated by injected shift.
4. **Recovery**: run greedy chamfer on the plot, measure `IoU(chamfer_corrected, truth)`. Label = IoU ≥ 0.5.
5. **Signals → monotone raw score**:
   `raw = 0.40·(1−P2SP) + 0.45·(1−agree_m/28m) + 0.15·(1−GP_std/5m)`
6. **Isotonic regression**: raw_score → P(IoU ≥ 0.5). Monotone, non-parametric.

## Key Finding — the agreement signal

P2SP alone gave **synthetic AUC 0.490** (coin flip). Root cause: P2SP measures
peak *sharpness*, not peak *correctness*. On small/dense plots, chamfer locks onto a
sharp but WRONG local minimum — low P2SP, high confidence, wrong location.

Fix: **chamfer-GP agreement** `agree_m = |chamfer_shift − GP_field_prediction|`.
A chamfer that agrees with the spatially-smooth GP field is almost certainly correct;
one that diverges found a false peak. This is the discriminator P2SP cannot provide.

| Signal set | Vadnerbhairav synth AUC | Malatavadi synth AUC |
|---|---|---|
| P2SP only | 0.490 | — |
| **P2SP + agreement + GP-std** | **0.813** | **0.730** |

## Results (calibrated predictions)

| Village | Synth samples (accurate) | Synth AUC | Real-truth Spearman | Real-truth IoU |
|---|---|---|---|---|
| vadnerbhairav | 302 (132) | 0.813 | 0.765 | 0.872 |
| malatavadi | 272 (76) | 0.730 | — (3 pts, all accurate) | 0.678 |

Reliability diagrams: `docs/reliability_vadnerbhairav.png`, `docs/reliability_malatavadi.png`.
Calibration models: `docs/calibration_<village>.pkl`.

## Anti-overfit note

Calibration NEVER tuned to the 9 example truths. Synthetic set built from the
village's own drift field + Phase-0 regime distribution. The 9 truths are used only
for final reporting (Spearman/IoU), not for fitting any threshold.
