---
status: active
owner: backend-and-platform
reviewed: 2026-10-10
summary: Source-grounded Codex takeover audit: runtime ownership, workflow correctness, evidence boundaries, and targeted migration acceptance.
sourceOfTruth:
  - project.yml
  - config/roadmap.json
  - config/runtime-refactor-contract.json
---
# Vocello: Codex takeover and workflow audit

**Baseline:** `185444b`, reviewed October 10, 2026. This report supplements the
[October 6 deep audit](2026-10-06-deep-audit.md), the
[September project audit](2026-09-22-project-audit.md), and the
[telemetry audit](2026-09-25-benchmark-telemetry-audit.md). Their finding IDs and
historical evidence remain intact; current work status belongs to
[`config/roadmap.json`](../../config/roadmap.json), not to a re-count of their findings.

## Evidence and limits

The takeover review traced production entry points, ownership boundaries, terminal paths,
storage publication, test target membership, scripts, and CI/release contracts. The lead's
pre-migration verification recorded **142 tests and 390 subtests passing in 21.18 seconds**.
That is the selected tooling/contracts baseline, not a count of the native suite and not proof
that generation, UI, background delivery, or memory behavior ran successfully.

This document's author performed static inspection only: no model load, download, build,
device interaction, UI execution, listening, benchmark, or release operation. Migration
validation is recorded separately in [`development-progress.md`](../development-progress.md).
New fixture results are attributed below. No performance improvement is claimed from this work.

The review used Axiom's `axiom-build`, `axiom-concurrency`, `axiom-data`, `axiom-testing`,
`axiom-swiftui`, `axiom-performance`, `axiom-networking`, `axiom-integration`, `axiom-media`,
and `axiom-macos` guidance. The consequential rules are isolation-domain ownership,
immutable shipped migrations with populated upgrade fixtures, deterministic synchronization,
measurement before optimization, and separating retained evidence from new execution.
The app deployment floors remain macOS 26.0 and iOS 26.0 (`project.yml`); installed SDK
availability does not authorize raising either floor.

## Architecture and workflow knowledge

| Surface | Entry and ownership | Failure, persistence, and cleanup boundary |
| --- | --- | --- |
| Shared runtime | [`NativeRuntimeFactory`](../../Sources/QwenVoiceCore/NativeRuntimeFactory.swift) builds the registry, asset store, preparation, and `MLXTTSEngine`; the owned [`VocelloQwen3Engine`](../../Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Engine.swift) owns model mutation through actor leases. | `NativeEngineRuntime` retains load/prewarm/clone-conditioning responsibilities. `ActiveGenerationCoordinator` and the main-actor memory-relief admission latch prevent trim/unload from racing an unfinished take. Host policy differs; there is one in-process engine implementation. |
| Generation and cancellation | [`MLXTTSEngine.generate`](../../Sources/QwenVoiceCore/MLXTTSEngine.swift) admits work, records typed first-reason cancellation ingress, registers the running task, and forwards generation-scoped events. [`GenerationOutputAdapter`](../../Sources/QwenVoiceCore/GenerationOutputAdapter.swift) reserves, claims the sole audio consumer, prepares product output, then opens generation. | Success requires model EOS, accepted product completion, and finalization acknowledgment before lease release. Before-open failure aborts the reservation; after-open failure cancels/drains audio and model termination, then acknowledges abortion. User, shutdown, supersession, and memory-pressure reasons are distinct. |
| Streaming and playback | [`ClassifiedGenerationSession`](../../Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/ClassifiedGenerationSession.swift) provides frame-bounded lossless producer backpressure. [`GenerationScopedEventRouter`](../../Sources/QwenVoiceCore/GenerationEventDeliveryProbe.swift) separately bounds frontend events. [`LiveStreamingPlaybackEngine`](../../Sources/SharedSupport/Services/LiveStreamingPlaybackEngine.swift) and `AudioPlayerViewModel` own preview scheduling/handoff. | Canonical PCM reaches the incremental WAV before matching preview publication. Final WAV publication is atomic and protected from partial-take cleanup. Preview scheduling proves a scheduled frame, not sound heard by a listener; interruption, underrun, and perceived quality require platform evidence. |
| macOS adapter | [`MacEngineBootstrap`](../../Sources/Services/MacEngineBootstrap.swift), the shared `TTSEngineStore`, and `MacAppModel`-owned per-mode `StudioGenerationCoordinator` drive `MacStudioSingleTakeRunner`; macOS hooks supply playback, History, export, and telemetry behavior. | Immutable requests come from `MacStudioGenerationRequestFactory`; attempt tokens reject stale completion. Line batches and long-form work use shared orchestration with macOS hooks. Views do not own the engine or independently mutate model state. |
| iOS adapter | [`QVoiceiOSApp`](../../Sources/iOS/QVoiceiOSApp.swift) owns app-lifetime wiring. [`IOSSingleTakeGenerationExecutor`](../../Sources/iOSSupport/Services/IOSSingleTakeGenerationExecutor.swift) owns common take sequencing behind the Studio attempt authority and engine store. | Foreground exit takes bounded background time, requests typed shutdown cancellation, waits for the barrier, then releases runtime resources and suspends database work. This is cancellation/cleanup time, not a promise of background GPU generation. |
| History | [`GenerationPersistence`](../../Sources/SharedSupport/Services/GenerationPersistence.swift) hands off playback, writes durable outbox intent, and commits through [`DatabaseService`](../../Sources/iOSSupport/Services/DatabaseService.swift)'s GRDB queue; [`GenerationMigrations`](../../Sources/SharedSupport/Database/GenerationMigrations.swift) owns v1–v7. | Successful SQLite acceptance retires intent. Failed enqueue is visibly recoverable in-session but is not crash-safe. Reconcile handles pending writes, clear/delete journals, and deferred audio removal. Moved-root repair rebases absolute paths only when the old root is gone and the replacement audio exists. Unavailable History is never presented as empty. |
| Model delivery | Exact production catalog identity produces `ArtifactDeliveryPlan`; [`HuggingFaceDownloader`](../../Sources/QwenVoiceCore/HuggingFaceDownloader.swift) stages pinned files, verifies size/hash, and atomically installs; `LocalModelAssetStore` authenticates local reuse. [`IOSModelDownloadCoordinator`](../../Sources/iOS/IOSModelDownloadCoordinator.swift) owns one background session and one active model. | iOS persists cancellation before cancelling tasks, fences queued progress, restores ledger requests, adopts matching tasks, and defers UIKit completion until postprocessing is durable. Stale operation generations cannot update a newer install. Shared-component identity never substitutes an unverified local file. |
| CLI | [`CLIRuntime`](../../Sources/VocelloCLI/CLIRuntime.swift) builds the same in-process engine; registry-only discovery avoids engine initialization. Generate/prime/enroll entry points enforce invocation-scoped clone consent. | [`CLIProcessSupervisor`](../../Sources/VocelloCLI/CLIProcessSupervisor.swift) owns signals, cancellation, child cleanup, and explicitly classified forced exit. Engine cancellation is distinct from caller signal cancellation. CLI output and provenance must correspond to a published file, not merely a completed model loop. |
| Website | [`website/package.json`](../../website/package.json) defines React/Vite authoring, SSR/prerender, copy/render contracts, and Playwright browser smoke. Public release facts and sample data are local contract inputs. | Source validation alone cannot prove rendered markup, loading races, audio controls, or responsive layout; built/rendered and browser checks cover different boundaries. Website checks must route when their external fact inputs change. |
| Diagnostics/benchmarks | Typed generation records, JSONL sinks, merger, v9 streaming sidecars, and build receipts feed canonical scripts. [`benchmarking-procedure.md`](../reference/benchmarking-procedure.md) and the memory/quality contracts own admissibility. | Safe diagnostic classifications exclude raw scripts, transcripts, paths, and arbitrary reflected errors. Exact source/executable identity, fixed seeds, optimization receipts, quiet-host status, sampler coverage, and compatible baseline rules constrain publishable comparisons. Fast QC gates and report-only QC v2 have different authority. |
| CI/release | [`ci.yml`](../../.github/workflows/ci.yml) routes contracts, Python, deterministic native tests, TSan, device-SDK compilation, UI-bundle compilation, website, and dependency submission to `CI required`. [`release.yml`](../../.github/workflows/release.yml) builds an authorized source commit. | Ordinary CI executes no native UI or model/device lane. Release source authority, signed tag/commit continuity, managed verification manifests, archive/IPA checks, evidence hashes, attestations, and reviewer-gated promotion protect publication. A local success or hook result cannot replace these authorities. |

The [architecture reference](../ARCHITECTURE.md) retains detailed policy and dependency
descriptions. The smallest useful change normally stays within one owner and its boundary tests;
a second engine, new task owner, parallel persistence path, or independently constructed terminal
state increases risk more than it improves iteration speed.

## Coverage map

Presence in this table means inspected test/target wiring, not execution in this audit.

| Critical behavior | Deterministic evidence | What still needs a different lane |
| --- | --- | --- |
| Cancellation, lease, and terminal ordering | `ActiveGenerationCoordinatorTests`, `GenerationOutputAdapterChoreographyTests`, `GenerationEventDeliveryProbeTests`, owned `Qwen3RuntimeTests` synthetic sessions. | Loaded-model `GenerationOutputAdapter.run` with concrete `EngineReservedTake`, limiter, file writer, telemetry, and event transport together. Existing helper-level choreography coverage is real; concrete integration remains a gap. |
| Atomic WAV and quality contract | `AtomicWAVPublicationTests`, `AtomicWAVGenerationOutputSinkTests`, `GenerationQualityReportProducerTests`, `GenerationTerminalCleanupTests`. | Model/codec output stability, audible continuity, ASR/prosody quality, and real device playback require the existing model/diagnostic or listening lanes. |
| Store and Studio orchestration | `TTSEngineStoreTests`, `StudioGenerationCoordinatorTests`, `MacStudioSingleTakeRunnerTests`, `IOSSingleTakeGenerationExecutorTests`, and ownership/attempt tests. | App composition, lifecycle callbacks, system audio session, TCC/permissions, and visible control behavior need platform runtime and XCUITest evidence. |
| History and migrations | Outbox, enqueue, page, deletion, recovery, long-form acceptance, and seed tests; populated previous-schema upgrade fixtures are added by this migration. | Real backup/restore, filesystem failures, process death at journal boundaries, and iOS suspension need targeted integration/device evidence. Existing fresh-schema tests alone did not establish old-data preservation. |
| Model delivery | `ProductionModelCatalogTests`, `LocalModelAssetStoreIntegrityTests`, shared component tests, downloader lifecycle/chunk scheduling tests, pure ledger and cancellation-sequence tests. | Coordinator-level background-session orchestration is not in the app-host-free test target. `VocelloiOSModelDownloadUITests` supplies explicit opt-in physical-iPhone proof, independent of ordinary smoke/benchmark/CI. |
| Tooling and guards | Python behavioral tests, contracts, privacy scans, regeneration/routing/worker/triage fixtures. | A trusted fresh Codex session must confirm discovery and hook delivery. Parsing a hook config does not prove that the host activated it. |
| Platform compilation | Generic physical-device SDK app/logic compile and affected macOS/iOS `build-for-testing` UI bundles. | Compilation proves API/target compatibility only. The app-host-free iOS logic assertions execute through the macOS core target; the standalone iOS bundle is compile-only. |
| Performance and memory | Telemetry/schema/admissibility tests and policy contracts. | Measured canonical device/model lanes on a committed checkpoint, with delegated work stopped/joined, are required for performance claims. Dirty/exploratory or busy-host runs cannot establish a qualified trend. |

## Findings and migration disposition

Severity here describes engineering impact. A coverage gap is not a reproduced product failure.
The first four entries are demonstrated baseline workflow/test weaknesses addressed by the
Codex migration; final acceptance must cite the integration checks rather than this static review.

| ID / severity | Evidence at baseline | Disposition and required acceptance |
| --- | --- | --- |
| CW-01 / P2 | `regenerate_project.sh` publishes only `project.yml.sha256`; `build_cache.sh` compares only that digest; `development_workflow.py` requests regeneration only for `project.yml`. A newly added source can therefore leave generated target membership stale. | Replace the three decisions with [`project_generation.py`](../../scripts/project_generation.py)'s common signature over specifications, generator inputs, and membership. Prove add/delete/rename and missing-output regeneration; content-only source edits must keep incremental reuse. |
| CW-02 / P2 | `host_preflight.sh` counts `git worktree list --porcelain` entries beginning `locked` as active agents. A retained lock is not a live worker; an active worker need not own a locked worktree. | [`active_workers.py`](../../scripts/active_workers.py) and lifecycle hooks track live ownership and reject stale/reused-process identities. Preserve load, memory, native-lock, and exploratory classification. If tracking is unavailable, measurements use lead-only execution. |
| CW-03 / P2 | Hook normalization understands Claude `Edit`/`Write` payloads; configuration, CI classification, and invariant scans name `.claude`/`CLAUDE.md`. Copying settings would miss Codex patch paths and leave new configuration untested. | Migrate instructions, skill discovery, agents, hook schema/payload adapters, routing, scanners, and direct checks together. Cover multiple-file patches, renames, spaces, managed worktrees, and inactive-hook reporting. Hooks supplement repository checks and do not become release authority. |
| CW-04 / P2 coverage/reliability | Baseline seed tests migrate an empty database; coordinator assertions include fixed yield counts and 50 ms sleeps in `ActiveGenerationCoordinatorTests`. These do not prove a populated old-schema upgrade or establish that the competing task entered its critical boundary. | Add populated upgrade fixtures without editing shipped migrations; replace selected scheduler assumptions with explicit fake/continuation synchronization and bounded test completion. Preserve XCTest and app-host-free execution. |
| CW-05 / P2 characterized migration invariant | A populated v2 fixture retaining row 41 after deleting row 900 characterizes the v3 rebuild: copying survivors into `generations_v3` and dropping/renaming the old table reduces `sqlite_sequence` from 900 to 41; the next insert obtains 42. This contradicts the assumption that historical IDs are never reused across that upgrade. | Record `GenerationMigrationUpgradeTests.testV3RebuildCurrentlyResetsDeletedHighWaterToLargestRetainedID` in [`DatabaseServiceTests.swift`](../../Tests/VocelloCoreTests/DatabaseServiceTests.swift) and a dedicated roadmap follow-up. The native test author independently reproduced the same DDL with Python sqlite3; native GRDB execution remains pending integration validation. Do not alter the shipped v3 migration in workflow work. No current-user data-loss incident or reachable journal failure is established by this characterization; repair strategy and upgrade compatibility need separate design. |
| CW-06 / P2 coverage gap | Production `GenerationOutputAdapter.runReservedTake` is tested over `ScriptedReservedTake`; concrete `run` construction and the complete loaded-model output path are not tested together by that fixture. | Defer a bounded production-adapter integration seam; retain helper tests and explicit model proof. This refines October E7-02/DA-09 rather than reopening the old claim of zero choreography coverage. |
| CW-07 / P2 coverage gap | Pure ledger, cancellation ordering, and downloader tests exist, but `IOSModelDownloadCoordinator` itself is absent from the standalone app-host-free compile list. Its concrete background-session construction and AppPaths/relay ownership couple it to the app. | Defer dependency injection for coordinator orchestration (restore/adoption, cancel-progress fencing, durable UIKit completion, operation-generation staleness). Keep the opt-in real-iPhone lifecycle lane; do not silently add downloads to CI. |

### Reconciliation with existing work

- October A2-01 is already addressed by `DatabaseService.rebaseMovedAudioPaths`; outbox repair
  follows the shared moved-root rule. Absolute storage itself is not evidence of an unfixed restore bug.
- October E7-02 now has production-helper choreography tests. The remaining concrete integration
  boundary is narrower and is recorded as CW-06. Shutdown/terminal and memory-policy assertions
  likewise do not prove actual allocator calls or loaded-model state transitions.
- Existing DA-04/05/06/07/12/13 retain ownership of one-token inputs, global caches, cancelled
  prewarm, device playback/recording, and prior tooling/UI follow-ups. This review neither repeats
  them as new findings nor declares them resolved without their required evidence.
- September/October benchmark and QC decisions remain authoritative. Report-only QC v2 is not a
  replacement for shipping Fast QC, calibrated promotion gates, or recorded human listening.

## Operating conclusions

The existing repository already has strong contracts, retained evidence, exact dependency/catalog
identities, target isolation, and scripts for expensive lanes. Codex should improve access to those
authorities rather than create competing build, device, measurement, or release pipelines.

The development loop is targeted tests and changed-file lint while editing, routed checks and diff
review before a scoped commit, then the smallest relevant explicit runtime/model/UI lane at a
coherent committed checkpoint. Use [`workflow_diagnostics.py`](../../scripts/workflow_diagnostics.py)
through `scripts/dev.sh doctor` for read-only capability inventory and `triage` for retained-run
classification. An infrastructure failure, interruption, incomplete evidence, and product failure
must stay distinguishable; retain failed attempts and identify any justified rerun separately.

Repository instructions and skills must remain useful with no personal plugin installed. Axiom,
MLX guidance, authoritative documentation tools, verified diagnostic helpers, XcodeBuildMCP,
browser inspection, and GitHub inspection can improve a session, but scripts own canonical evidence.
No global configuration mutation, dependency repin, new large asset download, push, external write,
deployment, or release is implied by read-only readiness or local validation.
