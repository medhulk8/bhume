# Session Log

### 2026-06-16 — Session 3
- Created `src/evidence.py` (Phase 2 signal module, renamed from signal.py to avoid stdlib conflict)
- Created `src/graph.py` (adjacency graph: shared vertices + Delaunay backstop)
- Created `src/matching.py` (block-grow BFS + chamfer_block)
- Created `src/drift_field.py` (RANSAC anchor purification, seam detection, GP drift field)
- Created `src/phase3_drift.py` (Phase 3+4 orchestration — two-pass architecture)
- Phase 3 complete. Key fix: block chamfer had higher P2SP (flatter merged DT) than greedy. Two-pass: block for anchors, greedy for corrections, GP fallback for uncertain.
- Final Phase 3 scores: vadnerbhairav IoU 0.872 / Spearman +0.829; malatavadi IoU 0.678 (up from 0.030). Runtime: ~5 min/village.
- CLAUDE.md and sessions.md restructured (session log moved out of CLAUDE.md).

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
