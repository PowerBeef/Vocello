# `asr.parakeet-tdt-0.6b-v3@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `asr.parakeet-tdt-0.6b-v3@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Secondary literal voter for en, de, fr, es, it, pt and ru (audit section 4.1): a transducer transcript beside Whisper's, which bounds Whisper's hallucination on non-speech.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `shadow` | legacy-unqualified | neural | parakeet | yes | no | 2 (gpu) | D0 (expected D1) |

`shadow`: Runs beside the current judges; its verdicts are uncalibrated and never block.

**Languages.** voter: en, de, fr, es, it, pt, ru.

**Audit section.** 4.1.

## Provenance

- License tier **B** (scraped-web-audio): Permissive weights, but training data includes scraped web audio or corpora whose rights stay with the original owners, with no explicit non-commercial term. Internal, never-shipped evaluation only (decision 2a). Commercial use compatible: yes.
- Weights: CC BY 4.0 (NVIDIA parakeet-tdt-0.6b-v3 and the mlx-community conversion card)
- Code: Apache-2.0 (parakeet-mlx)
- Training data: Granary (YODAS and other scraped web audio) with NVIDIA's ASR sets; rights stay with the original owners; no explicit non-commercial term
- Notices: CC BY 4.0 attribution: NVIDIA, parakeet-tdt-0.6b-v3
- Tier-B acceptance: decision 2a (2026-09-25), scope `internal-never-shipped-evaluation`.
- Independence: vendor NVIDIA (weights); mlx-community (conversion); architecture FastConformer encoder with a token-and-duration transducer decoder, 0.6B parameters; training data Granary multilingual corpus; label lineage Whisper pseudo-labels (Granary); correlated with the generator's lab: no.
- Correlation: Its labels descend from Whisper, so its agreement with Whisper is audited (phi and joint misses) before it gates (AQ-F35).
- Sources: <https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3>, <https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3>, <https://arxiv.org/html/2505.13404v1>

## Pins

- `mlx-community/parakeet-tdt-0.6b-v3` at revision `ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15`.
- Digest status: `content-addressed-snapshot`.
- Verification: scripts/acquire_audio_qc_judges.py fetches exactly these files at the pinned revision into the owned model root, refusing any size or digest mismatch; before every load the worker verifies the snapshot directory holds exactly these files, each matching its pin (verify_judge_snapshot), and refuses an excluded runtime package. Nothing is downloaded at load time.
- Runtime: librosa 0.11.0, mlx 0.32.0, numpy 2.4.6, parakeet-mlx 0.5.2.
- `filesSource`: The Hugging Face tree metadata of the pinned revision (read 2026-09-26, no download): the LFS SHA-256 of each large file and the git blob ID of every other file, with its size. Every file of the revision is pinned and fetched.
- `upstream`: repository="nvidia/parakeet-tdt-0.6b-v3", revision="541d1f99c6b0c3cd0b11a95167540bb8edefd82b", note="The card's base model at its current revision (read 2026-09-26); the conversion predates it and is what is pinned."

| File | Bytes | Digest |
|---|---|---|
| `.gitattributes` | 1519 | git blob `a6344aac8c09253b` |
| `README.md` | 1081 | git blob `2775a7563b1df0f1` |
| `config.json` | 244093 | git blob `4f469c2e92c98186` |
| `model.safetensors` | 2508288736 | LFS SHA-256 `05e01c7f396c298c` |
| `tokenizer.model` | 360916 | LFS SHA-256 `eacec2b0a77f336d` |
| `tokenizer.vocab` | 101024 | git blob `3fa4c819f33b03e8` |
| `vocab.txt` | 46772 | git blob `d2fc51742d86127c` |

## Execution

- Stage 2; lane gpu; engine parakeet-mlx; device mlx-gpu; threads 2 (provisional); batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment
- Decode options: decoding="greedy", dtype="bfloat16", chunking="none", maximumUnchunkedSeconds=120
- Acquisition: directory="parakeet-tdt-0.6b-v3-mlx", stage=1, runtime="parakeet-mlx"
- Resources: canonical-host peak 5.44 GiB; admission ceiling 6.52 GiB (calibrated), measured in session 20260927-70e86ea6; policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: Audit section 3.4 GPU-lane estimate (1.5-2.5 GB resident, section 4.1); provisional until two clean M6 runs measure its peak.
- `ceilingHistory`: [{"canonicalHostPeakBytes": 4507699696, "ceilingBytes": 5409239636, "ceilingSession": "20260927-aaba14fd", "date": "2026-09-27"}]
- Output identity: repository, revision, snapshotFileDigests, runtimeDependenciesDigest, runtimeVersions, workerSourceSHA256, engine, decodeOptions, preprocessing, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- Canary record: [benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/asr.parakeet-tdt-0.6b-v3-v1.json](../../../../benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/asr.parakeet-tdt-0.6b-v3-v1.json) (2026-09-27), output identity `c42785b420fbb3fc`.
- Canary qualification passed: yes; determinism D0 over 19 rows (19 bit-exact, 0 discrete mismatches); peak 4.20 GiB on mac-mini-m6-16gb (session 20260927-aaba14fd).

Its accuracy is claimed only through the detectors that consume it:

| Detector | Class | Languages | Reads | Qualification |
|---|---|---|---|---|
| [`content.consensus-error@1`](../detectors/content.consensus-error-v1.md) | B (content) | english, french, german, italian, portuguese, russian, spanish | panel `errorRate` | refused |
| [`content.consensus-error@2`](../detectors/content.consensus-error-v2.md) | B (content) | english, french, german, italian, portuguese, russian, spanish | transcript-edit `insertionDeletionRate` | not qualified |
| [`boundary.truncation@1`](../detectors/boundary.truncation-v1.md) | C (boundary) | english, french, german, italian, portuguese, russian, spanish | transcript-tail `trailingUnmatchedFraction` | qualified (warn) |
| [`boundary.run-on@1`](../detectors/boundary.run-on-v1.md) | C (boundary) | english, french, german, italian, portuguese, russian, spanish | must complete | refused |
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Judge panel acquisition](../../audio-qc-engineering.md#judge-panel-acquisition-aq-06-prepared-2026-09-26) and [panel jobs and qualification](../../audio-qc-engineering.md#panel-jobs-and-qualification-aq-06-p8-tooling-2026-09-27): how a panel judge is fetched, run under admission and canaried.
