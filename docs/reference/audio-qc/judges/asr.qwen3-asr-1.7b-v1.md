# `asr.qwen3-asr-1.7b@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `asr.qwen3-asr-1.7b@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Adjudicator, non-voting (decision 3a; audit sections 4.1 and 4.2): transcribes inconclusive rows only and may corroborate a fail as diagnostic-corroborated, never turn a disagreement into a pass; a language=None pass is its language-ID adjudication.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `shadow` | legacy-unqualified | neural | qwen3-asr | no | no | 2 (gpu) | D0 (expected D1) |

`shadow`: Runs beside the current judges; its verdicts are uncalibrated and never block.

**Languages.** adjudicates: en, de, fr, es, it, pt, ru, zh, ja, ko.

**Audit section.** 4.1, 4.2.

## Provenance

- License tier **A** (vendor-declared-undisclosed): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: Apache-2.0 (Qwen card and the mlx-community conversion card)
- Code: MIT (mlx-audio)
- Training data: Vendor-declared multilingual ASR data (Qwen3-ASR technical report); composition undisclosed
- Tier basis: audit section 4.1: A
- Independence: vendor Alibaba Qwen (weights); mlx-community (conversion); architecture Qwen3-ASR 1.7B audio-language model, bf16; training data Qwen3-ASR corpus; label lineage vendor-internal; correlated with the generator's lab: yes.
- Correlation: The generator's own lab (Qwen3-TTS): it never votes and never provides labels (decision 3a).
- Sources: <https://huggingface.co/mlx-community/Qwen3-ASR-1.7B-bf16>, <https://huggingface.co/Qwen/Qwen3-ASR-1.7B>, <https://arxiv.org/html/2601.21337v1>

## Pins

- `mlx-community/Qwen3-ASR-1.7B-bf16` at revision `e1f6c266914abc5a46e8756e02580f834a6cf8a7`.
- Digest status: `content-addressed-snapshot`.
- Verification: scripts/acquire_audio_qc_judges.py fetches exactly these files at the pinned revision into the owned model root, refusing any size or digest mismatch; before every load the worker verifies the snapshot directory holds exactly these files, each matching its pin (verify_judge_snapshot), and refuses an excluded runtime package. Nothing is downloaded at load time.
- Runtime: mlx 0.32.0, mlx-audio 0.5.6, numpy 2.4.6, transformers 5.17.0.
- `filesSource`: The Hugging Face tree metadata of the pinned revision (read 2026-09-26, no download): the LFS SHA-256 of each large file and the git blob ID of every other file, with its size. Every file of the revision is pinned and fetched.
- `upstream`: repository="Qwen/Qwen3-ASR-1.7B", revision="7278e1e70fe206f11671096ffdd38061171dd6e5"

| File | Bytes | Digest |
|---|---|---|
| `.gitattributes` | 1519 | git blob `a6344aac8c09253b` |
| `README.md` | 1008 | git blob `71c41cef2dfed48e` |
| `chat_template.json` | 1161 | git blob `c44736493efd71ec` |
| `config.json` | 6983 | git blob `37b6178034956463` |
| `generation_config.json` | 142 | git blob `7382a4d347c0a865` |
| `merges.txt` | 1671853 | git blob `31349551d90c7606` |
| `model.safetensors` | 4076186653 | LFS SHA-256 `2f080a3b769ae469` |
| `model.safetensors.index.json` | 51384 | git blob `0ed946ae9d91b091` |
| `preprocessor_config.json` | 330 | git blob `8f7f07346466d5d4` |
| `tokenizer_config.json` | 12487 | git blob `b93109843922a40c` |
| `vocab.json` | 2776833 | git blob `4783fe10ac3adce1` |

## Execution

- Stage 2; lane gpu; engine qwen3-asr-mlx; device mlx-gpu; threads 2 (provisional); batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment
- Decode options: decoding="greedy", context=null, languageLock="expected-language", languageDetectionPass="language=None"
- Acquisition: directory="qwen3-asr-1.7b-bf16-mlx", stage=2, runtime="mlx-audio"
- Resources: canonical-host peak 5.43 GiB; admission ceiling 6.52 GiB (calibrated), measured in session 20260927-aaba14fd; policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: Audit section 3.4 GPU-lane estimate (3.5-4 GB resident, section 4.1); admitted only beside CPU judges of 2.5 GB or less; provisional until two clean M6 runs measure its peak.
- Output identity: repository, revision, snapshotFileDigests, runtimeDependenciesDigest, runtimeVersions, workerSourceSHA256, engine, decodeOptions, lockedLanguage, preprocessing, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- Canary record: [benchmarks/audio-qc-qualification/20261001-505107fc/judges/asr.qwen3-asr-1.7b-v1.json](../../../../benchmarks/audio-qc-qualification/20261001-505107fc/judges/asr.qwen3-asr-1.7b-v1.json) (2026-10-01), output identity `f208db7b42e430aa`.
- Re-cited after its output identity changed; replaced canary records: [benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/asr.qwen3-asr-1.7b-v1.json](../../../../benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/asr.qwen3-asr-1.7b-v1.json) (2026-09-27, output identity `7a23e1253d6171c9`).
- Canary qualification passed: yes; determinism D0 over 9 rows (9 bit-exact, 0 discrete mismatches); peak 4.84 GiB on mac-mini-m6-16gb (session 20261001-505107fc).

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Judge panel acquisition](../../audio-qc-engineering.md#judge-panel-acquisition-aq-06-prepared-2026-09-26) and [panel jobs and qualification](../../audio-qc-engineering.md#panel-jobs-and-qualification-aq-06-p8-tooling-2026-09-27): how a panel judge is fetched, run under admission and canaried.
