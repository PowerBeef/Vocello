---
status: active
owner: backend-and-platform
reviewed: 2026-11-13
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

### November 11–13: the quality remediation's decisions, and one hybrid model (resume here)

The remediation the maintainer asked for on November 11 (RF-50 to RF-60). Nothing is pushed: `main`
is ahead of `origin/main` (`f4edb60a`) by every commit since then, and a push needs the maintainer's
word. The phone is not available, so everything ran on the Mac. This entry is written so another
session can continue from it alone.

**Next, in order**

1. RF-59's verification. The swap is on `main` (`b3b09d3c`, `d50e860b`: one `speed` variant per
   mode, the hybrid, on both platforms; [hybrid-model.md](reference/hybrid-model.md) §6). The Mac
   install is proven: `vocello models install pro_custom_speed` into a scratch data folder downloaded
   and verified the 14 files in 38 s, reclaimed a seeded retired 4-bit folder and a staged 8-bit
   download, and a seeded take passed Fast QC v10. Maintainer decision (November 13): every mode's
   retired folders go once any mode's model verifies; a rerun on the same folder then removed Voice
   Design's old folder too. The iPhone's download lane waits for the phone. Never install the hybrid
   into the canonical models folder casually (`scripts/macos_test.sh models install|ensure` and the
   Mac app's Download button do): once one model verifies, all six Speed and Quality folders there
   are reclaimed, and the quality screens and `build_hybrid_model.py` read them.
2. On a quiet host, lead only: the formal speed lane for `attn` (`scripts/pcm_identity.py`) and the
   Mac gate bench's baseline seeded again (Fast QC v10).
3. ★ The iPhone's memory and speed for `attn` (a BrowserStack App Automate farm run the maintainer
   runs, or an announced phone window), with the queued phone checks of RF-51, RF-52 (a punctuated
   enrollment), RF-58 and RF-60.
4. ★ One Mac enrollment with recognition (G-15): Speech is not allowed for the agent's shell, so the
   maintainer runs `build/vocello voices enroll … --transcribe always` once; the transcript should
   carry punctuation, its coverage stay whole on a complete clip and its confidence near the same
   clip's unpunctuated one (nothing shows how Speech times punctuation in its segments).

**Done**

- **RF-56 (closed):** document corrections. **RF-57 (done):** the repeated suites are clean apart
  from one environmental failure (BKL-72, fixed on November 13).
- **RF-51 (code complete; phone checks left):** `b876e29d`, `b308c609`, `a5bf4add`.
- **RF-50:** the encoder golden-codes pin and the paired screen `scripts/quality_screen.py`
  ([qc.md](reference/qc.md#paired-screens-for-a-change-that-alters-samples)). Screens: `clone`,
  `clone-stereo`, `clone-long`, `clone-cjk`, `clone-english` (64 LibriTTS-R references), `long-form`
  (version 2, Expressive only), `single` (Built-in Voice and Voice Design single takes) and
  `custom-short` (short Built-in Voice scripts in six Latin languages). An arm may run another
  installed variant (`--variant`), a built model (`--models-root`, `--manifest`) or another transcript
  form (`--transcript-form`).
- **RF-53 (closed):** Fast QC v9 (`278a11d7`) and v10 (`654c921e`); D1 and D6 decided. The Mac gate
  bench's baseline binds the QC version and must be seeded again (a measured lane on a quiet host)
  before its next use.
- **RF-58 (code complete; phone lanes left):** the Variation setting is retired and every take samples
  as Expressive (`0e248d2c`); fixed-seed Expressive takes are PCM-identical before and after.
- **RF-60 (code complete; the iPhone view left):** a long-form script that Auto sends as Korean gets a
  caution on both apps and a `long_form_korean` CLI warning (`a3311c09`).

**Decisions, each by a rule recorded before its arms** (`config/quality-screens.json`, which holds
every number; arms under `build/artifacts/macos/quality-screen/`)

| Change | Rule | Verdict | Default |
|---|---|---|---|
| Reproducible reference preparation (v2), two channels averaged (v3) | `reference-preparation-v2`, `reference-mixdown-average` | ADOPT, ADOPT | `a715b2ae`, `fffcc709` |
| Encoder split-half rotary (A-02) | `encoder-rotary-split-half` | INCONCLUSIVE | stays adjacent |
| Reference encoded unpadded (A-12) | `reference-padding-none` | ADOPT | `a144a489` |
| Decoder 72-frame window (A-03, RF-54) | `decoder-window-72` | INCONCLUSIVE | stays unwindowed |
| Streamed clones primed with the reference (A-04), primed state kept per prompt (A-26) | `clone-decoder-history-primed-confirm` | ADOPT (similarity +0.056) | `1a308d7e`, `321d6c77` |
| No space before a Han or kana clone target (A-11) | `icl-target-space-unspaced-scripts` | ADOPT | `0b7465a2` |
| A transcript-backed reference's edges trimmed and faded (G-07) | `reference-edges-trimmed` | ADOPT | `9db958fd` |
| Full-text conditioning for long-form segments (D1) | `long-form-full-text`, `long-form-korean-full-text` | INCONCLUSIVE, then REJECT for Korean | off |
| Japanese, East Asian and Han/kana segment budgets | `long-form-*-budget`, `long-form-han-kana-budget-confirm` | INCONCLUSIVE each (the confirmation: sign test p = 0.26 on 64 paired projects) | 300, closed |
| 8-bit code predictor (RF-55) | `code-predictor-8bit`, `long-form-korean-code-predictor-8bit` | NOT REPEATED, NOT SHOWN | 4-bit |
| The hybrid `attn` against Speed and Quality (RF-55) | `hybrid-attn-*`, `hybrid-single-model` | ADOPT on every rule; the single-model choice is `attn` | RF-59 |
| Built-in Voice falls back to Auto when it cannot detect a language (D6) | `custom-auto-fallback` | INCONCLUSIVE (7 undetected takes of 192, the rule needs 24) | English, closed |
| Enrollment transcripts keep their punctuation (G-15) | `transcript-punctuation` | ADOPT (neutral within every margin) | enrollment asks for punctuation; verification unchanged |

Each adopted default reproduces its screened arm take for take. Every saved voice's prompt rebuilds
once on first use after these commits. Consistent long-form segments sampled as Balanced
(`5a7bddce`, `long-form-consistent-talker` ADOPT) until RF-58 retired the variation the same day.

**The hybrid model (RF-55 decided, RF-59 open).** `attn` (the talker's attention at 8 bits, +176 MB,
about 5% slower) beats Speed everywhere and does not match Quality (clone similarity −0.026,
long-form error rate about twice Quality's; 65 of 72 long-form projects against Speed's 56 and
Quality's 68). On November 13 the maintainer decided that it replaces both Speed and Quality, and that
Korean long-form (6 of 12 projects) is documented and warned about up front (RF-60). Its guide is
[hybrid-model.md](reference/hybrid-model.md). At the maintainer's request the three artifacts were
published the same day from the publication build (`--publish-as`, weights identical to the screened
build); every published file matches it.

**Standing limits:** nobody listens; a pin move, a model artifact, its publication and any push or tag
need the maintainer's specific word; device checks queue for an announced phone window (RF-51's note
lists them); at most four agents, and none during a measured run.

### November 11: the overhaul measured on the iPhone 17 Pro

The maintainer opened a phone window on November 11. The headless measurements (at `3119a745`), the
UI benchmark, the long-form journey, full smoke and the frame-health lane (at `3f8fa144` and
`f6d78880`) ran on the paired iPhone 17 Pro and confirm the overhaul there. No iPhone 15 Pro is
paired. `main` is pushed up to `f4edb60a` with CI green. The earlier `c6a80dcb` stays red only
because two Linux jobs could not reach the Ubuntu package mirror.

- **Same samples (RF-44, RF-46).** 23 fixed-seed takes are PCM-identical to the build of November 3
  (`ios-lang-bench-20261111-162231-d118b261` against `20261103-183237-3c5b79f2`); the files differ
  only in their 192-byte metadata chunk. 29 more takes are identical across the diagnostic arms
  below. The language gate prints the same lines as on November 3, including its failures on fixed
  seeds.
- **Watermark.** All 23 phone-made takes read 0.999 to 1.0 under Meta's detector with the payload
  exact.
- **Speed.** A frame takes 3.5% less time on the 14 takes that ran cool in both runs (39.5 to
  37.6 ms). A cooled medium Custom take is 35.5 ms per frame, RTF 0.477. The app's CPU is busy 0.56
  of a take at QoS high, so the 17 Pro sits near the GPU-bound end, like the M6.
- **Nothing to tune in the submission layer (RF-45).** On cooled interleaved takes, 40 operations
  per command buffer is 0.8% slower than the phone's default of 20, and turning the per-chunk cache
  clear off changes nothing. No constant is set and the clear stays.
- **Heat is the larger effect.** Twenty takes back to back drift from RTF 0.55 to 0.75 at thermal
  state fair; with 75 seconds between takes the phone stays nominal at 0.48 to 0.49.
- **Memory (RF-47).** The retained-memory qualification passed
  (`ios-memory-qualification-20261111-170450-503cb136`). Against November 3, MLX's peak is 316 MB
  lower in each mode, the footprint held after a take about 215 MB lower, and the median footprint
  peak of the 23 short takes 381 MB lower. Under the iPhone 15 Pro profile (a 5,000 MB limit; GPU
  and heat are not simulated) the three modes peak at 2,132 to 2,767 MB with at least 2,233 MB of
  headroom. MLX's peak does not rise during marking (RF-48).
- **Live preview (RF-48).** The UI benchmark passed (`ios-xcui-benchmark-20261111-172017-636b2dd5`).
  Against its November 3 record the preview starts 0.5 to 0.8 seconds sooner after the first chunk
  on medium and long takes (medium Custom 1.40 to 0.63 s) and 0.1 to 0.2 seconds sooner on short
  ones, with no underrun in 29 takes. RTF is unchanged (0.53 to 0.52), and the exact footprint peaks
  are 313 to 415 MB lower.
- **Long-form.** The long-form journey passed (`ios-xcui-smoke-20261111-173732-88218ccb`), on the
  build that carries assembly v3 and the heat pause. The phone stayed cool, so the pause never
  engaged, and the project's file was not pulled for a detector reading.
- **Regression checks.** Full smoke passed (`ios-xcui-smoke-20261111-174409-5a3c5a46`). The
  frame-health lane passed twice at `f6d78880`: its first run
  (`ios-xcui-perf-20261111-175155-f5267c25`) warned on the two player scenarios because History's
  newest row was a 2-minute project left by smoke, and the rerun on a short row
  (`180357-2d245d6e`) matches November 3 with no warning (BKL-69). With a take generating, hitch
  time is 91 ms per second against 76 on November 3, inside the lane's ceilings.
- **Tooling.** `scripts/ios_device.sh` forwards MLX's three environment keys to the phone
  (`3119a745`). The cache-clear and memory-profile switches act only in a build made with
  `--device-diagnostics`; the benchmark build ignores them.
- **Not measured, and why:**
  - the acceptance and promotion rows: they belong to a candidate, and none carries the overhaul
    yet. (The UI benchmark's first attempt, `ios-xcui-benchmark-20261111-170901-04e3d785`, ran no
    test: UI Automation was off on the phone until the maintainer turned it on.);
  - the heat pause: it needs serious heat, and the 17 Pro reached fair;
  - reloads with the two-minute window: no lane holds a process idle between takes;
  - core placement of the generation thread: Instruments lists the phone as offline without a cable;
  - anything on an iPhone 15 Pro.
- **An outside report on the Qwen3-TTS integration was counter-verified** (RF-49, closed;
  [review](audits/2026-11-11-qwen3-tts-quality-report-review.md)). Its facts about the code hold.
  Measured in the Python port, the encoder's rotary fix (A-02) changes clones by nothing detectable,
  the 8-bit model beats the 4-bit one by 0.025 in speaker similarity, and an 8-bit code predictor
  alone gives +0.010 for 56 MB. It changes no code and opens no work; its recommendations are for
  the parked engine-remediation items.
- **Maintainer decision of November 11: quality remediation before the submission.** The review's
  verified findings are RF-50 to RF-56: the machine screens (RF-50), clone input correctness
  (RF-51), clone conditioning parity (RF-52), the long-form and language screens with a stop for
  runaway takes (RF-53), the decoder's 72-frame window (RF-54), code-predictor precision (RF-55)
  and document corrections (RF-56). Sample-changing changes land only behind a pre-registered
  machine screen. Publishing an artifact and moving a pin stay the maintainer's. The submission
  waits until the engine and its output are as good as they can be. The tooling the remediation
  leans on is audited too (RF-57): every screen is first run against itself. The phone is not
  available, so all of this runs on the Mac and device checks queue for an announced window.
- **Next:** RF-51 and RF-56 need no screen and go first, with RF-50 beside them; then RF-52 to
  RF-55 by their gates; then a candidate that carries the overhaul and the remediation, which needs
  green CI on `main` and the maintainer's request, and RF-15's and RF-17's rows on it.

### November 11: the overhaul's Mac half is complete

Everything in the core overhaul (RF-44 to RF-48) that needs no iPhone is implemented, measured on
the M6 and committed on `main`. Every engine change kept the samples: fixed-seed PCM digests are
identical.

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
    crop offsets the detector reads below its 0.5 threshold. Long-form assembly trimmed each
    segment's edges by arbitrary frame counts, so a long-form file read 0.67 to 0.93 with a wrong
    payload.
  - **Fixed in long-form assembly v3:** every segment keeps up to one frame (13 ms) more of its own
    leading non-speech and lands on the grid, with its pauses unchanged. Three rebuilt projects
    (Custom Speed with one and three segments, Design Quality with three) read 0.993 to 0.998
    with the payload exact.
  - **Not known:** whether Meta's own generator at 16 kHz has the same sensitivity (it needs their
    generator file), and what an iPhone's output reads. A file the user crops still has to be
    realigned by whoever verifies it (`docs/ARCHITECTURE.md`, Reading the mark).
- **Open on the Mac:** the measurements as published benchmark records (publication needs a
  request).
- **The App Review notes** say nothing about the heat pause yet.

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
