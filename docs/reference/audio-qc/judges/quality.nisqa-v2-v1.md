# `quality.nisqa-v2@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `quality.nisqa-v2@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Former clip-quality screen (MV-06): five NISQA dimensions against a calibrated MOS warn floor in the delivery cascade and clip_quality_screen.py.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `retired` | none | neural | - | no | no | - | unmeasured |

`retired`: Removed from every QC path; only what reads legacy records remains.

**Retired.**

- `date`: 2026-09-25
- `decision`: 1a
- `finding`: AQ-F01
- `reason`: The released weights (nisqa.tar) are CC BY-NC-SA 4.0; the registry recorded MIT and commercial compatibility. Weak on clean TTS (onset-cluster AUC 0.54).
- `successor`: Audiobox Aesthetics and DNSMOS advisory columns after a ladder test (AQ-08)

## Provenance

- License tier **C** (non-commercial): Non-commercial weights, or training data under an explicit non-commercial or research-only term. Never runs in a QC path. Commercial use compatible: no.
- Weights: CC BY-NC-SA 4.0 (nisqa.tar); the torchmetrics port downloads the same checkpoint
- Code: MIT (NISQA); Apache-2.0 (torchmetrics port)
- Training data: NISQA Corpus (non-commercial research) and the listed public listening-test datasets
- Independence: vendor TU Berlin (Mittag et al.); architecture CNN-self-attention MOS predictor; training data NISQA Corpus; label lineage crowdsourced MOS; correlated with the generator's lab: no.
- Sources: <https://github.com/gabrielmittag/NISQA>, <https://github.com/gabrielmittag/NISQA/wiki/NISQA-Corpus>, <https://github.com/Lightning-AI/torchmetrics/blob/master/src/torchmetrics/functional/audio/nisqa.py>

## Pins

- `gabrielmittag/NISQA` at revision `fe84f0f252abec382b24367d5b22498a7ce34dbb`.
- Digest status: `pinned`.
- Verification: Retired: no QC path loads it.
- Execution registry: `config/delivery-evaluator-v2-candidates.json#retiredCandidates.nisqa-v2`.

| File | Bytes | Digest |
|---|---|---|
| `nisqa.tar` | - | SHA-256 `7ec4cf937514dd3f` |

## Execution

- Resources: canonical-host peak -; admission ceiling - (provisional); policy: retired.
- Ceiling basis: Retired; about 403 MB peak RSS in its 2026-09-14 qualification.
- Output identity: adapterID, modelID, sourceRevision, weightsSHA256, binarySHA256, runtimeDependenciesDigest, preprocessingConfigDigest. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion.
- Legacy identifiers: adapterIDs: nisqa-v2; cascadeLayers: clip-quality-screen; reportFields: clipQualityScreen; sources: scripts/clip_quality_screen.py.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- No canary record.

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Audit section 2.1](../../../audits/2026-09-25-audio-qc-speech-analysis-audit.md#21-license-and-compliance-urgent) and [legacy and orchestration debt](../../audio-qc-engineering.md#legacy-and-orchestration-debt): why it left every QC path; the validators that read its legacy records stay.
