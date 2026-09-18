---
status: current
owner: backend-and-platform
reviewed: 2026-09-17
summary: Findings of the specialist audit run over the macOS UI-fidelity range 3874b70d..e1755734 and the project around it, separating defects that range introduced from pre-existing conditions it surfaced.
sourceOfTruth:
  - config/roadmap.json
  - Sources/Views/Studio/MacStudioCanvas.swift
  - Sources/Views/Studio/MacChipRowBudget.swift
  - Tests/UIAutomationSupport/VocelloUIAutomationSupport.swift
  - scripts/repo_invariants.sh
---

# UI rework audit, 2026-09-17

The [September 18 independent review](project-review-2026-09-18.md) revalidates all twelve AUD items
against current code and supersedes their severity/causal interpretations below where noted. In
particular, do not implement the original unverified-transaction finish recommendation without the
new investigation gate. This report preserves the historical audit; the roadmap owns current status.

Seventeen commits landed a macOS UI-fidelity pass between `3874b70d` and `18bb3b81`. Each had a green
local check and most had a green lane chain and green CI. The maintainer asked for an exhaustive audit
anyway, on the grounds that green gates were not evidence the work was safe.

They were right, and the reason is structural rather than incidental.

## Why the gates could not have caught this

| Gap | Consequence |
|---|---|
| **No gate compiles the XCUITest bundles.** `repo_invariants.sh` check #2 forbids CI from naming them. | Most of the range's code landed in UI-test infrastructure, where nothing automated could see it. One commit hung the localization lane for 82 minutes and exhausted memory once before being reverted. |
| **No gate checks geometry.** | Every layout defect in this range — and in the plan before it — was found by eye or by an auditor, never by a test. |
| `config/ui-perf-thresholds.json` is `warnOnly`. | A performance regression would not have failed anything. |
| `ci-required` treats `skipped` as pass. | A lane misrouted by `classify_changes.py` produces a green aggregate with no work done. |
| iOS behaviour cannot be verified without a phone. | 96 iOS logic tests run host-side; the device-SDK build proves compilation only. The phone is parked under CONV-20. |

## Defects introduced by this range — six, all fixed

| # | Defect | Commit that caused it | Fix |
|---|---|---|---|
| 1 | Removing a `GeometryReader` reconnected a **window height-floor overrun**. Its comment named only one of its two jobs; the unwritten one was reporting a flexible minimum so the column's floors could not become the window's floor. Two auditors independently summed those floors: Voice Design needs ~633 pt and Voice Cloning ~603 against a declared 560 pt minimum, with a finished take on screen. | `2a68eb5c` | `e1755734` |
| 2 | **A chip could draw outside its row**, unclipped. The 132 pt floor was applied after the row budget was computed, so the width it added came out of the trailing chip — which then rendered at its own minimum anyway, because `VocelloSetupChipPill` pins `.frame(minWidth:)`. | `d9362cff` | `d7360dda` |
| 3 | `VocelloUIScroll.intoView`'s **fast-fail was dead** for a missing element: the stall counter sat behind `guard element.exists`, so the one case it exists to catch quickly always paid the full budget. On the smoke lane's critical path. | `a93186f3` | `e1755734` |
| 4 | **An 8 pt budget drift**: the library lists' row insets moved from `lg` to `xl` and `MacVoiceRow.rowChrome` kept subtracting `lg`, so `usesWideLayout` chose the wide arrangement 8 pt past its fallback point. | `ea54741c` | `d7360dda` |
| 5 | **A transcript newline reached the conditioning string.** Making the field multi-line meant Return inserted a newline, and the trim only touched the ends. | `683facf4` | `d7360dda` |
| 6 | **A History layout assertion hung the localization lane.** An unscoped `app.descendants(matching: .any)` over an unfiltered History, whose row identifier propagates to every child. The same commit removed the vacuous-pass guard. | `c4db5ad7`, `18bb3b81` | reverted in `c967f807` |

Also closed: the chip arithmetic now has its first unit coverage
(`Tests/VocelloCoreTests/MacChipFlowTests.swift`), holding the invariant that broke — a row never hands
out more width than it has — for ideals above, below and on the floor at every chips-per-row split.

## Cleared

Stated so they are not re-investigated. The retired TextKit measurement left no orphaned observer, closure
or retain cycle. The completed take's VoiceOver story is complete and the removal orphaned nothing. The
toolbar button's demotion to `.bordered` holds 8.1–11.4:1 contrast. The multiline transcript introduces no
accessibility issue. Project-wide: no unbounded memory growth, no data races, no unpaired prewarm slots,
no unregistered `@unchecked Sendable` or `nonisolated(unsafe)`, no credentials in source, no PII in
telemetry, no unlabelled interactive control, no partial model can activate as complete, and the StoreKit
boundary holds by grep.

## Pre-existing conditions this audit surfaced

Not caused by this range. Eight were closed in the remediation pass that
followed on 2026-09-17 (marked **closed**); the rest are tracked as
`audit-remediation-2026-09` in `config/roadmap.json`, which is where their
current status lives. Ranked by the severity they were given here.

| Severity | Finding | Where |
|---|---|---|
| CRITICAL | iOS dependency-bootstrap failure screen is a **true dead end** — no retry, no restart; a persistent cause reproduces every launch | `Sources/iOS/QVoiceiOSApp.swift:44-58` |
| CRITICAL | **Playback can go silent after a recording**: the shared player never sets the audio session category, and the recorder leaves it on `.record`, deactivated. `ClipReviewPlayer` already carries the fix for this exact contamination | `AudioPlayerViewModel.swift:992,1334`, `ReferenceClipRecorder.swift:145` |
| CRITICAL | All three Studio screens **start their own generation Task**, which `.claude/rules/native.md` forbids in as many words | `MacCustomVoiceScreen.swift:337` + 2 |
| CRITICAL | `onOpenURL` presents an import cover without checking the onboarding cover, so opening a file during first run races two `fullScreenCover`s and can drop the hand-off | `RootView.swift:117,138,325` |
| HIGH | Clone's `canGenerate` ignores `cloneContextStatus` and `ensureCloneReferencePrimed` failures are swallowed by `try?`, so a take can silently degrade to audio-only cloning | `IOSGenerationModeViews.swift:1404,1900` |
| HIGH | Six findings in History persistence: unindexed idempotency key, filesystem work inside the database queue, **synchronous delete on the main thread**, and a **silently swallowed delete failure** on iOS — *index and main-thread delete **closed**; the rest is AUD-05* |
| HIGH | Two independent `AVAudioPlayer` owners install no interruption or route-change observer | `IOSPlayerSheet.swift:769`, `IOSStudioInlinePlayerCard.swift:657` |
| HIGH → MEDIUM | Deprecated `AVAudioSession.InterruptionType` decoding in three files. The reported consequence does not occur: compiling the exact expression at deployment target 26.0 and 27.0 emits no warning, so nothing breaks under warnings-as-errors today — *AUD-12* |
| HIGH | iOS modal overlays do not hide the background from VoiceOver, so focus can reach controls behind a presented panel | `RootView.swift:250-315` |
| HIGH | Four close/back buttons at 40×40 against the app's own 44×44 standard — ***closed***, and the standard is now `Theme.HitTarget.minimum` |
| HIGH | `.background(.regularMaterial)` bypasses `GatedGlass` entirely — no Reduce Transparency check, no performance gate — ***closed*** |
| HIGH | macOS `deleteVoice` never clears the pending clone handoff, and the handoff applies with no existence check — ***closed*** on macOS, both halves |
| MEDIUM | `UIPerfFrameProbe` / `IOSUIPerfFrameProbe` never remove their observers and never nil their `static active` — ***closed*** on both platforms |
| MEDIUM | An `.unverified` StoreKit transaction is never finished, so it redelivers every launch and Restore cannot clear it | `IOSStoreKitClient.swift:56` |
| MEDIUM | Hardcoded English `"play"` / `"selected"` accessibility values on a French-shipping app — ***closed***: selection is the `.isSelected` trait, play/pause a localized action label |
| MEDIUM | `privacy_scan.py` cannot see runtime log interpolation, so the logging half of the privacy invariant is discipline, not a gate | `scripts/privacy_scan.py:23` |
| MEDIUM | `test01` depends on a clone-voice fixture nothing in the suite creates, contradicting its own "leaves no persisted state" header | `VocelloMacSmokeUITests.swift:97` |
| MEDIUM | On `highMemoryMac` there is no idle-unload and no pressure monitor, so the warm prefetch fires from tab navigation alone and nothing ever unloads it — the engine is kept hot by browsing rather than by intent | `NativeMemoryPolicyResolver.swift:62`, `MLXTTSEngine.swift:812` |
| MEDIUM | Repetition-penalty token dedup does an O(n) scan plus a full rebuild per decode step, while a `Set` for the identical membership check already exists in the same function | `Qwen3TTS.swift:4710` |

Also closed in the same pass: the `VocelloSectionHeading` uppercase transform (it baked the change into
the string the accessibility layer reads), and a `chunkCancellable` that was declared and cancelled and
never once assigned.

Fixed in passing because it was one line and provably wrong: `settingsWindowDefaultSize` asked for 720 pt
of content on a 720 pt screen, which no non-zero chrome allows, so the system had been silently clamping
it.

## Found while remediating, not by the audit

Three things only turned up because the remediation wrote tests that had to run.

| Finding | How it surfaced |
|---|---|
| **History's accessibility tree is unbounded.** It renders every generation the machine has ever produced, and each card's `children: .contain` multiplies that across descendants. A *typed*, bounded XCUITest query over it times out. | The re-landed History assertion could not resolve its own query until the list was filtered first. Tracked as AUD-05, where it is the concrete argument for bounding the fetch. |
| **The declared window minimum is not the enforced one.** `MacShellMetrics` says 560 pt tall; SwiftUI enforces whatever the content subtree demands, which is written down nowhere. | Tracked as UIF-07, with the audit's own 603–633 pt measurement as its input. |
| **The geometry assertion's height half does not bind on this machine.** The logical screen is 1280×720, so a window at any natural size has its bottom edge under the Dock and the resize affordance cannot be pressed. | The pin reports this on every run rather than implying it measured the minimum. Width does bind: 880 is reached. |

And two beliefs of mine about SwiftUI that were wrong, both caught by the
assertion's vacuous-pass guard rather than by review:
`.accessibilityElement(children: .contain)` does **not** hand the container's
identifier to a child that has none, and a child under `children: .ignore` is
not exposed as the element type its content suggests. The guard has now earned
its keep twice; it is the reason those are sentences here rather than two
silently green lane runs.

## Coverage of this audit

Twenty-one reviewers: seven Axiom specialists over the blast radius (SwiftUI layout, SwiftUI performance,
concurrency, memory, accessibility, testing, resize), thirteen over the rest of the project (security and
privacy, GRDB, database schema, networking, energy, StoreKit, audio capture, SwiftUI architecture,
navigation, UX flow, Liquid Glass, Swift performance, Codable), and the repository's own `swift-review`
against Vocello's domain rules.

Auditors were chosen against a domain map rather than run wholesale. **TextKit, Core Data, SwiftData, raw
SQLite, CloudKit, Keychain, camera, SpriteKit/SceneKit, custom Metal rendering and `BGTaskScheduler` are
absent from this codebase**, so those auditors would have returned nothing. TextKit is absent *because of*
this range — retiring the composer's height measurement removed the last `NSTextLayoutManager` in the tree.

The split is the result worth keeping: **every auditor that reached into the changed surface found a defect
of this range; every auditor that looked elsewhere found only pre-existing conditions.** The damage was
real and bounded to what was edited.

## What would have caught this earlier

1. A gate that **compiles the XCUITest bundles**. Nothing else in the repository protects the code that
   drives every acceptance lane.
2. A **geometry assertion at the scene minimum**. Both the chip overflow and the height-floor overrun are
   arithmetic, reachable without a screenshot.
3. Treating a **deleted comment as a deleted requirement**. The `GeometryReader` removal was safe against
   the reason its comment gave and unsafe against the reason it did not.
