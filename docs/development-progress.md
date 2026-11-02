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

### November 1: a dated path to App Review on November 12 (resume here)

- **Next, in order** (maintainer decision of November 1, recorded in the release plan):
  1. The maintainer, by November 5 to 6: RF-02's remaining account steps, which activate the Paid
     Apps agreement (status and details in the maintainer's private record, never in Git); ASR-02
     and ASR-11's App Privacy readback in the browser, which needs a fresh App Store Connect sign-in
     in Chrome.
  2. One phone session on build 29 (`v3.0.0-ios.8`), after RF-02, by November 9: RF-17's six
     records and its manifest, RF-15 including the purchase rows, AUD-01, AUD-02, AUD-07, AUD-09,
     ASR-06, RF-35's cellular download, RF-12's Airplane Mode export and ASR-05's screenshots.
     About 3 to 4 hours, mostly unattended; Mac quiet, phone unlocked with Auto-Lock off.
  3. By November 12, on the maintainer's go: ASR-09's North America download proof, then the App
     Review submission (RF-16). RF-17's records must be at most 7 days old at validation.
- **Done since October 30:** most of RF-02's account steps (private record). On November 1, ASR-04
  attested and closed; ASR-05's en-US listing text and the App Review contact and notes entered in
  App Store Connect and read back; build 29 attached to version 3.0.0, with no export-compliance
  question left. RF-10 closed by decision; RF-23, DW-04 and RF-38 parked until after the submission. The Mac
  smoke on main passed 15/15 on Xcode 27.2. The App Store Connect audit (ASR-11) lists what
  version 3.0.0 still lacks: listing text, screenshots, review details, an attached build and the
  purchase's metadata.
- **Build 29:** `v3.0.0-ios.8` at `a60dd204` is in TestFlight (release run 41079341984). Its
  release evidence is kept in `build/artifacts/quality-promotion/release-v3.0.0-ios.8` (the GitHub
  artifact expires November 13). Build 28's upload timed out in the archive step (45 minutes is
  tight); build 29 replaces it. Its only RF-17 attempt so far, model download on October 30, failed
  on a CoreDevice launch error; replug the phone if it repeats.
- **Phone:** UI Automation re-enabled after the Xcode 27.2 update; development builds from the
  October 30 lanes may be installed, so reinstall TestFlight build 29 before a candidate row and
  tap Continue on its What to Test sheet.
- **Mac:** Xcode 27.2 with the iOS 27.2 component. The ad-hoc test build asks for speech
  recognition again after every clean rebuild (BKL-51); the maintainer clicks Autoriser.
- **TestFlight:** builds 26 and 27 are in Internal and Public Beta under the RF-17 waiver for the
  Public Beta only; RF-17 still gates App Review.
- **In force:** 3.0 ships outside the EU (BKL-41 holds the EU release). Nobody listens for 3.0;
  machine screens catch gross failures only. RF-38's farm runs are exploratory only.

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
