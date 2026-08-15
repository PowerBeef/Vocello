---
status: active
owner: backend-mlx
summary: Maintaining the owned Qwen3 core package — first-party monorepo posture, facade vs compatibility identities, and the vendor-runtime contract that guards the boundary.
sourceOfTruth:
  - Packages/VocelloQwen3Core/Package.swift
  - scripts/vendor_runtime_contract.py
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
4. `UPSTREAM_BASELINE.json` and `PATCHES.json` for historical upstream comparison.
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

Use a separate branch and an explicit upstream checkout:

1. Review the desired upstream commit against the recorded import baseline.
2. Never rebuild the immutable import inventory merely to record a newer review point.
3. Port selected changes as isolated commits and update the capability contract. Rebuild the
   baseline only for an explicitly approved new import lineage.
4. Regenerate the Xcode project when products or dependencies change.
5. Run:

```sh
python3 scripts/vendor_runtime_contract.py validate
./scripts/check_project_inputs.sh
scripts/macos_test.sh test
./scripts/build_foundation_targets.sh macos
./scripts/build_foundation_targets.sh ios
```

Model-dependent benchmarks remain explicit evidence for performance or output-quality changes;
they are not required for documentation-only or ordinary deterministic publishing.

## Review checklist

- [ ] The change belongs in the lower-level runtime.
- [ ] `RUNTIME_CAPABILITIES.json` covers every owned runtime file.
- [ ] Tests and documentation references exist.
- [ ] Measured claims cite a current record or carry an explicit non-current evidence class.
- [ ] Immutable lineage and the separate upstream review point are current.
- [ ] Package products and dependency pins still match `COMPATIBILITY.json`.
- [ ] Deterministic gates pass without writing `.build` inside the owned package.
