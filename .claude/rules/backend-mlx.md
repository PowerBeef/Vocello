# Backend / MLX domain rule

> Domain rule for `QwenVoiceBackendCore`, `QwenVoiceCore`, the owned Qwen3 core package
> stack, and everything related to model loading, prompt construction, synthesis,
> memory policy, and audio QC.

## Boundaries

**Owns:**
- `Sources/QwenVoiceBackendCore/`
- `Sources/QwenVoiceCore/` (engine core, generation semantics, model registry, downloader, telemetry)
- `Packages/VocelloQwen3Core/`
- Typed telemetry semantics and the owned-runtime lineage, compatibility, ownership, capability,
  performance, and clone-artifact contracts
- The `VocelloQwen3Core` product facade and its typed product/runtime boundary. Product sources
  must not import the compatibility-preserved `MLXAudio*` implementation modules directly.
- `Sources/Resources/qwenvoice_contract.json`
- `Sources/Resources/qwenvoice_production_model_catalog.json` and
  `config/model-artifact-receipts.json` (complete fail-closed exact-artifact identities; never infer
  a size or digest)
- `config/runtime-debug-knobs.json` and `config/concurrency-safety.json` for backend-owned runtime
  overrides and explicit concurrency-safety exceptions

**Does NOT own:**
- macOS SwiftUI / XPC client wiring (`.claude/rules/macos.md`)
- iOS app UI / on-device coordination (`.claude/rules/ios.md`)
- Build scripts, CI, signing, release packaging (`.claude/rules/release-qa.md`)

**Consults:**
- `docs/ARCHITECTURE.md` §4 (engine core), §11 (model management), §12 (telemetry)
- `docs/reference/{mlx-guide,qwen3-tts-guide,mimi-codec-guide,metal-guide,swift-performance-guide,ios-engine-optimization,telemetry-and-benchmarking}.md`
- Root `CLAUDE.md` (Hard rules) + [`docs/ARCHITECTURE.md`](../../docs/ARCHITECTURE.md) (engine invariants)

## Required pre-read

Before changing anything in this layer, read:
1. `docs/ARCHITECTURE.md` §4 (the `TTSEngine` abstraction, factory, pipeline, memory, streaming, prewarm, clone cache, cancellation, QC).
2. The relevant subsystem guide under `docs/reference/` (e.g. `mlx-guide.md` for `MLXArray`/`Memory`/`GPU`, `qwen3-tts-guide.md` for prompt construction, `mimi-codec-guide.md` for codec work).
3. `Sources/Resources/qwenvoice_contract.json` if you are touching model IDs, speakers, variants, or HF revisions.

## Tools and skills

- **Shell scripts are authoritative** for build/test:
  - `scripts/build_foundation_targets.sh macos|ios` for compile-safety.
  - `scripts/build.sh cli` to build `vocello`.
  - `QWENVOICE_DEBUG=1 ./build/vocello bench …` for perf/quality gates.
- When callable, use Swift/concurrency/performance skills (for example the Axiom skills) and
  authoritative MLX / Hugging Face documentation for language, isolation, and profiling decisions.
  Read each selected skill before use.
- Skills guide implementation and diagnosis; shell builds, tests, benchmarks, and their artifacts
  remain authoritative. Where no skill applies, inspect the owned runtime source and authoritative Apple,
  package, or Hugging Face documentation.
- Generated output must use `config/build-output-policy.json`. Backend work may consume the
  canonical macOS/iOS caches and the dedicated owned-runtime SwiftPM scratch path, but must not create
  another DerivedData root or a `.build` directory below `Packages/VocelloQwen3Core/`. Route policy
  changes through `.claude/rules/release-qa.md`.
- XCUITest is the sole autonomous app UI driver. Smoke and benchmark UI lanes are explicit
  frontend acceptance only and never a prerequisite for a commit, push, pull request, ordinary
  merge, ordinary CI, or release package. Frontend observations do not prove backend completion;
  typed app/XPC/backend rows must still join by `generationID`.
- Telemetry or benchmark schema-version changes require backend, the affected macOS or iOS capture
  owner, and release/QA review. Backend owns field meaning; platform roles own capture/transport;
  release/QA owns schemas, publication, and history compatibility.

## Build / test commands

```sh
# Compile-safety for the core frameworks
./scripts/build_foundation_targets.sh macos
./scripts/build_foundation_targets.sh ios
scripts/macos_test.sh test   # Core, XPC transport, and owned Qwen3 runtime contracts

# Build the CLI and run a quick generate
./scripts/build.sh cli
QWENVOICE_DEBUG=1 ./build/vocello custom --variant speed --text "Hello world."

# Perf gate (autonomous QC/telemetry proof for release-affecting changes)
QWENVOICE_DEBUG=1 ./build/vocello bench --modes clone --variants speed \
  --lengths short,medium,long --warm 3 --voice <prepared-voice> \
  --label "backend-qa"
```

A successful in-repository benchmark publishes a compact, allowlisted record automatically. Do
not append to `benchmarks/HISTORY.md`; it is generated from `benchmarks/runs/`. Raw JSONL, audio,
screenshots, result bundles, and traces remain in the untracked artifact directory. Dirty-source
runs are retained as exploratory evidence and excluded from canonical trends. Human listening is
optional annotation; promotion requires clean deterministic QC rather than a manual waiver for a
warning.

## Invariants (do not regress)

- **Prewarm reentrancy gate.** `acquirePrewarmSlot()` / `releasePrewarmSlot()` must stay paired.
  Never pair a throwing `try? await acquirePrewarmSlot()` with an unconditional
  `defer { releasePrewarmSlot() }` — on a throw the slot isn't held and the defer releases
  someone else's slot.
- **Lossless core audio; non-dropping frontend events.** Final PCM crosses the actor-owned,
  single-consumer suspending channel. Frontend preview/status uses a separate per-generation,
  bounded suspending router with yield accounting. Do not reintroduce an eviction policy for
  audio-bearing events.
- **Cancellation ownership.** `MLXTTSEngine` conforms to `ActiveGenerationCancellable` on every
  platform. `ActiveGenerationCoordinator` owns one active generation, records the typed reason
  (`user`, `memoryPressure`, `superseded`, or `shutdown`), and awaits task termination before trim,
  unload, or ownership release. Cancellation emits `.cancelled`, not `.failed`, and no late result
  may reach persistence. The generate catch must still restore `loadState` on every terminal path.
- **Per-tier memory.** `NativeMemoryPolicyResolver` sets policy per device class. There is
  **no hard `Memory.memoryLimit` in production** and **no Quality→Speed OOM fallback**. MLX
  allocator limits are host-boundary process state; request-varying Qwen clear cadence and KV
  window travel in immutable `VocelloQwen3MemoryConfiguration`/
  `Qwen3RequestMemoryPolicy` values and must never return to a mutable singleton.
- **Sampling is request-local.** Algorithm v2 gives every request an effective seed and fresh
  `MLXRandom.RandomState`; talker and subtalker stages remain independently configurable, and all
  categorical draws for one request use that state. Do not reintroduce `MLXRandom.seed` or another
  process-global sampling override.
- **Convergence authority is explicit.** `config/runtime-refactor-contract.json` records
  `VocelloQwen3Engine`, its classified session, and QwenVoiceCore's `GenerationOutputAdapter` as
  the shipping generation path for Custom, Design, and Clone. Phase 4 `overallPromotion` passed
  2026-07-20 with clean Phase 0 controls and canonical matrices. The contract JSON's
  `phaseStatus` block is the sole per-phase status authority (human summary: the phase table in
  `docs/development-progress.md`); do not restate open/closed phase state here. Prepared-model
  loading, post-load metadata/facts, preparation diagnostics, priming, and schema-3 clone-artifact
  persistence/adoption are actor-owned public surfaces; the legacy compatibility SPI is retired
  and its symbols are internal to the package. Do not add a public mutation surface back to the
  loaded model or reintroduce an `@_spi` runtime boundary.
  Preserve the actor's explicit reserved/generating/aborting ownership: open must fail once abort
  owns the reservation, duplicate aborts join one finalization, and typed cache-trim/full-unload
  relief must carry the generation lease without reopening critical admission before completion.
  Keep Clone prompt tensors actor-owned behind epoch-bound handles: default capacity one, bounded
  LRU for explicit larger capacities, fail-closed explicit release, preservation across noncritical
  trim, and invalidation on model reload, critical trim, or full unload.
  Task cancellation of a producer suspended on the shipping channel must continue to wake the
  pending send rather than publish or strand it.
- **Decoder drift.** The owned `Qwen3TTSSpeechTokenizer` uses input-side overlap-and-discard.
  Do not "fix" drift by changing the output side.
- **SPM pins move in lockstep.** `mlx-swift` and `mlx-swift-lm` are bumped together, never
  alone, and only after a benchmark-gated review on a throwaway branch.
- **MLX is the only backend.** Do not pivot to Core ML or another runtime.
- **Telemetry semantics are typed.** Schema-v8 frontend latency stops at playback scheduling, not
  acoustic audibility; process memory belongs only to the process that measured it, and a macOS UI
  benchmark is authoritative only when app, XPC service, and engine layers are complete.
- **Diagnostic overrides are fail closed.** Every production-affecting environment key must be in
  `config/runtime-debug-knobs.json` and is inert without the `QWENVOICE_DEBUG` master gate. Every
  owned unchecked/unsafe concurrency declaration must remain justified in
  `config/concurrency-safety.json`; validate both with `scripts/runtime_security_contract.py`.
- **Catalog activation is fail closed.** The generated schema-v2 production catalog is complete for
  all six Speed/Quality artifacts, and every host uses an exact delivery plan. Reuse a shared
  component only after exact store verification; installed component paths remain regular hard
  links, never symlinks. Never reintroduce live repository enumeration, infer a digest, or accept a
  staged/missing identity. Delivery-plan resolution may automatically reconcile an existing model
  only after every catalog file authenticates; a failed local check must grant no reusable bytes.
  `model_catalog_contract.py validate --require-complete` is deterministic contract proof; a fresh
  isolated Mac/iPhone delivery run is separate explicit quality evidence after delivery changes.

## Common mistakes

- Editing `QwenVoice.xcodeproj/project.pbxproj` directly. Always edit `project.yml` and run
  `./scripts/regenerate_project.sh`.
- Adding a generic `#if DEBUG` behavior fork. There is no Debug configuration or `DEBUG` symbol;
  use runtime `DebugMode.isEnabled` or a narrowly named condition owned by a test target.
- Touching the iOS Simulator. Backend work is validated through macOS builds, foundation-target
  builds, and on-device iOS lanes — never the simulator.
- Changing the contract JSON without updating the iOS catalog check
  (`scripts/check_ios_catalog.sh`) if model eligibility changes.
