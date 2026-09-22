---
status: active
owner: backend-and-platform
reviewed: 2026-09-22
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

## Implementation sequence

1. Record this map and re-scope the existing UIF items. Extract shared presentation only when both
   apps immediately use it; keep iOS defaults and behavior unchanged.
2. Build the four-destination shell and one complete Built-in Voice Studio slice. Share the selector
   and composer/setup/dock layout. Keep the other screens operational until their turn.
3. Review the working Built-in Voice surface before extending its presentation to Design/Cloning.
   Validate empty, short and long scripts, missing model, error, generating/live and completed states.
4. Convert Design/Cloning, then Voices/History, then Settings and secondary sheets. Each change removes
   the presentation it replaces. Keep platform-specific IO and lifecycle effects in adapters.
5. Reconcile remaining window-size behavior and remove obsolete layout helpers and prescriptions.

The approved Built-in slice establishes the shell and shared composition. The subsequent Design
pass moves its brief behind a setup chip, uses a native popover with the shared brief catalog,
and places Save as Voice in the completed inline player. The assigned Clone pass moves saved
reference selection, import/record and transcript review into a native popover. All three modes
share the same column and own inline transport when their displayed take owns audio; other
destinations retain footer transport. Library/Settings screens remain for their own passes.

## Acceptance and handoff

- Run repository contracts, relevant deterministic tests, generic iOS compilation, Mac compilation,
  and compile changed XCUITest bundles. Native commands remain serialized.
- Explicitly authorize the capture/QA checkpoint through `scripts/ui_test.sh`; the earlier iPhone
  build/install request is not authorization for another automated device campaign. Use real controls,
  no seeded product state, Simulator, computer-use UI driver or test-only production route.
- Capture actual minimum/default/wide window sizes and a narrow localized pass. Check control fit,
  scrolling, keyboard focus, reduced motion/transparency, navigation and playback ownership. Preserve
  failures and fix the observed batch before a confirmation pass; no open-ended visual churn.
- Maintainer approval of the working Studio is the gate for the next screen pass. Image generation
  can illustrate a choice but cannot establish implementation fidelity.
- After shared extraction, generic iOS compilation is an immediate gate; physical-device regression
  remains required before declaring iOS preservation verified. Keep CONV-20 open until its own proof.
- Record baseline SHA, owned files, removed duplication, intentional platform differences, checks,
  deferred checks and next action. Codex edits the existing main checkout and preserves unrelated work.

Success means one implementation for common presentation, the approved iOS hierarchy on Mac,
preserved desktop capabilities, and a documented reason for each remaining platform-specific view.

## Outcome (September 19 and 20)

Every screen in the map was converted on the shared composition and approved on the running Mac:
the four-destination shell and Built-in Voice, Voice Design behind a brief chip, Voice Clone behind
a reference popover, compact Voices rows, transparent History headings, the sidebar status
alignment, and Settings as shared groups and rows in both the sidebar and the Cmd+, window. The
per-screen evidence and run ids are recorded in the archived UIF-03, UIF-04, UIF-05 and UIF-06
entries of `config/roadmap-archive.json`. Two items stay open under the plan: UIF-07 (the adapted
screens measured at real minimum, default and wide window sizes with genuine geometry assertions)
and UIF-08 (a consented lane set on current source covering error, missing-model and wide-window
states, the Cmd+, window and model links, and the iOS localization lane once its scroll helper is
corrected). Release-first is the primary plan again.

## Mac acceptance (September 22)

Source `d7058ea6`, including the unchanged, paused marketing-test edit in the run fingerprint:

| Repository lane | Run | Result |
| --- | --- | --- |
| `scripts/ui_test.sh macos smoke` | `macos-xcui-smoke-20260922-041322-1258c968` | PASS: 11 tests, no failures or skips; required steps and crash delta pass. |
| `scripts/ui_test.sh macos perf` | `macos-xcui-perf-20260922-052539-af73c69c` | PASS: nine scenarios, complete probe coverage, no configured-threshold warnings; required steps and crash delta pass. |

Smoke includes the complete ten-language localization journey, so a duplicate standalone localization
run was unnecessary. It also covers real Speed generation in all three Studio modes, completed
players, History ownership, switching clips, dismissal during streaming followed by cancellation,
recording, long-form joining and its segment map, line batch, Cmd+, Settings, and all three missing-model
links. Missing models use an empty diagnostics-only storage root; installed models are not removed or
downloaded, and normal-profile Speed readiness is checked afterward. Interface language and the
autoplay preference changed by the streaming test are restored through genuine controls.

The missing standard sidebar command group was added in `80feb7dc`. Ctrl+Cmd+S now toggles the
sidebar, and smoke proves that playback remains accessible in the detail footer when it is collapsed.
The stale library expectation was corrected in `d7058ea6`: the shared session helper deliberately
selects English and restores the original language, so the test must not assume System Default.

The earlier minimum-size discrepancy was a comparison of content size with outer window size.
The toolbar occupies 52 points on this host. Strict viewport/control assertions and screenshots
establish the following Studio bounds for long scripts, completed players and missing models:

| Case | Actual content size | Actual outer window size |
| --- | --- | --- |
| Minimum | 780 × 560 | 780 × 612 |
| Default width, display-limited height | 1040 × 638 | 1040 × 690 |
| Display-limited wide | 1072 × 638 | 1072 × 690 |

No application minimum, font scaling or scrolling behavior changed. The test measures the editor's
scroll viewport rather than its potentially offscreen text document, and can resize from the top edge
when the bottom edge reaches the display boundary. Representative completed-player and collapsed-sidebar
screenshots were visually reviewed. The configured 680-point default content height and larger widths
were not reached at the tested window placement; error-only player cards were not exercised. These remain
explicit limits of UIF-07/UIF-08, alongside the deferred iPhone acceptance and remaining cross-language
Studio-content cases. Neither item is closed by this pass.

Performance details are in the [qualified record](../../benchmarks/runs/ui-perf/macos-xcui-perf-20260922-052539-af73c69c.json).
Idle and Settings scrolling recorded zero hitch time. Navigation, delivery menus and typing stayed
within their existing warn-only ceilings; no thresholds changed. Exploratory History scrolling and
filtering reported maximum gaps of 4079.50 ms and 3322.23 ms, respectively. These measure app plus
XCUITest accessibility work, not compositor presentation; `maxGapMS` also retains the worst gap of any
probe block touching the measurement window. They are retained observations requiring attribution,
not confirmed application stalls or evidence of uniformly smooth History performance. Resizing and
generation-active measurements also remain exploratory. This is one local session, not a threshold
recalibration or signed-candidate qualification.

Earlier runs remain separate failures/incomplete evidence:

| Run suffix (all `macos-xcui-smoke-20260922-…`) | Outcome |
| --- | --- |
| `022102-4bee9238` | Wrong assertion measured the scrolled text document rather than its viewport. |
| `022515-ea673d69` | Bottom-edge resize could not shrink from the display boundary; the strict minimum assertion caught it. |
| `023232-eaabe9b5` | Size/Settings test passed; run stopped before the remaining journeys to finish command and fixture corrections. |
| `025338-8591ab82` | Ten tests passed; the library test failed on its stale System Default expectation. |

The routed local checks passed, including deterministic core/runtime tests and the Mac UI bundle;
the application change also passed generic iOS compilation. Application source `80feb7dc` passed
[CI including generic iOS compilation](https://github.com/PowerBeef/Vocello/actions/runs/35681116335).
Final test source `d7058ea6` passed [CI including Mac tests and TSan](https://github.com/PowerBeef/Vocello/actions/runs/35686046774).
Local Xcode 27/Swift 6.4 evidence remains distinct from pinned CI. No phone, release or website lane
was run for this Mac follow-up. Raw screenshots, logs and audio remain untracked.
