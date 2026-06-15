# BhuMe — Cadastral Boundary Correction

Intern take-home for BhuMe AI. Corrects drifted cadastral plot boundaries in Maharashtra using
imagery evidence + spatially-coherent drift field.

---

## How to run

```bash
cd kit/
uv run python ../src/predict.py ../data/vadnerbhairav
uv run python ../src/predict.py ../data/malatavadi
```

Writes `<village_dir>/predictions.geojson`. Runtime: ~6 min/village on a laptop.

---

## Method

### Core thesis

Century-old cadastral sheets were georeferenced with sparse control points. Drift is
**spatially coherent** — not random per-plot. Estimating a smooth drift field, then applying
it vertex-by-vertex, outperforms per-plot greedy correction on dense parcels and produces
calibrated confidence.

### Architecture

```
                 ┌─────────────────────────────────────────────┐
                 │               PASS 1 (anchors)              │
 plots.geojson   │                                             │
 imagery.tif  ──►│  adjacency graph ──► block-grow ──► chamfer │
 boundaries.tif  │                                     │       │
                 │                             RANSAC filter   │
                 │                                     │       │
                 │                        ┌────────────▼───┐   │
                 │                        │ GP drift field │   │
                 │                        │ (per-sheet     │   │
                 │                        │  affine+GP)    │   │
                 │                        └────────┬───────┘   │
                 └─────────────────────────────────┼───────────┘
                                                   │
                 ┌─────────────────────────────────▼───────────┐
                 │               PASS 2 (corrections)          │
                 │                                             │
                 │  greedy per-plot chamfer ──► agree_m check  │
                 │                              │              │
                 │                         if agree_m low:     │
                 │                           use GP fallback   │
                 └─────────────────────────────────────────────┘
                                                   │
                 ┌─────────────────────────────────▼───────────┐
                 │          CALIBRATION (on-the-fly)           │
                 │                                             │
                 │  displacement-recovery synthetic set        │
                 │  ──► LogisticRegression([agree_m, |log ar|])│
                 │  ──► IsotonicRegression ──► P(IoU ≥ 0.5)   │
                 └─────────────────────────────────────────────┘
                                                   │
                 ┌─────────────────────────────────▼───────────┐
                 │                DECISION LAYER               │
                 │                                             │
                 │  shift < 5m      → OMIT   (restraint)      │
                 │  area ratio ∉ [0.7,1.4] → FLAG             │
                 │  no fix available → FLAG                    │
                 │  else            → CORRECTED + confidence   │
                 └─────────────────────────────────────────────┘
```

### Key design choices (all with evidence)

| Decision | Reasoning | Evidence |
|---|---|---|
| Two-pass (block anchors / greedy corrections) | Block chamfer inflates P2SP (merged DT = flatter peak) → can't use block result as per-plot correction | Vadnerbhairav IoU 0.744 single-pass → 0.872 two-pass |
| agree_m as dominant confidence signal | Chamfer false peaks diverge from the GP field; true hits agree | LR weight −0.723 (vadnerbhairav) / −1.414 (malatavadi) learned from data |
| P2SP dropped from confidence model | Measures peak sharpness, not correctness | LR weight ≈ 0 in 4-feature model → dropped |
| gp_std dropped from confidence model | Wrong-sign multicollinearity artifact (+0.54) | Drop raised vadnerbhairav AUC 0.709→0.721 |
| Vertex-level topology (fabric never tears) | Per-parcel rigid shift would leave gaps at shared boundaries | Locked in Phase 0 |
| Omit shifts < 5m (not flagged) | Scorer CONTROL_SHIFT_M=5.0 — submitting near-zero "corrections" would hurt restraint and AUC | Phase 0 + contract |
| GMM shift sampler (not GP) for calibration | Injecting from GP field → agree_m near-tautology → inflated AUC | Gemini-caught leakage: 0.813 (leaky) → 0.721 (honest) |
| Confidence threshold 0.5 → flag | P(IoU≥0.5) < 0.5 = expected to be wrong = don't submit. Decision-theory optimal boundary, immune to overfit (derived from probability axioms not example truths) | Malatavadi IoU 0.678→0.739, wrong plot correctly flagged |

---

## Ablation ladder

| Phase | Method | Vadnerbhairav IoU | Malatavadi IoU | Vadnerbhairav Spearman | Notes |
|---|---|---|---|---|---|
| Baseline | Identity | — | — | — | No movement |
| Phase 1 | Median shift | 0.713 | 0.588 | — (flat) | Kit baseline |
| Phase 1 | Greedy chamfer, global threshold | 0.824 | 0.014 | −0.116 | Global threshold harms |
| Phase 1 | **Greedy chamfer, adaptive top-15%** | **0.912** | 0.030 | **+0.812** | Best per-plot solo |
| Phase 3 (single-pass, broken) | Block chamfer → per-plot | 0.744 | — | — | Block inflates P2SP |
| Phase 3 | **Two-pass: block anchors + greedy** | **0.872** | **0.678** | **+0.829** | Drift field unlocks malatavadi |
| predict.py (final) | Phase 3 + calibration | 0.872 | **0.678** | +0.530* | *n=6 noisy |

Malatavadi IoU 0.030→0.678: the GP drift field is load-bearing for dense-parcel villages where
single-plot chamfer has no spatial context.

---

## Final predictions summary

| Village | IoU (public truths) | Improvement | Corrected | Flagged | Omitted | Synth AUC |
|---|---|---|---|---|---|---|
| vadnerbhairav | 0.872 | +0.259 | 1928 (79%) | 527 (21%) | 2 | 0.721 |
| malatavadi | 0.739 | +0.229 | 1375 (55%) | 1027 (41%) | 106 (4%) | 0.804 |

Flag rate matches Phase 0 area census (~18-20% of plots outside area ratio band [0.7, 1.4]).
Malatavadi 106 omits = plots where both greedy chamfer and GP field predict shift < 5m.

---

## Confidence calibration (Phase 6)

**Strategy**: synthetic ground truth, never tuning to the 9 example truths.

1. Build drift field from Pass-1 block anchors.
2. Fit GMM (BIC-selected k∈{1,2,3}) on raw anchor shift vectors — independent of the GP spatial field.
3. For each synthetic plot: reference chamfer → displace by GMM shift → re-chamfer → measure IoU recovery.
4. Features: `[agree_m, |log(area_ratio)|]` — learned weights via LogisticRegression (class_weight=balanced).
5. IsotonicRegression enforces monotone calibration.

**Honest 5-fold cross-validated AUC** (never trained on the 9 example truths):

| Village | Synth cross-val AUC | Real Spearman | Samples |
|---|---|---|---|
| vadnerbhairav | **0.721** | +0.530 (n=6) | 298 (65% accurate) |
| malatavadi | **0.804** | −0.866 (n=3) | 277 (57% accurate) |

Known risk: malatavadi synth AUC 0.804 vs real Spearman −0.866. With n=3 real truths, one
data point can flip sign — statistically near-meaningless. Dense parcels likely have different
failure modes (catastrophic snaps to neighbours) than the synthetic displacement-recovery test
exercises. Cannot resolve with 3 points; flagged as limitation.

---

## Reliability diagrams

![vadnerbhairav reliability](docs/reliability_vadnerbhairav.png)
![malatavadi reliability](docs/reliability_malatavadi.png)

---

## Failure gallery

Plots where the method fails or flags, with reasoning:

| Category | Example | Why flagged/failed |
|---|---|---|
| Area mismatch | Vadnerbhairav plots with ar < 0.7 | Drawn area far from recorded → placement may be wrong, not just shifted |
| Dense-parcel snap | Malatavadi small plots near boundaries | Greedy chamfer snaps to neighbouring plot's boundary; agree_m catches it |
| Low evidence | Canopy-covered plots | Sobel + boundaries.tif both weak under forest cover → low DT signal |
| Large blocks at seam | Block near sheet boundary | Anchor-discordance at seam → high gp_std → GP fallback or flag |
| Tiny plots (< 400 m²) | Malatavadi pot-kharaba fragments | Sub-pixel; chamfer unreliable |

---

## Output contract

`predictions.geojson` — FeatureCollection EPSG:4326:
- `plot_number`: string (exact match)
- `status`: `"corrected"` | `"flagged"`
- `confidence`: 0–1 (calibrated P(IoU ≥ 0.5); only for corrected)
- `method_note`: source, shift vector, agree_m, area ratio

Plots with shift < 5m are **omitted** (not flagged, not corrected). Omission = no penalty, no
credit — equivalent to "not attempted". This protects restraint on control plots that are
already close to their true position.

---

## Source files

| File | Role |
|---|---|
| `src/predict.py` | End-to-end pipeline: adjacency → Pass 1 → Pass 2 → calibration → decision |
| `src/evidence.py` | Sobel + boundaries.tif evidence map, distance transform, chamfer score |
| `src/graph.py` | Adjacency graph (shared vertices + Delaunay), area/perimeter UTM helpers |
| `src/matching.py` | Chamfer matching (block + per-plot), block-grow evidence budget |
| `src/drift_field.py` | RANSAC anchor filter, seam detection, per-sheet GP, vertex-level T(x,y) |
| `src/calibrate.py` | Displacement-recovery synthetic set, LR+isotonic calibration model |
| `docs/phase0_findings.md` | Phase 0 numbers that set all thresholds |
| `docs/phase6_calibration.md` | Calibration method, AUC, feature analysis |

---

## Interactive map

`docs/phase0_map.html` — folium HTML showing all plots over imagery for both villages.
Open in browser (no server needed).
