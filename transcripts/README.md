# AI Transcripts

Graded deliverable: shows how AI was directed throughout the project.

## Claude Code sessions

Exported via `/export` in the Claude Code CLI. Files in this directory:
- `session_1.md` — repo setup, PLAN.md, data inventory
- `session_2.md` — Phase 0 forensics, Phase 1 baseline ladder
- `session_3.md` — Phase 3 two-pass drift field, Phase 6 calibration
- `session_4.md` — predict.py, bug fixes (area ratio, physical cap, agree_m), README

Export command: `/export` in Claude Code session → saves to this folder.

## Gemini conversations (external architect-critic)

Gemini was used as an adversarial critic throughout. Key decisions it shaped:

| Session | Decision | Gemini's ruling |
|---|---|---|
| 3 | Synthetic shift sampler | Must use GMM on raw anchor shifts, not GP field — GP injection would leak into agree_m (tautology) |
| 3 | Displacement bug | Calibration was chamfering original (un-displaced) plot → near-random labels. Fix: displacement-recovery test |
| 3 | Feature selection | Drop gp_std (wrong-sign +0.54 artifact) and p2sp (weight ≈0). 2-feature model [agree_m, |log ar|] |
| 3 | Block anchors + regression | Approved 0.040 IoU regression (Phase 1→Phase 3) as correct trade for generalization |
| 4 | agree_m on GP-fallback | Confirmed epistemically valid: measures signal conflict, protects calibration from confidently-wrong predictions |

Gemini share links: *(add share links from each Gemini conversation here)*
