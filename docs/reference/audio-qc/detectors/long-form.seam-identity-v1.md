# `long-form.seam-identity@1`

<!-- BEGIN GENERATED audio-qc-docs:definition (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `long-form.seam-identity@1` in [config/audio-qc-detectors.json](../../../../config/audio-qc-detectors.json); definition digest `2ef7bfad0a02cc25` (a plan binds it, so any change is a new version, A7).

**Measures.** Seam identity delta: across each long-form seam, the cosine between CAM++'s last 2 s window ending at or before the seam and its first window starting at or after it, reduced from its window embeddings; the lowest over the seams. A voice that changes at a seam alarms. A take without seams, or without a window on both sides of one, abstains.

| Class | Stage | Direction | Combination | Unit | Thresholds |
|---|---|---|---|---|---|
| J (long form) | 2 | below | single | cosine | pooled |

**Score components.**

| Languages | Components | Requires complete |
|---|---|---|
| chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | [`speaker.campplus-voxceleb@1`](../judges/speaker.campplus-voxceleb-v1.md) raw-output `seamWindowCosineMinimum` | - |

**Scope.** chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish.

**Positives and shams.**

| Injector | Severities | Mechanism | Matched sham |
|---|---|---|---|
| `SEAM-VOICE` | severe | T1-pcm-construction | yes |

**Populations** (role set `n3-long-form`): fit N3 (calibration, pending-vocello-long-form-calibration); confirmNegatives N3 (confirmation, pending-vocello-long-form-confirmation); positives P1 (confirmation); shams S (confirmation).

**Limitations.**

- `n3-no-labels`: A measure that exists only on generated takes (the talker's introspection, long-form seams) has no N2 to confirm on: a codec round trip samples no token and joins no segment, so its fit and confirmation negatives are N3 alone (audit section 5.7), the two splits of config/audio-qc-calibration-takes.json disjoint by family, speaker and script. N3 carries no defect labels, so a flag rate f bounds the false-alarm rate only as f / (1 - pi_max), where pi_max is the largest defect prevalence admitted (section 5.1). Each language stratum needs at least 60 scored families in each split (the calibration split plans 80 per language).
- `long-form-takes-pending`: Class J's negatives are natural long-form takes (N3 long form, audit section 5.7): multi-segment projects assembled by the product's long-form path, with their segment boundaries. The N3 take plan holds single-segment takes only, so the fit and confirmation cohorts (role set n3-long-form, corpora pending) wait for a long-form take plan: at least 60 scored families in each (one pooled threshold, over at least 3 languages, speakers and scripts), every family a script x voice x seed project with at least one seam, the two disjoint by family, speaker and script.

**Risks.**

- `no-seam-injector`: Injector catalog version 2 has no seam family. The audit's SEAM-* constructions (section 5.2) act at a long-form seam and need the take's seam offsets: SEAM-DISC removes 1, 5 and 20 ms of samples at the seam (mild, moderate, severe; no removal as its sham), and SEAM-VOICE replaces the segment after the seam with the same text rendered by another voice (a same-voice re-render as its sham). COD-SEAM (T2, a 1-3 frame seam misalignment) is the second mechanism. Until they exist the class J detectors have no positives.
- `speaker-raw-windows-export`: The panel bundle keeps CAM++'s reference-relative L2 metrics only; its window embeddings stay in the orchestrator's L1 cache. audio_qc_calibration_set.py raw-outputs --judge speaker.campplus-voxceleb@1 exports them per take (speaker embeddings: an untracked build artifact, never committed), and scores --raw-outputs passes them with each long-form take's seam times.
- `seam-window-similarity`: Two 2 s windows of one voice score lower against each other than whole takes do, and a window beside a seam may hold the inserted pause, so the clean long-form distribution, not a speaker-verification threshold, sets the bound; a seam without a whole window on both sides is not scored.
- `resnet293-not-voting`: The audit fails an identity only when both speaker families fall below their thresholds and abstains when they disagree (section 4.3), but ResNet293 votes only after its correlated-failure audit against CAM++ (the same VoxCeleb training data) passes. These detectors read CAM++ alone; the two-family rule (consensus-max of the two families' scores) is a new version once ResNet293 votes.

**Lanes it gates** ([config/audio-qc-lane-gates.json](../../../../config/audio-qc-lane-gates.json)): none.
<!-- END GENERATED audio-qc-docs:definition -->

<!-- BEGIN GENERATED audio-qc-docs:qualification (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Qualification

**Status.** Not qualified; no plan.

**Plan.** None committed under [config/audio-qc-preregistrations/](../../../../config/audio-qc-preregistrations).

**Not qualified.** No committed calibration record qualifies it: its measurements compose as `uncalibrated` and it gates no lane.
<!-- END GENERATED audio-qc-docs:qualification -->
