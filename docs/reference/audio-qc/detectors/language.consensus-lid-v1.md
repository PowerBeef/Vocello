# `language.consensus-lid@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `language.consensus-lid@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `e3d4b088a357e90d` (a plan binds it, so any change is a new version, A7).

**Measures.** The larger of Whisper large-v3's expected-language probability and VoxLingua's expected-language posterior, so both must be low to alarm.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| D (language) | 2 | below | consensus-max | probability | per language |

**Strata.** Expected-language confidence differs by language (clean N2 share below the pooled 5th percentile, 0.983: 20% in de, 15% in en, at most 4% elsewhere).

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) panel `expectedLanguageProbability`; [`lid.voxlingua107-ecapa@1`](../judges/lid.voxlingua107-ecapa-v1.md) panel `expectedPosterior` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `LNG-SWAP` | severe | T1-parallel-corpus | yes |

**Populations** (role set `fleurs-n2`): fit N2 (calibration, fleurs-dev); confirmNegatives N2 (confirmation, fleurs-test); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. Speaker disjointness between the dev (calibration) and test (confirmation) splits cannot be verified, and neither can a speaker count: family and script disjointness hold, speaker disjointness is assumed, not shown.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).

**Risks.**

- `voxlingua-weak-german-russian`: VoxLingua's expected-language posterior is below 0.5 on 21.4% (de) and 43.5% (ru) of N1 FLEURS dev recordings, 22.2% and 44.1% on N2 (panels of 2026-09-29). Under max() a low VoxLingua posterior never alarms alone, so in German and Russian the consensus reduces to Whisper's vote.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Qualified (warn); confirmed (qualified).

**Plan.** [config/audio-qc-preregistrations/language.consensus-lid@1.json](../../../../config/audio-qc-preregistrations/language.consensus-lid@1.json): digest `67b4358cc9d3e121`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N2; injector catalog 2, classes A,B,C,D,F, 150 per cell.
Calibration cohort audio-qc-n2-cohort (fleurs-dev, manifest `59221512a00b2b4a`); confirmation cohort audio-qc-n2-cohort (fleurs-test, manifest `ae62a87f35ed9b7c`).

**Confirmation.** Ledger entry qualified.

### Record [record-67b4358cc9d3e121.json](../../../../benchmarks/audio-qc-calibration/language.consensus-lid@1/record-67b4358cc9d3e121.json): qualified at warn

Operating point warn; rule split-conformal, alpha 0.05, thresholds per language; plan `67b4358cc9d3e121`. Rates count source families with one-sided Clopper-Pearson bounds.

| Stratum | Threshold | FAR on confirmation N2 | Limit | Meets |
|---|---|---|---|---|
| chinese | 0.998029 | 23/602 (0.038), upper 0.063 | 0.2 | yes |
| english | 0.967729 | 19/236 (0.081), upper 0.137 | 0.2 | yes |
| french | 0.993339 | 12/286 (0.042), upper 0.083 | 0.2 | yes |
| german | 0.947496 | 45/560 (0.080), upper 0.115 | 0.2 | yes |
| italian | 0.984945 | 18/351 (0.051), upper 0.090 | 0.2 | yes |
| japanese | 0.995184 | 10/357 (0.028), upper 0.059 | 0.2 | yes |
| korean | 0.999776 | 6/245 (0.024), upper 0.063 | 0.2 | yes |
| portuguese | 0.993608 | 32/359 (0.089), upper 0.135 | 0.2 | yes |
| russian | 0.985932 | 21/326 (0.064), upper 0.108 | 0.2 | yes |
| spanish | 0.991186 | 14/396 (0.035), upper 0.067 | 0.2 | yes |
| pooled | - | 200/3718 (0.054), upper 0.060 | 0.1 | yes |

Per-language bounds at confidence 0.995 (Bonferroni over the languages), pooled at 0.95. Clean abstention: 0/3718 (0.000), upper 0.001 (limit 0.1, meets yes).

| Mechanism | Cell | Detected | Limit | Meets |
|---|---|---|---|---|
| T1-parallel-corpus | LNG-SWAP/severe | 150/150 (1.000), lower 0.980 | 0.7 | yes |

Mechanisms meeting: T1-parallel-corpus (minimum 1).

| Sham cell | Alarms | Overlaps N2 FAR | Informative |
|---|---|---|---|
| LNG-SWAP | 5/150 (0.033), upper 0.069 | yes | no |

Counts: calibration 1888 clips, 1888 families, 0 abstained; confirmation N2 3718 clips, 3718 families, 0 abstained; P1 150 clips, 150 families, 0 abstained; S 150 clips, 150 families, 0 abstained. Speakers: 10 (lower-bound, unit `language:fleurs-unidentified`).

| Consensus languages | Judges | Units | Phi | Joint failure |
|---|---|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | asr.whisper-large-v3@1, lid.voxlingua107-ecapa@1 | 3868 | -0.057598 | 200/3718 (0.054), upper 0.060 |

N3 (report-only): flag rate 119/791 (0.150), upper 0.173; FAR bound pi 0.05: 0.158361, pi 0.1: 0.167158, pi 0.2: 0.188053.

Judge output identities: `asr.whisper-large-v3@1` `0bdd27ea106e2512`, `lid.voxlingua107-ecapa@1` `49294258d799b54d`. Record limitations: `fleurs-no-speaker-ids`, `fleurs-speaker-lower-bound`, `n2-one-codec`; risks: `voxlingua-weak-german-russian`.
<!-- END GENERATED audio-qc-docs:qualification -->

## See also

- [Detector qualification at warn](../../audio-qc-engineering.md#detector-qualification-at-warn-aq-07-2026-09-29): the plan, derive and confirm procedure and the reasons behind this definition.
- [Codec resynthesis (N2)](../../audio-qc-engineering.md#codec-resynthesis-n2-audit-p9): the cohorts it is fitted and confirmed on.
