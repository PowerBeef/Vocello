# `content.consensus-error@2`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `content.consensus-error@2` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `353e57339154c3bf` (a plan binds it, so any change is a new version, A7).

**Measures.** The mean of two independent recognizer families' insertion-deletion rates against the script: the units (words, or characters in zh) a family heard beyond the script plus the script's units it did not hear, over the script's length, from the minimum-cost alignment of its private transcript that has the fewest of them (a pair read either way counts as a substitution, a recognizer's own error; substitutions do not count). The mean lets the literal family's hearing count where Whisper large-v3 smooths a repetition away: on the spent AQ-07 data Whisper transcribed none of the repeated units in 73 of 133 CNT-REP severe positives, where the second family heard at least three in 125, so v1's minimum could not reach 0.70. One family alarms alone only with twice the threshold's evidence. Qwen3-ASR is same-lab and never votes (A6).

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| B (content) | 2 | above | consensus-mean | reference-fraction | per language |

**Strata.** Word against character units and each recognizer's hearing per language (spent AQ-07 dev N2, 95th percentile of the two families' mean: 0.021 in it to 0.059 in de).

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| english, french, german, italian, portuguese, russian, spanish | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) transcript-edit `insertionDeletionRate`; [`asr.parakeet-tdt-0.6b-v3@1`](../judges/asr.parakeet-tdt-0.6b-v3-v1.md) transcript-edit `insertionDeletionRate` | - |
| chinese | [`asr.whisper-large-v3@1`](../judges/asr.whisper-large-v3-v1.md) transcript-edit `insertionDeletionRate`; [`asr.paraformer-zh@1`](../judges/asr.paraformer-zh-v1.md) transcript-edit `insertionDeletionRate` | - |

**Scope.** chinese, english, french, german, italian, portuguese, russian, spanish.
Excludes japanese: The ja and ko content pair is Whisper and SenseVoice, and SenseVoice fails outright on codec audio (error rate above 0.5 on 5.6% of ja and 18.5% of ko N2): under the two-family mean each failure scores about 0.5 on a clean take, so on the spent AQ-07 data the Japanese threshold sat at 0.5 and 6 of 49 Japanese severe content positives alarmed. Japanese and Korean stay outside until a second family survives the codec (Korean also has no word-level positives).
Excludes korean: The ja and ko content pair is Whisper and SenseVoice, and SenseVoice fails outright on codec audio (error rate above 0.5 on 5.6% of ja and 18.5% of ko N2): under the two-family mean each failure scores about 0.5 on a clean take, so on the spent AQ-07 data the Japanese threshold sat at 0.5 and 6 of 49 Japanese severe content positives alarmed. Japanese and Korean stay outside until a second family survives the codec (Korean also has no word-level positives).

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
- `substitutions-not-scored`: A substitution (a unit heard as another) does not count, so a mispronounced or wrong word leaves the score unchanged unless it changes the number of units heard: substitution defects stay outside this detector, which the audit keeps warn-only anyway (section 5.7).

**Risks.**

- `parakeet-whisper-label-lineage`: Parakeet's training labels include Whisper pseudo-labels (Granary), so the pair may fail together; the phi audit in the record measures it before the pair gates.
- `one-family-alarm`: Under the two-family mean one family's evidence alarms alone once it reaches twice the threshold, so a passage one recognizer hallucinates or drops (Whisper hallucinates on non-speech) can alarm without the other. The per-language conformal threshold still bounds the N2 FAR, and the phi audit records how the two families fail together; a strict consensus (both high) cannot see what one family never transcribes, which is why v1 missed repetitions.
- `splice-sham-content-errors`: CNT-REP's sham, a splice at the same boundary with nothing repeated, raises the two families' insertion-deletion rate: on the spent AQ-07 data 14 of 133 sham families alarmed at alpha 0.05 against 164 of 3,116 clean ones, intervals that do not overlap (A4 would refuse), and 9 of 133 against 104 of 3,116 at alpha 0.03, which overlap narrowly. Plan at alpha 0.03, where the severe cells still met A3 (lower bounds 0.868, 0.816 and 0.913).

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
