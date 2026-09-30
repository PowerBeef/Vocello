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
| [`signal.clicks@1`](../detectors/signal.clicks-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | fastqc `clickEventsPerSecond` | qualified (warn) |
| [`signal.dropout@1`](../detectors/signal.dropout-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | fastqc `longestSilenceMS` | qualified (warn) |
| [`signal.terminal-silence@1`](../detectors/signal.terminal-silence-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | fastqc `trailingSilenceMS` | qualified (warn) |
| [`signal.dc-offset@1`](../detectors/signal.dc-offset-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | absolute fastqc `dcOffset` | qualified (warn) |
| [`signal.level@1`](../detectors/signal.level-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | fastqc `rmsDBFS` | qualified (warn) |
| [`signal.clipping@1`](../detectors/signal.clipping-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | fastqc `hotSamples` | refused |
| [`signal.noise@1`](../detectors/signal.noise-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | observations `wadaSNRDB` | qualified (warn) |
| [`signal.band-limit@1`](../detectors/signal.band-limit-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | observations `effectiveBandwidthHz` | not qualified |
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Threshold-change authority](../../audio-qc-engineering.md#threshold-change-authority): the rule its existing fail bounds live under (A10).
- [The first measurement of Fast QC v8](../../audio-qc-engineering.md#qualification-engine-and-the-first-measurement-of-fast-qc-v8-aq-03-2026-09-25), [speaking-rate plausibility](../../audio-qc-engineering.md#speaking-rate-plausibility-qc-v8-audit-10-2026-09-25) and [clustered click events](../../audio-qc-engineering.md#clustered-click-events-audit-85-2026-09-25).
