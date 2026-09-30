# `signal.clipping@2`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `signal.clipping@2` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `3e9ac09ae51187a8` (a plan binds it, so any change is a new version, A7).

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
- `clip-variants-not-sampled`: The N2 injection schedule (audio_qc_calibration_set.py build_plan) draws each injector's sham, mild, moderate and severe catalog variants only, so SIG-CLIP's soft-knee and over-range variants never reach a confirmation set and the moderate cell holds hard clipping alone. Their design-data detection comes from building them in memory on the spent confirmation sources; qualifying them needs the schedule to draw the extra variants.

**Risks.**

- `n2-full-scale-clamps`: The N2 round trip clamps some loud FLEURS recordings at full scale (the N2 manifest's clampedSampleCount), leaving genuine two-sided flat tops on clean negatives: on the spent AQ-07 cohorts 16 of 3,718 test N2 families carry any (15 of them Japanese, upper bound 0.077 at 0.995), so the pooled threshold sits at 0 whatever the alpha and the Japanese stratum holds the FAR.
- `soft-knee-saturation`: A soft knee leaves a flat top only where it saturates: SIG-CLIP's knee squashes toward an asymptote 12% above its level, so samples far above the knee (speech's crest factor puts the loudest 1% well above the level that 1% exceeds) round to the asymptote on both polarities, while a waveform that barely crosses the knee is compressed without one. On the spent confirmation sources 149 of 150 soft-knee constructions scored; on the smooth procedural fixtures none does.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
