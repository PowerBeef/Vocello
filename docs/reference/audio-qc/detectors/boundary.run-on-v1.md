# `boundary.run-on@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `boundary.run-on@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `2ecc7a52104d0c5c` (a plan binds it, so any change is a new version, A7).

**Measures.** Seconds of recognized speech after the script ends: Whisper large-v3's last segment end minus the aligner's last aligned script unit end, only where both content voters of the language completed (the aligner times, never votes). Neither end alone against the file end works on FLEURS: Whisper's end follows the speech, so an inserted run-on leaves duration minus it unchanged, and the aligner's tail gap carries the natural trailing silence (clean N2 95th percentile 3.8 s against 0.7 s for the difference).

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| C (boundary) | 2 | above | difference | seconds | per language |

**Strata.** Whisper's last segment end overshoots the script end differently by language (clean N2 share above the pooled 95th percentile, 0.72 s: 27% in en, 12% in ja, at most 2% in fr, it, pt, ru and es).

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| english, french, german, italian, portuguese, russian, spanish | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) panel `lastSegmentEndSeconds`; [`align.qwen3-forcedaligner-0.6b@1`](../judges/align.qwen3-forcedaligner-0.6b-v1.md) panel `spanEndSeconds` | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md), [`asr.parakeet-tdt-0.6b-v3@1`](../judges/asr.parakeet-tdt-0.6b-v3-v1.md) |
| chinese | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) panel `lastSegmentEndSeconds`; [`align.qwen3-forcedaligner-0.6b@1`](../judges/align.qwen3-forcedaligner-0.6b-v1.md) panel `spanEndSeconds` | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md), [`asr.paraformer-zh@1`](../judges/asr.paraformer-zh-v1.md) |
| japanese | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) panel `lastSegmentEndSeconds`; [`align.qwen3-forcedaligner-0.6b@1`](../judges/align.qwen3-forcedaligner-0.6b-v1.md) panel `spanEndSeconds` | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md), [`asr.sensevoice-small-f16@1`](../judges/asr.sensevoice-small-f16-v1.md) |

**Scope.** chinese, english, french, german, italian, japanese, portuguese, russian, spanish.
Excludes korean: The forced aligner is out of scope for Korean: mlx-audio tokenizes it with soynlp (GPL-3.0), which the exclusion list refuses, so there is no script-end time in Korean.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `BND-RUNON` | severe | T1-pcm-construction | yes |

**Populations** (role set `fleurs-n2`): fit N2 (calibration, fleurs-dev); confirmNegatives N2 (confirmation, fleurs-test); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `fleurs-no-speaker-ids`: FLEURS publishes no speaker ids; its TSVs give only a gender per recording. Speaker disjointness between the dev (calibration) and test (confirmation) splits cannot be verified, and neither can a speaker count: family and script disjointness hold, speaker disjointness is assumed, not shown.
- `fleurs-speaker-lower-bound`: Units carry the speaker '<language>:fleurs-unidentified', a lower bound on the speaker count: FLEURS collects each locale separately, so recordings of different languages cannot share a speaker. The policy minimum of 3 speakers is therefore met only by covering at least 3 languages.
- `n2-one-codec`: N2 is one production codec round trip (the pro_clone speed variant at full codebooks) of FLEURS read speech; FAR on it is in the codec's domain, not on natural Vocello takes (N3, informational at warn).

**Risks.**

- `fleurs-trailing-silence`: FLEURS recordings end in natural trailing silence (clean N2 aligner tail gap: median 1.3 s, 95th percentile 3.8 s), which swamps a run-on measured against the file end; the run-on score subtracts it by measuring against the script's aligned end instead.
- `aligner-anchoring`: The run-on score assumes the aligner places the script's last unit on its first occurrence; a repeated tail the aligner anchors on its last copy is missed.
- `whisper-segment-timing`: Whisper segment ends come from 20 ms timestamp tokens and can end early or snap to round seconds (clean N2: 5% end more than 1.1 s before the aligner's script end).

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; planned, not confirmed.

**Plan.** [config/audio-qc-preregistrations/boundary.run-on@1.json](../../../../config/audio-qc-preregistrations/boundary.run-on@1.json): digest `40cbfdf9b37db8a2`, rule split-conformal, alpha 0.05, confidence 0.95, operating point warn, population N2; injector catalog 2, classes A,B,C,D,F, 150 per cell.
Calibration cohort audio-qc-n2-cohort (fleurs-dev, manifest `59221512a00b2b4a`); confirmation cohort audio-qc-n2-cohort (fleurs-test, manifest `ae62a87f35ed9b7c`).

**Confirmation.** Not run: no ledger entry.

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->

## See also

- [Detector qualification at warn](../../audio-qc-engineering.md#detector-qualification-at-warn-aq-07-2026-09-29): the plan, derive and confirm procedure and the reasons behind this definition.
- [Codec resynthesis (N2)](../../audio-qc-engineering.md#codec-resynthesis-n2-audit-p9): the cohorts it is fitted and confirmed on.
