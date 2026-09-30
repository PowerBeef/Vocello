# `asr.whisper-small@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `asr.whisper-small@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Mac recognizer family 'whisper': locale-locked full-file transcript and first-30-second language identification, after the generator exits.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `gating` | legacy-unqualified | neural | whisper | yes | no | 2 (gpu) | unmeasured |

`gating`: Feeds a verdict that can fail a take or a lane.

## Provenance

- License tier **B** (scraped-web-audio): Permissive weights, but training data includes scraped web audio or corpora whose rights stay with the original owners, with no explicit non-commercial term. Internal, never-shipped evaluation only (decision 2a). Commercial use compatible: yes.
- Weights: MIT (OpenAI Whisper release); Apache-2.0 on the mlx-community conversion card
- Code: MIT (mlx-whisper)
- Training data: 680,000 hours of weakly supervised multilingual web audio; rights stay with the original owners; no explicit non-commercial term
- Tier-B acceptance: decision 2a (2026-09-25), scope `internal-never-shipped-evaluation`.
- Independence: vendor OpenAI (weights); mlx-community (conversion); architecture encoder-decoder transformer, 244M parameters; training data Whisper web audio; label lineage weakly supervised web transcripts; correlated with the generator's lab: no.
- Sources: <https://github.com/openai/whisper>, <https://huggingface.co/mlx-community/whisper-small-mlx>

## Pins

- `mlx-community/whisper-small-mlx` at revision `45f3915923c7a79a5a5b5a7d909d39aeb0e5630e`.
- Digest status: `pinned`.
- Verification: prepare_delivery_compact_model_config.py verifies every file at preparation; the adapter re-verifies the weights and runtime binary before each launch; nothing is downloaded.
- Runtime: mlx 0.32.0, mlx-whisper 0.4.3, numpy 2.4.6.
- Execution registry: `config/delivery-evaluator-v2-candidates.json#whisper-small-mlx`.

| File | Bytes | Digest |
|---|---|---|
| `config.json` | - | SHA-256 `e8f58e638208af66` |
| `weights.npz` | - | SHA-256 `55b6674c9b339702` |

## Execution

- Stage 2; lane gpu; engine whisper-mlx; device mlx-gpu; threads 2; batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment
- Resources: canonical-host peak -; admission ceiling 2.74 GiB (provisional); policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: The legacy recognizer has no canary record, so its ceiling stays provisional: the measured M6 peak x 1.2 from two clean full-cohort runs of recalibration session 20260927-70e86ea6 (791 takes in 64-row chunks, peak 2449459696 bytes, recorded in that session's legacyJudges). It replaces 2.5 GiB, set before any canonical-host measurement (AQ-F43), which an unchunked 478-row run passed at 2.68 GiB on 2026-09-27.
- Output identity: modelID, sourceRevision, weightsSHA256, labelMapDigest, binarySHA256, runtimeDependencies, workerSourceSHA256, commandTemplate, algorithm, decodeOptions, lockedLanguage, preprocessingConfigDigest, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
- Legacy identifiers: adapterIDs: whisper-small-mlx; modelFamilies: whisper; algorithms: mlx-whisper-locked-decode-v1; sources: scripts/independent_asr.py, scripts/independent_asr_worker.py.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- No canary record.

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Independent recognition](../../audio-qc-engineering.md#independent-recognition-one-additional-observation-no-waiver): how its whole-file transcripts entered the Mac language verdicts.
- [Language and naturalness remain separate](../../audio-qc-engineering.md#language-and-naturalness-remain-separate).
