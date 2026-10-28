---
status: active
owner: backend-mlx
reviewed: 2026-10-28
summary: Maintaining the owned Qwen3 core package — first-party posture, the authority order of its contracts, the production contracts it must keep, the selective upstream-intake procedure (moved here from UPSTREAM.md) and the review checklist guarded by `scripts/qwen3_core_contract.py`.
sourceOfTruth:
  - Packages/VocelloQwen3Core/Package.swift
  - Packages/VocelloQwen3Core/LINEAGE.json
  - Packages/VocelloQwen3Core/RUNTIME_CAPABILITIES.json
  - Packages/VocelloQwen3Core/SEMANTIC_DELTAS.json
  - scripts/qwen3_core_contract.py
---
# Maintaining Vocello Qwen3 Core

The source under `Packages/VocelloQwen3Core/` is an owned, specialized product runtime, not a thin
patch stack. It moved from `third_party_patches/mlx-audio-swift/` because that path misrepresented
its first-party ownership. Product sources consume the stable `VocelloQwen3Core` facade; the legacy
package, product, target, module and public API identities remain behind it for implementation
compatibility. See the [owned Qwen3 runtime ADR](../decisions/owned-qwen3-runtime-monorepo.md).

What this doc does not cover: MLX semantics, error scopes and the dependency pins are
[`mlx-guide.md`](mlx-guide.md)'s; the model, its generation semantics and the parity ledger are
[`qwen3-tts-guide.md`](qwen3-tts-guide.md)'s; the tracked upstreams and their review points are
[`UPSTREAM.md`](../../Packages/VocelloQwen3Core/UPSTREAM.md)'s.

## Authority

Use these sources in order:

1. Runtime source and deterministic tests.
2. `LINEAGE.json`, `COMPATIBILITY.json` and `OWNERSHIP.json` for provenance and boundaries.
3. `RUNTIME_CAPABILITIES.json` for current behaviour and evidence.
4. `UPSTREAM_BASELINE.json` and `SEMANTIC_DELTAS.json` for the upstream comparison.
5. `PERFORMANCE.md`, `CLONE_ARTIFACT_FORMAT.md` and the Qwen and codec guides for design narrative.
6. Dated audits only for research context.

`QwenVoiceCore` owns application engine coordination. The core package owns Qwen3 model loading,
sampling, streaming, Mimi decoding and clone artifacts. `QwenVoiceBackendCore` is the narrow
app-owned policy and provenance vocabulary between those layers; it does not re-export MLX or
MLXAudio.

## Local change policy

Edit the package directly when a change belongs to the Qwen3/MLXAudio implementation rather than
app coordination. Keep the change focused and:

- add or update a stable `RUNTIME_CAPABILITIES.json` entry, stating whether the capability is
  production, diagnostic, internal or retired;
- name its source files, deterministic tests and current documentation;
- attach a tracked benchmark record for a measured performance claim, or mark the evidence
  historical, diagnostic or unmeasured;
- preserve the immutable origin lineage and record upstream review separately;
- preserve typed completion, cancellation, output and memory contracts.

Do not mass-format, add a nested `.git`, create a package-local `.build` or replace the snapshot
with a fresh upstream tree. Direct SwiftPM work uses
`--scratch-path build/cache/swiftpm/mlx-audio-runtime`.

## Production contracts

- Custom, Design and Clone use the bounded streaming pipeline. Non-final chunk evaluation may
  overlap token generation; the final chunk is synchronized before terminal completion.
- Sampling: the code predictor (subtalker) samples at the reference's 0.9 / top-k 50 / top-p 1.0
  for every variation, and the talker filters EOS like any token (D2); both follow the reference
  since the RF-18 follow-up screen (2026-10-20). The talker uses the official values only under the
  default Expressive variation; Balanced and Consistent narrow it on purpose. Both stages sample from
  float32 logits (D3). An explicit internal-diagnostics override can change any of these.
- `maxTokens` is a quality failure, not a successful truncated result.
- MLX work runs inside the facade's error scopes and surfaces as typed failures
  ([`mlx-guide.md` §2.6](mlx-guide.md#26-errors-and-error-scopes)).
- Clone prompt artifacts are atomically published and fail closed on a file, digest, shape, dtype,
  mode, runtime-profile or MLX-build mismatch (`CLONE_ARTIFACT_FORMAT.md`).
- The generation gate has one owner and deterministic FIFO and cancellation-transfer behaviour.
- Decoder partitioning, reset and timing instrumentation must not change the waveform beyond
  floating-point tolerance: partition invariance is tested within 1e-5 max absolute and 1e-6 RMS
  (`Qwen3DecoderPartitionTests`), not bit for bit.

Details and test references live in `PERFORMANCE.md`, `CLONE_ARTIFACT_FORMAT.md` and
`RUNTIME_CAPABILITIES.json`.

## Selective upstream intake

Intake is selective engineering on local `main`, not a rebase. An external upstream checkout may be
used read-only for comparison; it is never a development branch or an alternate source authority.
The tracked upstreams are mlx-audio-swift (the origin), mlx-audio (Python) and the official
QwenLM reference ([`UPSTREAM.md`](../../Packages/VocelloQwen3Core/UPSTREAM.md)).

1. Compare the upstream commit with the recorded import baseline (`UPSTREAM_BASELINE.json`) and the
   current semantic ledger (`SEMANTIC_DELTAS.json`).
2. Record the reviewed head in `LINEAGE.json` (`lastReviewedUpstream`) and in `UPSTREAM.md`'s
   ledger, with each change's disposition. Never rebuild the immutable import inventory to record a
   newer review point; rebuild the baseline only for an explicitly approved new import lineage.
3. Port only behaviour that preserves Vocello's model, artifact, streaming, cancellation, memory,
   output and telemetry contracts, as isolated commits. Update `RUNTIME_CAPABILITIES.json` and the
   affected `SEMANTIC_DELTAS.json` entries.
4. A change to how clone conditioning is computed (the speaker frontend, the reference-encode
   preprocessing, or the MLX build) changes its version token, so stored clone artifacts rebuild
   fail-closed (`CLONE_ARTIFACT_FORMAT.md`). A dependency move follows
   [`mlx-guide.md` §9.3](mlx-guide.md#93-upgrade-procedure).
5. Run `scripts/dev.sh regen`, which rebuilds the current inventory and the facade API baseline
   (`python3 scripts/qwen3_core_contract.py rebuild-current-inventory` and
   `rebuild-facade-api-baseline`) with the other generated artifacts.
6. Regenerate the Xcode project when products or dependencies change
   (`./scripts/regenerate_project.sh`; `--verify` also runs the contract gate).
7. Run `scripts/dev.sh check` (its contract lane runs `python3 scripts/qwen3_core_contract.py
   validate`), or `scripts/dev.sh ci` to reproduce push CI serially. Commit on `main`; CI on `main`
   is the gate.

Benchmark evidence stays `diagnostic` or `unverified` after a runtime-impacting change until a
matching clean record exists. A measured claim needs a validated generation record (schema v3;
`rtf` = wall ÷ audio, lower is faster, declared through `run.rtfDefinition`; `decodeSpeedupX` is the
old inverted figure; `toolchain.optimization` comes from the hash-bound build receipt, never a
literal). Language or prosody evidence names its recognizer family (Apple Speech in the iPhone app;
QC v2's Qwen3-ASR and Whisper large-v3 on the Mac, `qc.py language-bench`; two families for
consensus). Model-dependent benchmarks are not required for documentation-only or ordinary
deterministic changes.

Never replace the directory wholesale, infer parity from matching filenames, or treat a newer
upstream implementation as equivalent without deterministic and benchmark evidence.

## Review checklist

- [ ] The change belongs in the lower-level runtime.
- [ ] `RUNTIME_CAPABILITIES.json` covers every owned runtime file.
- [ ] Tests and documentation references exist.
- [ ] Measured claims cite a current record or carry an explicit non-current evidence class.
- [ ] Immutable lineage and the separate upstream review point are current.
- [ ] Package products and dependency pins still match `COMPATIBILITY.json`.
- [ ] A change to clone conditioning or the MLX pin moves the clone-artifact version.
- [ ] `scripts/dev.sh check` passes without writing `.build` inside the owned package, and CI on
      `main` is green after the push.
