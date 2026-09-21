---
status: active
owner: backend-and-platform
reviewed: 2026-09-20
summary: Current resume checkpoint; config/roadmap.json owns open work, config/roadmap-archive.json holds finished work, and older narrative lives in git history.
sourceOfTruth:
  - config/roadmap.json
  - config/runtime-refactor-contract.json
---
# Vocello development checkpoint

Start here, then follow `config/roadmap.json`'s `primaryPlan` and the
[release-first execution plan](reference/release-first-execution-2026-09.md).
This is a narrative, not a second work ledger. Product source, contracts and scripts win.
Checkpoints older than the ones below live in git history (`git log -p -- docs/development-progress.md`,
last full copy at commit 25a895ed).

## Resume now

### Codex-only development workflow (September 20)

Codex is the sole development agent. Baseline: `cb9ff234`; the pre-existing paused change in
`Tests/VocelloMacUITests/VocelloMacMarketingCaptureUITests.swift` is outside this assignment.
Root and website `AGENTS.md` now own instructions; native/release rules live under
`docs/reference/agent-rules/`. Four explicit `.agents/skills` shortcuts reuse existing scripts.
Tracked Claude configuration and reviewer definitions are retired; personal settings and historical
attribution remain untouched. The five Codex hooks share one input adapter, use local checkout paths,
and no longer probe the iPhone at startup. Hook tests are consolidated, and local/CI routing covers
Codex configuration and skill metadata without selecting native lanes for instruction-only changes.
No application, product-test, release-gate or toolchain changes. Routed verification passed lint,
contracts and 1,563 Python tests plus 959 subtests. Its native stage first hit sandbox cache denial
(`mac-test-20260920-232235`, retained), then passed with compiler-cache access
(`mac-test-20260920-232320`); the remaining generic iOS app/logic compilation and full website checks
(12 fixtures, rendered accessibility, production build, two Playwright tests) passed serially.
All four skills validate; root/website hook fixtures cover allowed and blocked operations. Initial
CI exposed an accidental PyYAML import in the metadata smoke test; the fix uses only the standard
library, verified by all 24 hook tests with `python3 -S -m unittest discover -s scripts/tests -p
test_agent_hooks.py`. No CI dependency or pin was added. Local compatibility is separate from pinned
CI: check the latest migration commit's GitHub checks before resuming
product work. Fresh-session instruction/skill discovery and platform hook trust activation remain
unverified; fixtures do not prove runtime activation. The marketing test remains paused.


### Marketing lane and screen close-out (September 20)

Claude returned to a dirty tree left on the afternoon of September 19: a new
`scripts/ui_test.sh macos marketing` lane (`test00_WebsiteRefresh`, `test06_ModelDownloadsRefresh`,
the lane registered in `config/orchestration-contract.json` and `config/build-output-policy.json`)
and ten refreshed README and website images, with no narrative entry, roadmap note or handoff
naming an owner. The maintainer transferred ownership to Claude. The lane drives genuine controls at
a 1040×680 window, generates two demo takes and saves one designed voice; its run record carries
`evidenceClass: marketing-assets` and never counts as acceptance, promotion or benchmark evidence.
Runs `macos-xcui-marketing-20260919-165526-a31fd916` (all scenarios) and
`macos-xcui-marketing-20260919-170123-cb31c03d` (models) passed with their crash checks; the two
earlier attempts that afternoon are retained as failed. The Model Downloads capture had not been
copied: `docs/screenshots/vocello-model-downloads.png` and the website `model-downloads.png` now come
from the second run, so all six Mac images share one 2080×1380 capture size. The lane is documented
beside the other macOS lanes in `macos-testing.md` and `macos-app-guide.md`, whose smoke row now
counts the nine journeys the class actually runs. The contract gate had never been run on this tree: `scripts/repo_invariants.sh` rejected the inherited test's two visible-label lookups of the enrolled "Studio narrator" row, now replaced by an identifier-anchored row lookup that waits without recording a failure. That is a test-only change after the captures; the lane was not rerun for it.
Validation: `scripts/dev.sh check` passed on the corrected tree (deterministic Mac tests
`mac-test-20260920-151733`, 1,566 Python tests with 944 subtests, the generic iOS compile, the
website check and the Mac UI-test bundle build).

The maintainer then had the roadmap reflect the finished redesign: UIF-03, UIF-04, UIF-05 and
UIF-06 are archived on the per-screen visual approvals and lane runs recorded above, with the
open acceptance clauses re-homed into UIF-07 (window-size geometry) and a new UIF-08 (consented
lane set on current source, error/missing-model/wide-window states, the Cmd+, window and model
links, and the iOS localization lane after its scroll-helper correction). The reset document
records the outcome; `release-first-3-0-2026-09` is `primaryPlan` again and its stale title
parenthetical is gone. Next: the phone-free backlog, starting with the iOS scroll-helper
correction (UIF-08, ISU-4) and AUD-03.

### Mac Studio automatic mode and line-by-line override (September 19)

From clean `dac06129`, the maintainer requested the iPhone long-form indicator on Mac and a
line-by-line toggle in place of the batch-sheet shortcut. All three Studio modes now show the
active batch mode instead of a character counter. Grey off remains clickable; tinted on also
exposes the selected accessibility trait and a Line-by-line label. Generate and its keyboard
shortcut route the current draft to line-by-line when selected, otherwise to long-form above
900 characters or an ordinary take. The router now counts the exact script like iOS, including
outer whitespace. The sheet retains its review/start/recovery workflow with a read-only mode.
Validation: `scripts/dev.sh check` passed, including native tests
`mac-test-20260919-121757` (900/901 routing, whitespace parity and the line-by-line override),
909 Python tests with 610 subtests, generic iOS app/logic builds and both UI-test bundle builds.
No generation or XCUITest journeys were run. UIF-06 remains in flight for visual acceptance.

### iPhone long-form indicator (September 19)

After approving Studio spacing, the maintainer requested replacing the misleading character
counter with a long-form mode indicator. From clean `82843da6`, all three iPhone Studio modes
show the existing localized Long-form label only when the shared generation policy routes the
draft to long-form (above 900 characters). Short drafts leave that area empty. The editor uses
the shared 30,000-character clamp directly; the UI no longer has a separate counter-derived cap.
The control inventory and UI journeys now identify the mode indicator and read the editor itself
to confirm text entry. Generation routing and the threshold are unchanged.
`scripts/dev.sh check` passed: native tests `mac-test-20260919-113724` (including the existing
900/901-character routing boundaries), generic iOS app/logic builds, the updated iOS UI-test
bundle compile, and 751 Python tests with 395 subtests. Device generation/UI journeys were not
run for this presentation change; the installed build is for maintainer visual review.

### iPhone Studio spacing (September 19)

The maintainer visually approved the refreshed Settings and requested more separation between
Generate and the iPhone tab bar. The initial 12-point addition from `9602678c` was too large;
the maintainer requested a gap matching the selectors above Generate. From clean `b1958526`,
the extra clearance is reduced to 7 points, accounting for the existing gap below the button.
The action area's internal height is unchanged;
the flexible composer yields the extra space. This is an iOS presentation-only adjustment.
`scripts/dev.sh check` passed, including deterministic native tests
`mac-test-20260919-112133` for the refined spacing, generic iOS app/logic compilation and repository contracts.
This spacing-only follow-up uses the maintainer's screenshot and manual device review;
it does not reopen or claim a pass for the pending doubled-string Settings lane.

### Shared Settings refinement (September 19, visually approved)

The maintainer assigned Settings on both platforms after the benchmark checkpoint. Codex owns
this slice from clean `34d49ca4`: shared quiet Settings groups and navigation rows, shared typed
category copy, a compact Mac overview/detail flow, and value-led iOS overview rows. The Mac keeps
all existing model, memory, playback, variation, language, storage and consent controls, in both
the sidebar and Cmd+, host. Studio model links still select and focus the correct package mode.
The Mac UI tests now navigate the real category buttons and cover overview/audio/language fit.
No engine, download, preference-key, commerce or persistence behavior changes.

Validation: `scripts/dev.sh check` passed (deterministic Mac tests
`mac-test-20260919-095017`, generic iOS compile and Mac UI bundle compile); contracts passed
with 690 Python tests and 367 subtests. Mac localization
`macos-xcui-localization-20260919-135822-84f9678f` passed; overview, Audio and doubled-string
captures were inspected. The subsequently corrected UI interaction helpers pass all 19 focused
`UIInteractionPolicyTests`; each device lane rebuilt its current iOS test bundle.

The maintainer made the iPhone available for the requested installation/layout check. Four
failed localization runs are retained, without merging their verdicts:

- `ios-xcui-localization-20260919-140555-e9353b74`: the generic status query resolved a decorative
  image. The layout test now explicitly queries the readable status text.
- `ios-xcui-localization-20260919-141903-c09e20c2`: repeated gestures used a heading clipped at
  the top edge. The maintainer also reported an alarm interruption. The helper now prefers
  central visible content, with a captured-bounds regression test.
- `ios-xcui-localization-20260919-143339-e7679bb6`: doubled strings stopped language navigation
  because a tall row was not wholly visible. Navigation now requires its visible central tap
  band; full-frame layout assertions remain separate and unchanged, with regression coverage.
- `ios-xcui-localization-20260919-144816-4590e8d3`: English, French, AX-L and AX-XXXL completed
  their layout walks, but Pseudo-AX-XXXL still stopped at language navigation: the scroll
  helper's delta-dependent anchor-size limit excluded the available visible text. The complete
  device lane remains **failed**, and the doubled-string configuration is unverified.

Raw captures and forensics remain untracked under `build/artifacts/ui-tests/`. No application
layout defect is established by these helper failures. The maintainer visually approved the
installed Settings. Next: resolve the bounded scrolling helper and run a new complete iOS
localization lane. Model-download deep links and the separate Cmd+, window were reviewed in
source but not independently exercised in this slice. UIF-04 and broader secondary surfaces
remain open; this is not release or complete native acceptance.


### Speed versus Quality benchmark (September 19)

The maintainer requested a complete mode/preset performance and peak-memory comparison before
continuing UI work. The optimized shared-engine CLI campaign on clean `b23d8a7e` completed all
58 takes across Built-in Voice, Design and Clone, Speed/Quality, three text lengths and three warm
repetitions (plus four Built-in/Design cold-model takes). All six runs passed evidence validation
with soft-trim warnings, 100% memory sampling coverage, nominal thermals and no crashes. Quality
used 35.7–40.1% more normalized synthesis time on warm long text and 0.54–0.76 GiB more peak
physical footprint; the largest observed peak was Clone Quality at 4.04 GiB on the 8 GiB M2 Mac.
The approved clone fixture and all six model variants were verified; missing Design/Clone Quality
weights were installed through the production downloader. See the
[full report and retained evidence](reference/speed-quality-benchmark-2026-09-19.md).
These are engine cost measurements, not a perceptual-quality verdict or an iPhone/UI benchmark.
No application source changed; the existing UI acceptance work remains the next assignment.


### iOS-derived Mac UI reset (September 18)

The maintainer confirmed the installed iOS 3.0.0 (24) UI from `ca5a10cd` and approved replacing
Mac presentation with shared iOS-derived screens. Follow
[the reset map and acceptance sequence](reference/macos-ios-ui-reset-2026-09.md); it supersedes
conflicting layout and pixel prescriptions in the older entries below. Preserve the engine migration
and correctness/accessibility fixes. UIF-06 owns the first shell/Built-in Voice slice and its visual
checkpoint; UIF-05 owns sharing/metrics, with library, Settings and window acceptance in the existing
UIF items. No automated device/UI acceptance is implied by the earlier manual iPhone review.

Codex owns the first implementation slice, based on the clean `ca5a10cd` checkout: four sidebar
destinations, the shared capsule selector and Studio composition, and Built-in Voice's inline
transport. The iOS wrappers immediately consume the extracted components and shared navigation
labels. Mac navigation and playback XCUITest queries follow the genuine replacement controls.
The changed-file scope is the shell, Studio presentation, those iOS adapters, shared presentation,
Mac UI tests, generated project and the associated roadmap/guidance. Subsequent Studio, compact Voices and History heading assignments and evidence are recorded below;
Settings and broader library acceptance remain open. Before another assistant edits, check the
actual diff and HEAD against the committed handoff.

Verification on September 18: `scripts/dev.sh check` passed after the final source correction:
contracts, 690 selected Python tests plus 367 subtests, deterministic Mac tests
(`mac-test-20260918-130741`), generic iOS app/logic compilation, and the Mac app/XCUITest bundle
build. The aggregate log is `build/artifacts/macos/ios-ui-reset-check-2026-09-18.log` (untracked).
This is local Xcode 27 evidence, not pinned-toolchain CI or maintainer visual approval.

The maintainer then authorized Mac localization and smoke QA. Localization passed in
`macos-xcui-localization-20260918-171455-4d66e569`. The first smoke run,
`macos-xcui-smoke-20260918-171958-4eb258ae`, is retained as failed: six journeys passed, while
the Built-in completion helper still required the retired sidebar transport. Its capture and
element tree confirmed the completed inline player. The correction changed tests only, selecting
the mode's actual player and checking inline/sidebar ownership across History navigation.
Confirmation `macos-xcui-smoke-20260918-173621-fa6a4301` passed all seven journeys, crash checks
and playback capture (one of one captured, no capture gate failures). Lint passed after the
correction. Ready/completed/minimum-window Built-in captures were inspected; raw evidence stays
untracked under the corresponding `build/artifacts/ui-tests/macos/` run directories.

The maintainer approved the Built-in Voice layout, requesting one correction: the selected mode's
highlight should fill its equal-width third of the rail. The shared selector now offers segment-width
fill, enabled by the Mac adapter; the approved iOS presentation keeps its original default.
The sizing correction passed `scripts/dev.sh check` and the focused localization lane
`macos-xcui-localization-20260918-181344-6693debf`; its inspected capture confirms the full-third
highlight. Aggregate logs: `build/artifacts/macos/ios-ui-reset-segment-check-2026-09-18.log` and
`build/artifacts/macos/ios-ui-reset-segment-localization-2026-09-18.log` (untracked).
The seven-journey smoke evidence above predates this visual-only adjustment.
The maintainer next assigned Voice Design. Its implementation now uses the approved column and
inline player. The permanent brief form is replaced by a Voice brief chip and native popover;
the existing brief editor/catalog, character limit and accessibility field identity are retained.
Save as Voice moves into the completed player; saved confirmation, seed, batch and generation
request ownership remain with their existing owners. The Mac UI helpers open the genuine brief
control; a new smoke journey covers retention, Design generation, player fit and save-dialog
prefill/cancellation. Captures exposed a filename-style display label; the final presentation
uses readable brief text and the Design accent on the popover confirmation.

Design verification: final `scripts/dev.sh check` passed (737 Python tests plus 553 subtests,
Mac deterministic run `mac-test-20260918-145417`, generic iOS app/logic compile and Mac UI-test
bundle build). Localization passed in `macos-xcui-localization-20260918-183415-a688dd70` before
the label polish. The first Design smoke run passed all eight journeys; final confirmation
`macos-xcui-smoke-20260918-190108-5dcf5888` also passed 8/8, including its pseudolocalized
navigation journey, crash checks and captured playback (1/1, no capture gate failures).
The ready, brief-popover and completed-player window captures were inspected. Aggregate logs are
`build/artifacts/macos/ios-ui-reset-design-final-check-2026-09-18.log` and
`build/artifacts/macos/ios-ui-reset-design-confirmation-2026-09-18.log` (untracked).
The new journey checks save-dialog prefill and cancellation, not committing a new saved voice.

The maintainer next assigned Voice Clone. Its reference chip now opens a focused native
popover containing saved-voice selection, import, recording, active-reference details and the
editable transcript. Consent and actionable load/drop warnings remain on the canvas. Clone
now shares the same column and inline-player ownership as Built-in and Design. Reference
hydration, transcription, proactive priming and generation execution retain their existing owners.
The recording journey opens the genuine reference control, and a new Clone journey checks
reference retention, generation, narrow player fit and transport ownership across History.

Clone verification: `scripts/dev.sh check` passed (737 Python tests plus 553 subtests,
Mac deterministic run `mac-test-20260918-213831`, generic iOS app/logic compilation and Mac
UI-test bundle compilation). The initial check found an incomplete presentation-state switch;
its failed build evidence remains in `mac-test-20260918-213413`. The corrected check and final
lint passed. Localization `macos-xcui-localization-20260919-014410-be602795` and smoke
`macos-xcui-smoke-20260919-014828-1e1fcc0b` both finished with full runner PASS. Smoke passed
all nine journeys, including recording from the reference panel and Clone reference/transcript
retention, generation, narrow player fit and History transport ownership; playback capture was
1/1 with no capture gate failures. Ready/reference/completed window captures were inspected.
The temporary sidebar-dependent Studio player branch and obsolete wider Clone column are removed.
Aggregate logs are `build/artifacts/macos/ios-ui-reset-clone-final-check-2026-09-18.log` and
`build/artifacts/macos/ios-ui-reset-clone-smoke-2026-09-18.log` (untracked). The run IDs use UTC;
the local work date is September 18. Import panels, drag/drop and saving a newly recorded reference
were not exercised by these journeys.

The maintainer then flagged a horizontal rule beneath the Voices heading. Hiding the native
section separator compiled but did not remove the visible rule. The correction replaces the
native section header with a plain, separator-free heading row and retains the voice rows,
scroll-to-voice behavior and controls. Localization confirmation
`macos-xcui-localization-20260919-022755-735a2909` passed; its explicit Voices screenshot was
inspected and confirms the rule is gone. A preceding UI preflight refused a manually launched
app at another build location; that instance was closed before the confirmation run.
The verified optimized app was reopened for the maintainer. Final `scripts/dev.sh check` passed;
its log is `build/artifacts/macos/voices-heading-final-check.log` (untracked).

The maintainer assigned a compact Voices pass after finding the cards disproportionately large.
Rows now use a 32-point avatar, two-line metadata, inline Play/Use controls, a compact warning
icon and an actions menu for Delete. The heavy glass surface and width-driven second action row
are removed; French Use/More actions labels are maintained in the catalog. The existing warning
popover and replacement action remain available. UI queries now address the menu as the actual
macOS `MenuButton`; the initial wrong-button-query failure is retained at
`macos-xcui-localization-20260919-025626-a89168cc`. Confirmation
`macos-xcui-localization-20260919-030105-1f97cbec` passed, including doubled-label geometry,
normal-text primary-control alignment and menu discovery without deleting a voice. Both captures
were inspected; the normal capture catches the menu fading after Escape. No additional visual
polish pass was run. Final `scripts/dev.sh check` passed (log: `build/artifacts/macos/voices-compact-final-check.log`);
History and broader library acceptance remain open under UIF-03.

The maintainer next flagged the same native header rule and material band in History. Its date
buckets now render as transparent heading rows, matching the corrected Voices approach; date
bucketing, search, filtering, sorting and project grouping retain their existing implementation.
Localization `macos-xcui-localization-20260919-032042-5341bb4a` passed and its explicit History
capture confirms the full-width header rule and material band are gone. The genuine heading
has an accessibility identifier so the capture cannot silently pass on an empty/filtered screen.
Final `scripts/dev.sh check` passed (`build/artifacts/macos/history-heading-final-check.log`);
aggregate UI log: `build/artifacts/macos/history-heading-localization.log`.

September 19: the sidebar status title now has the same minimum height as its symbol frame,
centering single-line labels such as Ready/Prêt while retaining the existing message/progress
layout. Localization `macos-xcui-localization-20260919-040439-201d99cc` passed; the inspected
History capture confirms the alignment. Final `scripts/dev.sh check` passed; log:
`build/artifacts/macos/status-alignment-final-check.log` (untracked).

September 19: the maintainer approved the resulting Studio, compact Voices, corrected History
headings and status alignment, and requested committing and pushing all changes from the original
`ca5a10cd` baseline. This change records that visual approval. Next: the remaining Settings and
broader library/window acceptance work in the roadmap. Check HEAD and repository state before
handing editing ownership back to Claude.
The extracted iOS presentation still has compile proof only; physical regression remains deferred
under CONV-20. Missing-model/error states, wide-window coverage, and accessibility preference
combinations were not exhaustively exercised by these two Mac lanes.


### Shared Claude–Codex workflow and independent review (September 18)

Claude remains primary; Codex reviews and implements assigned work on the same local `main`, one
editor at a time. Root and website `AGENTS.md` route to existing rules; the five shared hooks have a
Codex adapter, configuration changes select their tests, and seven project actions use the existing
scripts with empty automatic setup. Follow the
[baseline/evidence handoff](reference/development-workflow.md#claude-and-codex-handoffs), checking the
actual diff before taking ownership. Codex discovered the hooks without errors but reported them
untrusted; platform trust and fresh-session automatic dispatch remain to be verified.

The [dated review](reference/project-review-2026-09-18.md) maps ownership and coverage and revalidates
AUD-01 through AUD-12 without changing their work status or the primary plan. It narrows unsupported
claims, especially AUD-07's former unconditional StoreKit finish prescription. Native deterministic
tests, TSan, generic iOS compilation, Python and website checks passed locally; local Xcode 27 differs
from CI's pinned 26.6. No application runtime or schema changed. Device/UI/model and release work
retain their explicit-request requirements. Use the roadmap for the next assignment.

### The Mac screens read like the iOS app, on a desktop (September 15, evening)

The close-out captures showed that adopting the iOS screens had not adopted the iOS design: the
skeleton matched, nearly every surface had been re-implemented at different numbers. Plan
`macos-ui-fidelity-2026-09` (UIF-01 to UIF-04) is primary; its decisions live in the "UI fidelity
follow-up" section of `docs/reference/macos-ios-convergence-2026-09.md`. UIF-01 is closed: the Studio
canvas went to the phone's composition (5140a475), the localization lane caught a Settings row the
close-out had squeezed (c54b8dff), and the maintainer's review of the literal copy led to the
desktop pass (03c12444, 2be20f0c): a composer sized to its text with the controls under it and space
at the bottom, Batch as a square beside Generate, the column at 640 pt, one mode wash across sidebar
and canvas painted per split-view column, and a transparent title bar with the per-destination
controls attached to the detail column. Lanes on 2be20f0c: localization 012725-a705d1fe, smoke
013020-f98f17b1 7/7, perf 014036-508e2487 nine scenarios clean, custom benchmark 014846-5892b77c.
Two CI-only compile errors this evening came from the same source, Xcode 26.6 on CI against Xcode 27
here; both were isolation annotations, both fixed forward, and CI is read after every push. Next:
UIF-05 follows, and runs before the remaining screen work: the maintainer judged the composition right
but the elements and text proportions incoherent, and three inventories measured why. The macOS app
renders 38 text styles for 13 roles, with 10 pt alone carrying thirteen of them because `.caption`,
`.caption2` and `.footnote` all resolve to 10 pt on macOS; a row title is rendered at 10, 11, 12, 13 and
14 pt on different screens; fourteen interactive control heights live between 22 and 56, six of them used
once; one warning triangle appears at seven sizes; and half the layout numbers sit off the project's own
4 pt grid while the shared `Spacing` tokens are used seven times against roughly two hundred literals. The
scale is six type steps for thirteen roles, six control heights each carrying the glyph size and shape
that belong to it, and new stroke, elevation and opacity tokens, all in the shared theme so the two apps
cannot drift apart on type the way they just did on primitives.

UIF-02 collapsed the duplicated view primitives into `Sources/SharedSupport/Views` as a pure move:
thirteen types, 923 lines of duplication removed, every platform difference now a parameter carrying
the value that side already had. A verification fleet audited each pair adversarially and refuted
every claimed regression; its completeness critic caught the two things a pair-by-pair audit cannot
see — the phone's `.tracking(0)` riding along onto the macOS wordmark, which never had it, and the
primary CTA's `Button` leaving the iOS control audit's scan when it moved into SharedSupport, which
would have made that contract weaker while reporting green. The scanner now reads the shared views
and the CTA has its own coverage row. The filter chip row and the settings rows stay put until
UIF-03 and UIF-04, which rewrite exactly the numbers that would otherwise be parameterised. Then
History and Saved Voices, Settings and the shell, and the captures are retaken.

### macOS converges on the iOS architecture (September 14)

The maintainer decided that the iOS app's design and architecture are the project's gold
standard. The macOS app drops its XPC engine service for the in-process engine the iOS app runs,
on the same `TTSEngineStore`, then drops its legacy screens for the iOS screens adapted to macOS
with the desktop features that already exist (batch and long-form, variant picker, repair and
update, output folder, Save As and Reveal, ⌘ menus, drag-and-drop, sort, replace reference, the
Cmd+, window), dark-only. `macos-ios-convergence-2026-09` was the primary plan until it completed
on September 15 (archived; `release-first-3-0-2026-09` is primary again); its authority is
`docs/reference/macos-ios-convergence-2026-09.md`, which now records the outcome. Order: engine first (CONV-01 seams, CONV-02
in-process swap behind the legacy screens, CONV-03 XPC removal with its contracts, CONV-04 memory
relief), then the screens one per commit (CONV-10 to CONV-18), with CONV-20 re-verifying the frozen
iOS behavior when the phone is back. Accepted costs: no crash isolation, and 8 GB relief from
in-process trim and unload instead of service retirement. CONV-01 (96709242) laid the seams; CONV-02
put the macOS app on the in-process engine behind the legacy screens: `MacEngineBootstrap`, the shared
store compiled by path, two-layer telemetry, and all seven smoke journeys passing on the first run
(macos-xcui-smoke-20260915-040350-f374335f). CONV-03 removed the XPC service, its two frameworks,
the transport test bundle and every contract, script and document that named them; the smoke lane
passed again (macos-xcui-smoke-20260915-054806-55c7c01b) and the first two-layer benchmark record
published (macos-xcui-benchmark-20260915-060047-cf740c28). CONV-04 closed on the consented memory lane
(mac-memory-qualification-20260915-165501-b1cb1ebc: eleven takes, one soft trim each, no
warning or critical pressure, footprint peak under 3 GB). The screens started
with CONV-10 (b7b62075): `Sources/SharedSupport` now holds the theme tokens, the glass surface body,
the word-timing planner and the script-limit policy, the iOS files forward to them unchanged in
behavior, and the macOS long-form router reads the shared limit. CONV-11 put the new shell in
place: `SidebarView` rewritten in the iOS visual language (lockup, Studio and Library sections,
tinted glyph tiles, tint-glass selection pill, install hint on dimmed modes), `MacInlinePlayerCard`
and `MacStatusStrip` in the footer, `MacWindowToolbar` and `MacStartupDiagnosticsView` out of
`ContentView`, `MacAppModel` for the shell state, `MacTheme` / `MacGlass` / `MacMotion` over the
shared tokens, dark-only on both scenes; every `sidebar_*` and `sidebarPlayer_*` identifier
unchanged and the legacy screens still hosted underneath; the localization lane passed on it
(macos-xcui-localization-20260915-065557-d168d6d4). CONV-12 followed with History: the iOS card
design (date buckets, mode filter chips, tinted thumbnail tiles) with the desktop's toolbar sort,
search and clear, Save As, Reveal in Finder and pinned seed, over the shared `Generation` and
`DatabaseService` now compiled into both apps; `HistoryView.swift` and the macOS twins are gone.
CONV-13 followed with Saved Voices: the iOS avatar rows, the enrollment sheet and the record
sheet in the iOS language, over the shared `PreparedVoice` and the shared saved-voices view model.
CONV-14 put Settings on the iOS row design: the recommended-setup summary and the per-mode Speed
and Quality packages with their desktop actions, the interface-language picker (an `IOSAppLanguage`
over the app's defaults store, owned by `MacInterfaceLanguage`), auto-play, variation, the
lower-memory toggle, the output folder and Application data, clone consent last; the Cmd+, scene
shows the same screen; its lanes passed (localization 172237-799a37c7, smoke 172745-96a732fb, perf
173808-8adae46d) and CONV-14 is closed. CONV-15 put Built-in Voice on the iOS Studio canvas
(composer, chip menus, dock with the player card) over the shared single-take pipeline; the batch
sheet and runner wait for CONV-22 because the legacy Design and Cloning screens still present them.
CONV-16 followed with Voice Design on the same canvas: the brief editor inline above the composer,
the shared Delivery and Language chips (now `MacStudioChips`), and the save-as-voice action for the
last take over the shared pipeline; its lanes passed (localization 193652-7fbe0a64, smoke
193951-08d0c88c 7/7, design benchmark 195002-89555f53) and CONV-16 is closed.
CONV-17 put Voice Cloning on the canvas (d6098edf): the reference chip is the saved-voice menu with
Import, Record and Clear inside it, the bank delivery chip appears for a persona, and the footer
carries the reference status, warnings, transcript field, inline consent and readiness; the legacy
pipeline (VoiceCloningCoordinator, GenerationLifecycleExecutor, TextInputView and the workflow
views) is gone. Its lanes passed (localization 202046-d7f04ed1, smoke 202348-6a2e9d2f 7/7, perf
203408-f0d2bd13 nine scenarios clean, clone benchmark 204218-674a9e13) and CONV-17 is closed. Push
CI had been red since the Settings commit on one test fixture calling a main-actor bootstrap from a
nonisolated setUp (Xcode 26.6 on CI refuses what Xcode 27 accepts locally); ea795cde fixed it
forward. CONV-22 landed as 606faa1f: MacBatchGenerationSheet serves all three modes, line batch
loops the shared single-take executor through MacLineBatchRunner on MacAppModel, long-form runs the
shared iOS coordinator and runner through a platform-hooks seam (the iOS adapter reproduces the
inline calls, the macOS adapter supplies Settings variation and language, telemetry merge, History
announce and catalog card titles), and the legacy remainder is gone: BatchGenerationRunner,
AppTheme, LayoutConstants and the macOS drafts, replaced by the shared iOS drafts. Its lanes passed
(localization 215251-77c1665d, smoke 215552-ae7e4fe4 7/7 with the batch and long-form journeys on
the new sheet, perf 220611-0bb33592 nine scenarios clean, custom benchmark 221418-0b947118) and
CONV-22 is closed. Every legacy macOS screen is now replaced. CONV-18 closed the plan (55c8cd9b):
the UI perf thresholds moved to baseline-v3 from three sessions on the converged tree (220611,
221935, 222752; nine scenarios each, no warnings), the six macOS README and website images were
retaken through the explicit capture class (now with a Voice Design and Settings capture) and the
first capture at a 720 pt window exposed two narrow-window defects the lanes never see, both
fixed: the Studio chips now wrap through MacChipFlow instead of pushing the canvas past the
viewport, and the Settings package label keeps its width over the badge. The release QA doc gained
an attended walk of the converged screens. The plan is archived complete; CONV-20 (device
re-verification of the frozen iOS behavior) and CONV-21 (the toolchain bump) moved to
`release-first-3-0-2026-09`, which is the primary plan again and remains parked on the phone for
its release path; phone-free work continues in the other plans.
Its lanes needed three fixes on the way (an NSTextView bridge answering an infinite proposal with
its document height, then the screen identifier erasing the dock identifiers) and passed on
62279fc7 (localization 183823-bca6adf5, smoke 184118-afaded1b 7/7, perf 185131-61165de6, custom
benchmark 185941-08c5a2e8); CONV-15 is closed.
The maintainer consented to the Step B lanes for every screen commit; they run one at a time as
each commit lands. On the Saved Voices commit all four passed and closed CONV-11, CONV-12 and
CONV-13: localization 162652-a093f4a3, smoke 162950-777019e3 (7/7), perf 164002-0177f946 (nine
scenarios) and the short clone benchmark 164814-b6dd6b2d.

### Harness stabilization first (September 13, night)

The four-day flow that rebuilt the workflow, the CI, the benchmark harness, the audio QC and the
played-audio capture left the work ledger behind it, so the roadmap was straightened in four
commits. `harness-stabilization-2026-09` is now the primary plan: it absorbs the two plans opened
on September 13 (MV and PC ids kept), adds HS-01 for the TSan characterization due 2026-09-30, and
holds the two decisions that gate the next release work, MV-07 (the fp16 speech tokenizer's opening
burst on streamed clone takes) and PC-03 (the 1.8 s gap between playback scheduling and audible
output). `release-first-3-0-2026-09` stays active and secondary. Four duplicates retired as
superseded (F-17 into RF-08, RF-11 into ICA-04 with RF-12 now behind ICA-05, ICA-20 into AV-13,
MV-02 into MV-01), MV-05 waits on MV-06's judge, AV-09's controllable-clock clause became AV-15,
ICA-06's gate is re-scoped to a reproduction by request identity, RF-09 is re-gated on the freeze
commit behind RF-13, and twenty-four items that only wait for the paired iPhone, a signed candidate
or an external decision are parked with the exact trigger that wakes them. The validator now
refuses the drift that hid all of this: every source path must exist, notes stop at 1200
characters, done items must be archived, planned work behind parked work is surfaced, and the
in-flight staleness window is 14 days.

**Harness plan, September 14.** MV-03 (a dispatch no longer cancels the push run), MV-01 (one
macOS arena per optimization level; the warm CI lane compiles two files), MV-04 (the whole
contract gate runs on Linux; config and scripts changes no longer reach the macOS lane), PC-03 and
PC-02 are done. The 1.8 s "gap" was the UI driver: XCUITest takes about 1.7 s to resolve the Generate
button, and measured from the app's own submit clock audio reaches the tap 27 to 163 ms after
scheduling on three consecutive canonical runs. The played-audio comparison is a gate now
(coverage 0.98, residual −25 dBFS, no dropout, 500 ms), proven by a gated canonical run and a smoke
run that captures too. Open in the plan: MV-06 (the second judge's dependency), MV-05 behind it,
and HS-01 (TSan by 2026-09-30).

**fp32 codec restored, September 14.** MV-07 is decided: rather than patch the streaming decoder,
the maintainer chose the codec 2.4.0 shipped. The fp32 speech tokenizer went back to all six
Hugging Face repos and everything is re-pinned as artifactVersion 2026.09.14.1 (each artifact grows
by 341 MB; installed models relink the fp32 blob already in the component store, no download).
The same 28-seed clone-short matrix on the re-pinned model shows no burst inside the first 50 ms
and no QC v7 onset warning, matching the fp32 reference exactly; the plosive-onset cluster stays
(MV-05). The gate-bench baseline is re-saved under the fp32 codec.

**Second machine judge, September 14.** MV-06 is done on the torch route the DistilHuBERT candidate
already established: NISQA v2 is a pinned evaluator candidate (checkpoint digest, upstream commit,
runtime versions in the registry, a venv under the owned model root that the prepare step verifies)
and the delivery cascade's `--clip-quality-config` scores both sides of every pair on the original
24 kHz bytes. The warn floor is corpus-calibrated (tenth percentile of 54 neutral PASS takes, 3.81);
a take below it abstains the pair and never rejects, so native QC keeps the decision. Two-run
qualification passed.

**Onset cluster judged, September 14.** MV-05 closes with a judgement rather than a fix. The NISQA
judge with a 300 ms onset window, run over 88 fixed-seed clone short takes through the new
`scripts/clip_quality_screen.py`, cannot tell the 11 cluster takes from the 52 clean ones at clip
level (AUC 0.54) and only modestly on the onset window (AUC 0.71, overlapping ranges). The cluster
is recorded as model-intrinsic with a minor perceptual footprint, QC v7 keeps counting it, and the
reproduction (seed 55) passes the clip-quality warn floor.

**TSan promoted, September 14.** HS-01 closes the harness plan: three consecutive scheduled nightly
passes (Sept 12, 13, 14; 654 core and 19 transport tests, zero races) are recorded in the policy and
the maintainer chose blocking on push CI. `ci.yml` now runs the sanitizer subset as `macos-tsan`
with the Swift lane inside `CI required`, the nightly keeps a cold run, and the policy validator
refuses a blocking status without the recorded passes and a dated decision. Every item of
`harness-stabilization-2026-09` is done; `release-first-3-0-2026-09` is the primary plan again and
resumes at RF-13 → RF-09.

**RF-13 source side, September 14 (phone-free).** The outward-export inventory is audited and
written down (app guide): every path that lets audio leave the iOS app goes through the one gate
with the output's recorded mode, recovery surfaces stay free by policy, and generated output never
reaches the Files-visible Documents folder. The repository invariants now pin that boundary over
every source root the iOS app compiles, the saved-outputs folder copy takes an injected policy
with host tests proving a locked Design clip never leaves the app, and a read-only IAP audit found
no defect. RF-13 and RF-09 are parked on the paired iPhone for the offline, remaining-surface and
sandbox gates, and the freeze-dependent chain behind them (ICA-04, ICA-05, RF-12) carries the same
trigger, so the release plan has no open item until a device window. Phone-free work that remains
open elsewhere: F-16, F-25 and F-26 (engineering review), DP-28, DP-29 and DP-31 (delivery prompting),
AV-07, AV-13 and AV-15 (autonomous validation), ISU-4 and ISU-5 (iOS settings), ASR-02, ASR-04 and
ASR-10 (App Store readiness).

**Doubled text in UI-lane screenshots explained, September 14 to 15.** The maintainer's photos of "VOCELLO
VOCELLO" and doubled French menu titles came from the pseudo-localized readiness journey (Foundation's
double-length and untranslated-string arguments, launched by the first smoke test and the localization
lane; process-scoped, never persisted). The stress exposed a real fragility: the saved-voice row chose
its layout from its own rendered width and locked into a collapsed column once long titles overflowed
the action cluster. AV-16 (done) fixed the row from container and action widths, gave chips and badges
line limits, made the journey assert single-line rows and in-window controls, and migrated the macOS
interface copy into the String Catalog with French in four batches: the view literals first, then the
model-driven labels (sidebar, variants, statuses, readiness, batch, alerts) once a French-system Mac
showed a mixed-language app. `MacInterfaceText` owns 379 `vocello.mac.` entries; the literal baseline
holds only the 13 iOS records; the localization lane passed on every batch.

Critical path (the harness plan completed on September 14): RF-13 → RF-09 freeze → ICA-04 → ICA-05
→ RF-12, and ISU-4's physical walk rides the next device window.

### Machinery validation (September 12 to 13)

The maintainer asked to prove that the refreshed development machinery works as intended and
optimally. Three read-only investigations set the baseline (mechanism checklist over the 41
commits, CI step timings of the previous 36 hours, local readiness), then a five-phase campaign
repaired what they found and ran every lane once with timings. The full ledger of commands, exit
codes and verdict lines is the session's campaign log; this section keeps the outcomes.

**Repairs before measuring (`22ab4c42`…`643891b8`).** Push CI routes only its own inputs
(`ci.yml`, `.github/actions/**`, the classifier) to every native lane, the website base advances
when the lane is skipped inside a green run, and inert paths route nowhere; the DerivedData caches
are keyed by ISO week and saved only on an exact miss with the package checkout in its own entry;
the iOS lane compiles at `-Onone`; every `-Onone` build in the macOS arena shares one settings set;
`config/toolchain.json` pins numpy 2.4.6 like the whisper adapter; the hook wiring, the single test
root and `scripts/lib/shared.sh` have tests. Phase 1 evidence: 1473 Python tests in 87 s,
`scripts/dev.sh ci` in 318 s, every negative probe and scratch-mirror probe behaved as claimed.

**Defects the heavy lanes exposed, all fixed the same day.** `Duration.seconds` divided attoseconds
by 1e15, so every CLI-side wall figure since the RTF commit carried its fraction ×1000 (`6ab8c461`,
with `TimingExtensionsTests`); the gate bench judged its single cold take and mapped an invalid
baseline to "REGRESSION" (`b1824091`); the sampled footprint peak swings by hundreds of MB between
identical runs, so it now uses the baseline's own dispersion like `rtf` (`b88d6d03`); the language
publisher rejected mixed-language runs on the per-row decode digest (`acba7581`); the history
validator had never met a negative-control take with metrics (`5ca95a73`); it demanded an RTF
declaration from kinds that publish no RTF (`ee97e92c`); the shell lint failed on forty
pre-existing warnings (`a24cc3f8`); a flaky replay assertion expected an empty cache that MLX refills from its
scheduler thread (`5619004c`); a stale owned-package inventory and a stale chart pin each cost one
red push. Gate bench, language, UI benchmark and perf lanes each needed two to four runs to reach a
clean PASS; no lane was retried without a code change.

**Records published (all schema 3, clean tree, receipt-bound `-O`, `run.rtfDefinition`).**
Gate bench `mac-gate-bench-20260912-234613-c8f8a8c6`; language
`mac-lang-bench-20260913-000655-546b90cf` and `…-180416-c86db379` (whisper producer 851 / 852 MB
peak RSS, clean exit, no swap growth: AV-08's macOS host runs); UI benchmark
`macos-xcui-benchmark-20260913-170946-488a9ed0` and `…-181112-6cb80773`; CLI Speed matrix
`macos-engine-20260913-180702-42b26142`; perf `macos-xcui-perf-20260913-174907-79e014f2`. The
README and website charts pin the newest canonical UI record (Built-in Voice 0.71/0.59/0.57, Voice
Design 0.65/0.56/0.53, Voice Cloning 0.75/0.61/0.55 for short/medium/long). TSan passed cold locally
in 144 s and in the nightly in 386 s (was 646 s); smoke and localization lanes passed.

**CLI versus UI, same host, back to back.** Engine-measured RTF agrees within 0.04 per cell across
the two drivers. The UI adds 60 to 120 ms to the first chunk through XPC and about 0.3 to the
submit-to-completed span divided by audio on short scripts, nothing on long ones: a fixed
per-request latency, not a throughput loss. Footprints sit within run-to-run noise.

**CI before and after.** Push macOS lane 738 to 1100 s before; 501 to 582 s warm after (contract
gate 55 to 78 s, deterministic tests 332 to 419 s, CLI identity 28 to 48 s, restore 45 to 68 s); cold
dispatch 911 s. iOS 433 to 478 s before; 120 to 167 s warm after (compile 83 to 120 s at `-Onone`),
325 to 359 s cold. Python 208 s before, 102 to 109 s after on pushes. The store holds one weekly
entry per platform plus the package checkout (7.6 GiB after deleting the per-commit entries). The
warm macOS test step still recompiles the package graph after an exact cache hit (927 Swift files,
"Base directory status changed. Regenerating..."): follow-up MV-01. A manual dispatch cancels the
in-flight push run on the same ref: MV-03.

**Audio QC blind spot (September 13).** The maintainer heard the cloned voice break for the first
moments of the UI benchmark; every gate had passed the takes. Direct measurement found a 20 ms
burst of quarter-scale steps at the "tr" onset of eight of nine short clone takes across the UI runs
and the headless CLI matrix, seed-dependent and more frequent for consecutive in-process takes;
not the first streamed chunk seam, not the limiter, not the Article 50 mark (seeded on/off onsets
identical). Telemetry showed no underruns and the QC's click counter only sees steps the slew
limiter clamps. `0f16f35c` makes every take record `stepBurstPeakCount` and `stepBurstPeakStartMS`;
the perceptual judgement still needs a corpus (NISQA rates the affected takes no worse than clean
ones): MV-05 holds the reproduction, MV-06 the clip-level screen. The maintainer's rule stands: the
QC harness exists so nobody has to listen; the next step is PC-01, a Core Audio process tap in the
UI benchmark lane that captures what the app actually plays, mutes the physical output, and
compares the played audio with the published WAV.

**Played-audio capture landed (September 13, evening).** PC-01 closed with the first canonical
captured record, `macos-xcui-benchmark-20260913-220529-a1103a3a` (reduced Custom/short matrix, two
takes captured, coverage 1.0, no dropouts, residual −53 and −56 dBFS, no step burst, speakers silent
while tapped). Getting there took five runs and three facts nobody had written down: a freshly
relaunched app has no Core Audio process object until its first playback, so the runner attaches
on the HAL's process-list change (`f06de0a8`); Xcode signs the generated XCTest runner sandboxed,
which silently blocked both the tap and every capture file, and an ad hoc System Audio Recording
grant binds to one code hash, so the lane now re-signs the runner unsandboxed with the stable
Apple Development identity and the maintainer added it once by hand, because a process tap never
prompts on this macOS (`99081685`); and the capture WAV starts at the first delivered buffer, not at
arming (`28ef9156`, which also redefined `playback.capture.misaligned` against the app's own
`playbackScheduledMS`). The capture's first finding is PC-03: on both takes the audible onset trails
the app's playback-scheduled timestamp by about 1.8 s, on final-file playback, with the tap's first
buffer arriving 1.3 s after scheduling. The app's timeline stops at scheduling; the tap is the only
witness of what reaches the listener, and the warning stays warn-only until the cause is known.

**Clone onset glitch, root cause split (September 13, night).** With the capture in place the
maintainer asked whether the onset glitch had a root cause. The clone capture lane (record
`macos-xcui-benchmark-20260913-223436-256bda25`) showed the app plays the published file
faithfully (residual −55 dBFS, no dropouts), so the defect is in the file. A scratch A/B with two
data directories differing only in the speech tokenizer weights (the fp16 codec promoted in
`76bd6f3b` five hours after 2.4.0 shipped, versus the fp32 codec 2.4.0 carried; both blobs are still in
the local component store) over 28 fixed seeds, plus the 2.4.0 CLI built from its tag and run on the
fp32 codec, separated two phenomena. The 150 to 250 ms plosive-onset cluster the QC first measured is
in 19 of 28 fp16 takes and 18 of 28 fp32 takes, and the 2.4.0 binary renders the fp32 takes
sample-identically: model-intrinsic, present in 2.4.0, not a regression (MV-05 keeps the open
perceptual question). The regression is a burst inside the first 50 ms: 4 of 28 fp16 takes and 0 of
28 fp32, one of them at full scale, the take opening with broadband garbage from sample 0 where
fp32, 2.4.0 and the fp16 non-streaming decode all open in digital silence. It needs both the fp16
codec and the streaming decoder's first chunk (MV-07). The text tokenizer bump and the model-code
changes since August produce identical waveforms and are cleared. QC algorithm v7 adds the
warn-only `onset_step_burst` flag so the harness names this opening burst on every future take.

**Deferred.** The iPhone lanes (AV-14's iOS halves, AV-08's two-family record): CoreDevice reported
the paired phone unavailable and `ui_test.sh ios benchmark` aborted before its build as designed.

### Documentation currency pass (September 12)

After the workflow rebuild the maintainer asked whether the documentation, READMEs, rules and
CLAUDE.md still matched it. A mechanical pass (every back-ticked path in the 68 living documents
checked for existence, retired vocabulary counted) and a read-only audit workflow (ten slice auditors
reading every line, an independent verifier per slice, one cross-document consistency critic) found
217 verified discrepancies in 55 files (13 high, 73 medium, 131 low) and 58 operational facts no
living document stated. Maintainer decisions: document the main-only reality rather than add a
pull-request lane; make `benchmarks/OPTIMIZATION.md` historical with a `decodeSpeedupX` banner; fill
the gaps in their owning documents. Five commits (`9392f5c9`, `1e3dcbdd`, `e7824453`, `e34f5a66`, `db152b5e`) apply
the corrections by area: entry points and permissions; workflow, testing and release guides;
benchmarks, telemetry and CLI; audio QC, delivery and the Qwen guides; architecture, engine guides,
decisions and ledgers. Recurrent findings were the retired verbs and receipts, `python3 -m unittest`
as the test route, schema v2 named as current, pre-cutover speedups labelled RTF, pull-request
vocabulary, and pointers to deleted documents or rules. Reported and left in code: the
`sensevoice` family id in `scripts/lib/language_metrics.py` that no document names, six archive
evidence anchors to the deleted September 6 history, and two surviving experiment branches.

A follow-up removed the last patch-stack vocabulary around the owned runtime, which the maintainer
noticed while the pass ran: the maintenance guide is now `docs/reference/qwen3-core-maintenance.md`,
the semantic-delta ledger `Packages/VocelloQwen3Core/SEMANTIC_DELTAS.json` (schema 3, key `deltas`),
the component manifest `RUNTIME_MANIFEST.json`, and the validator `scripts/qwen3_core_contract.py`
with its test; the Mimi guide's "vendored" heading reads "owned". The relocation inventory, the
benchmark records and the dated ADR keep the historical names, and the upstream module names behind
the `VocelloQwen3Core` facade stay as compatibility identities by design.

### Workflow and harness scar removal (September 12)

The maintainer asked whether other parts of the development workflow or the remaining test harnesses
still carried the scars of earlier coding agents. Three read-only audits (workflow scripts, CI and
hooks; Python and Swift harnesses; docs and configs) found the load-bearing loop sound and every layer
carrying retired machinery that gated nothing or the wrong thing. Maintainer decisions: keep only the
release-time quality-promotion validation and fold path routing into its contract; move the product
invariants out of the source-text tests and delete every text assertion; delete the unlinked dated
docs and mark the linked ones historical; consolidate the duplicated helpers.

Five commits. `cb786c92` (+ `0327121d`) retired the evidence-impact router, the closed convergence
gate and characterization fixtures, five fp16-decoder research scripts, four reader-less configs and
the tracked third-party critique; `config/quality-promotion-contract.json` now carries
`promotionRouting` and `quality_promotion.py classify` replaces the deleted module. `72dae52c` moves
the monetization, export-boundary, StoreKit-fixture, clone-consent and candidate-acceptance invariants
into `scripts/repo_invariants.sh`, binds the StoreKit fixture to `IOSExportAccessPolicy` in a Swift
test, teaches `localization_contract.py` and `supply_chain_contract.py` the checks that had lived in
tests, moves three device helpers into `scripts/lib/ios_device_state.sh`, then deletes three test
modules and the text assertions in ten more (ICA-21, closed the same
day, see below). `4c0e07ff` removes the `plan|focused|checkpoint` shim, makes `regenerate_project.sh` fast by
default (`--verify` runs the gate), restores `dev.sh ci` to exactly the push-CI command list, derives
the CI cache keys from `config/toolchain.json` and corrects the skills, agents and hook wording.
`40d03135` adds `scripts/lib/jsonio.py` (load, canonical and pretty bytes, digests, atomic writes as
keyword options; every persisted digest re-validated byte-identical) and moves the lane scripts'
shared shell helpers into `scripts/lib/shared.sh`. `cb90ea89` rewrites CONTRIBUTING and the testing
runbook to the current loop, deletes three unlinked dated docs, marks six dated docs historical,
removes the 32 "removed 2026-09-11" stubs and corrects the release-QA, benchmarks and privacy docs.

Fixed afterwards: `test_delivery_experiment_runner.py::test_screen_summary_requires_one_factor_and_keeps_failures_in_denominator`
failed once under xdist with "another generator or heavy delivery analyzer is already active"
because `run_execution_plan` defaulted `lock_root` to the real `build/cache/delivery-analysis`
lock and five test calls omitted it. `lock_root` is now a required keyword: the runner CLI and
`delivery_prompt_remediation.py execute-stage` pass the shared `DEFAULT_SERIAL_LOCK_ROOT`
explicitly, every test passes a private temporary root, and an omitted root is a `TypeError`.

ICA-21 closed the same day. Both owning classes are `@MainActor` types in `Sources/iOS` that no
unit-test target compiles, so the orders moved into `Sources/iOSSupport` after the
`CriticalMemoryReliefExecutor` precedent. `IOSModelDownloadCancellationSequence` owns the
cancellation order (durable intent before any task cancellation, raced-install rollback after the
drain, the durable tombstone before staging removal or the terminal publish, every failed persist
returning first); binding each closure to the right side effect stays a call-site review item. `IOSGenerationOwnershipAuthority` owns generation admission, the completion that
stays retained while a critical-memory action is in flight, the post-barrier release, the
one-scope critical claim and the two-step completion (scope returned, idle published, claim
released); `CriticalMemoryFullUnloadSequence` orders the awaited unload, its event and the single
activity clear. `IOSModelDownloadCoordinator.cancel` and `TTSEngineStore` drive them with
unchanged statement order, events and early returns. Seventeen tests in `Tests/VocelloiOSLogicTests`
cover the orders; the new files joined both test targets and the promotion routing classes.
Adversarial review surfaced three pre-existing behaviours, recorded here and not changed by the
refactor: cancelling a queued download stops the diagnostics heartbeat of another model's active
transfer; `delete(model:)` reports a raced-install rollback failure with the storage-persistence
message; a generation that completes while a critical action is in flight, followed by a failed
cancellation inside that action, leaves the scope held until a user cancel.

### Audio and delivery QC streamlining (September 12)

The maintainer asked whether the audio and voice-delivery QC harness could be improved and
streamlined for the 8 GB M2 Mac mini. Three read-only audits (in-process Swift QC, the 46-script
delivery harness, the speech-recognition lanes) found the load-bearing core sound: thresholds live once
in Swift and judge the published bytes, extraction is NumPy-only with a bounded working set, holdouts
are frozen, and every heavy step runs after the engine has exited. The cost was elsewhere: fail-open
edges, a single Apple Speech family behind every language verdict (the Mac transcribed nothing), the
same logic copied three times, 2,784 lines of a listening lane the September 6 decision had retired,
and ~260 interpreter launches per language run. Maintainer decisions: delete the listening lane (keep
the schema-1 reader), remove the dead scaffolding, build the second recognizer family now with
`mlx-whisper` and a pinned `whisper-small` model.

Four commits: `1f0b1c9c` closes the fail-open edges (published-WAV format assertion, a streaming
continuity gate that judges the channel it is handed, unknown finish reasons and missing QC fail the
hint gate, the macOS language lane is seeded, the separability null defaults to 1,000 iterations, the
marking gate always runs, the language negative control must fail, run-level counts leave the takes).
`90152cb6` adds `scripts/lib/language_metrics.py` (one tokenizer, edit distance, locale table,
thresholds and family-consensus rule) and `scripts/independent_asr.py`: a manifest of digest-bound
rows, refused unless the generator has exited, one supervised subprocess that loads the pinned
whisper-small MLX model once, cached under audio, model, runtime and per-language decode identity.
The publisher gained `--output-gate independent` and `--recognitions`; macOS language records are now
`focused` single-family (`families: ["whisper"]`), iOS records require the Apple Speech and whisper
families to agree. A two-clip smoke on local Japanese takes measured 0.85 GB peak RSS, 2 to 4 s wall,
language detected at 0.996 and CER 0.062 / 0.156 against the corpus script. `053a7dc7` deduplicates
the audio-QC take mapping (`scripts/lib/audio_qc.py`), moves the prosody-effect and arousal weights
into `prosody_profile.py`, merges the two `AudioQualityGate.swift` copies into `SharedSupport`,
removes producer-less registry types, gives the analysis cache `prune --keep-newest N`, collapses the
iOS per-take extractions to one interpreter, and deletes 22 files (listening lane, closed-fixture
checkers, cadence contract triad, adherence bench, ICU diagnostic; 6,533 lines). This commit adds
`require_quiet_host` to every timing lane (load within twice the cores, no kernel memory pressure).

Consent-bound follow-ups are on the roadmap: AV-08 (two clean 8 GB qualification runs of the whisper
producer, then the first two-family iOS records), AV-14 item (5) (the first macOS
`lang-bench --subset quick` under the producer) and AV-07 (click-detector recalibration against the
reference base, where 3 of 45 professional recordings fail on `clicks`).

### Benchmark harness and XCUITest review (September 11 to 12)

Three read-only audits of the XCUITest suites (20 files, 7,747 lines), the benchmark harness
(~18k lines of scripts) and the 291 published records answered the maintainer's question "is the
benchmarking accurate, and does it cover CLI- and UI-driven runs on both platforms?" with: the harness
exists on every axis and its design is sound (no clocks in the UI tests, monotonic in-app telemetry,
three-layer authority on macOS, uptime-paired memory, hash-bound `-O` provenance on the macOS CLI), but
the published numbers were not accurate. Two RTF definitions shared one key (decode-loop speedup in UI
records, end-to-end audio/wall in CLI records, 10 to 28 % apart), bench wall time came from `Date()`,
iOS optimization labels were literals, and the gate bench judged single takes at a flat 5 % without
looking at host load. The maintainer decided to adopt the industry-standard RTF from now on.

Commits so far: `458a7410` makes `rtf` the standard real-time factor (engine request wall ÷ audio,
lower is faster) on every surface, derived from the engine's monotonic stage recorder as
`requestWallSeconds` / `realTimeFactor`; the decode speedup survives as `decodeSpeedupX`, UI records add
`rtfAppEndToEnd`, records declare `run.rtfDefinition`, legacy records are never rewritten and render a
derived `~` value, comparison lineages never mix, the README and website charts moved to the newest
canonical record (`0b234262`) with generated alt text and a stale-pin check. `7c2f9af2` binds every
optimization label to a build receipt that names the executable and its digest
(`scripts/lib/build_provenance.py`), makes `ios_device.sh bench` build `-O` and poll only the completion
sentinel, stamps the CLI's own digest into `bench-results.json`, moves the gate bench to three warm takes
compared by median with MAD-widened thresholds, an inconclusive verdict (exit 3) under host load or heat,
OS/Xcode identity in the baseline, and publishes full-matrix engine runs as canonical. The following
commits fix the UI perf lane (fractional window attribution, refresh fail-closed, contract-owned
designations, macOS environment row, marker flush, readiness-free generation windows, sleep hold on
every lane, iOS cell-length and per-mode seed checks) and the runner/test hygiene items from the audit.

Open follow-ups are roadmap items AV-13 (macOS coverage lanes), ICA-20 (iOS coverage and the last
English-label lookups) and AV-14 (consent-bound re-baseline runs: three-take gate baseline, one canonical
macOS and iOS benchmark run and one perf run per platform under the new definition, then repin the
charts). The first push's macOS CI job failed once in
`Qwen3DecoderPartitionTests.testReplayCachePolicyPreservesBothPartitionsAndBoundsObservations` (an MLX
cache-bytes assertion in the owned package, untouched by the change) and passed on the next commit;
AV-14 carries the watch.

### Lean verification migration (September 11)

Seven commits replaced the gate-and-governance machinery the Codex and GPT phases left behind. Local
verification is `scripts/dev.sh check` (lint, contracts, selected tests, the native lanes the dirty
tree touches) and nothing blocks a commit except a 15-second lint (`scripts/hooks/commit_lint.sh`:
branch `main`, clean whitespace, no private path or credential); CI on `main` is the gate. CI routes
pushes by `scripts/ci/classify_changes.py`, restores the persistent DerivedData caches on the macOS
jobs, runs the Python suite on Linux and the darwin-only modules inside the macOS gate; `security.yml`
runs weekly and inside the release workflow; `nightly.yml` owns TSan, the complete Python suite and
cold compiles. The Python suite runs under pytest with `-n auto` in about 90 seconds (300 serial
before), with `research` and `darwin_only` lanes by marker. Deleted: the checkpoint receipt and its
fingerprint, `check_test_workflows.sh`, the documentation contract, doc metadata pins, surface
coverage and its byte budget, the project-health and Python-test contracts, the 254-path existence
list, the workflow token assertions, seven governance test modules, the 53 pinned historical
documents (release notes and decisions stay), and the Codex-era instruction sprawl. `CLAUDE.md` is
about 9 KB with two rules (`native.md`, `release.md`) plus `website/CLAUDE.md`. `config/roadmap.json`
now holds only open work (finished items and completed plans moved to `config/roadmap-archive.json`,
notes capped at 1,200 characters); `docs/ROADMAP.md` lists open items with their blockers.

Product invariants kept an executable check throughout: `scripts/repo_invariants.sh` (exact greps),
`scripts/privacy_scan.py`, `scripts/public_facts_contract.py`, and the product contracts in
`./scripts/check_project_inputs.sh`. The quality additions landed in the seventh commit: owned Xcode
targets compile with warnings as errors (five real warnings fixed, one of them visible only at `-O`; the
nightly lane now also compiles the macOS app optimized), flaky tests have a 30-day quarantine
(`config/test-quarantine.json`), and `scripts/dev.sh lint` runs the low-noise SwiftLint rules in
`.swiftlint.yml` on changed files. swift-format was measured and not adopted: with a four-space
configuration it still rewrote 310 files and 23,500 lines of a codebase that already follows one
consistent Xcode style, for no correctness gain. Next measurement: the warm-cache time of the macOS
CI job on the second push after the cache save.

### Claude Code adoption (September 11)

Claude Code replaced Codex as the development environment in six checkpointed commits on `main`
(roadmap plan `claude-code-adoption-2026-09`, CCA-01 to CCA-12, all done and the plan complete). The since-retired `AGENTS.md` became a
177-line `CLAUDE.md`; the five domain rules moved to path-scoped `.claude/rules/` with a new
always-loaded `claude-tooling.md`; the nested website guidance became `website/CLAUDE.md`. Every gate that
named the old files was rewired in the same commit, the Codex hook config and session-storage tooling
were retired (runbook pinned historical), and a configuration contract validated the repository-owned
`.claude/` files inside the project gate (retired on September 11 in favour of the hook behaviour tests). `.claude/settings.json` wires the commit
lint plus `policy_guard.sh` (Simulator destinations, whole-cache deletion, force pushes, new
branches, `project.pbxproj` writes), `generated_file_guard.sh` (refuses hand edits of generated and
frozen files), the `project.yml` regeneration reminder and the session-start script;
`scripts/dev.sh status` reports branch, dirty paths, the lanes `check` would run and the primary
plan's open items. Four project skills (`/ios-lane`, `/macos-ui-lane`, `/device-diagnostics`,
`/release-evidence`) and two read-mostly subagents (`swift-review`, `xcresult-triage`) route to the
existing scripts and documents; device, model and release lanes stay user-invoked only.

Two harness findings were recorded with evidence rather than assumed. The checkpoint receipt (since
deleted) had stopped binding PATH membership (`local-v3`) because the hook environment lacks the plugin
`bin` entries the tool shell appends, which made a fresh receipt read as stale. For CCA-09 the direct `xcrun xctest` runner stays:
bounded `xcodebuild test-without-building` trials on the same xctestrun passed one class in 4 s but
took 95 s for the full bundles and failed two tests that pass under the direct runner on every
checkpoint (`CLIExecutionTests.testRealSignalsReachNativeSupervisorAndAwaitCleanup` at 31.4 s and
`PreparedVoiceRepositoryTests.testTwoNativeProcessesExcludePreparationReplacementAndDeletion` at
45.2 s, both real native-process boundaries timing out under the xcodebuild test host). The lane now
writes `core`, `transport` and `runtime` `test-results.json` summaries through the shared
`scripts/lib/xctest_summary.py`, and `scripts/macos_test.sh test --coverage` is an opt-in,
non-blocking llvm-cov export. The Python test roots are one root (`scripts/tests/`); the
2026-08-21 omitted-tests finding was already closed, and pytest collects every module under `scripts/tests/`
(the 302 s unittest discovery figure recorded then is superseded by the ~90 s pytest run).

Follow-ups scheduled, not started (the TSan characterization closed as HS-01 on 2026-09-14): an `axiom:iap-auditor` pass over the iOS export unlock before RF-13; an
`axiom:accessibility-auditor` pass for ISU-4; the optional `swift-lsp` build-server setup. Product
critical path is unchanged: ISU-4 localization qualification and RF-13 remain next; the adoption track
is closed.

Later the same day the follow-up audits ran through Axiom and CI on `main` was repaired in two steps: the
first push fixed a gitignored path quoted in prose and a PyYAML import the runner cannot satisfy (`main`
had been red since the previous day); that run still failed on a French plural test that depended on the
process locale, fixed in `2f06f21a` by binding formatted copy to the interface locale. The StoreKit audit found the export unlock clean against every invariant
(one low note on generic error copy). The concurrency audit found no unregistered unsafe declaration and no
confirmed race; the registry text for the engine service host now describes the per-method MainActor
discipline the code really uses, the performance gate model is class-isolated (F-24), and the unchecked
Sendable budget sits at its ceiling. The TSan lane failure was not a race: every helper xctest child spawned
from the instrumented parent aborts at load on this toolchain (three launch variants tried), and the bundle
then crashed on an unguarded index; the two helper-process tests now skip under the sanitizer with the
exclusion recorded, the lane runs to completion with zero reports, and the scheduled workflow gains the
pinned numpy its toolchain step verifies (AV-12). The accessibility audit named a credible root cause for
ISU-4: the tab dock had no Dynamic Type ceiling and grew into the scroll-gesture zone at AX-XXXL; the dock
is now capped at the first accessibility size, the compact toggles regain the switch role, the tab icon is
hidden from VoiceOver and the App Language rows adapt their layout (ISU-5, source landed; the physical
English/French AX-XXXL and pseudo-localization walks remain the explicit qualification step).

### Roadmap reconciliation (September 11)

`config/roadmap.json` was compared item by item against tree `2f06f21a` by three read-only audits.
The ledger is structurally sound and every evidence and source path resolves, but about a third of the
open items were inaccurate. What changed, all in the ledger and active docs, no product code:

- Blocker topology was understated: eleven items were in flight although their only open clause is
  packaged, frozen-source or device evidence owned by a parked or unfrozen owner. They are now
  `planned` with the owner in `blockedBy` (F-05/15/18/20/21/23 behind RF-10, F-17 behind RF-08,
  ICA-04 behind RF-09, ICA-05 behind ICA-04, ISR-06 behind ISR-04, DP-32 behind DP-31). RF-11 no
  longer lists the done RF-07. Of the items still in flight, source work can move today on roughly a
  dozen; the rest wait for RF-09's freeze or a device window.
- F-19 (attempt-scoped terminal ownership) and F-22 (cross-process Saved Voice transactions) had fully
  discharged gates and are done. ASR-04 was `planned` with shipped source and is in flight.
- RF-06's title and gate now say what the September 7 amendment decided: known limitation, causal
  research deferred, incidence measured by the frozen campaign.
- Stale notes were corrected on F-16 (iOS long-form acceptance passed September 7), ISR-04 and VLR-07
  (runner, schema and classifier changed after their last revalidation), ISU-4 (next action is the
  post-ISU-5 physical walk), ICA-04 (five control families added after the frozen snapshot), AV-07
  (empty approved external catalog digests block the licensed-reference pilot), AV-08 and DP-29 (the
  September 2 language run is exploratory, partial and dirty-source with every cell
  `passedWithWarnings`, no Korean), AV-09 (the controllable-clock clause is untouched). ICA-06 carries a
  maintainer-visible re-scope proposal because seed-exact reproduction is unreachable through the UI.
- Evidence anchors that resolved to "Historical only" redirect stubs were repointed at the pinned
  September 6 history, itself deleted on September 11 (`f2efacde`); those six archive anchors now
  resolve only through git history. `config/delivery-evaluator-v2-contract.json` names the
  live `polyphase-kaiser5-v2` resampler instead of the retired one. The holdout rule (now in
  `.claude/rules/release.md`) says where the holdout really comes from.
- Two code defects were filed, not fixed: F-25 (a busy Saved Voice store is fatal to engine
  initialization, untyped and unlocalized; the exact app+CLI coexistence F-22 was for) and F-26 (CLI
  `afplay` children outlive a signalled process, signal sources install after the task starts, and a
  failure coinciding with a signal is reported as cancelled). ISU-5 carries a note on the stacked
  App Language row layout to decide before the physical walk.
- The September 11 host cleanup removed every retained run bundle and diagnostics directory under
  `build/artifacts`. No run id cited in the ledger is inspectable locally and `scripts/ui_test.sh ios control-audit
  --resume` has nothing to validate; the 201-take campaign restarts from take 1 on the frozen source.

Critical path as of September 11: ISU-4's post-ISU-5 walk, RF-13, then RF-09's freeze (superseded on
September 13 by the harness-stabilization order at the top of this file).
