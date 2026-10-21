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

### October 21, evening — RF-26 closes; RF-27 hosts takes like the app and routes long scripts (resume here)

- **RF-26 done:** `VocelloDesktopCore` (the app's store, History records, settings keys and
  model selection, compiled by path plus `Sources/DesktopShared`) gives the CLI read-only parity:
  History list/search/show/export (refused while the app runs on the same data root until RF-30),
  settings, briefs, voices show/banks, models active/verify, languages, doctor and runtime facts in
  `capabilities` (`701c0da9` to `6950f227`, reviewed).
- **RF-27 in flight:** takes default to the app's package and variation; `generate --plan`;
  `run --request(s)` with idempotent client ids whose identity is the resolved take; `generate`,
  `batch` and `run` host the engine through `TTSEngineStore` as `MacEngineBootstrap` does; a script
  past one take runs as a long-form project through the shared `CLILongFormProject` runner
  (`d2eee3c5` to `abc3d300`). Each step had a Swift review; its findings are fixed, including a hang
  where a store refusal stranded the stream drain. Verified on this Mac: a hosted 2-segment
  long-form take (60 s of audio in 17 s) and a SIGINT that keeps the finished segment. A review of
  `01f9206f` and `abc3d300` is running. Left: long-form through `IOSLongFormCoordinator` with its
  joined-output QC, the line batch on the app's plan, the interim History write policy, the engine
  lease, NDJSON progress polish and a hosted take per mode.
- **RF-08 in flight:** the pipeline, evidence and entitlement work landed (`3acf1251` to
  `e6a0a761`); the maintainer still needs the Developer ID Installer certificate, its two `release`
  secrets and the first rehearsal.
- Local commits are not pushed; the iPhone candidate stays at `0919e998` awaiting the maintainer's tag.

### October 21, later — the CLI overhaul starts: RF-25 lands, RF-08 builds a .pkg

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
