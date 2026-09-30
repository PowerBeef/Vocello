# `signal.noise@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `signal.noise@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `bfcf42f2e810f2a2` (a plan binds it, so any change is a new version, A7).

**Measures.** The WADA signal-to-noise ratio in dB (Stage 0 observation wadaSNRDB); a low ratio alarms.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| A (signal) | 0 | below | single | db | per language |

**Strata.** FLEURS records each locale separately, under its own conditions, so each language is its own clean distribution (clean N2 aligner tail gap, 95th percentile: 2.0 s in ru to 4.3 s in zh).

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`fastqc@8`](../judges/fastqc-v8.md) observations `wadaSNRDB` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `SIG-NOISE` | severe | T1-pcm-construction | yes |

**Populations** (role set `fleurs-n2`): fit N2 (calibration, fleurs-dev); confirmNegatives N2 (confirmation, fleurs-test); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. Speaker disjointness between the dev (calibration) and test (confirmation) splits cannot be verified, and neither can a speaker count: family and script disjointness hold, speaker disjointness is assumed, not shown.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Qualified (warn); confirmed (qualified).

**Plan.** [config/audio-qc-preregistrations/signal.noise@1.json](../../../../config/audio-qc-preregistrations/signal.noise@1.json): digest `c2a7396b45bc4e16`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N2; injector catalog 2, classes A,B,C,D,F, 150 per cell.
Calibration cohort audio-qc-n2-cohort (fleurs-dev, manifest `59221512a00b2b4a`); confirmation cohort audio-qc-n2-cohort (fleurs-test, manifest `ae62a87f35ed9b7c`).

**Confirmation.** Ledger entry qualified.

### Record [record-c2a7396b45bc4e16.json](../../../../benchmarks/audio-qc-calibration/signal.noise@1/record-c2a7396b45bc4e16.json): qualified at warn

Operating point warn; rule split-conformal, alpha 0.05, thresholds per language; plan `c2a7396b45bc4e16`. Rates count source families with one-sided Clopper-Pearson bounds.

| Stratum | Threshold | FAR on confirmation N2 | Limit | Meets |
|---|---|---|---|---|
| chinese | 10.1178 | 20/602 (0.033), upper 0.057 | 0.2 | yes |
| english | 7.1817 | 4/236 (0.017), upper 0.052 | 0.2 | yes |
| french | 23.5104 | 16/286 (0.056), upper 0.101 | 0.2 | yes |
| german | 14.6155 | 20/560 (0.036), upper 0.061 | 0.2 | yes |
| italian | 33.2761 | 27/351 (0.077), upper 0.121 | 0.2 | yes |
| japanese | 5.538 | 14/357 (0.039), upper 0.074 | 0.2 | yes |
| korean | 14.1485 | 12/245 (0.049), upper 0.096 | 0.2 | yes |
| portuguese | 16.3119 | 21/359 (0.058), upper 0.098 | 0.2 | yes |
| russian | 19.9041 | 21/326 (0.064), upper 0.108 | 0.2 | yes |
| spanish | 19.6677 | 12/396 (0.030), upper 0.060 | 0.2 | yes |
| pooled | - | 167/3718 (0.045), upper 0.051 | 0.1 | yes |

Per-language bounds at confidence 0.995 (Bonferroni over the languages), pooled at 0.95. Clean abstention: 0/3718 (0.000), upper 0.001 (limit 0.1, meets yes).

| Mechanism | Cell | Detected | Limit | Meets |
|---|---|---|---|---|
| T1-pcm-construction | SIG-NOISE/severe | 150/150 (1.000), lower 0.980 | 0.7 | yes |

Mechanisms meeting: T1-pcm-construction (minimum 1).

| Sham cell | Alarms | Overlaps N2 FAR | Informative |
|---|---|---|---|
| SIG-NOISE | 8/150 (0.053), upper 0.094 | yes | no |

Counts: calibration 1888 clips, 1888 families, 0 abstained; confirmation N2 3718 clips, 3718 families, 0 abstained; P1 150 clips, 150 families, 0 abstained; S 150 clips, 150 families, 0 abstained. Speakers: 10 (lower-bound, unit `language:fleurs-unidentified`).

N3 (report-only): flag rate 57/791 (0.072), upper 0.089; FAR bound pi 0.05: 0.075853, pi 0.1: 0.080067, pi 0.2: 0.090076.

Judge output identities: `fastqc@8` `072d385c65e95361`. Record limitations: `fleurs-no-speaker-ids`, `fleurs-speaker-lower-bound`, `n2-one-codec`; risks: -.
<!-- END GENERATED audio-qc-docs:qualification -->

## See also

- [Detector qualification at warn](../../audio-qc-engineering.md#detector-qualification-at-warn-aq-07-2026-09-29): the plan, derive and confirm procedure and the reasons behind this definition.
- [Codec resynthesis (N2)](../../audio-qc-engineering.md#codec-resynthesis-n2-audit-p9): the cohorts it is fitted and confirmed on.
- [Stage 0 observational measures](../../audio-qc-engineering.md#stage-0-observational-measures-and-engine-introspection-aq-04-2026-09-26).
