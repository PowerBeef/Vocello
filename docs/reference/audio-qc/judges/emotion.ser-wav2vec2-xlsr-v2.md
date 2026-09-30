# `emotion.ser-wav2vec2-xlsr@2`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `emotion.ser-wav2vec2-xlsr@2` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Former speech-emotion agreement advisory (emotion_advisory.py): reference-bank eligibility, the clone lane's third analyzer and the evaluator's SER layer.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `retired` | none | neural | - | no | no | - | unmeasured |

`retired`: Removed from every QC path; only what reads legacy records remains.

**Retired.**

- `date`: 2026-09-25
- `decision`: 1a
- `finding`: AQ-F03
- `reason`: Trained on RAVDESS (CC BY-NC-SA 4.0), TESS (CC BY-NC-ND 4.0) and SAVEE (research use); its docstring called it permissively licensed. It also resampled with np.interp and ran outside the supervisor.
- `successor`: Paired, speaker-normalized arousal and prosody deltas now; the owned Whisper-encoder probe later (AQ-08)

## Provenance

- License tier **C** (non-commercial): Non-commercial weights, or training data under an explicit non-commercial or research-only term. Never runs in a QC path. Commercial use compatible: no.
- Weights: Fine-tune of facebook/wav2vec2-large-xlsr-53 (Apache-2.0); the fine-tuned weights inherit the terms of their training data
- Code: transformers (Apache-2.0)
- Training data: RAVDESS (CC BY-NC-SA 4.0), TESS (CC BY-NC-ND 4.0) and SAVEE (research use)
- Independence: vendor community fine-tune; architecture wav2vec2-large XLSR-53 classifier; training data acted English emotion corpora; label lineage actor emotion labels; correlated with the generator's lab: no.
- Sources: <https://huggingface.co/firdhokk/speech-emotion-recognition-with-facebook-wav2vec2-large-xlsr-53>, <https://zenodo.org/records/1188976>

## Pins

- `firdhokk/speech-emotion-recognition-with-facebook-wav2vec2-large-xlsr-53` at revision `611e6db8ee667aa07fe66596f9fc761e036ff5b9`.
- Digest status: `unpinned-retired`.
- Verification: Retired: no QC path loads it. It loaded by revision with no file digest (AQ-F04).

## Execution

- Resources: canonical-host peak -; admission ceiling - (provisional); policy: retired.
- Ceiling basis: Retired; about 1.3 GB fp32 weights on CPU, unsupervised.
- Output identity: repository, revision, labelSet, resampler. Envelope identity: peakRSSBytes.
- Legacy identifiers: evaluatorLayers: ser; cascadeLayers: legacy-ser-during-bakeoff; reportFields: emotionAdvisory, ser; sources: scripts/emotion_advisory.py.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- No canary record.

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Audit section 2.1](../../../audits/2026-09-25-audio-qc-speech-analysis-audit.md#21-license-and-compliance-urgent) and [legacy and orchestration debt](../../audio-qc-engineering.md#legacy-and-orchestration-debt): why it left every QC path; the validators that read its legacy records stay.
