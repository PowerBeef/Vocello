---
name: vocello-audio-qc
description: Prepare, run and aggregate the offline, report-only multimodal audio QC complement (Gemini 4 Neon via Antigravity read_file and run_workflow) alongside QC v2 and quality_screen.py.
---

# Multimodal audio QC complement

Use this procedure to run the offline, report-only multimodal audio QC layer (`RF-72`) on a QC v2
run, a paired `scripts/quality_screen.py` comparison, or the Q1/Q2 calibration benchmarks.

Read `docs/reference/qc.md` and `config/qc/multimodal-rubric-v1.json` first. This layer is strictly
**report-only advisory**: it never replaces Fast QC, never clears a machine failure, never alters
QC v2 `SCORING_SOURCES`/`scoring_identity`, and never overrides `RF-57` decision rules. Personal
user recordings are blocked by default; only allowlisted non-personal corpus/synthetic roots (or
explicitly opted-in non-clone synthetic confirm batches) may be staged.

1. Prepare a blinded packet (`scripts/dev.sh qc multimodal prepare|prepare-screen|prepare-q1|prepare-q2 ...`):
   staging normalizes to 16 kHz mono PCM16, assigns opaque randomized hex filenames, builds focused
   local zoom crops and 440 Hz marker-stitched streams (`[Ref | Take]` and dual-order `[A | B]` /
   `[B | A]`), and writes `build/private/qc/multimodal/<session>/review-packet.json`.
2. Emit the resumable Antigravity workflow (`scripts/dev.sh qc multimodal workflow --session <session>`)
   and execute it with `run_workflow(ScriptPath=...)` using read-only `research` workers inheriting
   Gemini 4 Neon. Workers read only their assigned opaque `.wav` path via `read_file`. Join the
   workflow completely before starting any native build or measured lane.
3. Reconcile verdicts (`scripts/dev.sh qc multimodal aggregate --session <session> --verdicts ...`)
   or compute privacy-safe aggregate qualification receipts (`scripts/dev.sh qc multimodal qualify`).
   Never commit raw audio, transcripts, prompts, or private paths; only aggregate evaluation JSON
   enters Git (`benchmarks/qc/multimodal-eval-v*.json`).
