---
status: active
owner: release-qa
reviewed: 2026-11-15
summary: A whole-project audit before the Mac and CLI 3.1 release — engine, apps, CLI and storage, test harnesses and lanes, tooling and CI, instructions and documentation — with every finding, its evidence, and a recommended order.
sourceOfTruth:
  - config/roadmap.json
  - docs/development-progress.md
---
# Project audit before 3.1 (RF-61)

Requested by the maintainer on 2026-11-15. An audit only: nothing in the product, the tooling or the
documents was changed. The tree audited is `main` at `0dbd391d`.

## How it was done, and its limits

Six read-only reviewers each read one area end to end (engine and core; the Mac and iPhone apps; the
CLI, storage and delivery; tests and lanes; tooling, CI and hooks; instructions and documentation).
They ran nothing: no build, test, lane or model. The lead then checked the strongest claims against
the code and data; those findings are marked **verified**. The rest are **confirmed** (a reviewer read
the code path and quoted it) or **suspected** (plausible, needs the named run).

Not covered: the model mathematics (talker, code predictor, codec, sampling), the downloader's
transfer internals, the iPhone lanes and device behaviour, GitHub-side settings (environment
protection, secret scope), and most of the largest reference documents line by line.

## Verdict

**The product code is in good health. The release process is not yet able to prove it.**

- No reviewer found a blocker or a crash, data-loss or security defect in the engine, the apps or
  the CLI. Cancellation, admission, the audio channel, the History outbox, the MCP path policy,
  model verification and the release workflow's source authority were all read closely and found
  sound.
- One real product defect matters to users today: a History of more than 500 takes rebuilds its
  list twice on every search, filter or sort (A1). It is the stall the performance lane measured.
- The larger risk is in the evidence. The lanes the maintainer asked for (responsiveness, playback,
  preview) check that evidence is complete and well formed, and almost never that the app got
  slower, janky or silent (T1 to T5). And everything measured locally is built with a different
  Xcode than the one that builds the release (B1).
- The documents and public copy need a planned flip at publication, and two things outside the copy
  would break it: a contract script that requires the old README wording (D1) and a privacy page
  that 3.1's automatic model update makes false (D2).

## Recommended order

**Before the 3.1 tag**

| # | Do | Findings |
|---|---|---|
| 1 | Fix the History paged path; isolate the perf lane's History store | A1, T11 |
| 2 | Make the lanes able to fail: silent capture, underruns and continuity, a ceiling for `history-filter`, expected test list | T1, T3, T4, T10 |
| 3 | Decide the Xcode question: move the pin to the 27 line, or run acceptance on the pinned 26.6 | B1 |
| 4 | Correct the 3.1 notes (speed figures, known limitations, hold the TestFlight section) | D3, D4, D12 |
| 5 | Restore `settings variation` as a retired no-op; report removed folders from `models install` | C1, C2 |
| 6 | Pin `gh` in the promote workflow; fix the bare `python3` in the release preflight | B6, B3 |
| 7 | Rerun, with the Mac free: UI benchmark first, then perf, smoke, readiness, `dev.sh ci` | T5 |

**At publication (one commit, with the release)**

- The README, website, privacy page, public facts and the two scripts that pin the old wording
  (checklist in the appendix): D1, D2, D5.

**After 3.1**

- Engine clean-ups (E1 to E3), the live-preview resume (A2, A3), the app-to-CLI coordination (C3, C4),
  the benchmark's speed gate and partial results (T2, T5), signing isolation (B2), the hook gaps (B7),
  and the documentation structure (D15).

---

## 1. Mac and iPhone apps (A)

Overall: defensive and consistent. Generation and playback are guarded by attempt tokens and
session IDs, heavy I/O carries `@concurrent`, glass and motion go through their gates.

| ID | Severity | Status | Finding |
|---|---|---|---|
| A1 | High | verified | **History over 500 entries rebuilds its list twice per change.** The debug History the perf lane uses holds 737 rows, past the 500-row page, so `holdsWholeArchive` is false. `pageInputsChanged` (`MacHistoryScreen.swift:685-690`) first filters the loaded page in memory (older matches are not in it, so the list is swapped for "No matches"), then the database page lands and a new list is built; `onChange(of: itemsRevision)` adds another pass. A user with more than 500 takes sees "No matches", then results, with a stall near a second. `history-scroll` is unchanged on the same build, so row rendering, `@Observable` and the concurrency default are not the cause. Fix: skip the in-memory pass when the archive is paged, never show the empty state while a read is in flight, apply the page and sections in one main-actor block. |
| A2 | Medium | verified (code) | **Resuming the live preview schedules 43 ms of silence after the queued audio.** `AudioPlayerViewModel.swift:1630-1633` calls `scheduleLeadingSilence()`, which appends (`LiveStreamingPlaybackEngine.swift:176-183`), so on a resume or an underrun recovery the silence lands behind the audio already queued, mid-stream. Whether it is audible needs a forced-underrun take. Fix: schedule it only when the queue is empty. |
| A3 | Medium | suspected | **The live playhead may double-count after a pause.** Resume sets `livePlaybackTimeOffset = currentTime`, but `AVAudioPlayerNode.pause()` does not reset player time; a later hand-off to the final file (output-device change, memory pressure) would then skip unheard audio. Confirm by pausing a preview at 3 s and comparing the counter with the audio. |
| A4 | Medium | confirmed | **Deleting a long-form project's row leaves its segments,** which then appear as loose rows with their audio (`MacHistoryScreen.swift:985-1017`; the iPhone is the same). Confirm the intent, then delete as a unit or say the segments are kept. |
| A5 | Low | confirmed | **Shared player strings are hard-coded English** and shown on the Mac in ten languages (`AudioPlayerViewModel.swift:258` "Live", and about ten more sites; `ModelManagerViewModel.swift:1125`, `:919`). The localization contract does not cover the file. |
| A6 | Low | confirmed | The playhead timer stops while a menu is open or the window resizes (`Timer.scheduledTimer` in the default run-loop mode, `:2088`). Add it to `.common`. |
| A7 | Low | confirmed | Save As and recovery export copy files on the main thread (`MacHistoryFileActions.swift:27`, `:57`): a long-form WAV to an external volume freezes the window. |
| A8 | Low | confirmed | The batch sheet accepts a dropped file and silently ignores it unless it is `.txt` (case-sensitive) in UTF-8 (`MacBatchGenerationSheet.swift:181-195`). |
| A9 | Low | suspected | "Remove Earlier Models and Update" gives no feedback when nothing could be removed (`ModelManagerViewModel.swift:776-794`). |
| A10 | Low | suspected | **The delivery menu's 19% extra frame time is probably the lane, not the menu.** The menu code is unchanged and main-thread CPU in the window is flat; the scenario does not suppress warms, and a model warm now overlaps it. Rerun with `QWENVOICE_SUPPRESS_WARMUP`. |
| A11 | Low | confirmed | Several screens still observe the whole engine store (`MacPlaybackFooter`, the Studio screens). Inside the rule; an optimisation. |

## 2. Engine and core runtime (E)

Overall: no blocker or high defect. Every continuation traced resumes exactly once, the prewarm
slot is paired, Fast QC judges the staged bytes before the atomic rename.

| ID | Severity | Status | Finding |
|---|---|---|---|
| E1 | Medium | confirmed | **Crash-orphaned install replicas are never swept and pin their blobs forever.** `.<folder>.component-install.<uuid>`, `.component-migration.` and `.installing.` directories sit beside the model folders; reclamation walks only the store's trash and staging (`SharedModelComponentStore.swift:873`) and protects any blob with a second link. A force quit during an install leaves a hidden copy that keeps every blob "in use". Fix: add the three name patterns to startup reclamation, with the existing age rule. |
| E2 | Medium | verified | **On the Mac, a full unload keeps the runtime caches.** `clearQwen3MemoryCachesIfNeeded` returns early unless the device is an iPhone (`NativeEngineRuntime.swift:2379-2387`), for idle unload (intended) and also for a pressure-driven hard trim or full unload on the 8 GB tier: about 218 MB of speech tokenizer plus up to 96 MiB of decoder state stay resident. Fix: clear on a Mac for hard trim and pressure unload. |
| E3 | Medium | confirmed | **The engine actor's pressure, relief and unload API is not on the shipping path,** but `native-engineering.md` describes it as the mechanism ("relief carries the generation lease"). The product unloads by dropping its reference. About 300 lines are tested and unshipped. Route the product through it, or mark it test-only and correct the rule. |
| E4 | Medium | suspected | **Fast QC's pause budget ignores paragraph breaks and dashes** (`GenerationOutputAdapter.swift:3506-3526`), so a heading followed by a blank line gets the strict 1.2 s line and a natural paragraph pause can refuse a complete take. Confirm on retained takes whose text has blank lines. A threshold change with a new algorithm version. |
| E5 | Low | suspected | A load or prewarm in flight across `stop()` republishes `.loaded` on a stopped engine (`MLXTTSEngine.swift:1121-1154`). |
| E6 | Low | suspected | `runReservedTake`'s cleanup can replace the original error (`GenerationOutputAdapter.swift:388-409`). |
| E7 | Low | confirmed | The failure-path cache clear runs before the producer has stopped (`:2047`, `:2096`), so a refused or cancelled take leaves the allocator cache full. Matters most on the iPhone. |
| E8 | Low | confirmed | Per-token cross-actor progress hops feed observers nobody reads (`Engine.swift:1757`). |
| E9 | Low | confirmed | Dead duplicate pipelines that can drift: the legacy unbounded stream generators (`Qwen3TTS.swift:1277-1760`) and `AtomicWAVGenerationOutputSink`, referenced only by tests. |
| E10 | Low | confirmed | WAV finalisation relies on a deinit and a `try?` fsync, with no directory fsync after the rename (`:1446`, `:646`). A failure surfaces as a QC refusal, not corruption. |
| E11 | Low | confirmed | Bench context is read from a fixed `/tmp` file in any build with telemetry on (`BenchRunContext.swift:73`); `ui_test.sh` does not clear it for the perf lane. |
| E12 | Low | confirmed | An all-quiet clone take reports "did not emit any audio chunks" instead of the no-speech refusal (`:1039`). |

## 3. CLI, storage and delivery (C)

Overall: no blocker or high defect. The weak points are the seams between processes and versions.

| ID | Severity | Status | Finding |
|---|---|---|---|
| C1 | Medium | verified | **A shipped v1 setting was removed.** `settings get|set variation` existed in 3.0.0 and now exits 2 (`DesktopAppSettings.swift:146-149`); the contract says never remove a property, and the other retired options were kept with a warning. Keep it as a no-op with `variation_retired`. |
| C2 | Medium | verified | **`models install` removes every mode's earlier models and says so only in text mode** (`ModelsCommand.swift:489-511`). With `--json` or MCP the result is silent; installing one mode leaves the other two without a model. A 3.1 CLI beside a closed 3.0 app removes the app's models. Add `removedRetiredFolders` to the result and a warning. |
| C3 | Medium | confirmed | **Engine coordination is one-directional.** Only the CLI reads leases; the app never does. A warm `vocello mcp` holds its lease for life, which blocks every `vocello generate` on an 8 GB Mac and lets the app delete a model the server has loaded. Planned as RF-30; release the lease on idle unload meanwhile. |
| C4 | Medium | suspected | App detection uses `NSRunningApplication`, which may see nothing from ssh, cron or launchd (`DesktopAppPresence.swift:10`). Confirm over ssh with the app open. |
| C5 | Medium | verified (design) | **MCP `delete_voice` is offered by default and cannot be undone,** while `install_model` needs a flag (`MCPTools.swift:300-306`). A prompt-injected agent can delete saved voices. Gate it behind a flag or move files to the Trash. |
| C6 | Low | confirmed | A signalled run can exit 130 while its envelope says `ok: true` (`CLIProcessSupervisor.swift:93-100`). |
| C7 | Low | confirmed | The idempotency ledger keeps script lines past seven days until another request completes (`CLIRequestLedger.swift:163`), and no privacy document names the folder. |
| C8 | Low | suspected | A full disk during `models install` reports `download_failed`, not `storage_full`; the CLI has no free-space preflight. |
| C9 | Low | confirmed | The `--out` overwrite protection is weaker while the app runs (case-sensitive prefix, `GenerateCommand.swift:1294`). |
| C10 | Low | confirmed | Two-package leftovers in agent-facing text: the MCP description of `list_models`, two `--variant speed` hints, a contract example with `pro_custom_quality`. |
| C11 | Low | confirmed | One undecodable receipt fails a whole History page, worded as "update the CLI" (`Generation.swift:84`). |
| C12 | Low | confirmed | Small inconsistencies: model ids case-sensitive in some subcommands, `--stream --no-stream` silently means no-stream, a long-form project whose final rename fails deletes its joined output. |

## 4. Test suites and lanes (T)

Overall: the deterministic suites are strong (about 2,000 Swift tests, an empty quarantine, no
tautologies). The measured lanes are the weak side.

| ID | Severity | Status | Finding |
|---|---|---|---|
| T1 | High | verified | **The performance lane cannot fail on a hitch regression.** The checker rejects any contract that is not `warnOnly` (`check_macos_ui_perf.py:377`), and six of eleven scenarios have no ceiling. `history-filter` varies by about 2% across the three calibration runs, tighter than any judged scenario; a ceiling derived the usual way (about 163 ms/s and 610 ms) would have failed the November run. Add ceilings for the four stable scenarios and an `enforce` list. |
| T2 | High | verified | **The Mac UI benchmark has no speed gate.** It validates the evidence and summarises it; nothing compares RTF or time to first audio with a baseline. A doubled RTF passes and publishes. |
| T3 | High | verified | **The played-audio gate passes when the app plays silence.** A `silent` capture is a warning (`playback_capture.py:307`, `:420`), and the measured wait returns at once if playback never starts. Fail on `silent`; when the grant exists, require every planned capture. |
| T4 | High | verified | **Underruns and continuity failures only need to be non-negative** (`check_macos_ui_bench.py:417-426`). The lane the maintainer asked to guarantee playback does not gate them; on November 14 they were read by hand. Fail on a continuity failure; gate underruns. |
| T5 | High | confirmed | **The benchmark is all-or-nothing.** One refused take writes no manifest, so 28 takes of evidence are lost, and a fixed seed makes it permanent. The seed move (decision of 2026-11-15) does not change the design: about one run in ten can still hit a refusal. The durable fix is to record a refusal and publish the rest. |
| T6 | Medium | confirmed | The stall gate passes with zero gated takes (an unknown device class skips the row), and its limit comes from one run's maximum. |
| T7 | Medium | confirmed | **The Mac model update has no test that completes one.** The view model (1,824 lines) is unreachable from XCTest; the smoke journey proves the offer, Not Now and Cancel, never a finished update or the make-room path, which deletes the user's models. |
| T8 | Medium | confirmed | Most CLI command handlers (`models`, `voices`, `history`, `batch`, `doctor`) are outside the testable module; the packaged smoke runs three read-only commands. |
| T9 | Medium | confirmed | The player and the preview queue (2,400 lines) are referenced by no test; only the resume policy is. With T3, a playback regression has no failing check. |
| T10 | Medium | confirmed | No lane checks which tests ran: a deleted or skipped smoke journey still reads PASS (`xctest_summary.py:107`). |
| T11 | Medium | verified | **The perf lane seeds into the shared debug History,** which other lanes fill and nothing erases, so its `history-*` scenarios measure a different store each month. Seed an isolated profile; add a deliberate over-500 scenario. |
| T12 | Low | confirmed | A few tests wait on wall-clock sleeps (`LongFormHistoryAcceptanceTests.swift:451`, `SharedModelComponentStoreTests.swift:886`). |
| T13 | Low | confirmed | Reference-fixture watermark parity tests never run automatically (they need a private fixture path). |
| T14 | Low | confirmed | The benchmark's new completion check (`0dbd391d`) has not yet run in the lane. |

## 5. Tooling, CI, release pipeline and hooks (B)

Overall: unusually careful. Every action is pinned by SHA, permissions are least-privilege, the tag
and source authority fail closed, Swift pins are exact, every path a config names exists.

| ID | Severity | Status | Finding |
|---|---|---|---|
| B1 | High | verified | **Acceptance evidence comes from a different compiler and SDK than the shipped binary.** The release is built with the pinned Xcode 26.6 (Swift 6.3.3); this Mac has 27.2 and every benchmark, perf, memory and smoke record is from it. Promotion checks the app version and build, not the toolchain. Move the pin before the tag, or run acceptance with the pinned Xcode; either way compare the record's toolchain with the release's. |
| B2 | Medium | confirmed | The Developer ID keychain and notary key are present while third-party packages and unhashed pip packages build (`release.yml:331`, `:465`). Build without secrets, sign on a fresh runner. |
| B3 | Medium | verified | **The release preflight uses a bare `python3`** (`check_project_inputs.sh:57`); on this Mac it has no `pytest`, so `release.sh --preflight full` stops after the readiness work. Only `dev.sh` selects the right interpreter. |
| B4 | Medium | confirmed | The benchmark and perf lanes always write tracked records and rewrite `HISTORY.md`, with no opt-out and no prompt. Add `--no-publish`. |
| B5 | Medium | confirmed | The website step has no browser preflight, so `dev.sh check` fails late on a host without Playwright's browsers, and `doctor` does not probe for them. |
| B6 | Medium | verified | **The promote workflow uses the runner image's `gh`,** not the pinned one, for the attestation check that gates publication (`promote-release.yml`). |
| B7 | Medium | confirmed | Refusals of broad staging, stash and `commit -a` rest on literal prefixes: `git add -- .`, `git add :/` and `git commit -m x -a` match the allow rules. The hook already computes "adds all"; use it. |
| B8 | Low | confirmed | `xcb_run` turns the caller's `pipefail` off on a terminal (`build_cache.sh:698`). |
| B9 | Low | suspected | The native lock's stale-reclaim can race between two waiters (`build_cache.sh:78-112`). |
| B10 | Low | confirmed | Any collaborator's verified key authorises a release tag; the tagger is not allow-listed. |
| B11 | Low | confirmed | The freeze rule (an item ID in every subject) is checked only after the commit exists. |
| B12 | Low | confirmed | The session-start cache warning is wrong: `build/vocello-enhanced-security` is a leftover trial link, the main caches are intact. |
| B13 | Low | confirmed | Housekeeping: a stray `nonexistent/` directory at the repository root; two unreferenced converter scripts; temp files not removed (`check_ios_catalog.sh:55`); `settings.local.json` holds blanket allows for inline Python; the pyright baseline tolerates 748 findings. |
| B14 | Low | suspected | The app's release build does not pin the internal-diagnostics flag to empty as the CLI's does (`release.sh:288`). Confirm, pin, and add a binary check. |

## 6. Instructions, documentation and public copy (D)

Overall: path hygiene is excellent (855 named paths, none missing; no broken link). The weakness is
older paragraphs left standing beside newer ones.

| ID | Severity | Status | Finding |
|---|---|---|---|
| D1 | High | verified | **A contract script requires the old README wording.** `public_facts_contract.py:120-123` fails unless the README says "Speed (4-bit) and Quality (8-bit)"; the chart generator labels pools "of the Speed models". Both must change in the publication commit. |
| D2 | High | verified | **The privacy page becomes false at 3.1:** it says models download "when you choose to install one" (`website/public/privacy/index.html:77`, `:121`), and 3.1 starts the model update on its own. |
| D3 | High | verified | **The 3.1 notes disagree with themselves and omit limitations.** They say "about 4 to 6% more time than Speed and about 28% less than Quality" beside medians of 0.30, 0.28 and 0.41, which divide to +9% and -27% (the 4 to 6% is the per-cell figure). Missing: the rare run-on take refused by the audio check, CLI takes still absent from History, whether 3.0's French and Chinese refusals still apply, upgrading straight from 2.x. |
| D4 | Medium | confirmed | "A 3.0 update adds that" (CLI takes in History) is promised in the 3.0 notes, the website and `cli.md`; the work is parked until the iPhone submission. Say "a later update". |
| D5 | Medium | confirmed | Active references still describe two packages in places: `ARCHITECTURE.md:1160-1169`, `model-delivery.md:153-157`, `qwen3-tts-guide.md:98-104`, `hybrid-model.md:15-25`, `macos-app-guide.md:89` and `:279`, `telemetry-and-benchmarking.md:401`, `cli.md:494-502`, the package README. |
| D6 | Medium | verified | `CLAUDE.md` says the catalog comes from `config/model-artifact-receipts.json`, which holds no artifacts; the receipts are in the bundled iPhone catalog. |
| D7 | Low | verified | The smoke lane has sixteen journeys, not fifteen (`macos-app-guide.md:340`, `macos-release-qa.md:74`, a comment in `ui_test.sh`, and this audit's sibling of the same day). |
| D8 | Medium | confirmed | `privacy-storage.md` omits the CLI request ledger and the engine-host leases. |
| D9 | Medium | suspected | The hybrid's attribution names `mlx-community/…-4bit` as its base while two guides say Vocello ships its own conversions; all three models read `redistributionDecision: pending-qualified-review`. Settle which is true before publication. |
| D10 | Medium | confirmed | The roadmap shows RF-61 as planned while the three in-flight slots hold iPhone items; the checkpoint carries two "next" lists. |
| D11 | Medium | confirmed | The iPhone submission documents still describe 3.0.0, with one stale byte count. Not Mac-blocking. |
| D12 | Low | confirmed | The 3.1 notes carry a TestFlight section for a candidate that does not exist and flows unproven on a device. |
| D13 | Low | confirmed | Instruction contradictions: agents "inheriting its model" against "often on a cheaper model"; "For 3.0 nobody listens" now applies to 3.1. |
| D14 | Low | confirmed | The README hero image shows the Speed/Quality switch. |
| D15 | Low | confirmed | Structure: no index of the fifty documents; four unlinked dated documents; `reviewed` dates older than content in five references; `telemetry-and-benchmarking.md` is 185 KB with the refused-take rule at line 963. |

### CLAUDE.md

- **Add** (one line each): UI lanes take over the Mac, so run them with it free and in the
  background; the website check needs Playwright's browsers, and the browser pane is a stand-in, not
  the verdict; in a release sitting run the most failure-prone lane first; a take the audio check
  refuses in a benchmark is a product outcome, and seeds never move for it; read a lane's `--help`
  before passing options.
- **Fix**: the receipts source (D6), "For 3.0" (D13), model inheritance (D13).
- **Cut**: "Claude Code harness" restates `development-workflow.md` almost line for line, and
  "Release focus" restates the focus lock. The file is 2,300 words and loads into every session.

## Corrections to earlier statements in this release run

- The investigation of the same day said the History filter's cause was untraced and listed the
  October changes as candidates. A1 names the cause; those candidates are ruled out.
- "Fifteen journeys" for the smoke lane should read sixteen.
- The delivery menu's slowdown was reported as the menu's own animation; A10 says the lane is the
  likelier cause.
- Playback on the twelve completed benchmark takes was reported clean. That was read by hand from
  the telemetry; the lane itself would not have failed on an underrun (T4).

## Checked and found sound

- Cancellation and admission: the prewarm slot, the generation gate, the active-generation
  coordinator, the lossless audio channel, one terminal event per take.
- Fast QC ordering (silence before marking, QC before publish), the limiter, the runaway-silence stop.
- The downloader's path validation; publication and install under lock with hard links only.
- Debug-knob gating; privacy of logs; every unsafe-concurrency marker registered.
- The MCP path policy, per-request consent, the request ledger's locking, the saved-voice journal,
  the History outbox and clear.
- Catalog data: contract, production catalog and iPhone catalog agree on folders, revisions, sizes
  and digests.
- Workflows: SHA-pinned actions, no `pull_request_target`, timeouts everywhere, fail-closed source
  authority, the Sparkle key isolated, the build number check.
- Swift dependency pins exact and identical across both resolved files.
- Documentation paths and links; every command and flag CLAUDE.md names.

## Appendix: publication checklist (the flip to 3.1)

- `config/public-product-facts.json`: stable release to 3.1.0, remove the candidate.
- Scripts: `public_facts_contract.py:120-123`, `generate_readme_charts.py:91-93`, the two
  `readme_art/performance*.html` templates.
- `README.md`: lines 10 and 14 (links, badge), 31, 62, 65, 69, 70, 75 to 79, 86, 91, 97, 163 to 177;
  re-render the hero, performance and download images and the charts.
- `website/src`: `data/release.js`, `data/whatsnew.js`, `data/cli.js`, and the `FinalCTA`,
  `Limitations`, `IphoneBeta`, `CommandLine`, `Engineering` and `WhatsNew` sections; the three
  pages' meta descriptions.
- `website/public/privacy/index.html:77`, `:121`, `:147`, `:155` and `support/index.html:101`.
- Add this checklist to `docs/reference/macos-release-qa.md`, which has none.
