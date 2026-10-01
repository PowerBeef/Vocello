# `introspection.high-entropy@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `introspection.high-entropy@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `b8601f0ef1f10ee6` (a plan binds it, so any change is a new version, A7).

**Measures.** The longest run of consecutive generation steps at which the talker's distribution over the codec codebook and EOS (before penalty, temperature or truncation) had at least 4 nats of entropy (longestHighEntropyRunSteps): sustained uncertainty, where the talker babbles.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| I (introspection) | 0 | above | single | steps | per language |

**Strata.** The talker's per-step distribution follows each language's text tokens and prosody (its entropy, where it stops, and the cycles its pauses and repeated syllables form), so each language is its own clean distribution.

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`fastqc@8`](../judges/fastqc-v8.md) introspection `longestHighEntropyRunSteps` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `GEN-NOEOS` | severe | T3-controlled-generation | yes |

**Populations** (role set `n3-controlled-generation`): fit N3 (calibration, vocello-takes-calibration); confirmNegatives N3 (confirmation, vocello-takes-confirmation); positives P3 (confirmation); shams S (confirmation).

**Limitations.**

- `n3-no-labels`: A measure that exists only on generated takes (the talker's introspection, long-form seams) has no N2 to confirm on: a codec round trip samples no token and joins no segment, so its fit and confirmation negatives are N3 alone (audit section 5.7), the two splits of config/audio-qc-calibration-takes.json disjoint by family, speaker and script. N3 carries no defect labels, so a flag rate f bounds the false-alarm rate only as f / (1 - pi_max), where pi_max is the largest defect prevalence admitted (section 5.1). Each language stratum needs at least 60 scored families in each split (the calibration split plans 80 per language).

**Risks.**

- `introspection-rows-kept`: The engine's introspection summary reaches a take through its diagnostics row, which the engine front-trims at its log cap. The qc-takes lane marks the rows present before it starts, raises the cap (QWENVOICE_DIAGNOSTICS_MAX_MB=64), copies each vocello batch's new rows (generation id, WAV digest, Fast QC flag names, failure code and introspection numbers) into its diagnostics/ directory, and audio_qc_calibration_takes.py manifest --diagnostics binds each take to the row whose samplingWAVDigest is its WAV digest; verdict.txt reports the bound count. A take still without its row abstains (no-value); the 2026-09-27 cohort, generated before the lane kept its rows, bound 251 of its 791 takes.
- `generation-knob-published-only`: GEN-NOEOS@1 (T3, audit section 5.2; construction catalog 1) regenerates a confirmation take (its text, voice, batch seed and delivery) under the registered internal-diagnostics knob QWENVOICE_TALKER_EOS_SUPPRESSION_FRAMES (config/runtime-debug-knobs.json, group controlled-generation), which holds back the talker's first sampled EOS for 6, 18 or 50 codec frames; N = 0 is its sham. Each take's engine row records its hold, and the builder refuses a take whose row does not. The engine's mandatory Fast QC still refuses some held takes (a long slow or silent tail), and a refused take has no published WAV: P3 positives are published takes only, as N3 negatives are, so the detection rate is conditional on the product publishing the take, and the set counts the refusals per variant. Only Custom and Voice Design takes are regenerated (a clone take would need its reference transcript), and a positive whose talker never sampled EOS before the token cap is no entry.
- `entropy-target-uncertain`: EOS suppression is the only construction the audit names for the entropy detector (T3). Whether the talker's entropy stays at 4 nats or more after a suppressed stop, rather than filling the overrun with silence or a loop, is what the confirmation measures; harvested babble (P4) is the other source of positives.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; planned, not confirmed.

**Plan.** [config/audio-qc-preregistrations/introspection.high-entropy@1.json](../../../../config/audio-qc-preregistrations/introspection.high-entropy@1.json): digest `005432b722c54fb6`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N3; injector catalog 1, classes I, 150 per cell.
Calibration cohort audio-qc-calibration-takes (vocello-takes-calibration, manifest `9482435d54f16582`); confirmation cohort audio-qc-calibration-takes (vocello-takes-confirmation, manifest `20211aeea93a0abd`).

**Confirmation.** Not run: no ledger entry.

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
