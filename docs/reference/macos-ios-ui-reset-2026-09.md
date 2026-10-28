---
status: active
owner: backend-and-platform
reviewed: 2026-10-28
summary: Replace the unsuccessful Mac presentation with the approved iOS design, sharing composition and retaining small desktop adapters.
sourceOfTruth:
  - config/roadmap.json
  - Sources/iOS/IOSStudioCanvas.swift
  - Sources/iOS/IOSGenerateFlowViews.swift
  - Sources/SharedSupport/Views
---
# iOS-derived macOS UI reset

## Reference and scope

The maintainer approved the freshly installed iOS 3.0.0 (24) optimized build from
`ca5a10cd08901d7845a8ab418e6a5724d71452de` on September 18. This is manual visual approval,
not automated iPhone regression acceptance. That iOS implementation is the visual reference.
The generated desktop concepts from the earlier exploration are discarded.

The approved replacement plan supersedes the September 15–17 Mac-only composition and
pixel prescriptions where they conflict. Keep the in-process engine, shared store, generation
pipeline, persistence, localization, accessibility and correctness fixes. Replace presentation
forward, one screen at a time; do not revert mixed commits or restore XPC. No release or data
migration is part of this work. `config/roadmap.json` remains the only work-status ledger.

## Reference-to-desktop map

| Surface | Shared reference | Desktop adaptation |
| --- | --- | --- |
| Navigation | Studio, Voices, History, Settings | Four sidebar destinations; mode selection remains inside Studio. Existing stored mode routes and command routing survive. |
| Studio | Flexible borderless editor, metadata, equal-width tinted pills, stateful dock | AppKit editor, readable bounded column, full-word values, Speed/Quality in toolbar, Batch beside idle Generate. |
| Mode selector | iOS capsule selector, per-mode tint, selection semantics | Desktop label font; keep old mode accessibility IDs on the real segment buttons. |
| Player | Live-to-complete inline player | Native Save As/Reveal and keyboard actions; one transport for the active take. A stale result must not operate unrelated playback. |
| Setup | iOS voice, delivery, language, brief and reference flows | Native menus/popovers/sheets; Design brief and Clone reference review open from their setup chips. |
| Voices/History | Search, filters, avatar/waveform rows, grouped metadata | Desktop sort and file actions; preserve every capability and identifier. |
| Settings | Categories and detail sections | The sidebar and Cmd+, window use the same Settings presentation; preserve desktop model variants, repair/update and output-folder controls. |

Use the shared dark palette, mode accents, capsule shapes, backdrop and primary-button rendering.
Do not introduce an appearance picker, repeated Studio heading, generic table redesign, right-hand
inspector or new styling system. Existing Mac dimensions are provisional values, not design authority.


## Rules for further Mac UI work

- Extract shared presentation only when both apps immediately use it, and keep iOS defaults and
  behavior unchanged. Each change removes the presentation it replaces; platform-specific IO and
  lifecycle effects stay in adapters.
- Maintainer approval of a working screen gates the next screen pass. Image generation can
  illustrate a choice but cannot establish implementation fidelity.
- Run repository contracts, relevant deterministic tests, generic iOS compilation, Mac compilation
  and the changed XCUITest bundles; native commands stay serialized. After a shared extraction,
  generic iOS compilation is an immediate gate, and physical-device regression is still required
  before declaring iOS behavior preserved.
- Prove layout through `scripts/ui_test.sh` with real controls, never seeded product state, a
  Simulator or a test-only production route: actual minimum, default and wide window sizes and a
  narrow localized pass, with control fit, scrolling, keyboard focus, reduced motion and
  transparency, navigation and playback ownership. Preserve failures and fix the observed batch
  before a confirmation pass; no open-ended visual churn.
- Record the baseline SHA, owned files, removed duplication, intentional platform differences,
  checks, deferred checks and the next action.

Success means one implementation for common presentation, the approved iOS hierarchy on Mac,
preserved desktop capabilities, and a documented reason for each remaining platform-specific view.

## Outcome (September 19 to 22)

Every screen in the map was converted on the shared composition and approved on the running Mac:
the four-destination shell and Built-in Voice, Voice Design behind a brief chip, Voice Clone behind
a reference popover, compact Voices rows, transparent History headings, the sidebar status
alignment, and Settings as shared groups and rows in both the sidebar and the Cmd+, window
(UIF-03 to UIF-06 in `config/roadmap-archive.json`). The Design brief opens in a native popover
with the shared brief catalog, and Save as Voice sits in the completed inline player. All three
modes share one column and own inline transport while their displayed take owns audio; other
destinations keep footer transport.

UIF-07 closed on September 22. Studio long scripts, error and completed players, Voices, History
and every Settings category fit the actual outer window bounds of the test display: 780×612
(minimum), 1040×678 and 1268×678. The 52-point toolbar leaves 560 and 626 points of content height;
the configured 680-point default content height was not reachable on that display, so this is no
unlimited-display claim. The consolidated runs on `c66c5b79` passed full smoke (13/13,
`macos-xcui-smoke-20260922-145946-95d3a54f`) and perf
([`macos-xcui-perf-20260922-162034-c8dcee40`](../../benchmarks/runs/ui-perf/macos-xcui-perf-20260922-162034-c8dcee40.json),
passedWithWarnings: the idle and Settings-scroll maximum gaps exceed their warn-only ceilings in
probe blocks that overlap cleanup). The exploratory History scroll and filter scenarios measure the
app plus XCUITest accessibility work, not compositor presentation; their multi-second gaps in
earlier runs are retained observations, not confirmed product stalls, and justified no History
rewrite.

UIF-08 (native acceptance on current source, including the iPhone scroll and localization lanes)
stays parked. The per-run evidence, including the earlier failed attempts, is in the archived
roadmap entries and git history.
