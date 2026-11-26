---
status: active
owner: backend-and-platform
reviewed: 2026-11-26
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
`0a63f634` holds November 16 through November 25 (`RF-68`–`RF-73`), `3eeed981` holds October 26
through November 15, `20533a12` holds October 23 to 25, and `a0597deb` every checkpoint before them.

## Resume now

### November 26 (Phase 4 `RF-71` Option A CodeQL/TSan recovery + physical-iPhone 3.2.0 proof closing `RF-68`): ready for maintainer re-tag of `v3.2.0`

**Workspace & Git state:** Local `main` carries all Phase 4 (`RF-71`) Mac/CLI 3.2.0 build `32`
work (`b9d46ec4`), the Option A `Security / CodeQL (swift)` `macos-26` / Xcode 26.6 pin
(`7edccaa9`), physical-iPhone 3.2.0 qualification records (`79392a08`, `fa32b106`, `277ec13d`), and
the `AudioPlayerLivePreviewTests` TSan seek tolerance fix. `RF-68`, `RF-69`, `RF-70`, `RF-54`,
`RF-57`, and `RF-73` are closed (`done`); `RF-71` is `in-flight` pending green `Security` + `CI`,
maintainer replacement of the unpublished `v3.2.0` tag, `release.yml` draft, and the exact-tag
7-lane Mac promotion sitting.

**Landed & verified milestones (2026-11-26, `3.2.0` build `32`, Xcode `27.2` / Swift `6.4.2`):**

- **Mac/CLI 3.2.0 pre-tag qualification, live preview fix & publication flip (`90933c27`..`b9d46ec4`):**
  - Bumped `project.yml` to `3.2.0` build `32` (`release_build_number.py`: `32 > 31`), reseeded
    `mac-gate-bench.json` (warm RTF `0.289`), passed `gate` (`fa2d5c2c`), `memory` (`c3f4d2b1`),
    `lang-bench` (`51d3f1ff`), `delivery` (`fc1f5bbc`), `release-readiness`
    (`release-readiness-20261126-114535`), live preview playhead fix (`072d1bd7`,
    `Reviewed-by: vocello-swift-review`), `macos benchmark` (`ea3610e8`, 29/29, warm RTF `0.308`),
    `macos perf` (`3e754107`, 12/12), `macos smoke` (`d223bac9`, 16/16 with live preview
    screenshots `045` & `046`), publication flip (`docs/releases/v3.2.0.md`,
    `public-product-facts.json`, 23 README SVGs, `README.md`, `website/` 52/52 Playwright), push
    `CI` (`45864386843`, 9/9) and `Release rehearsal` (`45864386800`, 4/4).
- **Option A `v3.2.0` release recovery (`7edccaa9` + TSan test fix):**
  - First `v3.2.0` tag (`45870657481`, no draft/artifacts created) failed in `Security / CodeQL
    (swift)` on `xcode-27` (Apple removed `x86_64` slices on macOS 27 / Xcode 27). Pinned only
    `CodeQL (swift)` in `.github/workflows/security.yml` to `macos-26` / Xcode `26.6` (`codeql`
    group in `config/toolchain.json`), keeping all build/test/release lanes on `xcode-27` / `27.2`.
  - Widened the live `AVAudioPlayer` forward-advancement tolerance after `seek(to: 0.05)` in
    `AudioPlayerLivePreviewTests` (TSan overhead had shifted `0.05` by `+0.0017` in `45876015605`).
- **Physical-iPhone 17 Pro 3.2.0 build `32` window (`79392a08`, `fa32b106`, `277ec13d`, closing `RF-68`):**
  - **UI benchmark PASS** (`ios-xcui-benchmark-20261126-185008-141ece72`, 29/29 takes, 0 refused,
    canonical; warm median RTF `0.554`; peak physical footprint Built-in `2.31 GB`, Design
    `2.75 GB`, Clone `3.56 GB`).
  - **Retained-memory qualification PASS** (`ios-memory-qualification-20261126-191012-6d5ced96`, 0
    warnings; Custom `2297 -> 1855 MB`, Design `2096 -> 1851 MB`, Clone `3554 -> 2102 MB`) — closed
    `RF-68`.
  - **UI performance PASS** (`ios-xcui-perf-20261126-191957-2f1ecfc4`, 12/12).
  - **Localization PASS** (`ios-xcui-localization-20261126-193513-b396df56`, 35/35 screenshots
    including 3.2.0 About / Report an Issue in English, French, and AX-XXXL).
  - **Studio layout smoke PASS** (`ios-xcui-smoke-20261126-194417-ca32c92b`, 5/5 screenshots
    including Korean long-form caution); 3-minute Auto-Lock restored (`56cd3e62`).

**Next — Remaining Phase 4 (`RF-71` Option A re-tag & promotion) & Phase 5 (`v3.2.0-ios.1` → `RF-16`):**

1. **Option A re-tag (`RF-71`):** once `Security` and push `CI` are green on `main`, maintainer
   deletes the unpublished `v3.2.0` tag, re-signs `v3.2.0` on the green `main` tip, pushes
   `v3.2.0`, and approves `release.yml` (`package` & `sparkle-feed` jobs) to produce the verified
   draft release.
2. **Exact-tag Mac promotion sitting (`RF-71`):** on clean `v3.2.0` tag checkout, run the 7
   required Mac promotion lanes (with explicit authorization for the ~2.23 GB
   `macos-model-download-lifecycle` download) + `cli_package.py qualify` on the signed CLI candidate
   → assemble & upload `quality-promotion.json` → maintainer approves `promote-release.yml` → close
   `RF-71`.
3. **Maintainer web-portal items (anytime before iOS submission):** activate Paid Apps Agreement +
   tax/banking (`RF-02`, active 24h+ before submit) and set `Shared Location = No` / `Dating and
   Relationships = No` in App Store Connect Age Rating (`RF-62`).
4. **Phase 5 (`v3.2.0-ios.1` → `RF-16`):** Cut `v3.2.0-ios.1` → grouped iPhone window
   (`RF-15`/`RF-17` + `RF-72` 30-take audit + 6.3-inch screenshots + `RF-66` demo video) → AWS
   Device Farm iPhone 15 Pro (`RF-65`) → remaining authorized ASC updates (`3.2.0`, screenshots,
   IAP review screenshot + attach, `RF-63` Review Notes, `RF-62` Nov 16 readback) → `ASR-09` 24h
   proof → `RF-16` submission.
