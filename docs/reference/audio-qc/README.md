---
status: active
owner: backend-mlx
reviewed: 2026-09-29
summary: Index of the audio QC reference tree (AQ-09) - the staged pipeline, verdict vocabulary and lane gating, with one generated page per registry judge and detector and a generated accuracy report.
sourceOfTruth:
  - config/audio-qc-judges.json
  - config/audio-qc-detectors.json
  - config/audio-qc-qualification-policy.json
  - config/audio-qc-lane-gates.json
  - config/audio-qc-preregistrations/
  - benchmarks/audio-qc-calibration/
  - scripts/audio_qc_docs.py
  - scripts/audio_qc_lane_gates.py
---
# Audio QC reference

How Vocello judges its own audio without a listener, and how accurate each judgement is. The
registries are the authority; these pages render them. Every fact about a judge or detector (pins,
licenses, status, scope, languages, thresholds, measured rates, verdicts, record links) sits inside a
generated block that `scripts/audio_qc_docs.py` owns: edit the registry or commit the record, then
run `scripts/dev.sh regen`. The contract gate runs `scripts/audio_qc_docs.py regen --check`, so a
page that disagrees with its sources fails CI. Hand-written text outside the blocks explains; it
never restates a fact. The design and its reasons are in the
[audit](../../audits/2026-09-25-audio-qc-speech-analysis-audit.md); the decision log and the operator
commands are in [audio-qc-engineering.md](../audio-qc-engineering.md).

- [Qualification policy](qualification-policy.md): the threshold-change authority, rendered from its
  config.
- [Meta-evaluation report](meta-evaluation-report.md): generated only; the measured accuracy of
  every detector, the lane gates and the judges' canaries.
- `judges/` and `detectors/`: one page per registry entry, named by its id with `@N` spelled `-vN`.

## Pipeline

Stage 0 runs inside the engine on every take and every platform: Fast QC, deterministic and bounded,
and the only product publication gate. After the generator exits, the Python orchestrator (it loads
no model itself) runs Stage 1 DSP judges and Stage 2 model judges as supervised workers, one process
per model per run, admitted under the registry's memory ceilings. Stage 3, the composer, is pure: it
turns each detector's measurement and calibration record into a detector verdict and each lane's
gating verdicts into a take verdict. Stage 4 writes the private bundle (untracked), the
privacy-safe records under `benchmarks/` and these pages. Stages 1 and 2 gate evidence (records, the
language and clone lanes, release promotion), never a user's publication.

A **judge** produces measurements (a transcript's error rate, a language posterior, a Fast QC field).
A **detector** turns one or two judges' measurements into a score with a direction and a threshold
per stratum. Accuracy is claimed only for detectors, by a calibration record; a judge is as
qualified as the detectors that consume it.

## Verdicts

The verdict of a detector without a qualified record is `uncalibrated`: it is listed, never blocks
and never counts toward a pass. Outside its record's scope a qualified detector abstains (A1).
Per lane, the first status in precedence order among the gating verdicts decides the take.

<!-- BEGIN GENERATED audio-qc-docs:verdicts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Composition `worst-of-gating/1`; detector statuses in precedence order `fail`, `unavailable`, `abstain`, `warn`, `uncalibrated`, `pass`; take statuses `pass`, `warn`, `fail`, `inconclusive`, `uncalibrated`, `unavailable`.

| Detector status | Swift outcome |
|---|---|
| `pass` | `pass` |
| `warn` | `warning` |
| `fail` | `fail` |
| `abstain` | `abstained` |
| `uncalibrated` | `uncalibrated` |
| `unavailable` | `unavailable` |
<!-- END GENERATED audio-qc-docs:verdicts -->

## Lane gating

The policy names the detector classes and stages each lane may gate on;
`config/audio-qc-lane-gates.json` names the detectors that actually gate it and at which level.
`scripts/audio_qc_lane_gates.py validate`, in the contract gate, refuses a listed detector unless a
committed record qualified its current definition at that level or a stricter one, at an operating
point that applies to the lane, with a scope that covers the lane's languages, modes and FAR
population. A lane with no listed detector gates on nothing yet.

<!-- BEGIN GENERATED audio-qc-docs:lanes (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Classes and stages from `laneGatingSets` in [config/audio-qc-qualification-policy.json](../../../config/audio-qc-qualification-policy.json); kinds, scopes and gates from [config/audio-qc-lane-gates.json](../../../config/audio-qc-lane-gates.json).

| Lane | Gating classes | Stages | Kind | Scope | Gated by |
|---|---|---|---|---|---|
| publication | - | 0 | - | not declared | none |
| language-bench | B, C, D | - | evidence-lane | chinese, english, french, german, japanese, spanish; modes custom, design; FAR on N2 | none |
| clone-lane | E | - | evidence-lane | english; modes clone; FAR on N2 | none |
| delivery-bench | H | - | - | not declared | none |
| release-promotion | B, C, D, E, H | 0 | - | not declared | none |
<!-- END GENERATED audio-qc-docs:lanes -->

## Judges

<!-- BEGIN GENERATED audio-qc-docs:judges (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
| Judge | Status | Kind | Family | Votes | Tier | Stage | Canary |
|---|---|---|---|---|---|---|---|
| [`asr.whisper-small@1`](judges/asr.whisper-small-v1.md) | `gating` | neural | whisper | yes | B | 2 (gpu) | no |
| [`asr.apple-speech-consensus@2`](judges/asr.apple-speech-consensus-v2.md) | `gating` | platform | apple-speech | yes | A | 2 (device) | no |
| [`fastqc@8`](judges/fastqc-v8.md) | `gating` | dsp | - | yes | A | 0 (engine) | no |
| [`prosody@3`](judges/prosody-v3.md) | `advisory` | dsp | - | no | A | 1 (dsp) | no |
| [`temporal-contour@1`](judges/temporal-contour-v1.md) | `advisory` | dsp | - | no | A | 1 (dsp) | no |
| [`integrity.canonical-pcm@1`](judges/integrity.canonical-pcm-v1.md) | `gating` | dsp | - | no | A | 1 (dsp) | no |
| [`reference.acoustic-emotion-base@1`](judges/reference.acoustic-emotion-base-v1.md) | `advisory` | dsp | - | no | A | 1 (dsp) | no |
| [`compact.sensevoice-small-q8@1`](judges/compact.sensevoice-small-q8-v1.md) | `candidate` | neural | - | no | A | 2 (cpu) | no |
| [`compact.distilhubert@1`](judges/compact.distilhubert-v1.md) | `retired` | neural | - | no | A | - | no |
| [`delivery.fitted-heads@2`](judges/delivery.fitted-heads-v2.md) | `retired` | fitted | - | no | A | - | no |
| [`speaker.ecapa-voxceleb@1`](judges/speaker.ecapa-voxceleb-v1.md) | `advisory` | neural | speaker-ecapa | no | B | 2 (cpu) | no |
| [`quality.nisqa-v2@1`](judges/quality.nisqa-v2-v1.md) | `retired` | neural | - | no | C | - | no |
| [`quality.utmosv2@1`](judges/quality.utmosv2-v1.md) | `retired` | neural | - | no | C | - | no |
| [`emotion.ser-wav2vec2-xlsr@2`](judges/emotion.ser-wav2vec2-xlsr-v2.md) | `retired` | neural | - | no | C | - | no |
| [`asr.whisper-large-v3@1`](judges/asr.whisper-large-v3-v1.md) | `shadow` | neural | whisper | yes | B | 2 (gpu) | yes |
| [`asr.parakeet-tdt-0.6b-v3@1`](judges/asr.parakeet-tdt-0.6b-v3-v1.md) | `shadow` | neural | parakeet | yes | B | 2 (gpu) | yes |
| [`asr.paraformer-zh@1`](judges/asr.paraformer-zh-v1.md) | `shadow` | neural | paraformer | yes | A | 2 (cpu) | yes |
| [`asr.sensevoice-small-f16@1`](judges/asr.sensevoice-small-f16-v1.md) | `shadow` | neural | sensevoice | yes | A | 2 (cpu) | yes |
| [`asr.qwen3-asr-1.7b@1`](judges/asr.qwen3-asr-1.7b-v1.md) | `shadow` | neural | qwen3-asr | no | A | 2 (gpu) | yes |
| [`align.qwen3-forcedaligner-0.6b@1`](judges/align.qwen3-forcedaligner-0.6b-v1.md) | `shadow` | neural | qwen3-aligner | no | A | 2 (gpu) | yes |
| [`lid.voxlingua107-ecapa@1`](judges/lid.voxlingua107-ecapa-v1.md) | `shadow` | neural | lid-voxlingua107 | yes | B | 2 (cpu) | yes |
| [`speaker.campplus-voxceleb@1`](judges/speaker.campplus-voxceleb-v1.md) | `shadow` | neural | speaker-campplus | yes | B | 2 (cpu) | yes |
| [`speaker.resnet293-voxceleb@1`](judges/speaker.resnet293-voxceleb-v1.md) | `shadow` | neural | speaker-resnet293 | no | B | 2 (cpu) | yes |
| [`pitch.pyin@1`](judges/pitch.pyin-v1.md) | `shadow` | dsp | - | no | A | 1 (dsp) | yes |
| [`quality.audiobox-aesthetics@1`](judges/quality.audiobox-aesthetics-v1.md) | `shadow` | neural | - | no | A | 2 (cpu) | yes |
| [`quality.dnsmos-p835@1`](judges/quality.dnsmos-p835-v1.md) | `shadow` | neural | - | no | B | 2 (cpu) | yes |
<!-- END GENERATED audio-qc-docs:judges -->

## Detectors

<!-- BEGIN GENERATED audio-qc-docs:detectors (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
| Detector | Class | Stage | Combination | Plan | Qualification | Gates |
|---|---|---|---|---|---|---|
| [`signal.clicks@1`](detectors/signal.clicks-v1.md) | A (signal) | 0 | single | confirmed (qualified) | qualified (warn) | - |
| [`signal.dropout@1`](detectors/signal.dropout-v1.md) | A (signal) | 0 | single | confirmed (qualified) | qualified (warn) | - |
| [`signal.dropout@2`](detectors/signal.dropout-v2.md) | A (signal) | 0 | single | no plan | not qualified | - |
| [`signal.terminal-silence@1`](detectors/signal.terminal-silence-v1.md) | A (signal) | 0 | single | confirmed (qualified) | qualified (warn) | - |
| [`signal.terminal-silence@2`](detectors/signal.terminal-silence-v2.md) | A (signal) | 0 | single | no plan | not qualified | - |
| [`signal.dc-offset@1`](detectors/signal.dc-offset-v1.md) | A (signal) | 0 | single | confirmed (qualified) | qualified (warn) | - |
| [`signal.dc-offset@2`](detectors/signal.dc-offset-v2.md) | A (signal) | 0 | single | no plan | not qualified | - |
| [`signal.level@1`](detectors/signal.level-v1.md) | A (signal) | 0 | single | confirmed (qualified) | qualified (warn) | - |
| [`signal.clipping@1`](detectors/signal.clipping-v1.md) | A (signal) | 0 | single | confirmed (refused) | refused | - |
| [`signal.noise@1`](detectors/signal.noise-v1.md) | A (signal) | 0 | single | confirmed (qualified) | qualified (warn) | - |
| [`signal.band-limit@1`](detectors/signal.band-limit-v1.md) | A (signal) | 0 | single | no plan | not qualified | - |
| [`content.consensus-error@1`](detectors/content.consensus-error-v1.md) | B (content) | 2 | consensus-min | confirmed (refused) | refused | - |
| [`boundary.truncation@1`](detectors/boundary.truncation-v1.md) | C (boundary) | 2 | consensus-min | confirmed (qualified) | qualified (warn) | - |
| [`boundary.run-on@1`](detectors/boundary.run-on-v1.md) | C (boundary) | 2 | difference | confirmed (refused) | refused | - |
| [`language.consensus-lid@1`](detectors/language.consensus-lid-v1.md) | D (language) | 2 | consensus-max | confirmed (qualified) | qualified (warn) | - |
| [`identity.clone-similarity@1`](detectors/identity.clone-similarity-v1.md) | E (identity) | 2 | single | no plan | not qualified | - |
| [`identity.window-drift@1`](detectors/identity.window-drift-v1.md) | E (identity) | 2 | difference | no plan | not qualified | - |
| [`identity.onset-drift@1`](detectors/identity.onset-drift-v1.md) | E (identity) | 2 | difference | no plan | not qualified | - |
| [`prosody.pitch-break@1`](detectors/prosody.pitch-break-v1.md) | F (prosody) | 1 | single | no plan | not qualified | - |
| [`prosody.octave-jump@1`](detectors/prosody.octave-jump-v1.md) | F (prosody) | 1 | single | no plan | not qualified | - |
| [`prosody.pitch-instability@1`](detectors/prosody.pitch-instability-v1.md) | F (prosody) | 1 | single | no plan | not qualified | - |
| [`introspection.token-loop@1`](detectors/introspection.token-loop-v1.md) | I (introspection) | 0 | single | no plan | not qualified | - |
| [`introspection.high-entropy@1`](detectors/introspection.high-entropy-v1.md) | I (introspection) | 0 | single | no plan | not qualified | - |
| [`introspection.eos-overrun@1`](detectors/introspection.eos-overrun-v1.md) | I (introspection) | 0 | single | no plan | not qualified | - |
| [`long-form.seam-discontinuity@1`](detectors/long-form.seam-discontinuity-v1.md) | J (long form) | 0 | single | no plan | not qualified | - |
| [`long-form.seam-jump@1`](detectors/long-form.seam-jump-v1.md) | J (long form) | 0 | single | no plan | not qualified | - |
| [`long-form.seam-identity@1`](detectors/long-form.seam-identity-v1.md) | J (long form) | 2 | single | no plan | not qualified | - |
<!-- END GENERATED audio-qc-docs:detectors -->

## Adding a judge or a detector

1. **Judge.** Register it in `config/audio-qc-judges.json` as a `candidate` with its pins, license
   tier and independence fields (`scripts/audio_qc_judges.py validate`). The maintainer acquires it
   (`scripts/acquire_audio_qc_judges.py`); two clean canonical-host runs and a canary record
   (`scripts/audio_qc_panel_qualification.py`, a consent-bound model run) take it to `shadow`.
2. **Detector.** Register `id@version` in `config/audio-qc-detectors.json` with its score, direction,
   strata, scope, positives and shams. Any later change to the entry is a new version (A7).
3. **Qualification.** Commit the plan under `config/audio-qc-preregistrations/` before anything
   scores the confirmation cohort, then confirm once and commit the ledger entry and the record under
   `benchmarks/audio-qc-calibration/<id>/` (`scripts/audio_qc_detector_calibration.py`; procedure in
   [audio-qc-engineering.md](../audio-qc-engineering.md#detector-qualification-at-warn-aq-07-2026-09-29)).
4. **Gating.** List the detector under its lane in `config/audio-qc-lane-gates.json`; the validator
   refuses it until the record covers the lane.
5. Run `scripts/dev.sh regen`: new pages are created with their generated blocks. Add a short note
   below the blocks only when it explains something the registry cannot say.

Corpus and injector catalogs have no registry of their own yet: the injectors live in
`scripts/lib/qc_qualification/injectors.py` and the corpora in `config/audio-qc-n1-sources.json` and
`config/audio-qc-script-pool-sources.json`.
