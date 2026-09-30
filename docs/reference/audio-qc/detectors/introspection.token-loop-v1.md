# `introspection.token-loop@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `introspection.token-loop@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `0794b60e5319d04b` (a plan binds it, so any change is a new version, A7).

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
- `no-codec-trace-injector`: Injector catalog version 2 is T1 only. COD-LOOP (T2, audit section 5.2) repeats 4-32 codec frames (0.32-2.56 s) of a take's code trace, decoded by the production decoder, with the untouched trace as its sham; it needs a mutation-recipe replay mode, since BenchCodecReplay replays only an unmodified, digest-verified trace. Until it exists the loop detector has no positives.
- `introspection-from-trace`: A T2 positive never runs the talker, so its summary comes from the Python mirror over the mutated codebook-0 trace (audio_qc_observations.introspection_summary): the cycle fields are exact, but entropy and EOS need the talker's logits, so only the loop detector can use T2 positives. The negatives' summaries come from the engine; the two sides agree exactly on integers (config/audio-qc-stage0-observations.json).

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
