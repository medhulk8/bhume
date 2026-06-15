# BhuMe Take-Home — Decision Log & Video Script

## Core insight (30s)

Century-old cadastral sheets were georeferenced with sparse control points. The error is not
random per-plot — it's a smooth spatially-coherent drift field. Neighbours drift together.
That's the thesis. The 9 example truths validate it on day one: shift vectors cluster by
direction, max 18.6m, within-village angular spread only 6-29°.

The consequence: estimating the FIELD, not greedy per-plot matches, is the right architecture.

---

## Two-pass architecture — why it exists (60s)

Phase 1 greedy chamfer: vadnerbhairav IoU 0.912. Malatavadi: 0.030. Catastrophic on dense
small parcels — the chamfer snaps to neighbouring plot boundaries.

First attempt at Phase 3: single-pass block chamfer → anchors → per-plot correction.
Vadnerbhairav REGRESSED to 0.744. Root cause: block DT is a merged distance transform.
Merged DT has flatter peaks than single-plot DT → inflated P2SP → low confidence everywhere.

Fix: **two-pass**. Pass 1 = block chamfer for anchors only (don't use block result as
per-plot correction). Pass 2 = greedy per-plot chamfer for corrections. The block matches
are used purely to build the GP drift field. Per-plot confidence comes from greedy.

Result: vadnerbhairav 0.744→0.872. Malatavadi 0.030→0.678. The drift field is load-bearing
for dense villages.

---

## Confidence calibration — the whole story (90s)

**What doesn't work: P2SP**
First attempt: use Lowe's peak ratio as confidence. AUC 0.490. P2SP measures sharpness
of the chamfer peak, not correctness. A plot can snap to the wrong bund sharply.

**What works: agree_m**
agree_m = |greedy_shift − GP_field_prediction|. If the image-driven chamfer and the
spatial field agree → confident. If they diverge → the chamfer probably found a false peak.
LR weight −0.723 (vadnerbhairav) / −1.414 (malatavadi). LR learned this; we didn't hand-set it.

**Leakage bug (caught by Gemini)**
First calibration: injected shift = GP_field(location) + noise. Then agree_m = |chamfer − GP|.
agree_m was measuring recovery of the thing we injected → near-tautology. AUC 0.813 was fake.
Fix: GMM on raw anchor shifts (independent of GP field). Honest AUC: 0.721 / 0.804.

**The 81% constant problem (self-caught)**
81% of vadnerbhairav corrected plots used GP fallback with agree_m hardcoded to 28.0.
All got identical confidence 0.7308. 30 unique confidence values.
Fix: compute agree_m = |greedy − GP| even for high-P2SP plots. The greedy result is
unreliable for WHERE to move, but still informative about whether image and field AGREE.
Result: 94 unique confidence values. Real gradient.

**Decision boundary**
If calibrated P(IoU≥0.5) < 0.5 → flag. Submitting a correction expected to be wrong
hurts AUC. Threshold is probability-axiom-derived (not tuned to 9 example truths).
Malatavadi: plot 1177 (conf=0.381) correctly flagged. Accuracy 67%→100%.

---

## Where it breaks honestly (60s)

**Malatavadi centroid error 15.4m** — dense small parcels (median 872 m²) have many
adjacent bunds. Chamfer can snap to neighbouring plot boundary. The one wrong correction
(plot 1177, flagged after conf threshold) had agree_m=38.4m — greedy and GP diverged
violently, system knew it was uncertain.

**Malatavadi IoU still 0.739** — the drift field helps (0.030→0.739) but dense parcels
are harder. The remaining inaccurate plots likely have chamfer snapping across bunds.

**Vadnerbhairav hidden AUC unknown** — all 6 public truths are accurate, so the public
calibration metric can't be computed (needs both hits and misses). Synth cross-val 0.721
is the best estimate.

**n=3 malatavadi truths** — too few to draw firm conclusions. One point flips Spearman sign.
We report synth AUC, not the noisy public Spearman.

---

## What I'd build next (30s)

**District-scale drift fields**: right now we build one field per village from its own example
truths. At district scale, we'd have thousands of hand-checked anchors → much denser GP field,
better uncertainty estimates near sheet seams.

**Active learning loop**: flagged plots route to human annotators. Each human fix becomes a
new control point that refines the drift field. The system gets better with use — the more
you flag, the smarter it gets.

**Online seam detection**: sheet seams are currently found by anchor-discordance graph cut.
With more anchors, the seam geometry becomes crisp enough to model explicitly (road/stream
following) → tighter uncertainty at discontinuities.

---

## Bugs caught and fixed (for transcript evidence)

| Bug | Impact | Fix |
|---|---|---|
| Area ratio using equatorial metres | 6-12% error at 17-20°N → over-flagged 53 plots | Pass UTM area to _area_ratio |
| Redundant physical cap in decision layer | Over-flagged 1643 malatavadi plots (blocks of 10 small plots hit 10×median cap) | Remove post-hoc check (grow_block already enforces) |
| GP fallback agree_m constant 28m | 81% of corrected plots got identical confidence | Compute real |greedy−GP| even for high-P2SP |
| conf<0.5 not flagged | Submitting expected-wrong corrections hurt AUC | Add decision-theory threshold |

---

## Numbers to cite in video

- Drift vectors: max 18.6m, search radius 28m (Phase 0)
- Vadnerbhairav IoU: official 0.612 → us 0.872 (+0.259), 100% accurate
- Malatavadi IoU: official 0.510 → us 0.739 (+0.229), 100% accurate
- Malatavadi without drift field: 0.030 (Phase 1 greedy)
- Synth calibration AUC: 0.721 / 0.804
- Runtime: ~6 min/village on a laptop
