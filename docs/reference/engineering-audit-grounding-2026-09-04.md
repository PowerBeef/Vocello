---
status: active
owner: backend-and-platform
reviewed: 2026-09-04
summary: Current-source disposition of the September 4 external engineering audit, with bounded pre-freeze corrections under the existing 3.0 release programme.
sourceOfTruth:
  - config/roadmap.json
  - Sources/QwenVoiceCore/GenerationOutputAdapter.swift
  - Sources/QwenVoiceCore/MLXTTSEngine.swift
  - Sources/QwenVoiceCore/PreparedVoiceRepository.swift
  - Sources/ViewModels/GenerationLifecycleExecutor.swift
  - Sources/VocelloCLI/VocelloMain.swift
  - Sources/VocelloCLI/BatchCommand.swift
  - Sources/SharedSupport/Services/GenerationOutputVerifier.swift
  - Sources/SharedSupport/Database/LongFormHistoryAcceptance.swift
---
# September 4 engineering audit — source grounding

This is the disposition at the `75ecb740` review baseline. Subsequent source corrections and
verification are recorded in the [current checkpoint](../development-progress.md#resume-here-2026-09-04)
and authoritative roadmap; the baseline findings below are not claims that those paths remain unfixed.

## Decision and scope

The external report is substantially accurate and identifies two previously untracked **P1
data-preservation defects**. Address them before qualifying affected release surfaces. Its
asynchronous and cross-process schedules are important test hypotheses, not witnessed user
incidents. Neither requires an engine rewrite or a new testing programme.

The supplied HTML reviews `616fdfe21276bf24d00a1acaa750cd4061435d03`. This review checks
clean `main` at `75ecb740d76609d279da14140d5e8d9127dec2f9`, one commit later. Attachment SHA-256:
`66df02cedcb7390545ef7f6ef2c2d2059d60638c065906fb7358e69f46c19c58`.
The original attachment stays outside the repository. Its proposed tests and simplified Python
counterexamples are not native Vocello test results; the separate supplemental files were not
provided with this attachment and were not executed here.

This review traces source, callers, existing tests, configuration, and exact-commit CI. It does
not run speech generation, native UI, device operations, destructive filesystem fault injection,
signing, or App Store Connect operations. External legal/privacy decisions and Apple's account
requirements were not independently re-audited. No production source, model, sampling, prompt,
QC policy, or original campaign evidence changes in this review.

`config/roadmap.json` remains the only status authority. The primary plan remains
`release-first-3-0-2026-09`; the new work is a bounded amendment before RF-09 freeze, not a
replacement roadmap. The earlier RF-03/04/05 implementation milestones retain their historical
meaning; they do not establish closure of newly identified failure schedules.

## What changed after the audited revision

- Source identity is now **3.0.0/build 24**. Public stable downloads remain 2.4.0. The report's
  instruction to replace 2.4.0/build 23 is already implemented locally, not in the live App Store
  version record.
- `scripts/cli_package.py` now provides serial opt-in generation qualification, atomic partial
  reports, retained WAVs, real optional Clone transcripts, and bounded subprocess termination.
  Its 25 fixture tests are recorded in the preceding checkpoint. These changes do **not** fix
  `VocelloMain` signal handling or `BatchCommand` partial-output reporting.
- The qualifier records **requested** seed/streaming, not falsely observed receipts. It can
  remove a cancelled test output itself; that is not proof that the CLI cleaned up gracefully.
- Exact `75ecb740` [CI completed successfully](https://github.com/PowerBeef/Vocello/actions/runs/33915751142)
  at 20:49:09 UTC. [Security remained pending](https://github.com/PowerBeef/Vocello/actions/runs/33915751329)
  when queried during this review. Neither status is transferable to a later commit or signed
  candidate. The earlier local checkpoint recorded 1,481 Python tests, macOS suites/builds,
  generic iOS compilation, and website verification; these are historical results, not new runs.

## Boundary map

- macOS app/XPC and CLI select the same production Application Support root; CLI `--data-dir`
  can explicitly isolate it. iOS uses its App Group-backed support root.
- Permanent voices, outputs, History, and outbox are distinct from candidate, transaction,
  cache, model, and diagnostic trees. The iOS protection contract includes user voices/audio/
  History in backup and excludes regenerable/transient trees. Local inference is not a promise
  that operating-system backups cannot contain user audio.
- `PreparedVoiceRepository` serializes operations within its actor instance. It has no shared
  process-exclusion operation around candidate mutation or startup reconciliation in the
  inspected path. `SharedModelComponentStore` separately has an OS-backed publication lock.
- macOS coordinators and `GenerationLifecycleExecutor` are MainActor-isolated, but their
  stored tasks suspend through generation and persistence. Actor isolation does not make an
  old completion belong to a newer request. iOS already uses attempt-scoped terminal authority.
- History uses its GRDB writer for journal reconciliation and database mutation. Corrupt
  recovery state intentionally stops unrelated History operations rather than risking deletes.

The data/concurrency skills directed ownership and secondary-failure checks. Their broad pattern
scans were used for navigation, not as defect counts or a whole-project readiness score.

## Disposition of every finding

Source line numbers below refer to `75ecb740`; links resolve to the maintained source files.

| External ID | Disposition at review baseline | Evidence and technical owner |
| --- | --- | --- |
| V26-01 | **Confirmed, P1, high confidence.** Unsuccessful output cleanup can delete a destination belonging to an earlier take. | [Adapter](../../Sources/QwenVoiceCore/GenerationOutputAdapter.swift), lines 1401–1449 and 1759/1807; [engine](../../Sources/QwenVoiceCore/MLXTTSEngine.swift), lines 1207/1246/1280. New **F-18**, backend-and-platform. |
| V26-02 | **Confirmed, P1, high confidence.** Replacement/delete catches swallow restore failure and then remove the backup directory; post-publication housekeeping shares the rollback catch. | [PreparedVoiceRepository](../../Sources/QwenVoiceCore/PreparedVoiceRepository.swift), lines 291–338, 381–387, 437–447, 459–521. Reopen **F-01**, preserving prior success evidence. |
| V26-03 | **P1-impact risk, not runtime-reproduced.** Old macOS callbacks/task clearing have no attempt identity. | [Executor](../../Sources/ViewModels/GenerationLifecycleExecutor.swift), lines 44–104/117–132; [Design coordinator](../../Sources/ViewModels/VoiceDesignCoordinator.swift), lines 133–141; same executor used by Custom and Clone. New **F-19**, macos; cross-reference F-08/F-15. |
| V26-04 | **Confirmed behavior, P2, high confidence.** Ctrl-C calls process exit, not the engine cancellation barrier. | [VocelloMain](../../Sources/VocelloCLI/VocelloMain.swift), lines 9–12. New **F-20**, under F-17/RF-08. Host qualifier improvements do not change it. |
| V26-05 | **Confirmed contract gap, P2, high confidence.** A later batch error prevents reporting the array containing earlier accepted outputs. | [BatchCommand](../../Sources/VocelloCLI/BatchCommand.swift), request loop and post-`generateBatch` emission; [engine](../../Sources/QwenVoiceCore/MLXTTSEngine.swift), lines 1100–1116. New **F-21**, under F-17. |
| V26-06 | **Confirmed assurance gap, P2, high confidence.** Live duration acquisition uses `try?`; nil takes the compatibility path and skips the edge guard. | [Verifier](../../Sources/SharedSupport/Services/GenerationOutputVerifier.swift), lines 100–185. Extend **VLR-07/RF-06**; missing duration is not proof that an unreadable WAV has actually passed Speech. |
| V26-07 | **Confirmed limitation, P2 evidence semantics.** Endpoints establish edge coverage, not coverage of interior speech. | [Transcriber](../../Sources/SharedSupport/Services/VoiceClipTranscriber.swift), lines 540–544/565–599. Extend **VLR-07**. WER/CER may still detect an omission; this is not a demonstrated complete-verifier false PASS. |
| V26-08 | **Confirmed fail-closed behavior, P2 recovery gap.** A corrupt journal blocks ordinary History access; Retry does not itself repair the journal. | [Acceptance store](../../Sources/SharedSupport/Database/LongFormHistoryAcceptance.swift), lines 160–200; both platform DatabaseService wrappers reconcile before CRUD. Extend **F-16**, cross-reference F-06. Do not delete the journal to restore a green result. |
| V26-09 | **P1-impact qualification gap, narrowed.** Saved Voice reconciliation can encounter another process's live candidate/transaction. Model publication already has a shared lock. | [CLI bootstrap](../../Sources/VocelloCLI/CLIRuntime.swift), lines 23–39; [repository](../../Sources/QwenVoiceCore/PreparedVoiceRepository.swift), lines 100–121; [model lock](../../Sources/QwenVoiceCore/SharedModelComponentStore.swift), lines 1072–1090. New **F-22**; no claim that all shared-store paths lack locking or that corruption was observed. |
| V26-10 | **Confirmed retention; P2 lifecycle qualification gap.** Prior joined audio survives row replacement; unaccepted successful segments remain available for session continuation. | [Acceptance store](../../Sources/SharedSupport/Database/LongFormHistoryAcceptance.swift), lines 140–156; [deletion](../../Sources/QwenVoiceCore/HistoryDeletionEngine.swift), lines 80–99, enumerates persisted rows, not every retained file. Extend **F-16**; no invented leak-rate or blanket cleanup authorization. |
| V26-11 | **Confirmed documentation mismatch, P2; source copy corrected in this review.** Reviewer notes understated disk admission. | [Install caller](../../Sources/iOS/IOSModelDownloadCoordinator.swift), lines 160–176, passes full catalog total to [policy](../../Sources/iOSSupport/Services/IOSModelDeliverySupport.swift), lines 301–315. **ASR-05/ASR-09** still require actual candidate/account proof. |
| V26-12 | **Confirmed documentation drift, P3; corrected in this review.** `swift-transformers` is 1.3.3, not 1.1.9. | [Package manifest](../../Packages/VocelloQwen3Core/Package.swift), lines 32–38, and [lockfile](../../QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved), lines 140–145. RF-01 currency correction only; no dependency change. |

## Important qualifications and closure evidence

### Accepted output and Saved Voice bytes come first

`--out` accepts a caller-selected path without establishing exclusive ownership. The WAV writer
uses staging, but outer adapter and engine cleanup still removes the requested final path. The
pre-existing-file precondition is what makes V26-01 destructive; ordinary unique app filenames
do not prove it safe. Validate startup/QC/publish failure, cancellation, allocation recovery,
input/output aliasing, and two competing writers with immutable sentinel bytes. Define refusal
or explicit atomic replacement at the actual publication boundary, not only a race-prone
`fileExists` precheck.

For F-01, test failure of restoration itself and failure after candidate removal. The existing
[repository tests](../../Tests/VocelloCoreTests/PreparedVoiceRepositoryTests.swift) cover happy
publication, deletion, and selected interruption states, but not those secondary faults. A fresh
repository must recover either complete old content or positively committed new content after
the injected fault is removed. Keep bytes and metadata, not merely a nonempty directory. Same-name
replacement needs a content-aware commit witness; pathname existence alone can be ambiguous.

### Prove lifecycle schedules at the production boundary

Hold macOS attempt A after synthesis inside persistence, cancel it, start B, then resume A.
Assert that B retains its task, cancellation capability, live estimate, player, and error state.
Repeat with a late error and delayed Clone preparation. The [Design tests](../../Tests/VocelloCoreTests/VoiceDesignCoordinatorTests.swift)
execute the production coordinator but substitute its lifecycle executor; they correctly prove
request preservation, not V26-03. Preserve completed request-capture work.

For F-22, use two real processes against a disposable root. Pause A during candidate creation,
replacement, and deletion; B's initialize/list/mutate must not treat live work as abandoned.
Reconciliation must participate in the same exclusion as mutation. Audit the existing model lock
at its call sites rather than replacing it. Contention may be explicitly refused; do not silently
split the user's voice library or copy their installed models. This proof needs no phone or model.

### CLI outcome and evaluator corrections stay small

F-20 must distinguish graceful cancellation from forced termination and await the existing owned
operation boundary. Test first and second signals, model load, Clone preparation, streaming,
finalization, and batch boundaries. Exit 130 alone is insufficient. The current qualifier's
`partialOutputRemoved` is host cleanup, not evidence of CLI cleanup.

F-21 keeps stop-on-first-error but reports stable indices/identities for completed, failed,
cancelled, and unattempted inputs, with a nonzero terminal exit. Preserve all-success compatibility
or version the migration. The batch route does not advertise `--language` and forces non-streaming;
document or reject unsupported shortcut options rather than silently implying single-take parity.
No automatic retry or resumable batch framework is needed.

For VLR-07, distinguish strict new live evidence from legacy decoding/offline evaluation. Missing,
invalid, or unreadable duration must yield a typed nonqualifying result even with otherwise valid
recognition. Keep the existing edge rule, but name its claim accurately and add an interior-omission
fixture. Do not infer total speech coverage from first/last timestamps. Preserve recognizer
disagreement and historical rejects; a favorable diagnostic ASR score cannot authorize promotion.

### Long-form recovery is not a reason to discard accepted work

The corrupt-journal test already expects an error while retaining journal/audio. The product gap
is a usable, non-destructive recovery/export path and access policy for healthy unrelated History.
Test actual DatabaseService/UI error propagation, not only the pure store. Callers already retain
candidate files on `recoveryRequired`; this review does not claim the new journal automatically
deletes accepted audio on that outcome.

Define ownership of superseded joined audio and abandoned successful segments, including outbox,
recovery, player, and export references. Current clear-all enumerates database paths, so it cannot
by itself account for an old joined path whose row was replaced. Verify abandon, new project,
relaunch, regeneration, single delete, and clear-all with disposable stores. Intentional retention
must be visible/bounded or recoverably discardable; no general garbage collector is requested.

### Reviewer copy and privacy precision

The install caller applies `max(totalBytes * 2, totalBytes + 256 MiB)` to each full catalog total,
not simply the remaining transfer bytes. Current Built-in admission is 3,417,167,378 bytes;
Clone is 3,465,201,538 bytes. The revised runbook recommends at least 4 GB free **before each
installation**, with the actual app error and changing storage availability authoritative. This
does not alter disk policy or guarantee a download in exactly that amount of space. Live reviewer
metadata was not edited.

The privacy/storage guide now expressly distinguishes local inference and app uploads from
operating-system backup eligibility. This is source alignment, not a qualified privacy-label or
content-rights decision; ASR-02/04/06 remain open as applicable.

## Finite execution amendment

1. **Protect bytes:** F-18 output ownership and reopened F-01 rollback/commit recovery.
2. **Prove ownership risks:** F-19 macOS delayed terminal and F-22 two-process Saved Voice tests;
   apply only the demonstrated narrow correction or explicit contention policy.
3. **Finish CLI behavior:** F-20 graceful interruption and F-21 partial batch outcomes, feeding
   F-17/RF-08 and eventual copied signed-package qualification under RF-10.
4. **Close bounded recovery/evidence gaps:** F-16 corrupt-journal recovery and retained-file
   lifecycle; VLR-07 strict live duration and accurate edge semantics under RF-06. No new evaluator
   research or prompt/model changes.
5. **Verify once coherently, then freeze:** focused behavior tests per patch; RF-09 full checkpoint
   and exact-SHA CI/Security after the corrective set. The small physical pilot, existing 201-take
   campaign, signed artifacts, and qualified external decisions remain the adopted later gates.

No new broad harness, release programme, model acquisition, device work, publication, or submission
was performed by this review. Confirmation of a report is not implementation of its product fixes.
