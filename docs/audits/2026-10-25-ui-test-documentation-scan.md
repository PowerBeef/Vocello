---
status: active
owner: release-qa
reviewed: 2026-10-25
summary: Read-only scan, at commit 6f9fe5ff, of the repository's documentation, rules, skills, script help texts and test comments for outdated or contradictory statements about the UI test suites and their procedures, after the 2026-10-25 UI-lane rework and computer-use decision. Report only; no fix is applied until the maintainer picks one.
sourceOfTruth:
  - scripts/ui_test.sh
  - Tests/UIAutomationSupport/VocelloUIAutomationSupport.swift
  - Tests/VocelloMacUITests/VocelloMacUITestCase.swift
  - Tests/VocelloiOSUITests/VocelloiOSUITestCase.swift
  - CLAUDE.md
  - docs/reference/development-workflow.md
---
# UI test documentation scan (2026-10-25)

Scope: `CLAUDE.md`, `docs/reference/*.md`, `docs/ARCHITECTURE.md`, `docs/development-progress.md`,
`.claude/skills`, `.claude/agents`, the help and comments of the UI scripts, the doc comments of the
UI test sources, and the RF-10/RF-15/RF-17/RF-35 roadmap notes. Each line below was checked against
the code at 6f9fe5ff; quoted claims are short. "Mine" marks text this session's own changes should
have updated.

## A. Wrong instructions (a reader following them does the wrong thing)

1. **UI lanes "only when requested".** `testing-runbook.md:29`, `macos-testing.md:136`,
   `ios-appstore-submission.md:36,429`, `ARCHITECTURE.md:150-151`. These contradict `CLAUDE.md:101-102`,
   `testing-runbook.md:47`, `tooling-and-evidence.md` ("Targeted local acceptance") and
   `ios-device-testing.md:37`, which authorize local UI lanes at coherent checkpoints.
2. **XCUITest as the only driver.** These predate the 2026-10-25 decision that computer use is the
   default route for what XCUITest cannot cover (`CLAUDE.md:148-155`).
   - "XCUITest is the sole/only autonomous UI driver": `ios-device-testing.md:20`,
     `macos-testing.md:19`, `macos-app-guide.md:324`, `macos-release-qa.md:74`,
     `ios-app-guide.md:108-109,721-722`.
   - `ios-app-guide.md:896`: "Never validate with … alternate desktop/mobile UI driver".
   - Skills: `vocello-debug/SKILL.md:18` ("XCUITest-only UI driving"), `vocello-ios-validation/SKILL.md:22`
     ("No Simulator or MCP UI driving") and `vocello-macos-ui/SKILL.md:18` ("may explore … beforehand").
   - `development-workflow.md:650` routing table: "computer use to explore, never for evidence" (mine).
   - `.claude/agents/vocello-swift-review.md:69`: "XCUITest-only rules" (ambiguous now).
3. **Optional-element probe.** `native-engineering.md:232-233` says to use
   `XCTWaiter.wait(for: [XCTNSPredicateExpectation])`, which keeps XCTest's one-second polling.
   `VocelloUIWait.settles` is now the non-failing, eager probe.
4. **macOS `ui-preflight` called advisory.** `macos-testing.md:333-334` and `macos-app-guide.md:480` say
   it only warns; `mac_ui_preflight` refuses a locked session or Automation Mode needing a password
   (`ui_test.sh:681-687`). `macos-app-guide.md:550` is right.
5. **iPhone Files import "retired".** `ios_device.sh:570-572` says the iPhone app ships no file import.
   This contradicts `ui_test.sh:96-99` (the enroll-clone-fixture lane uses the genuine Files import), the
   fixture and saved-voice test comments, and `fileImporter` in `Sources/iOS` (`IOSVoicesView.swift`).
6. **Mirroring before lanes.** `vocello-ios-validation/SKILL.md:15-18` lists the pre-lane steps without
   quitting iPhone Mirroring (`scripts/ios_device.sh mirroring stop`), which `ui-preflight` now requires.
7. **Skill count.** Seven skills exist. Six are named or counted in `testing-runbook.md:43`,
   `development-workflow.md:552-554` and `CLAUDE.md:201-203`, and `development-workflow.md:633`'s
   fresh-session check ("the six skills and two agents") would now fail (mine).

## B. Stale details

8. **iOS smoke size.** `ios-device-testing.md:439` ("Three journeys") and `:445` ("two generation
   journeys"): full smoke runs four tests since 08372fdd (`ui_test.sh:1886-1891`). `ios-app-guide.md:693,
   765-766, 779-780` still put recording and model lifecycle outside smoke.
9. **macOS smoke and the language walk.** `macos-testing.md:136-138` doesn't say smoke now skips test01's
   ten-language walk; `localization.md:191` cites a smoke run as the walk's evidence;
   `macos-release-qa.md:75-76` describes smoke as one Custom generation (it is 15 journeys); no document
   gives the new duration (about 11 minutes; 637 s of tests in run 20261025-221609-c2191179).
10. **macOS navigation.** `macos-app-guide.md:353`: "Navigate by `sidebar_<mode>`". Journeys now use
    ⌘1–⌘6 with a sidebar fallback; test01 and the click-and-type classes still click.
11. **Candidate `first-launch` row.** `ios-device-testing.md:181` says it installs the three shipping
    models on a fresh install; it starts only missing models (Download or Retry, bottom row first) and
    also serves RF-35's reinstall on a set-up phone. The routing table there contradicts itself:
    line 252 sends the model reinstall to XCUITest, line 254 to computer use.
12. **Which rows are attended.** `development-progress.md:87-89` (October 24) lists the ~30-take screen
    and the purchase rows as attended; the routing table sends both to XCUITest. RF-15's gate in
    `config/roadmap.json` says every row runs "through the repository XCUITest stack", and its notes
    still speak of build 24; RF-35's notes lack the 2026-10-25 Wi-Fi reinstall PASS.
13. **Build number.** `release-first-execution-2026-09.md:186`: "3.0.0 / build 24"; `project.yml` is 25.
14. **Bundle count.** "Both XCUITest bundles" in `tooling-and-evidence.md:56`, `development-workflow.md:226`
    and `native-engineering.md:25`; `CLAUDE.md:52` and `build_ui_test_bundles.sh` have three.
15. **Routing and run review.** `testing-runbook.md:26-39` has no row for checks XCUITest cannot cover,
    and its "Read a finished run" section omits the `screenshots/index.json` review.
    `ios-appstore-submission.md:432-436` lists hand pre-flight checks without pointing to the candidate
    rows or computer use. `.claude/agents/vocello-xcresult-triage.md:28` points at the raw attachments
    manifest, not the screenshot index.
16. **Long-form segment count.** `macos-testing.md:318` says not to assume a fixed count; line 164 and
    `macos-app-guide.md:333` say "two planned segments by default".
17. **Test and script comments.**
    - `VocelloUIInteractionPolicy.swift:131` describes a drag from the anchor by the wanted distance; the
      reveal drags to a second text element (mine). `enum Swipe` and `swipingUp:` still say swipe.
    - `VocelloUIAutomationSupport.swift:638-639` calls `VocelloUIScroll.reveal` "the single replacement for
      the per-class reveal loops"; `VocelloUISettingsReveal` exists beside it.
    - `VocelloMacUITestCase.swift:45-47` says the measured lanes time the click and type paths; the
      benchmark pastes outside its windows, and only perf times them (mine).
    - `VocelloiOSSmokeUITests.swift:191-193` describes one journey in one session; the class has ten tests.
    - `ui_test.sh:131` and `VocelloiOSSmokeUITests.swift:159-160` say variation is read through the
      visible Settings control; it is read from the Settings root row first (mine).
    - `ui_test.sh:67-69` calls the localization lane an accessibility-size walk; on the Mac it is test01.
    - `VocelloPlaybackCaptureSession.swift:6` says benchmark only; smoke uses it too.
    - `VocelloMacSmokeUITests.swift:28` says "Xcode 26 test runner"; the host has Xcode 27.1.
    - `ios_device.sh:39-41, 567-570`: the speech-assets help and comment are split by the enroll lines.

## C. True in code, missing from the docs

18. The iPhone development build skip (fingerprint, Xcode version, phone and product digests) and
    `xcodebuild-build.log` (`ui_test.sh:1183-1250`); only the Mac's two-phase build is documented.
19. The candidate runner re-seal (`ensure_ios_candidate_runner_signature`, `ui_test.sh:650-671`).
20. `--prune-ui-results --quick` and the ledger's `startedAt`.
21. `scripts/ios_device.sh mirroring status|session|capture|stop` in `ios-device-testing.md`'s verb list.

## D. Code risks the scan surfaced (not documentation)

22. **The routed check undoes the iPhone build skip.** `build_ui_test_bundles.sh:121-131` compiles the
    iOS UI bundles unsigned and generic into the same DerivedData the lanes use, so after every routed
    check that touched test code the lane's product digests differ and it rebuilds (safe, but most of
    the skip's value is lost while tests change). The same overwrite left the candidate runner unsealed
    on 2026-10-25 (run 20261025-170520-043a66ef), now repaired at lane time.
23. **Retention keeps some lanes forever.** `config/build-output-policy.json` `childRetention.uiResults.lanes`
    omits `delivery-cohort`, `enroll-clone-fixture` and `saved-voice-lifecycle` (and `candidate-smoke`,
    whose runs are pinned on purpose), so those runs are never pruned. Runs are grouped by platform and
    lane only, so a passing focused smoke scenario compacts the previous full-smoke pass.
24. **The candidate navigation row swipes Settings natively** (`VocelloiOSCandidateAcceptanceUITests.swift:
    50-62`, `app.swipeDown()` and `VocelloUIScroll.reveal`), the gesture that tapped the cellular switch
    on 2026-10-25 (BKL-36). RF-35's gate depends on that row.
25. **The Mac benchmark's `pasteScript`** reads the general pasteboard without the `accessBehavior` check
    the shared paste helper now has (`VocelloMacBenchmarkUITests.swift:199-238`).
26. Steps recorded with `required_step_record` (the skipped `ui-build`, `result-retention`) carry no
    `startedAt`.

## Recommended order (for the maintainer to pick)

1. A: rules and skills, which steer every session (items 1-7). Small text edits.
2. B and C: lane and journey descriptions, the build number, the missing procedures (items 8-21).
3. D: each code risk as its own decision; 22 and 24 matter most for the next phone window.
