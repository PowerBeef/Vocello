---
status: active
owner: backend-and-platform
reviewed: 2026-10-27
summary: Current resume checkpoint; config/roadmap.json owns open work, config/roadmap-archive.json holds finished work, and older narrative lives in git history.
sourceOfTruth:
  - config/roadmap.json
  - config/runtime-refactor-contract.json
---
# Vocello development checkpoint

Start here, then follow `config/roadmap.json`'s `primaryPlan` and the
[release-first execution plan](reference/release-first-execution-2026-09.md).
This is a narrative, not a second work ledger. Product source, contracts and scripts win.
Checkpoints older than the five below live in git history (`git log -p -- docs/development-progress.md`;
the last copy with every earlier checkpoint is at commit a0597deb).

## Resume now

### October 26: build 26 in Public Beta (resume here)

- **Build 26** (3.0.0, `v3.0.0-ios.5` at `e0feaf2c`): build 25's product plus a test-only fix
  (`398709b8`) and the build number. Release run 40391931937 passed and the build processed VALID;
  en-US What to Test notes, beta review APPROVED, Internal and Public Beta IN_BETA_TESTING (public
  link and feedback on). Build 25's beta review was also approved; it never joined Public Beta.
  Build 23 (2.4.0) stays in the group until it expires on October 30.
- **RF-17 waived for this Public Beta only (maintainer, 2026-10-26):** the promotion lanes were
  skipped on `v3.0.0-ios.5`; RF-17 still gates the App Review submission. The beta looks for the
  remaining bugs and for performance and stability on the iPhone 15 Pro floor.
- **Model-download lane:** the bottom row's progress bar sat under the tab dock once the cellular
  switch lengthened Voice Models (`ios-xcui-model-download-20261026-182637-177434c3`, retained, ten
  findings on pro_clone). The test now reveals the bar before capturing it (`398709b8`); the proof
  run `ios-xcui-model-download-20261026-185315-4d030b9e` PASS, no findings.
- **Phone state (October 27):** TestFlight build 26 is installed over the development build, with
  History and Saved Voices intact, which closes RF-12's install row. RF-15's navigation row PASS on
  build 26 (`ios-xcui-candidate-smoke-20261027-135949-5fe567b6`) after four retained non-product
  failures. A new TestFlight build's first launch shows TestFlight's What to Test sheet: tap
  Continue before the first row.
- **RF-35, attended (October 27):** on 5G with no Wi-Fi and the switch off, a Voice Design download
  waits (maintainer). It shows 682.3 MB (33%) from the start: the speech tokenizer, identical in
  every model, is reused from an installed model with no network transfer, which also explains the
  682 MB seen on October 25. The display is parked as BKL-39. With the switch on, a download
  started afterwards progressed over cellular, then the maintainer stopped it before it finished
  because coverage there is weak, so a completion over cellular is not yet observed. Voice Design
  is not installed (2 of 3 models ready); reinstall it before the rows that need all three.
- **3.0 ships outside the EU (maintainer decision, October 27):** rather than publish a home address
  as an EU trader, the 27 EU territories were removed from availability (148 of 175 remain,
  verified) and the account and Vocello are declared non-trader with no EU distribution intended;
  App Store Connect reports the DSA requirements complete. The EU release is BKL-41. RF-02 keeps the
  updated Apple Developer Program License Agreement (it blocks submissions), the Paid Apps
  agreement, tax and banking, all the maintainer's.
- **RF-17 needs seven iOS records, not five:** `classify` against `v3.0.0` or `v3.0.0-ios.4` adds
  `ios-language-benchmark` (lang-bench) and `ios-delivery-benchmark`. No iOS lane or history record
  produces the delivery record yet, so no iOS manifest can validate until a lane or a recorded
  contract decision covers it.
- **RF-36 closed:** all ten languages, the dialog in the String Catalog, contract PASS, shipped in
  builds 25 and 26.
- **First beta report (build 23, no crash submissions):** a tester typed a voice description into
  Design's script field and Generate never ran; 3.0 still dims Generate without a visible reason
  (BKL-38, parked). The App Review notes draft now explains Design's voice description chip (ASR-05).
- **Next:** triage Public Beta feedback and crashes as they arrive. The next window runs RF-17's
  lanes (classify the submitted tag first), RF-35's attended cellular check and RF-15's remaining
  rows. The maintainer can do RF-02 (the updated license agreement, the Paid Apps agreement, tax
  and banking), ASR-05's listing review and ASR-04's attestations remotely.
- **Pushed:** through `726935ea` (CI passed); `2ef22a88` and later are local.

### October 25: build 25, faster UI lanes, computer use as the default route

- **Build 25** (3.0.0, `v3.0.0-ios.4` at `3f1d2bda`, RF-35 cellular opt-in plus RF-36 translations)
  passed release run 40146203055 and processed VALID; internal testers have it; no beta review
  submitted for it; Public Beta still waits for RF-17. Installed on the phone over build 24.
- **On build 25:** navigation PASS 15.1 s (`20261025-030310-db58b35b`, was 28.1 s), modes PASS
  125.4 s (`030425-0c0d2524`, was 530.2 s); RF-35's unattended Wi-Fi reinstall PASS
  (`184700-55cd4a7d`, `modelsDownloaded: ["pro_design"]`, switch off) after five harness failures,
  all retained and fixed (runner re-seal, settled reveals, bottom-up starts, a swipe that tapped the
  cellular switch, too-short swipes). RF-35's attended cellular check is open: the maintainer's
  screenshot showed 682 MB then "No progress" with Wi-Fi off and the switch off; whether those bytes
  came over cellular is unanswered. BKL-35, BKL-36 (a short drag flips a Settings toggle) parked.
- **UI lanes rebuilt (maintainer request):** retention 27 s -> 1 s, step start times in ledgers, a
  `screenshots/` index for Claude's post-lane review, iPhone dev builds skipped when nothing changed
  (fingerprint, Xcode, phone and product digests), iOS `ui-preflight` refuses under iPhone
  Mirroring. macOS smoke 3,843 s -> 637 s, 15/15 PASS (`macos-xcui-smoke-20261025-221609-c2191179`;
  the earlier `220226-302c01e3` failed on a History-count bug of the new code, fixed in 83655854).
  The ten-language walk is the localization lane's. iOS suite changes (long-form by title token,
  snapshot History census, one Settings visit) are committed but not yet run on the phone.
- **Decision 2026-10-25:** computer use (iPhone via iPhone Mirroring, the Mac directly) is the
  default route for checks XCUITest cannot cover, in announced windows, records confirmed by the
  maintainer (`/vocello-ui-autonomy`, `scripts/ios_device.sh mirroring`).
- **Next window:** the long-form scenario and a candidate row on build 25 to prove the iOS suite
  changes; RF-35's attended cellular check; the first-window Mirroring probes (start, input incl.
  typing, handoff lock state, window capture).
- **UI-test documentation scan:** [`docs/audits/2026-10-25-ui-test-documentation-scan.md`](audits/2026-10-25-ui-test-documentation-scan.md)
  lists outdated and contradictory statements and five code risks; sections A, B and C are fixed,
  and the code risks in D (items 22-26) wait for separate decisions.
- **Pushed:** through `6f9fe5ff` (CI passed).

### October 24, evening: RF-15 on build 24

- **Phone state:** build 3.0.0 (24) from TestFlight, onboarded by the `first-launch` row, with the
  three shipping models Ready and no clone voice yet. CoreDevice reports the team's own TestFlight
  build as `builtByDeveloper: true`, so every run takes `--candidate-origin-attestation`
  (`093772a0`; `d157f3f0` fixed the field name).
- **Rows (`e7847527`):** `first-launch` (onboarding and models; no permission prompt, runs
  unattended) and `clone-voice` (the benchmark voice from a Design take; Save as Voice raises the
  Speech Recognition prompt on a fresh install, which the maintainer answers, never a row). The
  review found that blocker before the run.
- **Unattended runs, all retained** (`ios-xcui-candidate-smoke-20261024-*`): first-launch PASS,
  onboarding walked through its three pages and all three models downloaded (`195718-935a856b`);
  navigation PASS (`200241-53f60937`); long-form PASS (`200402-db93f093`); accessibility FAIL
  (`201553-857a53b4`: Dynamic Type partial on Studio and the purchase sheet, purchase-sheet contrast,
  text clipped in Design and Clone at AX-XXXL). Not a release blocker (no accessibility declaration in
  App Store Connect); the maintainer accepted it as a 3.0 known limitation, fixed after the
  submission (BKL-31). Earlier failed runs: `171623` (locked), `171715` (field name),
  `173613` (first-launch guard).
- **Resume, with the maintainer at the phone** (the prompts): `--scenario clone-voice`, answering
  Speech Recognition; `voice-lifecycle`; `record-then-play`, answering Microphone; then `modes` and
  `one-word` (or `all`), each with `--preinstalled-candidate build/artifacts/ios/release-candidate-v3.0.0-ios.3 --retain-result --candidate-origin-attestation "<statement>"`.
  The phone was locked at the end of the evening; every iOS lane now refuses a locked phone in
  seconds at its `ui-preflight` step.
- **Later that evening, unattended (no maintainer needed):** ASR-10 closed (release run
  40103005257, attestation verified); ASR-07 closed (a full Release Analyze of the candidate source
  logs 99 warnings, all registered; mlx-swift Metal header and project group classes reviewed;
  BKL-32 parks the project fix); F-05 closed (hosted macos-26 packaged-app startup smoke in run
  40020993733); RF-10 Studio checks PASS 15/15 on the published Mac source
  (`macos-xcui-smoke-20261024-205357-0952e758`), leaving its benchmark and promotion lanes; DW-02
  closed (iPhone `ui-preflight` step, shared `derive_team`, preflight refusals triage as
  infrastructure). ASR-05's read-only listing check: 3.0.0 still lacks description, keywords,
  subtitle, What's New, review notes, screenshots, an attached build and the purchase's metadata;
  writing them needs the maintainer. Parked: BKL-33 (a Mac write failure shows engine copy, seen by
  the maintainer during smoke), BKL-34 (the CLI installer round-trip test fails on macOS 27).
- **Night, after the maintainer granted Microphone and Speech Recognition once:** every remaining
  automatable row PASS on build 24 with no new crash reports: clone-voice (`223015-956cb58b`),
  voice-lifecycle (`223349-956b723a`), record-then-play (`223803-96564112`), modes
  (`224037-4321cbb4`), one-word (`225022-c52c82c5`); DA-04, F-01 and F-16 closed. A first pass under
  iPhone Mirroring failed (`221807`, `222059`, `222344`: black screenshots, a stuck keyboard, no
  playback), so XCUITest needs Mirroring ended even when CoreDevice reports the phone unlocked.
  RF-15 still holds the attended rows (the file opened during onboarding, AUD-01, on a fresh
  install; AUD-02's hand checks; the hand VoiceOver row; the offline relaunch) and two XCUITest rows
  (the ~30-take machine screen and the purchase rows, RF-02; routing corrected 2026-10-25).
- **Unpushed:** `fa94e489` through this checkpoint (`a9ddb9c6` and earlier are pushed; CI passed).

### October 24 — the iPhone 3.0 release candidate goes to TestFlight

- **Maintainer decision:** iPhone focus. TestFlight carries the 3.0 release candidate, 3.0.0 (24):
  Internal at once and submitted for Apple's beta review at once; the Public Beta group waits for RF-17's
  exact-tag promotion (maintainer, later on October 24). The What to Test notes ask for the
  last bugs and for the hardware floor (iPhone 15 Pro, 8 GB). Fast-tracked: the agent approves the
  `release` gate and distributes when processing ends.
- **Archive path repaired:**
  - `13e9d05d`: mlx-c `__FILE__` paths (ASR-07).
  - `50c347a8`: `dlopen` is the only banned loader, and the export keeps the archived executable.
  - `054b5e4a`: release evidence accepts the summary the IPA verifier really writes (ASR-10). Release
    run 40085945191 failed on that after archiving, exporting and verifying the IPA.
- **Candidate tags without a Manual-mode session (`fc8bb78e`, RF-12):** on the maintainer's request,
  `python3 scripts/ios_candidate_tag.py` signs and pushes the next `v<version>-ios.N` tag. It refuses
  unless main is pushed, CI passed and the build number is unused. A candidate push runs only the iPhone
  archive and the TestFlight upload. `v3.0.0-ios.3` on `26995f71` started release run 40103005257.
- **RF-15 journeys (`10d0d603`):** `ui_test.sh ios smoke --preinstalled-candidate DIR --scenario ROW`
  runs black-box rows on the installed TestFlight build: modes, voice-lifecycle, one-word,
  record-then-play, long-form, accessibility or all. Development-build evidence the same day: startup
  Retry and the unverified purchase locked until Restore (AUD-07), both PASS.
- **Housekeeping:** issue #108 (stale nightly) is closed. RF-10's due date moved to 2026-10-31.
- **Keep-voice capture fix proven** (macos-xcui-marketing-20261024-145129-78cc21e5): the range
  warning appeared, Keep was clicked and the designed voice saved. The test then found no "Voice
  added" alert and failed; that is parked as BKL-28.
- **State at 15:04 UTC, when the CLI session ended** (the work moves to the Claude Code desktop app):
  - Release run 40103005257 (`v3.0.0-ios.3`) was still in the Security CodeQL Swift scan, with no
    approval pending and no build 24 in App Store Connect.
  - The release rehearsal 40103799663, dispatched on `26995f71` for issue #107, was still running.
  - `main` had local commits not yet pushed (the checkpoint and roadmap updates).
- **Desktop session, 15:40 UTC:** rehearsal 40103799663 passed and #107 is closed. `main` is pushed
  with `1b1ab348` (the Claude desktop app workflow, DW-04), CI green; release run 40103005257 was still
  in CodeQL.
- **Build 24 is on TestFlight (16:44 UTC):** the `release` gate was approved at 15:42, run 40103005257
  passed end to end and build 3.0.0 (24), `e008a349-a87b-4d9d-8790-be4c0e4a687c`, went VALID. Its What
  to Test notes are in, Internal testers have it (the group has access to all builds, so adding it by
  hand is refused), and beta review is submitted (WAITING_FOR_REVIEW). No external group: Public Beta
  waits for RF-17.
- **Same session:** the README became a project page (`e52d8d1e`, RF-32), a CI stub race was fixed
  (`9ced9a37`), and RF-34 redesigns the website home page for regular users.
- **Resume here, in order** (steps 1 to 3 are done):
  1. Done: when run 40103005257 asked for the `release` environment, it was approved. The maintainer asked to
     fast-track: `gh api -X POST repos/PowerBeef/Vocello/actions/runs/40103005257/pending_deployments
     -F 'environment_ids[]=22764362076' -f state=approved -f comment="fast-track the 3.0 RC"`.
     If the run fails, fix the cause, push `main`, wait for CI, then cut the next candidate with
     `python3 scripts/ios_candidate_tag.py`.
  2. Done (see above): when `asc builds list --app 6794692745 --platform IOS --build-number 24
     --processing-state all` showed VALID, it was distributed with the build's id:
     - `asc builds test-notes create --build-id ID --locale en-US --whats-new TEXT`, where TEXT is the
       candidate text in `docs/releases/v3.0.0.md` ("TestFlight: what to test");
     - `asc builds add-groups --build-id ID --group 70bd66ea-9d12-4f77-84b5-38e7a64ed871` (Internal);
     - `asc testflight review submit --build-id ID --confirm`;
     - not yet the Public Beta group (`2375b641-4224-486c-8c0a-0fa326d7b641`): it waits for RF-17.
  3. Done: rehearsal 40103799663 passed and #107 is closed.
  4. The maintainer installs 3.0.0 (24) from TestFlight over the development build. Then run
     `scripts/ui_test.sh ios smoke --preinstalled-candidate DIR --scenario all`, where DIR is the run's
     verified `vocello-ios-release-candidate` artifact. Then by hand: the offline relaunch and VoiceOver.
  5. Last: the approved fresh install (onboarding and the file opened during onboarding).

### October 23 — Vocello 3.0.0 for the Mac and the CLI is public

- **Published 2026-10-24 00:06 UTC as the latest release** by the maintainer's route A (from the signed
  draft, without a quality-promotion record). Release run 40020993733 on `e7a8e2ae` passed Security,
  source authority, packaging (Developer ID, notarized and stapled DMGs and pkg, the runner's install,
  upgrade and uninstall), the Sparkle feed and the draft. Before publication the draft was checked
  locally: SHA256SUMS, stapled tickets, Gatekeeper, the pkg signature, attestations, app 3.0.0 (24),
  `vocello 3.0.0`, the appcast enclosure and signature, and notes identical to `docs/releases/v3.0.0.md`.
  The published DMG's Developer ID CLI passed `cli_package.py qualify`. RF-08 and RF-32 are closed.
- **The first run (39914320626 on `41a147f6`) stopped before signing:** the tag checkout's detached HEAD
  made `dev.sh status` raise in `release.sh`'s Python suite. `e7a8e2ae` fixed it and `v3.0.0` moved there
  (the maintainer authorized the agent once to sign and replace it with hooks paused in the untracked
  `settings.local.json`, restored byte-identical).
- **Developer ID Installer certificate:** issued 2026-10-23, expires 2027-11-22; its `release`
  environment secrets are set.
- **README and website (RF-32):** integrated as `3aa8f20c`..`f269bf71`; the site goes live when `main`
  is pushed. The agent worktrees `wf_9f99b8e0-4f2-1`..`4` are integrated and can be removed.
- **Next:** the iPhone submission from the same `v3.0.0` tag in the coming days (RF-10's packaged-app
  checks stay open); RF-30 and RF-31 after it.
