# `long-form.seam-discontinuity@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `long-form.seam-discontinuity@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `409e51c8e2c071e7` (a plan binds it, so any change is a new version, A7).

**Measures.** The largest seam discontinuity z-score over the take's seams (Stage 0 observation seamDiscontinuityMaxZ): the first difference at a seam against the 10 ms either side, (d - mean) / max(std, 1 LSB). A take without seams has no value and abstains.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| J (long form) | 0 | above | single | z-score | pooled |

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`fastqc@8`](../judges/fastqc-v8.md) observations `seamDiscontinuityMaxZ` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `SEAM-DISC` | severe | T1-pcm-construction | yes |

**Populations** (role set `n3-long-form`): fit N3 (calibration, vocello-long-form-calibration); confirmNegatives N3 (confirmation, vocello-long-form-confirmation); positives P1 (confirmation); shams S (confirmation).

**Limitations.**

- `n3-no-labels`: A measure that exists only on generated takes (the talker's introspection, long-form seams) has no N2 to confirm on: a codec round trip samples no token and joins no segment, so its fit and confirmation negatives are N3 alone (audit section 5.7), the two splits of config/audio-qc-calibration-takes.json disjoint by family, speaker and script. N3 carries no defect labels, so a flag rate f bounds the false-alarm rate only as f / (1 - pi_max), where pi_max is the largest defect prevalence admitted (section 5.1). Each language stratum needs at least 60 scored families in each split (the calibration split plans 80 per language).
- `long-form-takes-pending`: Class J's negatives are natural long-form takes (N3 long form, audit section 5.7): multi-segment projects assembled by the product's long-form path, with their segment boundaries. The N3 take plan holds single-segment takes only, so the fit and confirmation cohorts (role set n3-long-form, corpora pending) wait for a long-form take plan: at least 60 scored families in each (one pooled threshold, over at least 3 languages, speakers and scripts), every family a script x voice x seed project with at least one seam, the two disjoint by family, speaker and script.

**Risks.**

- `no-seam-injector`: Injector catalog version 2 has no seam family. The audit's SEAM-* constructions (section 5.2) act at a long-form seam and need the take's seam offsets: SEAM-DISC removes 1, 5 and 20 ms of samples at the seam (mild, moderate, severe; no removal as its sham), and SEAM-VOICE replaces the segment after the seam with the same text rendered by another voice (a same-voice re-render as its sham). COD-SEAM (T2, a 1-3 frame seam misalignment) is the second mechanism. Until they exist the class J detectors have no positives.
- `seam-offsets-not-passed`: The Stage 0 seam z-score reads the take's seams. audio_qc_calibration_set.py score passes a long-form take's seams (its longForm block's seamFrames) to it, but the N3 take plan holds single-segment takes only, so every clip's seamDiscontinuityMaxZ stays null (no-value) until a long-form take plan records each project's assembly.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
