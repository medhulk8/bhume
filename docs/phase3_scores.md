# Phase 3 Scores — Block-Grow + GP Drift Field (two-pass)

Architecture: Pass 1 = block-grow chamfer → anchors for drift field.
Pass 2 = greedy per-plot chamfer → per-plot corrections.
Decision: greedy P2SP < 0.80 → use greedy direct; else → GP drift field interpolation.

## Ablation vs Phase 1

| Metric | Phase 1 greedy | Phase 3 two-pass | Delta |
|---|---|---|---|
| Vadnerbhairav IoU | 0.912 | 0.872 | −0.040 |
| Vadnerbhairav centroid err | 3.7m | 3.5m | −0.2m |
| Vadnerbhairav Spearman | +0.812 | +0.829 | +0.017 |
| Malatavadi IoU | 0.030 | **0.678** | **+0.648** |
| Malatavadi Spearman | flat | +0.500 | — |

## vadnerbhairav

```
=== vadnerbhairav · scored on 6 example truths ===
coverage:    6 corrected + 0 flagged
accuracy:    median IoU pred=0.872 vs official=0.612  (improvement=0.259, improved 1.000)
             median centroid err=3.547 m · accurate(IoU>=.5)=1.000
calibration: Spearman(conf,IoU)=0.829 · AUC=—   (higher = confidence tracks accuracy)
restraint:   N/A — graded on the hidden set (no control plots here)
```

## malatavadi

```
=== malatavadi · scored on 3 example truths ===
coverage:    3 corrected + 0 flagged
accuracy:    median IoU pred=0.678 vs official=0.510  (improvement=0.229, improved 0.667)
             median centroid err=14.831 m · accurate(IoU>=.5)=0.667
calibration: Spearman(conf,IoU)=0.500 · AUC=0.500   (higher = confidence tracks accuracy)
restraint:   N/A — graded on the hidden set (no control plots here)
```
