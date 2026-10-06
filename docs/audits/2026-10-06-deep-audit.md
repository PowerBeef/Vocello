---
status: active
owner: backend-and-platform
reviewed: 2026-10-06
summary: Deep whole-project audit of Vocello at 66ecb85b — 30 read-only auditors, every finding re-verified by two blind refuters; ranked confirmed defects, refuted candidates and test gaps.
sourceOfTruth:
  - config/roadmap.json
---
# Vocello: deep project audit, October 6, 2026

**Audited revision:** `main` at `66ecb85b` ("docs(qc): close QC v2 as a report-only diagnostic and return to the release plan"), clean tree.
**Status of this document:** point-in-time evidence. Open work belongs in [`config/roadmap.json`](../../config/roadmap.json), plan `project-audit-2026-10`. Finding IDs are local to this report.

## 1. Summary

**Verdict.** The core is sound. The engine's lease, reservation and terminal design left no reachable hang or double terminal; model delivery is fail-closed on every shipped path; the token loop, sampling and cancellation cadence hold; commerce has one StoreKit owner and verified-only grants; the diagnostics privacy work holds; target wiring, pins and the localization catalog are consistent. The defects are at the edges: what happens to History after a device migration, a few stuck or misleading states, guard scripts that match one spelling, and a release path whose last step is less protected than its first.

**Since the audit:** 81 confirmed findings are fixed on `main` in two passes the same day, 35 of the 41 P1 and P2 items among them, plus six that were only plausible; section 9 has the commits and what is left. The P2 items still open are E1-02, E2-01, E4-01 (each needs a model run or a maintainer decision), A7-02, A7-03 and T3-02.

**One P1 defect.**

- **History loses its audio after a restore or device migration (A2-01).** Every History row stores an absolute path inside the App Group container. The container path changes on a new install, so every restored row shows its audio as missing, although the files came back with the backup. Both verification passes confirmed it.

**The P2 defects most worth fixing before 3.0.**

- **A failed Mac engine start is silent and permanent (A14-02).** The error is swallowed, the app shows "Starting engine…" forever, and Retry does nothing because the store exists. It needs an abnormal Application Support state or a full disk to trigger.
- **A Stop accepted while a finished take is being saved still lands it in History and the Files folder**, on both platforms (A1-01, A14-52). This breaks the rule that a cancelled take never lands in History; the window is the History commit.
- **iPhone model delete removes files under a possibly running engine**, with no check and no unload (A5-01); an incomplete install cannot be removed from the iPhone UI at all (A5-02).
- **A cancelled prewarm unloads the resident model** while the UI still shows it loaded; the next take pays a full cold load (E1-02).
- **Deleting a saved voice leaves its normalized reference audio and transcript in the cache** (A8-01).
- **A download whose full-size partial fails its hash can never recover:** every retry asks for an empty range and gets HTTP 416 (E5-01).
- **One-token scripts such as "Hi" are refused** by an off-by-one guard (E4-01); the fix needs one model run to verify.
- **The commit privacy lint can be bypassed by ordinary git spellings** (T1-01, T1-02): it lists index paths and reads the working tree, so `git commit --all`, a pathspec commit or a stage-then-edit sequence commits unscanned content. The other command guards match one spelling each (T1-03, T1-06, T1-07, T1-55).
- **CI routing gaps:** a runtime-test-only change routes to no lane (T4-51), and a change to the public facts file never runs the website check that depends on it (T2-05).
- **The release path's last step is its least protected:** promotion has no reviewer environment, the promotion base comes from the manifest being validated, and 188 product files sit in no promotion class (T2-02, T2-09, T5-02).

**What the audit did not find.** No P0. No secret, prompt, transcript or path in telemetry. No way to activate an unverified model file on a shipped path. No StoreKit state outside its owner. Twelve of the 47 candidates the exploration raised were disproved, including every engine liveness candidate.

### Method and limits

- **Find.** Thirty read-only auditors, one per dimension (7 engine, 16 apps, 7 tooling), each with an owned file scope, a check list, the candidates to adjudicate and an exclusion list of open roadmap items and the [September 22 audit](2026-09-22-project-audit.md)'s finding IDs. Auditors reported only new defects or regressions.
- **Verify.** Every finding went to two blind refuters who saw only the finding: one re-traced the code path end to end, the other searched for a guard, test, contract or gate that already prevents it. A finding is confirmed only if the trace reproduced and no covering guard exists. Borderline P0 and P1 findings got a third, tie-breaking trace.
- **Two passes.** A resumed run re-audited 12 dimensions and re-verified everything, so 60 findings were verified twice by different refuters. The two passes disagreed on 11 of those 60. A finding is listed as confirmed only if every pass that examined it confirmed it; a split is listed as disputed.
- **Lead review.** The lead re-read the P1 and the first pass's P1 candidates in source, and set final severities from the refuters' reach arguments (a refuter's narrower-reach proposal is accepted).
- **Limits.** Nothing was built, run or measured: no device, UI, model or benchmark lane, no tests. A finding that needs a runtime fact to settle is listed as plausible or sent to the roadmap with that need stated. Visual defects (contrast, clipping) are read from code, not seen. Open roadmap items were excluded by design, so this report does not restate them.

## 2. Counts

| Severity | Confirmed | Plausible or disputed | Refuted |
| --- | --- | --- | --- |
| P0 | 0 | 0 | 0 |
| P1 | 1 | 0 | 0 |
| P2 | 40 | 2 | 0 |
| P3 | 111 | 15 | 9 |

178 findings after merging duplicates. Severities are the lead's, after the refuters' reach arguments; where the auditor rated a finding differently the entry says so.

## 3. Confirmed findings, P1 and P2

### Engine, runtime and CLI

#### E1-02 (P2): A cancelled prewarm unloads the resident model while the UI still shows it loaded

- **Where:** `Sources/QwenVoiceCore/NativeEngineRuntime.swift:1799` (NativeEngineRuntime.ensureWarmStateIfNeeded / ensureDesignConditioningWarmStateIfNeeded / MLXTTSEngine.generate cancel branch)
- **Defect:** The catch-all in both prewarm paths treats a pure CancellationError as a failure: it unloads the resident model, drops the clone and design warm state and clears the Qwen3 caches (iPhone). The engine's prewarm ends with a Task.checkCancellation(), so a cancel arriving at or after the end of the warm body also lands in that catch. MLXTTSEngine.generate's cancel branch then publishes loadState = .loaded(modelID:) for a model the runtime has just dropped, because its unload check only sees captured MLX failures.
- **How it fails:** 1. The Mac warmup coordinator's dispatched warm is running prewarmVoiceDesign (or the user cancels a take during Preparing). 2. The intent changes or the user cancels, so Task.cancel reaches engine.prewarm, whose trailing Task.checkCancellation() throws CancellationError. 3. The runtime catch runs loadCoordinator.unloadModel() and sets activeModelID = nil, so the resident model is gone. 4. For a cancelled take, generate sets loadState = .loaded(modelID:) while runtime.loadedModelID() is nil; the UI shows a ready model until the idle unload fires, and the next take or warm pays a full cold load.
- **Fix:** In the three runtime catch blocks, skip the unload and cache reset when NativeGenerationTerminalClassifier.disposition(of: error) == .cancellation and the engine did not record a runtime failure, and rethrow. In MLXTTSEngine.generate's two cancel branches, derive loadState from runtime.loadedModelID() (the settleCancelledModelOperation pattern) instead of assuming .loaded.
- **Notes:** confirmed by both verification passes; relates to AUD-10.
- **Action:** Roadmap DA-06: it changes when the engine unloads, which needs one model run to verify.

#### E2-01 (P2): macOS unload paths never clear the process-global Qwen3 caches, against four contract texts

- **Where:** `Sources/QwenVoiceCore/NativeEngineRuntime.swift:2316` (NativeEngineRuntime.clearQwen3MemoryCachesIfNeeded)
- **Defect:** On macOS no unload path (idle unload, the Mac store's critical fullUnload, stop(), the allocation-retry unload) clears the process-global Qwen3 caches. The resident speech tokenizer, a few hundred MB of MLXArray weights, therefore outlives every macOS unload, including on the 8 GB floor tier. The exemption is a documented decision (NativeEngineRuntime.swift:2311-2315, docs/reference/ios-engine-optimization.md:143-144), so C1 is not a pure oversight. It contradicts four other statements: Qwen3TTS.swift:97-99, Qwen3TTS.swift:472, Packages/VocelloQwen3Core/PERFORMANCE.md:18-19 and the hardTrim line in NativeMemoryPressureMonitor.swift:173. The 'warm-after-idle' rationale fits the small prefix and decoder-bucket caches. It does not fit the weights-sized tokenizer, and a macOS model switch (the tokenizer's reuse case) never goes through unload, so clearing on unload would not cost that win. The comments are stale, and the retained tokenizer is the real defect.
- **How it fails:** 1) On an 8 GB Mac the model loads and Qwen3TTSPreparedComponentCache.storeResidentSpeechTokenizer keeps the speech tokenizer (Qwen3TTS.swift:6034; 682 MB per the comment at :5949, about 218 MB resident decoder per :463-465). 2) The 120 s idle unload fires, or the footprint reaches the critical band (72% of RAM) and the store fully unloads; MLXModelLoadCoordinator.resetLoadedState drops the talker. 3) clearQwen3MemoryCachesIfNeeded returns at the iPhonePro guard, and Memory.clearCache() frees only buffer cache, not live arrays, so the tokenizer weights stay in the footprint for the life of the process. 4) The 'unloaded' floor Mac still holds hundreds of MB that PERFORMANCE.md:18-19 says full unload invalidates, so idle unload and critical relief free less than designed.
- **Fix:** Give clearQwen3MemoryCachesIfNeeded the trim reason. On macOS, keep preserving caches for softTrim and hardTrim (the weights stay loaded then). On idle unload, fullUnload, stop and the allocation-retry unload, clear at least the resident speech-tokenizer slot (or call clearAll) on every tier, or on the floor and mid tiers only if a measured warm-after-idle cost justifies the exception. Then reconcile the five contract texts listed in the evidence (or the exemption) so they agree, and add a test that a macOS unload releases the resident tokenizer.
- **Notes:** confirmed by both verification passes; candidate C1; relates to BT-01.
- **Action:** Roadmap DA-05 (maintainer decision: speed after idle versus memory at the critical band).

#### E4-01 (P2): One-token scripts (for example "Hi") are refused by an off-by-one length guard

- **Where:** `Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift:4902` (Qwen3TTSModel.validateOptimizedCustomVoiceTextEmbeddingLength)
- **Defect:** The chat-template length guard requires >= 10 tokens although the slicing it protects (`textEmbed[0..., 3 ..< 4]` and `textEmbed[0..., 4 ..< (dim - 5)]`) is valid from 9 tokens, so any script that tokenizes to a single text token is refused by the engine with an internal message that embeds the raw script and calls every mode 'custom voice'.
- **How it fails:** 1. User types a one-token script (e.g. 'Hi') in Built-in Voice or Voice Design and taps Generate; the host only checks non-empty (Qwen3TTSRuntimeProfile.validatePromptText). 2. prepareInputs tokenizes '<\|im_start\|>assistant\n' (3 tokens, pinned at 4753) + 1 text token + '<\|im_end\|>\n' (2) + '<\|im_start\|>assistant\n' (3) = 9 chat tokens. 3. validateOptimizedCustomVoiceTextEmbeddingLength throws AudioGenerationError.invalidInput("... produced only 9 chat tokens for 'Hi'"). 4. The take fails although `4 ..< (9 - 5)` is an empty-but-valid range and trailingTextHidden would be just the EOS embed; the error text carrying the script surfaces wherever the host shows localizedDescription (CLI stderr, alerts).
- **Fix:** Lower the guard to `>= 9` (or compute `3 + 1 + 5` from the pinned template) so one-token scripts generate, and drop `originalText` from the error description (report the token count only, with a mode-neutral message); alternatively reject too-short scripts in the host with a typed, localized error before the engine call.
- **Notes:** confirmed by both verification passes.
- **Action:** Roadmap DA-04 (two-line fix; needs one model run to verify).

#### E7-02 (P2): The finalize-before-release choreography is tested only on a type the product never constructs

- **Where:** `Packages/VocelloQwen3Core/Tests/Qwen3RuntimeTests/VocelloQwen3FacadeTests.swift:1697` (VocelloQwen3ProductOutputAdapter tests / AtomicWAVGenerationOutputSinkTests)
- **Defect:** The finalize-before-release, abort-after-sink-failure and pre-cancelled-abort choreography is verified only on VocelloQwen3ProductOutputAdapter. That type is constructed only by tests. Its sink, AtomicWAVGenerationOutputSink, is also instantiated only in tests (5 sites in AtomicWAVGenerationOutputSinkTests). The shipped path is GenerationOutputAdapter.run in QwenVoiceCore, which re-implements the reserve/claim/open/execute/acknowledge sequence and the catch-path cancel, abort and acknowledge by hand. That code has no test. About 7 facade tests plus 5 sink tests therefore pin a copy that no product build executes.
- **How it fails:** 1. Someone edits GenerationOutputAdapter.run, for example moving acknowledgeProductFinalization before chunkSink(.completed) or dropping the abortReservation call on the not-opened path. 2. All 12 adapter and sink tests still pass, because they run the package's unused copy. 3. A lease leak or a completed-then-failed ordering regression reaches users. 4. The roadmap item PA-19 (generate-loop and orchestrator coverage) reads as closed on this path.
- **Fix:** Either route GenerationOutputAdapter.run through VocelloQwen3ProductOutputAdapter with AtomicWAVGenerationOutputSink, so the tested code is the shipped code, or delete the unused adapter and sink and their tests. Then test the real adapter over the package fixture engine (VocelloQwen3Engine with FacadeCompatibilityModel) through GenerationOutputAdapting, covering success, sink failure, pre-cancel and acknowledge-throws.
- **Notes:** confirmed by both verification passes.
- **Action:** Fixed in `89896465`, `6306e841`.

#### E7-03 (P2): The PA-15 shutdown-reason tests re-create the engine wiring inline instead of exercising it

- **Where:** `Tests/VocelloCoreTests/IOSShutdownCancellationReasonTests.swift:33` (IOSShutdownCancellationReasonTests.terminalReason)
- **Defect:** PA-15 pins that a foreground-exit .shutdown reaches the terminal cancellation summary. The tests do this by re-creating MLXTTSEngine.generate's wiring inline: a hand-written cancel closure, a `cancelSwiftTask` closure standing in for the task cancellation handler, and `ingress.reason ?? coordinatorReason`. They never call MLXTTSEngine.generate. Only the helper types (GenerationCancellationIngress and ActiveGenerationCoordinator) are real. If the production composition changes, the tests do not notice.
- **How it fails:** 1. A refactor of MLXTTSEngine.generate swaps the order to `coordinatorCancellationReason ?? cancellationIngress.reason`, or stops installing the typed reason in the coordinator's cancel closure. 2. The terminal `.cancelled` summary reports `.user` for a shutdown. 3. All three tests still pass, because the precedence they check is written in the test itself.
- **Fix:** Drive a real MLXTTSEngine.generate over a stub GenerationOutputAdapting factory that suspends until cancelled. Cancel through cancelActiveGeneration(reason: .shutdown), then assert the `.cancelled` GenerationEvent summary reason from events(for:), and also assert the .user fallback when only the task is cancelled.
- **Notes:** confirmed by both verification passes.
- **Action:** Fixed in `89896465`.

### iOS and macOS apps

#### A2-01 (P1): History audio paths are absolute and break when the app container moves

- **Where:** `Sources/iOSSupport/Models/Generation.swift:13` (Generation.audioPath / GenerationMigrations v1)
- **Defect:** generations.audioPath is an absolute path string that is never rebased. On iPhone it resolves under the App Group container, whose path embeds a per-install UUID. After a backup restore or device migration, every History row, queued outbox entry and long-form journal points at a path that no longer exists, although the files and the database were restored together. Nothing resolves paths against the current AppPaths.outputsDir, and no migration or startup step rewrites them. This confirms candidate A-6. Playback and delete do not tolerate moves, even though IOSLeftoverAudioAnalysis does.
- **How it fails:** 1. A user with 200 takes restores an iPhone from backup onto a new device; history.sqlite and outputs/ return, but the App Group container has a new UUID. 2. HistoryScreen.loadPage runs fileExists on the stored absolute paths, marks every row audio-unavailable and disables Play and Share; the player sheet opens a dead URL. 3. Deleting a row hits deleteSingle, sees fileExists(stale) false and returns .deleted, so the real WAV in the new container stays as an unreachable orphan. 4. Queued outbox entries and journals keep stale paths and report missingAudio forever, so the recovery banner never clears.
- **Fix:** Resolve the stored path at read time: if the stored absolute path is missing, try appSupportDir plus the portion from 'outputs/' onward. Better, add migration v8 that rewrites in-root rows to relative paths (or rebases them to the current container on launch when the old root is absent), and make removeUnreferenced, the outbox and the journal resolve through the same helper. Keep absolute paths only for diagnostics-override roots. Rebase the long-form journal manifestURL the same way.
- **Notes:** confirmed by both verification passes; candidate A-6; relates to ASR-06.
- **Action:** Fixed in `64ad6677`.

#### A1-01 (P2): A Stop accepted while the finished take is being saved still lands it in History and the Files folder (iOS)

- **Where:** `Sources/iOSSupport/Services/IOSSingleTakeGenerationExecutor.swift:116` (IOSSingleTakeGenerationExecutor.run)
- **Defect:** A Stop (or PA-15 foreground-exit) accepted while generationCompleted is suspended on the History commit still persists the take to History and exports it to the Files folder, while the Studio attempt ends as cancelled ("Generation stopped" announced, no inline card): the attempt authority has no finalizing phase, so requestCancellation is accepted after the engine already returned the output and the engine barrier is a no-op.
- **How it fails:** 1) Engine returns the final take; executor passes the line-116 check and enters hooks.generationCompleted, which hands the file to the player synchronously, then suspends on GenerationPersistence.persist -> GenerationHistoryRecoveryCoordinator (actor) commit after the outbox entry is already enqueued. 2) User taps Cancel (or the app leaves the foreground): StudioGenerationAttemptAuthority.requestCancellation flips .running -> .cancelling and the barrier Task calls ttsEngine.cancelActiveGeneration, whose ActiveGenerationCoordinator.cancelCurrent returns immediately because nothing is active; coordinator.completeCancellation clears the attempt and announces "stopped" (PA-15 additionally records the singleTakeDiscarded notice). 3) The suspended generationCompleted resumes: the History row commits (the outbox is designed so cancellation cannot discard it) and IOSSavedOutputsDestination.exportIfConfigured copies the WAV into the user's folder. 4) run() returns; coordinator.complete(...) is rejected (token cleared) so no card appears: History and the Files folder hold a take the UI told the user was discarded; in Design, saveSheetAudioPath is still set to it. The same acceptance sliver exists for long-form (IOSLongFormProject.swift:881-884 checks cancellation before acceptLongFormProject but the commit can still land, after which finish(.completed) hands the joined file to the iOS player with no ownership guard). Window is the duration of the DB commit (tens of ms), so this is a race, but it is reachable from the ordinary Stop button and from backgrounding.
- **Fix:** Add a `.finalizing` phase to StudioGenerationAttemptAuthority (and a coordinator method the executor calls right after hooks.generate returns, before generationCompleted) in which requestCancellation returns false so the Stop button and the PA-15 interrupt are refused once the engine has produced the take; the attempt then completes normally with its card. Mirror it in IOSLongFormProjectRunner around acceptLongFormProject. Add an IOSSingleTakeGenerationExecutorTests case whose fake hook flips the cancellation flag inside generationCompleted and a StudioGenerationCoordinatorTests case asserting requestCancellation is rejected in the finalizing phase.
- **Rule:** .claude/rules/native.md: "Every start returns one attempt token; stale callbacks, overlapping starts and duplicate cancellations are rejected; a cancelled take never lands in History."
- **Notes:** confirmed by both verification passes; candidate A-3; relates to AUD-03; the window is the History commit, tens of milliseconds.
- **Action:** Fixed in `64ad6677`.

#### A10-01 (P2): iOS Design "Save as voice" depends on view-local state the generation task writes

- **Where:** `Sources/iOS/IOSGenerationModeViews.swift:701` (IOSVoiceDesignView.saveSheetAudioPath / canSaveVoice / presentSaveDesignedVoice)
- **Defect:** The iOS Design 'Save as voice' affordance depends on view-local @State (`saveSheetAudioPath`), written from the generation Task. The completed take lives on the AppModel coordinator, which survives remounts. The Design view is destroyed whenever the Studio mode or tab changes, so the Save action disappears while the completed card stays. When the sheet does open, its transcript and name come from the current draft, not from the take that produced the audio. The Mac fixed both problems with a shell-owned `VoiceDesignSavedVoiceCandidate` that carries the take's own audio, transcript and brief and is offered only while `matches(draft:)` holds. iOS has no equivalent.
- **How it fails:** 1) Generate a Voice Design take. The inline card shows it complete and `saveSheetAudioPath` is set. 2) Tap the Built-in capsule, or switch tab and come back. `IOSGenerateModeViewport` and `RootView` use `switch`, so IOSVoiceDesignView is rebuilt with `saveSheetAudioPath == nil`. 3) The complete card still shows from `coordinator.lastCompletedOutput`, but `onSaveAsVoice` is nil, so the Save action is gone. 4) Separately, edit the script after a take and tap Save: `saveSheetTranscript = promptText` pairs the old audio with the new text, and that is persisted as the reference transcript of a saved clone voice.
- **Fix:** Move the candidate to AppModel as a `VoiceDesignSavedVoiceCandidate`. The type is in MacAppModel.swift, which iOS does not compile, so first extract it to a shared file under Sources/iOSSupport or SharedSupport. Set it in an `onCompleted` step from the take's `result.audioPath`, `plan.request.text` and the brief. Drive `onSaveAsVoice`, the sheet's clip URL and the default transcript from it, and clear it when the take is replaced or no longer matches the draft. Add a VocelloCoreTests case for `matches(draft:)`.
- **Notes:** confirmed by both verification passes; relates to AUD-03.
- **Action:** Fixed in `8e8d5556`.

#### A10-02 (P2): Programmatic routes switch Studio mode during a generation

- **Where:** `Sources/iOS/Voices/VoicesScreen.swift:29` (VoicesScreen.onSelectBuiltInSpeaker / onSelectSavedVoice (also RootView recorder and import onEnrolled))
- **Defect:** iOS blocks switching Studio mode during a generation only in the capsule selector UI (`isSelectionDisabled: ttsEngine.hasActiveGeneration`). Programmatic routes set `studioMode` unconditionally: Voices tab built-in tap, Voices tab saved-voice tap, and the recorder and import `onEnrolled` handlers in RootView. Mac enforces the same rule in its single routing function (`selectDestination`). On iOS the target mode's canvas renders only its own coordinator's state, so it shows an idle disabled Generate button with no Stop control, and the selector is locked. The user cannot reach the running mode's Stop button until the take or long-form project ends.
- **How it fails:** 1) Start a Voice Design take or a long-form project. 2) Open the Voices tab and tap a saved voice or a built-in speaker. 3) `studioMode` becomes `.clone` or `.custom`, and the Studio tab shows an idle canvas with Generate disabled because the engine is busy. 4) The mode selector is disabled for the other modes (`.disabled(isSelectionDisabled && item != selection)`), so the running Design canvas and its Stop button are unreachable until the work completes. For long-form that can be minutes.
- **Fix:** Add one AppModel method, for example `requestStudioMode(_:)`, that returns without switching when `studioCoordinators`/`longForm` report active work in a different mode. Route the Voices, recorder and import call sites through it. Alternatively, let the canvas of any mode show a Stop control for `ttsEngine.hasActiveGeneration`. Mirror the Mac `selectDestination` rule.
- **Notes:** confirmed by both verification passes.
- **Action:** Fixed in `8e8d5556`, `5186f914`, `303ad901`.

#### A12-02 (P2): Skip and Retake buttons size from outside their label (small hit region)

- **Where:** `Sources/iOS/Overlays/IOSOnboardingFlow.swift:46` (Skip button; IOSRecordingOverlay.controls Retake button)
- **Defect:** The onboarding Skip button and the recording Retake button put their sizing (frame, background, capsule) on the Button from outside instead of inside its label. Under SwiftUI's behavior of limiting a Button's hit and accessibility region to its label, only the text bounds (about 40x20 pt) are tappable. Retake draws a full-width 52 pt capsule where most of the visible area does nothing.
- **How it fails:** 1. A user taps the empty part of the Retake capsule (or near the small Skip word). 2. Nothing happens because the hit region is only the text label. 3. Users with motor impairments, or at larger sizes, fail repeatedly. 4. The 44 pt minimum named in the audit contract is not met and these controls are not covered by the audit's target check.
- **Fix:** Move the frame, background and contentShape(Rectangle()) inside the Button label (as IOSPlayerSheet's topBar does) with minHeight 44, and add both identifiers to the target assertions.
- **Action:** Fixed in `e62747f0`.

#### A12-03 (P2): iOS History segments disclosure has no expanded state for VoiceOver

- **Where:** `Sources/iOS/History/HistoryScreen.swift:654` (longFormSegmentsDisclosure)
- **Defect:** The iOS History long-form segments disclosure has no expanded or collapsed accessibility value and a text-sized hit region. The macOS twin was fixed with both an accessibilityValue and an inner contentShape plus vertical padding. The iOS version applies only horizontal padding outside the Button and exposes the state only through an unlabeled chevron image.
- **How it fails:** 1. A VoiceOver user lands on 'N segments' in History. 2. VoiceOver reads the label but not whether the list is expanded, and the chevron is an unlabeled symbol. 3. They cannot tell whether activating expands or collapses. 4. The roughly 20 pt tall target is also hard to hit for motor-impaired users.
- **Fix:** Mirror the Mac implementation: add .accessibilityValue(expanded/collapsed) using catalog strings, hide the chevron, and add vertical padding plus contentShape(Rectangle()) with minHeight 44 inside the label.
- **Action:** Fixed in `e62747f0`.

#### A12-04 (P2): Only Studio transitions are announced to VoiceOver; lifecycle toasts and other status changes are silent

- **Where:** `Sources/iOS/IOSEngineLifecycleToast.swift:106` (IOSEngineLifecycleToast.handle / IOSExportPurchaseSheet notice / MacStatusStrip)
- **Defect:** Only Studio generation transitions post a VoiceOver announcement. Other status changes appear visually without one. Examples: the engine lifecycle toast (interrupted, recovering, restarted; informational states auto-dismiss after 4 s), the purchase/restore notice and progress in the export sheet, the History 'not saved' warning banner, and the Mac status strip error and crashed states. StudioGenerationAnnouncer is the only AccessibilityNotification call site.
- **How it fails:** 1. A VoiceOver user is mid-take, or in History, when the engine is interrupted and recovers. 2. The toast appears and is removed 4 s later, and VoiceOver focus never moves to it. 3. The user never learns the engine restarted, or whether a purchase or restore succeeded. 4. On Mac a crashed or errored engine shows only a visual strip.
- **Fix:** Route the lifecycle toast, purchase notice, enqueue warning and Mac status errors through the same announcer, on appearance and with the localized message; keep informational toasts from relying on 4 s visibility alone.
- **Notes:** relates to IOS-12.
- **Action:** Fixed in `e62747f0`, `201194a6`.

#### A12-05 (P2): The shared filter chip row truncates at large text sizes

- **Where:** `Sources/iOS/IOSDesignSystemPrimitives.swift:1024` (IOSFilterChipRow)
- **Defect:** The shared filter chip row (History mode filter, Voices filter) is a single non-wrapping HStack of equal-width, single-line chips with no accessibility-size layout. Labels truncate at larger sizes. The Studio capsule selector, by contrast, switches to a vertical stack at accessibility sizes.
- **How it fails:** 1. A user at AX3 or larger opens History with four chips, or Voices with three. 2. Each chip gets roughly a quarter or third of the width and its label is limited to one line with minimumScaleFactor 0.85. 3. Labels truncate to fragments, so the filter choices cannot be told apart visually. 4. The chip group can neither wrap nor scroll.
- **Fix:** At isAccessibilitySize render the chips in a vertical stack or a LazyVGrid, or allow two lines, matching the capsule selector's adaptation. Add History and Voices to the AX walk.
- **Notes:** relates to PA-20.
- **Action:** Fixed in `e62747f0`, `201194a6`.

#### A12-51 (P2): Onboarding and the recording overlay clip at large Dynamic Type sizes

- **Where:** `Sources/iOS/Overlays/IOSOnboardingFlow.swift:23` (IOSOnboardingFlow / IOSOnboardingWelcomePage / IOSOnboardingInstallPage)
- **Defect:** First-run onboarding and the reference-recording overlay lay out large Dynamic-Type text in non-scrolling stacks with fixed-width text columns and no accessibility-size branch. Neither file has a ScrollView, ViewThatFits or isAccessibilitySize check.
- **How it fails:** 1. A user with AX3 or larger text installs and opens the app, so the onboarding fullScreenCover shows. 2. The 36 pt largeTitle-scaled headline, the 17 pt body copy limited to 320 pt wide, and the three benefit rows exceed the screen height. 3. The pages container is centered with maxHeight .infinity and cannot scroll, so top and bottom content is clipped and unreachable except by VoiceOver. 4. The recording overlay shows the same clipping for its guidance and status text.
- **Fix:** Wrap the onboarding pages and the recording stage in IOSScrollView (or branch on dynamicTypeSize.isAccessibilitySize to a scrolling layout), drop the fixed 280/300/320 widths at accessibility sizes, and add onboarding and recording to the AX-XXXL walk.
- **Notes:** relates to PA-20.
- **Action:** Fixed in `e62747f0`.

#### A14-01 (P2): A line batch cancelled by the engine never closes its Studio attempt

- **Where:** `Sources/Services/MacLineBatchRunner.swift:249` (MacLineBatchRunner.finish(_:lastSaved:studioCoordinator:attempt:))
- **Defect:** A line batch that ends cancelled without going through the runner's own cancel() (the engine cancels the take for memory pressure) never closes the Studio coordinator attempt, so the mode stays 'generating' and every new start is refused as busy.
- **How it fails:** 1) Start a line batch on a memory-tight Mac. 2) Kernel critical pressure (hardTrim) or the store's critical band cancels the active take with reason memoryPressure; engine.generate throws CancellationError. 3) run() returns .cancelled, cancelTask is nil, finish(.cancelled) only sets the outcome. 4) coordinator.isGenerating stays true: the canvas stays locked, the sheet's retry shows the busy message although the engine is idle, and the outcome reads 'cancelled' with no reason. Recovery only by pressing Cancel or Cmd-. on a batch that is no longer running.
- **Fix:** In finish(.cancelled) call studioCoordinator.finish(attempt: attempt), as IOSLongFormCoordinator does: it is a no-op while a user cancellation barrier is pending and closes the attempt otherwise. Carry the non-user reason into the outcome so the sheet does not present it as a user cancel.
- **Notes:** relates to PA-19.
- **Action:** Fixed in `8e8d5556`. Why the engine cancelled is not shown yet (DA-13).

#### A14-02 (P2): A failed Mac engine start is swallowed: the app stays on "Starting engine…" forever

- **Where:** `Sources/QwenVoiceApp.swift:227` (QwenVoiceApp.startSelectedTTSEngineIfNeeded())
- **Defect:** A failed TTSEngineStore.initialize() is swallowed and never retried: the flag is set before the attempt, the engine publishes no failure state for it, and Retry rebuilds only when the store is nil, so the window stays on 'Starting…' with Generate disabled until relaunch.
- **How it fails:** 1) Launch with an app-support tree where the engine cannot create its voices, stream-session or normalized-reference directory (unwritable folder, a file at that path, full disk on first launch); setupAppSupport hides the same failure with try?. 2) initialize() throws from the directory-creation task before isInitialized is set. 3) The catch discards it; no visibleErrorMessage, loadState stays idle. 4) Sidebar shows 'Starting…' forever, Studio shows engine-starting, no diagnostics screen and no Retry. Rated P2 for the rare trigger; the rubric's 'hang on an error path' would make it P1.
- **Fix:** On failure, reset didInitializeSelectedTTSEngine and surface an AppLaunchDiagnosticsSnapshot (a new issue case) so the existing diagnostics view and Retry cover it; let retryLaunchPreflight re-run initialize when the store exists but is not ready. Correct the comment.
- **Notes:** confirmed by both verification passes; candidate A-2; relates to MAC-04; also reported as A10-03; the first pass rated it P1; the trigger needs an abnormal Application Support state or a full disk.
- **Action:** Fixed in `64ad6677`.

#### A14-03 (P2): A Mac cancel accepted during clone priming is not rechecked before the take starts

- **Where:** `Sources/Services/MacStudioSingleTakeRunner.swift:66` (MacStudioSingleTakeRunner.start(plan:estimatedAudioDuration:coordinator:hooks:prepare:onCompleted:))
- **Defect:** A cancellation accepted while prepare() (on-demand clone priming) is still running is not rechecked before the executor starts, and the cancel barrier covers only an active generation, so the coordinator goes idle while the stale task later runs generationSubmitted and takes the shared player's generation ownership from a take started in between.
- **How it fails:** 1) Voice Cloning, reference not yet primed: Generate, then Cancel during 'Preparing voice reference…'. The barrier finds no generation, returns, and the coordinator is idle while the prime unwinds. 2) Press Generate again inside that window: take 2 claims playback ownership and waits behind the prime. 3) The prime ends; stale task 1 calls generationSubmitted, beginGenerationPlayback(op1) replaces take 2's ownership, then its generate is refused and generationCancelled aborts the preview. 4) Take 2 completes with every preview chunk dropped and no final handoff or autoplay; it is in History but the Studio player never loads it.
- **Fix:** After await prepare(), throw CancellationError when Task.isCancelled or the attempt is no longer the coordinator's running attempt, before calling the executor. Optionally keep the coordinator nonterminal until the task has exited (await the task in the cancel path), matching the documented barrier contract.
- **Notes:** relates to AUD-03.
- **Action:** Fixed in `8e8d5556`.

#### A14-04 (P2): The Mac footer keeps showing an old error after the engine recovered

- **Where:** `Sources/Views/Shell/MacShellStatus.swift:46` (MacShellStatusPresentation.resolve(snapshot:prefersInlinePresentation:))
- **Defect:** The footer status maps any non-empty visibleErrorMessage to .error before it looks at loadState, and the engine clears that message only when a later operation succeeds, so a retry after a failed take shows the previous error for the whole run instead of the running activity.
- **How it fails:** 1) A take fails; handle() sets visibleErrorMessage and .failed, the strip shows Error (correct). 2) Press Generate again without dismissing the strip; the failed model was unloaded, so this is a cold start. 3) The engine publishes .running but keeps the old message. 4) The sidebar strip (identifier sidebar_backendStatus_error) keeps showing the old error with a dismiss button during the retry, and again after a user cancel of that retry; it clears only on success. With loadState .starting the old error text is shown as the activity title.
- **Fix:** In resolve(), let .running and .starting win over a stale message (show the error only for .failed, or for idle/loaded states), or clear the engine's visible error when a user generation is admitted. Add a table test over the snapshot combinations.
- **Action:** Fixed in `8e8d5556`.

#### A14-05 (P2): Mac Navigate commands stay enabled during a line batch or long-form project

- **Where:** `Sources/QwenVoiceApp.swift:86` (CommandMenu(Navigate) / AppCommandRouter.navigate(to:))
- **Defect:** The Navigate commands stay enabled during a line batch or long-form project, and selectDestination blocks only a change of Studio mode while the store reports an active generation; moving to History, Saved Voices or Settings removes the Studio screen that presents the batch sheet, and the sheet's onDisappear safety net then cancels the run.
- **How it fails:** 1) Start a 100-line batch or a long-form project from Built-in Voice (sheet presented by MacCustomVoiceScreen). 2) Press Cmd-4, Cmd-5, Cmd-6 or Cmd-F. 3) selectDestination switches the detail view, the presenting screen leaves the hierarchy and the sheet is dismissed. 4) onDisappear calls cancelIfDismissedWhileProcessing or longForm.cancel: the run is cancelled with no confirmation, and reopening the sheet resets the line-batch outcome. Cmd-1/2/3 do the same in the gap between two lines, when hasActiveGeneration is briefly false; during a take they are silent no-ops.
- **Fix:** Disable the Navigate commands (or make selectDestination refuse) while appModel.lineBatch.isProcessing or appModel.longForm.isProcessing, using the coordinators' isGenerating rather than the store's per-take flag; or host the batch sheet above the destination switch so navigation does not dismiss it.
- **Notes:** relates to MAC-23.
- **Action:** Fixed in `8e8d5556`.

#### A2-02 (P2): One unreadable outbox entry permanently blocks Clear All and pending-audio removal

- **Where:** `Sources/SharedSupport/Database/GenerationHistoryOutbox.swift:853` (GenerationHistoryRecoveryCoordinator.clearAll / removePendingAudio)
- **Defect:** One outbox entry that cannot be decoded or validated (corrupt file, identity mismatch, schema mismatch) permanently blocks Clear All and all pending-audio removal. The banner tells the user to Retry, and Retry only re-reads and re-fails. No in-app path discards or repairs such a record, and the recovery export lists only audio and long-form journals, never the damaged record. The fail-closed intent is deliberate, but there is no exit.
- **How it fails:** 1. One outbox .json becomes undecodable (disk fault, interrupted external copy, a restore that dropped half a file). 2. scan.issueCount becomes 1. 3. clearAll throws clearUnavailable on every call, removePendingAudio returns early so removed-row audio is never reclaimed, and withReferencedAudioPaths returns nil. 4. The banner says 'Retry before clearing History', Retry changes nothing, and only a reinstall clears it.
- **Fix:** Add an explicit user-confirmed 'Discard unverifiable record' action: move the damaged file to a .unreadable side file as the removal-list path already does, count it in the notice, and let clear-all and removal proceed once the user has seen it.
- **Notes:** confirmed by both verification passes; relates to F-06.
- **Action:** Fixed in `8ad9723c`, `86fd0afe`.

#### A5-01 (P2): iPhone model delete removes files with no engine coordination

- **Where:** `Sources/iOS/IOSModelDownloadCoordinator.swift:298` (IOSModelDownloadCoordinator.delete(model:))
- **Defect:** The iPhone model delete removes the installed files with no engine coordination of any kind: no active-generation or load-in-flight check, no unload, no busy alert. macOS runs MacModelDeletionSequence (gate, stopDownloads, unloadModel, re-gate) and attaches the engine store at launch; the iOS installer view model does not even hold an engine reference, and the row offers Remove whenever the model is installed.
- **How it fails:** 1. iPhone Studio is generating a Custom take (engine loadState.currentModelID == pro_custom, weights resident). 2. User opens Settings > Voice Models and taps Remove, confirms the sheet. 3. coordinator.delete tombstones the model folder immediately (SharedModelComponentStore.deleteModel) and publishes .deleted; no alert, unlike the Mac's 'Generation in Progress'. 4. Inventory now says not installed while the engine still reports the model loaded with gigabytes of weights resident; Studio flips to 'install the model' while the memory stays held until idle unload, and a later Install of an updated artifact is served by the stale weights until the engine unloads.
- **Fix:** Move MacModelDeletionSequence (it already only needs a MacModelEngineCoordinating value) into Sources/iOSSupport/Services as a shared deletion sequence, make the iOS TTSEngineStore conform (it already publishes hasActiveGeneration, hasSustainedPerformanceActivity, loadState, clonePreparationState and has unloadModel), give IOSModelInstallerViewModel/coordinator the engine reference from IOSAppDependenciesContainer, and show the busy outcome in VoiceModelsScreen like MacSettingsScreen does. When PA-33's engine-side lease lands, the iOS coordinator must take it too; PA-33's sourceOfTruth lists only the Mac files.
- **Notes:** confirmed by both verification passes; candidate A-1; relates to PA-33 (also MAC-20): what is new is that the iOS path has no gate at all, not even the store-level sequence the Mac got for MAC-20, and PA-33 as scoped (Mac sequence + MLXTTSEngine) would not reach the iOS delete unless the iOS coordinator is wired to the lease.
- **Action:** Fixed in `8ad9723c`. The engine-side lease stays PA-33.

#### A5-02 (P2): An incomplete install cannot be removed from the iPhone UI

- **Where:** `Sources/iOS/IOSModelInstallerViewModel.swift:98` (IOSModelInstallerViewModel.state(for:))
- **Defect:** An incomplete install can never be removed from the iPhone UI: state(for:) maps ModelStatus.incomplete to OperationState.failed for every download-eligible model, and the row's .failed branch shows only Retry, so the Repair + Remove branch written for .idle/.incomplete (and counted by visibleActionCount) is unreachable.
- **How it fails:** 1. An installed model loses or corrupts a required file (LocalModelAssetStore.state(for:) returns .incomplete). 2. The Voice Models row shows 'Retry needed' with a single Retry button. 3. Retry runs install, which needs Wi-Fi and a multi-hundred-MB to multi-GB transfer; if that fails or is unwanted the user has no way to delete the partial folder and reclaim storage. 4. The code's own intent (Repair + Remove for .incomplete, a delete sheet size label for .incomplete) never renders.
- **Fix:** Return .idle (or a dedicated .repairable) from state(for:) for .incomplete so the row's existing Repair + Remove branch renders; keep .failed for genuine delivery failures.
- **Notes:** confirmed by both verification passes.
- **Action:** Fixed in `5b3ebba2`.

#### A7-02 (P2): A failed recording start is invisible on iOS

- **Where:** `Sources/SharedSupport/ViewModels/ReferenceClipRecorder.swift:224` (ReferenceClipRecorder.start / IOSRecordingOverlay.controls)
- **Defect:** On iOS a failed recording start (audio-session activation refused or failed, AVAudioRecorder init/record failure) only sets `recordingFailed`, which no iOS view reads; the overlay keeps showing the Record button and the 'tap to begin' status, so the user gets no indication why nothing happened.
- **How it fails:** 1. Open Clone > Record while a call is active or another app holds the microphone (or the app was backgrounded during activation). 2. Tap Record: `referenceClipActivateRecordingSession` throws (`ClaimRefusedInBackground` or the setCategory/setActive error rethrown by `perform`), `start()` lands in `catch` and sets `recordingFailed = true`. 3. `IOSRecordingOverlay` has no reader of `recordingFailed`: `isRecording == false && elapsed == 0` renders the Record CTA and `recordBegin`. 4. The user taps again with no feedback; only the macOS sheet surfaces this state.
- **Fix:** In IOSRecordingOverlay, render a localized failure status (and keep the Record CTA) when `recorder.recordingFailed` is true, mirroring MacRecordVoiceSheet; add the catalog key through VocelloPresentationText.
- **Notes:** confirmed by both verification passes.
- **Action:** Roadmap DA-07 (needs new localized copy).

#### A7-03 (P2): Live preview playhead jumps after a pause or an underrun

- **Where:** `Sources/SharedSupport/ViewModels/AudioPlayerViewModel.swift:1153` (AudioPlayerViewModel.attemptLivePlay / updatePlaybackProgress)
- **Defect:** Resuming the live preview after a user pause or an underrun adds `livePlaybackTimeOffset = currentTime` to `renderedNodeSeconds`, but the node is only `pause()`d (never `stop()`ped) on those paths and AVAudioPlayerNode's player time continues across pause/play, so the live playhead roughly doubles after a resume; the inflated `currentTime` then feeds `explicitPlay` and `finalPlaybackHandoff`, which resume file playback past what was actually heard or decline the handoff.
- **How it fails:** 1. Live preview plays 5 s, then underruns (`handleLiveBufferPlaybackCompletion` -> `pauseNode()`) or the user taps Pause. 2. New chunks arrive and `attemptLivePlay` runs: `livePlaybackStarted` is true, so `livePlaybackTimeOffset = 5` and `playNode()` resumes; the node's player time continues from 5 s. 3. `updatePlaybackProgress` computes `adjustedTime = rendered(5+) + 5` -> currentTime jumps to ~10 s (clamped to `duration`). 4. The user pauses and taps Play after completion: `explicitPlay(currentTime:)` positions the final file at the inflated time, skipping audio never heard; on the Mac output-change path the same inflated `heardTime` is handed off. (The 'leading silence' is also appended behind still-queued buffers on a user-pause resume, inserting a 43 ms gap later in the stream.)
- **Fix:** Apply `livePlaybackTimeOffset` only after a node `stop()`/reset (e.g. in `stopLivePreviewForChunkContinuityFailure` or if the resume path is changed to stop+reschedule); on a plain pause/resume leave the offset unchanged and schedule leading silence only when the queue is empty. Verify on device with a forced underrun (QWENVOICE_LIVE_PREVIEW_PREBUFFER_SECONDS small) that the playhead does not jump.
- **Notes:** confirmed by both verification passes.
- **Action:** Roadmap DA-07 (needs a device listen to verify).

#### A8-01 (P2): Deleting a saved voice leaves its normalized reference audio and transcript in the cache

- **Where:** `Sources/QwenVoiceCore/MLXTTSEngine.swift:2060` (MLXTTSEngine.deletePreparedVoice(id:))
- **Defect:** Deleting a saved voice removes voices/<id>.{audio,txt,voice.json,clone_prompt} but never the normalized 24 kHz copy and mirrored transcript sidecar that cloning wrote to cache/normalized_clone_refs/<voiceName>_<sha256>.wav/.txt, so a deleted MP3/AIFF/M4A (or non-canonical WAV) reference's audio, transcript and name persist indefinitely.
- **How it fails:** 1) iPhone: import a friend's .m4a voice memo as a saved voice named Alice (stored as voices/Alice.m4a; supportedSavedVoiceAudioExtensions keeps m4a as is). 2) Generate one Clone take: NativePreparedCloneConditioningCache.normalizeCloneReference writes cache/normalized_clone_refs/Alice_<sha256>.wav and copies Alice.txt beside it. 3) Delete Alice in Voices: PreparedVoiceRepository.delete moves only voices/Alice.* into the tombstone; deletePreparedVoice clears in-memory caches only. 4) Alice_<sha256>.wav and Alice_<sha256>.txt remain on disk forever (no sweep names them; the only sweep removes .converting-*/saved-voice-import-* temporaries), although the user asked for the voice to be deleted and privacy-storage.md says each voice is individually deletable.
- **Fix:** In deletePreparedVoice (or repository.delete via a hook) remove cache/normalized_clone_refs/<id>_*.wav/.txt (fingerprint of the deleted audio is computable before the move), or key normalized outputs for saved voices under voices/<id>.clone_prompt/ so the existing tombstone carries them. Document the normalized cache lifecycle in privacy-storage.md and add a repository/engine test that a deleted non-canonical voice leaves nothing in the normalized directory.
- **Notes:** confirmed by both verification passes; relates to ASR-06 (backup classification of cache/; this is deletion retention, not backup).
- **Action:** Fixed in `2b7c49ba`.

### Tooling, CI, release, docs and website

#### T1-01 (P2): The commit lint ignores how a commit selects content: `git commit --all`, pathspec commits and `git add && git commit` skip the privacy scan

- **Where:** `scripts/hooks/commit_lint.sh:85` (commit_lint.sh staged checks / agent_hook_input.git_actions)
- **Defect:** The commit lint checks the index as it stands before the Bash call runs, and ignores how the commit selects content. A commit chained after `git add` in the same command, or one using a pathspec or `--all`, records content that neither the whitespace check nor the privacy scan ever saw.
- **How it fails:** 1) A new file notes.md contains a developer home path or a token. 2) The agent runs one Bash call: `git add notes.md && git commit -F - <<'EOF' ... EOF` (both parts auto-allowed by `Bash(git add *)` and `Bash(git commit *)`). 3) The PreToolUse hook runs first; the index is still empty, so `git diff --cached --check` and `privacy_scan.py --staged` pass on 0 paths. 4) The command then stages and commits the file; it reaches origin on the next push and only CI's full-tree scan notices, after publication. Same outcome with `git commit -m x docs/file.md`, `git commit --all -m x` or `git commit -m x -a` on an unstaged tracked file.
- **Fix:** In git_actions, report a commit as unresolved when an index-mutating git command (add, rm, mv, apply, reset, restore, stash, checkout -- paths) precedes it in the same command, as is already done for branch changers. For commits carrying -a/--all/-i/--include/-o/--only or a pathspec, also scan the paths from `git diff HEAD --name-only`. Alternatively run the two checks from a real git pre-commit hook, where the index is final.
- **Notes:** candidate T-12; also reported as T1-51.
- **Action:** Fixed in `09f3ebd4`.

#### T1-02 (P2): The staged privacy scan reads the working tree, not the blob being committed

- **Where:** `scripts/privacy_scan.py:58` (scan / main (--staged))
- **Defect:** `--staged` takes the path list from the index but reads each file's bytes from the working tree, so it does not scan the blob that will be committed. A staged path whose working copy is missing is skipped silently.
- **How it fails:** 1) `git add cfg.json` with a token in it; the lint blocks the commit. 2) The agent removes the token in the working tree but does not re-stage. 3) `git commit` is retried; the scan reads the cleaned working file and passes. 4) The commit records the staged blob that still holds the token. Variant: delete the working copy after staging, `not path.is_file()` skips it and the blob is committed.
- **Fix:** In --staged mode read content with `git -C root show :<path>` (or `git cat-file --batch`) instead of the working tree, and treat an unreadable staged blob as a failure rather than a skip.
- **Notes:** candidate T-12.
- **Action:** Fixed in `09f3ebd4`.

#### T1-03 (P2): The git tokenizer treats a mid-word `#` as a comment and drops the rest of the command

- **Where:** `scripts/hooks/git_commands.py:102` (_tokens)
- **Defect:** The tokenizer uses shlex with its default comment character, which treats an unquoted `#` in the middle of a word as a comment and drops the rest of the line. Bash only starts a comment at the beginning of a word. Every git command after such a word on the same line is invisible to both the policy guard and the commit lint.
- **How it fails:** Strings that pass both hooks with no invocation seen (verified on the pure parser): `[ $# -gt 0 ] && git checkout -b topic`; `echo ${x#y} && git commit -m x`; `open https://example.com/a#frag && git push origin topic`; `: a#b; git push --force origin main`. Bash runs the git command in each; the guard sees tokens only up to the `#`.
- **Fix:** Set `lexer.commenters = ''` and strip comments explicitly only where `#` starts a word (preceded by whitespace or a separator and outside quotes).
- **Action:** Fixed in `09f3ebd4`.

#### T1-06 (P2): The cache-deletion and pbxproj guards match one spelling each

- **Where:** `scripts/hooks/policy_guard.sh:58` (re_rm_build / re_rm_cache / re_pbxproj_write)
- **Defect:** The whole-build deletion regex only matches `build` written immediately after the flags and followed by whitespace or end of text, and the pbxproj regex only knows four writer spellings. Ordinary variants pass, including the absolute-path form agents use when the working directory resets between calls.
- **How it fails:** Pass the cache guard (verified): `rm -rf <repo>/build` (any absolute or `$PWD/` path), `rm -rf "build"`, `rm -rf build/*`, `rm -r -f build`, `rm --recursive --force build`, `rm -rf -- build`, `(rm -rf build)`, `bash -c 'rm -rf build'`, `cd build && rm -rf cache`, `find build -delete`. `rm -r -f build/cache` and absolute `.../build/cache` are blocked. Pass the pbxproj guard: `cp /tmp/p QwenVoice.xcodeproj/project.pbxproj`, `mv`, `sed -E -i ''`, `sed --in-place`, `perl -0pi`, `python3 -c "open(...,'w')"`, `dd of=`. Only the first three exact deny rules in settings.json back this up, and none covers an absolute path.
- **Fix:** Judge `rm` on tokens like git: resolve each operand against the payload cwd and block when it equals `<root>/build` or lies at or above `<root>/build/cache`, with any flag spelling. For pbxproj, block any non-read command whose operand or redirect target resolves to project.pbxproj, or drop the regex and rely on the project gate's generation stamp.
- **Notes:** confirmed by both verification passes; candidate T-10.
- **Action:** Fixed in `09f3ebd4`.

#### T1-07 (P2): The Simulator guard matches one destination spelling and six simctl verbs

- **Where:** `scripts/hooks/policy_guard.sh:47` (re_sim_destination / re_simctl_lifecycle)
- **Defect:** The Simulator guard matches one destination spelling and six lifecycle verbs written directly after the tool name. The most common phone-free Simulator build spelling and launching the Simulator app both pass.
- **How it fails:** A build that selects the Simulator SDK by name instead of by destination, a destination written with different spacing, the Simulator app opened by name, or a lifecycle verb preceded by an option all pass the guard, so a Simulator build or launch can start although the project is physical-iPhone only.
- **Fix:** Match the Simulator SDK name and target triples, the app launch by name, and lifecycle verbs after any options; add each spelling to scripts/tests/test_agent_hooks.py, building the strings from fragments as the tests already do.
- **Action:** Fixed in `09f3ebd4`.

#### T1-09 (P2): The read-only release-evidence skill pre-approves `gh api *` and `git tag*`

- **Where:** `.claude/skills/release-evidence/SKILL.md:6` (release-evidence allowed-tools)
- **Defect:** The `release-evidence` skill is described as read-only and never publishing, but pre-approves `Bash(gh api *)` with any HTTP method and `Bash(git tag*)`. No hook inspects `gh`. The `xcresult-triage` subagent is likewise labelled read-only with unrestricted Bash, and the test that asserts read-only only rejects the edit tools.
- **How it fails:** While the skill is active these run without a prompt and pass both hooks: `gh api -X PATCH repos/<owner>/<repo>/releases/<id> -f draft=false` (publishes the draft, skipping promote-release.yml and quality-promotion validation); `gh api -X PATCH repos/<owner>/<repo>/git/refs/heads/main -f sha=<sha> -F force=true` (a force move of main without git); `gh api -X DELETE .../git/refs/tags/<tag>`. The parser returned no invocation for the `gh api` string.
- **Fix:** Narrow the grant to the three GET shapes the steps use, e.g. `Bash(gh api repos/*/git/ref/tags/*)`, `Bash(gh api repos/*/git/tags/*)`, `Bash(gh api --paginate --slurp repos/*/commits/*/check-runs*)`, and `Bash(git tag -l *)`. Have the test reject a bare `Bash` or `Bash(gh api *)` for anything described as read-only.
- **Notes:** confirmed by both verification passes; candidate T-13.
- **Action:** Fixed in `09f3ebd4`.

#### T1-10 (P2): `Bash(gh run *)` also auto-approves rerun, cancel and delete

- **Where:** `.claude/settings.json:93` (permissions.allow Bash(gh run *))
- **Defect:** `Bash(gh run *)` is pre-approved so CI can be watched, but it also auto-approves `gh run rerun`, `gh run cancel` and `gh run delete`. Re-running a release or promotion run is a release action that the same file puts behind a prompt when spelled `gh workflow run`.
- **How it fails:** 1) A release.yml or promote-release.yml run fails. 2) The agent, following a failed run, issues `gh run rerun <run-id> --failed`. 3) The command matches the allow rule, no hook inspects `gh`, and it runs without a prompt. 4) The signing/draft-upload jobs or the publish step (`gh release edit ... --draft=false`) execute again without an explicit request. `gh run delete <id>` likewise removes a run record unprompted.
- **Fix:** Replace the rule with `Bash(gh run list*)`, `Bash(gh run view *)`, `Bash(gh run watch *)` and `Bash(gh run download *)`, and add `Bash(gh run rerun*)`, `Bash(gh run cancel*)`, `Bash(gh run delete*)` to `ask`. Extend the consent test to assert no allow rule matches `gh run rerun`.
- **Action:** Fixed in `09f3ebd4`.

#### T1-55 (P2): `$(which git) push --force` and similar spellings are not recognised as git

- **Where:** `scripts/hooks/git_commands.py:129` (_is_git / git_invocations substitution handling)
- **Defect:** Git is recognised only when a token's basename is literally `git`, and backtick bodies are replaced by `SUBST` after parsing, so `$(which git) push --force origin main`, `"$(command -v git)" push -f origin main`, `` `which git` push --force origin main ``, `` git `echo push` --force origin main `` and the brace-expansion spelling `{git,push,--force,origin,main}` produce no judged push; the same spellings make `commit` invisible to commit_lint (no branch check, no privacy scan). The push remote is also never judged (`git push https://host/other.git main` is allowed).
- **How it fails:** 1) Agent runs `$(which git) push --force origin main`. 2) Tokens become `$`, `(`, `which`, `git`, `)`, `push`, ...; the `git` token is taken as an invocation whose subcommand is `)`, so policy_violation returns nothing and policy_guard exits 0; the deny prefix `Bash(git push --force*)` does not match the leading `$(`. 3) The force push proceeds if the user approves the prompt (no allow rule matches), i.e. the hook that is meant to block force pushes 'regardless of intent' is silent. Same for `$(which git) commit -m x` -> commit_lint sees no commit and skips the branch, whitespace and privacy checks.
- **Fix:** Treat `$(which git)`, `$(command -v git)`, `"$(type -P git)"` and their backtick forms as the git token (detect `which\|command -v\|type -P` followed by `git` inside a substitution and splice `git` into the token stream); treat a `SUBST`/`$`-bearing subcommand or any `{...,...}` token containing `git` as computed and fail closed; optionally restrict `push` to the `origin` remote or the configured remote name. Add these spellings to test_git_spellings_do_not_bypass_the_main_only_rules.
- **Action:** Fixed in `09f3ebd4`.

#### T2-02 (P2): The promotion diff base is whatever the manifest author passed

- **Where:** `scripts/quality_promotion.py:625` (validate_manifest / changed_paths)
- **Defect:** The promotion base is whatever the manifest author passed to `--base`. Validation only requires a distinct ancestor of the candidate; nothing ties it to the previous public release (config/public-product-facts.json stableMacRelease is never read). Every path-classified lane (engine, Quality-tier engine, retained memory, UI performance, language, delivery, model-download lifecycle) is derived from `base..tag`, so a nearer base shrinks the required evidence to the platform minimum and promote-release.yml accepts it.
- **How it fails:** 1. v3.0.0 is tagged; the true diff since public v2.4.0 touches catalog, memory, UI and engine routing classes. 2. The operator runs `quality_promotion.py create --base v3.0.0-rc.1` (a never-promoted candidate tag, the natural reading of the runbook's `<previous-tag>`) or `--base HEAD~1`. 3. `changed_paths` returns a handful of paths matching no class, so `requiredEvidence` is only `macos-ui-benchmark`. 4. promote-release recomputes the same small set from the manifest's own baseCommit and publishes without the other lanes.
- **Fix:** In validate_manifest (and create), require baseCommit to equal the commit of `stableMacRelease.tag` from config/public-product-facts.json at the candidate tag (or of the newest tag whose GitHub Release is public), and reject any other base.
- **Notes:** also reported as T4-03.
- **Action:** Fixed in `e45d3ad2`.

#### T2-03 (P2): release.yml has no concurrency group and cannot archive iOS alone

- **Where:** `.github/workflows/release.yml:182` (jobs.package (no `if`, no workflow concurrency))
- **Defect:** release.yml has no `concurrency:` and no way to request the iOS archive alone. The documented iOS dispatch (`-f archive_ios=true` on the same tag) also runs `package`, which re-signs and re-notarizes a new macOS DMG, deletes every asset on the existing draft (including the maintainer-uploaded quality-promotion.json) and replaces the qualified DMG with different bytes. The runbook states the opposite. A dispatch issued while the tag-push run is still packaging gives two package jobs resetting and uploading to the same draft.
- **How it fails:** 1. Tag push builds the macOS draft; the maintainer qualifies that DMG and uploads quality-promotion.json. 2. The maintainer runs `gh workflow run release.yml --ref v3.0.0 -f tag=v3.0.0 -f archive_ios=true` for the IPA. 3. `package` runs again and 'Reset draft Release assets' deletes the DMGs, evidence and quality-promotion.json, then uploads a newly notarized DMG. 4. Promotion fails on the missing manifest; regenerating it from the same source-bound records publishes a DMG that was never the one hand-qualified. If the release was already public, the job signs, notarizes and attests a second DMG before failing at the draft check.
- **Fix:** Add `concurrency: { group: release-${{ env-independent tag expression }}, cancel-in-progress: false }` to release.yml and promote-release.yml (same group), and add a dispatch input or `if:` so an `archive_ios` dispatch skips `package` unless a macOS rebuild is explicitly requested; correct the runbook sentence.
- **Notes:** candidate T-6; also reported as T2-56.
- **Action:** Fixed in `e45d3ad2`.

#### T2-05 (P2): A change to the public facts file never runs the website check that depends on it

- **Where:** `scripts/ci/classify_changes.py:277` (classify)
- **Defect:** The website lane is enabled only by `website/` paths, but the website's lint step reads config/public-product-facts.json and fails when website/src/data/release.js does not mirror it. A facts-only change never runs that check, and the Python public-facts contract does not compare release.js either, so main stays green with a stale download mirror.
- **How it fails:** 1. After promotion a commit bumps stableMacRelease to 3.0.0 in config/public-product-facts.json and the README link (which the Python contract demands), leaving website/src/data/release.js at 2.4.0. 2. Routing yields website=false; `CI required` is green. 3. The site keeps offering the 2.4.0 DMG as the stable download. 4. The next unrelated website commit fails `site-contract.mjs` and is blamed for a break it did not cause.
- **Fix:** Route `config/public-product-facts.json` to the website lane in classify() (a WEBSITE_INPUTS tuple beside the `website/` prefix test).
- **Notes:** confirmed by both verification passes; candidate T-7.
- **Action:** Fixed in `09f3ebd4`.

#### T3-01 (P2): The native build lock spins forever when its parent directory is not writable

- **Where:** `scripts/lib/build_cache.sh:115` (acquire_native_lock)
- **Defect:** When the lock directory cannot be created but its parent exists (parent not writable), the acquire loop takes the `continue` branch forever: no sleep, no `waited` increment, no timeout, no error. Every native build or test then burns a core silently instead of failing.
- **How it fails:** 1. The lock parent (~/Library/Caches/Vocello) exists but is not writable for this process (root-owned after one sudo build, read-only volume, or a write-restricted agent sandbox). 2. Run scripts/dev.sh test or build -> xcb_run -> acquire_native_lock. 3. `mkdir "$lock_dir"` fails, `-d` is false, `-e` is false, `mkdir -p` of the existing parent returns 0, so the code hits `continue`. 4. The loop repeats at 100% CPU indefinitely; QVOICE_NATIVE_LOCK_WAIT_SECONDS never applies and 'cannot create the native lock' is never printed.
- **Fix:** Count the `continue` branch against the wait budget: sleep and increment `waited` there, or allow one immediate retry and then fail with 'cannot create the native lock' when mkdir fails while the path still does not exist. Add a test with a chmod 555 parent.
- **Action:** Fixed in `04bec09a`.

#### T3-02 (P2): A macOS UI lane's EXIT trap can exit 1 and mask the lane's real result

- **Where:** `scripts/ui_test.sh:803` (cleanup_ui_run)
- **Defect:** The EXIT trap of a macOS UI lane calls terminate_macos_app, which `die`s (exit 1) when any Vocello process is not the lane's own build product. That exit inside the trap skips ledger finalization and `write_run_metadata failed`, so run.json stays `running` and retention treats the dead run as active.
- **How it fails:** 1. The dev app from `scripts/dev.sh run` (the -Onone arena, a different path from the lane's optimized arena) or an installed Vocello is running. 2. Start `scripts/ui_test.sh macos smoke`; line 1486 terminate_macos_app dies with 'cannot establish exclusive Vocello ownership'. 3. The EXIT trap runs cleanup_macos_run -> terminate_macos_app -> die again, exiting from inside the trap. 4. required_steps_finalize and write_run_metadata failed never run: run.json keeps status running, the ledger is unfinalized and the take manifest is not removed.
- **Fix:** Make cleanup non-fatal: run the ownership check in a subshell inside the trap (`( cleanup_macos_run ) \|\| status=1`) or give terminate_owned_processes a non-dying mode for cleanup, so finalization and `write_run_metadata failed` always run.
- **Action:** Roadmap DA-12.

#### T4-51 (P2): A change under Packages/VocelloQwen3Core/Tests routes to no CI lane

- **Where:** `scripts/ci/classify_changes.py:201` (_is_swift / _is_ios)
- **Defect:** A change under Packages/VocelloQwen3Core/Tests/ routes to no lane, although the macOS job's `scripts/macos_test.sh test` is what compiles and runs those Qwen3RuntimeTests, so a runtime-test-only push skips the only lane that executes it and the skip is then recorded as proven for every later diff.
- **How it fails:** 1. Push a commit that only edits Packages/VocelloQwen3Core/Tests/Qwen3RuntimeTests/Qwen3DecoderPartitionTests.swift (commit 5619004c is exactly such a commit). 2. classify_changes reports swift=false (verified: `--paths` prints `swift=false ios=false python=false ...`), so ci.yml skips 'Run deterministic macOS tests' and the run is green. 3. lane_bases() treats the skipped job inside a green run as proven at that head, so the next swift-lane diff starts after this commit. 4. A broken or newly failing runtime test (or a compile error in the test target, which fails `swift build --build-tests` and thus the whole macOS lane) lands on main green and is first seen by nightly or by an unrelated later Swift change.
- **Fix:** In `_is_swift`, route `Packages/*/Tests/` (or any path under a package that is not prose) to the swift lane: e.g. `if path.startswith("Packages/"): return "/Sources/" in path or "/Tests/" in path or path.endswith(PACKAGE_MANIFESTS)`; add the path to test_classify_changes.ClassificationTests.test_compile_and_contract_inputs_still_route with expected {"swift"}.
- **Action:** Fixed in `09f3ebd4`.

#### T5-01 (P2): The rule that a done roadmap item cites resolvable evidence never runs

- **Where:** `scripts/roadmap.py:289` (validate / load_archive)
- **Defect:** The roadmap's rule that a done item must cite resolvable evidence never runs. A done item is rejected in config/roadmap.json and must move to config/roadmap-archive.json, which is never validated. 15 of 213 archived done items have no evidence at all (QC-01, QC-02, QC-03, QC-05, BT-02, PA-32, AUD-05, AUD-08, AUD-10, AQ-01 to AQ-06). A further 58 references use a 'run:' kind the resolver rejects as unknown.
- **How it fails:** 1. Move an item to roadmap-archive.json with status done and no evidence, as QC-03 was on 2026-10-06. 2. roadmap.py validate and render --check pass. 3. Its dependants (QC-04, QC-06, QC-08 on QC-03; AV-17 on BT-02) count as unblocked and the plan's progress percentage rises, on an unverified self-assertion.
- **Fix:** Validate archived done items for non-empty evidence. Resolve evidence at closure, for example for archive items whose updated date falls inside a recent window, or record a resolved-at commit. Add 'run' as a known kind or convert those references.
- **Action:** Fixed in `04bec09a`.

#### T5-02 (P2): Promotion routing leaves 188 of 446 product files in no class

- **Where:** `config/quality-promotion-contract.json:410` (promotionRouting.classes)
- **Defect:** Promotion routing leaves 188 of 446 tracked product files (135 Swift files, project.yml, the entitlements file) in no class, so changing them adds no promotion evidence beyond the platform UI benchmark. The gaps are inconsistent with the classes' own intent. memory-runtime covers Sources/QwenVoiceCore/*Memory*.swift and the iOS store but not Sources/Services/MacMemoryBudgetPolicy.swift or MacWarmupAdmissionPolicy.swift. model-catalog-and-delivery lists the Mac TTSModel, TTSContract and ModelManagerViewModel but not the iOS copies under Sources/iOSSupport. platform-ui covers Sources/Views/** and Sources/iOS/** but nothing under Sources/SharedSupport. Two include globs match no file. Nothing checks completeness.
- **How it fails:** 1. A point release after 3.0.0 changes only Sources/Services/MacMemoryBudgetPolicy.swift (admission and critical-band unload thresholds). 2. classify_paths matches no class. 3. Promotion requires only macos-ui-benchmark; macos-retained-memory evidence is never requested for a memory-policy change.
- **Fix:** Add the Mac memory and warm-up policies to memory-runtime, the iOSSupport model/contract/manager copies to model-catalog-and-delivery, and Sources/SharedSupport/Views and ViewModels to platform-ui. Remove the two dead globs. Have validate-contract fail when a tracked Sources/**.swift file matches no class and is not on an explicit no-evidence list.
- **Action:** Fixed in `e45d3ad2`.

## 4. Confirmed findings, P3

Hygiene, latent or narrow-reach defects. Each was reproduced by reading and has no covering guard.

### Engine, runtime and CLI

| ID | Where | Defect | Action |
| --- | --- | --- | --- |
| E1-03 | `Qwen3TTS.swift:2355` | The four legacy AsyncThrowingStream producers start with guard let self else { return } and never call continuation.finish(). | Roadmap DA-06. |
| E2-02 | `MLXTTSEngine.swift:1468` | NativeMLXAllocatorControl is documented as the process-wide MLX allocator side effects of the engine's memory lifecycle, and .inert is meant to keep the ThreadSanitizer-run core test bundle off MLX. It covers only trimMemory's clearCache and… | Roadmap DA-05. |
| E3-01 | `LatestEventCoalescer.swift:43` | If the drain task is already cancelled when `withTaskCancellationHandler` is entered, the handler runs before the body installs the waiter, so the continuation is installed with nobody left to resume it; the comment's no-leak claim does not hold for that… | Roadmap DA-06. |
| E3-03 | `AudioQCSignalObserver.swift:444` | When the frame hop exceeds the FFT size (sample rates above 102,400 Hz that are multiples of 100, e.g. 176,400 or 192,000), `start` can exceed `pending.count` after the last analyzed frame and `pending.removeFirst(start)` traps. | Roadmap DA-06. |
| E3-04 | `GenerationOutputAdapter.swift:429` | The stream-session directory is keyed by a per-process `requestID` counter under a root the macOS app and the `vocello` CLI share (`QwenVoice/cache/stream_sessions`), so one process's `makeSessionDirectory` removes another process's `session_%04d` directory… | Roadmap DA-06. |
| E4-02 | `Qwen3TTS.swift:3240` | Loading falls back to a default talker config when config.json has no `talker_config`, but generation and prewarm force-unwrap `config.talkerConfig!`, so a checkpoint that loads successfully traps on its first generate/prewarm instead of failing closed at… | Roadmap DA-04. |
| E4-03 | `Qwen3TTS.swift:3213` | The `memoryClearCadence` parameter is discarded (`_: Int?`) and the loop always uses `memoryPolicy.tokenMemoryClearCadence`, so the quality-first entry points' `productionFullResultMemoryClearCadence = 0` ('no cadence clears') is silently ignored and… | Roadmap DA-04. |
| E5-01 | `HuggingFaceDownloader.swift:2279` | A staging partial that is already at the catalog size but fails the SHA-256 check is kept after a `.fail` disposition, and every later single-stream attempt resumes it with `Range: bytes=<size>-`, which the server answers with HTTP 416; 416 is classified… | Fixed in `5b3ebba2`. |
| E5-02 | `ModelAssets.swift:348` | Installed-artifact identity is never compared with the descriptor's pinned repo/revision: `deepIntegrity` verifies files only against the manifest's own recorded sizes/digests (it checks `targetFolder` and the required path set, never… | Roadmap DA-06. |
| E5-03 | `ModelAssets.swift:394` | A manifest entry or RepoFile whose `sha256` is nil or not 64 lowercase hex silently skips hashing: `deepIntegrity(.contentDigest)` returns `.verified(checkedFiles:)` and `validateDownloadedFile` returns without hashing (and skips the size check when… | Fixed in `5b3ebba2`. |
| E5-04 | `ModelAssets.swift:267` | `LocalModelAssetStore.init(modelRegistry:)` silently `removeItem`s every folder in `legacyInstallFolderNames` that the supplied registry does not list, and those three names are exactly the current macOS Quality artifact folders (`…-CustomVoice-8bit`,… | Roadmap DA-06. |
| E5-05 | `ProductionModelCatalog.swift:561` | The catalog validator (Swift `isSafeRelativePath`, schema v2 `relativePath: minLength 1`, and `IOSModelDeliverySupport.validate`) accept a path component that starts with '.', but the downloader rejects every dot-prefixed component as `invalidRemotePath`; a… | Roadmap DA-06. |
| E6-01 | `BatchCommand.swift:199` | The short-form `vocello batch` throughput figure (`wallSeconds` in the JSON summary and the "Xs audio in Ys" note) is measured with `Date()` although native.md requires `ContinuousClock` for any throughput wall time; the same file's long-form branch,… | Fixed in `5b3ebba2`. |
| E6-02 | `Support.swift:38` | A bare flag that is followed by a positional token silently consumes that token as its value, so the flag reads as unset and the positional disappears; the parser only documents the inverse limitation (a value cannot begin with `--`), and the explicit… | Roadmap DA-06. |

### iOS and macOS apps

| ID | Where | Defect | Action |
| --- | --- | --- | --- |
| A10-05 | `IOSGenerationModeViews.swift:197` | The iOS mode views run `PromptLanguageDetector.detect(promptText)` synchronously on the main actor after the 350 ms debounce, in all three modes. | Fixed in `8e8d5556`. |
| A10-06 | `IOSGenerateFlowViews.swift:7` | `IOSGenerateContainerView` declares `@EnvironmentObject` `audioPlayer` and `ttsEngine` and a `hasAnyInstalledModel` computed property. | Fixed in `8e8d5556`. |
| A12-06 | `VocelloPrimaryCTAButton.swift:196` | The primary CTA scales its .headline title but forces a fixed 56 pt (phone) frame height and sits in a fixed 64 pt Studio dock slot. | Fixed in `e62747f0`. |
| A12-07 | `IOSBottomSheets.swift:143` | Several sheet controls are below 44 pt, although the control-audit contract lists 44 pt as the minimum for the sheet-navigation family. | Fixed in `e62747f0`. |
| A12-08 | `MacInlinePlayerCard.swift:82` | Three VoiceOver values are hard-coded English literals in an app that ships French. | Fixed in `e62747f0`. |
| A12-09 | `ios-control-audit.json:491` | Several control-family identifier patterns name identifiers that no longer exist in code, and the validator cannot notice. voices-surface lists voicesFilterButton, voicesImportAudioFile and voicesSaveNewVoice. | Fixed in `e62747f0`. |
| A12-10 | `IOSBottomSheets.swift:1062` | The voice-picker filter chip identifier is built from the localized visible label. | Fixed in `e62747f0`. |
| A12-11 | `IOSVoicesView.swift:394` | The language tag pill (EN, ZH, ...) on every Built-in Voices row uses a fixed 10 pt non-scaling system font inside a fixed 20 pt frame, while all neighbouring text scales. | Fixed in `e62747f0`. |
| A13-01 | `IOSShellPrimitives.swift:859` | The iOS utility buttons apply the system glass button styles (.glassProminent / .glass) directly, outside IOSGatedGlassModifier. | Fixed in `2b2b7bf4`. |
| A13-02 | `Theme.swift:195` | The iOS Theme says it forwards to the shared VocelloTheme but redeclares several tokens as literals. | Fixed in `2b2b7bf4`. |
| A13-03 | `IOSGenerationSharedViews.swift:320` | The notice reads `iosReduceTransparencyEnabled` itself to choose its solid backing opacity (0.18 vs 0.06) and passes no `gatedFill`. | Fixed in `2b2b7bf4`. |
| A13-04 | `Theme.swift:22` | Theme claims to forward to the shared VocelloTheme but re-declares a large set by value: Brand.goldSoft/goldGlow, Surface.glassSurface/glassSurfaceMuted/glassFloating/hairline/glassOuterStroke/glassInnerStroke, accentSurface/Stroke/Wash, glassTint,… | Fixed in `2b2b7bf4`. |
| A13-05 | `ThemeModifiers.swift:122` | Several design-system helpers have no callers: `ThemeShape`, `Color.themeOnAccent`/`themeOnAccentPressed`, `ThemeFeedback.Selection`, `View.iosDockGlass`, `View.iosSectionGlass` (whose comment says studio dock and section group use them),… | Fixed in `2b2b7bf4`. |
| A14-06 | `MacStudioGenerationRequestFactory.swift:19` | The Voice Design and Voice Cloning factories omit streamingInterval while Built-in Voice, the iOS views, long-form segments and the warmup coordinator's Design request all pass GenerationSemantics.appStreamingInterval, so on 16 GB and larger Macs Design and… | Fixed in `8e8d5556`. |
| A14-07 | `IOSAppDefaults.swift:33` | The vocello.ios.autoplayCompletions preference accessor has no reader or writer anywhere; the live autoplay setting on both platforms is the autoPlay key. | Fixed in `5b3ebba2`. |
| A14-08 | `MacGenerationWarmupCoordinator.swift:166` | A warm intent that arrives while the engine is not ready or busy, or that the admission gate defers, is dropped, and nothing schedules it again when the engine state changes: the shell's snapshot handler only calls observe(), which never schedules, although… | Fixed in `8e8d5556`, `105bdac3`, `303ad901`. |
| A14-52 | `MacStudioSingleTakeGenerationHooks.swift:40` | On macOS a Stop (⌘. or the Studio Cancel) accepted while generationCompleted is suspended in History persistence still lands the take in History (and announces "stopped"), because the executor's cancellation check runs only before generationCompleted and the… | Fixed in `64ad6677`. |
| A14-53 | `MacGenerationWarmupCoordinator.swift:289` | A prefetch or clone prime the store refused (thermal or memory-band gate inside allowsProactiveWarmOperations) is recorded as a completed warm whenever the model is already loaded, so the same Studio intent is never re-warmed after the gate clears and the… | Fixed in `8e8d5556`, `105bdac3`, `303ad901`. |
| A14-55 | `MacWarmupAdmissionPolicy.swift:21` | The type's doc comment still says the warm gate defaults to `records` while validating, but Mode.fromEnvironment defaults to `.enforce` (flipped 2026-06-09 per the inline comment), so the header misdescribes shipped behavior. | Fixed in `8e8d5556`. |
| A15-01 | `project.yml:304` | The two diagnostics compile capabilities are injected through build settings that project.yml never defines, so their value in a distribution build is whatever the xcodebuild process environment supplies. | Roadmap DA-12. |
| A15-02 | `project.yml:366` | The VocelloiOS target carries a `resources:` key, which native.md forbids outright, and the project's own comment 35 lines above says entries under that key are silently dropped. | Roadmap DA-12. |
| A15-03 | `project.yml:149` | Because the macOS target globs all of Sources/ and excludes only retired paths, the Mac app's Resources phase carries iPhone-only material that no Mac code reads: the nine voice-preview WAVs (about 1.5 MB), qwenvoice_ios_model_catalog.json, and the developer… | Roadmap DA-12. |
| A15-04 | `project.yml:683` | VocelloiOSUITests turns warnings-as-errors off for the whole bundle, while native.md and the workflow doc both state that every owned target treats warnings as errors. | Roadmap DA-12. |
| A15-05 | `project.yml:532` | VocelloCoreTests compiles the iOS copies of TTSContract, TTSModel, AppPaths, AppPerformanceSignposts and ModelManagerViewModel (and neither AudioService), so the macOS copies cannot join any unit-test target. | Roadmap DA-12. |
| A15-52 | `project.yml:353` | The developer-facing `Sources/Resources/voice-previews/README.md` is bundled into both shipping app bundles because the voice-previews folder is added as a resource folder on iOS and the QwenVoice `Sources/Resources` resource glob excludes only… | Roadmap DA-12. |
| A16-01 | `GenerationTelemetryJSONLSink.swift:69` | The QWENVOICE_DIAGNOSTICS_MAX_MB knob is clamped from below (max(1, n)) but not from above, and the result is multiplied with Swift's trapping Int operator. | Roadmap DA-06. |
| A16-02 | `IOSCrashObserver.swift:85` | Crash and hang payloads from one MetricKit delivery are written under a name built from a one-second-resolution timestamp, so a batch of two or more diagnostic payloads overwrites itself and only the last survives. | Roadmap DA-06. |
| A2-03 | `HistoryPersistenceError.swift:28` | The typed History storage errors have English-only literal descriptions. | Fixed in `1662434c`, `86fd0afe`. |
| A2-04 | `HistoryDeletionEngine.swift:43` | A single delete commits the row deletion before any durable record of the audio removal exists. | Fixed in `8ad9723c`, `86fd0afe`. |
| A4-01 | `IOSSavedOutputsDestination+Commerce.swift:8` | The automatic Files-folder copy reads the purchase state synchronously at completion. | Fixed in `21ea84ab`, `6306e841`. |
| A4-02 | `IOSExportPurchaseState.swift:144` | Purchase maps a thrown user cancellation to `.cancelled` through `isUserCancellation`, but Restore does not. | Fixed in `21ea84ab`. |
| A5-03 | `IOSModelDownloadCoordinator.swift:274` | When the durable cancel intent cannot be written for an active download, the coordinator publishes .failed with a message telling the user to 'Retry Cancel' while the transfer keeps running in inflight; the row in .failed state shows only Retry, and Retry… | Fixed in `8ad9723c`. |
| A5-04 | `IOSModelDownloadCoordinator.swift:239` | Cancelling a queued (pending) model calls stopDiagnosticsHeartbeat(), which cancels the single diagnosticsHeartbeat task that belongs to the different model currently downloading, so that model's heartbeat events stop for the rest of its transfer. | Fixed in `8ad9723c`. |
| A5-05 | `IOSAppBootstrap.swift:212` | The installer's onModelInstalled hook is documented as the engine preload after an install, but the only assignment sets it to nil, so the post-install preload path described in the view model does not exist and the documentation is drift. | Fixed in `8ad9723c`. |
| A6-01 | `IOSAppBootstrap.swift:140` | The clone-gate decision is written with an unconditional `print` on every app launch and every startup Retry, while every other log line in the iOS lifecycle files is gated by `TelemetryGate.resolvedEnabled` or compiled out under `QVOICE_DEVICE_DIAGNOSTICS`. | Fixed in `5b3ebba2`. |
| A7-04 | `IOSStudioInlinePlayerCard.swift:813` | In adoption mode the display-link tick mirrors the shared player's state and returns early, so the ~15 fps CADisplayLink keeps firing after the shared player has stopped or finished; only the own-player branch invalidates the link. | Roadmap DA-07. |
| A8-02 | `IOSGenerationModeViews.swift:759` | The iOS 'Save generated voice' path hand-builds PreparedVoiceEnrollmentMetadata with transcriptSource: .manual for an untouched generation script or an empty transcript, bypassing VoiceClipTranscriber.preparedVoiceEnrollmentMetadata and the shared… | Fixed in `8e8d5556`. |
| A9-01 | `TTSEngineStore.swift:368` | The two host-layer generation-admission refusals are English literals wrapped in TTSEngineError.generationFailed(String); GenerationFailurePresentationReason maps that case to code "generation.failed", which init?(typedCode:) rejects, so… | Fixed in `1662434c`. |
| A9-02 | `localization-unlocalized-baseline.json:28` | The baseline carries a record for a Text literal in Sources/iOS/IOSStudioCanvas.swift that no longer exists (the literal was "\(script.count) / \(charLimit)", last present at commit 82843da6), and localization_contract.py only fails when a current count… | Fixed in `53e77deb`. |
| A9-03 | `GenerationDrafts.swift:225` | The shared VoiceCloningReadiness.describe with ten English-only title/detail strings is referenced nowhere in Sources or Tests; the Mac re-implements the same decision order in MacVoiceCloningReadiness with catalog keys and documents the shared copy as… | Fixed in `1662434c`. |
| A9-04 | `ModelManagerViewModel.swift:111` | The iPhone model inventory emits English computed statuses with a hand-rolled plural ("Installation incomplete: missing N required file/files.") and "Missing asset descriptor" (duplicating the already-localized IOSInterfaceText.missingDescriptor), and… | Fixed in `1662434c`. |

### Tooling, CI, release, docs and website

| ID | Where | Defect | Action |
| --- | --- | --- | --- |
| T1-04 | `git_commands.py:27` | Two parser desyncs hide real commands. | Roadmap DA-12. |
| T1-05 | `policy_guard.sh:31` | The policy guard strips every heredoc body before the Simulator, cache-deletion and pbxproj regexes run, including bodies fed to a shell. | Fixed in `09f3ebd4`. |
| T1-08 | `generated_file_guard.sh:26` | The generated-file guard compares paths case-sensitively, but the checkout is on a case-insensitive volume and the path adapter does not fold case. | Fixed in `09f3ebd4`. |
| T1-11 | `git_commands.py:365` | The git policy blocks `git config` writes to remote URL, mirror and push keys but has no case for `git remote`, which writes the same keys. | Roadmap DA-12. |
| T1-12 | `privacy_scan.py:29` | The scanner's home-path rule needs a separator after the user name, and its `sk-` rule needs 32 consecutive alphanumerics right after the prefix. | Fixed in `09f3ebd4`. |
| T1-13 | `settings.json:154` | The deny rules for stashing, broad staging, `commit -a` and release.sh are literal prefixes with no hook behind them. | Fixed in `09f3ebd4`. |
| T1-58 | `xcresult-triage.md:4` | The xcresult-triage subagent is described as read-only but is granted unrestricted `Bash`; the only enforcement is the parent's permission rules and hooks, and SubagentTests.test_project_subagents_are_read_only asserts only that no Edit tool is listed, so… | Roadmap DA-12. |
| T2-01 | `release.yml:228` | The signing jobs check out the mutable tag ref again instead of the commit that source-authority authorized. source-authority exports no commit, and the package job's only source check compares the tag to its own HEAD, so a tag that moves between the two jobs… | Fixed in `e45d3ad2`. |
| T2-04 | `release_source_authority.py:72` | The required-check selection matches only name, head_sha and the github-actions app, then takes the newest by completion time. ci.yml also produces a check named `CI required` on `pull_request` runs, where it aggregates the Linux lanes only and attaches to… | Fixed in `e45d3ad2`. |
| T2-06 | `classify_changes.py:102` | A Swift deterministic test reads scripts/tests/fixtures/audio_qc_codec_loop.json and asserts byte parity with the Python builder, but that fixture is missing from SWIFT_PARITY_FIXTURES, so changing it routes only the Python lane. | Fixed in `e45d3ad2`. |
| T2-07 | `classify_changes.py:349` | When the run-history fetch fails, routing silently falls back to the previous-push diff instead of running every lane. | Fixed in `e45d3ad2`. |
| T2-08 | `release.yml:960` | In archive-ios the App Store Connect .p8 (two copies), the unlocked distribution keychain and the provisioning profile stay on disk through the attestation and artifact-upload actions and are removed only by the job's last step. | Fixed in `e45d3ad2`. |
| T2-09 | `promote-release.yml:22` | The job that makes a release public has no `environment:` (the reviewer gate covers candidate production only) and verifies nothing outside the draft itself. | Fixed in `e45d3ad2`. |
| T2-10 | `release.yml:205` | The team ID, notary key ID and issuer ID secrets are set in job-level env, so every step of the package job receives them, including release.sh's build and test run and the attest and upload actions, although only release.sh and the verify scripts use them. | Fixed in `e45d3ad2`. |
| T3-03 | `macos_test.sh:1476` | `${coverage:+--enable-code-coverage}` expands whenever `coverage` is non-empty, and it is initialised to the string `0`. | Roadmap DA-12. |
| T3-04 | `check_ios_catalog.sh:54` | The EXIT trap decides 'is this my temp file' by the path prefix `/tmp/*`. | Roadmap DA-12. |
| T3-05 | `ios_device.sh:2921` | The launch-spec temp file holds the exact user script text and is promised to be ephemeral, but it is removed only on three guarded failures and at line 2953. | Roadmap DA-12. |
| T3-06 | `build_cache.sh:657` | On the interactive path (xcbeautify installed, stdout a TTY) xcb_run runs `set -o pipefail` then `set +o pipefail`, which turns pipefail off for the calling script for the rest of its run. | Roadmap DA-12. |
| T3-07 | `permissions_doctor.sh:105` | The mktemp template has a suffix after the Xs. | Roadmap DA-12. |
| T3-09 | `install_pinned_tools.sh:46` | `$MANIFEST` (the repo path) and `$tool` (a command-line argument) are pasted into Python source inside single quotes. | Roadmap DA-12. |
| T3-10 | `check_project_inputs.sh:23` | A value-taking flag given last exits 1 with no message: `--python` shifts once in its arm and the loop shifts again with nothing left, which fails under set -e. | Roadmap DA-12. |
| T3-11 | `repo_invariants.sh:50` | The invariant greps cannot tell 'no match' from 'the tool failed'. | Roadmap DA-12. |
| T3-12 | `verify_ios_release_archive.sh:53` | Under `set -euo pipefail`, a grep that finds nothing inside a command substitution fails the assignment and ends the script before the purpose-written error on the next line. | Roadmap DA-12. |
| T3-13 | `verify_release_bundle.sh:69` | Three build and verify paths kill by process name, so they terminate any running Vocello: the maintainer's installed release app as well as the build under test. verify_release_bundle.sh does it in its EXIT trap even when the launch smoke was skipped, and… | Roadmap DA-12. |
| T3-14 | `ios_device.sh:717` | The launch helper forwards every host variable starting with QWENVOICE_ or QVOICE_ into the iPhone app's environment. ios_device.sh sources build_paths.sh, which exports about 26 QVOICE_* variables holding absolute host paths (home directory, checkout path,… | Roadmap DA-12. |
| T3-15 | `verify_packaged_dmg.sh:103` | The attach-error formatter uses the GNU-only BRE operator `\+`, which BSD sed on macOS (the only platform this script runs on) treats literally, so whitespace is never squeezed. | Roadmap DA-12. |
| T4-01 | `classify_changes.py:251` | A change to the root .gitignore routes to no CI lane and no local Python selection, although two Python tests read the real .gitignore to prove credential files and the private QC store stay ignored. | Roadmap DA-12. |
| T4-04 | `required_step_ledger.py:459` | A second SIGINT/SIGTERM/SIGHUP that arrives while the first is being handled raises ManagedTermination inside the except block; it escapes run_managed_step and main, so the child is never SIGKILLed and no step manifest or ledger result is written. | Roadmap DA-12. |
| T4-05 | `test_qc_runners_speech.py:412` | The test swallows every exception and asserts nothing, so it passes whether the engine constructors raise ImportError, raise anything else, or succeed. | Roadmap DA-12. |
| T4-06 | `classify_changes.py:126` | Three research prefixes name scripts deleted with the QC v1 stack: run_local_delivery, prepare_delivery and independent_asr match no file under scripts/. | Roadmap DA-12. |
| T4-07 | `development_workflow.py:100` | The local Python selection ignores inputs that CI routes to the Python lane (pytest.ini, Sources/Resources/**, .github/workflows/**, Packages/**.json) and treats conftest.py as an ordinary module, so `scripts/dev.sh check` runs no or almost no Python tests… | Roadmap DA-12. |
| T4-08 | `test_qc_detectors.py:249` | Several phone-feature tests pass the default `Layout()` (the real repository root), so they read the developer's fetched QC model cache and shared G2P text cache under build/cache/qc; the same test computes with PanPhon distances on a Mac that has fetched… | Roadmap DA-12. |
| T4-09 | `test_required_step_ledger.py:479` | The test sends SIGTERM after a fixed 0.4 s sleep with no readiness handshake, so on a loaded runner the signal can arrive before the tool has installed its handlers. | Roadmap DA-12. |
| T5-03 | `concurrency-safety.json:122` | C10 confirmed. | Roadmap DA-12. |
| T5-04 | `ios-control-audit-schema-v1.json:54` | config/ios-control-audit.json does not conform to the schema it declares in $schema. | Roadmap DA-12. |
| T5-05 | `build-output-policy.json:12` | The UI-result retention list names 10 lanes, but scripts/ui_test.sh runs 13 and can also stamp 'candidate-smoke'. | Roadmap DA-12. |
| T5-06 | `roadmap.py:454` | The generated docs/ROADMAP.md lists archived, finished items in the 'Blocked by' column as if they still block. | Roadmap DA-12. |
| T5-07 | `runtime_security_contract.py:440` | The knob contract registers 23 device-diagnostics keys as behavior-mutating and 'unavailable-without-diagnostics-compilation-condition', but enforces nothing about them. | Roadmap DA-12. |
| T5-08 | `model_catalog_contract.py:371` | config/model-catalog-schema-v2.json is never used to validate the catalog; the tool checks only its $id and hashes its bytes. | Roadmap DA-12. |
| T5-09 | `public-product-facts.json:3` | The facts file says it is validated against project.yml and README, but only the marketing version, the stable DMG link and the canonical benchmark profiles are checked. ios.minimumOS, ios.minimumDevice, ios.testflightPublicLink, minimumMac.memoryBytes and… | Roadmap DA-12. |
| T5-10 | `generate_readme_charts.py:496` | The generated architecture chart embedded in README.md contains an em dash in visible text. | Roadmap DA-12. |
| T5-11 | `refresh_derived_artifacts.py:31` | The build-output policy table in docs/reference/privacy-storage.md is a generated block the contract gate checks for freshness, but it is not registered for regeneration, has no command that writes it, and is not covered by the generated-file guard. | Roadmap DA-12. |
| T5-12 | `roadmap.py:343` | Cycle detection follows only the first blocker of each item, so a cycle that passes through a second or later blockedBy entry is not detected. | Roadmap DA-12. |
| T5-54 | `runtime-debug-knobs.json:8` | scripts/build_ui_test_bundles.sh compiles with -DVOCELLO_INTERNAL_DIAGNOSTICS but is not listed in enabledBuildRoutes, and the contract validator only checks that listed enabled routes contain the condition and listed distributed routes do not, so an unlisted… | Roadmap DA-12. |
| T5-57 | `runtime_security_contract.py:16` | The concurrency registry is enforced with a single-line regex ([^\n{]* between the type name and @unchecked Sendable), so a declaration whose conformance list is wrapped onto the next line (common once a long list is reformatted, e.g. | Roadmap DA-12. |
| T6-01 | `macos-testing.md:407` | Three reference docs still say the macOS retained-memory-v2 bound and the M6 unobserved-gap bound are uncalibrated and gate nothing. | Roadmap DA-12. |
| T6-02 | `benchmarking-procedure.md:731` | benchmarking-procedure.md still describes the stall contract as a provisional 250 ms limit that only reports and never fails a run. | Roadmap DA-12. |
| T6-03 | `CONTRIBUTING.md:36` | CONTRIBUTING.md tells contributors ci.yml has no pull-request lane, so a fork's change only gets a verdict after a maintainer pushes it to main. | Roadmap DA-12. |
| T6-04 | `README.md:128` | README line 128 still says the published Mac figures were measured on the retired M2, and that 'the pinned Mac record' is the M2 record 379db820. | Roadmap DA-12. |
| T6-05 | `development-progress.md:334` | Commit 4051f87b deleted two dated docs that development-progress.md still links: the 2026-09-25 audio QC audit and the 2026-09-21 French delivery pilot. | Roadmap DA-12. |
| T6-53 | `SECURITY.md:36` | SECURITY.md says the signing jobs grant only codesign access to the temporary keychain. release.yml's partition lists also grant apple-tool: and apple: (the iOS job omits codesign: entirely), and the iOS import trusts /usr/bin/security. | Roadmap DA-12. |
| T7-01 | `Listen.jsx:21` | Starting a second sample while the first is still loading leaves the page showing nothing playing while the second sample is audible. | Roadmap DA-12. |
| T7-02 | `Engineering.jsx:113` | The website performance chart never says it measures the Speed (4-bit) models. | Roadmap DA-12. |
| T7-03 | `samples.js:12` | The Voice Design 'British narrator' row is labelled 0:08, but its WAV is 6.4 seconds long. | Roadmap DA-12. |
| T7-04 | `site-contract.mjs:86` | Public facts reach the site only through a hand mirror, and the contract checks just the version and tag of the stable and fallback releases. | Roadmap DA-12. |
| T7-07 | `samples.js:66` | DELIVERY_COLORS is exported but imported nowhere. | Roadmap DA-12. |

## 5. Plausible or disputed, not confirmed

A refuter found a partial guard or could not finish the trace, or the two verification passes disagreed. None of these enters the fix phase.

- **A10-04 (P2, plausible)** `Sources/ContentView.swift:26`: On Mac, `MacAppModel` holds the three StudioGenerationCoordinators, the line-batch runner and the long-form coordinator. Everything on the repo side matches the claim, and I found nothing that breaks the chain: no `onDisappear`, `willClose` or `deinit` in ContentView, MacAppModel or StudioGenerationCoordinator cancels the take, and a repo-wide grep for `applicationShouldTerminateAfterLastWindowClosed` and `applicationShouldHandleReopen`… **Action:** Roadmap DA-02 (the second pass could not settle SwiftUI's window-state behavior without running the app).
- **A13-52 (P2, plausible)** `Sources/SharedSupport/Views/VocelloGlassSurface.swift:19`: The gate is expressed as an if/else that wraps the caller's `content` in a different branch for each state. Every repo-side step is real: the if/else over `content`, the gate flipping on generation start/stop (every generation on macOS liquid builds; fixed-refresh iPhones on iOS), and focused TextFields plus whole edge-sheet panels sitting under the gate with no guard against being open when a take finishes. **Action:** Fixed in `2b2b7bf4`, `201194a6`.
- **A12-01 (P3, plausible)** `Sources/SharedSupport/Views/VocelloCapsuleSelector.swift:81`: The shared capsule selector (Studio mode selector on both platforms) has a hard fixed outer height (44 pt horizontal, 136 pt vertical) and single-line labels, so at accessibility Dynamic Type sizes the scaled labels can be truncated or clipped. What survives: on iOS only, at AX5 (and at AX4 if SwiftUI does not shrink the single-line Text for height), the vertical rail is 16 to 42 pt taller than its fixed 136 pt slot. **Action:** Fixed in `e62747f0`.
- **A13-06 (P3, plausible)** `Sources/iOS/IOSDesignSystemPrimitives.swift:617`: In the ungated branch the edge-to-edge sheet panel is pure `.regular` glass with only a 6% tint (`glassTint(tint, intensity: 0.45)`). The structure is as described (tint-only glass with no solid base in the ungated branch, 10 pt tertiary headers on it, no contrast check anywhere), but whether contrast actually falls below 4.5:1 is a measurement question the system glass material may or may not resolve. **Action:** Roadmap DA-03: a contrast question that needs a device measurement.
- **A3-01 (P3, plausible)** `Sources/iOSSupport/Services/IOSSavedOutputsDestination.swift:142`: The automatic Files-folder copy deletes any same-named file in the user's folder with try?, then copies straight to the final name with try?. A failed copy therefore loses the user's earlier file. the two passes agree on the code and disagree on reach: exported names are millisecond-unique, so losing a user's file needs a pre-placed file with the exact name **Action:** Fixed in `21ea84ab`.
- **A3-02 (P3, disputed)** `Sources/QwenVoiceCore/DocumentIO.swift:182`: Two helpers use delete-then-copy with no staging. Both code facts hold, but the reach is narrower than claimed. 1) Platform is iOS only, not both. **Action:** Fixed in `dde11229`.
- **E3-02 (P3, plausible)** `Sources/QwenVoiceCore/GenerationEventDeliveryProbe.swift:272`: A subscription created by `stream(for:)` whose producer never calls `beginGeneration`/yields a terminal is never removed from `active`: `consumerTerminated` only nils the channel, and `snapshot(consuming:)` only prunes `completed`. Confirmed, but reach is narrower than 'one entry per refused generate'. **Action:** Roadmap DA-06.
- **E4-04 (P3, disputed)** `Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSTalker.swift:300`: For a multi-token step on a non-empty KV cache the talker builds a `[seqLen, seqLen]` causal mask that ignores `cache.offset`, unlike the speech-tokenizer DecoderTransformer which slices the mask to `[seqLen, offset + seqLen]`; production only prefills on an… The static description is accurate (talker builds `createAdditiveCausalMask(seqLen)` while Qwen3TTSSpeechTokenizer.swift:491-496 slices to offset + seqLen), but no code path forwards more than one embedding on a non-empty talker cache. **Action:** Roadmap DA-04.
- **E7-01 (P3, plausible)** `Packages/VocelloQwen3Core/Tests/Qwen3RuntimeTests/Qwen3StreamingContractTests.swift:47`: Two of the three tests in the 'streaming contract' suite exercise no production code. Claim holds as read. **Action:** Fixed in `89896465`.
- **E7-04 (P3, disputed)** `Tests/VocelloCoreTests/TTSEngineStoreTests.swift:168`: The fake engine behind the store and runner suites does not mirror the real terminal-event contract. The divergence is real, but the consequence is narrower than the failure scenario says. **Action:** Declined: the store drops every non-chunk event, so a terminal-yielding fake changes nothing a store test can see; terminal order is now tested at the engine and adapter (`89896465`).
- **E7-05 (P3, plausible)** `Packages/VocelloQwen3Core/Tests/Qwen3RuntimeTests/Qwen3TalkerGenerateLoopTests.swift:420`: The token cap is asserted only if the seeded random-weight talker happens to reach it. Structural claim confirmed by reading; whether the current seed yields 2 or 3 frames cannot be settled without running it, so the failure scenario is conditional, as the finding itself says. **Action:** Fixed in `89896465`.
- **T1-15 (P3, plausible)** `.claude/settings.json:18`: Both command guards are wired only to the tool named `Bash`. The repo-side chain holds in full; the one step I could not read is the harness's hook dispatch, which lives outside the repository. - **Confirmed by reading:** the matcher is exactly `^Bash$` and cannot match the string `Monitor`. **Action:** Roadmap DA-12.
- **T3-08 (P3, plausible)** `scripts/regenerate_project.sh:37`: The entitlements backup uses the predictable path /tmp/QwenVoice.entitlements.backup.$$ instead of mktemp. Reach is narrower than the scenario states. **Action:** Roadmap DA-12.
- **T4-02 (P3, plausible)** `scripts/ci/classify_changes.py:255`: Research-marked tests are not triggered by several inputs they consume: scripts/qc/** modules, config/audio-qc-*.json and scripts/check_delivery_instructions.py route to the Python lane only, and the Python lane runs `-m "not research"`. Could not break the chain; no other job covers these consumers (grep finds test_audio_qc.py as the only Python reader of audio-qc-stage0-calibration.json). **Action:** Roadmap DA-12.
- **T7-05 (P3, plausible)** `website/vercel.json:3`: The production deploy does not depend on the website contract. Every repository-side statement in the claim checks out, and nothing in the tree makes the deploy wait for or depend on the website contract. **Action:** Roadmap DA-12.
- **T7-06 (P3, plausible)** `website/tests/browser-smoke.spec.mjs:51`: The browser smoke reads the nav progress transform once, right after the scroll position changes, with no polling. Split result. **Action:** Roadmap DA-12.
- **T7-53 (P3, unverified)** `website/scripts/prerender.mjs:30`: The pre-rendered body is injected with String.prototype.replace using a string replacement, so any `$&`, `` $` ``, `$'` or `$$` sequence in rendered copy is interpreted as a replacement pattern and corrupts the production dist/index.html (React escapes & to… Latent, not shipped: no `$` appears in rendered website copy at this commit. **Action:** Roadmap DA-12.

## 6. Candidate adjudication

The exploration maps listed 47 unverified candidates. Every one was assigned to an auditor.

| Candidate | Verdict | Finding |
| --- | --- | --- |
| A-1 | confirmed | A5-01 (P2, confirmed) |
| A-2 | confirmed | A14-02 (P2, confirmed) |
| A-3 | confirmed | A1-01 (P2, confirmed) |
| A-4 | confirmed | A4-01 (P3, confirmed) |
| A-5 | confirmed | A3-01 (P3, plausible) |
| A-6 | confirmed | A2-01 (P1, confirmed) |
| A-7 | not a defect: free export of pre-provenance voices is a documented decision | A8-03 (P3, refuted) |
| A-8 | confirmed (as A2-03; the iOS screen maps the error, the Mac screen shows it raw) | A2-03 (P3, confirmed) |
| A-9 | confirmed | A9-01 (P3, confirmed) |
| A-10 | confirmed | A6-01 (P3, confirmed) |
| A-11 | confirmed | A14-07 (P3, confirmed) |
| A-12 | not found: each platform's logic is tested against the copy it ships with (the residual is A15-05) | - |
| C1 | confirmed (E2-01; a maintainer decision) | E2-01 (P2, confirmed) |
| C2 | refuted: the publish is cancellation-guarded | E1-01 (P3, refuted) |
| C3 | not found | - |
| C4 | not found | - |
| C5 | not found | - |
| C6 | not found | - |
| C7 | not found | - |
| C8 | not found | - |
| C9 | confirmed | E5-03 (P3, confirmed) |
| C10 | confirmed | T5-03 (P3, confirmed) |
| C11 | confirmed | E2-02 (P3, confirmed) |
| C12 | not found | - |
| C13 | confirmed | E1-03 (P3, confirmed) |
| C14 | not found | - |
| C15 | confirmed | E6-01 (P3, confirmed) |
| T-1 | confirmed | T2-09 (P3, confirmed) |
| T-2 | refuted as a release risk: a staged catalog fails a Swift test in CI; the docs wording is T6 | T2-11 (P3, refuted) |
| T-3 | confirmed | T2-04 (P3, confirmed) |
| T-4 | confirmed | T2-10 (P3, confirmed) |
| T-5 | confirmed | T2-08 (P3, confirmed) |
| T-6 | confirmed | T2-03 (P2, confirmed) |
| T-7 | confirmed | T2-05 (P2, confirmed) |
| T-8 | refuted | T1-14 (P3, refuted) |
| T-9 | confirmed | T1-05 (P3, confirmed) |
| T-10 | confirmed | T1-06 (P2, confirmed) |
| T-11 | confirmed | T1-08 (P3, confirmed) |
| T-12 | confirmed | T1-01 (P2, confirmed), T1-02 (P2, confirmed), T1-12 (P3, confirmed) |
| T-13 | confirmed | T1-09 (P2, confirmed), T1-13 (P3, confirmed), T1-58 (P3, confirmed) |
| T-14 | confirmed | T3-04 (P3, confirmed) |
| T-15 | confirmed | T3-08 (P3, plausible), T3-09 (P3, confirmed), T3-10 (P3, confirmed) |
| T-16 | confirmed | T4-05 (P3, confirmed) |
| T-17 | confirmed | T4-02 (P3, plausible), T4-06 (P3, confirmed) |
| T-18 | confirmed | T7-04 (P3, confirmed) |
| T-19 | not found as new: the removed-script references are dated history | - |
| T-20 | not found | T6-05 (P3, confirmed) |

## 7. Test gaps

Behaviors the auditors found with no deterministic test, most valuable first per area.

- **A1:** (1) StudioGenerationAttemptAuthority / StudioGenerationCoordinator: requestCancellation after the engine has returned the take (a finalizing phase) must be rejected; no such phase or test exists. (2) IOSSingleTakeGenerationExecutor.run: a cancellation flag raised while generationCompleted is suspended (fake hook flips isCancellationRequested inside generationCompleted) must not persist or export and must end as… (3) IOSLongFormProjectRunner.run: cancellation requested while services.acceptLongFormProject is in flight (fake service that suspends) must not yield .completed for a studio attempt whose cancellation completed, and…
- **A5:** (1) IOSModelDownloadCoordinator.delete(model:): no deterministic test exists (only IOSModelDownloadCancellationSequenceTests pins the cancel order); a fake-engine test should prove a busy or loaded engine blocks or unloads… (2) IOSModelInstallerViewModel.state(for:) x IOSModelRow.actionControls: for ModelStatus.incomplete with an eligible descriptor the row must expose iosModelDelete_<id> (Remove) alongside Repair. (3) IOSModelDownloadCoordinator.cancel(modelID:) .intentPersistenceFailed: the published state must still offer a cancel path (or install() must not be a silent no-op while the model is inflight). (4) IOSModelDownloadCoordinator.cancel(modelID:) pending branch: the inflight model's diagnostics heartbeat keeps running after a different queued model is cancelled. (5) IOSModelInstallerViewModel.handleBackgroundEventsCompletion + coordinator.resumeBackgroundEventsIfNeeded/restoreInFlightDownloadsIfNeeded: a ledger with no request (or a set-aside document) completes the stored handler…
- **A6:** (1) IOSAudioSessionLedger: no transition for an external deactivation. (2) IOSBackgroundGenerationController: no test that the expiration handler suspends History and ends the grant while a barrier is still awaited, and that a barrier returning after expiry (still backgrounded, same epoch)… (3) IOSAppDependenciesContainer: `retry()` after a failed `makeBackend` re-evaluates `cloneCapableLoadProfile()` and re-registers `IOSModelDeliveryBackgroundEventRelay.handler`; a unit test over the Result-driven…
- **A7:** (1) IOSInlinePlaybackController: after adoptLive(), load(url:) then play() must start the card's own player when the shared player is idle (asserts isLiveMirroring is cleared on adopt/load/stop). (2) IOSInlinePlaybackController.tick: the display link stops once the mirrored shared player reports isPlaying == false. (3) ReferenceClipRecorder (iOS) + IOSRecordingOverlay: an activation failure in start() sets recordingFailed and the overlay renders a visible failure status. (4) AudioPlayerViewModel live resume: currentTime continuity across underrun/pause resume (device lane with QWENVOICE_LIVE_PREVIEW_PREBUFFER_SECONDS forced small), and that explicitPlay after such a resume positions at the… (5) AudioPlayerViewModel.appendLiveChunk: a preview chunk whose sampleRate differs from the pre-warm format reconfigures the graph instead of scheduling a mismatched buffer.
- **A8:** (1) IOSPlayerSheetItem.from(savedVoice:): export provenance for a voice with nil enrollmentMetadata, with metadata lacking generatedSourceMode, and with a sidecar whose schemaVersion mismatches (expected gated or explicitly… (2) MLXTTSEngine.deletePreparedVoice / PreparedVoiceRepository.delete: after cloning a non-canonical (m4a/mp3/44.1 kHz) saved voice, deletion leaves no <id>_<fingerprint>.wav/.txt in cache/normalized_clone_refs. (3) IOSVoiceDesignView save-as-voice: persisted PreparedVoiceEnrollmentMetadata.transcriptSource for an untouched script and for an emptied transcript; Save disabled on an empty transcript without audio-only confirmation… (4) SavedVoicesViewModel (orchestrator, VocelloCoreTests only): busy-store retry schedules exactly three refreshes against a fake engine that keeps throwing savedVoiceStoreBusy, then stops; cancelBusyRetry during the sleep…
- **A9:** (1) VocelloPresentationText.generationFailureMessage: a TTSEngineError.generationFailed admission refusal from TTSEngineStore (both strings) resolves to catalog copy in a non-English VocelloLocalization rather than the… (2) scripts/localization_contract.py _validate_literal_baseline: a baseline record whose literal no longer exists in the tree is reported (stale) rather than silently kept. (3) IOSModelInstallerViewModel.state(for:) / iOSSupport ModelManagerViewModel.status(from:): an .incomplete or descriptor-missing inventory state produces interface-language copy with correct plural for 1 vs N missing files.
- **A10:** (1) Shared saved-voice candidate for Design (to be extracted from MacAppModel.swift): the take's audio, transcript and brief survive a mode or tab remount, and `matches(draft:)` hides the Save action after the script or… (2) AppModel (or equivalent): a programmatic studio-mode change requested while a generation is active in another mode is refused (Voices tab, recorder onEnrolled, import onEnrolled). (3) QwenVoiceApp.startSelectedTTSEngineIfNeeded: an `initialize` failure surfaces a visible error and re-arms a retry, with a fake engine whose `initialize` throws once. (4) Mac MacAppModel lifetime: coordinators, long-form state and `appCommandRouter.isGenerationActive` stay consistent with the engine across a window close and reopen.
- **A14:** (1) QwenVoiceApp.startSelectedTTSEngineIfNeeded / TTSEngineStore.initialize: a fake backend whose initialize throws must leave the store with a visible error (or a retryable state), not isReady=false with no message; today… (2) MacStudioSingleTakeRunner + MacStudioSingleTakeGenerationHooks: a cancellation requested while generationCompleted is suspended (fake persistence that suspends until released) must not leave a History row after… (3) MacGenerationWarmupCoordinator: a prefetch the store refuses (fake store returning nil from prefetchInteractiveReadinessIfNeeded with the model loaded) must not set completedContext, so the same context reschedules once… (4) MacLineBatchRunner.run/finish: a take that ends with CancellationError without the runner's cancel() (memory-pressure reason) closes the Studio coordinator attempt and reports a non-user outcome (5) MacLineBatchRunner.run: first failing line ends .failed with earlier lines saved and later lines pending; cancel between two lines marks the remainder cancelled and awaits the barrier
- **A15:** (1) scripts/repo_invariants.sh: no check rejects a `resources:` key under the VocelloiOS target (the native.md rule is unenforced; A15-01). (2) Mac TTSContract.resolvedManifest / validate (Sources/Models/TTSContract.swift:113-250): the macOS variant expansion (one `isHardwareRecommended` per mode, variant-scoped ids) has no unit test because the Mac copy cannot… (3) Sources/Models/TTSContract.swift resolvedManifest/validate: for each NativeDeviceMemoryClass the bundled contract yields exactly one recommended model per mode, and the variant-scoped ids equal those of… (4) Sources/Models/TTSContract.swift model(id:): a base id resolves to the hardware-recommended variant; an unknown id returns nil. (5) Sources/Services/AppPaths.swift validatedDebugOverride: rejects relative paths, "/", non-writable and foreign-owned locations, and is inert without DebugMode (the iOS twin has tests; the Mac one has none).
- **A16:** (1) GenerationTelemetryPrivacy.failureNotes: a regression test that the persisted notes hold only a digest and a length and never the raw message (the failure rows at GenerationOutputAdapter:399 and NativeEngineRuntime:1273… (2) TelemetryGate.resolve(environment:): a pinned test that QWENVOICE_DEBUG alone and QWENVOICE_NATIVE_TELEMETRY_MODE=light alone enable telemetry. (3) IOSPullableDiagnosticsMirror.captureAuditOutput: a negative test that it returns nil for a run id without the control-audit or startup-reliability prefix, and that no user audio is copied when telemetry is off. (4) DiagnosticPrivacy.redactedText: a test that bare, unquoted file names are not redacted.
- **E1:** (1) GenerationOutputAdapter.run + MLXTTSEngine.generate: a cancel injected after the model terminal and before publish (marking test seam) must end .cancelled with no published file and no .completed event. (2) NativeEngineRuntime.ensureWarmStateIfNeeded / ensureDesignConditioningWarmStateIfNeeded: a cancelled model.prewarm* body must leave the resident model loaded (use a fake model that throws CancellationError, not a fake… (3) MLXTTSEngine.generate cancel branch: after a take cancelled during prepare, loadState must match runtime.loadedModelID(). (4) VocelloQwen3Engine.abortReservation: owner throw (injected via abortLifecycleHook) must still resolve abortCompletion and release the lease (documents that hardening is not needed or adds it). (5) Qwen3TTSModel.generateStream with a released model: the stream must finish (or the API must be removed).
- **E3:** (1) LatestEventCoalescer.waitForUpdate: entering with the task already cancelled must return without installing a waiter (cancel the drain task before its first wait, then assert `clear()`-free completion). (2) GenerationScopedEventRouter: a `stream(for:)` subscription cancelled before any `beginGeneration` must not remain in `active` (observable via a test-only count or by asserting `snapshot(for:)` returns the empty default… (3) PersistedWAVAudioQCAnalyzer.evaluate: a synthetic 192 kHz mono WAV must evaluate without trapping (hop > fftSize path in `observeSpectrum`). (4) GenerationOutputAdapter.run post-publish cancel: cancel the generate task after `publish()` succeeded and assert the terminal, the published file and the coordinator's recorded reason agree (evidence for E1's C2… (5) IncrementalPCM16WAVFileWriter.publish: a cancelled task must leave no file at the destination and no staging file beside it (covers the marking/QC cancel window end to end).
- **E4:** (1) Qwen3TTSModel.prepareInputs / validateOptimizedCustomVoiceTextEmbeddingLength: a one-text-token script must either generate (trailingTextHidden == EOS embed only) or be refused by a typed host validation before the… (2) Qwen3TTSModel.fromPreparedDirectory: a config.json without `talker_config` must fail at load, not trap at the first prewarm/generation (`config.talkerConfig!`). (3) Qwen3TTSTalkerModel.callAsFunction: a multi-token forward on a cache with offset > 0 must build a `[seqLen, offset + seqLen]` causal mask (currently untested and wrong). (4) generateVoiceDesign quality-first: assert the recorded `cache_clear_count` / `memory_clear_cadence` match the intended policy (callers pass 0, loop uses 50).
- **E5:** (1) HuggingFaceDownloader.attemptFileDownload: a partial already at `expectedSize` that fails `fileIsValid` must restart from zero (never send `Range: bytes=<size>-`), and an HTTP 416 must not pin the partial (E5-01). (2) LocalModelAssetStore.deepIntegrity: a manifest whose `repo`/`revision` differ from the descriptor's pinned identity must not be `.verified`; `ProductionModelCatalog.installedFileSizeMismatches` (or a sibling) must flag… (3) LocalModelAssetStore.deepIntegrity(.contentDigest) and HuggingFaceDownloader.validateDownloadedFile: a nil or non-hex digest must fail, not pass (E5-03; the existing test at ModelDownloadLifecycleTests.swift:380-391… (4) LocalModelAssetStore.cleanupLegacyInstallFolders: constructing the store with a Speed-only (resolved) macOS registry must not remove installed Quality folders (E5-04). (5) ProductionModelCatalog.validate vs HuggingFaceDownloader.validatedRelativeRepoPath: a dot-prefixed path component must be rejected by both or accepted by both (E5-05).
- **E6:** (1) BatchCommand.run (short-form): `wallSeconds` is monotonic (ContinuousClock) — BatchCommand.swift is not compiled into VocelloCoreTests (project.yml:473-484), so no test can pin the clock source today; a seam that… (2) Args.init: a bare flag followed by a positional token (`["status", "--json", "pro_custom_speed"]`) keeps `flag("json") == true` and `positionals == ["pro_custom_speed"]` (whichever behavior is chosen for E6-02), beside… (3) ModelsCommand.run: `status <id> --json` and `status --json <id>` produce the same filtered JSON (end-to-end check of the parser decision above).
- **E7:** (1) GenerationOutputAdapter.run (Sources/QwenVoiceCore/GenerationOutputAdapter.swift:182-327): the shipped terminal choreography has zero tests. (2) MLXTTSEngine.generate outer terminal emission (MLXTTSEngine.swift:1218-1255): `.cancelled` with ingress.reason vs coordinator reason, `.failed` for non-cancel errors, the terminalYielded == 0 guard, the… (3) NativeEngineRuntime.trimMemory soft and hard (NativeEngineRuntime.swift:635-684): only .inert allocatorControl is ever injected, so clearCache calls, preparedCloneConditioningCache.clear, prewarm-state reset and the… (4) NativeMemoryPressureMonitor (public, NativeMemoryPressureMonitor.swift:183-268): zero references. (5) CLI commands outside the Swift test bundle: BatchCommand, BenchCommand and ModelsCommand are not in project.yml's VocelloCoreTests compile list (lines 473-484 add only CLIProcessSupervisor, CLIBatchExecution,…
- **T1:** (1) commit_lint.sh / privacy_scan.py --staged: stage a blob containing a home path, then rewrite the working copy clean without re-adding, and assert the lint still blocks (today's… (2) commit_lint.sh: `git commit --all -m x`, `git commit -qa -m x`, `git commit -m x <path>`, `git commit --include <path>` must be blocked or have their working-tree content scanned. (3) policy_guard.sh: a heredoc body fed to `bash`/`sh`/`python3 -` that contains `rm -rf build/cache`, a pbxproj write or a Simulator destination must block. (4) policy_guard.sh: `rm -rf build/*`, `rm -r -f build`, `rm --recursive --force build`, `cp x QwenVoice.xcodeproj/project.pbxproj`, `mv x ...project.pbxproj`, backslash-escaped `platform=iOS\ <word>` destination. (5) git_commands.py: `$(which git) push --force origin main`, `` `which git` push ... ``, `` git `echo push` --force ``, `{git,push,--force,origin,main}` must be judged (or fail closed as computed); `$(which git) commit -m…
- **T2:** (1) release_source_authority.validate: a successful `CI required` check run whose workflow run was a pull_request event on the same head_sha must be rejected (no event-dimension fixture exists in… (2) classify_changes.classify: `config/public-product-facts.json` (and every repository path website/scripts/site-contract.mjs reads) routes the website lane. (3) check_project_inputs.sh / model_catalog_contract: a catalog with activationState `staged` must fail the contract gate (currently only validate_catalog(require_complete=True) is unit-tested, never the gate wiring). (4) release.yml archive-ios credential hygiene: no third-party `uses:` step may follow a step that materializes a secret on disk before that secret's cleanup step (the existing hygiene test covers the macOS package ordering… (5) verify_release_bundle.sh launch smoke: assert the temporary fixture directory is populated by the launched app, proving the environment override reached the process.
- **T3:** (1) scripts/check_ios_catalog.sh: no test runs the script (bundle:// and --url paths); a deterministic test should assert the temp file is removed under a non-/tmp TMPDIR and that the bundled catalog survives a run from a… (2) scripts/regenerate_project.sh: entitlements backup/restore round-trip (xcodegen overwrite, failure mid-generation) is untested. (3) scripts/lib/build_cache.sh xcb_run: no test asserts the caller's shell options (pipefail) are unchanged after the xcbeautify branch. (4) scripts/check_project_inputs.sh: argument parsing (`--python` without a value, unknown lane) has no test asserting exit 2 with a usage line. (5) acquire_native_lock: a lock whose parent exists but is not writable must fail fast with 'cannot create the native lock' (the current test covers only a parent that is a file)
- **T4:** (1) classify_changes.classify: a path under Packages/VocelloQwen3Core/Tests/ routes to the swift lane (currently routes nowhere; no test covers Packages test sources). (2) classify_changes.RESEARCH_PREFIXES: every prefix matches at least one existing scripts/ file, and test_bench_command_contract.py is not research-marked. (3) development_workflow.check_plan: a Sources/Resources catalog or .xcstrings change yields at least the contract gate plus a Python selection (or an explicit note), consistent with CI's python=true for the same path. (4) qc.runners engines: constructing ZipaEngine/Wav2Vec2Engine/WhisperEngine/Qwen3AsrEngine with a missing model directory raises a specific exception type (currently unasserted). (5) classify_changes.classify: `.gitignore` enables the python lane (currently no lane)
- **T5:** (1) scripts/lib/build_artifact_retention.analyze_ui_artifacts: a run whose lane is accepted by ui_test.sh but absent from childRetention.uiResults.lanes must not be classified legacy-or-malformed-metadata (and… (2) scripts/ios_control_audit.validate_contract: structural validation of config/ios-control-audit.json against config/ios-control-audit-schema-v1.json (currently only the schemaVersion const is checked). (3) scripts/runtime_security_contract.validate_concurrency_contract: a multi-line `final class X:\n @unchecked Sendable` declaration must be counted and reported as unregistered. (4) scripts/runtime_security_contract.internal_diagnostics_capability_errors: a script outside enabledBuildRoutes that sets -DVOCELLO_INTERNAL_DIAGNOSTICS must fail the contract. (5) scripts/roadmap.validate: a blockedBy cycle reachable only through a non-first blocker must be reported; render must not print archived ids as live blockers.
- **T6:** (1) refresh_derived_artifacts / docs link hygiene: no deterministic check that relative markdown links in active docs/ and pointer strings in config `authority` fields resolve to tracked files (would have caught T6-02);…
- **T7:** (1) website/scripts/site-contract.mjs validateText: every literal `Vocello \d+.\d+.\d+` / `\d+.\d+.\d+ download` in website/src must equal a version from config/public-product-facts.json (stable, fallback or candidate). (2) website/scripts/render-waveforms.mjs or site-contract: each SAMPLES[].duration equals the WAV data-chunk length rounded to m:ss. (3) website/scripts/prerender.mjs: a body containing `$&`, `$`` and `$$` is injected verbatim into dist/index.html (function replacer). (4) website/scripts/site-contract.mjs: extend the em-dash / target=_blank / img-alt walk to website/public/**/*.html so the static privacy and support pages are under the same copy contract as src/. (5) Listen.togglePlay: switching to a second sample while the first is still loading must leave the second row marked playing (no browser test clicks a play button).

## 8. Refuted

Reported by an auditor and disproved by a refuter. Listed so they are not raised again.

- **A15-06** `Packages/VocelloQwen3Core/Package.swift:66`: The owned engine package's deterministic suite (Qwen3RuntimeTests) is built and run in SwiftPM's debug configuration, and Package.swift carries a debug-only unsafe flag, while the stated boundary is… Disproved by: scripts/repo_invariants.sh:49: "# Release-only configuration: no generic DEBUG branch in shippable sources." and .claude/rules/release.md:59: "- **Release-only.** One shippable `Release` configuration; the app and development CLI compile `-Onone`,"
- **A7-01** `Sources/iOS/Studio/IOSStudioInlinePlayerCard.swift:633`: Once a card controller has mirrored a live preview, `isLiveMirroring` is never reset, so `isAdopting` stays true for the controller's lifetime and every Play/Pause/scrub is forwarded to the shared… Disproved by: if audioPlayer.isLiveStream, audioPlayer.activeGeneratePreviewVisibilityState == .ready, let live = coordinator.liveItem { return .live(live) } return .generating
- **A7-05** `Sources/SharedSupport/ViewModels/AudioPlayerViewModel.swift:1075`: The chunk-arrival sites configure the live graph only when it is unconfigured, so a pre-warmed 24 kHz Int16 graph is never reconfigured when a chunk arrives in another format, although the pre-warm… Disproved by: Sources/SharedSupport/ViewModels/AudioPlayerViewModel.swift:871 `if liveSessionID != sessionID {` -> :920 `teardownLivePlayback(clearSession: true)` -> :1308 `livePlayback.discardGraph()`
- **A8-03** `Sources/iOS/Sheets/IOSPlayerSheet.swift:424`: A saved voice with no enrollmentMetadata or no generatedSourceMode exports as .originalReference (free) instead of .unknown (gated); today only pre-provenance designed voices (Design save path… Disproved by: public static let currentSchemaVersion = 1
- **E1-01** `Sources/QwenVoiceCore/GenerationOutputAdapter.swift:1966`: The last cancellation checkpoint after the model terminal is postStreamTerminalError at line 1966. Disproved by: Sources/QwenVoiceCore/GenerationOutputAdapter.swift:1378: `try Task.checkCancellation()` (inside `func publish() throws`, immediately before `try AtomicFilePublisher.publishAtomically(`)
- **E7-06** `Packages/VocelloQwen3Core/Tests/Qwen3RuntimeTests/ClassifiedGenerationSessionTests.swift:253`: The test claims the audio channel simply ends after a model terminal with no consumer activity. Disproved by: Packages/VocelloQwen3Core/Tests/Qwen3RuntimeTests/VocelloQwen3FacadeTests.swift:492 `let end = try await iterator.next()`, :499 `XCTAssertNil(end)`, :500 `XCTAssertEqual(terminal.outcome, .completed(.endOfSequence))` (testEngineDirectProducerBackpressuresUntilMandatoryConsumerDrains).
- **T1-14** `scripts/hooks/agent_hook_input.py:92`: The git policy check returns no violation when the parser raises, and both Bash hooks allow the call when the payload is not valid JSON. The parser case is currently masked because the commit lint… Disproved by: \|\| block "cannot parse the git command." "Run a plain git commit or push from the checkout."
- **T2-11** `scripts/check_project_inputs.sh:61`: No gate, workflow or script runs `model_catalog_contract.py validate --require-complete`; the contract gate runs plain `validate`, which passes a `staged` catalog. Disproved by: self.assertTrue(result["complete"])
- **T2-58** `scripts/verify_release_bundle.sh:158`: The 'isolated native mode' launch smoke sets HOME, QWENVOICE_DEBUG=1 and QWENVOICE_APP_SUPPORT_DIR only on the `/usr/bin/open -n` process; LaunchServices does not forward the caller's environment to… Disproved by: open(1) man page on this host (Darwin 27), DESCRIPTION: `Opened applications inherit environment variables just as if you had launched the application directly through its full path.

## 9. Fix status

**Fixed on `main` (item DA-01), each with tests and a green `CI required`:**

| Commit | Findings |
| --- | --- |
| `64ad6677` | A2-01 (History audio rebased when the container moved), A1-01 and A14-52 (a Stop is refused once the take is being saved), A14-02 (a failed Mac engine start shows the launch diagnostics, and Retry works) |
| `5b3ebba2` | E5-01 (a full-size bad partial restarts clean), E5-03 (the digest check no longer reads as verified without a digest), A5-02 (an incomplete install is removable on iPhone), E6-01, A6-01, A14-07 |
| `09f3ebd4` | T1-01, T1-02, T1-03, T1-05, T1-06, T1-07, T1-08, T1-09, T1-10, T1-12, T1-13, T1-55 (commit lint and command guards), T4-51 and T2-05 (CI routing) |

Each Swift batch went through the project's Swift review and the guard batch through an adversarial review; both found real problems in the first version of the fixes (a History rebase that could rewrite rows of an unmounted Mac output folder, an integrity change that hid a wrong-size file, a commit lint that a multi-line message could still bypass), and the fixes above include their corrections.

**Deliberately not fixed in the first pass.** A5-01, E1-02 and A8-01 waited for shared code, a model run or a test seam; A5-01 and A8-01 were fixed in the second pass below, and E1-02 is still DA-06.

**Second pass (same day, items DA-02, DA-03 and DA-08 to DA-12).** Five agents worked in isolated worktrees; every branch was integrated on `main`, built and tested there, and reviewed (Swift review on every Swift change, an adversarial review of the release path). The reviews found real problems in the first versions (a warm retry that could reload weights right after a memory-relief unload, a promotion attestation check that any `release.yml` run would pass, an English failure inside a localized alert, a banner that rebuilt and re-announced at every generation start), and the commits below include their corrections.

| Commit | Findings |
| --- | --- |
| `04bec09a` | T3-01 (the build lock fails fast under an unwritable folder), T5-01 (archived done items need evidence) |
| `2b7c49ba`, `dde11229`, `21ea84ab`, `6306e841` | A8-01 (a deleted voice's clone cache goes with it), A3-01, A3-02 (staged copies), A4-01, A4-02 (folder copies held for access, Restore cancellation) |
| `89896465`, `6306e841` | E7-01, E7-02, E7-03, E7-05 (tests drive the shipped take choreography and cancellation wiring); E7-04 declined with its reason |
| `1662434c`, `e62747f0`, `2b2b7bf4`, `53e77deb`, `201194a6` | A9-01 to A9-04, A2-03, A12-01 to A12-11, A12-51, A13-01 to A13-05, A13-52 (localization, Dynamic Type, hit regions, VoiceOver, one view tree per gated surface) |
| `8ad9723c`, `86fd0afe` | A5-01, A5-03, A5-04, A5-05 (iPhone model removal coordinated with the engine), A2-02, A2-04 (damaged History records can be set aside; a single delete is journaled) |
| `8e8d5556`, `105bdac3`, `5186f914`, `303ad901` | A10-01, A10-02, A10-04, A10-05, A10-06, A14-01, A14-03, A14-04, A14-05, A14-06, A14-08, A14-53, A14-55, A8-02 (Studio state with its take, one mode-switch rule, warm retries that never undo an unload) |
| `e45d3ad2` | T2-01 to T2-04, T2-06 to T2-10, T5-02 (signing jobs and promotion bound to the authorized commit and tag; attestations, exact assets, reviewer environment; promotion scope) |

Still open from these items: A10-04 needs one run of the Mac app to settle; the A12 and A13 layouts were read from code and need a device check, A13-06 a contrast measurement; the release changes are proven by the rehearsal and first meet `release.yml` and `promote-release.yml` end to end at the next release. Smaller follow-ups the reviews found are DA-13.

**Roadmap.** Everything else is an item of plan `project-audit-2026-10`:

| Item | Scope | Findings | Status |
| --- | --- | --- | --- |
| DA-02 | Studio state and window ownership | A10-01, A10-02, A10-04, A10-05, A10-06, A14-01, A14-03, A14-04, A14-05, A14-06, A14-08, A14-53 | fixed in code; one Mac app run |
| DA-03 | Accessibility, localization and glass gating | A12-*, A13-*, A9-*, A2-03 | fixed in code; device check, A13-06 |
| DA-04 | Engine edge inputs | E4-01 (needs one model run), E4-02, E4-03, E4-04 | open |
| DA-05 | macOS memory relief and the process-global caches | E2-01 (maintainer decision), E2-02 | open |
| DA-06 | Engine, delivery and telemetry hygiene | E3-*, E5-02, E5-04, E5-05, A16-01, A16-02 | open |
| DA-07 | Playback and recording | A7-02, A7-03, A7-05 | open |
| DA-08 | History and model-management dead ends | A2-02, A2-04, A3-01, A3-02, A5-03, A5-05 | done |
| DA-09 | Test quality and coverage | E7-*, the test gaps of section 7 (PA-19 is related) | done |
| DA-10 | Commerce and provenance | A4-01, A8-02 | done |
| DA-11 | Release and promotion hardening | T2-01, T2-02, T2-03, T2-04, T2-08, T2-09, T2-10, T5-02 | done |
| DA-12 | Guard, tooling, docs and website hygiene | the remaining T1, T3, T4, T5, T6, T7 and A15 findings | T3-01, T5-01 done; rest open |
| DA-13 | Follow-ups from the second pass | the reviews' smaller findings | open |

**Never without the maintainer's explicit request:** device, UI, model or benchmark lanes, releases and promotion. Findings that need one of those to settle say so in their action.

