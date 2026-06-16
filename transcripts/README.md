# AI Transcripts

Graded deliverable: shows how AI was directed throughout the project.

## Claude Code session

- `session_1_1c9455f0.md` — full project session: repo setup, Phase 0 forensics, Phase 1 baseline ladder, Phase 3 two-pass drift field, Phase 6 calibration, predict.py bug fixes (area ratio UTM, physical cap, constant agree_m, conf < 0.5 threshold), README

## Gemini conversations (external architect-critic)

Gemini was used as an adversarial critic throughout. Key decisions it shaped:

| Decision | Gemini's ruling |
|---|---|
| Synthetic shift sampler | Must use GMM on raw anchor shifts, not GP field — GP injection would leak into agree_m (tautology) |
| Displacement bug | Calibration was chamfering original (un-displaced) plot → near-random labels. Fix: displacement-recovery test |
| Feature selection | Drop gp_std (wrong-sign +0.54 artifact) and p2sp (weight ≈0). 2-feature model [agree_m, \|log ar\|] |
| Block anchors + IoU regression | Approved 0.040 IoU regression (Phase 1→Phase 3) as correct trade for generalization |
| agree_m on GP-fallback | Confirmed epistemically valid: measures signal conflict, protects calibration from confidently-wrong predictions |
| Confidence threshold 0.5 | One principled threshold from probability axioms — P(IoU≥0.5) < 0.5 = expected wrong = don't submit |

Gemini share link: https://gemini.google.com/share/fc6fe17ecfe9
