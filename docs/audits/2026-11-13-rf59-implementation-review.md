---
status: active
owner: backend-mlx
reviewed: 2026-11-13
summary: Review of the RF-59 implementation (one hybrid model per mode, retired-folder reclamation, the model update for 3.0 users, the research folder) - what holds, two defects found by reading the code, the verification still owed, and ordered follow-up instructions.
sourceOfTruth:
  - Sources/QwenVoiceCore/ModelUpdateLedger.swift
  - Sources/QwenVoiceCore/SharedModelComponentStore.swift
  - Sources/ViewModels/ModelManagerViewModel.swift
  - Sources/iOS/IOSModelInstallerViewModel.swift
  - Sources/iOS/IOSModelDownloadCoordinator.swift
  - Sources/iOSSupport/Services/IOSModelUpdateAutoStartPolicy.swift
  - docs/reference/hybrid-model.md
  - config/roadmap.json
---

# RF-59 implementation review (November 13)

Scope: commits `41693f7f` to `80e0c2e9` on `main` (the contract swap, the reclamation, the model
update for 3.0 users, the research folder). Method: reading the code paths a release depends on and
the session's evidence; nothing was built, run or measured for this review. It opens no plan: every
follow-up below belongs to RF-59, and each defect is classified under the focus lock.

## Verdict

The design is sound and the Mac side is well evidenced. The ledger is recorded before anything is
deleted and fails closed; one entry point serves every host; the update was proven end to end on a
clone of real 3.0 Mac data; the new UI scenario passes. It is **not ready for an iPhone candidate**:
the iPhone flow has never run on a device, two code defects below change what a user sees after a
failed download, and none of the 78 unpushed commits has been compiled by CI's pinned Xcode.

## Findings

Severity: **B** blocks an iPhone candidate or a Mac release; **S** should be fixed before either;
**N** note.

| # | Sev | Finding | Evidence |
|---|---|---|---|
| 1 | B | **CI has never compiled these 78 commits.** Local Xcode is 27.2; CI pins 26.6, which disagrees on `@safe` markers, region isolation and "never executed" warnings. The new code adds flock, `rename`, detached `@concurrent` closures and a continuation. | `git log f4edb60a..HEAD`; native-engineering.md, Common mistakes |
| 2 | B | **The iPhone flow is unverified on a device**: the consent alert, the queue, the reclaim after each install, "remove old models first", and the hybrid's memory against the 4,500 / 5,200 MiB bands (the Mac measured +168 MB peak; the iPhone 15 Pro has the least headroom). | No device run this session; RF-59 gate |
| 3 | S | **iPhone: a failed update download restarts at every launch.** The launch decision reads `failed` from the view model's `states`, but `restoreInFlightDownloadsIfNeeded` publishes no snapshot for a kept-failed request (`.keepFailed` only breaks), so at the one call site `failed` is always false. A consented update that fails deterministically (digest mismatch, no space) re-queues silently on each launch, against NET-1, the docs and the policy tests' claim. | `IOSModelDownloadCoordinator.restoreInFlightDownloadsIfNeeded`; `IOSModelInstallerViewModel.startModelUpdateIfNeeded` |
| 4 | S | **Mac: no failure memory and no free-space check.** `startModelUpdateIfNeeded` filters only paused and active modes; a failure lives in `lastFailureMessages` (memory only). A 3.0 user with both packages per mode holds about 14 GB of old models that stay until the first hybrid verifies; on a nearly full disk the update fails and retries on every launch, and unlike the iPhone there is no "remove old models first". | `ModelManagerViewModel.startModelUpdateIfNeeded`; no `volumeAvailableCapacity` on the Mac download path |
| 5 | S | **iPhone: a file lock in the App Group container with no background assertion.** The ledger's flock and fsync run on detached utility tasks; iOS terminates an app suspended while holding a lock in a shared container (0xdead10cc). The window is short, but a crash is a release-blocker class. The first review raised it (N4); it was not addressed. | `ModelUpdateLedger.withLock`; `AppPaths` models folder |
| 6 | S | **Active docs still describe two packages**, against the contract (authority rule): ios-app-guide.md 446 and 618, ios-engine-optimization.md 54-56, macos-app-guide.md 59, 300 and 320, mlx-guide.md 51, privacy-storage.md 44, macos-release-qa.md 279, ARCHITECTURE.md 238. The README, website and public facts wait for the release by decision; these do not. | grep for "Speed (4-bit)", "Quality (8-bit)" |
| 7 | S | **Settings contradicts the banner during the update.** While the banner says the models need an update, the summary row reads "0 of 3 recommended models installed" with "Download recommended". For "seamless", the summary should speak of the update while a plan exists. | Lane screenshot `002-mac-model-update-required.png` |
| 8 | N | **The done note, Not Now and Later were never exercised.** No test taps the Mac's Not Now or the iPhone's Later; the "Voice models updated, freed X" banner was not observed in any run (computer use was declined; test15 stops before a model installs). The banner and progress arithmetic lives in app-only view models with no unit test. | test15; review 2, test adequacy |
| 9 | N | **The real upgrade path is untested**: the end-to-end run used a debug-gated launch on a data clone, not 3.0.0 updated by Sparkle with the release defaults domain. The maintainer's Mac can no longer dogfood it by a normal launch, since the 3.0 folders moved. Downgrading to 3.0 after the update (how 3.0 treats the hybrid folders and the ledger) is unverified. | Session evidence |
| 10 | N | **The debug root now holds no model.** Every Mac model lane (smoke, benchmark, gate bench, language bench, QC takes) fails its preflight until the hybrids are installed there (about 4.65 GB with the tokenizer reused; needs the maintainer's word). `run --stock` and `capture --stock` have not run from the research folder. | `80e0c2e9` |
| 11 | N | **Translations are unreviewed**: 28 keys in ten languages, written by the model, and the localization lane has not run on the banner (long German and Russian titles at the minimum window width). | `Localizable.xcstrings` |
| 12 | N | **Orphaned clone caches**: per-voice `pro_clone_quality` prompt folders stay after the update; the approved plan said the reclaim removes them. Small. | End-to-end run |
| 13 | N | **Mac Quality users lose quality**, by decision: clone similarity -0.026 and about twice Quality's long-form error rate. The release notes must say so. | hybrid-model.md §4 |

Checked and found sound: the ledger's write order, durability and newer-schema refusal; the single
reclaim entry and its tests; hard links between the research folders and the app's component store
(the tokenizer blob stays pinned, so the first hybrid install still reuses it); consent keyed by
artifact; `QWENVOICE_MODEL_UPDATE_AUTOSTART` read only through the debug gate; no hardcoded 4-bit
folder names left in the lane tooling.

## Follow-up instructions (in order; all RF-59)

1. **Finding 3.** Give the coordinator a read of its ledger's request statuses and build the launch
   candidates' `failed` from it (not from `states`). Extract the candidate mapping and the consent
   subset into a value type under `Sources/iOSSupport/Services`, listed in both test bundles, and
   test: a kept-failed request does not restart; Retry does.
2. **Finding 4.** Record a failed update in the ledger entry (reason class and attempt count, no
   paths), auto-start only modes without one, and let Update or Retry clear it. Before the Mac
   auto-start, check free space against the delivery plan's bytes with the iPhone's rule
   (`minimumFreeBytes`); when short, the banner offers "remove old models first" through
   `removeRetiredFoldersBeforeUpdate` and its pins. Unit-test the decision as a value type shared
   with step 1 where possible.
3. **Finding 5.** Hold a background-task assertion (or `performExpiringActivity`) around every
   iPhone ledger reconcile and reclaim; confirm what the publication lock does today and match it.
4. **Finding 7 and 8.** While a plan exists, the Settings summary reads as an update. Extract the
   Mac banner state and progress into a tested value type; extend test15 to tap Not Now.
5. **Finding 6 and 12.** Correct the listed prose in one docs commit; remove the orphaned Quality
   clone caches in the shared reclaim, with a test.
6. Run the routed check, `vocello-swift-review`, then `ui_test.sh macos smoke --scenario
   model-update` and `macos localization`.

## Decisions for the maintainer

- **Push `main`** so CI compiles the 78 commits (finding 1). Recommended now, before steps 1 to 5
  add more; a CI failure on the pinned compiler is cheaper to fix early.
- **Authorize `scripts/macos_test.sh models ensure`** (about 4.65 GB) so the Mac lanes, the speed
  lane and the gate-bench reseed can run (finding 10).
- **Announce a phone window** for finding 2: 3.0 from TestFlight, this build over it,
  `smoke --scenario update-models`, then the memory and speed lanes for the hybrid.
- Whether the Mac should also ask before a multi-gigabyte download on a capped home connection
  that macOS does not flag as expensive (today it starts and shows the banner).
