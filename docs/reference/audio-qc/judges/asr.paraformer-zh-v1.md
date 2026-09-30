# `asr.paraformer-zh@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `asr.paraformer-zh@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Content voter for zh (audit section 4.1): a non-autoregressive transcript with no hotwords, punctuation or VAD model.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `shadow` | legacy-unqualified | neural | paraformer | yes | no | 2 (cpu) | D0 (expected D0) |

`shadow`: Runs beside the current judges; its verdicts are uncalibrated and never block.

**Languages.** voter: zh.

**Audit section.** 4.1.

## Provenance

- License tier **A** (vendor-declared-undisclosed): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: Apache-2.0 (Hugging Face card); the upstream FunASR model license's attribution and model-name obligations are kept as notices
- Code: MIT (FunASR)
- Training data: 60,000+ hours of Mandarin speech (vendor-declared; composition undisclosed)
- Tier basis: audit section 4.1: A, with notices
- Notices: FunASR model license: attribution and model-name obligations
- Independence: vendor Alibaba (FunASR); architecture Paraformer: SAN-M encoder, CIF predictor and non-autoregressive decoder, 220M parameters; training data vendor Mandarin corpus; label lineage vendor-internal; correlated with the generator's lab: no.
- Correlation: The same company as SenseVoice and as the generator's lab, but a different lab; counts toward the error-correlation audit before any consensus gates (AQ-F35).
- Sources: <https://huggingface.co/funasr/paraformer-zh>, <https://github.com/modelscope/FunASR>

## Pins

- `funasr/paraformer-zh` at revision `d7811ee3ac581fbcfdeb37c98c6ba674028433dc`.
- Digest status: `content-addressed-snapshot`.
- Verification: scripts/acquire_audio_qc_judges.py fetches exactly these files at the pinned revision into the owned model root, refusing any size or digest mismatch; before every load the worker verifies the snapshot directory holds exactly these files, each matching its pin (verify_judge_snapshot), and refuses an excluded runtime package. Nothing is downloaded at load time.
- Runtime: funasr 1.4.16, numpy 2.4.6, torch 2.11.0, torchaudio 2.11.0.
- `filesSource`: The Hugging Face tree metadata of the pinned revision (read 2026-09-26, no download): the LFS SHA-256 of each large file and the git blob ID of every other file, with its size. Every file of the revision is pinned and fetched.

| File | Bytes | Digest |
|---|---|---|
| `.gitattributes` | 1579 | git blob `684ad6fd2c6e1825` |
| `README.md` | 3537 | git blob `09724db9b2a03c1d` |
| `am.mvn` | 11203 | git blob `681910cd1ab6458b` |
| `config.yaml` | 2509 | git blob `c0a9f403c8e62017` |
| `configuration.json` | 472 | git blob `6f77310bef84268f` |
| `example/asr_example.wav` | 417742 | LFS SHA-256 `732f28a4445eb2b6` |
| `fig/struct.png` | 49870 | git blob `4c3d7855faae8b59` |
| `model.pt` | 880502012 | LFS SHA-256 `5bba782a5e919616` |
| `seg_dict` | 8287834 | git blob `fb19e07f2870b09b` |
| `tokens.json` | 93676 | git blob `f8bc9c31ab1ba458` |

## Execution

- Stage 2; lane cpu; engine funasr-paraformer; device cpu; threads 3 (provisional); batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment
- Decode options: hotwords=null, punctuationModel=null, vadModel=null, batchSize=1, device="cpu"
- Acquisition: directory="paraformer-zh", stage=1, runtime="funasr-torch"
- Resources: canonical-host peak 3.02 GiB; admission ceiling 3.63 GiB (calibrated), measured in session 20260927-aaba14fd; policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: Audit section 3.4 CPU-lane estimate (1.2-1.8 GB resident, section 4.1); provisional until two clean M6 runs measure its peak.
- Output identity: repository, revision, snapshotFileDigests, runtimeDependenciesDigest, runtimeVersions, workerSourceSHA256, engine, decodeOptions, preprocessing, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- Canary record: [benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/asr.paraformer-zh-v1.json](../../../../benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/asr.paraformer-zh-v1.json) (2026-09-27), output identity `de8bd7fd3c9cffdb`.
- Canary qualification passed: yes; determinism D0 over 4 rows (4 bit-exact, 0 discrete mismatches); peak 3.02 GiB on mac-mini-m6-16gb (session 20260927-aaba14fd).

Its accuracy is claimed only through the detectors that consume it:

| Detector | Class | Languages | Reads | Qualification |
|---|---|---|---|---|
| [`content.consensus-error@1`](../detectors/content.consensus-error-v1.md) | B (content) | chinese | panel `errorRate` | not qualified |
| [`boundary.truncation@1`](../detectors/boundary.truncation-v1.md) | C (boundary) | chinese | transcript-tail `trailingUnmatchedFraction` | not qualified |
| [`boundary.run-on@1`](../detectors/boundary.run-on-v1.md) | C (boundary) | chinese | must complete | not qualified |

**UNQUALIFIED.** No committed calibration record qualifies a detector that consumes this judge, so every verdict built on it composes as `uncalibrated`.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Judge panel acquisition](../../audio-qc-engineering.md#judge-panel-acquisition-aq-06-prepared-2026-09-26) and [panel jobs and qualification](../../audio-qc-engineering.md#panel-jobs-and-qualification-aq-06-p8-tooling-2026-09-27): how a panel judge is fetched, run under admission and canaried.
