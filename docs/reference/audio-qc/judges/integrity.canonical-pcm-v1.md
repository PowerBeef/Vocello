# `integrity.canonical-pcm@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `integrity.canonical-pcm@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Canonical 16 kHz PCM integrity (sample count, peak, RMS, clipped fraction; all-zero and truncated PCM are rejected) ahead of every other delivery layer; a rejection routes the pair to rejected.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `gating` | legacy-unqualified | dsp | - | no | no | 1 (dsp) | unmeasured |

`gating`: Feeds a verdict that can fail a take or a lane.

## Provenance

- License tier **A** (none): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: none
- Code: Vocello (owned)
- Training data: none
- Independence: vendor Vocello; architecture deterministic DSP; training data none; label lineage none; correlated with the generator's lab: no.

## Pins

- Digest status: `no-learned-weights`.
- Verification: Owned deterministic code bound by source digest in every cache identity.

## Execution

- Stage 1; lane dsp; engine in-process; device cpu; threads 1; batch size 1; orchestrated; worker `scripts/audio_qc_orchestrator.py`.
- Thread control: orchestrator-process
- Resources: canonical-host peak -; admission ceiling - (provisional); policy: bounded by construction.
- Ceiling basis: Streams the canonical derivative in 1 MiB blocks.
- Output identity: analyzerSourceSHA256, layerVersion, numpyVersion, canonicalizationIdentity, threads. Envelope identity: -.
- Legacy identifiers: cascadeLayers: pcm-integrity-qc; sources: scripts/run_local_delivery_cascade.py.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- No canary record.

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Staged pipeline, workers and admission](../../audio-qc-engineering.md#staged-pipeline-workers-and-admission-aq-05-2026-09-26): the canonical PCM every later stage reads.
