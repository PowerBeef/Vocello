# `speaker.campplus-voxceleb@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `speaker.campplus-voxceleb@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Speaker-identity family 1 (audit section 4.3): whole-take and windowed (2 s, 0.5 s hop) embeddings for clone identity and drift; it fails a take only jointly with family 2, once both are calibrated.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `shadow` | legacy-unqualified | neural | speaker-campplus | yes | no | 2 (cpu) | D0 (expected D0) |

`shadow`: Runs beside the current judges; its verdicts are uncalibrated and never block.

**Audit section.** 4.3.

## Provenance

- License tier **B** (scraped-web-audio): Permissive weights, but training data includes scraped web audio or corpora whose rights stay with the original owners, with no explicit non-commercial term. Internal, never-shipped evaluation only (decision 2a). Commercial use compatible: yes.
- Weights: Apache-2.0 (Hugging Face card); WeSpeaker's pretrained-model notes say VoxCeleb-trained models follow the dataset's CC BY 4.0
- Code: Apache-2.0 (WeSpeaker export); the feature and embedding code is owned
- Training data: VoxCeleb 1 and 2: YouTube-derived celebrity speech; copyright stays with the owners; no explicit non-commercial term
- Tier-B acceptance: decision 2a (2026-09-25), scope `internal-never-shipped-evaluation`.
- Independence: vendor WeSpeaker (wenet-e2e); architecture CAM++ speaker embedding (512-dimensional, large-margin fine-tuned), ONNX; training data VoxCeleb; label lineage speaker identity labels; correlated with the generator's lab: no.
- Correlation: The same VoxCeleb training data as ResNet293 and the legacy ECAPA; the correlated-failure audit must pass before two families vote jointly (audit section 4.3).
- Sources: <https://huggingface.co/Wespeaker/wespeaker-voxceleb-campplus-LM>, <https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md>

## Pins

- `Wespeaker/wespeaker-voxceleb-campplus-LM` at revision `c5e01c6fcffcce160861e7e79782828320192b5c`.
- Digest status: `content-addressed-snapshot`.
- Verification: scripts/acquire_audio_qc_judges.py fetches exactly these files at the pinned revision into the owned model root, refusing any size or digest mismatch; before every load the worker verifies the snapshot directory holds exactly these files, each matching its pin (verify_judge_snapshot), and refuses an excluded runtime package. Nothing is downloaded at load time.
- Runtime: kaldi-native-fbank 1.22.3, numpy 2.4.6, onnxruntime 1.30.0.
- `filesSource`: The Hugging Face tree metadata of the pinned revision (read 2026-09-26, no download): the LFS SHA-256 of each large file and the git blob ID of every other file, with its size. Only the ONNX export, its training config and the card are pinned and fetched; the PyTorch checkpoint (avg_model.pt) is not used.

| File | Bytes | Digest |
|---|---|---|
| `README.md` | 31 | git blob `7b95401dc46245ac` |
| `config.yaml` | 1705 | git blob `8b7af85851bdd195` |
| `voxceleb_CAM++_LM.onnx` | 29292449 | LFS SHA-256 `1068e4ac3a76bb9c` |

## Execution

- Stage 2; lane cpu; engine wespeaker-onnx; device cpu; threads 2 (provisional); batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment
- Preprocessing: {"features": "kaldi fbank: 80 mel bins, 25 ms frames, 10 ms shift, hamming window, dither 0, snip edges, int16-scaled samples, per-utterance mean normalization", "windows": {"hopSeconds": 0.5, "seconds": 2.0}}
- Acquisition: directory="wespeaker-voxceleb-campplus-lm", stage=1, runtime="onnx-cpu"
- Resources: canonical-host peak 0.27 GiB; admission ceiling 0.32 GiB (calibrated), measured in session 20260927-aaba14fd; policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: Audit estimate 0.12-0.2 GB resident (section 4.3), raised to 512 MiB for the interpreter and ONNX Runtime; provisional until two clean M6 runs measure its peak.
- Output identity: repository, revision, snapshotFileDigests, runtimeDependenciesDigest, runtimeVersions, workerSourceSHA256, engine, preprocessing, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- Canary record: [benchmarks/audio-qc-qualification/20261001-72a97eab/judges/speaker.campplus-voxceleb-v1.json](../../../../benchmarks/audio-qc-qualification/20261001-72a97eab/judges/speaker.campplus-voxceleb-v1.json) (2026-10-01), output identity `e9531c63646f0192`.
- Re-cited after its output identity changed; replaced canary records: [benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/speaker.campplus-voxceleb-v1.json](../../../../benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/speaker.campplus-voxceleb-v1.json) (2026-09-27, output identity `567113ff49594c84`).
- Canary qualification passed: yes; determinism D0 over 12 rows (12 bit-exact, 0 discrete mismatches); peak 0.14 GiB on mac-mini-m6-16gb (session 20261001-72a97eab).

Its accuracy is claimed only through the detectors that consume it:

| Detector | Class | Languages | Reads | Qualification |
|---|---|---|---|---|
| [`identity.clone-similarity@1`](../detectors/identity.clone-similarity-v1.md) | E (identity) | chinese, english, french, german, italian, korean, portuguese, spanish | panel `cosine` | qualified (warn) |
| [`identity.window-drift@1`](../detectors/identity.window-drift-v1.md) | E (identity) | chinese, english, french, german, italian, korean, portuguese, spanish | panel `cosine`, panel `windowCosineMinimum` | refused |
| [`identity.onset-drift@1`](../detectors/identity.onset-drift-v1.md) | E (identity) | chinese, english, french, german, italian, korean, portuguese, spanish | panel `cosine`, panel `onsetWindowCosine` | qualified (warn) |
| [`long-form.seam-identity@1`](../detectors/long-form.seam-identity-v1.md) | J (long form) | chinese, english, french, german, italian, japanese, korean, portuguese, russian, spanish | raw-output `seamWindowCosineMinimum` | not qualified |
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Judge panel acquisition](../../audio-qc-engineering.md#judge-panel-acquisition-aq-06-prepared-2026-09-26) and [panel jobs and qualification](../../audio-qc-engineering.md#panel-jobs-and-qualification-aq-06-p8-tooling-2026-09-27): how a panel judge is fetched, run under admission and canaried.
