# `signal.dropout@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `signal.dropout@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `a94b51fa2bf3a7ce` (a plan binds it, so any change is a new version, A7).

**Measures.** The longest interior silent run, in milliseconds (Fast QC v8 longestSilenceMS).

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| A (signal) | 0 | above | single | milliseconds | per language |

**Strata.** FLEURS records each locale separately, under its own conditions, so each language is its own clean distribution (clean N2 aligner tail gap, 95th percentile: 2.0 s in ru to 4.3 s in zh).

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`fastqc@8`](../judges/fastqc-v8.md) fastqc `longestSilenceMS` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `SIG-DROP` | severe | T1-pcm-construction | yes |

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

**Plan.** [config/audio-qc-preregistrations/signal.dropout@1.json](../../../../config/audio-qc-preregistrations/signal.dropout@1.json): digest `d8cd9a971a7c37b1`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N2; injector catalog 2, classes A,B,C,D,F, 150 per cell.
Calibration cohort audio-qc-n2-cohort (fleurs-dev, manifest `59221512a00b2b4a`); confirmation cohort audio-qc-n2-cohort (fleurs-test, manifest `ae62a87f35ed9b7c`).

**Confirmation.** Ledger entry qualified.

### Record [record-d8cd9a971a7c37b1.json](../../../../benchmarks/audio-qc-calibration/signal.dropout@1/record-d8cd9a971a7c37b1.json): qualified at warn

Operating point warn; rule split-conformal, alpha 0.05, thresholds per language; plan `d8cd9a971a7c37b1`. Rates count source families with one-sided Clopper-Pearson bounds.

| Stratum | Threshold | FAR on confirmation N2 | Limit | Meets |
|---|---|---|---|---|
| chinese | 1159 | 30/602 (0.050), upper 0.077 | 0.2 | yes |
| english | 1270 | 7/236 (0.030), upper 0.071 | 0.2 | yes |
| french | 681 | 17/286 (0.059), upper 0.105 | 0.2 | yes |
| german | 269 | 46/560 (0.082), upper 0.117 | 0.2 | yes |
| italian | 924 | 18/351 (0.051), upper 0.090 | 0.2 | yes |
| japanese | 1018 | 17/357 (0.048), upper 0.085 | 0.2 | yes |
| korean | 2397 | 21/245 (0.086), upper 0.142 | 0.2 | yes |
| portuguese | 16 | 16/359 (0.045), upper 0.081 | 0.2 | yes |
| russian | 1419 | 26/326 (0.080), upper 0.126 | 0.2 | yes |
| spanish | 906 | 18/396 (0.045), upper 0.080 | 0.2 | yes |
| pooled | - | 216/3718 (0.058), upper 0.065 | 0.1 | yes |

Per-language bounds at confidence 0.995 (Bonferroni over the languages), pooled at 0.95. Clean abstention: 0/3718 (0.000), upper 0.001 (limit 0.1, meets yes).

| Mechanism | Cell | Detected | Limit | Meets |
|---|---|---|---|---|
| T1-pcm-construction | SIG-DROP/severe | 138/150 (0.920), lower 0.874 | 0.7 | yes |

Mechanisms meeting: T1-pcm-construction (minimum 1).

| Sham cell | Alarms | Overlaps N2 FAR | Informative |
|---|---|---|---|
| SIG-DROP | 8/150 (0.053), upper 0.094 | yes | no |

Counts: calibration 1888 clips, 1888 families, 0 abstained; confirmation N2 3718 clips, 3718 families, 0 abstained; P1 150 clips, 150 families, 0 abstained; S 150 clips, 150 families, 0 abstained. Speakers: 10 (lower-bound, unit `language:fleurs-unidentified`).

N3 (report-only): flag rate 92/791 (0.116), upper 0.137; FAR bound pi 0.05: 0.12243, pi 0.1: 0.129232, pi 0.2: 0.145386.

Judge output identities: `fastqc@8` `072d385c65e95361`. Record limitations: `fleurs-no-speaker-ids`, `fleurs-speaker-lower-bound`, `n2-one-codec`; risks: -.
<!-- END GENERATED audio-qc-docs:qualification -->

## See also

- [Detector qualification at warn](../../audio-qc-engineering.md#detector-qualification-at-warn-aq-07-2026-09-29): the plan, derive and confirm procedure and the reasons behind this definition.
- [Codec resynthesis (N2)](../../audio-qc-engineering.md#codec-resynthesis-n2-audit-p9): the cohorts it is fitted and confirmed on.
