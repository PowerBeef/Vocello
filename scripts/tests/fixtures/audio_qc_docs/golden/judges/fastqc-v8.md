# `fastqc@8`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `fastqc@8` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Stage 0 Fast QC inside the engine: amplitude and waveform-shape measures on every take; the only product publication gate.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `gating` | legacy-unqualified | dsp | - | yes | yes | 0 (engine) | unmeasured |

`gating`: Feeds a verdict that can fail a take or a lane.

## Provenance

- License tier **A** (none): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: none
- Code: Vocello (owned)
- Training data: none
- Independence: vendor Vocello; architecture deterministic DSP; training data none; label lineage none; correlated with the generator's lab: no.

## Pins

- Digest status: `no-learned-weights`.
- Verification: Owned deterministic code; the algorithm version is part of the gate baseline identity.

## Execution

- Stage 0; lane engine; not orchestrated.
- Note: Inside the engine on every take; the orchestrator reads its receipt.
- Resources: canonical-host peak -; admission ceiling - (provisional); policy: engine memory contract.
- Ceiling basis: Bounded, file-bound streaming inside the engine.
- Output identity: qcAlgorithmVersion, pcmSHA256. Envelope identity: -.
- Legacy identifiers: algorithms: qcAlgorithmVersion 8; sources: Sources/QwenVoiceCore/GenerationOutputAdapter.swift, scripts/lib/audio_qc.py.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- No canary record.

Its accuracy is claimed only through the detectors that consume it:

| Detector | Class | Languages | Reads | Qualification |
|---|---|---|---|---|
| [`signal.clicks@1`](../detectors/signal.clicks-v1.md) | A (signal) | english, french, german | fastqc `clickEventsPerSecond` | not qualified |

**UNQUALIFIED.** No committed calibration record qualifies a detector that consumes this judge, so every verdict built on it composes as `uncalibrated`.
<!-- END GENERATED audio-qc-docs:accuracy -->
