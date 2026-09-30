# `boundary.truncation@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `boundary.truncation@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `465f8deced04dc52` (a plan binds it, so any change is a new version, A7).

**Measures.** The smaller of two independent recognizer families' trailing unmatched fraction: the reference units (words, or characters in zh, ja and ko) after the family's last matched unit, anchored as early as any minimum-cost alignment of the private transcript allows (language_metrics' units and edit costs, independent of tie order), over the reference length; only the score leaves the bundle.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| C (boundary) | 2 | above | consensus-min | reference-fraction | per language |

**Strata.** Word against character units and per-language recognizer behaviour at the end of a take; a pooled threshold would let one language's tail errors set every language's bound.

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| english, french, german, italian, portuguese, russian, spanish | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) transcript-tail `trailingUnmatchedFraction`; [`asr.parakeet-tdt-0.6b-v3@1`](../judges/asr.parakeet-tdt-0.6b-v3-v1.md) transcript-tail `trailingUnmatchedFraction` | - |
| chinese | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) transcript-tail `trailingUnmatchedFraction`; [`asr.paraformer-zh@1`](../judges/asr.paraformer-zh-v1.md) transcript-tail `trailingUnmatchedFraction` | - |
| japanese, korean | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) transcript-tail `trailingUnmatchedFraction`; [`asr.sensevoice-small-f16@1`](../judges/asr.sensevoice-small-f16-v1.md) transcript-tail `trailingUnmatchedFraction` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `BND-TRUNC` | severe | T1-pcm-construction | yes |

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

**Status.** Not qualified; planned, not confirmed.

**Plan.** [config/audio-qc-preregistrations/boundary.truncation@1.json](../../../../config/audio-qc-preregistrations/boundary.truncation@1.json): digest `68b22b3caabe3742`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N2; injector catalog 2, classes A,B,C,D,F, 150 per cell.
Calibration cohort audio-qc-n2-cohort (fleurs-dev, manifest `59221512a00b2b4a`); confirmation cohort audio-qc-n2-cohort (fleurs-test, manifest `ae62a87f35ed9b7c`).

**Confirmation.** Not run: no ledger entry.

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->

## See also

- [Detector qualification at warn](../../audio-qc-engineering.md#detector-qualification-at-warn-aq-07-2026-09-29): the plan, derive and confirm procedure and the reasons behind this definition.
- [Codec resynthesis (N2)](../../audio-qc-engineering.md#codec-resynthesis-n2-audit-p9): the cohorts it is fitted and confirmed on.
