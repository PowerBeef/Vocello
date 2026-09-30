# `align.qwen3-forcedaligner-0.6b@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `align.qwen3-forcedaligner-0.6b@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Timing instrument, non-voting (decision 3a; audit section 4.1): word intervals for alphabetic languages and character intervals for zh and ja, whitespace eojeol for ko (no soynlp), supplied only to class B, C and F detectors that already have content consensus.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `shadow` | legacy-unqualified | neural | qwen3-aligner | no | no | 2 (gpu) | D0 (expected D1) |

`shadow`: Runs beside the current judges; its verdicts are uncalibrated and never block.

**Languages.** aligns: en, de, fr, es, it, pt, ru, zh, ja.

**Audit section.** 4.1.

**Scope.** Korean is out of scope: mlx-audio tokenizes it with soynlp (GPL-3.0), which the exclusion list refuses.

## Provenance

- License tier **A** (vendor-declared-undisclosed): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: Apache-2.0 (Qwen card and the mlx-community conversion card)
- Code: MIT (mlx-audio)
- Training data: Vendor-declared alignment data (Qwen3-ASR technical report); composition undisclosed
- Tier basis: audit section 4.1: A
- Independence: vendor Alibaba Qwen (weights); mlx-community (conversion); architecture Qwen3-ForcedAligner 0.6B, bf16; training data Qwen3-ASR alignment corpus; label lineage vendor-internal; correlated with the generator's lab: yes.
- Correlation: The generator's own lab: it supplies intervals only, never a vote or a label (decision 3a).
- Sources: <https://huggingface.co/mlx-community/Qwen3-ForcedAligner-0.6B-bf16>, <https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B>

## Pins

- `mlx-community/Qwen3-ForcedAligner-0.6B-bf16` at revision `53c8c0e46733eec430e4b53dd6471d0e5dee45f8`.
- Digest status: `content-addressed-snapshot`.
- Verification: scripts/acquire_audio_qc_judges.py fetches exactly these files at the pinned revision into the owned model root, refusing any size or digest mismatch; before every load the worker verifies the snapshot directory holds exactly these files, each matching its pin (verify_judge_snapshot), and refuses an excluded runtime package. Nothing is downloaded at load time.
- Runtime: mlx 0.32.0, mlx-audio 0.5.6, numpy 2.4.6, transformers 5.17.0.
- `filesSource`: The Hugging Face tree metadata of the pinned revision (read 2026-09-26, no download): the LFS SHA-256 of each large file and the git blob ID of every other file, with its size. Every file of the revision is pinned and fetched.
- `upstream`: repository="Qwen/Qwen3-ForcedAligner-0.6B", revision="c7cbfc2048c462b0d63a45797104fc9db3ad62b7"

| File | Bytes | Digest |
|---|---|---|
| `.gitattributes` | 1519 | git blob `a6344aac8c09253b` |
| `README.md` | 1068 | git blob `9956259fa50a8bfa` |
| `chat_template.json` | 1161 | git blob `c44736493efd71ec` |
| `config.json` | 6735 | git blob `d37a92d4b3792df0` |
| `generation_config.json` | 115 | git blob `b0a540032cf7b6b5` |
| `merges.txt` | 1671853 | git blob `31349551d90c7606` |
| `model.safetensors` | 1835539240 | LFS SHA-256 `9d0728e17e28ee12` |
| `model.safetensors.index.json` | 51430 | git blob `31f1561137d88a00` |
| `preprocessor_config.json` | 330 | git blob `8f7f07346466d5d4` |
| `tokenizer_config.json` | 12666 | git blob `3df92df83b22342e` |
| `vocab.json` | 2776833 | git blob `4783fe10ac3adce1` |

## Execution

- Stage 2; lane gpu; engine qwen3-aligner-mlx; device mlx-gpu; threads 2 (provisional); batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment
- Decode options: {"language": "explicit", "units": {"alphabetic": "word", "ja": "character", "ko": "whitespace-eojeol", "zh": "character"}}
- Acquisition: directory="qwen3-forcedaligner-0.6b-bf16-mlx", stage=2, runtime="mlx-audio-aligner"
- Resources: canonical-host peak 3.91 GiB; admission ceiling 4.69 GiB (calibrated), measured in session 20260927-aaba14fd; policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: Audit section 3.4 GPU-lane estimate (2-2.4 GB resident, section 4.1); provisional until two clean M6 runs measure its peak.
- Output identity: repository, revision, snapshotFileDigests, runtimeDependenciesDigest, runtimeVersions, workerSourceSHA256, engine, decodeOptions, lockedLanguage, preprocessing, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- Canary record: [benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/align.qwen3-forcedaligner-0.6b-v1.json](../../../../benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/align.qwen3-forcedaligner-0.6b-v1.json) (2026-09-27), output identity `b50cc9cd7a8adf9a`.
- Canary qualification passed: yes; determinism D0 over 24 rows (24 bit-exact, 0 discrete mismatches); peak 3.91 GiB on mac-mini-m6-16gb (session 20260927-aaba14fd).

Its accuracy is claimed only through the detectors that consume it:

| Detector | Class | Languages | Reads | Qualification |
|---|---|---|---|---|
| [`boundary.run-on@1`](../detectors/boundary.run-on-v1.md) | C (boundary) | english, french, german, italian, portuguese, russian, spanish, chinese, japanese | panel `spanEndSeconds` | refused |

**UNQUALIFIED.** No committed calibration record qualifies a detector that consumes this judge, so every verdict built on it composes as `uncalibrated`.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Judge panel acquisition](../../audio-qc-engineering.md#judge-panel-acquisition-aq-06-prepared-2026-09-26) and [panel jobs and qualification](../../audio-qc-engineering.md#panel-jobs-and-qualification-aq-06-p8-tooling-2026-09-27): how a panel judge is fetched, run under admission and canaried.
