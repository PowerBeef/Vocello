# `signal.clipping@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `signal.clipping@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `e030d3287ff9a87b` (a plan binds it, so any change is a new version, A7).

**Measures.** Samples above the 0.965 ceiling (Fast QC v8 hotSamples), the only v8 trace of clipping in a written PCM16 take.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| A (signal) | 0 | above | single | samples | per language |

**Strata.** FLEURS records each locale separately, under its own conditions, so each language is its own clean distribution (clean N2 aligner tail gap, 95th percentile: 2.0 s in ru to 4.3 s in zh).

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`fastqc@8`](../judges/fastqc-v8.md) fastqc `hotSamples` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `SIG-CLIP` | severe | T1-pcm-construction | yes |

**Populations** (role set `fleurs-n2`): fit N2 (calibration, fleurs-dev); confirmNegatives N2 (confirmation, fleurs-test); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. Speaker disjointness between the dev (calibration) and test (confirmation) splits cannot be verified, and neither can a speaker count: family and script disjointness hold, speaker disjointness is assumed, not shown.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).

**Risks.**

- `v8-sub-full-scale-clipping`: Fast QC v8 counts only samples above its 0.965 ceiling; hard or soft-knee clipping below that level (the SIG-CLIP sweep flattens at the source's own level) leaves no trace in any v8 field (AQ-07 M2), so detection is expected only for over-range clipping. A plateau-run measure is the successor.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Refused; confirmed (refused).

**Plan.** [config/audio-qc-preregistrations/signal.clipping@1.json](../../../../config/audio-qc-preregistrations/signal.clipping@1.json): digest `328f5dbd95a49c0c`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N2; injector catalog 2, classes A,B,C,D,F, 150 per cell.
Calibration cohort audio-qc-n2-cohort (fleurs-dev, manifest `59221512a00b2b4a`); confirmation cohort audio-qc-n2-cohort (fleurs-test, manifest `ae62a87f35ed9b7c`).

**Confirmation.** Ledger entry refused (cross-mechanism-detection-not-met).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.

### Record [record-328f5dbd95a49c0c.json](../../../../benchmarks/audio-qc-calibration/signal.clipping@1/record-328f5dbd95a49c0c.json): refused (cross-mechanism-detection-not-met)

Operating point warn; rule split-conformal, alpha 0.05, thresholds per language; plan `328f5dbd95a49c0c`. Rates count source families with one-sided Clopper-Pearson bounds.

| Stratum | Threshold | FAR on confirmation N2 | Limit | Meets |
|---|---|---|---|---|
| chinese | 0 | 0/602 (0.000), upper 0.009 | 0.2 | yes |
| english | 0 | 0/236 (0.000), upper 0.022 | 0.2 | yes |
| french | 0 | 0/286 (0.000), upper 0.018 | 0.2 | yes |
| german | 0 | 0/560 (0.000), upper 0.009 | 0.2 | yes |
| italian | 0 | 0/351 (0.000), upper 0.015 | 0.2 | yes |
| japanese | 40 | 19/357 (0.053), upper 0.092 | 0.2 | yes |
| korean | 0 | 3/245 (0.012), upper 0.044 | 0.2 | yes |
| portuguese | 0 | 1/359 (0.003), upper 0.021 | 0.2 | yes |
| russian | 0 | 0/326 (0.000), upper 0.016 | 0.2 | yes |
| spanish | 0 | 15/396 (0.038), upper 0.070 | 0.2 | yes |
| pooled | - | 38/3718 (0.010), upper 0.013 | 0.1 | yes |

Per-language bounds at confidence 0.995 (Bonferroni over the languages), pooled at 0.95. Clean abstention: 0/3718 (0.000), upper 0.001 (limit 0.1, meets yes).

| Mechanism | Cell | Detected | Limit | Meets |
|---|---|---|---|---|
| T1-pcm-construction | SIG-CLIP/severe | 0/150 (0.000), lower 0.000 | 0.7 | no |

Mechanisms meeting: - (minimum 1).

| Sham cell | Alarms | Overlaps N2 FAR | Informative |
|---|---|---|---|
| SIG-CLIP | 2/150 (0.013), upper 0.041 | yes | no |

Counts: calibration 1888 clips, 1888 families, 0 abstained; confirmation N2 3718 clips, 3718 families, 0 abstained; P1 150 clips, 150 families, 0 abstained; S 150 clips, 150 families, 0 abstained. Speakers: 10 (lower-bound, unit `language:fleurs-unidentified`).

N3 (report-only): flag rate 5/791 (0.006), upper 0.013; FAR bound pi 0.05: 0.006654, pi 0.1: 0.007023, pi 0.2: 0.007901.

Judge output identities: `fastqc@8` `072d385c65e95361`. Record limitations: `fleurs-no-speaker-ids`, `fleurs-speaker-lower-bound`, `n2-one-codec`; risks: `v8-sub-full-scale-clipping`.
<!-- END GENERATED audio-qc-docs:qualification -->

## See also

- [Detector qualification at warn](../../audio-qc-engineering.md#detector-qualification-at-warn-aq-07-2026-09-29): the plan, derive and confirm procedure and the reasons behind this definition.
- [Codec resynthesis (N2)](../../audio-qc-engineering.md#codec-resynthesis-n2-audit-p9): the cohorts it is fitted and confirmed on.
