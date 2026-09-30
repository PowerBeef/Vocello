# `content.consensus-error@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `content.consensus-error@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `a3f8d2856e7a8749` (a plan binds it, so any change is a new version, A7).

**Measures.** The smaller of two independent recognizer families' error rates (WER, or CER in zh, ja and ko) against the script, so both must be high to alarm. Qwen3-ASR is same-lab and never votes (A6).

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| B (content) | 2 | above | consensus-min | error-rate | per language |

**Strata.** Error rates differ by language: word against character units and each recognizer's quality per language (clean N2 95th percentile: 0.037 in it to 0.14 in ja; 13% of ja above the pooled 0.094).

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| english, french, german, italian, portuguese, russian, spanish | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) panel `errorRate`; [`asr.parakeet-tdt-0.6b-v3@1`](../judges/asr.parakeet-tdt-0.6b-v3-v1.md) panel `errorRate` | - |
| chinese | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) panel `errorRate`; [`asr.paraformer-zh@1`](../judges/asr.paraformer-zh-v1.md) panel `errorRate` | - |
| japanese, korean | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) panel `errorRate`; [`asr.sensevoice-small-f16@1`](../judges/asr.sensevoice-small-f16-v1.md) panel `errorRate` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `CNT-DEL` | severe | T1-pcm-construction | yes |
| `CNT-INS` | severe | T1-pcm-construction | yes |
| `CNT-REP` | severe | T1-pcm-construction | yes |

**Populations** (role set `fleurs-n2`): fit N2 (calibration, fleurs-dev); confirmNegatives N2 (confirmation, fleurs-test); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. Speaker disjointness between the dev (calibration) and test (confirmation) splits cannot be verified, and neither can a speaker count: family and script disjointness hold, speaker disjointness is assumed, not shown.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).

**Risks.**

- `parakeet-whisper-label-lineage`: Parakeet's training labels include Whisper pseudo-labels (Granary), so the pair may fail together; the phi audit in the record measures it before the pair gates.
- `sensevoice-codec-degradation`: SenseVoice degrades through the codec: its error rate exceeds 0.5 on 0% (ja) and 9.6% (ko) of N1 FLEURS dev recordings and on 5.6% and 18.5% of their N2 resyntheses (panels of 2026-09-29). Under min() a failed SenseVoice transcript leaves Whisper as the effective vote in ja and ko; the confirmation decides and the phi audit shows it.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Refused; confirmed (refused).

**Plan.** [config/audio-qc-preregistrations/content.consensus-error@1.json](../../../../config/audio-qc-preregistrations/content.consensus-error@1.json): digest `7ca2a3effc9f6df0`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N2; injector catalog 2, classes A,B,C,D,F, 150 per cell.
Calibration cohort audio-qc-n2-cohort (fleurs-dev, manifest `59221512a00b2b4a`); confirmation cohort audio-qc-n2-cohort (fleurs-test, manifest `ae62a87f35ed9b7c`).

**Confirmation.** Ledger entry refused (cross-mechanism-detection-not-met).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.

### Record [record-7ca2a3effc9f6df0.json](../../../../benchmarks/audio-qc-calibration/content.consensus-error@1/record-7ca2a3effc9f6df0.json): refused (cross-mechanism-detection-not-met)

Operating point warn; rule split-conformal, alpha 0.05, thresholds per language; plan `7ca2a3effc9f6df0`. Rates count source families with one-sided Clopper-Pearson bounds.

| Stratum | Threshold | FAR on confirmation N2 | Limit | Meets |
|---|---|---|---|---|
| chinese | 0.111111 | 27/602 (0.045), upper 0.071 | 0.2 | yes |
| english | 0.117647 | 8/236 (0.034), upper 0.077 | 0.2 | yes |
| french | 0.0952381 | 32/286 (0.112), upper 0.168 | 0.2 | yes |
| german | 0.1 | 36/560 (0.064), upper 0.096 | 0.2 | yes |
| italian | 0.0416667 | 21/351 (0.060), upper 0.100 | 0.2 | yes |
| japanese | 0.146341 | 21/357 (0.059), upper 0.099 | 0.2 | yes |
| korean | 0.0666667 | 15/245 (0.061), upper 0.112 | 0.2 | yes |
| portuguese | 0.0909091 | 20/359 (0.056), upper 0.095 | 0.2 | yes |
| russian | 0.0869565 | 11/326 (0.034), upper 0.069 | 0.2 | yes |
| spanish | 0.0588235 | 25/396 (0.063), upper 0.101 | 0.2 | yes |
| pooled | - | 216/3718 (0.058), upper 0.065 | 0.1 | yes |

Per-language bounds at confidence 0.995 (Bonferroni over the languages), pooled at 0.95. Clean abstention: 0/3718 (0.000), upper 0.001 (limit 0.1, meets yes).

| Mechanism | Cell | Detected | Limit | Meets |
|---|---|---|---|---|
| T1-pcm-construction | CNT-DEL/severe | 124/150 (0.827), lower 0.768 | 0.7 | yes |
| T1-pcm-construction | CNT-INS/severe | 100/150 (0.667), lower 0.598 | 0.7 | no |
| T1-pcm-construction | CNT-REP/severe | 77/150 (0.513), lower 0.443 | 0.7 | no |

Mechanisms meeting: - (minimum 1).

| Sham cell | Alarms | Overlaps N2 FAR | Informative |
|---|---|---|---|
| CNT-DEL | 7/150 (0.047), upper 0.086 | yes | yes |
| CNT-INS | 8/150 (0.053), upper 0.094 | yes | yes |
| CNT-REP | 13/150 (0.087), upper 0.134 | yes | yes |

Counts: calibration 1888 clips, 1888 families, 0 abstained; confirmation N2 3718 clips, 3718 families, 0 abstained; P1 450 clips, 435 families, 0 abstained; S 450 clips, 435 families, 0 abstained. Speakers: 10 (lower-bound, unit `language:fleurs-unidentified`).

| Consensus languages | Judges | Units | Phi | Joint failure |
|---|---|---|---|---|
| english, french, german, italian, portuguese, russian, spanish | asr.whisper-large-v3@1, asr.parakeet-tdt-0.6b-v3@1 | 2865 | 0.389013 | 170/2514 (0.068), upper 0.076 |
| chinese | asr.whisper-large-v3@1, asr.paraformer-zh@1 | 652 | 0.401077 | 34/602 (0.056), upper 0.074 |
| japanese, korean | asr.whisper-large-v3@1, asr.sensevoice-small-f16@1 | 651 | 0.295244 | 43/602 (0.071), upper 0.091 |

N3 (report-only): flag rate 130/791 (0.164), upper 0.188; FAR bound pi 0.05: 0.172999, pi 0.1: 0.18261, pi 0.2: 0.205436.

Judge output identities: `asr.paraformer-zh@1` `cd3aec442e0fd17f`, `asr.parakeet-tdt-0.6b-v3@1` `cf1534c3855670ab`, `asr.sensevoice-small-f16@1` `60dd465a89773f48`, `asr.whisper-large-v3@1` `0bdd27ea106e2512`. Record limitations: `fleurs-no-speaker-ids`, `fleurs-speaker-lower-bound`, `n2-one-codec`; risks: `parakeet-whisper-label-lineage`, `sensevoice-codec-degradation`.
<!-- END GENERATED audio-qc-docs:qualification -->

## See also

- [Detector qualification at warn](../../audio-qc-engineering.md#detector-qualification-at-warn-aq-07-2026-09-29): the plan, derive and confirm procedure and the reasons behind this definition.
- [Codec resynthesis (N2)](../../audio-qc-engineering.md#codec-resynthesis-n2-audit-p9): the cohorts it is fitted and confirmed on.
