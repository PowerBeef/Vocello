---
status: active
owner: backend-and-platform
reviewed: 2026-10-18
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

### October 19 — the strictness settings are on; P2-5's seam suites land (resume here)

`main` is pushed through `26c419ce`; the P3-5 commits after it are local. Push CI is green on
Xcode 26.6.

- **Landed today:**
  - **P2-5 test adequacy (DW-03):**
    - an injectable allocator control keeps the core tests off MLX (`e124f375`);
    - seam suites for the model-load coordinator and the runtime;
    - warm and prime fakes that fail inside the body (`7fe58fa2`);
    - a nightly shipped-configuration run (`dfb51453`), which also stops the runtime suite
      always building instrumented.
  - **P3-3 (DW-04):** strict memory safety (`4c464df3`, with `@safe` forwards for the five
    calls Swift 6.4 marks safe and 6.3 does not: `2375922b`, `d2cfb45c`) and
    NonisolatedNonsendingByDefault (`50af9a6d`, 711 sites kept `@concurrent`).
    - The UI stall gate passed on the NonisolatedNonsendingByDefault commit: a maximum of
      460 ms against the 600 ms limit.
    - CI's compile logs show both settings applied on 26.6.
  - **Enhanced Security trial (DW-04):** `scripts/build.sh cli-enhanced-security` builds an arm64e
    CLI with `ENABLE_ENHANCED_SECURITY` in its own arena (`49702a2c`). MLX builds, and the takes
    pass Fast QC at the regular speed with 0.5–2% more peak RSS. This was exploratory, not a
    measured lane. The hardened-process entitlements and the apps wait for the submission.
  - **P2-3 step 1 (DW-03):** the CLI's runtime and parsing became `VocelloCLICore`, which the tests
    import instead of compiling by path (`cd4843eb`). Step 2 waits for the submission: the Mac-only
    files depend on shared by-path code that has to move first.
  - **P3-5 (DW-04):** the inline Python of `macos_test.sh` (`349ddc34`) and the shared steps of
    `ui_test.sh` (`da0200b1`) became tested modules. Each matched the original output on
    retained artifacts and in a differential run (1,566 checks). `dev.sh test --only X --repeat N`
    hunts flaky tests (`68c796d9`).
  - **vDSP declined after measurement:** the assembly's per-sample loops cost about 28 ms per
    10 minutes of audio at -O, against about 186 s of generation.
  - **DW-01 closed:** CI proved the failing-test summary and the drifted-cache re-save.
- **Pinned defects:** strict expected failures pin B-02 (ER-06) and a new BKL-20, where a rebuilt
  overlay trusts weights that changed in place. B-04 is pinned as current behaviour (ER-02).
- **Fixed lanes:**
  - The Pyright gate counted Linux-only duplicates (`2894a5c1`).
  - The macOS UI benchmark ran its checker under a `python3` without numpy (`d85aadd9`).
    Its run was recorded as failed, then passed on re-check; nothing was published.
- **Next:**
  - Push the P3-5 batch and watch CI.
  - The iOS-only lane snippets, `ios_device.sh`, and P1-2's and P1-15's iPhone halves wait for an
    iPhone window. DW-02 is parked until then: P1-2's Mac half was already met, with the
    `ui-preflight` failing before the build about 1 s into the run.
- **Still waiting on an iPhone window:** the iOS runtime proof of the Observation migration and
  of the strictness settings.

### October 18, evening — the workflow programme runs alongside the release

`main` is pushed through `1b02555f`; about 50 local commits wait for the maintainer's push request.

- **Maintainer decisions (2026-10-18):**
  - The audit runs now as DW-01 to DW-04 in the release plan, with the in-flight cap raised to 8.
  - Refactors land one at a time.
  - Periphery, Pyright in CI and website type checks are approved.
  - CI keeps Xcode 26.6 as the required gate.
- **Landed:** the roadmap notes of DW-01 to DW-04 carry each item's commit. This session landed:
  - `@Observable` view models (`1406ebaf`);
  - `Mutex` in place of `NSLock` (`b2d1e9c0`, `89ba5cf4`);
  - InferIsolatedConformances (`335bac7d`);
  - the Pyright, SwiftLint and website gates;
  - the Periphery nightly;
  - the migrate-report fix (`e32fb52f`).

  All 15 macOS smoke journeys pass on the Observation tree. The iOS side compiles, but its runtime
  proof waits for the next announced iPhone window.
- **After the next push:**
  - Confirm that CI's Xcode 26.6 compile carries `-enable-upcoming-feature InferIsolatedConformances`.
    Xcode ignores a setting it does not define.
  - Confirm that the new SwiftLint, Pyright and website gates pass on the runners.
- **BKL-19:** after each rebuild, the ad-hoc-signed UI-lane app asks again for Speech Recognition.
  Answer the dialog, or the dialog covers the window and the smoke run fails.
- **Next (DW-03 and DW-04):**
  - NonisolatedNonsendingByDefault (796 sites in the macOS migrate report) and strict memory safety
    (407 sites), both behind the stall gate;
  - an Enhanced Security trial;
  - fewer `AnyView`;
  - P2-3, a shared framework;
  - P2-5, the test-adequacy seams;
  - P3-5, lane orchestration in Python.
- The local arenas are warm again. The RF-18 E4 note below still applies.

### October 18 — workflow audit saved; the local build arenas are cold

`main` is pushed through `1b02555f`; the release state is unchanged from the October 17 entry below.

- **Workflow audit:** [docs/audits/2026-10-18-dev-workflow-audit.md](audits/2026-10-18-dev-workflow-audit.md)
  holds the verified findings and the phased programme. It is recommendations only: nothing is
  scheduled until the maintainer picks a phase, and picked items after the freeze join the release plan.
- **Cold arenas (audit W-13):** every `build/cache/xcode/*` root vanished at 21:15 EDT on October 17
  while the disk was 98% full, most likely macOS's low-storage purge. This corrects the earlier report
  that the build caches were untouched. The repository cleaner only dry-ran, and the models, QC v2
  caches, RF-18 data and corpora are intact. `build/vocello` and `build/Vocello.app` dangle. The next
  `check` regenerates the project, and the first native build is cold, so it is never a measurement.
- **RF-18 E4:** the resume script finds no CLI with the screen's digest. It rebuilds
  `cli-optimized` at HEAD and records the new digest in its driver log; note that in the E4 result.

### October 17, early morning — the freeze waits for an iPhone window; backlog work without the iPhone

On local `main`, not pushed (pushes wait for the maintainer's request).

- **Maintainer decisions (2026-10-16, in `focusLock`):** the iPhone proofs of BG-01, CONV-21 and RF-18
  stay before the freeze, so the October 23 freeze needs an iPhone window the maintainer announces;
  the backlog items that need no iPhone may be fixed now, each closed in the change that fixes it.
- **Closed:** BKL-17 (the QC v2 lanes run under the selected Python and fail before generating
  without numpy; RF-15's language bench needed it), BKL-13 (Mac Saved Voices Delete waits for a
  take, a Studio Clone take still priming, a line batch or a long-form project, and releases the
  retained project that reads a deleted voice) and BKL-15 (Saved Voices' empty and error states stay
  inside the window; new `ui_test.sh macos smoke --scenario saved-voices-states`).
- **In part:** BKL-09 (new takes are named `<stamp>_Vocello.wav`, History uses SQLite secure delete,
  the app ships no developer README; the iPhone share of older takes, SEC-3, SEC-7 and
  `get-task-allow` remain) and BKL-12 (the DMG's intermediate image is sized from its payload; it
  closes after the rehearsal passes on three consecutive pushes). New parked line: BKL-18.
- **ER-13:** the v0.1.5 upstream review point, a banner on the historical iPhone memory figures and
  the artifact provenance in `model-delivery.md`. Pass 2 follows the RF-18 follow-up screen.
- **RF-18 follow-up screen** (pre-registered in the engine audit, A2), paused at the E2/E4 boundary
  with six of seven arms done (failed long-form projects of 56): C0 9, C1 2, C2 15, C4 7, E0 0, E2 0.
  The control reproduced; C1 (subtalker at the reference 0.9/50/1.0) passes its rule, C2 (budget 200)
  fails it, and D2 waits on E4. Resume: `ARMS=E4
  build/private/qc/rf18-followup/tools/rf18_followup_resume.sh` (about 27 minutes; it skips finished
  projects and reuses the screen's CLI binary when its digest still matches), then `python3
  build/private/qc/rf18-followup/tools/rf18_followup_analyze.py`. Then adopt per the rules: C1 changes
  the subtalker defaults for Balanced and Consistent (`UnsafeSpeechGenerationModel`), D2 flips
  `filtersEOS`; if both pass, a combined Consistent arm must fail at most one project more than C1
  before the combination ships; record the result in the audit (A2), RF-18, ER-05 and the release notes.
- **Owed after the screen:** CONV-21's Mac smoke lanes (`scripts/ui_test.sh macos smoke`,
  `--scenario long-form`, `--scenario long-form-recovery`).
- **Next iPhone window, in order:**
  1. `scripts/ios_device.sh preflight`
  2. `scripts/ui_test.sh ios smoke`: CONV-21's iPhone smoke on the new MLX, and the long-form
     journey pinned to Expressive (RF-18's iPhone scenario); it also exercises the new take names.
  3. `scripts/ui_test.sh ios smoke --scenario background-warmup` (BG-01).
  4. `scripts/ios_device.sh memory --voice-id <benchmark clone voice>` (CONV-21's memory benchmark).
  5. `scripts/dev.sh triage <smoke run dir> --json` for the first take after the update (the
     one-time Metal compile, F-05).
- **Freeze day:** a Security run on the exact freeze commit (the weekly run is on Tuesdays, so a
  dispatch on request), ASR-08's manual build-24 check, the push, and `focusLock.freeze`.

### October 16, night — RF-19 closes; BG-01, the MLX refresh and the model research land on the Mac

All on local `main`, not pushed (pushes wait for the maintainer's request). The iPhone stayed
unavailable and no Mac XCUITest ran.

- **RF-19 closed on the Mac:** the four install fixes (NET-3, E-02, NET-1, E-01) plus a review
  follow-up (a Retry checks space only for the bytes it still needs; a stale artifact's staging is
  discarded; the unexpected-stop row is localized). Device proof: RF-15's onboarding and download
  row. The integrated agent branch `worktree-agent-a3e1e1ebe4bc3aef0` remains; deleting it needs
  `git branch -D`, the maintainer's call.
- **RF-18 decided:** the pre-registered Mac screen does not adopt full-text conditioning (D1): D1-on
  failed 3 of 23 long segments, D1-off 2 of 27, all under Consistent, Expressive clean, Fast QC
  refused them all. The Consistent stall is a 3.0 known limitation in the release notes; the
  long-form smoke now pins Expressive and runs alone (`ui_test.sh ios smoke --scenario long-form`).
  For the maintainer: C-02 (shorter segments) and the subtalker hypothesis on ER-05.
- **BG-01's hardening landed** with tests: the foreground permit (also when the engine starts in
  the background), cancellation of the clone prime and the chained prompt prebuilds, a check before
  marking, MLX error scopes on clone adoption, persistence and replay, the CPU finite check and the
  evaluated ICL encode. Left: `background-warmup` on the iPhone.
- **CONV-21 landed:** mlx-swift 0.32.3, mlx-swift-lm 3.32.3, swift-transformers 1.3.5 and
  swift-huggingface 1.0.0 with their prerequisites. A same-host A/B kept RTF, memory and audio QC
  unchanged; the warm first chunk rose 146 → 155 ms, and the first cold run paid a one-time Metal
  compile, so prewarm now also runs the production sampler. Gate baseline re-pooled, memory
  qualification, a 336-take qc-takes screen and `dev.sh ci` (TSan included) pass; seeds changed
  (release note). Left: the Mac smoke lanes and the iPhone checks.
- **ER-13:** the sourced research report
  ([`2026-10-17-qwen3-tts-model-research.md`](audits/2026-10-17-qwen3-tts-model-research.md)) and
  docs pass 1, which corrected the wrong model facts in the guides. Pass 2 follows the freeze
  decisions.
- **Queued for the next iPhone window:** the full smoke, `--scenario long-form`, `background-warmup`,
  an iPhone memory benchmark on the new MLX, and the first take after the update (one-time compile).
