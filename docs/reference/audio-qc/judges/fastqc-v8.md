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
| [`signal.dropout@2`](../detectors/signal.dropout-v2.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | pcm `longestInteriorDigitalSilenceMS` | qualified (warn) |
| [`signal.terminal-silence@1`](../detectors/signal.terminal-silence-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | fastqc `trailingSilenceMS` | qualified (warn) |
| [`signal.terminal-silence@2`](../detectors/signal.terminal-silence-v2.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | pcm `trailingDigitalSilenceMS` | qualified (warn) |
| [`signal.dc-offset@1`](../detectors/signal.dc-offset-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | absolute fastqc `dcOffset` | qualified (warn) |
| [`signal.dc-offset@2`](../detectors/signal.dc-offset-v2.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | absolute fastqc `dcOffset` | qualified (warn) |
| [`signal.level@1`](../detectors/signal.level-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | fastqc `rmsDBFS` | qualified (warn) |
| [`signal.clipping@1`](../detectors/signal.clipping-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | fastqc `hotSamples` | refused |
| [`signal.clipping@2`](../detectors/signal.clipping-v2.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | pcm `symmetricFlatTopFraction` | qualified (warn) |
| [`signal.noise@1`](../detectors/signal.noise-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | observations `wadaSNRDB` | qualified (warn) |
| [`signal.band-limit@1`](../detectors/signal.band-limit-v1.md) | A (signal) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | observations `effectiveBandwidthHz` | qualified (warn) |
| [`boundary.run-on@2`](../detectors/boundary.run-on-v2.md) | C (boundary) | english, french, german, italian, portuguese, russian, spanish, chinese, japanese | pcm `lastActiveSeconds` | qualified (warn) |
| [`introspection.token-loop@1`](../detectors/introspection.token-loop-v1.md) | I (introspection) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | introspection `tokenCycleSpanFrames` | not qualified |
| [`introspection.high-entropy@1`](../detectors/introspection.high-entropy-v1.md) | I (introspection) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | introspection `longestHighEntropyRunSteps` | not qualified |
| [`introspection.eos-overrun@1`](../detectors/introspection.eos-overrun-v1.md) | I (introspection) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | introspection `eosLikelyStepsWithoutStop` | not qualified |
| [`long-form.seam-discontinuity@1`](../detectors/long-form.seam-discontinuity-v1.md) | J (long form) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | observations `seamDiscontinuityMaxZ` | refused |
| [`long-form.seam-jump@1`](../detectors/long-form.seam-jump-v1.md) | J (long form) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | longform `maximumSegmentBoundaryJump` | refused |
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Threshold-change authority](../../audio-qc-engineering.md#threshold-change-authority): the rule its existing fail bounds live under (A10).
- [The first measurement of Fast QC v8](../../audio-qc-engineering.md#qualification-engine-and-the-first-measurement-of-fast-qc-v8-aq-03-2026-09-25), [speaking-rate plausibility](../../audio-qc-engineering.md#speaking-rate-plausibility-qc-v8-audit-10-2026-09-25) and [clustered click events](../../audio-qc-engineering.md#clustered-click-events-audit-85-2026-09-25).
