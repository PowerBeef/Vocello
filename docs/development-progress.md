---
status: active
owner: backend-and-platform
reviewed: 2026-11-27
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

### November 26 (`RF-71` CLOSED — Vocello & `vocello` CLI `3.2.0` live public release; `RF-68` CLOSED): ready for Phase 5 (`v3.2.0-ios.1` → `RF-16`)

**Workspace & Git state:** **Vocello & `vocello` CLI 3.2.0 (build `32`) are live and public** from
signed tag `v3.2.0` at `33e65c15` (`Release` `45914974565` PASS, `Promote verified release`
`45933267704` PASS). `RF-71`, `RF-68`, `RF-69`, `RF-70`, `RF-54`, `RF-57`, and `RF-73` are all
closed (`done`). Next focus is **Phase 5 (`v3.2.0-ios.1` → `RF-16` iOS App Store submission)**.

**Shipped `3.2.0` (build `32`) milestones (2026-11-26, Xcode `27.2` / Swift `6.4.2`):**

- **Mac/CLI 3.2.0 build, qualification & publication (`90933c27`..`33e65c15`):**
  - Live streaming preview playhead fix (`072d1bd7`, `Reviewed-by: vocello-swift-review`), Mac UI
    smoke (`d223bac9`, 16/16), publication flip (`docs/releases/v3.2.0.md`,
    `public-product-facts.json`, 23 README SVGs, `README.md`, `website/` 52/52 Playwright).
  - CI & release automation hardening: pinned `CodeQL (swift)` in `security.yml` to `macos-26` /
    Xcode `26.6` with `timeout-minutes: 150` (`7edccaa9`, `726ea823`), fixed `AudioPlayerLivePreviewTests`
    TSan seek tolerance (`a9a80ffd`), isolated `HooksWiringTests` from detached-HEAD release checkouts
    (`33e65c15`), and added fail-closed `force_ask`-gated `scripts/release_tag.py` (`5467a913`) and
    `scripts/upload_promotion_manifest.py`.
  - **Exact-tag `v3.2.0` (`33e65c15`) Mac promotion (7/7 PASS, `Xcode 27.2`, `dirty=False`):**
    `macos-ui-benchmark` (`9759f6b1`, 29/29, 0 refused, max stall `212 ms`), `macos-ui-performance`
    (`ddd74c0d`, 12/12), `macos-model-download-lifecycle` (`3eb709aa`, 2.23 GB verified),
    `macos-engine-benchmark` (`611b9e40`, `GATE: PASS`), `macos-retained-memory` (`77299416`),
    `macos-language-benchmark` (`0c1e793d`, 23/23), `macos-delivery-benchmark` (`141b516b`, 5/5).
    `quality-promotion.json` validated (`963c57ff`) and signed CLI candidate passed
    `cli_package.py qualify` on `Vocello-macos26-cli.dmg`.
  - **Live public release (`v3.2.0`):** `Release` `45914974565` (CodeQL Swift 72m45s, Developer ID +
    Apple notarized DMG/CLI pkg 47m04s, iOS compile-safety 16m24s, Sparkle appcast 31s, draft 56s)
    and `Promote verified release` `45933267704` (35s) both succeeded.
- **Physical-iPhone 17 Pro 3.2.0 build `32` window (`79392a08`, `fa32b106`, `277ec13d`, closing `RF-68`):**
  - **UI benchmark PASS** (`141ece72`, 29/29, 0 refused, canonical, warm median RTF `0.554`, peak
    phys `2.31 / 2.75 / 3.56 GB`), **retained memory PASS** (`6d5ced96`, 0 warnings — closed `RF-68`),
    **UI perf PASS** (`2f1ecfc4`, 12/12), **localization PASS** (`b396df56`, 35/35 screenshots),
    **studio-layout smoke PASS** (`ca32c92b`, 5/5 screenshots), 3-minute Auto-Lock restored (`56cd3e62`).

**Next — Phase 5 (`v3.2.0-ios.1` → `RF-16` iOS 3.2.0 App Store Submission):**

1. **Completed 2026-11-27 (`RF-62` CLOSED; `RF-02` account prerequisites Active):** Paid Apps
   Agreement, tax forms, and banking are now **Active** in App Store Connect and Apple Small
   Business Program enrollment is submitted (redacted; private receipts off-Git). `RF-62` is closed:
   Apple's Nov 16 descriptors (`Shared Location = No`, `Dating and Relationships = No`) were saved
   keeping Age Rating `13+` (`THIRTEEN_PLUS`), verified via read-only `asc age-rating view`
   readback. Only the `Design & Clone Export` IAP review screenshot from processed `3.2.0`
   TestFlight (`RF-12`) remains on `RF-02`.
2. **Cut & upload `v3.2.0-ios.1` (`RF-12`):** run `python3 scripts/ios_candidate_tag.py` (when ready)
   → approve `archive-ios` in `release.yml` → install processed TestFlight build on paired iPhone.
3. **Grouped iPhone acceptance & submission (`RF-15`, `RF-17`, `ASR-05`, `RF-66`, `RF-65`, `RF-63`, `ASR-09`, `RF-16`):**
   run `RF-15` TestFlight acceptance + `RF-17` exact-tag iOS promotion + 6.3-inch screenshots +
   `RF-66` demo video → AWS Device Farm iPhone 15 Pro (`RF-65`) → ASC metadata/IAP/review notes
   updates → `ASR-09` 24h proof → `RF-16` App Review submission.
