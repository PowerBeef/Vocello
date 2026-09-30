# `compact.distilhubert@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `compact.distilhubert@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Former compact research representation in the delivery cascade: a frozen 128-dimensional projection that fed only the fitted heads; transcribes nothing.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `retired` | none | neural | - | no | no | - | unmeasured |

`retired`: Removed from every QC path; only what reads legacy records remains.

**Retired.**

- `date`: 2026-09-26
- `decision`: audit-7.1-delete-from-qc
- `item`: AQ-05
- `reason`: No QC measurand: it transcribes nothing, and the ridge, elastic-net and PLS heads it fed were never calibrated and always abstained (audit sections 4.9 and 7.1, AQ-F48). Removed from the candidate order, the adapter, the preparation tool and the cascade; its license stays tier A, so it is excluded as a measurand, not for its terms.
- `successor`: None needed: class H delivery detectors (AQ-08) measure paired arousal and prosody contrasts directly.

## Provenance

- License tier **A** (none): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: Apache-2.0
- Code: Vocello runtime (owned); transformers Apache-2.0
- Training data: LibriSpeech (CC BY 4.0), distilled from HuBERT
- Independence: vendor National Taiwan University SPML; architecture distilled HuBERT encoder; training data LibriSpeech; label lineage self-supervised distillation; correlated with the generator's lab: no.
- Sources: <https://huggingface.co/ntu-spml/distilhubert>

## Pins

- `ntu-spml/distilhubert` at revision `fa87d96265d6b7af66e112faff6ff44df419cec9`.
- Digest status: `pinned`.
- Verification: Retired: no QC path loads it. The registry's load gate refuses it and the compact adapter no longer names it.
- Runtime: numpy 2.5.2, python 3.14.4, safetensors 0.7.0, torch 2.13.0, transformers 4.57.6.
- Execution registry: `config/delivery-evaluator-v2-candidates.json#retiredCandidates.distilhubert`.

| File | Bytes | Digest |
|---|---|---|
| `config.json` | - | SHA-256 `0427043d1c4c8d58` |
| `model.safetensors` | - | SHA-256 `77ad8f985c97750d` |
| `preprocessor_config.json` | - | SHA-256 `7a8f0fc8ee1272ed` |

## Execution

- Resources: canonical-host peak -; admission ceiling - (provisional); policy: retired.
- Ceiling basis: Retired; two cold probes measured 572.87 and 562.99 MB peak RSS on the M2 (2026-09).
- Output identity: adapterID, modelID, sourceRevision, weightsSHA256, binarySHA256, adapterSourceSHA256, adapterLayerSHA256, commandTemplate, runtimeDependenciesDigest, labelMapDigest, outputFormat, preprocessingConfigDigest, hostProfile. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
- Legacy identifiers: adapterIDs: distilhubert.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- No canary record.

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Audit section 2.1](../../../audits/2026-09-25-audio-qc-speech-analysis-audit.md#21-license-and-compliance-urgent) and [legacy and orchestration debt](../../audio-qc-engineering.md#legacy-and-orchestration-debt): why it left every QC path; the validators that read its legacy records stay.
