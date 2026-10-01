# `signal.clipping@2`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `signal.clipping@2` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `c53dd8505b4b845c` (a plan binds it, so any change is a new version, A7).

**Measures.** Sign-symmetric flat tops: the smaller of the take's positive and negative flat-top sample counts over its samples (pcmMeasures symmetricFlatTopFraction), a flat top being a run of at least two equal PCM16 samples within 1% of the take's own peak magnitude, against one threshold pooled over the languages. A clipping stage at any level, below full scale (hard or soft-knee) or at it (an over-range signal written to PCM16), holds both polarities at the level it limits to, while speech reaches its peak on isolated samples; v1 counted only samples above Fast QC's 0.965 ceiling and detected none of the SIG-CLIP injections, which flatten at the source's own level.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| A (signal) | 0 | above | single | fraction | pooled |

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`fastqc@8`](../judges/fastqc-v8.md) pcm `symmetricFlatTopFraction` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `SIG-CLIP` | moderate, severe | T1-pcm-construction | yes |

**Populations** (role set `fleurs-reserve-n2`): fit N2 (calibration, fleurs-reserve-1); confirmNegatives N2 (confirmation, fleurs-reserve-2; at a fail point fleurs-reserve-3); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-reserve-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. The reserve cohorts are drawn from the one train split (config/audio-qc-corpora.json fleurs-train), disjoint by FLoRes sentence from each other and from dev and test, so family and script disjointness hold; but they are grouped by sentence, not by speaker, so a train speaker who read sentences of two cohorts speaks in both: the calibration (reserve-1) and confirmation (reserve-2) cohorts likely share speakers, and neither that nor a speaker count can be measured.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).
- `pcm-measures-python-only`: The pcmMeasures block is measured by the calibration scorer (scripts/lib/qc_qualification/pcm_measures.py, audio_qc_calibration_set.py score) over the persisted PCM16, not inside the engine: until a Swift mirror joins the Stage 0 observations the app's own takes carry no such field, so the detector serves the evidence lanes that run the scorer. An N1 recording is measured after its resampling, which smooths flat tops and zero runs.
- `clip-variants-moderate`: SIG-CLIP's soft-knee and over-range variants exist at moderate only (1% of samples). Schedule 2 of the calibration set (audio_qc_calibration_set.py SCHEDULE_EXTRAS; the plan binds injectionSchedule) draws both beside the hard sweep on the same sampled families, so the confirmation set's moderate cell holds all three constructions and each scored unit names its variant. A warn confirmation gates on severe cells only, where clipping is hard, so the soft-knee and over-range detection is measured per unit but judged only at a fail point.

**Risks.**

- `n2-full-scale-clamps`: The N2 round trip clamps some loud FLEURS recordings at full scale (the N2 manifest's clampedSampleCount), leaving genuine two-sided flat tops on clean negatives: on the spent AQ-07 cohorts 16 of 3,718 test N2 families carry any (15 of them Japanese, upper bound 0.077 at 0.995), so the pooled threshold sits at 0 whatever the alpha and the Japanese stratum holds the FAR.
- `soft-knee-saturation`: A soft knee leaves a flat top only where it saturates: SIG-CLIP's knee squashes toward an asymptote 12% above its level, so samples far above the knee (speech's crest factor puts the loudest 1% well above the level that 1% exceeds) round to the asymptote on both polarities, while a waveform that barely crosses the knee is compressed without one. On the spent confirmation sources 149 of 150 soft-knee constructions scored; on the smooth procedural fixtures none does.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Qualified (warn); confirmed (qualified).

**Plan.** [config/audio-qc-preregistrations/signal.clipping@2.json](../../../../config/audio-qc-preregistrations/signal.clipping@2.json): digest `879cebbc7bfd4f87`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N2; injector catalog 3, classes A,B,C,F, 150 per cell.
Calibration cohort audio-qc-n2-cohort (fleurs-reserve-1, manifest `de5491c5ecb55042`); confirmation cohort audio-qc-n2-cohort (fleurs-reserve-2, manifest `64b667943e2e4bbf`).

**Confirmation.** Ledger entry qualified.

### Record [record-879cebbc7bfd4f87.json](../../../../benchmarks/audio-qc-calibration/signal.clipping@2/record-879cebbc7bfd4f87.json): qualified at warn

Operating point warn; rule split-conformal, alpha 0.05, thresholds per pooled; plan `879cebbc7bfd4f87`. Rates count source families with one-sided Clopper-Pearson bounds.

| Stratum | Threshold | FAR on confirmation N2 | Limit | Meets |
|---|---|---|---|---|
| chinese | 0 | 0/257 (0.000), upper 0.020 | 0.2 | yes |
| english | 0 | 0/213 (0.000), upper 0.025 | 0.2 | yes |
| french | 0 | 0/237 (0.000), upper 0.022 | 0.2 | yes |
| german | 0 | 0/245 (0.000), upper 0.021 | 0.2 | yes |
| italian | 0 | 0/218 (0.000), upper 0.024 | 0.2 | yes |
| japanese | 0 | 0/238 (0.000), upper 0.022 | 0.2 | yes |
| korean | 0 | 0/254 (0.000), upper 0.021 | 0.2 | yes |
| portuguese | 0 | 0/231 (0.000), upper 0.023 | 0.2 | yes |
| russian | 0 | 1/227 (0.004), upper 0.032 | 0.2 | yes |
| spanish | 0 | 0/228 (0.000), upper 0.023 | 0.2 | yes |
| pooled | 0 | 1/2348 (0.000), upper 0.002 | 0.1 | yes |

Per-language bounds at confidence 0.995 (Bonferroni over the languages), pooled at 0.95. Clean abstention: 0/2348 (0.000), upper 0.001 (limit 0.1, meets yes).

| Mechanism | Cell | Detected | Limit | Meets |
|---|---|---|---|---|
| T1-pcm-construction | SIG-CLIP/severe | 148/148 (1.000), lower 0.980 | 0.7 | yes |

Mechanisms meeting: T1-pcm-construction (minimum 1).

| Sham cell | Alarms | Overlaps N2 FAR | Informative |
|---|---|---|---|
| SIG-CLIP | 0/150 (0.000), upper 0.020 | yes | no |

Counts: calibration 2262 clips, 2262 families, 0 abstained; confirmation N2 2348 clips, 2348 families, 0 abstained; P1 592 clips, 148 families, 0 abstained; S 150 clips, 150 families, 0 abstained. Speakers: 10 (lower-bound, unit `language:fleurs-unidentified`).

Judge output identities: `fastqc@8` `072d385c65e95361`. Record limitations: `fleurs-reserve-no-speaker-ids`, `fleurs-speaker-lower-bound`, `n2-one-codec`, `pcm-measures-python-only`, `clip-variants-moderate`; risks: `n2-full-scale-clamps`, `soft-knee-saturation`.
<!-- END GENERATED audio-qc-docs:qualification -->
