# BhuMe Take-Home — Complete Project Plan

> **Read this first.** This file is the full context for a fresh session. It contains everything:
> what the project is, the task spec, scoring rubric, the finalized implementation strategy
> (refined over a planning debate with Gemini acting as architect-critic), data inventory,
> and next steps. Site screenshots are in `docs/screenshots/` (numbered 1–6 in reading order).
> Planning is DONE. Next action is Phase 0 (data forensics).

---

## 1. What this is

Applying for a full-stack intern role at **BhuMe AI** (Bangalore, HSR Layout, ₹1.5L stipend,
3 months). BhuMe builds a private land-ownership verification layer for India (70% of Indian
civil cases are property disputes). Application = attempt their take-home at
**https://hiring.bhume.in/** + a 100-word self-intro with links to best work.

**They grade HOW YOU THINK, not the score.** Metrics rank submissions but don't decide.
Method review (code + video + AI transcripts) decides. No deadline — "take the time you need."
Expected effort floor: 8–12 hours; we are deliberately going beyond that for Platinum tier.
Questions → yash@bhume.in.

## 2. The problem (from the "Understand" page)

Official land-plot boundaries in Maharashtra come from century-old cadastral maps (chain /
plane-table surveys, 1:4,000–1:10,000 scale, half-millimetre of pen = 2–5 m on the ground).
MRSAC scanned and **georeferenced** these sheets onto satellite imagery using sparse control
points (bunds, roads, tanks). Fit is only good near control points → parcels **drift** off the
real fields they describe.

**The one-sentence task:** For each land plot, decide whether the official boundary can be
nudged onto the real field, and if so, where it should go.

Key vocabulary:
- **plot** — one drawn outline on the cadastral map, has unique `plot_number`. The unit we correct.
- **7/12 (saat-baara)** — written revenue record per plot: holders, recorded area. Organised by
  survey/gat number; survey can subdivide into **hissa** (e.g. 142/2).
- **recorded area** = sum of holdings = cultivable + **pot-kharaba** (uncultivable, recorded separately).
- The 7/12 does **not** draw the shape — outline comes from the cadastral map; area comes from
  the record; the two can disagree.

**Two independent kinds of wrong (telling them apart is most of the job):**
1. **PLACEMENT** — shape roughly right, slid off the true field. Fixable by moving.
2. **AREA** — drawn shape doesn't match recorded area. Moving won't help; geometry itself
  disagrees with record (stale outline, ownership/split changes after drawing, digitisation error).

**The `drawn ÷ recorded` area ratio is a clue, not a verdict:** near 1.0 → placement problem
(fixable); far from 1.0 → area/record problem → investigate/flag, don't drag.

## 3. Data given (per village bundle)

| File | What | Trust level |
|---|---|---|
| `input.geojson` | Official plots: id (`plot_number`), recorded area, holdings. EPSG:4326 FeatureCollection | The thing to correct |
| `imagery.tif` | Satellite raster of village | PRIMARY SIGNAL |
| `boundaries.tif` | Auto-detected field edges | ROUGH — strong on open fields, unreliable under tree cover / near buildings. "A nudge, never an answer" |
| `example_truths.geojson` | Hand-checked true boundaries | Only 6 plots (Vadnerbhairav) / 3 plots (Malatavadi) — beware overfitting |

**Two villages:**

| | Vadnerbhairav (Nashik) | Malatavadi (Kolhapur) |
|---|---|---|
| Plots | 2,457 | 2,508 |
| Extent | 54.2 km² | 5.8 km² |
| Median plot | 7,753 m² | 872 m² (~30×30 m!) |
| Character | Open agrarian, large well-separated fields, drift easy to see — build intuition here first | Mixed tightly-packed parcels near a town, crowded edges — the stress test |

**Python starter kit** (downloadable from "Get started" page): `load(village)`,
`lonlat ↔ pixel`, `write_predictions()`, `patch_for_plot()` (crops raster under a plot as
plain image array, projection handled), `score()` (the same metrics they grade with, runs
locally), `global_median_shift()` (naive baseline to beat). Thin readable helpers, not a
framework. No need to hand-parse GeoTIFFs.

**ML explicitly optional.** Classical image work (edge detection, cross-correlation for
offset, contour fitting) named as valid. They judge *judgment*: which edge is right, what
confidence should mean, which records to trust.

### Local data inventory (complete as of 2026-06-11)

Everything downloaded and organised:
```
bhume/
├── PLAN.md
├── docs/screenshots/        # 6 site pages, numbered in reading order
├── data/
│   ├── vadnerbhairav/       # input.geojson, imagery.tif, boundaries.tif, example_truths.geojson (6 plots: 1145,1403,1476,1710,2647,622)
│   └── malatavadi/          # same 4 files (truths 3 plots: 1177,1763,1966)
├── kit/                     # official starter kit (their code, untouched): bhume/{io,geo,score,baseline}.py, quickstart.py, CONTRACT.md, uses uv
└── transcripts/             # /export sessions land here (graded deliverable)
```
Plot counts verified: vadnerbhairav 2,457 / malatavadi 2,508 (match site).
NO implementation code written yet — kit/ is the organisers' downloaded starter kit, as-is.
Kit run pattern: `uv run quickstart.py <path-to-village-dir>` from `kit/`.
Read `kit/CONTRACT.md` + README + the `bhume/` modules before writing any code.

## 4. Output contract & scoring (from "The task" page)

Code reads a village bundle → writes `predictions.geojson` (FeatureCollection, EPSG:4326)
beside it. Per claimed plot:

| Field | Meaning |
|---|---|
| `plot_number` | echo the plot's id exactly |
| `status` | `corrected` (you moved it) or `flagged` (you looked, not sure) |
| `confidence` | 0–1 for corrected plots. **Scored — make it mean something** |
| `method_note` | optional free text: how you got it / why flagged |
| `geometry` | predicted boundary (corrected) or original (flagged) |

Omitted plots = "not attempted" — no penalty, no credit. Choosing what to leave alone is
part of the work.

**Scoring (vs hidden hand-checked truths):**
- **A. Accuracy** — IoU + centroid error (metres). Always compared against official starting
  position; a corrected plot clearing **IoU 0.5** counts as a solid hit. What counts is the
  *improvement* you add.
- **B. Confidence calibration ("WE WATCH THIS MOST")** — does confidence track being right?
  Single number: **AUC** (0.5 = chance, 1 = perfect). Weighted most. Random/flat confidence
  sits at 0.5. This decides which fixes to trust and which to send to a human.
- **C. Restraint** — honest flags protect calibration; they read the logic behind flags.
  **Control plots already in the right place are seeded in: leaving them put counts FOR you,
  moving them counts AGAINST.**

**Tiers:** Bronze (it runs end-to-end, honest correct-or-flag calls) → Silver (corrected plots
measurably beat official position) → Gold (confidence tracks accuracy) → Platinum
(**one method holds across villages without hand-tuning; automatic adaptation fine**).

**Anti-overfit warning (verbatim spirit):** hand-edited geometry or anything overfit to the
handful of example truths scores poorly even when numbers look good. They run YOUR CODE on
data it wasn't tuned to.

**Test page** (https://hiring.bhume.in/test): drop `predictions.geojson`, scored in-browser
against the example truths with the same metrics. Use before submitting to catch schema issues.

## 5. Submission package (from "Submit" page)

One **GitHub repo** (public, or private with them invited):
1. **Code** — turns village bundle → predictions, runnable by them. Rough fine. No written report.
2. **`predictions.geojson`** per attempted village (contract format, validated through Test page).
3. **`/transcripts/`** — AI transcripts. Claude Code: `/export` the session, commit under
   `/transcripts`. Web chats (Gemini etc.): share links listed in `transcripts/README.md`.
   "Use AI as much as you like, we read how you direct it."

Plus a **Google Form**: name, email, phone, repo URL, **5-minute video** link (screen-record
walking through the approach — what you tried, what you learned from data, where it broke,
what next; any host, must open without login), résumé upload. Sign in with Google.

Then the application itself: 100-word intro + links to best work.

---

## 6. FINALIZED IMPLEMENTATION STRATEGY

(Survived an adversarial whiteboard review with Gemini-as-architect; all amendments merged.
Decisions log in §7.)

### Core thesis
Drift is **not random per-plot**. Sheets georeferenced with sparse control points → error is
a **smooth, spatially coherent drift field**: neighbours drift together, drift varies gradually.
Estimate the *field*, not greedy per-plot matches → (a) accuracy where signal is weak,
(b) principled uncertainty → confidence, (c) mirrors the physical cause = defensible story.
Second independent signal: `drawn ÷ recorded` ratio separates placement-wrong from
record-wrong → **flag, don't drag** the latter.

### Phase 0 — Data forensics (NEXT ACTION; before any method code)
1. Load both bundles + starter kit. Render plots over imagery. Build clickable HTML map
   (folium/leaflet) — inspection artifact that lives in repo through the whole project.
2. **Test the drift hypothesis** on the 9 example truths: shift vectors = truth centroid −
   official centroid; check magnitudes + whether nearby truths share direction. Validates or
   kills the core thesis on day one.
3. **Area-ratio census**: histogram drawn/recorded over all ~5k plots; sets flag threshold
   empirically; quantifies placement-fixable vs record-broken fractions.
4. **Signal audit**: ~30 plots per regime (open field / canopy / village core / tiny parcel);
   per-regime reliability of image gradients and boundaries.tif. Malatavadi 872 m² median is
   the stress case — confirm how much edge signal even exists.
5. **boundaries.tif characterisation**: precision/recall vs visible bunds in sampled patches →
   sets its fusion weight.
6. Check whether adjacent plots in input.geojson share identical boundary vertices (or near —
   snap tolerance). Determines whether the vertex-through-field topology trick (§Phase 4) is free.
7. Metadata blockiness scan: do plot_number/survey ranges form spatially contiguous patches?
   (sheet-boundary candidates, see Phase 4).

### Phase 1 — Baseline ladder (scored with kit `score()` from day one)
1. **Identity** (move nothing) — restraint reference.
2. **`global_median_shift()`** (provided) — naive reference to beat.
3. **Greedy solo per-plot match** — later proves the field adds value; becomes an ablation row.

### Phase 2 — Boundary evidence map (TIMEBOXED — biggest rabbit-hole risk)
Fuse per village into one **boundary-likelihood raster**:
- Sobel gradient magnitude (luminance) — bunds, roads.
- Local texture variance shifts — ploughed-vs-fallow edges gradients miss.
- Excess-Green (2G−R−B) tested in Phase 0 audit; **dropped without ceremony if weak**
  (RGB-only pseudo-NDVI is noisy; Indian bunds often dry earth/stone — Gemini critique, accepted).
- boundaries.tif weighted by Phase 0 reliability, down-weighted near buildings/canopy.
Then **distance transform** once per village → cheap chamfer matching everywhere.
Decent fused map + strong matching/field/calibration stack > perfect edge map + greedy matcher.

### Phase 3 — Registration with dynamic block matching
**Adjacency graph** built once per village: nodes = plots; edges = shared-boundary contiguity
(touch with snap tolerance) + centroid-Delaunay backstop with distance cap. Reused for block
growing, fabric checks, seam detection.

Per plot (area-ratio sane):
1. `patch_for_plot()` crop; rasterize official outline.
2. **Chamfer matching**: slide outline over translation grid (search radius from Phase 0 drift
   stats), score = **trimmed-mean** edge distance along outline (one occluded edge can't sink a
   match). Coarse-to-fine. Optional ±2–3° rotation refine (sheet warp).
3. Keep full **score landscape** — peak sharpness + best/second-peak ratio are confidence raw material.
4. **Evidence-budget block growing** (no hardcoded block size):
   `budget(plot) = Σ boundary-segment length × per-regime signal reliability (Phase 0)`.
   If solo budget ≥ threshold → solo match. Else grow block over adjacency graph, adding
   neighbours by budget-per-area-added, until budget met. Block size *emerges from signal
   poverty* — Malatavadi grows 5–15-plot blocks, open Vadnerbhairav stays solo.
5. **Physical Constraint Cap** (Gemini resolution, accepted): max block ≈ 10× village median
   plot area. Hit cap and still under budget → area fundamentally unmatchable (canopy etc.) →
   force `flagged`.
6. **Edge-Density Decay** (Gemini resolution, accepted): mild distance penalty on chamfer
   weights for edges far from target-plot centroid — distant edges do coarse alignment, local
   edges decide the fine peak; mitigates the block-rigidity assumption.
7. Block outer-envelope edges full weight; interior edges weighted by measured visibility
   (interior bunds between same-crop fields often invisible — counting them inflates false sharpness).
8. Blocks never cross a detected sheet seam (Phase 4).
9. **Solo/block disagreement** (where both adequately powered) = strong flag/down-weight signal.
10. **Variogram audit** (demoted from gate to audit, per debate): once Vadnerbhairav's open-field
    solo anchors exist, compute drift variogram; if locally-rigid length scale ≪ the 10× cap,
    tighten the cap and report. Cap = prior, variogram = audit.

### Phase 4 — Drift field with multi-sheet handling (the centerpiece)
1. **Anchors** = sharp, unambiguous matches (top quantile landscape sharpness, spatially spread),
   purified by a **RANSAC-style consensus filter** vs local neighbours.
2. **Sheet seam detection** (maps were multiple physical sheets georeferenced independently —
   drift field may have genuine discontinuities). Three detectors, cheap first, agreement raises
   confidence:
   a. Metadata blockiness (Phase 0, free) + seams historically follow roads/streams (visible).
   b. **Primary: anchor-shift discordance on adjacency graph** — delete edges with
      ‖shift_i − shift_j‖ above threshold (set from intra-sheet discordance distribution);
      connected components = sheet hypotheses. True seams = *spatially coherent connected cuts*;
      isolated bad anchors = salt-and-pepper (absorbed by consensus filter).
   c. **Model-selection brake against over-segmentation**: accept a split only if the piecewise
      model beats one smooth field on **leave-one-out anchor residual** by a real margin.
      Within-sheet cloth-warp must be absorbed by the smooth field, not spawn fake seams.
3. **Hierarchical per-sheet model**: **sheet-level affine (6 DOF — soaks up systematic
   stretch/skew of that sheet, the "torn cloth" critique) + GP regression on residuals**
   (smooth local warp; **predictive variance feeds confidence directly**). GP is cubic in
   *anchors* (a few hundred — trivially cheap), evaluation over all plots is linear. Simpler
   fallback if needed: RBF interpolation + residual bootstrap.
4. Plots near seams get a distance-to-seam variance bonus → lower confidence → more flags
   exactly where sheets disagree. (Failure-gallery material.)
5. **EM-flavoured alternation, hard cap 2 iterations**: match → fit field → field-regularised
   rematch (final shift = argmax(edge evidence + λ·field prior)). Weak plots lean on field;
   strong plots can override locally. Second-pass stability is itself a reportable diagnostic.
6. **Topology — key design decision**: final correction is a continuous map T(x,y) =
   sheet-affine ∘ smooth residual field. **Apply T to every VERTEX, not translate polygons.**
   Shared vertices map identically by construction → parcel fabric stretches, never tears —
   no shared-vertex bookkeeping, no least-squares parcel adjustment (canonical GIS answer,
   explicitly rejected as over-engineering; one line in video as "production next step").
   Discontinuities only across detected seams, where the source fabric genuinely was torn.
7. Sanity guard: corrected plots must not newly overlap neighbours / detach from fabric →
   violations cost confidence or trigger flag.

### Phase 5 — Decision layer (every plot's method_note states its path)
- **Leave alone (omit / restraint)**: best shift below minimum-meaningful threshold, or IoU
  gain negligible. Protects against seeded control plots. Concrete number from kit score.py:
  control plot moved >5 m centroid = false shift (CONTROL_SHIFT_M=5.0); so leave-alone
  threshold must sit safely under 5 m. Kit also reports Spearman(conf,IoU) alongside AUC;
  accuracy hit = IoU ≥ 0.5 (ACC_IOU). Kit's baseline example: median IoU 0.71 vs official 0.61.
- **Flag**: area ratio outside sane band; flat/multi-peak landscape AND high field variance;
  solo-vs-block conflict; block hit physical cap under budget; post-move fabric violation.
  Flagged keep original geometry + note saying WHY (they read flag logic).
- **Correct**: everything else; geometry = vertices through T (+ small rotation if refined).
- **Per-plot override gate**: a plot may diverge from the field only if solo budget sufficient,
  match sharp, and fabric check passes; else field wins, disagreement encoded as reduced
  confidence or flag.

### Phase 6 — Confidence calibration (highest-weighted; gets its own phase)
Trap: 9 truths → tuning to them is the overfit they penalise. Manufacture validation instead:
1. **Synthetic ground truth**: take plots where method is most certain (+ the 9 truths), treat
   corrected position as truth, inject KNOWN shifts drawn from the Phase 0 drift distribution,
   re-run pipeline blind, measure recovery (found it? final IoU?). Hundreds of
   (match-metrics → outcome) pairs, free. **Stratify injection across Phase 0 regimes** so the
   synthetic set isn't biased toward easy plots; report per-regime reliability.
2. **Isotonic regression** mapping raw signals — landscape sharpness, peak ratio, solo/block
   agreement, GP variance, seam distance, area-ratio sanity — to **P(IoU > 0.5)**. That
   probability IS the submitted confidence. Monotone → can't overfit wiggles.
3. Artifacts: **reliability diagram** + AUC on synthetic set and the 9 truths → repo + video.
   Direct proof of the exact skill they watch most.

### Phase 7 — Generalization proof (Platinum)
- ONE pipeline, ONE config. All adaptive parameters derived from data (search radius ← drift
  census, patch scale ← median plot size, fusion weights ← signal audit, block cap ← median
  area). "Automatic adaptation fine" is the Platinum wording — this is engineered to it.
- Run both villages fresh. Expect lower mean confidence on Malatavadi — that's calibration
  WORKING; said out loud in the video, not hidden.
- **Ablation table**: field off / block-matching off / boundaries.tif off / calibration→raw
  score. Quantifies what each idea buys.
- **Failure gallery**: 5–10 curated plots flagged-or-failed, one sentence each on why.
  Honest self-knowledge = rubric currency.

### Phase 8 — Deliverables
1. Repo: `predict.py <village_dir>` → contract `predictions.geojson`; modules
   `signal.py / matching.py / drift_field.py / calibrate.py / decide.py`; README with method
   diagram, baseline-ladder table, ablations, reliability diagram, failure gallery; interactive
   before/after HTML map as clickable bonus.
2. Predictions both villages, schema-validated via Test page first.
3. `/transcripts/`: Claude Code session via `/export` + Gemini share links in
   `transcripts/README.md`.
4. **Video script (5 min)**: drift insight (30s) → why field + chamfer over per-plot greed
   (1m) → evidence: ladder, reliability diagram, before/after flips (2m) → where it breaks,
   honestly (1m) → what I'd build next at BhuMe (30s): district-scale drift fields +
   active-learning loop where flagged plots route to humans and fixes become new control points.
5. Google Form + 100-word intro with best-work links.

## 7. Decisions log (from the Gemini whiteboard debate)

| Decision | Outcome |
|---|---|
| Pseudo-NDVI on RGB | Timeboxed; ExG tested in Phase 0 audit, dropped if weak. Gradients + texture + boundaries.tif are primary. |
| GP scalability fear | Corrected: GP cubic in ANCHORS (~hundreds), evaluation linear over plots. Dense GP fine. RANSAC consensus filter kept as anchor-purity gate, not for speed. |
| EM iterations | Hard cap 2. Second-pass stability = diagnostic. |
| Multi-sheet / torn cloth | Seam detection (metadata blockiness + anchor-discordance graph cut + LOO model-selection brake). Per sheet: affine + GP-on-residuals. Seam-distance variance penalty. |
| Block size selection | Evidence-budget growing over adjacency graph + Physical Constraint Cap (10× median plot area; cap-hit ⇒ flag) + Edge-Density Decay on chamfer weights. Variogram demoted to post-hoc audit of the cap. |
| Topology | Vertices through continuous field T(x,y) ⇒ fabric never tears, free. ESRI-style parcel-fabric least-squares adjustment REJECTED as over-engineering (video mention only). |
| Runtime target | Pipeline under ~5–10 min per village. |

## 8. Risk register

| Risk | Mitigation |
|---|---|
| Drift hypothesis wrong (chaotic per-plot) | Phase 0 tests on truths before building; fallback = solo matching + heavier flagging |
| Malatavadi signal too weak | Block matching + field prior built for this; confidence drops honestly where signal dies |
| Calibration self-deception (easy-plot bias in synthetic set) | Stratify injection across regimes; per-regime reliability reporting |
| Overengineering Phase 2 edge map | Hard timebox; baseline ladder makes diminishing returns visible |
| Hidden control plots (already correct) | Leave-alone threshold + negligible-gain rule (Phase 5) |
| Overfitting 9 example truths | Never tune to them; synthetic calibration; they run code on unseen data |

## 9. Immediate next steps (start of next session)

1. ~~Download data + kit~~ DONE — see inventory in §3.
2. Set up env: kit uses `uv` (pyproject + uv.lock in kit/). Read kit/README.md +
   CONTRACT.md + bhume/ modules first; add our extra deps (folium, scikit-learn for
   isotonic/GP, opencv optional). (Env NOT yet verified — check first.)
3. `git init`, sensible `.gitignore` (large tifs — decide whether to commit data or document
   download), commit plan + screenshots + kit.
4. Execute Phase 0 exactly as §6 Phase 0. Write findings into `docs/phase0_findings.md` —
   every downstream threshold cites this file.
5. Keep a running `docs/journal.md` (decisions + observations) — feeds the video script.
6. Remember: export AI transcripts as you go (`/export` for Claude Code; save Gemini share links).

## 10. Workflow note

User's process: Claude Code (this repo) does planning + implementation; Gemini (web) is used
as an external architect-critic — user pastes strategy back and forth. Transcripts of BOTH go
in `/transcripts` (that's a graded deliverable showing how AI is directed). Tone preference:
direct, no fluff.
