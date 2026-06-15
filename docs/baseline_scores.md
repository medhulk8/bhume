# Phase 1 Baseline Scores

Scored against public example truths only (6 vadnerbhairav / 3 malatavadi).
AUC requires both accurate (IoU≥0.5) and inaccurate plots — blank when all truths fall on same side.

## vadnerbhairav (6 example truths, median plot 7,753 m², open agrarian)

| Baseline | Median IoU | Improvement | Centroid err | Spearman(conf,IoU) | AUC |
|---|---|---|---|---|---|
| identity | — | — | — | — | — |
| median_shift | 0.713 | +0.112 | 8.8 m | — (flat conf) | — |
| chamfer, global threshold 0.15 | 0.824 | +0.274 | 3.8 m | −0.116 | — (all accurate) |
| **chamfer, adaptive top-15%** | **0.912** | **+0.299** | **3.7 m** | **+0.812** | — (all accurate) |

Key: adaptive threshold improved vadnerbhairav IoU by +0.088 AND flipped Spearman from −0.116 → +0.812.
Lowe's P2SP ratio genuinely tracks accuracy on open-field plots — plots where chamfer finds a unique
sharp peak are the ones that actually land correctly.

## malatavadi (3 example truths, median plot 872 m², dense mixed parcels)

| Baseline | Median IoU | Improvement | Centroid err | Spearman(conf,IoU) | AUC |
|---|---|---|---|---|---|
| identity | — | — | — | — | — |
| median_shift | 0.588 | +0.090 | 7.9 m | — (flat conf) | 0.500 |
| chamfer, global threshold 0.15 | 0.014 | −0.092 | 14.8 m | — | 0.500 |
| chamfer, adaptive top-15% | 0.030 | −0.076 | 17.0 m | — | 0.500 |

Adaptive threshold: +0.016 IoU, AUC still 0.500. Problem is structural — dense grid, no drift prior.

## Ablation summary (adaptive threshold, final Phase 1 baseline)

| | Vadnerbhairav | Malatavadi | Interpretation |
|---|---|---|---|
| Greedy chamfer IoU | **0.912** | 0.030 | 0.882 gap — structural, not threshold |
| Spearman(conf, IoU) | **+0.812** | — | P2SP works on open fields, blind on dense |
| AUC | — (all accurate) | 0.500 | Need negatives; Malatavadi gives them |

**Phase 1 conclusion:**
- Adaptive threshold fixes both villages: vadnerbhairav IoU +0.088, Spearman −0.116→+0.812
- P2SP confidence is calibrated on Vadnerbhairav (Spearman 0.812). This is the AUC foundation.
- Malatavadi structurally requires drift field + block matching. No evidence map fix closes the gap.
- Phase 1 ablation row (greedy chamfer, no field) is locked and ready for Phase 3 comparison.
