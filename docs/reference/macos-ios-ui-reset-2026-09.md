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
  deferred checks and next action. Claude Code edits the existing main checkout and preserves unrelated work.

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


## Remaining Mac acceptance (September 22)

Baseline `1b275857`. The failure journey exposed a real recovery dead end: Built-in and Design
blocked a new request whenever the connected engine retained a failed load state. `137ecee4` allows
retry while preserving installed-model, valid-input and no-active-generation guards. `e1ed0ed2`
uses one error/retry capsule instead of an error plus a second Generate row, disables it for invalid
input, and exposes the full error through help/accessibility. No engine or persistence contract changed.
Project regeneration also synchronizes known regions with the existing ten-language catalogs; no
translation content changed.

| Focused repository journey | Source | Run suffix (`macos-xcui-smoke-20260922-…`) | Result |
| --- | --- | --- | --- |
| `--scenario generation-errors` | `137ecee4` | `064658-0775af9b` | PASS: real output-write failure and successful retry in Built-in, Design and Clone; empty-input guard; zero failed History entries and one entry after each recovery; error/completed size matrix. |
| `--scenario studio-content` | `37c77c1e` | `070809-9f60d365` | PASS: English UI/French speech and inverse; localized starters/presets; exact custom delivery and brief preservation across speech/interface changes. |
| `--scenario layout` | `37c77c1e` | `071752-a3ac3e43` | PASS: long scripts in all three modes, Voices, History, all Settings categories and Cmd+, across minimum/default-width/wide cases. |

Each run passed required steps, crash delta and preference restoration. Failure injection changed
permissions only on run-owned disposable output subfolders selected through the genuine folder picker;
permissions and the original output preference were restored. No installed model was changed.
Representative minimum error/recovered players, language popovers, Settings and wide History captures
were reviewed. Raw evidence stays under the untracked run directories.

Actual outer bounds are **780×612**, **1040×678**, and **1268×678**. The 52-point toolbar leaves
560/626 points of content height. The helper now positions the window inside the display's usable
frame before resizing. No product minimum, scaling or scrolling behavior changed. The configured
680-point default content height exceeds this display's available height and remains untested here.
UIF-07 is complete for actual supported bounds on this host; this is not an unlimited-display claim.

Earlier attempts remain separate failures: `061630-291b0efc` (Settings category navigation),
`062520-1725e4c4` (Touch Bar Open matched instead of the folder dialog), `063146-2905a0a3`
(folder value read as a label; offscreen Back), `063823-31b5b168` (empty-string containment assertion),
`064228-15bd02fc` (the confirmed disabled-Retry product defect), `065638-46e5b543` (AppKit toggle
menu identifiers not exposed), and `070322-97957672` (starter accessible title includes a prefix).
Their corrections use existing controls, exact text assertions and bounded native navigation.
Interrupted interface preferences were restored through the real picker; no defaults were rewritten.

### History attribution and performance

`macos-xcui-perf-20260922-072938-4dfa8717` on `37c77c1e` passed 9/9 scenarios and all required
steps with 100% probe coverage. Its qualified record is **passedWithWarnings**, not warning-free:
idle max gap 61.21 ms exceeded 50 ms, and Settings max gap 67.84 ms exceeded 40 ms. Both maxima
belong to final probe blocks straddling teardown; fully enclosed blocks have a 16.667 ms maximum.
The unchanged checker intentionally retains boundary-block maxima. No thresholds were relaxed.
See the [compact record](../../benchmarks/runs/ui-perf/macos-xcui-perf-20260922-072938-4dfa8717.json).

Read-only 10 ms stack sampling was limited to the two exploratory History app processes. Across the
whole sampled scenarios, main-thread XCTest query-dispatch frames accounted for 926/6867 samples
(scrolling) and 961/8289 (filtering); filtering and grouping functions together appeared in fewer than
0.3% of samples. Snapshot construction and accessibility attribute traversal are substantial callers.
These aggregate samples include setup/teardown and do not timestamp an individual stall.

History scroll max gap was 176.56 ms. Filter max gap was 8600.56 ms in a block beginning 260 ms
before the measured window ended and ending 8678 ms afterward; fully enclosed filter blocks peaked
at 217.77 ms. This supports the existing combined app/XCUITest classification, not an 8.6-second
in-window product-stall claim or proof of perfectly smooth interaction. Sampling changes timing, so
these History numbers are not a clean performance comparison with the earlier unsampled run.
No History product rewrite is justified by this evidence. Cleanup subsequently drops its unnecessary
full-tree menu-existence query and sends the same Escape directly; that cleanup-only simplification
is compiled by the routed check, with no new timing-improvement claim.

These focused runs supplement the earlier 11/11 full smoke pass; they are not a new full-suite pass
on one source identity. UIF-08 retains its consolidated source-bound acceptance gate and iPhone
requirements. No phone, release or website lane was run. Local Xcode 27/Swift 6.4 results remain
separate from pinned CI. Source `137ecee4` passed [CI](https://github.com/PowerBeef/Vocello/actions/runs/35696425533),
and `37c77c1e` passed [CI](https://github.com/PowerBeef/Vocello/actions/runs/35699106198).

Final scoped `scripts/dev.sh check --paths …` passed: contracts/privacy/lint, 691 Python tests plus
382 subtests, 712 core tests, 122 runtime tests with three existing private-fixture skips, generic iOS
app/logic compilation, and the Mac UI bundle. The unrelated marketing-test edit remains unstaged.

## Consolidated Mac acceptance (September 22)

The complete suites were rerun serially on `c66c5b794b66cf84139bce5d296a95446953e62f`, with no
intervening source changes or retries. Both provenance snapshots have workspace fingerprint
`80ef9af7eec5c0dca8094be683da27719ec7fcf1456e4d600080bf8f8135d672`; the sole dirty source was
the unchanged paused marketing-test edit (five additions, one deletion). This is consistent local
development acceptance, not a clean-tree or signed-release qualification.

| Repository command | Run | Result |
| --- | --- | --- |
| `scripts/ui_test.sh macos smoke` | `macos-xcui-smoke-20260922-145946-95d3a54f` | PASS, 13/13 tests, no skips. Includes the complete ten-language/pseudolocalization journey, window matrix, three generation modes, cancellation, recording/review, libraries, long-form, line batch, missing-model links, error/retry recovery and cross-language Studio content. |
| `scripts/ui_test.sh macos perf` | `macos-xcui-perf-20260922-162034-c8dcee40` | Runner PASS, 9/9 tests, 100% probe coverage; performance **passedWithWarnings**. No external stack sampler. |

Both required-step ledgers and crash deltas passed. The smoke playback capture was available and
passed its gate (1/1). Preference/output restoration completed; representative minimum error and
recovered players plus bilingual custom-text captures were visually reviewed. Raw artifacts remain
untracked. Existing actual outer bounds remain 780×612, 1040×678 and 1268×678; the configured
680-point content height still cannot be reached on this display.

The [performance record](../../benchmarks/runs/ui-perf/macos-xcui-perf-20260922-162034-c8dcee40.json)
retains two unchanged warn-only ceiling breaches:

| Scenario | Reported maximum gap | Ceiling | Worst block relative to window start | Window duration | Fully enclosed block maximum |
| --- | --- | --- | --- | --- | --- |
| Idle | 58.899 ms | 50 ms | 14793–15293 ms | 15005 ms | 16.667 ms |
| Settings scroll | 70.447 ms | 40 ms | 8893–9397 ms | 9242 ms | 16.797 ms |

Both worst blocks overlap cleanup, so their maxima cannot be assigned entirely to the interaction
window. They remain warnings; the checker and thresholds were not altered. The other three
confirmatory scenarios had no threshold warnings. All scenarios reported nominal thermal state.
Exploratory History scroll/filter maxima were 125.721/174.072 ms, with both worst blocks fully
inside their windows. The previous multi-second gaps were not reproduced here, but this single
unsampled run does not isolate a cleanup improvement or prove compositor smoothness. History,
resizing and active-generation timings keep their exploratory designation; the complete registry
record is also exploratory because of the preserved dirty source.

Review before committing found a publisher defect: the default toolchain enrichment inspected the
development-cache app, while the UI runner had executed the optimized arm64 app. The run-owned
`last-build.json` receipts agree on the tested executable digest
`3251351076103eed6ed3d32eb451d121435754d4cddb7ffb1b7b18108d87118b` and optimization `-O`.
The publisher now uses that verified receipt for macOS UI performance records and fails closed if it
is missing or the executable changed. A deterministic regression test includes a conflicting
development-cache binary and checks stale/missing receipt rejection.

Only this new, uncommitted registry record was regenerated. Original resolved/publication metadata
was retained beside the raw run. The corrected record explicitly carries a publication-time
fingerprint mismatch because documentation and publisher corrections happened after execution;
the two original run snapshots and original resolved metadata establish the common execution source.
Measurements, warnings, thresholds and previously committed records were not changed. This remains
exploratory evidence, not an exact-source release record.
The final scoped routed check passed contracts, privacy and 692 Python tests plus 382 subtests.
The correction touched only publication tooling, its regression test and evidence documentation;
it selected no additional native build or UI run.

This supplies the previously missing full smoke/performance evidence on one source identity.
UIF-08 remains open for physical-iPhone scroll/localization acceptance. No phone, release or website
lane ran. Local Xcode 27/Swift 6.4 evidence remains distinct from the tested source's
[passing pinned-toolchain CI](https://github.com/PowerBeef/Vocello/actions/runs/35702227185).
