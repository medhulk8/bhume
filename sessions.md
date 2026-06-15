# Session Log

### 2026-06-16 — Session 3
- Created `src/evidence.py`, `src/graph.py`, `src/matching.py`, `src/drift_field.py`, `src/phase3_drift.py`
- Phase 3 complete (two-pass: block chamfer for anchors, greedy for corrections, GP fallback).
- Scores: vadnerbhairav IoU 0.872 / Spearman +0.829; malatavadi IoU 0.678 (up from 0.030).
- Created `src/calibrate.py` (Phase 6 synthetic calibration). Running on vadnerbhairav.
- Gemini approved block anchors, 0.040 regression, and Phase 6 plan. Directive: synthetic shifts must sample from GP field, not uniform scatter.
- CLAUDE.md update protocol strengthened: update after every significant step, not just session end.
- sessions.md = log only; CLAUDE.md = living status (no session entries there).
- Phase 6 first run: AUC 0.490 (P2SP alone fails — predicts sharpness not correctness). Diagnosed: false chamfer peaks have low P2SP but wrong location.
- Fix: added chamfer-GP agreement signal (agree_m). AUC 0.490 → 0.813 on vadnerbhairav. Spearman on 6 truths 0.765.
- Phase 6 v1 (leaky): synth AUC vadnerbhairav 0.813, malatavadi 0.730. DISCARDED.
- Gemini caught data leakage: injected truth = GP_field, agree_m = |chamfer-GP| → tautology. Also found my displacement bug (no displacement → near-random labels).
- Phase 6 v2 (leakage-free): inject from GMM on raw anchor shifts + displacement-recovery + LogisticRegression→isotonic (learned weights, not hand-set).
- Honest cross-val AUC: vadnerbhairav 0.709, malatavadi 0.814. agree_m dominant (LR proved it). P2SP near-worthless (-0.04).
- OPEN RISK flagged: malatavadi synth 0.814 vs real-truth AUC 0.250 (n=3 inverted). gp_std +0.54 wrong sign on malatavadi.

### 2026-06-15 — Session 2
- Installed uv (not on PATH initially). Ran `uv sync` in kit/. Added folium, scikit-learn, matplotlib, opencv-python-headless.
- Verified baseline: vadnerbhairav median IoU=0.713 vs official=0.612 (improvement +0.112).
- Ran full Phase 0 forensics (`src/phase0_forensics.py`). All 7 sub-tasks complete.
- Key Phase 0 numbers (see `docs/phase0_findings.md` for full detail):
  - Drift vectors: vadnerbhairav mean shift (-5.2m, +12.2m), malatavadi (+8.1m, +1.3m). Max drift 18.6m → search radius 28m.
  - Angular spread 71° combined; within-village spread 6–29° → per-village drift fields correct model.
  - Area-ratio: 80.3% vadnerbhairav / 82.0% malatavadi in [0.7, 1.4] → ~80% placement-fixable.
  - Shared vertices viable: 25%/31% in both villages.
  - Blockiness 0.77 in both → sheet seam detection viable.
- Built `src/baseline_ladder.py`, `src/phase0_forensics.py`.
- Phase 1 final scores: vadnerbhairav IoU 0.912, Spearman +0.812. Malatavadi IoU 0.030 (structural).
- Committed and pushed all outputs.

### 2026-06-15 — Session 1
- Created GitHub repo (private): https://github.com/medhulk8/bhume
- Read all kit modules (io.py, geo.py, score.py, baseline.py, CONTRACT.md, README.md)
- Created CLAUDE.md
- No implementation code written. Env not yet verified. Phase 0 not started.
