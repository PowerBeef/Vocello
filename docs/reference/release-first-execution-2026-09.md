---
status: active
owner: release-qa
reviewed: 2026-10-16
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
  failures; D1, D2 and D6 stay off as knobs. RF-15's by-ear takes became the same machine screen.
- **Device gate (RF-15).** Risk-based acceptance of the processed TestFlight candidate. The 201-take
  campaign (ICA-04/ICA-05) and the full matrix (ASR-12) follow the submission.
- **Privacy and content rights (ASR-02, ASR-04).** The maintainer's own recorded answers, with the
  rationale kept in the repository. No paid counsel.
- **Export purchase.** It stays in 3.0, per the September 7 decision. If the Paid Apps agreement,
  tax or banking is not ready, deferring the purchase to 3.0.1 is a recorded maintainer decision.
- **Promotion.** The exact-tag quality-promotion contract stays authoritative (RF-17).

## The path

Dates are targets; an overdue item is surfaced by `roadmap.py validate` and `scripts/dev.sh status`.

| Step | Items | Exit | Who | Target |
| --- | --- | --- | --- | --- |
| 1 — decisions | RF-02, ASR-02, ASR-04, ASR-09 | Recorded privacy, rights and region answers; App Store Connect prerequisites, including the Paid Apps agreement | Maintainer; Claude drafts the facts | On hold since Oct 13 |
| 2 — before the freeze | RF-14; AUD-01, AUD-02, AUD-07, AUD-09, F-01, F-16, DA-04 | D3 the default (done); the blockers' code fixes with deterministic tests | Claude | Oct 21–23 (code) |
| 3 — export purchase | RF-13 | The purchase lane passes on the phone | Claude, in a phone window | Done Oct 16 |
| 4 — freeze | ASR-08, RF-09 | Build 24 unused; exact-SHA CI green; `focusLock.freeze` recorded; the v3.0.0 tag | Maintainer pushes the tag | Oct 23 |
| 5 — archive and TestFlight | ASR-10, ASR-07, RF-12 | Release workflow `archive-ios` dispatch, verifier, internal TestFlight | Maintainer dispatches and approves | Oct 26–27 |
| 6 — acceptance and promotion | RF-15, ASR-06, RF-17 | Risk-based acceptance of the processed build, with a machine screen of its takes; exact-tag promotion evidence | Claude and the phone | Oct 29 |
| 7 — store materials | ASR-05, ASR-11 | Screenshots, metadata, privacy answers, reviewer notes; the read-only account check | Maintainer; Claude prepares | Oct 30 |
| 8 — submission | RF-16 | The maintainer submits for App Review | Maintainer | Nov 2 |

**Step 1 is on hold** (maintainer decision, October 13). The decisions are recorded, but the
maintainer's own account steps, the ASR-04 attestations and the privacy-page push wait, so RF-02,
ASR-02, ASR-04, ASR-11 and RF-16 are parked without dates. Steps 2–6 continue. The Paid Apps
agreement can take days to activate, so the submission date is set again when step 1 resumes.

The blockers' device proof comes from RF-15, so they close after it and before RF-16. Group the phone
work into as few windows as possible: RF-13 closed on October 16, so the next window is RF-15 with
ASR-06 and the ASR-05 screenshots.

## Rules while the focus lock holds

- **One plan holds live work.** Only this plan may hold planned or in-flight items, at most
  `focusLock.maxInFlight` in flight (the lock's dated decision records the cap). `roadmap.py validate`
  fails otherwise.
- **Blocker definition.** A new finding joins this plan only if it risks App Review rejection, a crash
  or hang, data loss, a broken purchase or restore, or a privacy or metadata mismatch on iOS. It joins
  with a due date and a gate.
- **Intake for everything else.** Any other finding becomes one parked line in
  `post-3-0-backlog-2026-10`, or in its domain plan, without investigation.
- **No new plans, audits or research programmes.**
- **Moving the primary plan means rewriting `focusLock`** with a new dated maintainer decision.
- **After the freeze, every commit names an item of this plan in its subject.** `focusLock.freeze.commit` records the
  freeze commit and the validator checks every later commit. A commit that slipped through is accepted
  only through `freeze.exceptions`, with its reason; history is never rewritten.
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
- the Xcode 27 toolchain move (CONV-21);
- the audit and benchmark backlogs.

## Standing constraints

- **Monetization is iOS-only.** One StoreKit non-consumable unlocks Design and Clone output export.
  Generation, listening, internal History and Built-in export stay free. macOS and the CLI have no
  paywall, and there is no Mac App Store route. The product `com.patricedery.vocello.design_clone_export`
  was approved on September 8 at USD 19.99 with automatic regional pricing and Family Sharing off. Its
  localized metadata and availability remain open under RF-02. See the
  [app guide](ios-app-guide.md#ios-export-purchase).
- **Version.** 3.0.0 / build 24 in `project.yml`. A fresh read-only check confirms the build is unused
  immediately before the archive.
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
