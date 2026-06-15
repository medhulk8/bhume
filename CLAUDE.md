# BhuMe Take-Home — Project Knowledge Base

> **MANDATORY PROTOCOL — every significant step (phase complete, scores, arch decision, Gemini sent):**
> 1. Update "Current Status" below immediately — don't batch to session end
> 2. Update "Next Session Priority" below
> 3. Add entry to `sessions.md`
> 4. Commit + push
>
> Session log → `sessions.md` only. Never put session entries in this file.

---

## Current Status

**Phase 6 calibration — COMPLETE (leakage-free, learned weights). Phase 5 + predict.py next.**
Phase 0/1/3/6 done. Phase 3: vadnerbhairav IoU 0.872; malatavadi IoU 0.678.
Phase 6 (`docs/phase6_calibration.md`): honest cross-val AUC vadnerbhairav 0.709, malatavadi 0.814. LR-learned weights: agree_m dominant (−0.73 / −1.52), area_ratio (−0.585 / −0.08), P2SP near-zero (confirms sharpness≠correctness).
OPEN RISK: malatavadi synth AUC 0.814 but real-truth AUC 0.250 (n=3, inverted Spearman). gp_std weight +0.54 wrong sign on malatavadi. Both flagged in doc.

Session log → `sessions.md`
GitHub: https://github.com/medhulk8/bhume (private)

---

## Next Session Priority

```bash
cd /Users/medhul/Desktop/projects/bhume/kit
uv run python ../src/calibrate.py both   # regenerate calibrated predictions
```
Key next steps:
1. Phase 5 decision layer: leave-alone threshold (shift <5m → keep official, safe under CONTROL_SHIFT_M=5.0), area-ratio flag band [0.7,1.4]. Fold into phase3_drift.py or new decide.py.
2. Final `predict.py <village_dir>` single-entry wrapper → predictions.geojson (runs Phase 3 + calibration end-to-end).
3. README: method diagram, ablation ladder, reliability diagrams, failure gallery (5-10 plots).
4. 5-min video script from docs/journal.md.

---

## Gemini Collaboration Protocol

After every significant step (phase complete, major decision, threshold locked, surprising finding):
1. Generate a Gemini prompt and give it to the user unprompted.
2. User pastes it into Gemini, pastes response back.
3. Evaluate the response critically — agree only if reasoning is sound. Flag if wrong.

**Prompt format:** Include current phase, specific decision/finding, relevant numbers, and ask for critique or validation. Be specific — paste data, not vague summaries.

**What Gemini is good for:** Architecture critique, catching overfit/overengineering, second opinion on threshold choices, risk register updates.

**What to push back on:** Suggestions to add complexity without evidence, changes that contradict locked decisions (§Locked Architecture Decisions), anything that reintroduces tuning to the 9 example truths.

---

## What This Is

Intern take-home for BhuMe AI (Bangalore, ₹1.5L, 3 mo). Land-plot boundary correction for Maharashtra cadastral maps — century-old sheets georeferenced with sparse control points → parcels drift off real fields. Task: decide which plots can be nudged to their true position and where. Graded on HOW YOU THINK, not score. AUC (confidence calibration) is most-weighted metric.

Contact: yash@bhume.in. Submission: Google Form (repo URL + 5-min video + résumé).

---

## Repo Layout

```
bhume/
├── CLAUDE.md              ← this file
├── PLAN.md                ← full strategy doc (read once; decisions locked here)
├── data/
│   ├── vadnerbhairav/     # 2,457 plots, 54 km², median 7753 m², Nashik — build intuition here
│   └── malatavadi/        # 2,508 plots, 5.8 km², median 872 m², Kolhapur — stress test
│       both: input.geojson, imagery.tif, boundaries.tif, example_truths.geojson
├── docs/
│   ├── screenshots/       # 1_understand.png … 6_submit.png
│   ├── phase0_findings.md # WRITE THIS — all thresholds cite it (doesn't exist yet)
│   └── journal.md         # decisions + observations log (feeds video script)
├── kit/                   # organiser's starter kit — DO NOT MODIFY
│   ├── bhume/{io,geo,score,baseline}.py
│   ├── quickstart.py
│   └── pyproject.toml / uv.lock
├── src/                   # OUR code goes here (doesn't exist yet)
└── transcripts/           # graded deliverable — /export Claude sessions here
```

---

## Kit API Summary

All from `kit/` — run with `uv run` from `kit/`.

- `bhume.io.load(village_dir)` → `Village(slug, dir, plots[GDF/4326/indexed by plot_number], imagery_path, boundaries_path, example_truths)`
- `bhume.geo.patch_for_plot(src, geom_4326, pad_m=25)` → `Patch(image HxWx3 uint8, transform, crs, bounds)` — imagery CRS is EPSG:3857 (web-mercator), plots are 4326; kit handles conversion
- `bhume.geo.lonlat_to_pixel(src, lon, lat)` → `(col, row)`
- `bhume.geo.pixel_to_lonlat(src, col, row)` → `(lon, lat)`
- `bhume.geo.geom_to_imagery_crs(src, geom_4326)` → reprojected geometry
- `bhume.score.score(predictions_gdf, village)` → `Scorecard` (print it) — ACC_IOU=0.5, CONTROL_SHIFT_M=5.0
- `bhume.baseline.global_median_shift(village)` → naive baseline (median shift from example truths)
- `bhume.io.write_predictions(path, gdf)` — writes contract-valid predictions.geojson

---

## Output Contract

`data/<village>/predictions.geojson` — FeatureCollection EPSG:4326:
- `plot_number` (string, exact match)
- `status`: `"corrected"` | `"flagged"`
- `confidence`: 0–1 (required for corrected; SCORED — must mean something)
- `method_note`: optional free text
- geometry: your predicted boundary (corrected) or original (flagged)
- Omitted plots = "not attempted", no penalty, no credit

---

## Scoring (what matters)

| Metric | Weight | Note |
|---|---|---|
| AUC (conf calibration) | **highest** | Does confidence track accuracy? Flat conf = 0.5 AUC |
| IoU accuracy | high | vs hidden truths; clearing IoU≥0.5 = "accurate" |
| Restraint | high | Seeded control plots (already correct) — moving them = penalty |
| Improvement | medium | Must beat official position |

**Anti-overfit**: only 9 public example truths (6 vadnerbhairav: plots 1145,1403,1476,1710,2647,622; 3 malatavadi: 1177,1763,1966). Never tune to them. Synthetic calibration is the answer.

---

## Implementation Strategy (summary — full detail in PLAN.md §6)

**Core thesis**: drift is spatially coherent (sparse control-point georeferencing → smooth drift field). Estimate the field, not greedy per-plot.

### Phases (in order)
0. **Data forensics** → `docs/phase0_findings.md` (FIRST — validates drift thesis, sets all thresholds)
   - Render plots over imagery (folium HTML map)
   - Test drift hypothesis: shift vectors on 9 truths — coherent?
   - Area-ratio census (drawn/recorded histogram)
   - Signal audit: 30 plots per regime (open/canopy/village/tiny)
   - boundaries.tif characterisation (precision/recall vs visible bunds)
   - Adjacent-vertex sharing check (topology trick viability)
   - Metadata blockiness scan (sheet-boundary candidates)

1. **Baseline ladder** — identity → global_median_shift → greedy solo (ablation rows)

2. **Boundary evidence map** — Sobel + texture variance + boundaries.tif (weighted by Phase 0 reliability) → distance transform raster (one per village, reused)

3. **Registration + dynamic block matching** — adjacency graph (shared vertices + Delaunay backstop); chamfer matching with trimmed-mean score; evidence-budget block growing; Physical Constraint Cap (10× median area → flag if hit); Edge-Density Decay; solo/block disagreement = flag signal

4. **Drift field** — RANSAC-purified anchors → sheet seam detection (anchor-discordance graph cut + LOO model-selection brake) → per-sheet affine + GP on residuals (GP cubic in anchors ~hundreds, linear to evaluate); EM iterations hard-capped at 2; topology: apply T(x,y) to every VERTEX (fabric never tears)

5. **Decision layer** — leave-alone threshold (<5m, safe under CONTROL_SHIFT_M=5.0); flag conditions; corrected = vertices through T

6. **Confidence calibration** — synthetic ground truth (inject known shifts from Phase 0 distribution, stratified by regime) → isotonic regression on raw signals → P(IoU>0.5) = submitted confidence; reliability diagram + AUC reported

7. **Generalization proof** — one pipeline, one config; adaptive parameters from data; ablation table; failure gallery (5–10 plots)

8. **Deliverables** — `predict.py <village_dir>` → predictions.geojson; modules: `signal.py / matching.py / drift_field.py / calibrate.py / decide.py`; README with method diagram + ladder + ablations + reliability diagram + failure gallery; interactive HTML map

---

## Locked Architecture Decisions

| Decision | Outcome |
|---|---|
| Topology | Vertices through T(x,y) — fabric never tears. NOT ESRI-style parcel-fabric adjustment. |
| GP scalability | GP cubic in anchors (~hundreds), not plots. Dense GP fine. |
| Block size | Evidence-budget growing + Physical Constraint Cap (10× median) + Edge-Density Decay |
| Multi-sheet | Seam detection (anchor-discordance graph cut + LOO model-selection brake) → per-sheet affine + GP |
| EM iterations | Hard cap 2 |
| Pseudo-NDVI (ExG) | Tested in Phase 0 audit; drop without ceremony if weak |
| Runtime target | <5–10 min per village |
| Confidence calibration | Isotonic regression on synthetic set, stratified by regime. Never tune to 9 example truths. |

---

## Gotchas

- imagery CRS = EPSG:3857 (web-mercator), plots CRS = EPSG:4326. Kit hides this — always use kit helpers.
- `recorded_area_sqm` = cultivable only (excludes pot-kharaba). Compare drawn area against `recorded_area + pot_kharaba` for area-ratio.
- Area ratio = drawn/recorded is clue not verdict: near 1.0 → placement; far → flag, don't drag.
- `uv run` from `kit/` dir — don't activate venv manually.
- Our code goes in `src/`, not `kit/`.

---

## Session Log → `sessions.md`
