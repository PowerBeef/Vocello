# Vocello Qwen3 audio runtime

This directory is Vocello's first-party, specialized runtime derived from
[`mlx-audio-swift`](https://github.com/Blaizzy/mlx-audio-swift). It is not the upstream multi-model SDK.
The import was narrowed to the Qwen3-TTS runtime and the codec primitives that runtime needs; deleted
upstream model families remain recoverable from Git history or the recorded upstream baseline.

## Checked-in products

- **`VocelloQwen3Core`** — the stable first-party product boundary used by Vocello. It owns typed
  model-bundle, capability, sampling, memory, request, engine-lease, classified generation-session,
  terminal, cancellation, finalization, and diagnostic contracts, plus narrowly scoped runtime
  adapters.
- **`MLXAudioCore`** — generation protocols and shared audio utilities.
- **`MLXAudioCodecs`** — the Mimi codec subset used by the Qwen3 speech tokenizer.
- **`MLXAudioTTS`** — Qwen3-TTS only.
- **`MLXAudioMark`** — the AudioSeal audio-marking target consumed inside the package through the
  facade (`audio-marking` capability; `PATCHES.json` MARK-001).
- **`Qwen3RuntimeTests`** — deterministic coverage for the runtime behavior Vocello owns.

There are no checked-in STT, speech-to-speech, VAD/diarization, UI, or non-Qwen TTS targets. Do not use
the upstream README's model catalogue as evidence that a model is supported by this fork.

## Supported model contract

The owned model family is **Qwen3-TTS 12 Hz**. Vocello currently selects the 1.7B Base, CustomVoice,
and VoiceDesign families in 4-bit and 8-bit variants. The authoritative repository IDs, pinned
Hugging Face revisions, artifact versions, required files, tokenizer profile, and platform eligibility
live in:

- [`Sources/Resources/qwenvoice_contract.json`](../../Sources/Resources/qwenvoice_contract.json)

The local implementation and family-level API notes live in:

- [`Sources/MLXAudioTTS/Models/Qwen3TTS/`](Sources/MLXAudioTTS/Models/Qwen3TTS/)

Do not add a model to this README as a declaration of support. Update the contract, loader validation,
tests, and benchmark evidence together when the product adopts a new artifact.

## Integration and ownership

Vocello consumes the `VocelloQwen3Core` product as an owned local dependency from the generated
Xcode project. Product sources import that facade rather than the compatibility modules directly.
`QwenVoiceCore` coordinates the product engine while this package owns Qwen3 model loading,
sampling, streaming, Mimi decoding, and clone artifacts. `QwenVoiceBackendCore` contains shared
provenance/policy vocabulary; it does not re-export this package.

The shipping generation boundary is `VocelloQwen3Engine`. It keeps loaded-model identity separate
from operation phase and retains one lease from reservation through explicit product finalization.
A reserved generation remains inert until its one mandatory audio consumer is claimed. Core audio
then uses a direct caller-isolated Qwen producer and frame-bounded suspending channel. Lazy audio is
materialized to `[Float]` before the awaited send, so no `MLXArray` crosses a task or actor boundary;
prepared state, coalesced progress, model terminal, bounded PCM-free diagnostics, cancellation, and
product finalization remain independent. Custom, Design, and Clone now use that classified session
through QwenVoiceCore's `GenerationOutputAdapter`; direct compatibility streams are not product
generation authority. The old combined facade event session remains a package-internal
characterization surface only. `VocelloQwen3LegacyCompatibility` was retired; loading, metadata,
prewarm and schema-3 clone-prompt persistence/adoption now use actor-owned public surfaces.
The empty retired-SPI inventories in `COMPATIBILITY.json` are enforced fail-closed.

The implementation-only `AudioGeneration.audio` compatibility event also carries `[Float]`,
not `MLXArray`. Its four Qwen producers call `audio(materializing:)` while still owning the
waveform; sample-stream consumers do not evaluate tensors in their proxy tasks. There are no
product consumers of the former tensor payload and no persisted event format to migrate.
The actor-owned shipping facade and sampling/chunk schedules are unchanged.

The actor closes its inert-reservation and critical-relief lifecycle explicitly.
Reserved, generating, and aborting states prevent open-after-abort and make duplicate aborts join
one finalization. Typed cache-trim or full-unload relief carries the generation lease through the
release operation and reopens critical admission only after relief completes. A rejected atomic
relief claim clears ownership before session reconciliation so a concurrent ordinary finalizer
cannot strand the lease.

Clone prompts remain actor-owned behind epoch-bound `VocelloQwen3CloneHandle` values. The default
retained-handle capacity is one; an explicit larger capacity uses least-recently-used eviction.
Release is explicit and repeat-safe, a reservation keeps an already captured prompt, noncritical
cache trim preserves valid handles, and model reload, critical trim, or full unload invalidates them.

The `MLXAudioCore`, `MLXAudioCodecs`, and `MLXAudioTTS` products remain checked in for implementation
compatibility. They may be used inside this package, but are not the application-layer dependency
boundary. The facade exposes owned Vocello contracts and opaque adapters; it does not re-export raw
MLX or `MLXAudio*` implementation declarations.

Keep MLX dependency versions synchronized with `project.yml`; the lockstep rule is in
`.claude/rules/native.md` and the pin-bump procedure in `docs/reference/mlx-guide.md` §9.

```swift
.package(path: "Packages/VocelloQwen3Core")
```

The package requires Swift 6.1, macOS 14 or newer, or iOS 17 or newer. Vocello's application deployment
targets are stricter and remain authoritative for the shipped products.

## Verification

From the repository root, run the native test lane:

```sh
scripts/dev.sh test          # or: scripts/dev.sh test --all
```

It drives `scripts/macos_test.sh test`, which runs `VocelloCoreTests`, `VocelloEngineIntegrationTests`
and the owned `Qwen3RuntimeTests` target. `scripts/dev.sh check` is the advisory local loop (lint,
contracts, selected tests, the native lanes the dirty tree touches); the commit lint hook is the only
local block, and CI on `main` is the gate (`scripts/dev.sh ci` reproduces it serially). Model-dependent
benchmark and frontend lanes remain explicit QA and are not prerequisites for committing or publishing
ordinary development work.

## Provenance and license

The contract index, immutable import lineage, package compatibility, ownership boundary, and current
capabilities are recorded in [`VENDOR_MANIFEST.json`](VENDOR_MANIFEST.json),
[`LINEAGE.json`](LINEAGE.json), [`COMPATIBILITY.json`](COMPATIBILITY.json),
[`OWNERSHIP.json`](OWNERSHIP.json), and
[`RUNTIME_CAPABILITIES.json`](RUNTIME_CAPABILITIES.json). `UPSTREAM_BASELINE.json` is the immutable
non-null import inventory; `CURRENT_INVENTORY.json` is the derived retained-file/delta inventory;
and `PATCHES.json` is the active semantic delta ledger. Benchmark-backed capability claims become
diagnostic or unverified whenever their source differs from the recorded run. Active performance design is in
[`PERFORMANCE.md`](PERFORMANCE.md). Attribution and notices are in [`ORIGINS.md`](ORIGINS.md),
[`NOTICES.md`](NOTICES.md), and [`LICENSE`](LICENSE).

[`FACADE_API_BASELINE.json`](FACADE_API_BASELINE.json) is the deterministic declaration and source
inventory for the `VocelloQwen3Core` product boundary. Contract validation rejects stale facade
sources and any public declaration that exposes raw MLX or `MLXAudio*` implementation types.
