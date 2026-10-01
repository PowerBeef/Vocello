# `pitch.pyin@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `pitch.pyin@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Pitch tracker (audit section 4.4): probabilistic YIN over the full 50-1,000 Hz range with a fixed frame and hop, voicing probabilities kept; feeds class E and F detectors.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `shadow` | legacy-unqualified | dsp | - | no | no | 1 (dsp) | D0 (expected D0) |

`shadow`: Runs beside the current judges; its verdicts are uncalibrated and never block.

**Audit section.** 4.4.

## Provenance

- License tier **A** (none): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: none
- Code: ISC (librosa); the configuration is owned
- Training data: none
- Notices: soxr (LGPL-2.1-or-later), a librosa dependency, runs unmodified inside the internal, never-shipped runtime venv
- Independence: vendor librosa (pYIN, Mauch and Dixon 2014); architecture probabilistic YIN with HMM voicing decoding; training data none; label lineage none; correlated with the generator's lab: no.
- Sources: <https://librosa.org/doc/latest/generated/librosa.pyin.html>

## Pins

- Digest status: `no-learned-weights`.
- Verification: Owned configuration of librosa's pYIN; the runtime lock pins librosa and every dependency by hash, and no learned weights load. The worker refuses an excluded runtime package before it runs.
- Runtime: librosa 0.11.0, numba 0.67.0, numpy 2.4.6, scipy 1.18.1.

## Execution

- Stage 1; lane dsp; engine pyin-librosa; device cpu; threads 1 (provisional); batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment
- Configuration: {"betaParameters": [2, 18], "boltzmannParameter": 2, "center": true, "fmax": 1000.0, "fmin": 50.0, "frameLength": 1024, "hopLength": 160, "maxTransitionRate": 35.92, "nThresholds": 100, "noTroughProb": 0.01, "padMode": "constant", "resolution": 0.1, "sampleRateHz": 16000, "switchProb": 0.01}
- Acquisition: directory="pitch-pyin", stage=1, runtime="librosa-dsp"
- Resources: canonical-host peak 0.49 GiB; admission ceiling 0.59 GiB (calibrated), measured in session 20260927-aaba14fd; policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: Audit section 3.4 DSP-pool estimate (0.3 GB), raised to 512 MiB for librosa and numba; provisional until two clean M6 runs measure its peak.
- Output identity: workerSourceSHA256, engine, configuration, runtimeDependenciesDigest, runtimeVersions, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- Canary record: [benchmarks/audio-qc-qualification/20261001-505107fc/judges/pitch.pyin-v1.json](../../../../benchmarks/audio-qc-qualification/20261001-505107fc/judges/pitch.pyin-v1.json) (2026-10-01), output identity `a12f12f5cf71a807`.
- Re-cited after its output identity changed; replaced canary records: [benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/pitch.pyin-v1.json](../../../../benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/pitch.pyin-v1.json) (2026-09-27, output identity `772bcaf2018a0b50`).
- Canary qualification passed: yes; determinism D0 over 9 rows (9 bit-exact, 0 discrete mismatches); peak 0.29 GiB on mac-mini-m6-16gb (session 20261001-505107fc).

Its accuracy is claimed only through the detectors that consume it:

| Detector | Class | Languages | Reads | Qualification |
|---|---|---|---|---|
| [`prosody.pitch-break@1`](../detectors/prosody.pitch-break-v1.md) | F (prosody) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | raw-output `maxPitchStepSemitones` | refused |
| [`prosody.octave-jump@1`](../detectors/prosody.octave-jump-v1.md) | F (prosody) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | raw-output `longestOctaveDisplacementSeconds` | refused |
| [`prosody.pitch-instability@1`](../detectors/prosody.pitch-instability-v1.md) | F (prosody) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | raw-output `pitchJumpsPerVoicedSecond` | refused |

**UNQUALIFIED.** No committed calibration record qualifies a detector that consumes this judge, so every verdict built on it composes as `uncalibrated`.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Judge panel acquisition](../../audio-qc-engineering.md#judge-panel-acquisition-aq-06-prepared-2026-09-26) and [panel jobs and qualification](../../audio-qc-engineering.md#panel-jobs-and-qualification-aq-06-p8-tooling-2026-09-27): how a panel judge is fetched, run under admission and canaried.
