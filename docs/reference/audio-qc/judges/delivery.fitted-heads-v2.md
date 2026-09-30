# `delivery.fitted-heads@2`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `delivery.fitted-heads@2` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Former tiny local heads of the delivery evaluator v2 (ridge-v1 baseline, elastic-net-v2 and partial-least-squares-v2 challengers, with the pairwise logistic head) that estimated semantic delivery from paired acoustic and compact deltas in the cascade.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `retired` | none | fitted | - | no | no | - | unmeasured |

`retired`: Removed from every QC path; only what reads legacy records remains.

**Retired.**

- `date`: 2026-09-26
- `decision`: audit-7.1-delete-from-qc
- `item`: AQ-05
- `reason`: Never calibrated and always abstained, so they had no QC measurand (audit sections 4.9 and 7.1, AQ-F48). The cascade no longer accepts an evaluator model or requests the tiny-local-heads layer; the fitting and scoring commands of delivery_evaluator.py remain research tooling outside every QC path.
- `successor`: Class H paired arousal and prosody contrasts at cell level (AQ-08).

## Provenance

- License tier **A** (none): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: none: coefficients fitted locally per calibration
- Code: Vocello (owned)
- Training data: Operator-local fits over Vocello's own paired delivery features and dimensional labels; no fit was ever qualified
- Independence: vendor Vocello; architecture regularized linear and logistic heads over acoustic and compact deltas; training data Vocello delivery features; label lineage operator-local dimensional labels; correlated with the generator's lab: no.

## Pins

- Digest status: `fitted-model-digest`.
- Verification: Retired: no QC path loads a fitted model. A fitted model was a local file bound by its modelDigest.

## Execution

- Resources: canonical-host peak -; admission ceiling - (provisional); policy: retired.
- Ceiling basis: Retired; ran in-process in the cascade.
- Output identity: modelDigest, featureNames, analyzerSourceSHA256. Envelope identity: -.
- Legacy identifiers: cascadeLayers: tiny-local-heads; reportFields: tinyLocalHeads; evaluatorModels: ridge-v1, elastic-net-v2, partial-least-squares-v2, per-preset-regularized-logistic-v2.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- No canary record.

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Audit section 2.1](../../../audits/2026-09-25-audio-qc-speech-analysis-audit.md#21-license-and-compliance-urgent) and [legacy and orchestration debt](../../audio-qc-engineering.md#legacy-and-orchestration-debt): why it left every QC path; the validators that read its legacy records stay.
