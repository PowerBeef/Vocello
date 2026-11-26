---
status: active
owner: backend-and-platform
reviewed: 2026-11-25
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

### November 25 (`RF-73` closed, live ASC prep applied, docs & `AGENTS.md` tightened): ready for Phase 4 (`RF-71` Mac/CLI 3.2.0)

**Workspace & Git state:** Local `main` ahead of `origin/main` `0a63f634` with the pre-3.2
documentation, `AGENTS.md`, harness, roadmap, website parity, and audit-pruning cleanup commits
(**unpushed** — awaiting explicit push request), 0 linked worktrees, 0 active builds/tests/benchmarks.
Phase 3 (`RF-70`, `RF-54`, `RF-57`) is closed with shipped `attn` retained unchanged for 3.2
(`f070f41a`), and **`RF-73` is closed (`done`)** after full phone-free, physical-iPhone, CI,
Release rehearsal, Vercel production, and manual macOS verification.

**Landed & verified milestones (2026-11-25):**

- **`RF-73` App Store 3.2.0 readiness & streamlined AI safeguards (`1363da5c..71dd7d53` on `origin/main`, strictly sample-preserving, `vocello-swift-review` approved on every Swift commit):**
  - Admitted 13 eligible 8 GB+ M-series / A17 Pro iPads in portrait compatibility mode (`4703237c`,
    `IOSDeviceEligibilityPolicy`), compiled out dormant Release diagnostics & shipping iOS
    `QWENVOICE_*` env reads (`QVOICE_DEVICE_DIAGNOSTICS`, Guideline `2.5.19`, enforced by
    `verify_ios_release_artifacts.py`), enforced `.withoutCloneEncoders`, dropped `UIFileSharingEnabled`.
  - Localized 10-language `.disallowedVoiceImitation` guardrails (`b896fce1`), scoped `Sparkle` to
    macOS only, resolved `"pending-qualified-review"` to attested ASR-04 status, added Meta
    AudioSeal (`MIT`) auxiliary attribution.
  - Shipped streamlined iOS safeguards (`da5ce80d`, `71dd7d53`): Onboarding Page 3 watermark +
    Terms/Privacy notice, one-time inline `IOSVoiceCloningConsentSheet` + passive Save Voice
    reminder (0 extra toggles, 0 Player/History AI badges), 1-tap `IOSStudioSetupPrompt`, dismissible
    multi-line `errorBar`, `IOSExportPurchaseSheet` contrast/loading-flash fix + 1-tap `Export Now` +
    `/privacy/` & `/terms/` links, `Settings → Privacy & Permissions` revocation/disclosure/watermark
    note & `Terms of Use`, `Settings → About → Report an Issue`, path-free localized download/removal
    errors, and aligned macOS Settings rows.
  - Published website `/terms/` and updated `/privacy/`, `/support/#report`, `README.md`,
    `app-store-listing.md`, and `ios-appstore-submission.md` (`9afcbefe`); verified `/terms/`,
    `/privacy/`, and `/support/` live HTTP `200` on `vocello.vercel.app`.
  - **Verification:** `scripts/dev.sh check --since 1363da5c` 11/11 stages PASS (52/52 Playwright
    checks); physical iPhone 4/4 XCUITest lanes PASS + visual QA (`studio-layout`
    `ios-xcui-smoke-20261125-171558-719509a0`, `purchase exports`
    `ios-xcui-purchase-20261125-173317-6570050a`, `control-audit external`
    `ios-xcui-control-audit-20261125-174101-5e0f34ca`, `localization`
    `ios-xcui-localization-20261125-180114-8f09bdd2`); GitHub **CI** (`45674571446`, 9/9) and
    **Release rehearsal** (`45674571439`, 4/4) PASS; signed local `build/Vocello.app` manually verified.
- **App Store Connect read-only audit & authorized updates (`RF-62`, `ASR-11`, verified via readback):**
  - **Territories (`148 → 147`):** excluded China Mainland (`CHN`) on both app and export IAP
    (`com.patricedery.vocello.design_clone_export`); readback verified identical **147** territories
    (27 EU + `CHN` excluded; South Korea `KOR` kept; `availableInNewTerritories: true`).
  - **Privacy Policy URL:** updated `en-US` App Info localization to `https://vocello.vercel.app/privacy/`
    and verified readback (`supportUrl` already `https://vocello.vercel.app/support/`).
  - **Age Rating (`4+ → 13+`):** raised `ageRatingOverride` and `ageRatingOverrideV2` to
    `THIRTEEN_PLUS` (`territoryAgeRatings` read back `THIRTEEN_PLUS`). Apple's two Nov 16
    descriptors (`sharedLocation`, `datingAndRelationships`) still read back `null` because `asc`
    v7.4.0 lacks CLI flags for them — 2 web-portal clicks (`No`/`No`) remain to close `RF-62`.
  - **Remaining ASC gaps:** version `3.0.0` (`PREPARE_FOR_SUBMISSION`, 0 screenshot sets); export IAP
    `MISSING_METADATA` (0 review screenshot uploaded + `RF-02` Paid Apps pending).
- **Pre-3.2 documentation, `AGENTS.md` & context cleanup:**
  - Tightened `AGENTS.md` by ~30% (19.7 KB → 13.7 KB), synced `.agents/` rules/skills/agents/workflows,
    fixed P0 `Terms of Use` Settings path (`Settings → Privacy & Permissions`) in paste-ready App
    Review Notes, unblocked `RF-71`/`RF-12` from `RF-68`'s Phase 5 iPhone proof, fixed live website
    `whatsnew.js` `IPHONE_NOTE` (`"3.1" → "3.2"`), synced all active iOS/macOS/runtime/QC/package
    reference docs, pruned 26 historical `docs/audits/*.md` files (−1.12 MiB, preserved in git
    history) and 518 lines of obsolete checkpoints here, and verified zero broken links and clean
    contracts/hooks.
- **Disk cache note:** `python3 scripts/build_cleanup.py --qc-v1 --yes` reclaimed `0 B` because QC v2
  hard-links both 6.67 GiB ASR weights in `build/cache/delivery-analysis`.

**Next — Phase 4 (`RF-71` Mac/CLI 3.2.0) & Phase 5 (`v3.2.0-ios.1` → `RF-16`):**

1. **Maintainer web-portal items (anytime before submission):** activate Paid Apps Agreement +
   tax/banking (`RF-02`, active 24h+ before submit) and set `Shared Location = No` / `Dating and
   Relationships = No` in App Store Connect Age Rating (`RF-62`).
2. **Phase 4 (`RF-71` — Mac/CLI 3.2.0):** quiet-Mac `mac-gate-bench.json` reseed (`>= 3` clean runs
   with `QWENVOICE_GATE_BENCH_SEED=1 scripts/macos_test.sh gate`, `QVOICE_LEAD_ONLY=1`), bump
   `project.yml` (`3.2.0` / build `34`) + contracts + `docs/releases/v3.2.0.md`, push on go → CI →
   signed `v3.2.0` tag & 7-lane Mac promotion sitting.
3. **Phase 5 (`v3.2.0-ios.1` → `RF-16`):** Cut `v3.2.0-ios.1` → grouped iPhone window
   (`RF-68`/`RF-15`/`RF-17` + `RF-72` 30-take audit + 6.3-inch screenshots + `RF-66` demo video) →
   AWS Device Farm iPhone 15 Pro (`RF-65`) → remaining authorized ASC updates (`3.2.0`, screenshots,
   IAP review screenshot + attach, `RF-63` Review Notes, `RF-62` Nov 16 readback) → `ASR-09` 24h
   proof → `RF-16` submission.
