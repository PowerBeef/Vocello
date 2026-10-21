---
status: active
owner: backend-and-platform
reviewed: 2026-10-21
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

### October 21, later — the CLI overhaul starts: RF-25 lands, RF-08 builds a .pkg (resume here)

The maintainer asked for a full CLI: Mac-app parity, driven by agents (a JSON contract and an MCP
server), shipped as a signed `.pkg` beside the releases. The plan is
`docs/audits/2026-10-21-cli-overhaul-plan.md` (RF-25 to RF-31, RF-08 re-gated); no iPhone-compiled
file changes before the submission (`git diff --quiet 0919e998 -- Sources/iOS …`).

- **RF-25 done:** one command tree drives the strict parser, help, completions, `capabilities` and
  `config/cli-contract/v1/commands.json`; every command but `bench` speaks the v1 envelope
  (`--json`) or NDJSON events (`--ndjson`) with typed codes and exits; the contract, schemas,
  examples and additive-only baseline validate in the contract gate; every JSON caller reads
  through `scripts/lib/vocello_cli_json.py` (`26c0cee6`, `0e8eeff0`, reviewed).
- **RF-08 in flight:** `cli_package.py pkg`/`pkg-verify` build and verify an unsigned installer
  package with relative `/usr/local` links and a sealed `uninstall.sh` (`cdb5eea6`). Left: evidence
  and entitlement policy, the release pipeline, the hardened-runtime probe, and the maintainer's
  Developer ID Installer certificate with its two `release` secrets.
- **RF-26 in flight next:** `VocelloDesktopCore` and read-only parity.
- Local commits are not pushed; the iPhone candidate stays at `0919e998` awaiting the maintainer's tag.

### October 21 — the freeze moves to `0919e998`; Mac updates land

`main` is pushed through `0919e998`, the freeze commit; the freeze record follows it. The maintainer
holds the release: no tag yet.

- **RF-24 (release blocker, maintainer report): the iPhone Clone Studio matches the other modes.**
  Clone had stacked its reference transcript review under the canvas (since `46504a11`), pushing
  Generate up and squeezing the script. The review now sits at the top of the Reference panel
  (`50761bcc`, `08372fdd`, reviewed). `ios smoke --scenario studio-layout` (also part of full smoke)
  passed on the iPhone (`ios-xcui-smoke-20261021-050240-000ce5bc`): Generate sits 8.6 pt above the
  tab dock in all three modes. macOS was never affected (its review lives in a popover).
- **RF-23 (maintainer request): Sparkle updates for the Mac app.** Vocello > Check for Updates…, a
  Settings > Updates category, Sparkle's second-launch prompt, no silent installs, a signed feed
  required and updates verified before extraction; the EdDSA key is in the maintainer's keychain
  and the `release` environment. The release workflow signs the DMG and the feed in a minimal job;
  the Swift and security reviews' findings are fixed; the Mac layout lane passes; the privacy page
  names the check. Left: the release rehearsal on GitHub and one end-to-end update between signed
  builds.
- **The freeze:** the full checks pass on `0919e998` (website browser smoke included now that
  Playwright's Chromium is installed locally); `focusLock.freeze` names it.
- **Next:** the maintainer's signed `v3.0.0` tag (tag-signing key setup first), then ASR-10's signed
  archive and TestFlight (RF-12, RF-15), each on the maintainer's go.

### October 20, night — the iPhone 3.0.0 candidate is frozen at `029427c9`

`main` is pushed through `029427c9`, the freeze commit, and its push CI is green (run 39531352634); the freeze record follows it.

- **RF-22 (maintainer request): the export unlock sheet matches the app.** It opens like onboarding's
  welcome: the warm mode backdrop, a hero of a Design and a Clone waveform card with a gold export
  badge (the maintainer rejected a first pastel tile), benefit rows, the shared glass CTA, Restore,
  and a quiet footer. Strings, identifiers and purchase behavior are unchanged; the Swift review
  found no blocker and its tap-area and VoiceOver points landed (`9d6c60b1`). The iPhone purchase lane
  passed on clean `9d6c60b1` (`ios-xcui-purchase-20261021-014956-fcc2d6ac`), and the maintainer
  approved the sheet.
- **RF-09's freeze checks pass on `029427c9`:** regen clean; the full contract gate with 2,589 Python
  tests; macOS 1,522 core and 199 runtime tests and 1,522 under TSan; the Mac app (3.0.0/24), CLI,
  generic iOS and UI-test builds; lints. The website check rests on CI run 39385512938 over the
  identical `website/` tree (the local browser smoke lacks Playwright 1.64.1's Chromium). Build 24
  is unused in App Store Connect (read-only). The first attempt caught the control audit's drifted
  count (`029427c9`); a second failed on three signal-timing tests that pass alone (BKL-26). BKL-24
  and BKL-25 park the audit scanner and check-routing gaps.
- **The freeze:** `focusLock.freeze` records `029427c9`, `maxInFlight` is 2, DW-03 is parked until the
  submission, and every later commit names an item of this plan.
- **Next:**
  - The maintainer pushes the annotated `v3.0.0` tag on `029427c9`; then ASR-10's signed archive
    and the TestFlight path (RF-12, RF-15), each on the maintainer's go.
  - RF-23: Sparkle updates for the Mac app (maintainer choices: Sparkle, after the freeze, ask on
    the second launch). The EdDSA key, its GitHub secret and the appcast publication are the
    maintainer's steps.

### October 20 — BG-01, RF-18 and CONV-21 close; full text up front adopted

`main` is pushed through `8c0cadf9`, and push CI is green on it (run 39516326220, ThreadSanitizer
included). PR #110's zsh completion landed earlier in the day; #110 and #87 are closed.

- **iPhone window (iPhone 17 Pro, iOS 27.0.1, the adopted engine and the MLX refresh):**
  - **RF-18 closed:** `smoke --scenario long-form` passed (`ios-xcui-smoke-20261020-160313-80e6aba4`).
    The first attempt finished the project, then failed at History search when notifications
    interrupted the phone (`…153705-0a3bf3f5`, kept).
  - **BG-01 closed:** `background-warmup` passed with a clean crash delta (`…161737-a54444f8`).
  - **CONV-21, iPhone half done:**
    - The full iPhone smoke passed (`…162655-207aa53e`), the first full pass in 30 days.
    - The memory qualification passed: 60 MB maximum retained growth, 0.5% of RAM
      (`ios-memory-qualification-20261020-175216-613bb02a`, record `bf9d0da2`).
    - The first take after launch reached audio 0.61 s after load, so no gemv compile stall
      (`ios-engine-20261020-175501-9d08fde9`, record `3bff8143`).
  - These lanes ran the app with the Observation migration and the strictness settings in place.
- **Defects the window found, all fixed and tested:**
  - Saved-voice Clone failed on the iPhone once a voice's artifact identity changed, as the MLX
    refresh does (`6a2a29f6`, reviewed). Publication compared `standardizedFileURL` spellings,
    which drop `/private` only from existing paths, and iOS spells the App Group `/private/var`.
    A refused publication now skips the cache instead of failing the take.
  - The device-diagnostics build failed under strict memory safety (`c368d7df`).
  - Device lanes read another run's engine rows from the pulled mirror (`bd494cb7`) and counted
    Xcode 27's simulated iPhone (`f1698bd8`); the doctor's "multiple devices" error is gone.
  - `scripts/ui_test.sh ios take-variation` restores Take variation through Settings, and session
    cleanup closes a History search keyboard first (`d549d45c`). The phone is back on Consistent.
- **Auto language verified on the Mac (maintainer request):** `scripts/ui_test.sh macos auto-language`
  (`4a4c31df`, `3f134082`) passed all 17 takes (`macos-xcui-auto-language-20261020-193808-e91827da`).
  With Studio on Auto the request carries `auto`, the engine resolves the detected language and sends
  its language token, and the chip agrees, in all ten languages and in Design and Clone. Dutch, which
  Qwen3 does not speak, shows Auto: Built-in then sends English (D6, ER-05), Design sends no token.
  BKL-21 parks the receipt-validator gap the checker works around. An iPhone run waits for a window.
  Manual selection followed (`aa0adfdd`, `64fbbbc9`): 22 of 22 takes pass
  (`macos-xcui-auto-language-20261020-204002-f86c7a46`). A pinned language reaches the engine even
  when the text is in another language, and returning to Auto follows detection again.
- **Full text up front (D1) adopted for single streamed takes (RF-21; RF-20 declined first).** The
  lane's French take that whispered for 35 s had streamed its whole script during an opening sigh
  (A-01). RF-20's screen favored D1 (5 gross failures against 10 of 251 takes per arm), but its rule
  also required the Mac language bench, where D1 garbled one Japanese take
  (`mac-lang-bench-20261020-215933-4b3c7b82` against `…220248-067bb65c`), so RF-20 closed declined.
  At the maintainer's request both ASR families then scored the 496 saved screen takes under a rule
  written first: wrong-content takes fell from 31 to 16, and the maintainer adopted D1. Long-form
  segments keep trailing text (`GenerationRequest.longFormSegment`). Landed in `9cd075bd` and
  verified there: the French take replays clean, a long-form segment matches forced trailing text
  byte for byte, the auto-language lane passes 22 of 22 (`…231517-484006e1`) and the Mac memory
  qualification passes with unchanged MLX peaks (`mac-memory-qualification-20261020-233325-d9f14b0a`).
  RF-21 is done; the iPhone proof is RF-15's. BKL-22 and BKL-23 park two language-bench tooling gaps.
- **CONV-21 closed:** the full Mac smoke passed 15 of 15, attended, on clean `8c0cadf9` with no new
  crash reports (`macos-xcui-smoke-20261020-234442-98d62058`). test01's 25 minutes is its usual
  length (1,514 s on 2026-10-10): about 1,500 existence checks, no step over 2 s.
- **Next:**
  - RF-09's freeze checks run on the freeze commit (due 2026-10-23); no release-plan blocker is left
    open before them.
  - RF-15 and the items behind it run on the processed TestFlight candidate after the freeze.
  - DW-02 and P1-15's `ios_device.sh` shared library stay deferred until after the submission.

### October 19 — the strictness settings are on; P2-5's seam suites land

`main` is pushed through the documentation consolidation. Push CI is green on Xcode 26.6.

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
  - **RF-18 adopted (7a125aaf):** the follow-up screen finished. Its E4 arm and the pre-registered
    combined arm ran on a CLI that reproduced the stored control take byte for byte. C1, the
    subtalker on the reference values, and D2, EOS filtered, both pass, as does their combination
    (2 failed long-form Consistent projects of 56, against 9). The subtalker now keeps the
    reference sampling for every variation, and production filters EOS. With no knobs,
    production reproduces the screened take byte for byte. Device proof: RF-15's long-form row.
  - **`@preconcurrency` ratchet (DW-03):** 34 → 21 imports (`9fca022a`). The iOS UI bundle's four
    tolerated warnings were cleared too (`12db497c`).
  - **CONV-21's owed Mac smoke scenarios pass on the adopted engine:** `--scenario long-form`
    (3 segments, 150.7 s of audio, project RTF 0.42) and `--scenario long-form-recovery`.
  - **ER-13 closed:** the Qwen3-TTS reference docs were rewritten against the model research and the
    engine audit, with RF-18 and CONV-21 as shipped. Three documentation agents and the lead did
    this: the model reference, the prompting and 12 Hz tokenizer guides, the MLX guide and the
    package docs, ARCHITECTURE's engine sections and the package README. Links were checked.
  - **Documentation audit and consolidation (DW-04):**
    - About 40 stale or contradictory statements fixed. Release-relevant ones: the App Review
      note's model path, the App Store Connect state, the README chart record.
    - Three tooling gaps the docs misdescribed are closed: the agent guard now refuses subagent
      shell writes to the roadmap, `dev.sh ci` runs CI's lint gates, and `check --paths` scopes
      its gate.
    - `docs/reference/` went from 49 to 32 files: dead docs deleted, dated reports moved to
      `docs/audits/`, overlapping guides merged. No link is broken across the tracked Markdown.
- **Next:**
  - The full Mac smoke needs someone at the Mac: BKL-19's Speech Recognition prompt would block
    an unattended run.
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
