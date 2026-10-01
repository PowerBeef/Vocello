# `signal.dc-offset@2`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `signal.dc-offset@2` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `9ecee00a202dda9a` (a plan binds it, so any change is a new version, A7).

**Measures.** The magnitude of the DC offset (the absolute value of Fast QC v8 dcOffset) against one threshold pooled over the languages. A DC offset belongs to the signal chain, not the language: v1's per-language thresholds encoded each FLEURS locale's recording chain (4.2e-5 in fr against 2.7e-3 in de), so generated takes, whose offset does not vary by language (about 1.6e-4), flagged by language.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| A (signal) | 0 | above | single | full-scale | pooled |

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`fastqc@8`](../judges/fastqc-v8.md) absolute fastqc `dcOffset` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `SIG-DC` | moderate, severe | T1-pcm-construction | yes |

**Populations** (role set `fleurs-reserve-n2`): fit N2 (calibration, fleurs-reserve-1); confirmNegatives N2 (confirmation, fleurs-reserve-2; at a fail point fleurs-reserve-3); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-reserve-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. The reserve cohorts are drawn from the one train split (config/audio-qc-corpora.json fleurs-train), disjoint by FLoRes sentence from each other and from dev and test, so family and script disjointness hold; but they are grouped by sentence, not by speaker, so a train speaker who read sentences of two cohorts speaks in both: the calibration (reserve-1) and confirmation (reserve-2) cohorts likely share speakers, and neither that nor a speaker count can be measured.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).

**Risks.**

- `pooled-fleurs-locale-concentration`: One threshold pooled over the languages puts FLEURS's false alarms in the locales whose recording chain sits furthest out, while the confirmation still bounds every language's FAR (0.20 at warn, upper bound at the Bonferroni confidence). On the spent AQ-07 cohorts (design data, fitted on FLEURS dev N2 and counted on test N2), a pooled plan at alpha 0.05 put the worst language's bound at 0.354 (German DC), 0.283 (Spanish digital dropout) and 0.265 (English digital tail), and at alpha 0.01 at 0.066, 0.075 and 0.071: plan these detectors at alpha 0.01.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Qualified (warn); confirmed (qualified).

**Plan.** [config/audio-qc-preregistrations/signal.dc-offset@2.json](../../../../config/audio-qc-preregistrations/signal.dc-offset@2.json): digest `ebfcea42ad9e6045`, rule split-conformal, alpha 0.01, confidence 0.95, operating point warn, population N2; injector catalog 3, classes A,B,C,F, 150 per cell.
Calibration cohort audio-qc-n2-cohort (fleurs-reserve-1, manifest `de5491c5ecb55042`); confirmation cohort audio-qc-n2-cohort (fleurs-reserve-2, manifest `64b667943e2e4bbf`).

**Confirmation.** Ledger entry qualified.

### Record [record-ebfcea42ad9e6045.json](../../../../benchmarks/audio-qc-calibration/signal.dc-offset@2/record-ebfcea42ad9e6045.json): qualified at warn

Operating point warn; rule split-conformal, alpha 0.01, thresholds per pooled; plan `ebfcea42ad9e6045`. Rates count source families with one-sided Clopper-Pearson bounds.

| Stratum | Threshold | FAR on confirmation N2 | Limit | Meets |
|---|---|---|---|---|
| chinese | 0.00218448 | 0/257 (0.000), upper 0.020 | 0.2 | yes |
| english | 0.00218448 | 17/213 (0.080), upper 0.140 | 0.2 | yes |
| french | 0.00218448 | 0/237 (0.000), upper 0.022 | 0.2 | yes |
| german | 0.00218448 | 0/245 (0.000), upper 0.021 | 0.2 | yes |
| italian | 0.00218448 | 0/218 (0.000), upper 0.024 | 0.2 | yes |
| japanese | 0.00218448 | 0/238 (0.000), upper 0.022 | 0.2 | yes |
| korean | 0.00218448 | 12/254 (0.047), upper 0.093 | 0.2 | yes |
| portuguese | 0.00218448 | 0/231 (0.000), upper 0.023 | 0.2 | yes |
| russian | 0.00218448 | 0/227 (0.000), upper 0.023 | 0.2 | yes |
| spanish | 0.00218448 | 1/228 (0.004), upper 0.032 | 0.2 | yes |
| pooled | 0.00218448 | 30/2348 (0.013), upper 0.017 | 0.1 | yes |

Per-language bounds at confidence 0.995 (Bonferroni over the languages), pooled at 0.95. Clean abstention: 0/2348 (0.000), upper 0.001 (limit 0.1, meets yes).

| Mechanism | Cell | Detected | Limit | Meets |
|---|---|---|---|---|
| T1-pcm-construction | SIG-DC/severe | 150/150 (1.000), lower 0.980 | 0.7 | yes |

Mechanisms meeting: T1-pcm-construction (minimum 1).

| Sham cell | Alarms | Overlaps N2 FAR | Informative |
|---|---|---|---|
| SIG-DC | 2/150 (0.013), upper 0.041 | yes | no |

Counts: calibration 2262 clips, 2262 families, 0 abstained; confirmation N2 2348 clips, 2348 families, 0 abstained; P1 300 clips, 150 families, 0 abstained; S 150 clips, 150 families, 0 abstained. Speakers: 10 (lower-bound, unit `language:fleurs-unidentified`).

Judge output identities: `fastqc@8` `072d385c65e95361`. Record limitations: `fleurs-reserve-no-speaker-ids`, `fleurs-speaker-lower-bound`, `n2-one-codec`; risks: `pooled-fleurs-locale-concentration`.
<!-- END GENERATED audio-qc-docs:qualification -->
