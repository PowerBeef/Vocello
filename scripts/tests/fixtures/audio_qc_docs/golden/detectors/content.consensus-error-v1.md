# `content.consensus-error@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `content.consensus-error@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `70e9b82f45c710db` (a plan binds it, so any change is a new version, A7).

**Measures.** The smaller of two independent recognizer families' error rates (WER, or CER in zh, ja and ko) against the script, so both must be high to alarm. Qwen3-ASR is same-lab and never votes (A6).

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| B (content) | 2 | above | consensus-min | error-rate | per language |

**Strata.** Error rates differ by language: word against character units and each recognizer's quality per language (clean N2 95th percentile: 0.037 in it to 0.14 in ja; 13% of ja above the pooled 0.094).

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| english, french, german | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) panel `errorRate`; [`asr.parakeet-tdt-0.6b-v3@1`](../judges/asr.parakeet-tdt-0.6b-v3-v1.md) panel `errorRate` | - |

**Scope.** english, french, german.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `CNT-DEL` | severe | T1-pcm-construction | yes |

**Populations** (role set `fleurs-n2`): fit N2 (calibration, fleurs-dev); confirmNegatives N2 (confirmation, fleurs-test); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. Speaker disjointness between the dev (calibration) and test (confirmation) splits cannot be verified, and neither can a speaker count: family and script disjointness hold, speaker disjointness is assumed, not shown.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).

**Risks.**

- `parakeet-whisper-label-lineage`: Parakeet's training labels include Whisper pseudo-labels (Granary), so the pair may fail together; the phi audit in the record measures it before the pair gates.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): language-bench at warn.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Qualified (warn); confirmed (qualified).

**Plan.** [config/audio-qc-preregistrations/content.consensus-error@1.json](../../../../config/audio-qc-preregistrations/content.consensus-error@1.json): digest `827411f5fdccba84`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N2; injector catalog 2, classes B, 150 per cell.
Calibration cohort audio-qc-n2-cohort (fleurs-dev, manifest `ef260e9aa3c673af`); confirmation cohort audio-qc-n2-cohort (fleurs-test, manifest `9f86d081884c7d65`).

**Confirmation.** Ledger entry qualified.

### Record [record-827411f5fdccba84.json](../../../../benchmarks/audio-qc-calibration/content.consensus-error@1/record-827411f5fdccba84.json): qualified at warn

Operating point warn; rule split-conformal, alpha 0.05, thresholds per language; plan `827411f5fdccba84`. Rates count source families with one-sided Clopper-Pearson bounds.

| Stratum | Threshold | FAR on confirmation N2 | Limit | Meets |
|---|---|---|---|---|
| english | 0.0931 | 2/120 (0.017), upper 0.063 | 0.2 | yes |
| french | 0.0812 | 1/118 (0.008), upper 0.050 | 0.2 | yes |
| german | 0.1175 | 4/121 (0.033), upper 0.087 | 0.2 | yes |
| pooled | - | 7/359 (0.019), upper 0.036 | 0.1 | yes |

Per-language bounds at confidence 0.983333 (Bonferroni over the languages), pooled at 0.95. Clean abstention: 3/359 (0.008), upper 0.021 (limit 0.1, meets yes).

| Mechanism | Cell | Detected | Limit | Meets |
|---|---|---|---|---|
| T1-pcm-construction | CNT-DEL/severe | 141/150 (0.940), lower 0.898 | 0.7 | yes |

Mechanisms meeting: T1-pcm-construction (minimum 1).

| Sham cell | Alarms | Overlaps N2 FAR | Informative |
|---|---|---|---|
| CNT-DEL | 6/150 (0.040), upper 0.077 | yes | yes |

Counts: calibration 360 clips, 360 families, 2 abstained; confirmation N2 359 clips, 359 families, 3 abstained; P1 150 clips, 150 families, 1 abstained; S 150 clips, 150 families, 0 abstained. Speakers: 3 (lower-bound, unit `language:fleurs-unidentified`).

| Consensus languages | Judges | Units | Phi | Joint failure |
|---|---|---|---|---|
| english, french, german | asr.whisper-large-v3@1, asr.parakeet-tdt-0.6b-v3@1 | 505 | 0.261 | 4/505 (0.008), upper 0.018 |

N3 (report-only): flag rate 9/200 (0.045), upper 0.077; FAR bound pi 0.05: 0.047368, pi 0.1: 0.05, pi 0.2: 0.05625.

Judge output identities: `asr.parakeet-tdt-0.6b-v3@1` `bbbbbbbbbbbbbbbb`, `asr.whisper-large-v3@1` `aaaaaaaaaaaaaaaa`. Record limitations: `fleurs-no-speaker-ids`, `fleurs-speaker-lower-bound`, `n2-one-codec`; risks: `parakeet-whisper-label-lineage`.
<!-- END GENERATED audio-qc-docs:qualification -->
