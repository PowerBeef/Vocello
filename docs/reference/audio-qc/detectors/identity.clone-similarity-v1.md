# `identity.clone-similarity@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `identity.clone-similarity@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `773534a9136b65c6` (a plan binds it, so any change is a new version, A7).

**Measures.** Whole-take speaker similarity (SIM): the cosine between CAM++'s embedding of the take and of its reference clip (another utterance of the same speaker; the clone's reference in the clone lane). A low similarity alarms: a clone mismatch or another voice for the whole take.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| E (identity) | 2 | below | single | cosine | per language |

**Strata.** Speaker-verification scores shift with language: both speaker families train on VoxCeleb, which is mostly English, and the audit draws impostors from the same language first (section 4.3).

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`speaker.campplus-voxceleb@1`](../judges/speaker.campplus-voxceleb-v1.md) panel `cosine` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `IDN-IMPOSTOR` | severe | T1-parallel-corpus | yes |
| `IDN-SHIFT` | severe | T1-pcm-construction | yes |

**Populations** (role set `speaker-labeled-n2`): fit N2 (calibration, pending-speaker-labeled-calibration); confirmNegatives N2 (confirmation, pending-speaker-labeled-confirmation); positives P1 (confirmation); shams S (confirmation); informational N3, N1.

**Limitations.**

- `speaker-corpus-pending`: FLEURS publishes no speaker ids, so class E has no fit or confirmation corpus yet (role set speaker-labeled-n2, corpora pending a maintainer data decision): it needs a speaker-labeled corpus whose terms allow speaker verification (Common Voice's forbid speaker identification) with at least two utterances per speaker, resynthesized to N2 like FLEURS. Each language stratum needs at least 60 scored calibration families and 60 scored confirmation negative families (the policy's warn minimums; audit section 5.4 sizes a per-language bound on its own families), from at least 3 speakers per language, the two cohorts disjoint by family, speaker and script; the positives need 60 families per severe cell and each injector's sham 60 more. A language without such a corpus becomes a scope exclusion (audit section 5.5 step 5), which changes the definition: a new version once a plan binds it.
- `speaker-reference-clip`: The speaker judges score a take only against a reference clip: another utterance of the same speaker for a corpus take, the clone's reference in the clone lane (panel_jobs: needs_reference). The orchestrator embeds it only when the manifest names it; without one CAM++ reports no similarity and the take abstains (no-value).

**Risks.**

- `resnet293-not-voting`: The audit fails an identity only when both speaker families fall below their thresholds and abstains when they disagree (section 4.3), but ResNet293 votes only after its correlated-failure audit against CAM++ (the same VoxCeleb training data) passes. These detectors read CAM++ alone; the two-family rule (consensus-max of the two families' scores) is a new version once ResNet293 votes.
- `no-impostor-injector`: Injector catalog version 2 has no impostor construction: a recording of another speaker of the same language and gender presented against the source speaker's reference clip (T1-parallel-corpus, built from published speaker labels as LNG-SWAP is from parallel sentences), with another utterance of the source speaker as its sham. Until IDN-IMPOSTOR exists the whole-take detector has no impostor positives and its confirmation cannot start.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
