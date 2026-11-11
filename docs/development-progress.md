---
status: active
owner: backend-and-platform
reviewed: 2026-11-11
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

### November 11: the overhaul's Mac half is complete (resume here)

Everything in the core overhaul (RF-44 to RF-48) that needs no iPhone is implemented, measured on
the M6 and committed on `main`. Commits up to `6ddfa629` are pushed with CI green; `fd019b81` to the
commit carrying this entry wait on local `main` for a push request. Nothing is measured on an
iPhone, and every engine change kept the samples: fixed-seed PCM digests are identical.

- **The regression net (RF-44).** `scripts/pcm_identity.py` captures fixed-seed PCM digests and
  compares two builds, in alternation against a preserved baseline, on the Speed and Quality models
  and on instruct-bearing and long takes. `--clamp background` keeps the bench on the efficiency
  cores, where the host bounds a frame: the stand-in on a Mac for a device whose CPU is the
  bottleneck.
- **What bounds a frame on the M6.** The host is blocked on the GPU for over half of a take, so the
  M6 is GPU-bound and no host-side change speeds it up. A frame is 20.1 ms: 16.4 ms in the step
  submit, 1.8 ms in the token read, under 1 ms of graph building. Clamped to the efficiency cores
  the same take is host-bound. Which regime each iPhone is in is the first thing to measure in a
  device window.
- **Landed, with identical samples:**
  - the rotary step and fused projections, then the code predictor's frame as one compiled
    function that samples inside it (RF-46): together about 13% faster host-bound (RTF 0.747 to
    0.652 on the clamped M6) and under 1% GPU-bound. The compiled forms' identity is measured on
    this Mac's GPU, not proven, so the digests must be recaptured on a phone;
  - the text embedding read by row from the checkpoint file (RF-47): 315 MB less resident memory
    and 315 MB off every take's peak;
  - the watermark pass without its per-window cache clears (RF-48): finalization a fifth shorter;
  - the runtime's 6,800-line file split into eight by moving lines unchanged (RF-46).
- **Landed, no sample involved:**
  - the live preview starts from the take's measured pace instead of a fixed 3.25-second buffer
    (RF-48): on the M6 the first sound comes 0.44 s sooner, with no dropouts;
  - the iPhone's two footprint bands are stated at a 6,144 MiB budget and scale to the budget the
    process measures, and a loaded model stays two minutes in the foreground instead of 30 s,
    shortened under memory pressure (RF-47);
  - a long-form run waits between segments while the thermal state is serious or critical, for at
    most three minutes, and says why in ten languages (RF-48). The Mac never pauses.
- **Measured and not changed:**
  - MLX's default of 40 operations per command buffer is the fastest on the M6, so no constant is
    set (RF-45). The phone's default of 20 measured 8 to 10% slower in the host-bound stand-in.
    `QWENVOICE_STREAM_CHUNK_CACHE_CLEAR` isolates the per-chunk cache clear for a device A/B;
  - `MLX_ENABLE_TF32=0` changes every take's samples and shows no speed difference (RF-44);
  - Quality is 46 to 57% slower than Speed on the M6 (custom medium RTF 0.405 against 0.277).
- **Judged and left out,** each with its reason in the roadmap notes: holding the watermark's
  weights between takes; the lagged token read (no regime on the Mac where it pays; decide once the
  phones' regime is measured); a compiled talker sampler; marking as chunks arrive (it would break
  the rule that marking must not raise a take's peak); judging the Metal working set against the
  measured budget (an unmeasured cancel trigger).
- **The watermark check ran on November 11 (RF-44),** with Meta's reference detector reading the
  24 kHz samples as published. Seven single takes in the shipped configuration, in three modes on
  both models, read 0.998 to 1.0 with the payload `0x56C0` exact, and so do two with
  `MLX_ENABLE_TF32=0`; takes with marking off read 0.07 to 0.11.
  - **Finding: detection depends on alignment to the mark's 320-sample frame.** Cropping a take by
    a count that is not a multiple of 320 lowers detection and flips payload bits; at 15 to 28% of
    crop offsets the detector reads below its 0.5 threshold. Long-form assembly trims each
    segment's edges by arbitrary frame counts, so a long-form file read 0.67 to 0.93 with a wrong
    payload. Realigned to its own frame, every segment reads 0.999 with the payload exact.
  - **Not known:** whether Meta's own generator at 16 kHz has the same sensitivity (it needs their
    generator file), and what an iPhone's output reads. The fix is not decided.
- **Open on the Mac:** the fix for that finding, and the measurements as published benchmark
  records (publication needs a request).
- **For the next announced iPhone window,** in this order: the take's regime on each phone (CPU
  share and QoS class of the generation thread); sample identity of the compiled frame function on
  the phone's GPU; `MLX_MAX_OPS_PER_BUFFER=40` against the default; the cache-clear switch off;
  resident and peak memory and the bands on an 8 GB phone; reloads and memory with the two-minute
  window; the preview's start and any underrun on the iPhone 15 Pro; the footprint during marking;
  the heat pause on a hot phone. The submission candidate is the build that carries these commits,
  once the phone confirms them. The App Review notes say nothing about the heat pause yet.

### November 10: no target dates, and the core overhaul comes before the submission

- **Maintainer decisions of November 10** (recorded in `focusLock.decision`):
  - The target dates are removed from the roadmap and the release. No item carries a due date;
    gates set the order of work.
  - The core overhaul of the runtime (speed and memory on Apple silicon) is performed before the
    iOS App Store submission.
  - The result must be fully App Store compliant.
  - The repository's rules are open to change where that makes the project better.
- **What that changes below.** Build 30 stays in TestFlight, but the submission candidate will be
  the build that carries the overhaul: the candidate-bound work in step 2 (RF-17's records, RF-15's
  rows and the items that ride on them) runs on that build. Step 1 (the maintainer's account steps
  and the App Privacy readback) is unaffected.
- **The overhaul's stages and gates** are in the
  [research report](audits/2026-11-10-apple-silicon-performance-research.md) (RF-43, closed). Its
  five identity-preserving stages are in the release plan: RF-44 first (instruments and the
  regression net, no product change), then RF-45 (submission layer), RF-46 (the frame pipeline),
  RF-47 (memory) and RF-48 (finalization, preview and the heat pause). Its sample-changing stages
  are not in the plan. Nothing was built or measured for the report: its estimates stay estimates
  until RF-44 produces numbers.

### November 1: the path to App Review (its dates were removed on November 10)

- **Next, in order** (maintainer decision of November 1, recorded in the release plan):
  1. The maintainer: RF-02's remaining
     account steps, which activate the Paid Apps agreement (status and details in the maintainer's
     private record, never in Git); ASR-02 and ASR-11's App Privacy readback in the browser, which
     needs a fresh App Store Connect sign-in in Chrome.
  2. A new candidate, then one phone session on it. Build 29 is no longer the submission
     candidate: RF-41 (the download prompt, `f3689d2a` and `37c16b91`) landed on `main` on
     November 7 and 10 and its phone lane passed. Done on November 10 for the tag: RF-42 is
     decided (Vocello stays iPhone-only, with a localized unsupported-device screen), the archive
     job's limits are raised (BKL-56) and the build number is 30. CI passed, and on the
     maintainer's go `v3.0.0-ios.9` (build 30) was cut at `14c51659`; its release run passed and
     build 30 is processed in TestFlight (see Build 30 below).
     On the processed build: RF-17's six records on the new tag (build 29's five expired on
     November 10, and the language record still needs a maintainer decision), RF-15's rows
     including the purchase rows (RF-02 first), AUD-01, AUD-02, AUD-07, AUD-09, ASR-06 (procedure
     in `docs/reference/privacy-storage.md`), RF-35's cellular download, RF-12's Airplane Mode
     export and ASR-05's screenshots. The due dates were removed on November 10. The phone runs a development build of `main` on System Default App
     Language: install the processed candidate and set App Language to English before its rows.
  3. On the maintainer's go, after the core overhaul: ASR-09's North America download proof, then
     the App Review submission (RF-16). RF-17's records must be at most 7 days old at validation.
- **Done since October 30:** most of RF-02's account steps (private record). On November 1, ASR-04
  attested and closed; ASR-05's en-US listing text and the App Review contact and notes entered in
  App Store Connect and read back; build 29 attached to version 3.0.0, with no export-compliance
  question left. RF-10 closed by decision; RF-23 and DW-04 parked until after the submission. RF-38 closed on November 1: after `c878917a` let diagnostics builds start without the App Group the farm's re-signing drops, the BrowserStack smoke passed on a real iPhone 15 Pro (iOS 27) and 15 Pro Max (iOS 26) (clone-off exploratory evidence; first-take peak 2.6 GB). RF-40 and the follow-up farm runs on the iPhone 15 Pro (November 2): engine RTF 1.5 to 1.6 on a first take after rest, then a steady 2.2 at nominal heat (3.2 only on a phone that ran hot); memory flat at 2.5 GB. The live preview's pause below real time is an accepted tradeoff (BKL-53 declined). The Mac
  smoke on main passed 15/15 on Xcode 27.2. Version 3.0.0 in App Store Connect still lacks the
  screenshots and the purchase's review screenshot. The accessibility declaration is voluntary
  and cannot be published before a version is live; its approved draft is in the runbook (ASR-11).
- **Build 30:** `v3.0.0-ios.9` at `14c51659` is in TestFlight, processed `VALID` on November 10
  (release run 42872878302). The archive job took 80 of its 180 minutes and its readiness step 62
  of 90; the old limits (60 and 45) would have failed it (BKL-56, closed). Its complete release
  artifact, IPA included, is in `build/artifacts/quality-promotion/release-v3.0.0-ios.9-candidate`
  with its checksums verified (the GitHub artifact expires November 24); candidate rows need
  that folder. On the maintainer's request the same day, build 30 replaced build 29 on version
  3.0.0 and got its en-US What to Test notes (3,314 characters), both read back; export
  compliance needs no answer. It is in internal testing only: no beta review submission and no
  Public Beta group. The phone still needs build 30 installed from TestFlight before its rows.
- **Build 29:** `v3.0.0-ios.8` at `a60dd204` is in TestFlight (release run 41079341984). Its
  complete release artifact, IPA included, is kept in
  `build/artifacts/quality-promotion/release-v3.0.0-ios.8-candidate` (the GitHub artifact expires
  November 13); candidate rows need that folder, since `release-v3.0.0-ios.8` lacks the IPA. Build 28's upload timed out in the archive step (45 minutes is
  tight); build 29 replaces it. Its only RF-17 attempt so far, model download on October 30, failed
  on a CoreDevice launch error; replug the phone if it repeats.
- **Phone:** on November 1 TestFlight build 29 replaced the development copy, keeping its data
  (onboarding done, 3 of 3 models Ready, the benchmark clone voice saved), and RF-15's clone-voice,
  navigation and modes rows passed on it. UI Automation needed enabling again, and a notification
  banner took a tap, so turn on Do Not Disturb before a lane. RF-17's lanes install a development
  build of the tag: run the candidate rows (the purchase rows) before them, or reinstall TestFlight
  build 29 afterwards. Since RF-38's fix (November 1) `main` carries a product change after build
  29, so the candidate rows, like RF-17's records, run from a clean checkout of the tag
  `v3.0.0-ios.8`; return to `main` afterwards.
- **Mac:** Xcode 27.2 with the iOS 27.2 component. The ad-hoc test build asks for speech
  recognition again after every clean rebuild (BKL-19); the maintainer clicks Autoriser.
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
