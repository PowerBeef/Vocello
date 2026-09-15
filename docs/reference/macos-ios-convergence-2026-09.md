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
