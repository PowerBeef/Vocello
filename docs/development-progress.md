---
status: active
owner: backend-and-platform
reviewed: 2026-10-28
summary: Current resume checkpoint; config/roadmap.json owns open work, config/roadmap-archive.json holds finished work, and older narrative lives in git history.
sourceOfTruth:
  - config/roadmap.json
  - config/runtime-refactor-contract.json
---
# Vocello development checkpoint

Start here, then follow `config/roadmap.json`'s `primaryPlan` and the
[release-first execution plan](reference/release-first-execution-2026-09.md).
This is a narrative, not a second work ledger. Product source, contracts and scripts win.
Older checkpoints live in git history (`git log -p -- docs/development-progress.md`): commit
`20533a12` holds October 23 to 25, and `a0597deb` every checkpoint before them.

## Resume now

### October 29: build 27 is in TestFlight Internal (resume here)

- **Next, in order:**
  1. Install build 27 from TestFlight and check that its launch shows no Game Mode banner (RF-37).
     On the maintainer's request: What to Test notes, beta review and Public Beta, as for build 26
     (`ios-appstore-submission.md`; Public Beta needs RF-17's promotion or a new waiver).
  2. The next announced phone window, on build 27: RF-17's records at its tag (classify the tag
     first; ui-perf with App Language on System, lang-bench and model-download are still missing),
     RF-15's launch and navigation rows, RF-35's download completing over cellular, then RF-15's
     attended rows (AUD-01's onboarding file, AUD-02's hand checks, hand VoiceOver, the offline
     relaunch).
  3. The maintainer, any time: RF-02 (the updated license agreement, which blocks submissions, the
     Paid Apps agreement, tax and banking), ASR-05's listing review, ASR-04's attestations and
     RF-38's BrowserStack trial (`scripts/farm_smoke.sh upload`, then `results`).
  4. Triage Public Beta feedback and crashes as they arrive.
- **Git:** `origin/main` is `d37583a3` (CI run 40792875949 passed): build 27 (RF-37), RF-38's farm
  smoke test and script, and RF-39's review of the docs and roadmap (closed). Later checkpoint
  commits are local.
- **Decisions waiting:** RF-12 and RF-35 passed their October 27 due dates. RF-12's last row (the
  owned export in Airplane Mode) waits on RF-02, and RF-35 on a download completing over cellular.
  Each needs a recorded decision: move the date, cut the row or close the item.
- **TestFlight:** build 27 (`v3.0.0-ios.6` at `d37583a3`, release run 40804330039 passed with the
  IPA verifier requiring `LSSupportsGameMode` NO) is VALID and in Internal testing, not yet
  submitted for beta review. Build 26 (`v3.0.0-ios.5` at `e0feaf2c`) is in Internal and Public Beta
  with beta review approved. RF-17 was waived for this Public Beta only (maintainer, October 26) and
  still gates App Review. Build 23 (2.4.0) leaves the group when it expires on October 30.
- **Phone (October 27, after RF-17's lanes):** a development build of `e0feaf2c` over TestFlight
  build 26, all three models ready, App Language on System. Reinstall the TestFlight build before a
  candidate row; a new TestFlight build's first launch shows the What to Test sheet, so tap
  Continue first.
- **In force:** 3.0 ships outside the EU (maintainer, October 27: the 27 EU territories are off,
  the account and app are declared non-trader, and the EU release is BKL-41). Nobody listens for
  3.0; machine screens catch gross failures only. RF-38's farm runs re-sign the app without
  `increased-memory-limit`, so they are clone-off exploratory evidence only.

### October 26 to 27: build 26 in Public Beta, RF-17 at its tag

- **Build 26** is build 25's product plus a test-only fix (`398709b8`) and the build number.
  Release run 40391931937 passed and the build processed VALID, with en-US What to Test notes.
  Build 25's beta review was also approved; it never joined Public Beta.
- **Build 27 (RF-37, maintainer decision October 27):** build 26 shows the Game Mode banner at
  every launch, because the iPhone 15 Pro gate (`iphone-performance-gaming-tier`) makes iOS treat
  Vocello as a game. The Info.plist sets `LSSupportsGameMode` to NO, pinned by the eligibility
  contract and the archive verifier. RF-17's records and RF-15's launch and navigation rows rerun
  on build 27's tag.
- **RF-17 at the exact tag (iOS 27.0.1):** the canonical UI benchmark
  (`ios-xcui-benchmark-20261027-175531-87319beb`, 29 takes), retained memory and the three engine
  runs PASS. Against 2.4 on the same iPhone 17 Pro: decode speed within ±5% in the UI matrix and
  5–10% faster in the memory and engine lanes; first audio about 60 ms later for Built-in Voice and
  Voice Design (the whole-script read), unchanged for Clone; memory held after a take 1–9% lower
  with no within-mode growth; UI-matrix peaks mixed (−10% to +18%) under iOS 27's larger process
  limit (8,192 MB against 6,144 MB). ui-perf (BKL-42) and lang-bench (BKL-43) failed on harness
  issues. RF-17 needs seven iOS records, not five: `classify` adds `ios-language-benchmark` and
  `ios-delivery-benchmark`, and no iOS lane produces the delivery record yet, so no iOS manifest
  validates until a lane or a recorded contract decision covers it.
- **RF-12 and RF-15 on build 26:** installed from TestFlight over the development build with
  History and Saved Voices intact, and the navigation row passed
  (`ios-xcui-candidate-smoke-20261027-135949-5fe567b6`).
- **Model-download lane:** the bottom row's progress bar sat under the tab dock once the cellular
  switch lengthened Voice Models (`ios-xcui-model-download-20261026-182637-177434c3`, retained).
  The test now reveals the bar before capturing it (`398709b8`); the proof run
  `ios-xcui-model-download-20261026-185315-4d030b9e` PASS, no findings.
- **RF-35, attended:** on 5G with no Wi-Fi and the switch off, a Voice Design download waits. It
  shows 682.3 MB (33%) from the start because the speech tokenizer, identical in every model, is
  reused from an installed model with no network transfer (the display is BKL-39). With the switch
  on, a download progressed over cellular, then the maintainer stopped it because coverage there is
  weak; a completion over cellular is not yet observed.
- **RF-36 closed:** all ten languages and the dialog in the String Catalog, shipped in builds 25
  and 26.
- **First beta report (build 23, no crash submissions):** a tester typed a voice description into
  Design's script field and Generate never ran; 3.0 still dims Generate without a visible reason
  (BKL-38, parked). The App Review notes draft now explains Design's voice description chip
  (ASR-05).
