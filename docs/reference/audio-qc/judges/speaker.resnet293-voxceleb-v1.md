# `speaker.resnet293-voxceleb@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `speaker.resnet293-voxceleb@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Speaker-identity family 2 (audit section 4.3): a second architecture on the same VoxCeleb data, replacing the excluded WavLM-large SV checkpoint.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `shadow` | legacy-unqualified | neural | speaker-resnet293 | no | no | 2 (cpu) | D0 (expected D0) |

`shadow`: Runs beside the current judges; its verdicts are uncalibrated and never block.

**Audit section.** 4.3.

**Voting gate (pending).** The correlated-failure audit (audit section 5) against CAM++, which shares its VoxCeleb training data. Until it passes, ResNet293 runs as a non-voting candidate; it votes only after that audit, jointly with CAM++.

## Provenance

- License tier **B** (scraped-web-audio): Permissive weights, but training data includes scraped web audio or corpora whose rights stay with the original owners, with no explicit non-commercial term. Internal, never-shipped evaluation only (decision 2a). Commercial use compatible: yes.
- Weights: CC BY 4.0 (Hugging Face card at the pinned revision; accepted by the maintainer decision of 2026-09-26, where the audit recorded Apache-2.0)
- Code: Apache-2.0 (WeSpeaker export); the feature and embedding code is owned
- Training data: VoxCeleb 2 development set (5,994 speakers): YouTube-derived celebrity speech; copyright stays with the owners; no explicit non-commercial term
- Notices: CC BY 4.0 attribution: WeSpeaker ResNet293-LM (wenet-e2e/wespeaker; Wang et al., ICASSP 2023), trained on VoxCeleb (Nagrani et al.; CC BY 4.0, copyright of the audio stays with the original owners). Internal evaluation only; never shipped or redistributed.
- Tier-B acceptance: decision 2a (2026-09-25), scope `internal-never-shipped-evaluation`.
- License decision (2026-09-26, AQ-06): The maintainer accepts the CC BY 4.0 license the model card declares at the pinned revision (the audit, section 4.3, had recorded Apache-2.0). The tier stays B: internal evaluation only, never shipped (decision 2a). The quarantine of 2026-09-26 is lifted.
- Attribution: CC BY 4.0: WeSpeaker ResNet293-LM (wenet-e2e/wespeaker), trained on VoxCeleb
- Independence: vendor WeSpeaker (wenet-e2e); architecture ResNet293 r-vector (256-dimensional, large-margin fine-tuned), ONNX; training data VoxCeleb; label lineage speaker identity labels; correlated with the generator's lab: no.
- Correlation: The same VoxCeleb training data as CAM++; the correlated-failure audit must pass before the two vote jointly (audit section 4.3).
- Sources: <https://huggingface.co/Wespeaker/wespeaker-voxceleb-resnet293-LM>, <https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md>

## Pins

- `Wespeaker/wespeaker-voxceleb-resnet293-LM` at revision `6e6bffe5bf3d772a1f143dc6dbfea58a0799ea83`.
- Digest status: `content-addressed-snapshot`.
- Verification: scripts/acquire_audio_qc_judges.py fetches exactly these files at the pinned revision into the owned model root, refusing any size or digest mismatch; before every load the worker verifies the snapshot directory holds exactly these files, each matching its pin (verify_judge_snapshot), and refuses an excluded runtime package. Nothing is downloaded at load time.
- Runtime: kaldi-native-fbank 1.22.3, numpy 2.4.6, onnxruntime 1.30.0.
- `filesSource`: The Hugging Face tree metadata of the pinned revision (read 2026-09-26, no download): the LFS SHA-256 of each large file and the git blob ID of every other file, with its size. Only the ONNX export, its training config and the card are pinned; the PyTorch checkpoint (avg_model.pt) is not used.

| File | Bytes | Digest |
|---|---|---|
| `README.md` | 2893 | git blob `4ef54d5fa65e3405` |
| `config.yaml` | 1538 | git blob `4366128f5c5be8f7` |
| `voxceleb_resnet293_LM.onnx` | 114336285 | LFS SHA-256 `dbb1ccc7754caff5` |

## Execution

- Stage 2; lane cpu; engine wespeaker-onnx; device cpu; threads 2 (provisional); batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment
- Preprocessing: {"features": "kaldi fbank: 80 mel bins, 25 ms frames, 10 ms shift, hamming window, dither 0, snip edges, int16-scaled samples, per-utterance mean normalization", "windows": {"hopSeconds": 0.5, "seconds": 2.0}}
- Acquisition: directory="wespeaker-voxceleb-resnet293-lm", stage=2, runtime="onnx-cpu"
- Resources: canonical-host peak 1.14 GiB; admission ceiling 1.36 GiB (calibrated), measured in session 20260927-aaba14fd; policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: Audit estimate about 0.3 GB (section 3.4), raised to 512 MiB for the interpreter and ONNX Runtime; provisional until two clean M6 runs measure its peak.
- Output identity: repository, revision, snapshotFileDigests, runtimeDependenciesDigest, runtimeVersions, workerSourceSHA256, engine, preprocessing, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- Canary record: [benchmarks/audio-qc-qualification/20261001-505107fc/judges/speaker.resnet293-voxceleb-v1.json](../../../../benchmarks/audio-qc-qualification/20261001-505107fc/judges/speaker.resnet293-voxceleb-v1.json) (2026-10-01), output identity `afc541ed3ee2ff54`.
- Re-cited after its output identity changed; replaced canary records: [benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/speaker.resnet293-voxceleb-v1.json](../../../../benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/speaker.resnet293-voxceleb-v1.json) (2026-09-27, output identity `91f85e1da05aedc0`).
- Canary qualification passed: yes; determinism D0 over 12 rows (12 bit-exact, 0 discrete mismatches); peak 0.37 GiB on mac-mini-m6-16gb (session 20261001-505107fc).

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Judge panel acquisition](../../audio-qc-engineering.md#judge-panel-acquisition-aq-06-prepared-2026-09-26) and [panel jobs and qualification](../../audio-qc-engineering.md#panel-jobs-and-qualification-aq-06-p8-tooling-2026-09-27): how a panel judge is fetched, run under admission and canaried.
