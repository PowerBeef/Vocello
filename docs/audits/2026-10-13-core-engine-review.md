---
status: active
owner: backend-and-platform
reviewed: 2026-10-13
summary: Read-only, Axiom-led review of the core engine backend (runtime, model lifecycle, generation, persistence, model delivery, storage, memory, energy, performance, security, serialization and tests) with an architecture map; one crash-class candidate, not reproduced by its first device check, awaits the maintainer's classification, three findings attach to release items, and the rest is parked in the post-3.0 backlog.
sourceOfTruth:
  - Sources/QwenVoiceCore/MLXTTSEngine.swift
  - Sources/QwenVoiceCore/NativeEngineRuntime.swift
  - Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Engine.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift
  - Sources/iOS/QVoiceiOSApp.swift
  - Sources/iOS/TTSEngineStore.swift
  - Sources/SharedSupport/Database/GenerationHistoryOutbox.swift
  - Sources/QwenVoiceCore/HuggingFaceDownloader.swift
  - config/roadmap.json
---
# Core engine backend review

**Date:** October 13, 2026. **Baseline:** `7e50a12a`. Engine, package and app sources are unchanged
from it through `c08a1360`, which added tests and tooling only.

This review was read-only. The auditors built, ran and measured nothing, so every size, launch count
and timing below is arithmetic from code, not a measurement. The lead verified the crash chain in
[BG-1](#bg-1-gpu-work-can-outlive-the-foreground) against the source and Apple's documentation.

## Summary

- **One crash-class candidate (BG-1).** GPU work can keep running after the app leaves the
  foreground. iOS refuses any command buffer committed in the background, and MLX turns that refusal
  into a C++ exception thrown on a Metal thread, which ends the process. The most likely trigger:
  choose a saved voice in Clone, or save a voice, then switch apps within a few seconds. Three audits
  found it independently. The first device check passed: in three fresh processes the app survived
  leaving 0.3, 1.5 and 3.0 s after the Clone handoff, with a clean crash delta
  (`ios-xcui-smoke-20261013-232424-a8c32853`). That run cannot show a warm-up was in flight, so the
  path is not reproduced rather than refuted, and the other three paths have no device check.
- **No other new release blocker.** No crash, hang, data loss, broken purchase or privacy-label
  mismatch was found that a 3.0 user can reach in ordinary use. Four findings fall inside three
  existing release items and are recorded there:
  - SER-1 on F-16: an unreadable long-form journal keeps new takes out of History, and Export is its
    only exit.
  - SER-2 on RF-13: the full player's export gate fails open for a saved voice whose metadata sidecar
    cannot be decoded.
  - SEC-4 and SEC-6 on ASR-06: drafts outside the path contract, and the protection class for voices
    and History.
- **Close calls for the maintainer:** [F-06](#known-items-that-are-worse-than-titled) (data loss after
  an earlier failure plus an explicit confirmation), DB-3 (a narrow 0xDEAD10CC window) and SEC-2 (the
  privacy page's "none of this is uploaded" next to iOS backups).
- **The largest backlog themes.**
  - Cancellation does not reach model load, warm, clone priming or finalization.
  - Several crash-stranded file families have no sweeper, and iOS reclamation never frees anything.
  - History has fail-closed states with no exit.
  - Failed iPhone model installs restart on every launch.
  - The token loop is host-bound at about 2,900 kernel launches per frame, with roughly 30% removable.

## Method

The audits ran as Axiom agents on the baseline. Each separated verified facts from inferences and
cited file and line. The lead verified BG-1's chain, every finding attached to a release item (SER-1,
SER-2, SEC-2, SEC-4, SEC-6, STOR-1, F-06) and every roadmap cross-reference. Other findings carry their
auditor's evidence and confidence.

| Area | Axiom agent | Result |
|---|---|---|
| Storage | storage-auditor | FRAGILE: 3 P2, 3 P3 |
| Concurrency | concurrency-auditor | NEEDS WORK: 1 P2, 6 P3 |
| Memory | memory-auditor | 1 P2, 5 P3 |
| Performance | swift-performance-analyzer | 11 ranked levers |
| Model delivery | networking-auditor | 4 P2, 1 P2 needing a device, 5 P3 |
| History persistence | database-schema-auditor | 3 P2, 3 P3 |
| Energy and background | energy-auditor | 2 crash class (BG-1), 1 P2, 8 P3 |
| Security and privacy | security-privacy-scanner | HARDENED: 0 P1, 0 P2, 8 P3 |
| Serialization | codable-auditor | 3 P2, 6 P3 |
| Tests | testing-auditor | GAPS: 5 P1, 7 P2, P3 hygiene |

Finding IDs keep each audit's own prefix. This review adds BG-1, the EN prefix for energy, SEC for
security and privacy, and TEST for tests.

## Architecture map

### Layers and isolation

- **Layering.** `QwenVoiceBackendCore` ← `QwenVoiceCore` ← apps and CLI. The owned package
  `Packages/VocelloQwen3Core` (SwiftPM name `MLXAudio`) is reached only through the `VocelloQwen3Core`
  facade. No `MLXArray` crosses into `Sources/`: only PCM as `[Float]`, epoch-bound clone handles and
  scalar facts.
- **MainActor.** `MLXTTSEngine` holds published state, the `activeModelOperation` single-flight gate
  (load, prewarm, prime, generation), the critical-relief admission latch, idle unload and pressure
  tasks. `TTSEngineStore` sits above it on iOS.
- **Actors.**
  - `ActiveGenerationCoordinator`: one registration, a typed reason and the termination barrier.
  - `NativeEngineRuntime`: the prewarm slot, warm and prime identities.
  - `MLXModelLoadCoordinator`: the loaded model and its load epoch.
  - `NativePreparedCloneConditioningCache`, the global audio-preparation queue, and
    `PreparedVoiceRepository` (flock with `LOCK_NB`).
  - `VocelloQwen3Engine`: the operation lease, the reservation lifecycle and clone records. It runs the
    token loop on its own executor.
- **Lock-isolated.** The cancellation controller and ingress (first reason wins), the prewarm gate, the
  event router and the process-global caches (component and resident tokenizer, prefixes, decoder
  buckets).
- **Escape hatches.** `@unchecked Sendable` is at 33 of 33 registered entries and `nonisolated(unsafe)`
  at 6 of 6 (`config/concurrency-safety.json`). There is no headroom.

### One take

1. The view's coordinator calls `TTSEngineStore.generate` (admission). It starts a MainActor event
   drain and a 1 Hz memory guard.
2. `MLXTTSEngine.generate` registers a start-gated Task with the coordinator. The Task runs
   `prepareGeneration` on the runtime actor: load if needed, then warm or prime.
3. `session.run` reserves, claims and opens the engine session. The token loop checks cancellation every
   token. Audio moves through a bounded, suspending, lossless PCM channel.
4. The adapter limits and writes PCM into a hidden staging WAV beside the destination. Then come
   fsync, AudioSeal marking (on the GPU), Fast QC (CPU, Accelerate), a SHA-256 digest and the rename
   that publishes the file.
5. `GenerationPersistence` writes an outbox entry (`.writing` renamed to `.json`), commits an idempotent
   GRDB row, then removes the entry.
6. Cancel order: the ingress records the typed reason, cancels the Task, forwards the engine reason, and
   ends at `.cancelled(reason)`.

### Model lifecycle

- **Load.** `MLXModelLoadCoordinator` hashes the weights on a first or changed load and builds the model
  through the package loader. Weights are evaluated in layer batches. Nothing in that path checks
  cancellation (CONC-1).
- **Warm and prime.** `warmPreparedInputs` and clone priming run under the prewarm slot. Clone priming
  encodes the reference through the Mimi encoder (Clone only).
- **Proactive work.** On iPhone, choosing a saved voice in Clone starts a proactive load and prime.
  Saving a voice starts a prompt prebuild. Neither has a cancel hook (BG-1).
- **Unload.** An idle unload runs after 30 s on iPhone. A full unload releases weights, the engine
  actor, clone records, host caches and the MLX cache, and on iPhone every Qwen3 static. On macOS the
  resident speech tokenizer survives, with the encoder and its KV after Clone use (MEM-1).

### Foreground exit (iPhone)

- `.background` reaches `handleForegroundExit` (`Sources/iOS/QVoiceiOSApp.swift:235`).
- It cancels the Studio take, long-form run or segment regeneration through the typed barrier with
  `.shutdown`, any unowned generation, and the clone-prime token. It then unloads the model (`:457`).
  The unload queues behind any in-flight model operation (`MLXTTSEngine.swift:413-458`).
- Background time is requested only when
  `hasActiveGeneration || studioWork != .idle`
  (`Sources/iOSSupport/Services/IOSBackgroundGenerationPolicy.swift:70`).
- `hasActiveGeneration` ignores the `preparingVoiceReference` running state
  (`Sources/iOS/TTSEngineStore.swift:705-712`).
- There are no background modes, no BG task APIs, and one grant that is always ended.

### Persistence

- One GRDB `DatabaseQueue` per process, in rollback-journal mode with `busyMode` `.immediateError`. One
  table, `generations`, migrated v1 to v8 append-only (v3 rebuilds it). There are no foreign keys, no
  `ValueObservation` and no pragmas.
- The store sits in the App Group container on iPhone and in Application Support on the Mac. iOS
  suspends it when the app is about to be suspended (IOS-11).
- Recovery: startup and every History open run `GenerationHistoryRecovery.reconcile()`. That resumes a
  clear transaction, scans and commits outbox entries, and retries pending audio removals.

### Model delivery

- **Planning.** Catalog artifacts carry repository, revision, size and SHA-256. The shared tokenizer is
  reused when the content store verifies it.
- **Requests.** `GET /<repo>/resolve/<rev>/<path>` to `huggingface.co`, redirected only to
  `huggingface.co` or `*.hf.co`. The only header sent is `Range`.
  - Mac and CLI: 64 MiB ranges, 4 workers per file.
  - iPhone: one background `URLSession` with 128 MiB ranges submitted up front, Wi-Fi only, waiting for
    connectivity, and a ledger.
- **Activation.** Every file is checked for size and SHA-256. Shared blobs are published to a
  content-addressed store and a hard-linked replica is swapped in atomically under a flock. Unverified
  bytes are never activated.

### Storage roots

macOS uses `~/Library/Application Support/QwenVoice/`; iPhone uses `<App Group>/Vocello/`.

| Store | Owner | Deleted by | Backup (iPhone) |
|---|---|---|---|
| `models/<folder>` and `models/.qwenvoice-components-v1/{blobs,staging,trash}` | `SharedModelComponentStore` | `deleteModel` (tombstone, trash, unlink); reclaim (STOR-1) | Excluded |
| Download staging, `delegate-files/`, the iPhone delivery ledger | Downloader; `IOSModelDownloadLedgerStore` | Success or `discardStaging`; `delegate-files/` never (STOR-4) | Excluded |
| `cache/native_mlx/prepared_models/` | `MLXModelLoadCoordinator` | `deleteModel`; 1 h sweep | Excluded |
| `outputs/{CustomVoice,VoiceDesign,Clones}/` | `GenerationOutputAdapter` | History delete or clear; 1 h staging sweep; PA-30 review | Included |
| `history.sqlite`, `history-outbox/`, clear marker, removal list, long-form journals | `DatabaseService`, outbox and long-form stores | Commit, clear, set-aside | Included |
| `voices/` with `.clone_prompt/` and `.qvoice_clone_prompts/` | `PreparedVoiceRepository` | Tombstone delete; prompts keep 8 | Included |
| `cache/normalized_clone_refs/`, iPhone `cache/imported_references/` | Clone cache; `LocalDocumentIO` | A8-01 and abort paths only (STOR-3) | Excluded |
| `diagnostics/` | Loggers | Caps (200 records, 5 MB, 256 KB) | Excluded |

### Memory ownership

- **Weights.** Held only through `ModelBox`, then `VocelloQwen3Engine.loadedModel`, then
  `MLXModelLoadCoordinator.loadedModel`.
- **Per take.** Talker KV is 112 KiB per token, so 224 MiB at the cap. Decoder streaming KV is reset in
  a `defer`. Code-predictor plan buffers are per generation. Nothing keeps a whole take in memory
  besides the WAV, except marking (about 47 MB at the 163.8 s cap).
- **MLX buffer cache.** Capped at 128 MiB on iPhone, 256 MiB floor Mac, 512 MiB mid and 1 GiB high.
- **Clone prompts.** The actor holds at most one prompt, released after each take. The host cache holds
  1, 8 or 16 value handles plus decoded reference audio.

## BG-1: GPU work can outlive the foreground

**Class: crash. Status: candidate. Paths a and c were not reproduced on the iPhone with the work in
flight; b and d are uncovered. The maintainer classifies it (BG-01).**

### What is verified

1. **iOS refuses background GPU work.** Apple's
   [Preparing your Metal app to run in the background](https://developer.apple.com/documentation/metal/preparing-your-metal-app-to-run-in-the-background)
   says that after an app moves into the background, Metal returns an error for any new command buffer
   (`MTLCommandBufferStatus.error`, `MTLCommandBufferError.Code.notPermitted`). It also tells apps to
   stop sending work to Metal when they are deactivated.
2. **MLX turns that error into a process abort.** `check_error` in the pinned mlx-swift's
   `mlx/backend/metal/eval.cpp` throws `std::runtime_error` from the command buffer's completion
   handler. That block runs on a Metal thread outside any task, so the exception terminates the process.
   The facade's own documentation agrees that `VocelloQwen3MLXErrorScope` cannot capture it
   (`Packages/VocelloQwen3Core/Sources/VocelloQwen3Core/Runtime.swift`, "Real coverage is narrower").
3. **Proactive model work gets no background time and no cancel.**
   - The grant rule and the `hasActiveGeneration` exclusion are quoted in
     [Foreground exit](#foreground-exit-iphone). A proactive load publishes no `.running` state.
   - Nothing cancels the proactive load (`ensureModelLoadedIfNeeded`) or the saved-voice prompt
     prebuild, which holds a `.clonePriming` operation with no handle (`MLXTTSEngine.swift:2283-2308`).
   - The unstructured Task in `primeSelectedCloneVoiceProactively`
     (`Sources/iOS/IOSGenerationModeViews.swift:2319-2339`) is never cancelled.
   - The clone-prime token is checked only between steps.
4. **Load, warm and finalization have no cancellation checkpoints (CONC-1).**
   - The package loader and `warmPreparedInputs` contain no `checkCancellation` after `Qwen3TTS.swift:4372`.
   - The comment at `Engine.swift:556-563` claims "the loader's own cooperative checkpoints"; there are
     none.
   - In the output adapter, marking (GPU) and Fast QC run after the last cancel check
     (`GenerationOutputAdapter.swift:2056`, then `:2129-2155`).

### Paths into the window

| Path | Trigger | Grant? | Cancellable? |
|---|---|---|---|
| a. Proactive Clone load and prime | Choose a saved voice in Clone, leave within seconds | No | No |
| b. Saved-voice prompt prebuild | Save a voice, leave within seconds | No | No |
| c. Cold load or warm inside a take | Generate on a cold model, leave during the load | Yes | No |
| d. Marking after the last check | Leave in the last moments of a take or segment | Yes | No |

A grant keeps the process running, so on paths c and d it widens the window instead of closing it.

### What is still inferred

- Whether every phase submits Metal work. Weight evaluation may run only CPU `Load` primitives; prime,
  warm and marking dispatch kernels.
- How long the window is between `.background` and suspension when no grant is held.
- Whether GPU access is revoked before UIKit delivers `.background`.

### Device check

`scripts/ui_test.sh ios smoke --scenario background-warmup` (c08a1360) covers path a. In three fresh
processes it presses Home 0.3, 1.5 and 3.0 s after the Clone handoff, waits 15 s and returns. The
process must still be running and the lane's crash delta must stay empty.

- **First run, October 13:** PASS (`ios-xcui-smoke-20261013-232424-a8c32853`). Home came 1.8, 3.0 and
  4.5 s after the tap on the saved voice, and the app was running at every return. That test proved
  survival only (TEST P1.1).
- **Second run, October 13 (BG-01):** PASS (`ios-xcui-smoke-20261014-013015-ab48517b`). The scenario now
  waits for visible in-flight states and attaches what each pass observed:
  - path a: three passes left while the composer's readiness row read "Preparing reference";
  - path c: three passes tapped Generate on a cold Built-in model and left while Stop showed with no
    live preview yet.
  All six left with the work in flight, and the app survived each 15 s dwell with a clean crash delta.
- **Not covered:** path b (the prompt prebuild after Save voice) and path d (marking at a take's end)
  show no visible state a test can wait for; covering them needs an app-side diagnostic event.
- **Reading:** paths a and c are not reproduced with the work proven in flight. Apple's article allows
  "some time before the system restricts your app from using Metal" after deactivation, which may
  cover these short phases.

### Fix shape, for planning only

1. A GPU-permitted gate, closed at `.inactive` and reopened at `.active`, as Apple's article directs. Load
   batches, warm and prime stages, clone-prompt stages and marking windows check it and throw
   `CancellationError`.
2. Cancel proactive operations at `.inactive`: clear the prime token, cancel stored handles for load,
   prime and prebuild, and refuse proactive work until `.active`.
3. Real cancellation checkpoints in the loader, `warmPreparedInputs` and before marking (CONC-1). Correct
   the `Engine.swift` comment, and make `performLoad` discard rather than commit on `.shutdown` and
   `.memoryPressure`.
4. Count an in-flight model operation in `requestsBackgroundTime`, so the unload can finish under a
   grant.

## Findings by area

Severities are the auditors': P2 is a real defect with bounded impact, P3 is latent or hygiene.

### Cancellation and lifecycle

- **CONC-1 (P2).** No cancellation checkpoints in load, warm, prepared-cache hashing or finalization,
  so every cancel and relief barrier waits them out. Mac `.warning` soft trims block on the prewarm
  slot while holding the pressure executor's only response slot. Part of BG-1's fix.
- **CONC-2 (P3, latent).** A cancelled caller turns mandatory relief into a silent skip that is then
  published as success (`NativeEngineRuntime.swift:660-665`).
- **CONC-3 (P3, latent).** The resident speech-tokenizer hand-off shares one mutable decoder across model
  instances, contrary to its comments and the registry. It is safe today only because loads are
  serialized and the old model is dropped first.
- **CONC-4 (P3).** The prompt-prebuild Task has no handle. `latestEventDrainTask` is never recreated
  after `stop()`.
- **CONC-5 (P3).** Blocking IO on the MainActor and actors: Files import and export through
  `DocumentIO`, the `deleteModel` flock taken on the MainActor (a CLI install freezes the UI), and
  synchronous SHA-256 on the clone cache actor.
- **CONC-6 (P3).** The global audio-normalization queue is uncancellable and can wedge behind a hung
  AVFoundation decode.
- **CONC-7 (P3).** The registry claims a lock on the shared `PCM16ScratchBuffer` that does not exist.
- **Improvements.** Pin off-main execution with `@concurrent` before anyone enables
  `NonisolatedNonsendingByDefault`. Widen the TSan lane to the fixture-model suites. Add a watchdog to
  the uncancellable terminal wait. Buffer pressure events newest-only. Wire or delete the engine relief
  API.

### Memory

- **MEM-1 (P2).** The Mimi encoder's KV cache stays resident after every clone-reference encode.
  - `trim` only moves the offset in the pinned mlx-swift-lm `KVCacheSimple`, and a longer reference
    concatenates onto the stale buffer.
  - Size: 8 to 24 MiB on iPhone, where references last at most 20 s, and about 96 MiB for a 120 s Mac
    reference. A session of ever-longer references can reach about twice the longest.
  - Fix: build the cache per `encode`.
- **MEM-2 (P3, latent).** The actor's relief API has no product caller, and its order would strand
  weights in the MLX cache once wired. `docs/ARCHITECTURE.md` describes clone-handle invalidation on
  critical trim that the product path does not perform.
- **MEM-3 (P3).** Late-failure exits of a take (QC rejection, marking, an unreadable staging WAV,
  publish) skip the allocator clear, leaving up to the cache limit until the idle unload.
- **MEM-4 (P3, the same defect as CONC-4's drain Task).** After `stop()` then `initialize()`, the
  latest-event bridge stays dead.
- **MEM-5 (P3).** Per-session bookkeeping grows with every distinct clone reference or prewarm identity
  until the next load or hard trim (about 5 KiB each).
- **MEM-6 (P3, telemetry builds only).** The sampler's lifetime is not tied to its owner, and its samples
  are uncapped.
- **Improvements.** Leak canaries in the package tests (active memory after encode and drop, generate
  and drop, load and unload). A post-unload baseline in the quiescence evaluator. Key the text-tokenizer
  cache by content. Default a talker KV window on iPhone.

### Storage

- **STOR-1 (P2).** On iPhone, the launch protection pass resets the reclamation clock, so startup
  reclamation never frees anything.
  - The pass recursively chmods, protects and tags every file under `models/`, which updates each
    inode's ctime.
  - Reclaim keeps anything with a recent ctime (15-minute grace).
  - Orphan blobs of up to about 0.7 GB each stay forever. This contradicts `privacy-storage.md`.
  - Fix: age entries by birth time.
- **STOR-2 (P2).** Crash-stranded install and migration replicas in `models/` are never swept. They
  hard-link a model's 1.4 to 2.1 GB of weights, so "Delete model" frees nothing, and every shared blob
  they reference is protected forever.
- **STOR-3 (P2).** Personal reference audio copies are never pruned.
  - Every iPhone import copies into `cache/imported_references/`, up to 250 MiB. Only RootView's abort
    path deletes the copy; Save, Cancel and Discard leave it.
  - Normalized references accumulate on both platforms.
  - A third party's voice memo imported to try a clone stays in the container after Cancel.
- **STOR-4 (P3).** iOS delegate temp files (128 MiB chunks, or up to 2 GB whole files) from a killed
  process are orphaned.
- **STOR-5 (P3).** The A2-01 rebase misses absolute paths in `clear-transaction.json`,
  `audio-removals.json` and long-form journals, so a restore can wedge a pending long-form journal.
- **STOR-6 (P3).** Crash-stranded clone-prompt staging (speaker embedding, codes and transcript, in the
  backed-up `voices/`), export copy temporaries in the user's own folders, and a Mac `discardStaging`
  that skips the staging lock.
- **Improvements.**
  - One storage janitor with registered families. A contract test lists every hidden-name pattern the
    code creates against its sweeper.
  - A free-space preflight before generation, long-form, enrollment and import.
  - Store audio paths relative to `outputs/`.
  - Stop swallowing staging fsync errors.
  - A Settings storage page.

### History persistence

- **DB-1 (P2).** A damaged or newer-schema clear marker has no exit.
  - `reconcile()` returns before it scans, commits or retries removals, so queued takes never commit
    and deleted audio leaks.
  - Clear All fails, and the leftover review never runs.
  - No Discard is offered, because only entry files count as unverifiable.
- **DB-2 (P2).** Row decode is all or nothing.
  - One undecodable completion receipt takes the History page offline and blocks Clear All, while new
    takes commit invisibly.
  - A non-parsable `createdAt` or `seed` traps the process at every History open, because
    `Generation.init(row:)` uses GRDB's trapping subscript.
  - Reachable only through a downgrade, a restore from a newer build, or a hand edit.
- **DB-3 (P2).** Suspension is edge-triggered.
  - A queue opened after a suspend runs unsuspended, which is the 0xDEAD10CC exposure IOS-11 removed.
    It needs the database to open while the app is backgrounded, a narrow window.
  - A suspend that lands mid-open leaves the store failed until the user taps Retry, while Studio takes
    queue silently.
- **DB-4 (P3).** A queued entry whose WAV is gone is a permanent banner with no exit except Clear All.
- **DB-5 (P3, macOS).** Deleting with a custom output folder on an unmounted volume reports success but
  leaves the audio.
- **DB-6 (P3).**
  - An unused `persist` and test-only long-form replace paths.
  - Error classification order.
  - Docs that claim WAL sidecars on a rollback-journal store.
  - A `DatabaseFunction` re-registered per search, which GRDB would `fatalError` on with an active
    statement; not reachable today.
- **Improvements.** `busyMode` `.timeout(~2s)` with a cross-process lock for `history-outbox/`. Async
  reads for page loads. A downgrade guard with `PRAGMA user_version`. `secure_delete` or a vacuum after
  Clear. Real-GRDB cancel and golden-row decode tests.

### Model delivery

- **NET-1 (P2).** Failed iPhone installs restart themselves on every launch. The restore loop requeues
  `.failed` ledger entries, so a persistent integrity failure re-downloads several GB per launch.
  `IOSModelDownloadCoordinator` is compiled into no test target (DA-13).
- **NET-2 (P2).** "Wi-Fi only" still transfers over Personal Hotspot and Low Data Mode. Only
  `allowsCellularAccess` is false.
- **NET-3 (P2).** `NSURLErrorSecureConnectionFailed` (-1200), the catch-all for resets and handoffs, is
  classified permanent, and -1011, -1014, -1017 and -996 are in neither set. A connection reset fails
  the whole install, which NET-1 then repeats.
- **NET-4 (P2).** An explicit Retry re-applies the full-size free-space gate (twice the model) before it
  reads the ledger, so a nearly finished install can be refused.
- **NET-5 (P2, needs a device).** The background-session completion handler is held until the whole
  model installs, which can be hours or days. Failure branches never call it, and the session is not
  recreated at launch. The OS consequence is unverified.
- **NET-6 to NET-10 (P3).**
  - "No cookie" is asserted but not enforced in the session configuration.
  - The chunk sidecar trusts size, not artifact identity.
  - Mac and CLI transfers do not wait for connectivity and have no power assertion or free-space
    preflight.
  - A sub-second window lets Install start a second run.
  - Wording and fail-open defaults.
- **Improvements.**
  - No device download has run since the September 26 hardening (`4eff69d2`), which added the
    completion-time allowlist, the ceilings and the resume-URL check; the last device runs are from
    September 23. The check falls back to `currentRequest?.url`, so a missing final URL is unlikely, and
    RF-15 runs the shipping model download on the processed build. An earlier
    `scripts/ui_test.sh ios model-download --scenario acceptance` run on the development build would
    surface a failure before the freeze; it downloads models, so it needs the maintainer's go-ahead.
  - A `URLProtocol`-stubbed downloader suite.
  - Retry jitter.
  - Make `RepoFile.sha256` mandatory in production.

### Energy

- **EN-1 (P2).** The inline player card's 15 Hz display link keeps running for a paused or finished
  card, which is the resting state after every take
  (`Sources/iOS/Studio/IOSStudioInlinePlayerCard.swift:675-679, 848-854`).
- **EN-2 (P3).** The download heartbeat does main-actor ledger and staging work every 5 s in production,
  then the diagnostics gate drops the result.
- **EN-3 (P3).** Repeating timers set no `tolerance`.
- **EN-4 (P3).** An opened-file import waits by polling at 10 Hz with no bound.
- **EN-5 (P3).** `AudioMarking.swift` and `AudioPublicationMarking.swift` say marking is CPU-scoped; it runs
  on the GPU. This hides part of BG-1.
- **EN-6 (P3).** Every background exit unloads the model and the idle unload is 30 s, so each app switch
  costs a cold load. Profile it.
- **EN-7 (P3).** Proactive-warm gates ignore Low Power Mode.
- **EN-8 (P3).** The shared playback session claim stays active after playback ends. This is documented
  as intentional.
- **Clean.** No background modes, balanced idle timer and sustained-performance holds, claim-based
  audio session, generation-scoped memory guard, telemetry gated off.

### Performance

The token loop is host-bound: GPU busy 49%, with MLX encoding the frame graph on the loop thread for 60
to 73% of wall time (`benchmarks/OPTIMIZATION.md` §M). By count, an iPhone frame is about 2,900 kernel
launches. Confirm each lever with one Metal System Trace dispatch count before building it.

| ID | Lever | Launches per frame | Output |
|---|---|---|---|
| PERF-1 | Talker MRoPE rebuilt every frame; use `MLXFast.RoPE` like the code predictor | −241 | Shifts numerics; needs fixed-seed evidence |
| PERF-2 | Fuse q/k/v and gate/up quantized GEMVs at sanitize | −309 | Expected identical |
| PERF-3 | Compile each sampler as `(logits, key) → token` | −177 | Same RNG stream |
| PERF-4 | Code-predictor K/V `slice_update` copies whole buffers | −140 to −150 | Identical |
| PERF-5 | Duplicate embedding gathers and 15 serial adds | −30 | Identical |
| PERF-6 | AQ-04 introspection runs with telemetry off | −9 and 2 readbacks | Identical |
| PERF-10 | Compiled code-predictor plan re-traced every take; prewarm never exercises it | first chunk | Identical |

- **Measure first.**
  - PERF-7: per-chunk `Memory.clearCache()` with 7-frame iPhone chunks.
  - PERF-8: the fixed Mimi decoder cost per chunk; SnakeBeta precompute is identity-safe.
  - PERF-9: AudioSeal's unrolled LSTMs, about 1.2 to 2.4 s after the last chunk of a 30 s take.
  - PERF-11: about 8 executor hops per frame, and an audio channel holding exactly one chunk.
- **Order.** Identity-safe first (PERF-6, PERF-5, PERF-10, then PERF-2, PERF-3, PERF-4). PERF-1 last,
  with fixed-seed QC evidence.

### Security and privacy

**Posture: HARDENED.** No code path sends user data off the device, and nothing contradicts "Data Not
Collected". The single first-party `Sources/PrivacyInfo.xcprivacy` matches the code: UserDefaults
CA92.1, file timestamps C617.1 and 3B52.1, system boot time 35F9.1, disk space E174.1, no active
keyboards, no tracking. The microphone and speech-recognition purpose strings are localized into 10
languages and accurate, since recognition requires on-device mode. There is no Keychain, account,
token, analytics or crash SDK, and `ITSAppUsesNonExemptEncryption` is false.

- **SEC-1 (P3).** Exported and auto-saved files are named `<timestamp>_<first 20 characters of the
  script>.wav`, so AirDrop, Files, Spotlight and iCloud Drive show script text
  (`GenerationOutputFileName.swift`). Give shared copies a neutral name.
- **SEC-2 (P3, close call).** The privacy page says "None of this is uploaded", while a purpose string
  and the storage policy keep saved voices, outputs and History in iOS backups. Backups are not
  collection under Apple's definition. One sentence on backups would align the texts.
- **SEC-3 (P3).** A latent download client sits in the binary. The package calls `HubApi.shared` on each
  uncached tokenizer load. Its defaults point `downloadBase` at `<Documents>/huggingface`, a folder
  Files can see, and start an `NWPathMonitor`. Today only `configuration(fileURL:)` runs, and the
  snapshot-download entry points are unreachable from the facade. The invariant that guards
  `.documentDirectory` covers `Sources/` only.
- **SEC-4 (P3).** Studio drafts (up to 30,000 characters per mode) live in UserDefaults, outside the
  storage path contract, are backed up, and are never removed (`IOSStudioDraftPersistence.swift`).
- **SEC-5 (P3).** Deleted History text may remain in SQLite free pages: no `secure_delete`, no vacuum.
- **SEC-6 (P3).** `voices/`, `outputs/` and History take `completeUntilFirstUserAuthentication`, the OS
  default. Only `models/` and `downloads/` need access while locked, so voices and History could take
  `.complete`.
- **SEC-7 (P3).**
  - Telemetry turns on from environment variables alone; an App Store user cannot set them.
  - The package writes unredacted errors to stderr outside `DiagnosticPrivacy`.
  - Telemetry reads `systemFreeSize`, a use E174.1 does not cover.
- **SEC-8 (P3).**
  - A developer `README.md` ships at the app root.
  - The default iOS entitlements file carries `get-task-allow`. The release workflow overrides it and
    the IPA verifier rejects it.
  - One entitlements file is orphaned.
- **Clean.**
  - No secrets in source, config, scripts or workflows.
  - No Now Playing or lock-screen metadata.
  - No pasteboard, Spotlight, intents, widgets, iCloud, WebView or URL scheme.
  - Only the App Group and increased-memory entitlements.
  - Imports are security-scoped and size-capped.
  - The watermark and WAV provenance carry no user or device identifier.
  - StoreKit transactions are neither logged nor persisted.
- **Not verified statically:** the signed IPA, effective attributes on a device (ASR-06), SQLite's
  secure-delete default, and how App Review reads Hugging Face's request logs (ASR-02).

### Serialization

About 400 Codable conformances in 81 files. Each date-bearing store's reader matches its writer, and
bundled contracts are strict by design. The weak spots are version skew (the Mac's stable, candidate
and fallback builds share one data root; an iPhone can restore a newer backup) and file damage.

- **SER-1 (P2, release item F-16).** An unreadable long-form journal has no exit.
  - Reads withhold its project rows but keep standalone History.
  - Every write reconciles first, so each new take stays queued, Clear All fails, and the outbox's
    Discard is hidden behind the higher-ranked recovery banner.
  - The reconcile loop stops at the first bad file. Export is the only offer, and its copy says
    exporting does not repair.
  - Triggers: truncation, a newer `version`, a moved container.
  - Fix: set aside after Export, continue past a bad file, skip and report a newer journal.
- **SER-2 (P2, release item RF-13).** The full player's export gate fails open for a saved voice whose
  `.voice.json` sidecar cannot be decoded.
  - `loadEnrollmentMetadata` returns nil on any failure, and the player maps nil to
    `.originalReference`, which needs no unlock.
  - A Design-generated voice then exports free. Triggers: a truncated sidecar or a newer schema.
  - Fix: tell absent from unreadable, and map unreadable to `.unknown`, which stays locked.
- **SER-3 (P2).** The History outbox is closed-world.
  - An entry written by a newer build counts as "damaged" and blocks clears.
  - Its only exit, Discard, renames it where no build reads it again.
  - A newer audio-removals list is set aside silently, so those takes' audio is never removed.
- **SER-4 (P3, adds to DB-2).** Two closed receipt enums make a new case break older readers. The
  resulting `DecodingError` lands on a Retry that can never succeed.
- **SER-5 (P3).** Studio drafts decode all or nothing with `try?`, and the next background save overwrites
  an unreadable blob, losing the script.
- **SER-6 (P3).** A bad legacy v1 download ledger is never quarantined. It aborts restore on every launch.
- **SER-7 (P3).** No JSON persistence path syncs before its rename.
- **SER-8 (P3).** `Generation` is stored in three date dialects (ms since 1970, reference-epoch seconds,
  GRDB text).
- **SER-9 (P3).**
  - Version-skew policy differs by store: an unreadable integrity manifest fails open, a
    shared-components manifest fails closed, and one bad shared manifest silently disables all
    reclaim.
  - `try! decode("{}")` would trap at model load if a required key were ever added.
- **Clean.**
  - The saved-voice transaction store and the iPhone ledger already skip newer files and quarantine bad
    ones, never deleting.
  - The failure journal decodes per line.
  - Persisted formatters set a POSIX locale.
  - Purchase state is never persisted.

### Tests

VocelloCoreTests runs 1,238 XCTest methods (iOS-logic tests included), the package 193 and XCUITest
61. Swift Testing is not used. State machines and stores are deeply tested; the lifecycle glue that
joins them is not.

These sources are compiled into no test target:
- `IOSModelDownloadCoordinator` and `IOSModelInstallerViewModel`
- `GenerationHistoryRecovery` and `GenerationPersistence`
- `IOSLeftoverAudioCleanup`
- `QVoiceiOSApp`, `AppModel` and `IOSBackgroundGenerationController`

- **TEST P1.1.** Leaving during proactive model work is untested.
  - The exit plan has no input for it, and no test cancels a suspended operation.
  - The device check proves survival only.
  - Smallest tests:
    - a `hasProactiveModelWork` input pinned in `IOSBackgroundGenerationPolicyTests`;
    - an explicit-unload-during-proactive-load test over the existing suspending coordinator;
    - a store that refuses proactive work while backgrounded.
- **TEST P1.2.** Leaving during marking or publish is untested. `AtomicWAVPublicationTests` can run
  `publish()` in a pre-cancelled task with no production change.
- **TEST P1.3.** History persistence wiring is untested: routing, reconcile order, snapshot merging and
  the clear-all downgrade. The `.union(unqueued)` that keeps an unqueued take out of the leftover offer
  is the only guard against F-06's data loss. The roots must become injectable first.
- **TEST P1.4.** The 0xDEAD10CC guard on the real database is untested. Every suspension test builds its
  own queue, so deleting `observesSuspensionNotifications` keeps the suite green. Fix: about 15 lines
  in `DatabaseServiceTests`.
- **TEST P1.5.** Model-download restore is untested, including NET-1. Lift the decision table into the
  tested ledger and add a table test.
- **TEST P2.**
  - XCUITest still reads properties of possibly absent elements: the teardown tab read, the long-form
    closures, the download lane and the shared waits.
  - Only the purchase lane checks the dock. `revealHistoryRow` stops at hittable.
  - Lanes depend on device state, and their cleanup runs in-process, so a crash skips it.
  - 19 store tests skip on a thermally throttled host.
  - Marking failure tests never check that the staged WAV is unchanged.
  - F-18 cites tests of an unshipped sink.
- **TEST P3.**
  - `try! XCTUnwrap` traps the bundle.
  - Helper-process tests pass vacuously when run alone.
  - Test order is encoded in names.
  - Fixed sleeps in unit tests, and repeated language-picker walks.
- **Adequate.**
  - Generation-level cancel and terminal wiring over a real engine.
  - Relief against an in-flight load.
  - The outbox, database, long-form and download internals.
  - The package actor suite and async test hygiene.

## Known items that are worse than titled

- **F-06.** PA-30's one-time leftover review offers to delete any unreferenced WAV older than the
  session.
  - A take whose outbox enqueue failed in an earlier session is held only in memory. After a kill it
    looks exactly like a leftover.
  - The user must confirm, but the deleted file can be the take's only copy.
- **DA-05.**
  - The macOS survivors include the encoder and its KV (MEM-1) and up to three text tokenizers, so the
    fix must clear every slot.
  - On iPhone, the model switch clears the caches first, so Phase 9 residency never engages.
  - Sixteen direct `Memory.clearCache()` calls bypass `NativeMLXAllocatorControl`.
- **DA-06 (E1-02).** Every cancel of a warm lands at its trailing check, after the full warm, and then
  unloads the model and its primed state. Stop during "Preparing" therefore discards the model.
- **PA-16.** Its gate should add "no encoder KV retained after encode". A window alone does not fix
  MEM-1.
- **BT-01.** The v1 retention bound (5% of RAM) cannot see constant retention like MEM-1. The quiescence
  evaluator has no post-unload baseline.
- **ASR-06.** STOR-1 is a side effect of its launch protection pass. The clone-prompt staging in STOR-6
  sits in the backed-up tree.
- **AUD-11.** The sampler is already `Set`-backed; only the gate evidence is open.

## Classification

The focus lock defines a release blocker as an App Review rejection risk, a crash or hang, data loss, a
broken purchase or restore, or a privacy or metadata mismatch on iOS.

| Finding | Class | Destination |
|---|---|---|
| BG-1 (with CONC-1, TEST P1.1 and P1.2) | Crash candidate; path a not reproduced | The maintainer decides |
| SER-1 | Inside a release item | Note on F-16 |
| SER-2 | Inside a release item | Note on RF-13 |
| SEC-4, SEC-6 | Inside a release item | Notes on ASR-06 |
| SEC-2 | Privacy-text close call | Note on ASR-02; maintainer's call |
| F-06 aggravation | Data loss after an earlier failure plus confirmation | Note on F-06; maintainer's call |
| DB-3 | Crash class, narrow and unreproduced | BKL-05 |
| CONC-2 to CONC-7, MEM-2, MEM-4 | Backlog | BKL-02 |
| MEM-1, MEM-3, MEM-5, MEM-6 | Backlog | BKL-03 |
| STOR-1 to STOR-6 | Backlog | BKL-04; STOR-1 noted on ASR-06 |
| DB-1 to DB-6 | Backlog | BKL-05 |
| NET-1 to NET-10 | Backlog | BKL-06 |
| PERF-1 to PERF-11 | Backlog | BKL-07 |
| EN-1 to EN-8 | Backlog | BKL-08 |
| SEC-1, SEC-3, SEC-5, SEC-7, SEC-8 | Backlog | BKL-09 |
| SER-3 to SER-9 | Backlog | BKL-10 |
| TEST P1.3 to P1.5, TEST P2 and P3 | Backlog | BKL-11 |
| Known items | Notes only | F-06, DA-05, DA-06, PA-16, BT-01, ASR-06, AUD-11 |

## Checked and clean

- **Concurrency.** The engine reservation and lease machine re-fetches after every await. 17
  continuation sites have no double or missing resume. No lock is held across an await. Every
  `begin…ModelOperation` has a deferred finish.
- **Memory.** No retain cycle, no unbounded per-take growth, and no closure or observer that outlives its
  owner on a shipped path. Compiled functions are freed with their owner.
- **Storage.** A2-01, A2-02, A2-04, A3-01, A3-02, A8-01, E5-01 and E5-03 still hold. The WAV publish path
  and the saved-voice journals are sound.
- **Persistence.** The outbox publish and scan race is safe in all four interleavings. Commits are
  idempotent by `audioPath`. IOS-11's suspension state machine is sound once the queue exists.
- **Delivery.** No ATS exception and no `Authorization` header. Redirect ceilings and Range validation
  are sound.
- **Hot path.** Loop instrumentation is allocation-free. Telemetry is fully gated. The limiter is a
  single unsafe-pointer pass, and Fast QC reads in bounded blocks.
