# `boundary.run-on@2`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `boundary.run-on@2` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `f9314d3758021d8f` (a plan binds it, so any change is a new version, A7).

**Measures.** Seconds of speech-level audio after the script ends: the end of the take's last active span (pcmMeasures lastActiveSeconds: 10 ms frames within 35 dB of the take's loud level and at least 10 dB above its floor, in spans of 150 ms or more) minus the aligner's last aligned script unit end, only where both content voters of the language completed (the aligner times, never votes). A run-on keeps the take active past the script's end whether or not a recognizer transcribes it: v1 read Whisper large-v3's last segment end, which stays at the script's end on most BND-RUNON positives (median 0.04 s past the aligner's end at severe on the spent AQ-07 set), and detected 43 of 135.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| C (boundary) | 2 | above | difference | seconds | per language |

**Strata.** The aligner's script end and what FLEURS recordings hold after the last word (breaths, noise, a partial alignment) differ by language (spent AQ-07 dev N2, 95th percentile of the score: 0.09 s in es to 3.2 s in ja).

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| english, french, german, italian, portuguese, russian, spanish | [`fastqc@8`](../judges/fastqc-v8.md) pcm `lastActiveSeconds`; [`align.qwen3-forcedaligner-0.6b@1`](../judges/align.qwen3-forcedaligner-0.6b-v1.md) panel `spanEndSeconds` | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md), [`asr.parakeet-tdt-0.6b-v3@1`](../judges/asr.parakeet-tdt-0.6b-v3-v1.md) |
| chinese | [`fastqc@8`](../judges/fastqc-v8.md) pcm `lastActiveSeconds`; [`align.qwen3-forcedaligner-0.6b@1`](../judges/align.qwen3-forcedaligner-0.6b-v1.md) panel `spanEndSeconds` | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md), [`asr.paraformer-zh@1`](../judges/asr.paraformer-zh-v1.md) |
| japanese | [`fastqc@8`](../judges/fastqc-v8.md) pcm `lastActiveSeconds`; [`align.qwen3-forcedaligner-0.6b@1`](../judges/align.qwen3-forcedaligner-0.6b-v1.md) panel `spanEndSeconds` | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md), [`asr.sensevoice-small-f16@1`](../judges/asr.sensevoice-small-f16-v1.md) |

**Scope.** chinese, english, french, german, italian, japanese, portuguese, russian, spanish.
Excludes korean: The forced aligner is out of scope for Korean: mlx-audio tokenizes it with soynlp (GPL-3.0), which the exclusion list refuses, so there is no script-end time in Korean.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `BND-RUNON` | moderate, severe | T1-pcm-construction | yes |

**Populations** (role set `fleurs-reserve-n2`): fit N2 (calibration, fleurs-reserve-1); confirmNegatives N2 (confirmation, fleurs-reserve-2; at a fail point fleurs-reserve-3); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-reserve-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. The reserve cohorts are drawn from the one train split (config/audio-qc-corpora.json fleurs-train), disjoint by FLoRes sentence from each other and from dev and test, so family and script disjointness hold; but they are grouped by sentence, not by speaker, so a train speaker who read sentences of two cohorts speaks in both: the calibration (reserve-1) and confirmation (reserve-2) cohorts likely share speakers, and neither that nor a speaker count can be measured.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).
- `pcm-measures-python-only`: The pcmMeasures block is measured by the calibration scorer (scripts/lib/qc_qualification/pcm_measures.py, audio_qc_calibration_set.py score) over the persisted PCM16, not inside the engine: until a Swift mirror joins the Stage 0 observations the app's own takes carry no such field, so the detector serves the evidence lanes that run the scorer. An N1 recording is measured after its resampling, which smooths flat tops and zero runs.

**Risks.**

- `aligner-anchoring`: The run-on score assumes the aligner places the script's last unit on its first occurrence; a repeated tail the aligner anchors on its last copy is missed.
- `runon-quiet-span`: BND-RUNON's recording variant appends copies of a 0.5 s span of the take's middle, which can be a pause: such a positive adds nothing at speech level and the score cannot see it (7 of the 12 spent severe positives it missed at alpha 0.02). The other 5 were Japanese takes whose aligner placed the script's end past the last active span, with 42-61% of their units aligned.
- `noisy-tail-activity`: On a noisy recording the activity margin (10 dB over the 10th-percentile frame) is close to the noise's own spread, so noise after the last word can form an active span: BND-RUNON's sham, 300 ms of -80 dBFS room tone after the take, lowers such a take's floor and moved its active end 0.7-0.8 s later on 3 of 135 spent sham families. At alpha 0.05 the sham's 11 of 135 alarms depart narrowly from the clean N2 interval (A4), at alpha 0.02 its 1 of 135 does not: plan at alpha 0.02.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Qualified (warn); confirmed (qualified).

**Plan.** [config/audio-qc-preregistrations/boundary.run-on@2.json](../../../../config/audio-qc-preregistrations/boundary.run-on@2.json): digest `a131182003553bfa`, rule split-conformal, alpha 0.02, confidence 0.95, operating point warn, population N2; injector catalog 3, classes A,B,C,F, 150 per cell.
Calibration cohort audio-qc-n2-cohort (fleurs-reserve-1, manifest `de5491c5ecb55042`); confirmation cohort audio-qc-n2-cohort (fleurs-reserve-2, manifest `64b667943e2e4bbf`).

**Confirmation.** Ledger entry qualified.

### Record [record-a131182003553bfa.json](../../../../benchmarks/audio-qc-calibration/boundary.run-on@2/record-a131182003553bfa.json): qualified at warn

Operating point warn; rule split-conformal, alpha 0.02, thresholds per language; plan `a131182003553bfa`. Rates count source families with one-sided Clopper-Pearson bounds.

| Stratum | Threshold | FAR on confirmation N2 | Limit | Meets |
|---|---|---|---|---|
| chinese | 2.16 | 7/257 (0.027), upper 0.065 | 0.2 | yes |
| english | 2.31 | 4/213 (0.019), upper 0.057 | 0.2 | yes |
| french | 1.54 | 2/237 (0.008), upper 0.038 | 0.2 | yes |
| german | 1.7 | 3/245 (0.012), upper 0.044 | 0.2 | yes |
| italian | 0.44 | 6/218 (0.028), upper 0.070 | 0.2 | yes |
| japanese | 1.41 | 5/238 (0.021), upper 0.058 | 0.2 | yes |
| portuguese | 1.92 | 4/231 (0.017), upper 0.053 | 0.2 | yes |
| russian | 1.62 | 2/227 (0.009), upper 0.040 | 0.2 | yes |
| spanish | 2.1 | 2/195 (0.010), upper 0.046 | 0.2 | yes |
| pooled | - | 35/2061 (0.017), upper 0.022 | 0.1 | yes |

Per-language bounds at confidence 0.994444 (Bonferroni over the languages), pooled at 0.95. Clean abstention: 33/2094 (0.016), upper 0.021 (limit 0.1, meets yes).

| Mechanism | Cell | Detected | Limit | Meets |
|---|---|---|---|---|
| T1-pcm-construction | BND-RUNON/severe | 132/135 (0.978), lower 0.944 | 0.7 | yes |

Mechanisms meeting: T1-pcm-construction (minimum 1).

| Sham cell | Alarms | Overlaps N2 FAR | Informative |
|---|---|---|---|
| BND-RUNON | 6/135 (0.044), upper 0.086 | yes | yes |

Counts: calibration 2024 clips, 2024 families, 50 abstained; confirmation N2 2094 clips, 2094 families, 33 abstained; P1 403 clips, 135 families, 2 abstained; S 135 clips, 135 families, 0 abstained. Speakers: 9 (lower-bound, unit `language:fleurs-unidentified`).

Judge output identities: `align.qwen3-forcedaligner-0.6b@1` `bf244e4c8e9bf049`, `asr.paraformer-zh@1` `cd3aec442e0fd17f`, `asr.parakeet-tdt-0.6b-v3@1` `cf1534c3855670ab`, `asr.sensevoice-small-f16@1` `60dd465a89773f48`, `asr.whisper-large-v3@1` `0bdd27ea106e2512`, `fastqc@8` `072d385c65e95361`. Record limitations: `fleurs-reserve-no-speaker-ids`, `fleurs-speaker-lower-bound`, `n2-one-codec`, `pcm-measures-python-only`; risks: `aligner-anchoring`, `runon-quiet-span`, `noisy-tail-activity`.
<!-- END GENERATED audio-qc-docs:qualification -->
