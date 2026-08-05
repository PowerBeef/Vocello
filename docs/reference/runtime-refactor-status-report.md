---
status: historical
owner: backend-and-platform
summary: Maintainer status report for the staged convergence program as reviewed 2026-07-20 after overallPromotion passed. Point-in-time interpretation; the living phase summary is the table in docs/development-progress.md, and config/runtime-refactor-contract.json stays the status authority.
contentDigest: sha256:b9dc43c56fda8fb45609df13a8e4c417b8a40d85ffacf07e262da3704cba1629
---
# Vocello structure, backend depth, and runtime-refactor status report

> Maintainer status report for the active staged convergence program. Confirm against the
> checkout; source, `project.yml`, and `config/runtime-refactor-contract.json` remain higher
> authority. Reviewed 2026-07-20 after `overallPromotion: passed`.

**Verdict:** Phases **0–6 are closed** and Phase 4 **`overallPromotion: passed`** on protected
`main`. Shipping Custom/Design/Clone generation uses the actor → classified session →
`GenerationOutputAdapter` path. Telemetry still uses a **schema-v8 JSONL envelope** plus complete
`*.streaming-telemetry-v9.json` sidecars as streaming history authority. Sampling v2 ships with
fail-closed promotion packaging. Phases 7, 8, and 14 closed 2026-07-23: the UI-context gap is
closed by the generation performance gate, shared-component delivery is live-validated on both
platforms, and the Legacy SPI is retired — loading, metadata, priming, and clone artifacts are
actor-owned. Phases 9–13 remain open.

## Authority order

1. Code + [`project.yml`](../../project.yml)
2. [`config/runtime-refactor-contract.json`](../../config/runtime-refactor-contract.json)
3. [`docs/decisions/runtime-streaming-quality-convergence.md`](../decisions/runtime-streaming-quality-convergence.md)
4. [`docs/development-progress.md`](../development-progress.md)
5. [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) §4

## Project structure

| Path | Role |
| --- | --- |
| `Sources/` | First-party Swift: macOS app UI, Core/Backend/Native/XPC, iOS, SharedSupport, CLI |
| `Packages/VocelloQwen3Core/` | Owned Qwen3-TTS + Mimi runtime (XcodeGen alias `MLXAudio`) |
| `Tests/` | Core, XPC integration, macOS/iOS XCUITest, iOS logic (compile-only) |
| `scripts/` | Authoritative build/test/release/contract gates |
| `config/` | Machine-readable contracts |
| `docs/` | Architecture, progress, ADR, reference guides |
| `benchmarks/` | PASS-only privacy-safe history (schema v2 authoritative) |
| `.claude/rules/` | Domain rules |
| `.claude/settings.json` | Project tool permissions — not a second policy constitution |

### Shipping generation authority stack

```text
MLXTTSEngine (@MainActor product host)
  → NativeEngineRuntime (load / prewarm / conditioning orchestration)
  → UnsafeSpeechGenerationModel (pairs VocelloQwen3Engine with immutable post-load facts)
  → GenerationOutputAdapter  [GenerationOutputAdapter.swift]
       reserve → claimAudioConsumer → open → drain lossless channel
       → acknowledgeProductFinalization
  → VocelloQwen3Engine (actor: generation mutation lease)
       → VocelloQwen3ClassifiedGenerationSession
       → VocelloQwen3LoadedModel.produce (suspending Qwen producer)
```

macOS: UI/CLI → Native/XPC → EngineService → Core → owned runtime.  
iOS: UI → Core in-process → same owned runtime.

## Phase status (program map)

| Phase | State |
| --- | --- |
| 0 Characterization | Closed — clean controls bound |
| 1 Correctness | Shipping |
| 2 Actor + plans | Actor shipping and owns every product-reachable lifecycle operation (loading actor-owned since 14b); plans shadow-only |
| 3 Classified sessions | Shipping |
| 4 Product adapter + mode cutover | Overall promotion passed (`overallPromotion: passed`) |
| 5 Sampling v2 | Promotion-packaged evidence live |
| 6 Telemetry v9 | Complete sidecar authority with v8 envelope (`telemetry: 9`) |
| 7 UI-context gap | Implemented 2026-07-23: screen-recording observer effect fixed, then Liquid Glass compositor cost gated during generation (`generationPerformanceGate`); UI context delivers engine capability (matrix 1.43–1.94; XPC ≈3%) |
| 8 Shared component storage | Closed 2026-07-23: live six-artifact Mac + three-artifact iPhone validation with exact shared-component reuse (wire = expected − 682,295,738 on reused installs) |
| 9 Runtime component reuse | Unblocked (live disk proof); isolated A/B not started |
| 10–11 Spoken-text + long-form v4 | Complete for macOS 2026-07-23 (stages A–E + live acceptance, 6/6 smoke incl. a three-segment project): planner segmentation, sequential streaming with live segment preview (auto-play-gated), bounded assembly, manifest v4 with replacement history, resume, History projects; QC pause budgets and duration-aware thresholds calibrated in the same arc; iOS later |
| 12–13 | Foundations / not started as in the runtime contract |
| 14 Mechanical retirement | Complete 2026-07-23 (14a + 14b): combined characterization session, stream APIs, adapter filename, and the `VocelloQwen3LegacyCompatibility` SPI all retired; loading/metadata/priming/clone artifacts are actor-owned |

## In-progress dual surfaces (do not misread as dual backends)

- Package `VocelloQwen3ProductOutputAdapter` vs Core `GenerationOutputAdapter` (only Core ships)
- Shadow plan mapper — comparison only
- Nested v9-in-v8 plus complete `*.streaming-telemetry-v9.json` sidecars when ready

## Risks

1. JSONL envelope remains v8; do not treat nested transitions alone as history v9 rows.
2. The retired SPI must not return; vendor/security contracts fail closed on any `@_spi` runtime boundary.
3. Stale prose that still says “promotion pending” is wrong — trust the machine contract.
4. Phase 7+ work must not regress secret-sauce first-preview latency or trim/unload safety.

## Resume order

1. ~~Live fixed-seed pairs~~, ~~nested-v9 producers~~, and ~~macOS + iPhone nested-v9 pilots~~
   landed 2026-07-19/20 (see `docs/development-progress.md`).
2. ~~Live Phase 0 characterization~~ closed 2026-07-20 (`status: closed`,
   `characterizationContract: closed-clean-control-sessions-bound`).
3. ~~Fresh full 29-take matrices~~ landed 2026-07-20
   (`macos-xcui-benchmark-20260720-172920-591696d1`,
   `ios-xcui-benchmark-20260720-174441-16fc128c`).
4. ~~Phase 5 promotion packaging + Phase 6 v9 sidecar authority~~ closed 2026-07-20.
5. ~~`overallPromotion: passed`~~ claimed 2026-07-20. ~~Phase 14 mechanical retirement~~ closed 2026-07-23 (14a + 14b). Next: phases 9–13 by priority.

## Implementation landed with this report

| Surface | Path |
| --- | --- |
| Sampling evidence + sub-seed derivation | `Sources/QwenVoiceCore/SamplingEvidence.swift` |
| WAV digest + seed agreement telemetry notes | `GenerationOutputAdapter.swift` |
| Live codec/audio-channel/terminal nested-v9 producers | `GenerationOutputAdapter.swift`, `Qwen3TTS.swift` chunk schedule, `VocelloQwen3AudioChunkEvent` |
| v9 sidecar publication / readiness gate | `GenerationStreamingTelemetryV9Publication.swift` |
| Session/adapter identity digests in bridge | `GenerationStreamingTelemetryV9Bridge.swift` |
| Model-free characterization fixtures | `config/characterization-fixtures.json` |
| Promotion prerequisite gate | `scripts/check_convergence_promotion_gate.py` |
| Phase 14 deferred surface list | `config/runtime-refactor-contract.json` → `phase14DeferredSurfaces` |

## Quick file index

| Need | Start here |
| --- | --- |
| Status | `docs/development-progress.md`, `config/runtime-refactor-contract.json` |
| Product generation | `Sources/QwenVoiceCore/GenerationOutputAdapter.swift` (`GenerationOutputAdapter`) |
| Actor / session | `Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Engine.swift`, `ClassifiedGenerationSession.swift` |
| Sampling evidence | `Sources/QwenVoiceCore/SamplingEvidence.swift` |
| Telemetry transition | `GenerationStreamingTelemetryV9*.swift` |
| Gates | `scripts/runtime_security_contract.py`, `scripts/check_convergence_promotion_gate.py`, `scripts/macos_test.sh test` |
