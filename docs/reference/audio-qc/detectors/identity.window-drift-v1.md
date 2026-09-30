# `identity.window-drift@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `identity.window-drift@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `38976afe77eb66a2` (a plan binds it, so any change is a new version, A7).

**Measures.** Window drift: CAM++'s whole-take cosine to the reference clip minus its lowest 2 s window cosine (0.5 s hop) to the same reference, so a span of another voice inside the take alarms against the take's own similarity while a whole-take mismatch (the clone-similarity detector's) does not.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| E (identity) | 2 | above | difference | cosine | per language |

**Strata.** Speaker-verification scores shift with language: both speaker families train on VoxCeleb, which is mostly English, and the audit draws impostors from the same language first (section 4.3).

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`speaker.campplus-voxceleb@1`](../judges/speaker.campplus-voxceleb-v1.md) panel `cosine`; [`speaker.campplus-voxceleb@1`](../judges/speaker.campplus-voxceleb-v1.md) panel `windowCosineMinimum` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `IDN-SWAP` | severe | T1-pcm-construction | yes |

**Populations** (role set `speaker-labeled-n2`): fit N2 (calibration, pending-speaker-labeled-calibration); confirmNegatives N2 (confirmation, pending-speaker-labeled-confirmation); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `speaker-corpus-pending`: FLEURS publishes no speaker ids, so class E has no fit or confirmation corpus yet (role set speaker-labeled-n2, corpora pending a maintainer data decision): it needs a speaker-labeled corpus whose terms allow speaker verification (Common Voice's forbid speaker identification) with at least two utterances per speaker, resynthesized to N2 like FLEURS. Each language stratum needs at least 60 scored calibration families and 60 scored confirmation negative families (the policy's warn minimums; audit section 5.4 sizes a per-language bound on its own families), from at least 3 speakers per language, the two cohorts disjoint by family, speaker and script; the positives need 60 families per severe cell and each injector's sham 60 more. A language without such a corpus becomes a scope exclusion (audit section 5.5 step 5), which changes the definition: a new version once a plan binds it.
- `speaker-reference-clip`: The speaker judges score a take only against a reference clip: another utterance of the same speaker for a corpus take, the clone's reference in the clone lane (panel_jobs: needs_reference). The orchestrator embeds it only when the manifest names it (a calibration take's or entry's reference: its WAV path and digest); without one CAM++ reports no similarity and the take abstains (no-value), and the calibration refuses evidence measured against another clip than the declared one.

**Risks.**

- `resnet293-not-voting`: The audit fails an identity only when both speaker families fall below their thresholds and abstains when they disagree (section 4.3), but ResNet293 votes only after its correlated-failure audit against CAM++ (the same VoxCeleb training data) passes. These detectors read CAM++ alone; the two-family rule (consensus-max of the two families' scores) is a new version once ResNet293 votes.
- `short-window-embeddings`: Speaker embeddings degrade on short windows (audit section 4.3): a 2 s window scores lower against the reference than the whole take even on clean speech. The drift and onset scores subtract the window's cosine from the take's own whole-take cosine, so each take is its own baseline; a take shorter than one window has none and abstains (no-value).

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
