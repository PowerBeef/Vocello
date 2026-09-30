# `asr.sensevoice-small-f16@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `asr.sensevoice-small-f16@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Secondary content voter for ja and ko (audit section 4.1), replacing the q8 compact representation: the f16 GGUF on the pinned llama.cpp runtime.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `shadow` | legacy-unqualified | neural | sensevoice | yes | no | 2 (cpu) | D0 (expected D0) |

`shadow`: Runs beside the current judges; its verdicts are uncalibrated and never block.

**Languages.** secondary: ja, ko.

**Audit section.** 4.1.

## Provenance

- License tier **A** (vendor-declared-undisclosed): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: Apache-2.0 (GGUF model card); upstream weights keep FunASR Model License v1.1 attribution and model-name obligations
- Code: The pinned QwenAudio/SenseVoice llama.cpp runtime release, under the terms published with it
- Training data: More than 400,000 hours across more than 50 languages (vendor-declared; composition undisclosed)
- Tier basis: audit section 4.1: A, with notices
- Notices: FunASR Model License v1.1: attribution and model-name obligations
- Independence: vendor Alibaba Tongyi Lab (FunAudioLLM); architecture SenseVoice Small: SAN-M encoder with CTC, f16 GGUF; training data SenseVoice multilingual corpus; label lineage vendor-internal; correlated with the generator's lab: no.
- Correlation: The same company as Paraformer and as the generator's lab, but a different lab; counts toward the error-correlation audit before any consensus gates.
- Sources: <https://huggingface.co/FunAudioLLM/SenseVoiceSmall-GGUF>, <https://github.com/FunAudioLLM/SenseVoice>

## Pins

- `FunAudioLLM/SenseVoiceSmall-GGUF` at revision `90c1c61912018b70ada0fcc024ea24aca62f2e63`.
- Digest status: `content-addressed-snapshot`.
- Verification: scripts/acquire_audio_qc_judges.py fetches exactly these files at the pinned revision into the owned model root, refusing any size or digest mismatch; before every load the worker verifies the snapshot directory holds exactly these files, each matching its pin (verify_judge_snapshot), and refuses an excluded runtime package. Nothing is downloaded at load time.
- Runtime: release QwenAudio/SenseVoice:runtime-llamacpp-v0.1.9.
- `filesSource`: The Hugging Face tree metadata of the pinned revision (read 2026-09-26, no download): the LFS SHA-256 of each large file and the git blob ID of every other file, with its size. Only the f16 GGUF and the card are pinned and fetched: the q8 file stays compact.sensevoice-small-q8@1's and the f32 file is not used.

| File | Bytes | Digest |
|---|---|---|
| `README.md` | 2500 | git blob `02b2849ff7a26a43` |
| `sensevoice-small-f16.gguf` | 470197600 | LFS SHA-256 `2389039651f4574d` |

## Execution

- Stage 2; lane cpu; engine sensevoice-llamacpp; device cpu; threads 2 (provisional); batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment
- Note: The native binary reads no thread flag, so its own default on the recorded host applies (hostProfile is output identity), and it reloads its model on every invocation.
- Decode options: backend="cpu", keepTags=true, languageLock="unavailable", inverseTextNormalization="runtime-default", note="The pinned runtime's command line (-m, -a, --vad, --backend, --ids, --keep-tags) has no language, ITN or thread option, so the audit's ja/ko lock and use_itn=False cannot be set: the judge keeps the emitted language and ITN tags, and a take whose emitted language differs from the expected one abstains rather than being re-scored."
- Acquisition: directory="sensevoice-small-f16-gguf", stage=1, runtime="sensevoice-llamacpp"
- Resources: canonical-host peak 0.53 GiB; admission ceiling 0.64 GiB (calibrated), measured in session 20260927-70e86ea6; policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: Audit section 3.4 CPU-lane estimate (under 1 GB resident, section 4.1); provisional until two clean M6 runs measure its peak.
- `ceilingHistory`: [{"canonicalHostPeakBytes": 523239424, "ceilingBytes": 627887309, "ceilingSession": "20260927-aaba14fd", "date": "2026-09-27"}]
- Output identity: repository, revision, snapshotFileDigests, binarySHA256, runtimeDependencies, commandTemplate, workerSourceSHA256, engine, decodeOptions, preprocessing, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- Canary record: [benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/asr.sensevoice-small-f16-v1.json](../../../../benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/asr.sensevoice-small-f16-v1.json) (2026-09-27), output identity `4002df42e2a6ed63`.
- Canary qualification passed: yes; determinism D0 over 5 rows (5 bit-exact, 0 discrete mismatches); peak 0.49 GiB on mac-mini-m6-16gb (session 20260927-aaba14fd).

Its accuracy is claimed only through the detectors that consume it:

| Detector | Class | Languages | Reads | Qualification |
|---|---|---|---|---|
| [`content.consensus-error@1`](../detectors/content.consensus-error-v1.md) | B (content) | japanese, korean | panel `errorRate` | refused |
| [`boundary.truncation@1`](../detectors/boundary.truncation-v1.md) | C (boundary) | japanese, korean | transcript-tail `trailingUnmatchedFraction` | qualified (warn) |
| [`boundary.run-on@1`](../detectors/boundary.run-on-v1.md) | C (boundary) | japanese | must complete | refused |
| [`boundary.run-on@2`](../detectors/boundary.run-on-v2.md) | C (boundary) | japanese | must complete | not qualified |
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Judge panel acquisition](../../audio-qc-engineering.md#judge-panel-acquisition-aq-06-prepared-2026-09-26) and [panel jobs and qualification](../../audio-qc-engineering.md#panel-jobs-and-qualification-aq-06-p8-tooling-2026-09-27): how a panel judge is fetched, run under admission and canaried.
