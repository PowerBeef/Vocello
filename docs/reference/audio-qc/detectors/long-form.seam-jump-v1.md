# `long-form.seam-jump@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `long-form.seam-jump@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `3b4eaa11fa31cad2` (a plan binds it, so any change is a new version, A7).

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

**Populations** (role set `n3-long-form`): fit N3 (calibration, vocello-long-form-calibration); confirmNegatives N3 (confirmation, vocello-long-form-confirmation); positives P1 (confirmation); shams S (confirmation).

**Limitations.**

- `n3-no-labels`: A measure that exists only on generated takes (the talker's introspection, long-form seams) has no N2 to confirm on: a codec round trip samples no token and joins no segment, so its fit and confirmation negatives are N3 alone (audit section 5.7), the two splits of config/audio-qc-calibration-takes.json disjoint by family, speaker and script. N3 carries no defect labels, so a flag rate f bounds the false-alarm rate only as f / (1 - pi_max), where pi_max is the largest defect prevalence admitted (section 5.1). Each language stratum needs at least 60 scored families in each split (the calibration split plans 80 per language).
- `n3-long-form-cell`: Class J's negatives are the take plan's long-form cell (version 2): 80 projects per split, 8 per language, pool scripts joined to 330-480 planner units (about 30 to 110 s) so the apps' long-form planner splits each at least once, spoken by the split's standard voices through vocello batch --long-form. Each take carries the assembly as its longForm block (seams and the assembler's boundary jump). One pooled threshold over each split's 80 families (the warn floor is 60), the two splits disjoint by family, speaker and script (role set n3-long-form); a script may recur in a few projects of its split.

**Risks.**

- `seam-constructions`: Catalog version 3's seam families act at a long-form take's seams (its longForm seamFrames, which the calibration set reads as the take's seams). SEAM-DISC removes 1, 5 or 20 ms right after a seeded seam, with nothing removed as its sham. SEAM-VOICE replaces the speech after a seam with another voice: a time-aligned re-render by a close procedural voice, or another speaker's words on a speaker-labelled recording. Natural long-form takes have neither a procedural script nor a speaker label, so SEAM-VOICE is not applicable on them and seam-identity has no positives on the n3-long-form cohort. COD-SEAM (T2, a 1-3 frame seam misalignment), the second mechanism a fail level needs, has no producer.
- `long-form-block`: maximumSegmentBoundaryJump comes from the project's LongFormAssemblyEvidence (advisory above 4,096): audio_qc_calibration_takes.py manifest refuses evidence whose output digest is not the take's WAV and records it as the take's longForm block, and audio_qc_calibration_set.py score measures each clip's jump on its own PCM at its seams. A clean take's must equal the assembler's; a T1 construction that keeps the length keeps the seams; one that moves them (SEAM-DISC removes samples after a seam) is measured at the seams the injection mapped, which its entry records.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
