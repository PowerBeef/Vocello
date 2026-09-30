# Audio QC reference

<!-- BEGIN GENERATED audio-qc-docs:judges (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
| Judge | Status | Kind | Family | Votes | Tier | Stage | Canary |
|---|---|---|---|---|---|---|---|
| [`asr.parakeet-tdt-0.6b-v3@1`](judges/asr.parakeet-tdt-0.6b-v3-v1.md) | `shadow` | neural | parakeet | yes | B | 2 (gpu) | no |
| [`asr.whisper-large-v3@1`](judges/asr.whisper-large-v3-v1.md) | `shadow` | neural | whisper | yes | B | 2 (gpu) | yes |
| [`fastqc@8`](judges/fastqc-v8.md) | `gating` | dsp | - | yes | A | 0 (engine) | no |
| [`quality.nisqa-v2@1`](judges/quality.nisqa-v2-v1.md) | `retired` | neural | - | no | C | - | no |
<!-- END GENERATED audio-qc-docs:judges -->

<!-- BEGIN GENERATED audio-qc-docs:detectors (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
| Detector | Class | Stage | Combination | Plan | Qualification | Gates |
|---|---|---|---|---|---|---|
| [`signal.clicks@1`](detectors/signal.clicks-v1.md) | A (signal) | 0 | single | no plan | not qualified | - |
| [`content.consensus-error@1`](detectors/content.consensus-error-v1.md) | B (content) | 2 | consensus-min | confirmed (qualified) | qualified (warn) | language-bench (warn) |
<!-- END GENERATED audio-qc-docs:detectors -->

<!-- BEGIN GENERATED audio-qc-docs:lanes (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Classes and stages from `laneGatingSets` in [config/audio-qc-qualification-policy.json](../../../config/audio-qc-qualification-policy.json); kinds, scopes and gates from [config/audio-qc-lane-gates.json](../../../config/audio-qc-lane-gates.json).

| Lane | Gating classes | Stages | Kind | Scope | Gated by |
|---|---|---|---|---|---|
| publication | - | 0 | - | not declared | none |
| language-bench | B, C, D | - | evidence-lane | english, french, german; modes custom, design; FAR on N2 | [`content.consensus-error@1`](detectors/content.consensus-error-v1.md) (warn) |
| clone-lane | E | - | evidence-lane | english; modes clone; FAR on N2 | none |
| delivery-bench | H | - | - | not declared | none |
| release-promotion | B, C, D, E, H | 0 | - | not declared | none |
<!-- END GENERATED audio-qc-docs:lanes -->

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
