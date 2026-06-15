# BhuMe Take-Home — Decision Log & Video Script

## Screen recording plan

- `docs/phase0_map.html` in browser → show plots over imagery for drift thesis (visual proof)
- BhuMe Test page with vadnerbhairav loaded → live polygon overlays (before/after)
- Terminal: run predict.py for 30s, show it processing, skip to results
- `docs/reliability_vadnerbhairav.png` during calibration section

---

## (30s) Data-driven foundation — Phase 0

Don't skip the forensics. Audited `boundaries.tif` — 90% sparse under canopy / in village
cores. Greedy matching alone fails because there's nothing to match against. Also tested
`boundaries.tif` reliability on 30 plots per regime — only trustworthy on open fields.

Drift thesis validated on day one: 9 example truth shift vectors cluster by direction,
max 18.6m, within-village angular spread 6-29°. This is not random noise — it's a smooth
spatially-coherent field. **The architecture was born from data, not assumptions.**

---

## (60s) The drift field architecture — "torn cloth"

Cadastral sheets are physically separate pieces of paper, georeferenced independently.
The drift field has genuine discontinuities at sheet seams. We detect seams (anchor-
discordance graph cut + LOO model-selection brake), then fit per-sheet affine + GP on residuals.

**Why the field saves Malatavadi:** greedy chamfer on 872 m² plots → snaps to neighbouring
bund → IoU 0.030. Block-grow + GP field gives each plot spatial context from its neighbours.
Malatavadi: 0.030 → 0.739. The two-pass combines precision of greedy (sharp single-plot peaks)
with stability of the field (spatial prior). Neither alone is sufficient.

---

## (90s) The confidence engine — crown jewel

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
