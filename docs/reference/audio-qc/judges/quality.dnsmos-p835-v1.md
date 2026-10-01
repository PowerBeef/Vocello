# `quality.dnsmos-p835@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `quality.dnsmos-p835@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Secondary advisory quality screen (audit section 4.6): DNSMOS P.835 SIG, BAK and OVRL (and the P.808 MOS its reference script reports), a screen, not a naturalness judge; never reaches warn.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `shadow` | legacy-unqualified | neural | - | no | no | 2 (cpu) | D0 (expected D0) |

`shadow`: Runs beside the current judges; its verdicts are uncalibrated and never block.

**Audit section.** 4.6.

## Provenance

- License tier **B** (scraped-web-audio): Permissive weights, but training data includes scraped web audio or corpora whose rights stay with the original owners, with no explicit non-commercial term. Internal, never-shipped evaluation only (decision 2a). Commercial use compatible: yes.
- Weights: CC BY 4.0 (microsoft/DNS-Challenge LICENSE at the pinned commit, which covers the repository's content, the DNSMOS ONNX models included)
- Code: MIT (microsoft/DNS-Challenge LICENSE-CODE) for dnsmos_local.py, whose scoring the owned engine ports with credit
- Training data: Crowdsourced ITU-T P.835 ratings (Microsoft) of noisy and noise-suppressed DNS Challenge clips; the repository lists the challenge corpora under their original terms: LibriVox (public domain), PTDB-TUG (ODbL), Edinburgh 56 speakers and VCTK (ODC-By), VocalSet (CC BY 4.0), CREMA-D (DbCL), VoxCeleb2 (CC BY 4.0, copyright with the video owners), AudioSet (CC BY 4.0), Freesound (CC0 only), DEMAND (CC BY-SA 3.0) and OpenSLR 26/28 (Apache-2.0); no explicit non-commercial term
- Tier basis: The audit (section 4.6) rated DNSMOS A with its training-data terms still to confirm. Confirmed at acquisition: the weights are CC BY 4.0, but the corpora its ratings were collected on include VoxCeleb2, YouTube-derived audio whose copyright stays with the owners, which this registry places in tier B for every judge. Internal evaluation only (decision 2a).
- Notices: CC BY 4.0 attribution: Microsoft DNSMOS P.835 (microsoft/DNS-Challenge; C. K. A. Reddy, V. Gopal and R. Cutler, ICASSP 2022). Internal evaluation only; never shipped or redistributed., MIT: the DNSMOS scoring in scripts/lib/qc_pipeline/panel_engines.py is ported from microsoft/DNS-Challenge DNSMOS/dnsmos_local.py, Copyright (c) Microsoft Corporation.
- Tier-B acceptance: decision 2a (2026-09-25), scope `internal-never-shipped-evaluation`.
- License decision (2026-09-26, AQ-06): The maintainer accepts DNSMOS P.835 as an advisory, non-voting screen under the CC BY 4.0 license of microsoft/DNS-Challenge, fetched from that repository at the pinned commit. It leaves acquisitionBlocked.
- Attribution: CC BY 4.0: Microsoft DNSMOS P.835 (microsoft/DNS-Challenge; Reddy, Gopal and Cutler, ICASSP 2022); the owned engine ports dnsmos_local.py (MIT, Copyright (c) Microsoft Corporation)
- Independence: vendor Microsoft Research (DNS Challenge); architecture DNSMOS P.835 convolutional regressor on the raw 16 kHz waveform (9.01 s windows), plus the P.808 model on 120-bin log-mel features; training data DNS Challenge P.835 crowdsourced ratings; label lineage human ITU-T P.835 ratings of noise-suppression output; correlated with the generator's lab: no.
- Correlation: Trained on noise-suppression conditions, not TTS; a relative screen whose SIG and BAK read noise and suppression artifacts, not naturalness (audit section 4.6).
- Sources: <https://github.com/microsoft/DNS-Challenge/tree/591184a9fcb2cbdec02520fed81a32bbbf9d73ff/DNSMOS>, <https://arxiv.org/abs/2110.01763>

## Pins

- `microsoft/DNS-Challenge` at revision `591184a9fcb2cbdec02520fed81a32bbbf9d73ff`.
- Digest status: `content-addressed-snapshot`.
- Verification: scripts/acquire_audio_qc_judges.py fetches exactly these files from raw.githubusercontent.com at the pinned commit into the owned model root, refusing any size, SHA-256 or git blob mismatch; before every load the worker verifies the snapshot directory holds exactly these files, each matching its pin (verify_judge_snapshot), and refuses an excluded runtime package. Nothing is downloaded at load time.
- Runtime: librosa 0.11.0, numba 0.67.0, numpy 2.4.6, onnxruntime 1.30.0, scipy 1.18.1.
- `source`: github
- `filesSource`: The GitHub contents API at the pinned commit (read 2026-09-26): each file's path, size and git blob ID. Both files are small and not in LFS; each was fetched once into a temporary directory to record its content SHA-256, its bytes matching the blob ID, and deleted. Only the regular P.835 model and the P.808 model are pinned; sig.onnx, bak_ovr.onnx and the personalized pDNSMOS model are not used.
- `sourceScript`: path="DNSMOS/dnsmos_local.py", gitBlobID="e32032e97541fde9a98fdc12745d5c1e09e5c7f1", size=6491, portedTo="scripts/lib/qc_pipeline/panel_engines.py (DnsmosScorer)"

| File | Bytes | Digest |
|---|---|---|
| `DNSMOS/DNSMOS/model_v8.onnx` | 224860 | SHA-256 `9246480c58567bc6` |
| `DNSMOS/DNSMOS/sig_bak_ovr.onnx` | 1157965 | SHA-256 `269fbebdb513aa23` |

## Execution

- Stage 2; lane cpu; engine dnsmos-onnx; device cpu; threads 1 (provisional); batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment
- Configuration: {"aggregate": "mean over scored windows", "calibration": {"BAK": [-0.13166888, 1.60915514, -0.39604546], "OVRL": [-0.06766283, 1.11546468, 0.04602535], "SIG": [-0.08397278, 1.22083953, 0.0052439]}, "hopSeconds": 1.0, "inputLengthSeconds": 9.01, "p808": {"hopLength": 160, "nFft": 321, "nMels": 120, "padMode": "reflect", "toDb": "power_to_db(ref=max), then (x + 40) / 40", "trimSamples": 160}, "p808Model": "DNSMOS/DNSMOS/model_v8.onnx", "personalized": false, "primaryModel": "DNSMOS/DNSMOS/sig_bak_ovr.onnx", "sampleRateHz": 16000}
- Acquisition: directory="dnsmos-p835", stage=2, runtime="onnx-librosa"
- Resources: canonical-host peak 0.47 GiB; admission ceiling 0.57 GiB (calibrated), measured in session 20260927-aaba14fd; policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: Audit section 4.6 estimate (about 0.25 GB), raised to 768 MiB for the interpreter, ONNX Runtime, librosa and numba; provisional until two clean M6 runs measure its peak.
- Output identity: repository, revision, snapshotFileDigests, runtimeDependenciesDigest, runtimeVersions, workerSourceSHA256, engine, configuration, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- Canary record: [benchmarks/audio-qc-qualification/20261001-505107fc/judges/quality.dnsmos-p835-v1.json](../../../../benchmarks/audio-qc-qualification/20261001-505107fc/judges/quality.dnsmos-p835-v1.json) (2026-10-01), output identity `bda9cb3bed22b982`.
- Re-cited after its output identity changed; replaced canary records: [benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/quality.dnsmos-p835-v1.json](../../../../benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/quality.dnsmos-p835-v1.json) (2026-09-27, output identity `461fbe8a780bf3e1`).
- Canary qualification passed: yes; determinism D0 over 9 rows (9 bit-exact, 0 discrete mismatches); peak 0.46 GiB on mac-mini-m6-16gb (session 20261001-505107fc).

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Judge panel acquisition](../../audio-qc-engineering.md#judge-panel-acquisition-aq-06-prepared-2026-09-26) and [panel jobs and qualification](../../audio-qc-engineering.md#panel-jobs-and-qualification-aq-06-p8-tooling-2026-09-27): how a panel judge is fetched, run under admission and canaried.
