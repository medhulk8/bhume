# Phase 1 Baseline Scores

Scored against public example truths only (6 vadnerbhairav / 3 malatavadi).
AUC requires both accurate (IoU≥0.5) and inaccurate plots — blank when all truths are accurate.

## vadnerbhairav (6 example truths, median plot 7,753 m², open agrarian)

| Baseline | Median IoU | vs official | Improvement | Centroid err | AUC |
|---|---|---|---|---|---|
| identity | — | 0.612 | — | — | — |
| median_shift | 0.713 | 0.612 | +0.112 | 8.8 m | — (flat conf) |
| greedy_chamfer (global threshold 0.15) | 0.824 | 0.612 | +0.274 | 3.8 m | — (all accurate) |
| greedy_chamfer (adaptive top-15%) | ~0.824 | 0.612 | ~+0.274 | ~3.8 m | — |

Notes: Adaptive threshold does not degrade vadnerbhairav (open fields, dominant edges survive either threshold).

## malatavadi (3 example truths, median plot 872 m², dense mixed parcels)

| Baseline | Median IoU | vs official | Improvement | Centroid err | AUC |
|---|---|---|---|---|---|
| identity | — | 0.510 | — | — | — |
| median_shift | 0.588 | 0.510 | +0.090 | 7.9 m | 0.500 (flat conf) |
| greedy_chamfer (global threshold 0.15) | 0.014 | 0.510 | −0.092 | 14.8 m | 0.500 |
| greedy_chamfer (adaptive top-15%) | 0.030 | 0.510 | −0.076 | 17.0 m | 0.500 |

Notes:
- Adaptive threshold: +0.016 IoU improvement, AUC still 0.500, centroid error slightly worse
- **Threshold tuning cannot fix this.** Problem is structural: ±28m search with no drift prior
  finds the wrong neighbouring-plot edge in a dense grid. Every candidate has similar DT scores.
- Drift field prior + block matching is the only architectural fix.

## Ablation summary

| | Vadnerbhairav | Malatavadi | Interpretation |
|---|---|---|---|
| Greedy chamfer IoU | 0.824 | 0.030 | **0.794 gap** — signal poverty, not threshold |
| Greedy chamfer AUC | — | 0.500 | P2SP blind on multi-modal dense landscape |
| Adaptive threshold Δ | ~0 | +0.016 | Marginal: confirms problem is structural |

**Phase 1 conclusion: drift field + block matching are structurally necessary for Malatavadi.
No evidence map parameter changes fix a missing search prior.**
