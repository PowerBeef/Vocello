# `introspection.token-loop@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `introspection.token-loop@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `40b7fd7bdec91b90` (a plan binds it, so any change is a new version, A7).

**Measures.** The span, in codec frames (12.5 per second), of the longest exact codebook-0 token cycle of period 2 to 32 in the engine's introspection summary (tokenCycleSpanFrames); a take without one scores 0. A stuck single token (period 1, longestRepeatedTokenRunFrames) is not scored: a pause repeats one token.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| I (introspection) | 0 | above | single | codec-frames | per language |

**Strata.** The talker's per-step distribution follows each language's text tokens and prosody (its entropy, where it stops, and the cycles its pauses and repeated syllables form), so each language is its own clean distribution.

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`fastqc@8`](../judges/fastqc-v8.md) introspection `tokenCycleSpanFrames` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `COD-LOOP` | severe | T2-codec-construction | yes |

**Populations** (role set `n3-codec-trace`): fit N3 (calibration, vocello-takes-calibration); confirmNegatives N3 (confirmation, vocello-takes-confirmation); positives P2 (confirmation); shams S (confirmation).

**Limitations.**

- `n3-no-labels`: A measure that exists only on generated takes (the talker's introspection, long-form seams) has no N2 to confirm on: a codec round trip samples no token and joins no segment, so its fit and confirmation negatives are N3 alone (audit section 5.7), the two splits of config/audio-qc-calibration-takes.json disjoint by family, speaker and script. N3 carries no defect labels, so a flag rate f bounds the false-alarm rate only as f / (1 - pi_max), where pi_max is the largest defect prevalence admitted (section 5.1). Each language stratum needs at least 60 scored families in each split (the calibration split plans 80 per language).

**Risks.**

- `introspection-rows-kept`: The engine's introspection summary reaches a take through its diagnostics row, which the engine front-trims at its log cap. The qc-takes lane marks the rows present before it starts, raises the cap (QWENVOICE_DIAGNOSTICS_MAX_MB=64), copies each vocello batch's new rows (generation id, WAV digest, Fast QC flag names, failure code and introspection numbers) into its diagnostics/ directory, and audio_qc_calibration_takes.py manifest --diagnostics binds each take to the row whose samplingWAVDigest is its WAV digest; verdict.txt reports the bound count. A take still without its row abstains (no-value); the 2026-09-27 cohort, generated before the lane kept its rows, bound 251 of its 791 takes.
- `codec-loop-construction`: COD-LOOP@1 (T2, audit section 5.2; construction catalog 1, scripts/lib/qc_qualification/codec_trace.py) repeats 4, 12 or 32 codec frames (0.32, 0.96 or 2.56 s) once, all 16 codebooks, at a seeded start in the middle 60% of a confirmation take's recorded codec trace (the same start for every variant of a take), and vocello bench --codec-loop decodes it on the codec replay's full arm (the production non-streaming 25-frame schedule and window), then the production output limiter and the publication marking; the untouched trace is its sham. The copies are exact in every codebook, while a talker loop repeats codebook 0 and samples the acoustic codebooks anew: codebook 0, which the score reads, is exact in both, but a detector that reads the audio would hear a cleaner loop than a natural one. The qc-takes lane keeps each short-form take's trace since 2026-09-30, so only a confirmation cohort generated since then has sources (scripts/macos_test.sh qc-introspection).
- `introspection-from-trace`: A T2 positive never runs the talker, so its summary is the Python mirror over the looped codebook-0 trace (audio_qc_observations.introspection_summary, which audio_qc_introspection_positives.py loop-set writes into the entry): the cycle fields are exact, but entropy and EOS need the talker's logits, so the entry records no observed step and only the loop detector reads T2 positives. The negatives' summaries come from the engine; the two sides agree exactly on integers (config/audio-qc-stage0-observations.json), and loop-plan refuses a source trace whose codebook 0 does not reproduce its take's own engine summary.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
