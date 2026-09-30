# `signal.dc-offset@2`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `signal.dc-offset@2` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `2daaa914f6513b84` (a plan binds it, so any change is a new version, A7).

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

**Populations** (role set `fleurs-n2`): fit N2 (calibration, fleurs-dev); confirmNegatives N2 (confirmation, fleurs-test); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. Speaker disjointness between the dev (calibration) and test (confirmation) splits cannot be verified, and neither can a speaker count: family and script disjointness hold, speaker disjointness is assumed, not shown.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).

**Risks.**

- `pooled-fleurs-locale-concentration`: One threshold pooled over the languages puts FLEURS's false alarms in the locales whose recording chain sits furthest out, while the confirmation still bounds every language's FAR (0.20 at warn, upper bound at the Bonferroni confidence). On the spent AQ-07 cohorts (design data, fitted on FLEURS dev N2 and counted on test N2), a pooled plan at alpha 0.05 put the worst language's bound at 0.354 (German DC), 0.283 (Spanish digital dropout) and 0.265 (English digital tail), and at alpha 0.01 at 0.066, 0.075 and 0.071: plan these detectors at alpha 0.01.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
