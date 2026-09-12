---
status: active
owner: backend-mlx
reviewed: 2026-09-12
summary: Maintaining the owned Qwen3 core package — first-party monorepo posture, facade vs compatibility identities, and the vendor-runtime contract that guards the boundary.
sourceOfTruth:
  - Packages/VocelloQwen3Core/Package.swift
  - scripts/qwen3_core_contract.py
---
# Maintaining Vocello Qwen3 Core

The source under `Packages/VocelloQwen3Core/` is an owned, specialized product runtime, not a thin
patch stack. The package moved from `third_party_patches/mlx-audio-swift/` because that path
misrepresented its first-party ownership. Product sources now consume the stable
`VocelloQwen3Core` facade, while the legacy package, product, target, module, and public API
identities remain available behind it for implementation compatibility. The migration therefore
changed both location and the application dependency boundary without changing synthesis or
persistent identities. See the
[`owned Qwen3 runtime ADR`](../decisions/owned-qwen3-runtime-monorepo.md).

## Authority

Use these sources in order:

1. Runtime source and deterministic tests.
2. `LINEAGE.json`, `COMPATIBILITY.json`, and `OWNERSHIP.json` for provenance and boundaries.
3. `RUNTIME_CAPABILITIES.json` for current behavior and evidence.
4. `UPSTREAM_BASELINE.json` and `SEMANTIC_DELTAS.json` for historical upstream comparison.
5. `PERFORMANCE.md` and the Qwen/Mimi subsystem guides for design narrative.
6. Historical audits only for dated research context.

`QwenVoiceCore` owns application engine coordination. The core package owns Qwen3 model loading,
sampling, streaming, Mimi decoding, and clone artifacts. `QwenVoiceBackendCore` is the narrow
app-owned policy/provenance vocabulary between those layers; it is not an MLX re-export target.

## Local change policy

Direct edits are appropriate when a change belongs to the Qwen3/MLXAudio implementation rather
than app coordination. Keep the change focused and:

- add or update a stable `RUNTIME_CAPABILITIES.json` entry;
- identify capability state as production, diagnostic, internal, or retired;
- name source files, deterministic tests, and current documentation;
- attach a tracked benchmark record for measured performance claims, or explicitly mark the
  evidence historical, diagnostic, or unmeasured;
- preserve immutable origin lineage and record upstream review separately;
- preserve VoiceOver-independent product behavior, typed completion, cancellation, output, and
  memory contracts.

Do not mass-format, add a nested `.git`, create a package-local `.build`, or replace the snapshot
with a fresh upstream tree. Direct SwiftPM work must use
`--scratch-path build/cache/swiftpm/mlx-audio-runtime`.

## Production contracts

- Custom, Design, and Clone use the bounded streaming pipeline. Non-final chunk evaluation may
  overlap token generation; the final chunk is synchronized before terminal completion.
- Talker and subtalker sampling use official checkpoint behavior unless an explicit diagnostic
  override is active.
- `maxTokens` is a quality failure, not a successful truncated result.
- Clone prompt artifacts are atomically published and fail closed on file, digest, shape, dtype,
  mode, or runtime-profile mismatch.
- The generation gate has one owner and deterministic FIFO/cancellation-transfer behavior.
- Decoder partitioning, reset, and timing instrumentation must not change the waveform.

Details and test references live in `PERFORMANCE.md`, `CLONE_ARTIFACT_FORMAT.md`, and
`RUNTIME_CAPABILITIES.json`.

## Selective upstream intake

Keep Vocello development on local `main`. An explicit external upstream checkout may be used
read-only for comparison; it is not a development branch or an alternate source authority:

1. Review the desired upstream commit against the recorded import baseline.
2. Never rebuild the immutable import inventory merely to record a newer review point.
3. Port selected changes as isolated commits and update the capability contract. Rebuild the
   baseline only for an explicitly approved new import lineage.
4. Regenerate the Xcode project when products or dependencies change:
   `./scripts/regenerate_project.sh` regenerates only (`--fast` is the historical spelling of that
   default); `--verify` also runs the contract gate afterwards.
5. Run `scripts/dev.sh check` (advisory: lint, contracts, selected tests and the native lanes the
   dirty tree touches; `python3 scripts/qwen3_core_contract.py validate` runs inside its contract
   lane), or `scripts/dev.sh ci` to reproduce push CI serially. Commit on `main`; the commit lint hook
   is the only local block and CI on `main` is the gate.

Model-dependent benchmarks remain explicit evidence for performance or output-quality changes;
they are not required for documentation-only or ordinary deterministic publishing. A measured claim
needs a validated generation record (schema v3; `rtf` = wall ÷ audio, lower is faster, declared through `run.rtfDefinition`;
`decodeSpeedupX` is the old inverted figure; `toolchain.optimization` comes from the hash-bound build
receipt, never a literal), and language or prosody evidence names its recognizer family (Apple Speech
on the iPhone, the pinned whisper-small MLX producer `scripts/independent_asr.py` on the Mac after the
generator has exited; two families for consensus).

## Review checklist

- [ ] The change belongs in the lower-level runtime.
- [ ] `RUNTIME_CAPABILITIES.json` covers every owned runtime file.
- [ ] Tests and documentation references exist.
- [ ] Measured claims cite a current record or carry an explicit non-current evidence class.
- [ ] Immutable lineage and the separate upstream review point are current.
- [ ] Package products and dependency pins still match `COMPATIBILITY.json`.
- [ ] `scripts/dev.sh check` passes without writing `.build` inside the owned package, and CI on
      `main` is green after the push.
