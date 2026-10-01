# `long-form.seam-identity@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `long-form.seam-identity@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `5577550a0658c406` (a plan binds it, so any change is a new version, A7).

**Measures.** Seam identity delta: across each long-form seam, the cosine between CAM++'s last 2 s window ending at or before the seam and its first window starting at or after it, reduced from its window embeddings; the lowest over the seams. A voice that changes at a seam alarms. A take without seams, or without a window on both sides of one, abstains.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| J (long form) | 2 | below | single | cosine | pooled |

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`speaker.campplus-voxceleb@1`](../judges/speaker.campplus-voxceleb-v1.md) raw-output `seamWindowCosineMinimum` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `SEAM-VOICE` | severe | T1-pcm-construction | yes |

**Populations** (role set `n3-long-form`): fit N3 (calibration, vocello-long-form-calibration); confirmNegatives N3 (confirmation, vocello-long-form-confirmation); positives P1 (confirmation); shams S (confirmation).

**Limitations.**

- `n3-no-labels`: A measure that exists only on generated takes (the talker's introspection, long-form seams) has no N2 to confirm on: a codec round trip samples no token and joins no segment, so its fit and confirmation negatives are N3 alone (audit section 5.7), the two splits of config/audio-qc-calibration-takes.json disjoint by family, speaker and script. N3 carries no defect labels, so a flag rate f bounds the false-alarm rate only as f / (1 - pi_max), where pi_max is the largest defect prevalence admitted (section 5.1). Each language stratum needs at least 60 scored families in each split (the calibration split plans 80 per language).
- `n3-long-form-cell`: Class J's negatives are the take plan's long-form cell (version 2): 80 projects per split, 8 per language, pool scripts joined to 330-480 planner units (about 30 to 110 s) so the apps' long-form planner splits each at least once, spoken by the split's standard voices through vocello batch --long-form. Each take carries the assembly as its longForm block (seams and the assembler's boundary jump). One pooled threshold over each split's 80 families (the warn floor is 60), the two splits disjoint by family, speaker and script (role set n3-long-form); a script may recur in a few projects of its split.

**Risks.**

- `seam-constructions`: Catalog version 3's seam families act at a long-form take's seams (its longForm seamFrames, which the calibration set reads as the take's seams). SEAM-DISC removes 1, 5 or 20 ms right after a seeded seam, with nothing removed as its sham. SEAM-VOICE replaces the speech after a seam with another voice. On the n3-long-form cohort a take's generation voice is its speaker label (lead decision 2026-09-30: a Built-in speaker, a Voice Design brief, a clone reference speaker), so its take-voice-* variants splice another long-form take of the same split and language, of another voice whose recorded gender does not differ, from the start of one of its segments: the whole segment after the seam (severe) or its first 1 or 2 s, level-matched and crossfaded over 5 ms inside the replaced span; the sham splices another take of the same voice the same way. The label is the replaced span, and each entry's seams and longForm block describe its output. The positives are constructed: a splice joins two renderings, so part of a cosine drop may come from the join, which the same-voice sham measures. Take plan version 2 records no brief gender, so a Built-in speaker may take a brief's voice of either sound, and a brief need not sound the same in two takes, so its sham may change voice too. COD-SEAM (T2, a 1-3 frame seam misalignment), the second mechanism a fail level needs, has no producer.
- `speaker-raw-windows-export`: The panel bundle keeps CAM++'s reference-relative L2 metrics only; its window embeddings stay in the orchestrator's L1 cache. audio_qc_calibration_set.py raw-outputs --judge speaker.campplus-voxceleb@1 exports them per take (speaker embeddings: an untracked build artifact, never committed), and scores --raw-outputs passes them with each long-form take's seam times.
- `seam-window-similarity`: Two 2 s windows of one voice score lower against each other than whole takes do, and a window beside a seam may hold the inserted pause, so the clean long-form distribution, not a speaker-verification threshold, sets the bound; a seam without a whole window on both sides is not scored.
- `resnet293-not-voting`: The audit fails an identity only when both speaker families fall below their thresholds and abstains when they disagree (section 4.3), but ResNet293 votes only after its correlated-failure audit against CAM++ (the same VoxCeleb training data) passes. These detectors read CAM++ alone; the two-family rule (consensus-max of the two families' scores) is a new version once ResNet293 votes.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Refused; confirmed (refused).

**Plan.** [config/audio-qc-preregistrations/long-form.seam-identity@1.json](../../../../config/audio-qc-preregistrations/long-form.seam-identity@1.json): digest `61aa4a0dbda43863`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N3; injector catalog 4, classes J, 150 per cell.
Calibration cohort audio-qc-calibration-takes (vocello-long-form-calibration, manifest `4a141aaae38fc373`); confirmation cohort audio-qc-calibration-takes (vocello-long-form-confirmation, manifest `8366ac9b9b2368d5`).

**Confirmation.** Ledger entry refused (far-per-language-not-met, cross-mechanism-detection-not-met).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.

### Record [record-61aa4a0dbda43863.json](../../../../benchmarks/audio-qc-calibration/long-form.seam-identity@1/record-61aa4a0dbda43863.json): refused (far-per-language-not-met, cross-mechanism-detection-not-met)

Operating point warn; rule split-conformal, alpha 0.05, thresholds per pooled; plan `61aa4a0dbda43863`. Rates count source families with one-sided Clopper-Pearson bounds.

| Stratum | Threshold | FAR on confirmation N3 | Limit | Meets |
|---|---|---|---|---|
| chinese | 0.0732114 | 0/8 (0.000), upper 0.484 | 0.2 | no |
| english | 0.0732114 | 0/6 (0.000), upper 0.586 | 0.2 | no |
| french | 0.0732114 | 0/7 (0.000), upper 0.531 | 0.2 | no |
| german | 0.0732114 | 1/8 (0.125), upper 0.632 | 0.2 | no |
| italian | 0.0732114 | 0/8 (0.000), upper 0.484 | 0.2 | no |
| japanese | 0.0732114 | 0/8 (0.000), upper 0.484 | 0.2 | no |
| korean | 0.0732114 | 1/8 (0.125), upper 0.632 | 0.2 | no |
| portuguese | 0.0732114 | 0/8 (0.000), upper 0.484 | 0.2 | no |
| russian | 0.0732114 | 0/7 (0.000), upper 0.531 | 0.2 | no |
| spanish | 0.0732114 | 0/7 (0.000), upper 0.531 | 0.2 | no |
| pooled | 0.0732114 | 2/75 (0.027), upper 0.082 | 0.1 | yes |

Per-language bounds at confidence 0.995 (Bonferroni over the languages), pooled at 0.95. Clean abstention: 0/75 (0.000), upper 0.039 (limit 0.1, meets yes).

| Mechanism | Cell | Detected | Limit | Meets |
|---|---|---|---|---|
| T1-pcm-construction | SEAM-VOICE/severe | 18/74 (0.243), lower 0.164 | 0.7 | no |

Mechanisms meeting: - (minimum 1).

| Sham cell | Alarms | Overlaps N2 FAR | Informative |
|---|---|---|---|
| SEAM-VOICE | 4/74 (0.054), upper 0.119 | yes | yes |

Counts: calibration 75 clips, 75 families, 0 abstained; confirmation N3 75 clips, 75 families, 0 abstained; P1 74 clips, 74 families, 0 abstained; S 74 clips, 74 families, 0 abstained. Speakers: 4 (identified, unit `vocello-voice`).

Judge output identities: `speaker.campplus-voxceleb@1` `e9531c63646f0192`. Record limitations: `n3-no-labels`, `n3-long-form-cell`; risks: `seam-constructions`, `speaker-raw-windows-export`, `seam-window-similarity`, `resnet293-not-voting`.
<!-- END GENERATED audio-qc-docs:qualification -->
