---
status: active
owner: release-qa
reviewed: 2026-10-28
summary: The iOS 3.0 App Store submission path rebaselined on October 12, the maintainer's decisions behind it, and the focus-lock rules that keep other work parked until submission.
sourceOfTruth:
  - config/roadmap.json
  - config/quality-promotion-contract.json
  - config/release-evidence-contract.json
  - project.yml
---
# Vocello 3.0 — iOS App Store submission

The maintainer adopted the release-first programme on 2026-09-04 and rebaselined it on 2026-10-12
onto one goal: submit Vocello 3.0 for iPhone to the App Store. `config/roadmap.json` is the only status
ledger. Its `focusLock` names `release-first-3-0-2026-09` as the only plan that may hold planned or
in-flight work. This document holds the order, the decisions and the rules; item gates hold the exit
criteria.

## Why the rebaseline

Between September 4 and October 12 the release did not move:
- **The primary plan was handed to other work four times**: harness stabilization (September 13),
  macOS–iOS convergence (September 14), and audio QC (September 29 and October 1). Each time every
  release item was parked.
- **Work outside the release outgrew it.** Of 975 commits, fewer than 60 named a release item.
  Twelve plans were adopted after September 4, five of them to work through audit findings.
- **The gates were maximal and voided each other.** They included a 201-take device campaign,
  three-region host probes, counsel-level determinations and a full accessibility matrix. Any commit
  after a freeze voided device evidence; the first freeze verification was void 85 commits later.
- **The blockers were decisions waiting on the maintainer, not code.** The take-quality bar, the
  privacy answers (untouched since August 27), content rights and the App Store Connect setup all had
  no dated ask.

## Decisions of 2026-10-12

- **Focus.** The iOS 3.0 App Store submission is the only live work until it is submitted.
- **Quality bar (RF-14).** A one-week blind A/B of the four engine divergences from Qwen's reference
  (D1 streaming text conditioning, D2 EOS reinsertion, D3 sampling without a float32 cast, D6 the
  English fallback for Custom), described in the
  [tooling research](../audits/2026-10-12-audio-qc-tooling-research.md). Only fixes that win become
  defaults. The remaining defect rate, with RF-06's long-form failure, ships as a documented known
  limitation.
- **No listening (2026-10-13).** The maintainer chose not to listen. RF-14 closed without the A/B:
  D3 (float32 sampling) became the default on reference grounds after a machine screen found no gross
  failures; D1, D2 and D6 stayed off as knobs. RF-15's by-ear takes became the same machine screen.
  (D2 became production on 2026-10-20; see below.)
- **Device gate (RF-15).** Risk-based acceptance of the processed TestFlight candidate. The 201-take
  campaign (ICA-04/ICA-05) and the full matrix (ASR-12) follow the submission.
- **Privacy and content rights (ASR-02, ASR-04).** The maintainer's own recorded answers, with the
  rationale kept in the repository. No paid counsel.
- **Export purchase.** It stays in 3.0, per the September 7 decision. If the Paid Apps agreement,
  tax or banking is not ready, deferring the purchase to 3.0.1 is a recorded maintainer decision.
- **Promotion.** The exact-tag quality-promotion contract stays authoritative (RF-17).

## Decisions since 2026-10-12

`focusLock.decision` in `config/roadmap.json` is the authority. In summary:
- **2026-10-13.** Step 1 went on hold (below), and nobody listens to takes for 3.0.
- **2026-10-16.** The engine audit
  ([`2026-10-16-engine-runtime-audit.md`](../audits/2026-10-16-engine-runtime-audit.md)) added items
  before the freeze:
  - RF-18 (long-form pacing);
  - RF-19 (iPhone install dead ends);
  - BG-01, hardened per the audit;
  - CONV-21 (the MLX refresh, authorized).

  The same day:
  - Engine-remediation items that are identity-safe, test-only or doc-only are re-homed into this
    plan while they are worked.
  - The iPhone proofs of BG-01, CONV-21 and RF-18 stay before the freeze, so the freeze needs an
    iPhone window the maintainer announces.
  - Post-3-0-backlog items that need no iPhone are authorized; each closes in the change that fixes
    it.
- **2026-10-18.** The development-workflow programme (DW-01 to DW-04,
  [`2026-10-18-dev-workflow-audit.md`](../audits/2026-10-18-dev-workflow-audit.md)) runs alongside the
  release, and the freeze does not wait on it. `focusLock.maxInFlight` is 8 until the freeze and 2
  after it.
- **2026-10-20.** RF-18's pre-registered follow-up screen adopted two reference behaviours:
  - the subtalker's reference sampling for every variation;
  - EOS filtered like any token (D2).

  Consistent's remaining long-form failures stay the 3.0 known limitation.

  Later that day:
  - Full text up front (D1) was adopted for single streamed takes (RF-21).
  - The redesigned export unlock sheet was approved (RF-22).
  - The iPhone candidate was frozen at `029427c9`, with `maxInFlight` at 2 and DW-03 parked until the
    submission. Mac-only user requests follow as items of this plan without changing the iPhone
    candidate, starting with Sparkle updates for the Mac app (RF-23).
- **2026-10-21.** The maintainer reported a release-blocking iPhone Clone layout bug (RF-24). Its fix
  passed on the iPhone, the freeze checks reran, and the freeze moved to `0919e998`. The same day the
  CLI overhaul joined this plan (RF-08 re-gated, RF-25 to RF-31,
  [`2026-10-21-cli-overhaul-plan.md`](../audits/2026-10-21-cli-overhaul-plan.md)); none of it changes
  the iPhone candidate, and RF-30 (iPhone-compiled files) and RF-31 (the publication) wait for the
  submission.
- **2026-10-22.** The Mac app and the CLI 3.0 release first and the iPhone app follows a few days
  later, all from one `v3.0.0` tag so every platform ships the same fixes; the iPhone archive (ASR-10)
  is made from that tag. RF-10 (Mac and CLI qualification and publication) is in flight, RF-32
  announces the release, and `maxInFlight` is 3.
- **2026-10-23.** The Mac app and CLI 3.0.0 are public. RF-09 closed and the freeze moved to
  `e7a8e2ae`, the signed `v3.0.0` commit, whose iPhone-compiled sources and `VocelloiOS` target equal
  `0919e998`'s, so the proven iPhone candidate is unchanged. RF-33 (the website layout for phone,
  tablet and desktop) joined the plan.
- **2026-10-24.** The RF-15 accessibility row's audit findings on TestFlight build 24
  (`ios-xcui-candidate-smoke-20261024-201553-857a53b4`) are accepted as a 3.0 known limitation and
  fixed after the submission (BKL-31). The findings: Dynamic Type only partly supported on Studio and
  on the purchase sheet's support and privacy links, a purchase-sheet contrast failure, and text
  clipped in Design and Clone at AX-XXXL. App Store Connect carries no accessibility declaration, so
  nothing public claims otherwise; publishing one before the fix must not claim Larger Text or
  Sufficient Contrast.

  Later that day:
  - iPhone model downloads may use cellular data behind an opt-in switch, off by default (RF-35),
    in 3.0. The iPhone freeze moves to the commit that carries it.
  - Re-testing is proportionate to a change. A new candidate reruns only the rows a change's paths
    reach, plus the checks only a person can do, and earlier passes on untouched areas stand. A
    full device campaign is for engine-scale changes. For RF-35 that is the RF-15 navigation row,
    one model reinstall over Wi-Fi, and one attended download over cellular.
- **2026-10-25.** Computer use becomes the default route for device and UI checks XCUITest cannot
  cover, with as much autonomy as an announced window allows (`/vocello-ui-autonomy`). Inside a
  window Claude runs the XCUITest lanes, then drives the locked phone through iPhone Mirroring, and
  stops only for the maintainer's steps: iPhone system settings, permission prompts, the passcode,
  app deletion and purchase confirmations, which go on a setup card or a paused notification.
  A computer-use run saves a local step-and-screenshot record; an attended row closes only when the
  maintainer confirms that record. XCUITest stays the only automated evidence, and the iOS lanes
  refuse to start while iPhone Mirroring runs.
- **2026-10-26.** Build 26 (`v3.0.0-ios.5` at `e0feaf2c`: build 25's product plus a test-only fix)
  joined the Public Beta group without RF-17's exact-tag manifest, and its promotion lanes were
  skipped. The waiver covers that Public Beta distribution only; RF-17 still gates the App Review
  submission. The beta looks for the remaining bugs and for performance and stability on the
  iPhone 15 Pro, the hardware floor.
- **2026-10-27.** Build 26 shows the Game Mode banner at every launch, so build 27 opts out of Game
  Mode (RF-37), and RF-17's records and RF-15's launch and navigation rows rerun on its tag. 3.0
  ships outside the EU: the 27 EU territories left availability and the account is declared
  non-trader (the EU release is BKL-41).
- **2026-10-28.** A free BrowserStack trial runs a self-contained smoke test on a real iPhone 15 Pro
  and 15 Pro Max as exploratory evidence only (RF-38), and the documentation, agent instructions and
  roadmap are reviewed (RF-39).
- **2026-10-29.** Build 27 (`v3.0.0-ios.6` at `d37583a3`: build 26's product plus the Game Mode
  opt-out) joined the Public Beta group on the same terms as build 26: no RF-17 exact-tag manifest,
  for the Public Beta only, and RF-17 still gates the App Review submission.

## The path

Dates are targets and the status is as of October 28; `config/roadmap.json` is current, and an
overdue item is surfaced by `roadmap.py validate` and `scripts/dev.sh status`.

| Step | Items | Exit | Who | Status |
| --- | --- | --- | --- | --- |
| 1 — decisions | RF-02, ASR-02, ASR-04, ASR-09 | Recorded privacy, rights and region answers; App Store Connect prerequisites, including the Paid Apps agreement | Maintainer; Claude drafts the facts | On hold since Oct 13; ASR-09 due Oct 30 |
| 2 — before the freeze | RF-14; AUD-01, AUD-02, AUD-07, AUD-09, F-01, F-16, DA-04; BG-01, CONV-21, RF-18, RF-19 | D3 the default; the blockers' code fixes with deterministic tests; the engine-audit items with their iPhone proofs | Claude; the phone in an announced window | Done except AUD-01, AUD-02, AUD-07 and AUD-09, whose device proof comes from RF-15 (due Oct 30) |
| 3 — export purchase | RF-13 | The purchase lane passes on the phone | Claude, in a phone window | Done Oct 16 |
| 4 — freeze | ASR-08, RF-09 | Build unused; exact-SHA CI green; `focusLock.freeze` recorded; the `v3.0.0` tag | Maintainer pushes the tag | Done: frozen Oct 23 at `e7a8e2ae`, the signed `v3.0.0` commit |
| 5 — archive and TestFlight | ASR-10, ASR-07, RF-12 | A `v3.0.0-ios.N` candidate tag (or an `archive_ios` dispatch) archives, verifies and uploads to internal TestFlight; the processed build installs with personal data preserved | Maintainer requests the tag; Claude installs | ASR-10 and ASR-07 done Oct 24; build 26 in Public Beta, build 27 next (RF-37); RF-12's owned-export row waits on RF-02 |
| 6 — acceptance and promotion | RF-15, ASR-06, RF-17 | Risk-based acceptance of the processed build, with a machine screen of its takes; exact-tag promotion evidence | Claude and the phone | Due Oct 29; reruns on build 27's tag |
| 7 — store materials | ASR-05, ASR-11 | Screenshots, metadata, privacy answers, reviewer notes; the read-only account check | Maintainer; Claude prepares | ASR-05 due Oct 30; ASR-11 parked |
| 8 — submission | RF-16 | The maintainer submits for App Review | Maintainer | Parked until step 1 resumes |

The Mac and CLI items run beside the path without touching the iPhone candidate: RF-10 (qualification
and publication, in flight) and RF-23 (Sparkle updates); RF-30 and RF-31 wait for the submission.

**Step 1 is on hold** (maintainer decision, October 13). The decisions are recorded, but the
maintainer's own account steps, the ASR-04 attestations and the privacy-page push wait, so RF-02,
ASR-02, ASR-04, ASR-11 and RF-16 are parked without dates. The other steps continue. The Paid Apps
agreement can take days to activate, so the submission date is set again when step 1 resumes.

The blockers' device proof comes from RF-15, so they close after it and before RF-16. Group the phone
work into as few windows as possible, and use the phone only in windows the maintainer announces. The
next window serves build 27: the Game Mode check (RF-37), RF-17's remaining records, RF-35's attended
cellular check and RF-15's remaining rows. DW-04 runs alongside the release; DW-03 is parked until
the submission.

## Rules while the focus lock holds

- **One plan holds live work.** Only this plan may hold planned or in-flight items, at most
  `focusLock.maxInFlight` in flight (the lock's dated decision records the cap). `roadmap.py validate`
  fails otherwise.
- **Blocker definition.** A new finding joins this plan only if it risks App Review rejection, a crash
  or hang, data loss, a broken purchase or restore, or a privacy or metadata mismatch on iOS. It joins
  with a due date and a gate.
- **Intake for everything else.** Any other finding becomes one parked line in
  `post-3-0-backlog-2026-10`, without investigation. A backlog item that needs no iPhone may be fixed
  before the submission (2026-10-16); it closes in the change that fixes it and takes no in-flight
  slot.
- **No new plans, audits or research programmes.**
- **Moving the primary plan means rewriting `focusLock`** with a new dated maintainer decision.
- **After the freeze, every commit names an item of this plan in its subject.**
  `focusLock.freeze.commit` records the freeze commit and the validator checks every later commit. A
  commit that slipped through is accepted only through `freeze.exceptions`, with its reason; history
  is never rewritten.
- **A missed date is a decision, never a silent extension.** Cut scope, move the date with a recorded
  reason, or close the item.
- **Maintainer-only actions.** Pushing the tag, dispatching the release workflow and approving its
  environment, the TestFlight upload, App Store Connect edits and the submission. Neither this
  document nor the roadmap authorizes any of them.

## After the submission

The maintainer lifts the focus lock and picks the next primary plan from the parked work:
- the audio QC programme (labels, detectors, PA-16 and QC-04/06/08);
- the 201-take campaign and the full acceptance matrix;
- macOS and CLI 3.0 qualification and publication (RF-08, RF-10);
- CI's move to Xcode 27 (DW-04; the report-only `xcode-preview.yml` already runs the preview image);
- the engine-remediation and development-workflow items left unfinished at the freeze;
- the audit and benchmark backlogs.

## Standing constraints

- **Monetization is iOS-only.** One StoreKit non-consumable unlocks Design and Clone output export.
  Generation, listening, internal History and Built-in export stay free. macOS and the CLI have no
  paywall, and there is no Mac App Store route. The product `com.patricedery.vocello.design_clone_export`
  was approved on September 8 at USD 19.99 with automatic regional pricing and Family Sharing off. Its
  en-US, fr-CA and fr-FR details were entered on 2026-10-12 (RF-02), and availability excludes the EU
  since 2026-10-27. The updated Developer Program License Agreement, the Paid Apps agreement, tax and
  banking remain the maintainer's. See the
  [app guide](ios-app-guide.md#ios-export-purchase).
- **Version.** 3.0.0; `project.yml` owns the build number, which moves with each candidate. A fresh
  read-only check confirms the build is unused immediately before the archive.
- **No substitutes.** No diagnostics or development build stands in for the processed candidate. No
  faked entitlement replaces the purchase.
- **Personal data.** Fresh-install proof never erases personal data without verified recovery and
  separate approval.
- **Related documents:** the [content-rights packet](content-rights-review.md), the
  [submission procedure](ios-appstore-submission.md), the [quality-promotion contract](quality-promotion.md)
  and the candidate [v3.0.0 release notes](../releases/v3.0.0.md).

## Historical programme checkpoints

The September programme's amendments, queue, checkpoints and dispositions live in git history
(`git log -p -- docs/reference/release-first-execution-2026-09.md`). Current status is in the roadmap;
the next work is in [the current checkpoint](../development-progress.md).
