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

### November 26 (Phase 4 `RF-71` Mac/CLI 3.2.0 pre-tag qualification, live preview fix & publication flip complete on local `main`): ready for maintainer push & signed `v3.2.0` tag

**Workspace & Git state:** Local `main` ahead of `origin/main` `3dd764c6` with all Phase 4 (`RF-71`)
Mac/CLI 3.2.0 build `32` commits (**unpushed** — awaiting explicit maintainer push request), 0
linked worktrees, 0 active builds/tests/benchmarks. Phase 3 (`RF-70`, `RF-54`, `RF-57`) and `RF-73`
are closed (`done`); `RF-71` is `in-flight` pending maintainer push, CI, signed `v3.2.0` tag,
`release.yml` draft, and the exact-tag 7-lane Mac promotion sitting.

**Landed & verified Phase 4 milestones (2026-11-26, `3.2.0` build `32`, Xcode `27.2` / Swift `6.4.2`):**

- **Version bump & contracts (`90933c27`):** bumped `project.yml` to `MARKETING_VERSION: "3.2.0"`,
  `CURRENT_PROJECT_VERSION: "32"` (`release_build_number.py check --tag v3.2.0` PASS: `32 > 31`),
  updated `third-party-attribution-policy.json`, `third_party_attributions.json`, all 8 CLI v1
  contract examples, and regenerated `QwenVoice.xcodeproj/project.pbxproj`.
- **Headless Mac 3.2.0 benchmarks & gates (`7ca406b1`..`58bd3678`):**
  - Reseeded `benchmarks/baselines/mac-gate-bench.json` from 3 consecutive clean runs on `90933c27`
    for `RF-69`'s `.hybrid` telemetry tier (warm RTF `0.289`, first chunk `166.0 ms`, MLX peak
    `2227.1 MB`) and passed confirming `gate` (`mac-gate-bench-20261126-081917-fa2d5c2c`, warm RTF
    `0.2892` / `+0.05%`).
  - Retained-memory qualification PASS (`mac-memory-qualification-20261126-082054-c3f4d2b1`;
    Built-in peak `2.34 GiB`, Design `2.79 GiB`, Clone `4.12 GiB`, warm retained `2.87 GiB`).
  - 10-language benchmark PASS (`mac-lang-bench-20261126-082230-51d3f1ff`; 23/23 takes, `hint_gate`
    & `spoken_content` PASS, same 2 advisory Spanish cadence warnings as 3.1).
  - Delivery benchmark PASS (`macos-engine-20261126-082625-fc1f5bbc`; 5/5 takes, 0 warnings).
  - `macos_test.sh release-readiness` PASS (`release-readiness-20261126-114535`; 39/39 contracts,
    full Python suite, signed `Vocello.app`, Core/Runtime tests, 0 crashes).
- **Live streaming preview playhead fix (`072d1bd7`, `Reviewed-by: vocello-swift-review`) & Mac UI acceptance (`7e20e070`..`78e91cb5`):**
  - Fixed live preview playhead timer starvation (idempotent `startTimer()` + guarded
    `appendLiveChunk`) and monotonic progress across chunk arrivals and `.live → .complete` handoff
    in `AudioPlayerViewModel`, `MacStudioPlayerCard`, and `MacInlinePlayerCard` (14/14 unit tests).
  - Added lane-owned `QWENVOICE_MODEL_UPDATE_AUTOSTART` to `LANE_OWNED_RUNTIME_OVERRIDES`
    (`7e20e070`).
  - **UI benchmark PASS** (`macos-xcui-benchmark-20261126-154113-ea3610e8` on `072d1bd7`, paired
    with `a9057aef`; 29/29 takes, 0 refused, max stall `250 ms` vs `600 ms`, warm median RTF
    `0.308`; pooled chart medians: Built-in `0.29–0.36`, Design `0.29–0.34`, Cloning `0.29–0.38`).
  - **UI performance PASS** (`macos-xcui-perf-20261126-155321-3e754107`; 12/12 scenarios).
  - **UI smoke PASS** (`macos-xcui-smoke-20261126-162431-d223bac9`; 16/16 tests, 1/1 playback
    capture, 3-segment long-form `149.6 s` in `46.1 s` / RTF `0.31` / `-5.18%` footprint growth),
    including new real-app `test03_GenerationCancellation` assertions and visually verified
    screenshots (`045-mac-smoke-live-preview-advancing.png`, `046-mac-smoke-sidebar-live-advancing.png`)
    confirming the elapsed timer and golden waveform bars advance smoothly while generating.
- **Publication flip (local `main`, pre-tag):** authored frontmatter-free `docs/releases/v3.2.0.md`,
  flipped `config/public-product-facts.json` to `3.2.0` / `v3.2.0`, regenerated all 23 `docs/readme/`
  SVGs (`performance.svg` `18 s` per minute of speech, `2.5–4.3 GB` peak memory), updated
  `README.md` and `website/` (`/`, `/cli/`, `/engineering/`, `/privacy/`, `/support/`).

**Next — Remaining Phase 4 (`RF-71` push/tag/promotion) & Phase 5 (`v3.2.0-ios.1` → `RF-16`):**

1. **Maintainer push & tag (`RF-71`):** push local `main` → watch `CI required` green → maintainer
   creates & pushes signed `v3.2.0` tag (`git tag -s v3.2.0 <sha> && git push origin v3.2.0`) and
   approves `release.yml` (`package` & `sparkle-feed` jobs) to produce the verified draft release.
2. **Exact-tag Mac promotion sitting (`RF-71`):** on clean `v3.2.0` tag checkout, run the 7
   required Mac promotion lanes (with explicit authorization for the ~2.23 GB
   `macos-model-download-lifecycle` download) + `cli_package.py qualify` on the signed CLI candidate
   → assemble & upload `quality-promotion.json` → maintainer approves `promote-release.yml` → close
   `RF-71`.
3. **Maintainer web-portal items (anytime before iOS submission):** activate Paid Apps Agreement +
   tax/banking (`RF-02`, active 24h+ before submit) and set `Shared Location = No` / `Dating and
   Relationships = No` in App Store Connect Age Rating (`RF-62`).
4. **Phase 5 (`v3.2.0-ios.1` → `RF-16`):** Cut `v3.2.0-ios.1` → grouped iPhone window
   (`RF-68`/`RF-15`/`RF-17` + `RF-72` 30-take audit + 6.3-inch screenshots + `RF-66` demo video) →
   AWS Device Farm iPhone 15 Pro (`RF-65`) → remaining authorized ASC updates (`3.2.0`, screenshots,
   IAP review screenshot + attach, `RF-63` Review Notes, `RF-62` Nov 16 readback) → `ASR-09` 24h
   proof → `RF-16` submission.
