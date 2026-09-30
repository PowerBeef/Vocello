# `long-form.seam-discontinuity@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `long-form.seam-discontinuity@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `ff625a01d3715265` (a plan binds it, so any change is a new version, A7).

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
- `n3-long-form-cell`: Class J's negatives are the take plan's long-form cell (version 2): 80 projects per split, 8 per language, pool scripts joined to 330-480 planner units (about 30 to 110 s) so the apps' long-form planner splits each at least once, spoken by the split's standard voices through vocello batch --long-form. Each take carries the assembly as its longForm block (seams and the assembler's boundary jump). One pooled threshold over each split's 80 families (the warn floor is 60), the two splits disjoint by family, speaker and script (role set n3-long-form); a script may recur in a few projects of its split.

**Risks.**

- `seam-constructions`: Catalog version 3's seam families act at a long-form take's seams (its longForm seamFrames, which the calibration set reads as the take's seams). SEAM-DISC removes 1, 5 or 20 ms right after a seeded seam, with nothing removed as its sham. SEAM-VOICE replaces the speech after a seam with another voice. On the n3-long-form cohort a take's generation voice is its speaker label (lead decision 2026-09-30: a Built-in speaker, a Voice Design brief, a clone reference speaker), so its take-voice-* variants splice another long-form take of the same split and language, of another voice whose recorded gender does not differ, from the start of one of its segments: the whole segment after the seam (severe) or its first 1 or 2 s, level-matched and crossfaded over 5 ms inside the replaced span; the sham splices another take of the same voice the same way. The label is the replaced span, and each entry's seams and longForm block describe its output. The positives are constructed: a splice joins two renderings, so part of a cosine drop may come from the join, which the same-voice sham measures. Take plan version 2 records no brief gender, so a Built-in speaker may take a brief's voice of either sound, and a brief need not sound the same in two takes, so its sham may change voice too. COD-SEAM (T2, a 1-3 frame seam misalignment), the second mechanism a fail level needs, has no producer.
- `seam-offsets-from-block`: The Stage 0 seam z-score reads the take's seams: audio_qc_calibration_set.py score passes a long-form take's longForm seamFrames to it, and an entry's own seamSamples where a construction moved them. A single-segment take has none, so its seamDiscontinuityMaxZ stays null (no-value): class J's cohorts hold long-form takes only.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
