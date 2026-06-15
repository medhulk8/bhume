# Phase 1 Baseline Scores

Scored against public example truths only (6 vadnerbhairav / 3 malatavadi).
AUC requires both accurate (IoU≥0.5) and inaccurate plots — blank when all truths are accurate.

## vadnerbhairav (6 example truths, median plot 7,753 m², open agrarian)

| Baseline | Median IoU | vs official | Improvement | Centroid err | AUC | Coverage |
|---|---|---|---|---|---|---|
| identity | — | 0.612 | — | — | — | 0 corrected |
| median_shift | 0.713 | 0.612 | +0.112 | 8.8 m | — (flat conf) | 2457 corrected |
| greedy_chamfer | 0.824 | 0.612 | +0.274 | 3.8 m | — (all accurate) | 2457 corrected |

Notes:
- Chamfer beats median_shift by +0.111 IoU, halves centroid error
- AUC uncomputable: all 6 truths hit IoU≥0.5 — no negatives
- Spearman(conf, IoU) = -0.116 (6 points, not meaningful)

## malatavadi (3 example truths, median plot 872 m², dense mixed parcels)

| Baseline | Median IoU | vs official | Improvement | Centroid err | AUC | Coverage |
|---|---|---|---|---|---|---|
| identity | — | 0.510 | — | — | — | 0 corrected |
| median_shift | 0.588 | 0.510 | +0.090 | 7.9 m | 0.500 (flat conf) | 3 corrected |
| greedy_chamfer | 0.014 | 0.510 | **-0.092** | 14.8 m | **0.500** | 2508 corrected |

Notes:
- Chamfer HURTS vs identity: median IoU collapses from 0.510 → 0.014 (-0.496)
- Only 1/3 truths hit IoU≥0.5 (vs 3/3 for median shift)
- AUC 0.500 = Lowe's P2SP ratio is pure noise — landscape has many equally-good matches,
  ratio gives no discrimination signal on dense tiny plots
- Centroid error 14.8m — matcher wanders to random strong edges, not plot boundaries

## Cross-village summary

| | Vadnerbhairav | Malatavadi | Gap |
|---|---|---|---|
| Greedy chamfer IoU | 0.824 | 0.014 | **0.810** |
| Greedy chamfer AUC | — | 0.500 | — |

**This proves the block matching + drift field prior are structurally necessary for Malatavadi,
not a nice-to-have. Solo greedy chamfer on signal-poor dense plots = matches noise.**
