"""The staged audio QC pipeline after the generator exits (AQ-05, audit 2026-09-25 sections 3.1-3.6).

`scripts/audio_qc_orchestrator.py` is the one orchestrator for Stages 1-3; it
loads no model. This package holds its parts:

- `admission`: the budgeted admission semaphore (decision 9a). Admitted workers
  share the generator's host lock instead of taking it exclusively, and the
  judge registry's per-judge ceilings are admitted against one memory budget,
  with one MLX GPU worker at a time beside at most two CPU workers.
- `workers`: one persistent, supervised worker per judge per run
  (`scripts/audio_qc_worker.py`), JSONL rows over stdout, emitted rows kept on a
  crash and the remainder retried once in a fresh worker.
- `layered_cache`: the L0 canonical audio, L1 raw judge output and L2 metrics
  layers, keyed by the judges' output identities. Verdicts are never cached.
- `verdicts`: Stage 3 over L2 metrics, beside the pure composer of
  `lib.qc_qualification.composer`.
- `evidence`: the take-evidence schema (digests and metrics only) and the
  untracked private bundle.
"""
