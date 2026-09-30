# `compact.sensevoice-small-q8@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `compact.sensevoice-small-q8@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Compact research representation in the delivery cascade: coarse language, emotion and event tags plus a transcript.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `candidate` | legacy-unqualified | neural | - | no | no | 2 (cpu) | unmeasured |

`candidate`: Registered with pins, a tier and independence fields; research use only.

## Provenance

- License tier **A** (vendor-declared-undisclosed): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: Apache-2.0 (GGUF model card); upstream weights keep FunASR Model License v1.1 attribution and model-name obligations
- Code: The pinned QwenAudio/SenseVoice llama.cpp runtime release, under the terms published with it
- Training data: More than 400,000 hours across more than 50 languages (vendor-declared; composition undisclosed)
- Tier basis: audit section 4.1: A, with notices
- Notices: FunASR Model License v1.1: attribution and model-name obligations
- Independence: vendor Alibaba Tongyi Lab (FunAudioLLM); architecture non-autoregressive encoder (SenseVoice Small), Q8 GGUF; training data SenseVoice multilingual corpus; label lineage vendor-internal; correlated with the generator's lab: no.
- Correlation: Same company as the generator's lab and as Paraformer; a different lab. Counts toward the error-correlation audit before any consensus gates.
- Sources: <https://github.com/FunAudioLLM/SenseVoice>, <https://huggingface.co/FunAudioLLM/SenseVoiceSmall-GGUF>

## Pins

- `FunAudioLLM/SenseVoiceSmall-GGUF` at revision `90c1c61912018b70ada0fcc024ea24aca62f2e63`.
- Digest status: `pinned`.
- Verification: prepare_delivery_compact_model_config.py verifies weights, runtime archive and binary; the adapter re-verifies weights and binary before each launch.
- Runtime: release QwenAudio/SenseVoice:runtime-llamacpp-v0.1.9.
- Execution registry: `config/delivery-evaluator-v2-candidates.json#sensevoice-small-q8`.

| File | Bytes | Digest |
|---|---|---|
| `funasr-llamacpp-macos-arm64.tar.gz` | - | SHA-256 `2d5786784ad09d8f` |
| `llama-funasr-sensevoice` | - | SHA-256 `49d66b2f79d439e2` |
| `sensevoice-small-q8.gguf` | - | SHA-256 `4ae45c94422de949` |

## Execution

- Stage 2; lane cpu; engine native-command; device cpu; threads 2; batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment (OMP and BLAS variables); the pinned native binary reads no thread flag the harness has verified, so its own default on the recorded host applies (hostProfile is output identity)
- Note: The native binary loads its model on every invocation; the persistent worker makes supervision and admission per run, not the model load.
- Resources: canonical-host peak -; admission ceiling 5.00 GiB (provisional); policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: The shared provisional compact-adapter ceiling, set for the 8 GB floor before any canonical-host measurement (AQ-F43).
- Output identity: adapterID, modelID, sourceRevision, weightsSHA256, binarySHA256, adapterSourceSHA256, adapterLayerSHA256, commandTemplate, runtimeDependenciesDigest, labelMapDigest, outputFormat, preprocessingConfigDigest, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
- Legacy identifiers: adapterIDs: sensevoice-small-q8; modelFamilies: sensevoice; cascadeLayers: coarse-ser-asr.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- No canary record.

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Legacy and orchestration debt](../../audio-qc-engineering.md#legacy-and-orchestration-debt): the delivery research cascade it belongs to. The panel's SenseVoice voter is a separate judge, [`asr.sensevoice-small-f16@1`](asr.sensevoice-small-f16-v1.md).
