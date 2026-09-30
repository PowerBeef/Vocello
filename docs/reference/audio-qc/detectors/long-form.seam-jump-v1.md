# `long-form.seam-jump@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `long-form.seam-jump@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `6b0ba50e7c25f43b` (a plan binds it, so any change is a new version, A7).

**Measures.** The long-form assembler's largest adjacent-sample step at a segment boundary, in PCM16 units (maximumSegmentBoundaryJump), whose warn-first advisory the audit calibrates with the seam injectors (section 7.1).

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| J (long form) | 0 | above | single | pcm16-units | pooled |

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`fastqc@8`](../judges/fastqc-v8.md) longform `maximumSegmentBoundaryJump` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `SEAM-DISC` | severe | T1-pcm-construction | yes |

**Populations** (role set `n3-long-form`): fit N3 (calibration, pending-vocello-long-form-calibration); confirmNegatives N3 (confirmation, pending-vocello-long-form-confirmation); positives P1 (confirmation); shams S (confirmation).

**Limitations.**

- `n3-no-labels`: A measure that exists only on generated takes (the talker's introspection, long-form seams) has no N2 to confirm on: a codec round trip samples no token and joins no segment, so its fit and confirmation negatives are N3 alone (audit section 5.7), the two splits of config/audio-qc-calibration-takes.json disjoint by family, speaker and script. N3 carries no defect labels, so a flag rate f bounds the false-alarm rate only as f / (1 - pi_max), where pi_max is the largest defect prevalence admitted (section 5.1). Each language stratum needs at least 60 scored families in each split (the calibration split plans 80 per language).
- `long-form-takes-pending`: Class J's negatives are natural long-form takes (N3 long form, audit section 5.7): multi-segment projects assembled by the product's long-form path, with their segment boundaries. The N3 take plan holds single-segment takes only, so the fit and confirmation cohorts (role set n3-long-form, corpora pending) wait for a long-form take plan: at least 60 scored families in each (one pooled threshold, over at least 3 languages, speakers and scripts), every family a script x voice x seed project with at least one seam, the two disjoint by family, speaker and script.

**Risks.**

- `no-seam-injector`: Injector catalog version 2 has no seam family. The audit's SEAM-* constructions (section 5.2) act at a long-form seam and need the take's seam offsets: SEAM-DISC removes 1, 5 and 20 ms of samples at the seam (mild, moderate, severe; no removal as its sham), and SEAM-VOICE replaces the segment after the seam with the same text rendered by another voice (a same-voice re-render as its sham). COD-SEAM (T2, a 1-3 frame seam misalignment) is the second mechanism. Until they exist the class J detectors have no positives.
- `long-form-evidence-not-carried`: maximumSegmentBoundaryJump comes from the assembled project's long-form assembly evidence (LongFormAssemblyEvidence, advisory above 4,096). measurements.json carries no longForm block yet, and a T1 positive injected after assembly needs a Python mirror of the assembler's boundary jump at the recorded segment boundaries.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
