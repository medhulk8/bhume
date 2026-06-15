# Phase 1 Baseline Scores

Scored against public example truths only (6 vadnerbhairav / 3 malatavadi).
AUC requires both accurate (IoU≥0.5) and inaccurate plots in the scored set — blank when all truths are accurate.

## vadnerbhairav (6 example truths)

| Baseline | Median IoU pred | IoU official | Improvement | Centroid err | AUC | Coverage |
|---|---|---|---|---|---|---|
| identity | — | 0.612 | — | — | — | 0 corrected / 2457 flagged |
| median_shift | 0.713 | 0.612 | +0.112 | 8.835 m | — (flat conf) | 2457 corrected |
| greedy_chamfer | 0.824 | 0.612 | +0.274 | 3.814 m | — (all accurate) | 2457 corrected / 0 flagged |

Notes:
- Chamfer beats median_shift by +0.111 IoU and halves centroid error (8.8→3.8m)
- 0 flagged: flat-landscape and P2SP conditions never fire at this scale — expected for an ablation row
- AUC blank: all 6 truths hit IoU≥0.5 → no negatives for AUC computation
- Spearman(conf, IoU) = -0.116 (6 points, weak signal)

## malatavadi

_Not yet run._
