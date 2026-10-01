# `quality.audiobox-aesthetics@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `quality.audiobox-aesthetics@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Primary relative quality, advisory (audit section 4.6): production quality (PQ) and content enjoyment (CE) as deltas against the cell baseline, with duration as a covariate; never reaches warn.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `shadow` | legacy-unqualified | neural | - | no | no | 2 (cpu) | D0 (expected D0) |

`shadow`: Runs beside the current judges; its verdicts are uncalibrated and never block.

**Audit section.** 4.6.

## Provenance

- License tier **A** (vendor-declared): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: CC BY 4.0 (Hugging Face card and the repository license)
- Code: CC BY 4.0 (audiobox-aesthetics), with WavLM-derived portions under MIT
- Training data: Vendor-declared human aesthetic annotations (arXiv 2502.05139); the released evaluation annotations cover LibriTTS, Common Voice 13, EARS, MUSDB18, MusicCaps, AudioSet and PAM
- Tier basis: audit section 4.6: A
- Notices: CC BY 4.0 attribution: Meta Audiobox Aesthetics (Tjandra et al., 2025)
- Independence: vendor Meta FAIR; architecture WavLM-style transformer encoder with four regression heads (CE, CU, PC, PQ); training data Meta aesthetic annotations; label lineage human aesthetic ratings; correlated with the generator's lab: no.
- Sources: <https://huggingface.co/facebook/audiobox-aesthetics>, <https://github.com/facebookresearch/audiobox-aesthetics>

## Pins

- `facebook/audiobox-aesthetics` at revision `9b1dd8e5df9af7216e836a98974fe3b82c56ded6`.
- Digest status: `content-addressed-snapshot`.
- Verification: scripts/acquire_audio_qc_judges.py fetches exactly these files at the pinned revision into the owned model root, refusing any size or digest mismatch; before every load the worker verifies the snapshot directory holds exactly these files, each matching its pin (verify_judge_snapshot), and refuses an excluded runtime package. Nothing is downloaded at load time.
- Runtime: audiobox-aesthetics 0.0.4, numpy 2.4.6, torch 2.11.0, torchaudio 2.11.0.
- `filesSource`: The Hugging Face tree metadata of the pinned revision (read 2026-09-26, no download): the LFS SHA-256 of each large file and the git blob ID of every other file, with its size. Only the safetensors weights, their config and the card are pinned and fetched; the duplicate pickle checkpoint (checkpoint.pt) and the figure are not used.

| File | Bytes | Digest |
|---|---|---|
| `README.md` | 5924 | git blob `a85863984931090e` |
| `config.json` | 492 | git blob `e2b5a9ece8c3db1c` |
| `model.safetensors` | 415472992 | LFS SHA-256 `a5a3c2412649cc23` |

## Execution

- Stage 2; lane cpu; engine audiobox-aesthetics; device cpu; threads 2 (provisional); batch size 1; orchestrated; worker `scripts/audio_qc_worker.py`.
- Thread control: environment
- Acquisition: directory="audiobox-aesthetics", stage=2, runtime="audiobox-torch"
- Resources: canonical-host peak 2.99 GiB; admission ceiling 3.59 GiB (calibrated), measured in session 20260927-aaba14fd; policy: measured canonical-host peak x 1.2 (AQ-06).
- Ceiling basis: Audit section 3.4 CPU-lane estimate (0.8-1.2 GB, section 4.6); provisional until two clean M6 runs measure its peak.
- Output identity: repository, revision, snapshotFileDigests, runtimeDependenciesDigest, runtimeVersions, workerSourceSHA256, engine, preprocessing, hostProfile, threads. Envelope identity: resourceSupervisorSHA256, probeAlgorithmVersion, supervisorOptions.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- Canary record: [benchmarks/audio-qc-qualification/20261001-505107fc/judges/quality.audiobox-aesthetics-v1.json](../../../../benchmarks/audio-qc-qualification/20261001-505107fc/judges/quality.audiobox-aesthetics-v1.json) (2026-10-01), output identity `7511558af400a943`.
- Re-cited after its output identity changed; replaced canary records: [benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/quality.audiobox-aesthetics-v1.json](../../../../benchmarks/audio-qc-qualification/20260927-aaba14fd/judges/quality.audiobox-aesthetics-v1.json) (2026-09-27, output identity `68d2d6af4387cb59`).
- Canary qualification passed: yes; determinism D0 over 9 rows (9 bit-exact, 0 discrete mismatches); peak 1.68 GiB on mac-mini-m6-16gb (session 20261001-505107fc).

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Judge panel acquisition](../../audio-qc-engineering.md#judge-panel-acquisition-aq-06-prepared-2026-09-26) and [panel jobs and qualification](../../audio-qc-engineering.md#panel-jobs-and-qualification-aq-06-p8-tooling-2026-09-27): how a panel judge is fetched, run under admission and canaried.
