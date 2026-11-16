---
status: active
owner: release-qa
reviewed: 2026-11-15
summary: The step-by-step plan to remediate every finding of the 2026-11-15 project audit, in order — decisions first, then what must land before the 3.1 tag, the release sitting, the publication flip, and everything that can follow 3.1.
sourceOfTruth:
  - docs/audits/2026-11-15-project-audit.md
  - config/roadmap.json
---
# Remediation plan for the 2026-11-15 audit (RF-61)

Finding IDs (A1, T3, …) are those of [the audit](2026-11-15-project-audit.md). Every finding has a
step, the low-priority ones included.

## Status (2026-11-15, late evening, local `main`, nothing pushed)

Implemented and passing the routed check (lint, contracts, every deterministic macOS test, the CLI,
the iOS compile and the UI bundles). The release lanes have run and passed (steps 18 to 20).

| Steps | State |
|---|---|
| 1 to 13 | Done, and measured on 2026-11-15: the History stall is gone (longest frame gap 72 to 86 ms, from 873 ms). Step 7's ceilings are applied from the three runs: `enforce` names the four confirmatory scenarios other than the delivery menu and both History filters; the delivery menu keeps its ceiling, warn-only. Step 8 did not clear the delivery menu: with warms suppressed it reads 82 to 86 ms/s against September's 67 to 70, so finding A10's guess was wrong and the cause is open. |
| 14 | Done as decided on 2026-11-15, in two steps. The pin stays at Xcode 26.6: GitHub offers Xcode 27 only on a preview runner image, so D-1's move was reversed. And the toolchain difference is accepted by name: the benchmark Mac runs macOS 27.2.1, where Apple does not support Xcode 26.6, so the 3.1 promotion records are built with Xcode 27.2 and `create --accept-toolchain-difference "REASON"` writes that into the promotion record; without the option such a record is still refused. Audit finding B1 is therefore disclosed, not closed: the records prove the same source under another compiler and SDK than the release's. |
| 15 to 17 | Done. |
| 18 to 20 | Run on 2026-11-15 on the M6 with Xcode 27.2, all PASS: the UI benchmark as canonical under `cell-hash-v2`, the perf lane three times, smoke 16 of 16, `release-readiness`, `scripts/dev.sh ci` and the engine gate bench (warm median RTF 0.294 against 0.291). The run IDs are in `docs/releases/v3.1.0.md`. Step 19's charts are regenerated from the canonical record. Step 20's static audits (app, command line, security and privacy, read-only) found no release blocker; two of their findings were fixed in Swift after the UI lanes ran (the two entries under "Found while implementing"), so smoke and one perf run are owed on the final commit before the tag, and the rest are parked as BKL-76. The promotion lanes run again on the tagged commit. |
| 21 to 26 | Done on local `main`, as one set of commits before the tag: the public facts, the README and its charts, the website, the attribution, the reference documents and the release notes say 3.1. Two things remain: the screenshots that still show retired controls need a `ui_test.sh macos marketing` capture (a Mac window), and promotion now reads the previous public release from the facts file's history, because the flipped facts name the candidate itself. |
| 27 to 36 | Done, with three limits. A11 was declined: moving the Studio screens off the engine store is not mechanical and changes when state lands. Of E9, the generic unbounded `generateStream` pair stays (a protocol requirement a package test uses). Step 33 marked the actor's relief API off the shipping path and corrected the rule; the product still unloads by dropping its reference. |
| 37 | Done, unverified in the running app. The warm command-line engine's lease follows its model; the Mac app holds a lease of kind `app` while its model is loaded, refuses a model delete while another host holds a lease, and on an 8 GB Mac with nothing loaded does not start a take beside another engine; the command line finds the app by its lease, then the workspace, then the process table. Whether ssh hides the app from the workspace was not confirmed. The coordinator has no test of its own. |
| 38 | Done. |
| 39 | 39a done (result under step 39); 39b does not start. |
| 40 | Waits for three canonical benchmark runs under `cell-hash-v2`. |
| 41 | Not started: it extracts the Mac update's state machine from the 1,800-line view model that step 37 is changing, so it follows that step. |
| 42 | Done for `models`, `history`, `settings`, `batch`, `doctor` and `voices`: the handlers are in `VocelloCLICore`, with in-process tests of `models`, `history` and `doctor` over an empty data folder and two new contract examples. `voices`, `settings` and `batch` have no handler test. |
| 43 | Started: the player's live preview runs under unit test through an underrun and a pause. The take queue, the final-file hand-off and ownership are not covered. |
| 44 | Done: a take the audio check refuses is recorded (proved from its engine row), the run publishes its other takes as an exploratory record with `refusedCells`, and more than one refusal fails the lane. The benchmark lane has not run with it. The random-seed screen of the refusal rate is not built. |
| 45 | The test lane says whether the watermark parity tests ran, and the crash delta settles and counts `.hang` and `.spin` reports. The two sleeps of T12 stay: one is a window in which nothing must happen, the other ages a file's change time, which cannot be set. |
| 46 | Not started: it rewrites the release workflow and can only be proved by the release rehearsal, so it follows 3.1. |
| 47 to 49 | Done. |
| 50 | The pyright baseline went from 877 to 792; the rest is ongoing. |
| 51 to 53 | Done. `telemetry-and-benchmarking.md` is not split. |

Review notes left open (each from the Swift review of the step named; none blocks):

- Step 37: a lease can outlast or fall short of the weights after a failure (it is timed from the
  failure, the unload from the last trim); a reader can see a lease for an instant as an unknown
  host while its owner removes it; the refusal names only the command line when the other host may
  be an MCP server or another copy of the app; a renamed app bundle is missed from ssh.
- Step 38: on a case-sensitive volume `--out` refuses a different file whose path differs only by
  case from a History take; `batch --long-form` does not say where a project's joined output was
  kept when its final move failed.
- Steps 34 and 35: the guards on a clone prime and on a take cancelled by `stop()` have no test;
  the progress test pins the table, not the engine's use of it.
- Step 30: a Studio result card that shows a deleted take stays on screen.

Found while implementing, not in the audit:

- **An output-device change under a paused live preview lost the queued audio.** A stopped engine
  drops its node's queue and fires no completion, so the preview's bookkeeping waited for buffers
  that would never play and the take never handed off to its file. Fixed after the static audit
  of the release diff: a preview whose node has played is handed to the take's file at the heard
  position whether it is audible, paused or held by an underrun. Unit-tested on the fake graph;
  not checked on hardware (pause a preview, change the output, press Play).
- **A filtered History page that landed over a newer filter** showed a partial or empty list
  until the next change, when the newer filter had been answered in memory and queued no read.
  Found by the same audit and fixed: the landing queues the read.
- **A second History change during a page read** flashed a partial list; fixed in the review of
  step 1.

## How to read it

- **Order.** Steps run in number order inside a phase. Phases 1 to 3 can interleave, but all three
  finish before Phase 4.
- **Size.** S is under an hour of work, M about half a day, L a day or more. Lane time is extra.
- **Each step lists** the change, the files, the test that must fail without it, and how it is verified.
- **Rules that apply to every step.** One scoped commit naming RF-61 (or the backlog item it closes);
  `scripts/dev.sh check` before each commit; substantive Swift goes to the `vocello-swift-review`
  agent; a new Swift file needs `./scripts/regenerate_project.sh --fast`. Nothing is pushed without
  the maintainer's word.
- **UI lanes** (`ui_test.sh macos perf|benchmark|smoke`) take over the Mac. They run only in a
  window the maintainer gives, started in the background, the most failure-prone first.
- **A change that alters accepted audio** (only step 39) needs a screen whose rule is recorded first.

## Phase 0: decisions (the maintainer's, before the work they gate)

**Decided on 2026-11-15:** D-1 to D-5, each as recommended. The CI pin moves to the Xcode 27 line;
`models install` keeps removing every mode's earlier models and reports them; MCP `delete_voice`
goes behind `--allow-voice-delete`; deleting a long-form project deletes its segments, and the
confirmation says so; the benchmark records a refused take and publishes the rest. D-7 and D-8 were decided the same day, as recommended: the pause budget is measured on retained
takes before anything changes, and the release tag's signer is allow-listed. The maintainer then
asked for the whole plan to be implemented.

**D-6 is settled by the record (2026-11-15).** Each hybrid was built by
`scripts/build_hybrid_model.py` from two of Vocello's own 3.0 artifacts, with no requantization, as
its published model card says: every tensor of the 4-bit artifact, except the talker's attention
projections (`q_proj`, `k_proj`, `v_proj`, `o_proj` in its 28 layers), taken from the 8-bit one. Each
3.0 artifact is in turn mlx-community's conversion of the Qwen checkpoint at a pinned revision, with
one tensor changed (the text embedding quantized to 8 bits) and Meta's AudioSeal generator added.

| Hybrid (revision) | 4-bit parent (revision) | 8-bit parent (revision) | mlx-community bases (4-bit, 8-bit revisions) |
|---|---|---|---|
| `…-CustomVoice-hybrid-attn` (`c36e22ed`) | `PowerBeef02/…-CustomVoice-4bit` (`29c4b746`) | `…-CustomVoice-8bit` (`50c40b22`) | `f35faf19`, `41d3337e` |
| `…-VoiceDesign-hybrid-attn` (`6bcae41e`) | `…-VoiceDesign-4bit` (`62f2646e`) | `…-VoiceDesign-8bit` (`bb56faf7`) | `5c390979`, `f90d6177` |
| `…-Base-hybrid-attn` (`5af70b5c`) | `…-Base-4bit` (`47ab65f7`) | `…-Base-8bit` (`f63ea141`) | `37e955a1`, `e7dd0585` |

So the attribution policy's entry for each hybrid is incomplete, not wrong: it names the
mlx-community 4-bit base and omits the 8-bit one that supplied the attention tensors. Step 22 adds
it (the policy takes one `baseRepo` per entry today, so the entry needs a second base or a list),
and corrects two sentences that say Vocello ships "its own conversions": `hybrid-model.md` §7 and
`qwen3-tts-guide.md:93`. `redistributionDecision: pending-qualified-review` is unchanged from the
3.0 artifacts, which shipped with it; it is a standing item, not a 3.1 regression.

| # | Decision | Gates | Recommendation |
|---|---|---|---|
| D-1 | **Xcode for 3.1** (B1): move the CI pin to the 27 line, or keep 26.6 and run acceptance on it | Steps 14, 18 | Move the pin. This Mac already builds and measures on 27.2, and the nightly preview workflow already compiles on it. Keeping 26.6 means installing it here and re-measuring everything. |
| D-2 | **CLI `models install`** (C2): keep removing every mode's earlier models, or only the installed mode's | Step 3 | Keep the rule (it is your decision of 2026-11-13), but report what was removed. |
| D-3 | **MCP `delete_voice`** (C5): behind a flag, or move files to the Trash | Step 36 | Behind `--allow-voice-delete`, as `install_model` already is. |
| D-4 | **Long-form delete** (A4): deleting a project's row deletes its segments too, or keeps them and says so | Step 28 | Delete as a unit, with the confirmation saying so. |
| D-5 | **The benchmark's design** (T5): keep all-or-nothing, or record a refused take and publish the rest | Step 44 | Record and publish. It is the fallback you already accepted if a v2 seed is refused. |
| D-6 | **Hybrid attribution** (D9): which base the published models name | Step 22 | Settled from the record, below: both parents and both mlx-community bases. |
| D-7 | **Fast QC pause budget** (E4): pursue, or leave | Step 39 | Measure first (step 39a costs nothing); decide on the numbers. |
| D-8 | **Release tag signer** (B10): allow-list your key | Step 52 | Yes; one line of configuration. |

## Phase 1: product fixes before the tag

**1. History over 500 entries: one rebuild, no false "No matches" (A1). Size M.**
- Change `MacHistoryScreen.pageInputsChanged` (`Sources/Views/History/MacHistoryScreen.swift:685`):
  when `!holdsWholeArchive`, skip `recomputeFilteredItems()` and go straight to the page read.
- In `content` (`:416`), show the empty state only when no read is in flight
  (`reloadCoalescer.isReading`); keep the current rows on screen until the page lands.
- In `finishReload` (`:840`), assign `items`, `filteredItems` and `sections` in one main-actor block,
  and stop driving a second pass through `onChange(of: itemsRevision)` for a page result.
- Assign `recoverySnapshot` only when it changed (`:817`).
- Extract the decision ("filter in memory or read a page; what to show meanwhile") into a value type
  under `Sources/SharedSupport` so it is testable; list it in `project.yml` for `VocelloCoreTests`.
- Check the iPhone `HistoryScreen` for the same path and apply the same rule if it has it.
- Test: a `VocelloCoreTests` case over the extracted state: paged archive plus a query whose matches
  are outside the loaded page never yields the empty state while reading, and yields one list update.
- Verify: step 9's isolated perf scenario at 700 entries; expect the September numbers or better.

**2. `settings variation` returns as a retired setting (C1). Size S.**
- `Sources/VocelloDesktopCore/DesktopAppSettings.swift`: restore `"variation"` to `names`; `get`
  answers `expressive`; `set` accepts `expressive|balanced|consistent`, changes nothing and warns
  `variation_retired`, as `--variation` does.
- Record contract revision 2 in `config/cli-contract/v1` and `CLIEnvelope.swift`; update `cli.md:503`.
- Test: a golden list of every setting name v3.0.0's `settings list` printed; each must still resolve.

**3. `models install` reports what it removed (C2, after D-2). Size S.**
- `Sources/VocelloCLI/ModelsCommand.swift:489`: return the removed folders from
  `reclaimRetiredFolders`; add `removedRetiredFolders` to the install result and a
  `retired_folders_removed` warning; the MCP `install_model` result inherits both.
- Add the field and warning to the contract (same revision 2) with an example.
- Test: install over a fixture store holding retired folders; assert the JSON result and the warning.

**4. The 3.1 release notes say what is true (D3, D4, D12). Size S.**
- `docs/releases/v3.1.0.md`: one speed statement, from the medians: "about 9% more time than the old
  Speed model and about 27% less than Quality" (0.303 against 0.279 and 0.412).
- Add to Known limitations: a rare take that runs on in silence and is refused (under 1.5% in the
  screens; generate again); CLI takes are still not in History; which 3.0 limitations still stand
  (re-check the French and Chinese refusals against the hybrid's screens before writing); the History
  stall only if step 1 does not land.
- Add an "Upgrading from 2.x" line. Say "about 4.7 GB for three modes" beside "2.2 GB each".
- Replace the TestFlight candidate text with a short section that says the iPhone 3.1 follows and
  its What to Test text arrives with its candidate (the notes gate needs the heading).
- `docs/releases/v3.0.0.md` stays as published. In `cli.md:36`, say "a later update".
- Verify: `python3 scripts/check_release_notes.py v3.1.0`.

**5. CLI leftovers of the two-package line-up (C10). Size S.**
- `MCPTools.swift:230` (the `list_models` description), `CLIFailure.swift:89` and `:219` (hints that
  suggest `--variant speed`), `config/cli-contract/v1/examples/batch-memory-pressure.json`
  (`pro_custom_quality`). Verify: the CLI contract validator and its tests.

## Phase 2: lanes that can fail, before the tag

**6. The perf lane gets its own History (T11). Size M.**
- `Tests/VocelloMacUITests/VocelloMacPerfUITests.swift`: launch the `history-*` scenarios with an
  isolated `QWENVOICE_APP_SUPPORT_DIR` (as smoke `test10` and `test13` do), seeded to exactly 400.
- Add `history-filter-paged`: the same journey at 700 entries, so the over-500 path is measured.
- Record `archiveCount` in each scenario's setup stamp and in `ui-perf-report.json`.
- Update `docs/reference/macos-testing.md` (twelve scenarios).

**7. Performance ceilings that can fail (T1). Size M.**
- `scripts/check_macos_ui_perf.py`: accept a contract with an `enforce` list; a breach in an enforced
  scenario exits 1 (`:377` stops requiring `warnOnly` for every scenario). Add cycle markers to
  `history-filter` in the test.
- After step 6 and step 1, run the lane three times in a Mac-free window and derive ceilings with
  `--derive-thresholds` for the five confirmatory scenarios plus `history-filter`, `history-scroll`,
  `window-resize`, `sidebar-navigation-warms` and `history-filter-paged`.
- Enforce the five confirmatory scenarios and both history-filter scenarios; leave
  `generation-active` and `harness-control` exploratory.
- Tests: `scripts/tests` cases for an enforced breach (exit 1), a warn-only breach, a missing scenario.

**8. Delivery menu: measure it without a warm (A10). Size S.**
- Launch the `delivery-menu` scenario with `QWENVOICE_SUPPRESS_WARMUP`, as `sidebar-navigation` does.
- If the number returns to 67 to 70 ms/s the menu is cleared; if not, profile it in step 30.

**9. The played-audio gate fails on silence (T3). Size S.**
- `scripts/lib/playback_capture.py:307`: a `silent` status is a gate failure. When the capture was
  armed (the grant exists), every planned take must read `captured`; `unavailable` stays a warning
  only when the lane ran unarmed.
- `VocelloMacUITestCase.waitForPlaybackToFinish` (`:1084`): in non-measured lanes, assert the player
  reached "Pause" before waiting for the end; smoke `test02` asserts playback started.
- Tests: update `scripts/tests/test_playback_capture.py:164` (which pins the old behaviour) and add
  the armed-but-missing case.

**10. Underruns and continuity failures are gated (T4). Size S.**
- `scripts/check_macos_ui_bench.py:417`: fail a take with `playbackContinuityFailures > 0`. For
  `playbackUnderruns`, derive a per-cell allowance from the last three canonical runs (expected: 0)
  and fail above it. Mirror in `check_ios_ui_benchmark.py:217`, report-only there until a phone run.
- Tests: checker cases with one continuity failure and one underrun.

**11. Lanes check which tests ran (T10). Size S.**
- `scripts/lib/xctest_summary.py`: an expected-test list per lane (`config/ui-lane-tests.json`:
  smoke's sixteen journeys, perf's twelve, the benchmark's one); a missing or unexpectedly skipped
  test fails the lane. Test: a summary missing one journey fails.

**12. The stall gate cannot pass empty (T6). Size S.**
- `check_macos_ui_bench.py:1390`: on the canonical profile, fail when gated takes are fewer than the
  matrix expects. Recalibrate the limit from three benchmark runs once step 18 has produced them.

**13. Lanes stop publishing by surprise (B4). Size S.**
- `scripts/ui_test.sh`: `--no-publish` for `benchmark` and `perf` (the run keeps its artifacts,
  writes no tracked record); print "this run will publish a record" at the start otherwise.
- `.claude/settings.json`: an ask rule for `benchmark_history.py record`.

## Phase 3: release pipeline before the tag

**14. One toolchain for evidence and release (B1, after D-1). Size M, plus CI time.**
- If the pin moves: `config/toolchain.json` to the 27 line with its Swift; remove the
  toolchain-neutral shims only later; push and let CI prove the pinned build; update
  `native-engineering.md`'s "local Xcode may be newer" paragraphs.
- Either way: `scripts/quality_promotion.py:534` compares each record's `xcodeVersion` and
  `swiftVersion` with `release-metadata.txt` and refuses a mismatch; test it.
- Add to the release QA: run the Mac smoke lane against the app from the draft DMG.

**15. The release preflight finds its Python (B3). Size S.**
- `scripts/check_project_inputs.sh:44-57`: resolve the interpreter with `select_python.py` (a small
  shared `scripts/lib/python.sh` that `dev.sh` also uses). Verify:
  `./scripts/check_project_inputs.sh --local` from a shell whose `python3` has no pytest.

**16. Promotion uses the pinned `gh` (B6). Size S.**
- `.github/workflows/promote-release.yml`: add the `install_pinned_tools.sh gh` step `release.yml:715`
  has, before the attestation check. Verified by the release rehearsal workflow.

**17. The website check says what it needs (B5). Size S.**
- `scripts/development_workflow.py:484`: probe for Playwright's browsers before the step; without
  them, stop with the install command (`npx playwright install chromium webkit`) instead of running.
  `scripts/workflow_diagnostics.py`: report the browsers in `doctor`.
- ★ Installing the browsers on this Mac is a download: your word.

## Phase 4: the release sitting (a Mac-free window)

**18. Run the lanes, most failure-prone first.** Each in the background, on the release commit:
1. `scripts/ui_test.sh macos benchmark` (cell-hash-v2). A refused take stands (decision of
   2026-11-15); the fallback is step 44, not new seeds.
2. `scripts/ui_test.sh macos perf` (twice more, for step 7's ceilings and step 12's calibration).
3. `scripts/ui_test.sh macos smoke` (sixteen journeys), then review its screenshots.
4. `scripts/macos_test.sh release-readiness`, `scripts/dev.sh ci`.
5. The engine bench against the reseeded baseline (`QWENVOICE_GATE_BENCH=1 scripts/macos_test.sh gate`).
6. Static audits of the release diff; record each lane's run ID in `docs/releases/v3.1.0.md`.

**19. Performance surfaces.** `python3 scripts/generate_readme_charts.py` from the new canonical
record; `website/src/sections/Engineering.jsx` medians and provenance (step 21 fixes the label first).

**20. ★ The maintainer pushes, signs `v3.1.0`, approves the draft.** Then the seven macOS promotion
lanes and the CLI's signed-candidate qualification on the tag checkout; ★ the promote dispatch.

## Phase 5: the publication flip (one commit, with the release)

**21. The scripts that pin the old wording (D1). Size S.**
- `scripts/public_facts_contract.py:120-123`: require the one-model line-up on both README rows.
- `scripts/generate_readme_charts.py:91-93` and `scripts/readme_art/performance*.html`: label the
  pool by the model's display name, not the variant id (the hybrid's id is still `speed`).
- Their tests in `scripts/tests`.

**22. Attribution (D9, after D-6). Size S.** `config/third-party-attribution-policy.json`: the base
repositories the hybrids were actually built from, and the `redistributionDecision` for the three
shipping models; rebuild the manifest; align `hybrid-model.md` §7 and `qwen3-tts-guide.md:93`.

**23. The privacy page and privacy reference (D2, D8, C7). Size S.**
- `website/public/privacy/index.html:77`, `:121`: the automatic model update after an app update,
  and how to stop it; `:147`, `:155` say 3.1.
- `docs/reference/privacy-storage.md`: add the CLI request ledger (`<data>/cli/requests`, seven
  days), `outputs/cli`, and the engine-host leases under `~/Library/Caches`.

**24. README, website and public facts.** Work the audit's appendix checklist line by line:
`config/public-product-facts.json`; `README.md` (links, badge, model table, requirements, captions,
the hero and performance images re-rendered); `website/src` (`release.js`, `whatsnew.js`, `cli.js`,
the six sections, meta descriptions, screenshots). Replace the README hero image (D14).
Verify: the public-facts contract, `npm --prefix website run check`, a browser pass of the five pages.
★ Pushing this deploys the website: your word.

**25. Reference documents that still describe two packages (D5, D7, D13). Size M.**
- Rewrite the stale paragraphs in `ARCHITECTURE.md:1102`, `:1160-1169`; `model-delivery.md:153-157`;
  `qwen3-tts-guide.md:98-104`; `hybrid-model.md:15-25`; `macos-app-guide.md:89`, `:279`;
  `telemetry-and-benchmarking.md:401-403`, `:928-932`; `cli.md:494-502`, `:625-654`;
  `Packages/VocelloQwen3Core/README.md:26`, `:74` and `PERFORMANCE.md:95`.
- "Sixteen journeys" in `macos-app-guide.md:340`, `macos-release-qa.md:74`, `ui_test.sh:1577`.
- "For 3.0 nobody listens" becomes "for 3.x" in `CLAUDE.md`, `tooling-and-evidence.md:126`,
  `development-workflow.md:665`. Bump each document's `reviewed` date.
- Add the publication checklist to `macos-release-qa.md`.

**26. Roadmap and checkpoint (D10, D11). Size S.** After publication: close RF-61 with its evidence;
`unparkWhen` of RF-30, RF-31 and BKL-62 says 3.1; one "next" list in the checkpoint;
`app-store-listing.md` and `ios-appstore-submission.md` say 3.1.0 with the hybrid's byte counts.

## Phase 6: after 3.1

### Apps

**27. Live preview resume (A2, A3). Size M.**
- `AudioPlayerViewModel.swift:1630`: schedule the leading silence only when the node's queue is
  empty (at underrun, before new chunks are scheduled), never on a resume with audio queued.
- Establish what `AVAudioPlayerNode` reports after `pause()`; then set `livePlaybackTimeOffset` so
  the playhead never double-counts, and `retireLiveGraphKeepingHeardPosition` uses the heard position.
- Extract the scheduling order behind a small protocol over the player node; test it with a fake
  node (T9's first test): the order of buffers on resume, the playhead after pause and resume.
- Verify: a forced-underrun take through the streaming continuity screen; the smoke playback journeys.

**28. Long-form project delete (A4, after D-4). Size M.** `HistoryDeletionEngine` and
`DatabaseService.deleteOne`: delete the joined row and its segments in one transaction; the
confirmation names the segment count; the iPhone `HistoryScreen` shares it. Test: the deletion
engine over a fixture project.

**29. Player strings (A5). Size M.** Replace the English literals in `AudioPlayerViewModel` (`:258`
and the ten sites the audit lists) and `ModelManagerViewModel.swift:1125`, `:919` with typed cases
mapped through `VocelloPresentationText` and the string catalog in ten languages; extend
`scripts/localization_contract.py` to cover `Sources/SharedSupport/ViewModels`.

**30. Small app fixes (A6 to A9, A11). Size S each.**
- A6: add the playhead timer to `.common` run-loop modes (`AudioPlayerViewModel.swift:2088`).
- A7: copy on a detached task in `MacHistoryFileActions.swift:27`, `:57`; route the result to the alert.
- A8: `MacBatchGenerationSheet.swift:181`: detect the encoding, compare the extension
  case-insensitively, and say why a file was refused.
- A9: when make-room removes nothing, show the reason in the banner (`ModelManagerViewModel.swift:776`).
- A11: move `MacPlaybackFooter` and the Studio screens from the whole engine store to the scoped
  values they read. Profile the delivery menu here if step 8 did not clear it.

### Engine

**31. Sweep crash-orphaned installs (E1). Size M.** `SharedModelComponentStore`: startup reclamation
also removes `.<folder>.component-install.<uuid>`, `.component-migration.<uuid>` and `.installing.`
directories older than the grace period, under the publication lock; `installStagedRepository`
removes its moved tree when the swap throws. Test: an aged replica hard-linked to a blob is removed
and the blob reclaimed; a fresh one is kept.

**32. A Mac full unload frees the runtime caches (E2). Size S.** `NativeEngineRuntime.swift:2379`:
clear on a Mac for a hard trim and a pressure-driven full unload; keep them across idle unload.
Correct `Qwen3TTSCaches.swift:32`'s comment. Test: the cache-clear hook fires for a Mac hard trim
and not for idle unload. Verify: the retained-memory lane on the emulated 8 GB floor.

**33. The engine actor's unshipped relief API (E3). Size M.** Either route `unloadModel` and hard
trim through `engine.unload()` and `relieveMemory`, or mark that surface test-only; in the same
change, make `native-engineering.md` describe what the product actually does.

**34. Engine correctness, small (E5, E6, E7, E12). Size S each.**
- E5: recheck `isInitialized` after each await in `MLXTTSEngine.swift:1121-1154` before publishing.
- E6: make `runReservedTake`'s cleanup non-throwing and rethrow the original error.
- E7: clear the allocator cache after `waitForModelTermination` on the failure path.
- E12: an all-quiet clone take ends as the no-speech refusal.
- Each with the fake-runtime test the audit names.

**35. Engine housekeeping (E8, E9, E10, E11). Size S to M.**
- E8: publish progress per chunk, or only with a subscriber.
- E9: delete the legacy stream generators and move `AtomicWAVGenerationOutputSink` to the test
  target; update `FACADE_API_BASELINE.json` if the facade changes.
- E10: close the WAV file explicitly if the SDK allows; throw on a failed fsync; fsync the directory.
- E11: read the bench context file only in an internal-diagnostics build; `ui_test.sh` clears it for
  the perf lane.

### CLI and storage

**36. MCP `delete_voice` (C5, after D-3). Size S.** `MCPTools.swift:300`: offer it only with
`--allow-voice-delete`; document it in `cli.md`. Test: destructive tools are absent by default.

**37. Engine leases both ways (C3, C4). Size L; this is RF-30's first part.**
- `CLIWarmEngine`: release the lease on idle unload, re-admit on the next load.
- The Mac app reads `EngineHostLease.liveHosts()` before deleting a model and before 8 GB admission,
  and takes its own lease.
- `DesktopAppPresence`: fall back to the process table when `NSRunningApplication` sees nothing;
  confirm over ssh with the app open.

**38. CLI correctness, small (C6 to C9, C11, C12). Size S each.**
- C6: a recorded signal with nothing yet reported becomes `cancelled`; otherwise exit with the
  reported status.
- C7: store digests, not script text, in the request ledger; prune in `claim` as well.
- C8: classify ENOSPC and `NSFileWriteOutOfSpaceError` as `storage_full`; preflight free space.
- C9: compare `--out` protection case-insensitively.
- C11: decode History receipts per row; mark an unreadable one, keep the row.
- C12: model ids case-insensitive everywhere; `--stream --no-stream` is an error; a failed final
  rename keeps the joined long-form output.

**39. Fast QC's pause budget (E4, after D-7). Size M.**
- 39a (no generation): replay retained takes whose text has blank lines or dashes; read
  `longestSilenceMS` against the 1.2 s line. If none is refused, close as not observed.
- 39b (only if 39a shows refusals): count a paragraph break and an en dash as pause runs, as a new
  Fast QC algorithm version, behind a screen whose rule is recorded before its takes.
- **39a result (2026-11-15, retained quality-screen takes on the M6, no generation):** of 9,408
  single takes, 82 carry an en dash. None was refused and none passed the 1.2 s line: their longest
  silence has a median of 28 ms and a maximum of 1,036 ms, against 45 ms and 1,578 ms for the takes
  without one. Four long-form runs of one script with an en dash were refused, all under the retired
  Consistent variation, and the same script completes under Expressive. No retained take carries a
  blank line, because every screen script is one paragraph, so the paragraph-break half of E4 is
  **not observed and not measured**. The en-dash half closes as not observed; 39b does not start.
  A paragraph break stays an open question that only new takes can answer.

### Tests and lanes

**40. A speed gate for the UI benchmark (T2). Size M.** After step 18 has three canonical v2 runs:
compare per-cell warm medians of RTF, time to first chunk and playback scheduling with the pooled
lineage, with the gate bench's thresholds and its INCONCLUSIVE outcome.

**41. A completed model update under test (T7). Size L.**
- Extract the Mac update state machine from `ModelManagerViewModel` behind a downloader and store
  protocol (the iPhone's policy type is the model); unit-test start, make-room, failure memory.
- A smoke journey on a local fixture mirror that completes an update, verifies, reclaims and
  generates; one that takes make-room.

**42. CLI handlers under test (T8). Size L.** Move `ModelsCommand`, `VoicesCommand`,
`HistoryCommand`, `BatchCommand`, `SettingsCommand` and `DoctorCommand` into `VocelloCLICore`; a
model-free pass over a temporary `--data-dir` validates each `--json` envelope against the contract;
add examples for models, voices and history.

**43. Playback under test (T9). Size M.** Build on step 27's fake node: preview-queue hand-off,
`completeStreamingPreview`, ownership of a finished take's player.

**44. The benchmark records a refusal (T5, after D-5). Size M.** `check_macos_ui_bench.py`: write
the manifest on every run with a per-take `refused` status; publish passing cells as a non-canonical
record carrying `refusedCells`; the test continues past a refused take. A separate random-seed
screen measures the refusal rate.

**45. Test hygiene (T12, T13, T14). Size S.** Replace the wall-clock sleeps the audit lists with
conditions; run the watermark parity tests when the fixture path exists and say so in the lane
summary; give the crash delta a settle time and include `.hang` and `.spin` reports.

### Tooling and CI

**46. Signing isolation (B2). Size L.** `release.yml`: build in a job with no secrets; sign and
notarize on a fresh runner from the handed-over artifact, as `sparkle-feed` does; pip with
`--require-hashes`. Proved by the release rehearsal.

**47. Hook gaps (B7, B11). Size M.** `scripts/hooks/git_commands.py`: refuse a `git add` whose
selection is "all" (the parser computes it), `git stash` in any spelling, `commit -a`, and
`release.sh` through `sh`; fail closed on a parser exception. `commit_lint.sh`: require an item ID
in the subject. Tests in `scripts/tests/test_agent_hooks.py`.

**48. Shell and lock fixes (B8, B9, B12, B13, B14). Size S each.**
- B8: `xcb_run` saves and restores `pipefail`.
- B9: re-read the lock's pid after acquiring; release only an owned lock.
- B12: remove `build/vocello-enhanced-security` and its policy entry, or mark it optional.
- B13: delete the stray `nonexistent/` directory; delete or reference the two converter scripts;
  fix the temp files in `check_ios_catalog.sh:55` and `regenerate_project.sh:37`; prune
  `.claude/settings.local.json`'s blanket allows; pass values to `install_pinned_tools.sh`'s Python
  through argv.
- B14: pin `QVOICE_INTERNAL_DIAGNOSTICS_SWIFT_FLAG=""` in the app's release build and add a binary
  check that the shipped app lacks the capability.

**49. Workflow and document agreement (B-low). Size S.** `release.yml:992`'s cache restore against
`tooling-and-evidence.md:81`: change whichever is wrong.

**50. Baselines that only shrink (B13). Size L, ongoing.** Work the pyright baseline (748 findings)
down by module; raise shellcheck to `info` once clean.

### Instructions and documentation

**51. CLAUDE.md (D6, D13, the audit's recommendations). Size S.**
- Fix: the receipts source; "For 3.x"; the agents' model rule.
- Add five lines: UI lanes need the Mac free and run in the background; the website check needs
  Playwright's browsers; most failure-prone lane first; a refused benchmark take is a product
  outcome and seeds never move for it; read a lane's `--help` before passing options.
- Cut: "Claude Code harness" to three lines and a pointer; "Release focus" to the classification
  rule and a pointer to the focus lock.

**52. Tag signer (B10, after D-8). Size S.** `scripts/release_source_authority.py:176`: an
allow-list of tagger identities in `config/release-evidence-contract.json`. ★ Confirm on GitHub
that the signing secrets are environment-only.

**53. Documentation structure (D15). Size M.** An index of the reference documents (generated, with
a check that every document is listed); link or delete the four unlinked dated documents; add
`reviewed` to the documents that lack it; split `telemetry-and-benchmarking.md` so the benchmark
rules are findable.

## Coverage: every finding and its step

| Finding | Step | Finding | Step | Finding | Step |
|---|---|---|---|---|---|
| A1 | 1 | E1 | 31 | C1 | 2 |
| A2, A3 | 27 | E2 | 32 | C2 | 3 |
| A4 | 28 | E3 | 33 | C3, C4 | 37 |
| A5 | 29 | E4 | 39 | C5 | 36 |
| A6 to A9, A11 | 30 | E5 to E7, E12 | 34 | C6 to C9, C11, C12 | 38 |
| A10 | 8, 30 | E8 to E11 | 35 | C10 | 5 |
| T1 | 7 | B1 | 14 | D1 | 21 |
| T2 | 40 | B2 | 46 | D2, D8 | 23 |
| T3 | 9 | B3 | 15 | D3, D4, D12 | 4 |
| T4 | 10 | B4 | 13 | D5, D7 | 25 |
| T5 | 18, 44 | B5 | 17 | D6, D13 | 51 |
| T6 | 12 | B6 | 16 | D9 | 22 |
| T7 | 41 | B7, B11 | 47 | D10, D11 | 26 |
| T8 | 42 | B8, B9, B12 to B14 | 48, 50 | D14 | 24 |
| T9 | 27, 43 | B10 | 52 | D15 | 53 |
| T10 | 11 | | | | |
| T11 | 6 | | | | |
| T12 to T14 | 45 | | | | |
