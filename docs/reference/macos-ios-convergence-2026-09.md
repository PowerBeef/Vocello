---
status: active
owner: backend-and-platform
summary: The 2026-09-14 decision to make the iOS app the reference for both platforms — the macOS app hosts the engine in-process on the shared iOS store, then adopts the iOS UI adapted to macOS with its desktop features — with the step list, the accepted costs and the verification per step.
sourceOfTruth:
  - config/roadmap.json
  - Sources/iOS/TTSEngineStore.swift
  - Sources/QwenVoiceCore/AnyTTSEngineBackend.swift
  - project.yml
---
# macOS converges on the iOS architecture and UI — 2026-09

> Narrative authority for the roadmap plan `macos-ios-convergence-2026-09`. The ledger in
> [`docs/ROADMAP.md`](../ROADMAP.md) carries the live status; this document records the decision,
> the shape of the work and what each step must prove.

## Decision

The iOS app's design and architecture are the project's gold standard (maintainer, 2026-09-14). The
macOS app therefore:

1. drops its XPC engine service and hosts `MLXTTSEngine` in-process through `NativeRuntimeFactory`,
   on the same `TTSEngineStore` the iOS app uses (compiled into the macOS target by explicit path;
   iOS files keep their paths and behavior);
2. drops its legacy SwiftUI screens and adopts the iOS screens adapted to macOS, keeping every
   desktop capability that already exists (line batch and long-form, the per-mode Speed/Quality
   variant picker, model repair and update, the output folder, Save As and Reveal in Finder, the
   ⌘ menus, drag-and-drop import, History sort, replace reference, the Cmd+, Settings window);
3. keeps one dark palette, like iOS.

Two costs are accepted with the decision: an MLX or Metal fault takes the whole app down instead of a
service, and the 8 GB memory relief that came from retiring the XPC process is replaced by the
in-process trim and idle-unload policy the iOS app already runs.

## Shape of the work

| Step | Content | Proof |
| --- | --- | --- |
| A1 | `AnyTTSEngineBackend` moves to `QwenVoiceCore`; the iOS store gains a `snapshotUpdates` bridge; the app-local macOS `GenerationMode` copy is retired | macOS unit lane, generic iOS compile |
| A2 | the macOS app builds the in-process engine and the shared store behind the legacy screens; the XPC lifecycle coordinator goes; telemetry becomes app + engine | `macos_test.sh gate`, `ui_test.sh macos smoke`, one short benchmark record |
| A3 | the three XPC targets, the transport test bundle and every contract, script and document bound to them are removed or rewritten | `dev.sh ci`, `macos_test.sh gate`, smoke |
| B1–B9 | the iOS screens land under `Sources/Views` one per commit (shell, History, Saved Voices, Settings, Built-in Voice, Voice Design, Voice Cloning), identifiers unchanged, legacy files deleted as they fall out of use, then perf re-baseline and marketing captures | localization, smoke, perf and benchmark lanes per screen |

The iPhone is unavailable while this work runs: iOS changes are limited to forwards, seams with iOS
defaults and pure file splits, each verified by the generic device-SDK compile and the logic tests
compiled into `VocelloCoreTests`; the device lanes re-verify the frozen iOS behavior when the phone
returns (item CONV-20).

## Rules that hold throughout

- `main` only; every commit shippable and revertable on its own; `scripts/dev.sh check` before each.
- Accessibility identifiers survive every screen swap; the macOS XCUITest journeys are the gate.
- macOS interface copy stays catalog-owned with French; new strings enter `Localizable.xcstrings`.
- Model delivery stays macOS-native (`ModelManagerViewModel` over `HuggingFaceDownloader`): the iOS
  catalog carries only the Speed artifacts.

## Outcome (2026-09-15)

The plan completed in one day of commits on `main`, every one shippable and lane-verified. The
engine runs in-process on the shared `TTSEngineStore` (CONV-01–04, memory lane on the 8 GB Mac);
the shell, History, Saved Voices, Settings, Built-in Voice, Voice Design and Voice Cloning are the
iOS screens adapted to macOS under `Sources/Views` (CONV-10–17), and line batch plus long-form run
on the shared single-take executor and the shared long-form runner behind platform-hooks seams
(CONV-22). The legacy macOS views, coordinators, executor, theme, layout constants and drafts are
gone; the macOS accessibility identifiers survived unchanged and the lanes prove it. The perf
thresholds were re-baselined from three sessions on the converged tree and the marketing captures
retaken (CONV-18). Two items moved to the release-first plan: CONV-20 re-verifies the frozen iOS
behavior on the phone (the iOS edits were forwards, seams with iOS defaults and pure splits, each
verified by the generic device-SDK compile) and CONV-21 decides the toolchain bump. The single
cost that landed as predicted: push CI pins Xcode 26.6 while the Mac runs Xcode 27, so a
main-actor call from a nonisolated test override compiled locally and failed on CI until fixed
forward (ea795cde); the rule is to read CI after every push.

## UI fidelity follow-up (2026-09-15)

The close-out captures showed that adopting the iOS screens had not adopted the iOS design: the
skeleton matched, but nearly every surface had been re-implemented by hand at different numbers —
chips that hugged their labels and wrapped to two rows, a Generate button stranded at the left edge
of its row, a flat canvas where the phone paints a mode-tinted wash, a readiness paragraph the phone
never shows, and library rows, icons and buttons at their own sizes. Plan `macos-ui-fidelity-2026-09`
(UIF-01 to UIF-04) brings each surface back and moves the primitive that defines it into
`Sources/SharedSupport/Views`, so one edit changes both apps.

Maintainer decisions for that plan:

1. **Chip labels are full words on one line** (Aiden, Neutral, English). The pill shape, height, tint
   and equal-width row are the phone's; only the label uses the width a Mac window has and the phone
   does not, where it shows a two-letter code.
2. **The Studio title row goes** and the Speed/Quality picker moves to the window toolbar. The sidebar
   already names the mode, which is what the phone's capsule does.
3. **Search and filter chips come inline** on History and Saved Voices. The desktop-only sort menu and
   the enroll button stay in the toolbar.
4. Kept desktop-only against the phone: the sidebar instead of the tab dock, the persistent footer
   player, Voice Cloning's inline transcript field and consent stack, the inline Voice Design brief
   editor, and Settings' flat single scroll.

The first Studio commit copied the phone's composition literally, and on a desktop it read as a
void under floating text with a stain across the top. The same evening's decisions, all taken as
recommended: **top-down flow** (the composer is a bounded area that grows with its text, the
controls follow it, space falls to the bottom); **Batch is a square button beside Generate**, not a
setup chip; **one wash behind the whole window** at the phone's whisper intensity, tinted by the
selected destination, with the **title bar transparent over it**; and the **Studio column capped
at 640 pt** so three chips and the Generate button keep the phone's proportions.
