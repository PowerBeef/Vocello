# `introspection.eos-overrun@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `introspection.eos-overrun@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `746c5a516924e7d8` (a plan binds it, so any change is a new version, A7).

**Measures.** Generation steps at which the talker gave EOS a probability of at least 0.5 and generation went on (eosLikelyStepsWithoutStop): the take ran on past points where the talker would likely have stopped.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| I (introspection) | 0 | above | single | steps | per language |

**Strata.** The talker's per-step distribution follows each language's text tokens and prosody (its entropy, where it stops, and the cycles its pauses and repeated syllables form), so each language is its own clean distribution.

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`fastqc@8`](../judges/fastqc-v8.md) introspection `eosLikelyStepsWithoutStop` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `GEN-NOEOS` | severe | T3-controlled-generation | yes |

**Populations** (role set `n3-controlled-generation`): fit N3 (calibration, vocello-takes-calibration); confirmNegatives N3 (confirmation, vocello-takes-confirmation); positives P3 (confirmation); shams S (confirmation).

**Limitations.**

- `n3-no-labels`: A measure that exists only on generated takes (the talker's introspection, long-form seams) has no N2 to confirm on: a codec round trip samples no token and joins no segment, so its fit and confirmation negatives are N3 alone (audit section 5.7), the two splits of config/audio-qc-calibration-takes.json disjoint by family, speaker and script. N3 carries no defect labels, so a flag rate f bounds the false-alarm rate only as f / (1 - pi_max), where pi_max is the largest defect prevalence admitted (section 5.1). Each language stratum needs at least 60 scored families in each split (the calibration split plans 80 per language).

**Risks.**

- `introspection-not-carried`: The engine's introspection summary lands in the telemetry row's engineIntrospection. Neither the N3 takes manifest (audio_qc_calibration_takes.py manifest) nor measurements.json (audio_qc_calibration_set.py score) carries it yet, so every clip lacks its introspection block and abstains (no-value) until the takes lane records the summary per take and the scorer copies it into each clip.
- `no-generation-knob`: GEN-NOEOS (T3, audit section 5.2) suppresses EOS for 6-50 frames through a registered knob, with no suppression (N = 0) as its sham; config/runtime-debug-knobs.json lists no such knob, so the entropy and EOS detectors have no positives until one is registered under the release-only rules.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
