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

- `seam-constructions`: Catalog version 3's seam families act at a long-form take's seams (its longForm seamFrames, which the calibration set reads as the take's seams). SEAM-DISC removes 1, 5 or 20 ms right after a seeded seam, with nothing removed as its sham. SEAM-VOICE replaces the speech after a seam with another voice. On the n3-long-form cohort a take's generation voice is its speaker label (lead decision 2026-09-30: a Built-in speaker, a Voice Design brief, a clone reference speaker), so its take-voice-* variants splice another long-form take of the same split and language, of another voice whose recorded gender does not differ, from the start of one of its segments: the whole segment after the seam (severe) or its first 1 or 2 s, level-matched and crossfaded over 5 ms inside the replaced span; the sham splices another take of the same voice the same way. The label is the replaced span, and each entry's seams and longForm block describe its output. The positives are constructed: a splice joins two renderings, so part of a cosine drop may come from the join, which the same-voice sham measures. Take plan version 2 records no brief gender, so a Built-in speaker may take a brief's voice of either sound, and a brief need not sound the same in two takes, so its sham may change voice too. COD-SEAM (T2, a 1-3 frame seam misalignment), the second mechanism a fail level needs, has no producer.
- `long-form-block`: maximumSegmentBoundaryJump comes from the project's LongFormAssemblyEvidence (advisory above 4,096): audio_qc_calibration_takes.py manifest refuses evidence whose output digest is not the take's WAV and records it as the take's longForm block, and audio_qc_calibration_set.py score measures each clip's jump on its own PCM at its seams. A clean take's must equal the assembler's; a T1 construction that keeps the length keeps the seams; one that moves them (SEAM-DISC removes samples after a seam) is measured at the seams the injection mapped, which its entry records.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Refused; confirmed (refused).

**Plan.** [config/audio-qc-preregistrations/long-form.seam-jump@1.json](../../../../config/audio-qc-preregistrations/long-form.seam-jump@1.json): digest `02344db45583f6a4`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N3; injector catalog 3, classes J, 150 per cell.
Calibration cohort audio-qc-calibration-takes (vocello-long-form-calibration, manifest `4a141aaae38fc373`); confirmation cohort audio-qc-calibration-takes (vocello-long-form-confirmation, manifest `8366ac9b9b2368d5`).

**Confirmation.** Ledger entry refused (far-pooled-not-met, far-per-language-not-met, cross-mechanism-detection-not-met).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.

### Record [record-02344db45583f6a4.json](../../../../benchmarks/audio-qc-calibration/long-form.seam-jump@1/record-02344db45583f6a4.json): refused (far-pooled-not-met, far-per-language-not-met, cross-mechanism-detection-not-met)

Operating point warn; rule split-conformal, alpha 0.05, thresholds per pooled; plan `02344db45583f6a4`. Rates count source families with one-sided Clopper-Pearson bounds.

| Stratum | Threshold | FAR on confirmation N3 | Limit | Meets |
|---|---|---|---|---|
| chinese | 478 | 0/8 (0.000), upper 0.484 | 0.2 | no |
| english | 478 | 0/6 (0.000), upper 0.586 | 0.2 | no |
| french | 478 | 0/7 (0.000), upper 0.531 | 0.2 | no |
| german | 478 | 2/8 (0.250), upper 0.742 | 0.2 | no |
| italian | 478 | 0/8 (0.000), upper 0.484 | 0.2 | no |
| japanese | 478 | 1/8 (0.125), upper 0.632 | 0.2 | no |
| korean | 478 | 0/8 (0.000), upper 0.484 | 0.2 | no |
| portuguese | 478 | 1/8 (0.125), upper 0.632 | 0.2 | no |
| russian | 478 | 0/7 (0.000), upper 0.531 | 0.2 | no |
| spanish | 478 | 0/7 (0.000), upper 0.531 | 0.2 | no |
| pooled | 478 | 4/75 (0.053), upper 0.118 | 0.1 | no |

Per-language bounds at confidence 0.995 (Bonferroni over the languages), pooled at 0.95. Clean abstention: 0/75 (0.000), upper 0.039 (limit 0.1, meets yes).

| Mechanism | Cell | Detected | Limit | Meets |
|---|---|---|---|---|
| T1-pcm-construction | SEAM-DISC/severe | 37/75 (0.493), lower 0.393 | 0.7 | no |

Mechanisms meeting: - (minimum 1).

| Sham cell | Alarms | Overlaps N2 FAR | Informative |
|---|---|---|---|
| SEAM-DISC | 4/75 (0.053), upper 0.118 | yes | no |

Counts: calibration 75 clips, 75 families, 0 abstained; confirmation N3 75 clips, 75 families, 0 abstained; P1 75 clips, 75 families, 0 abstained; S 75 clips, 75 families, 0 abstained. Speakers: 4 (identified, unit `vocello-voice`).

Judge output identities: `fastqc@8` `072d385c65e95361`. Record limitations: `n3-no-labels`, `n3-long-form-cell`; risks: `seam-constructions`, `long-form-block`.
<!-- END GENERATED audio-qc-docs:qualification -->
