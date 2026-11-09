---
status: active
owner: release-qa
reviewed: 2026-11-09
summary: Read-only audit of the whole project on 2026-11-09 at f3689d2a, three days before the planned App Review submission. Covers the release path, the engine and runtime, the iPhone and Mac apps, tooling, CI, guardrails, process and the website. It changes no code, roadmap item or App Store Connect field; every recommendation waits for the maintainer.
sourceOfTruth:
  - config/roadmap.json
  - docs/development-progress.md
  - docs/reference/release-first-execution-2026-09.md
  - .github/workflows/release.yml
  - Sources/iOS/Info.plist
  - Sources/iOSSupport/Services/IOSDeviceEligibilityPolicy.swift
---

# Vocello: project audit, November 9, 2026

Source: `main` at `f3689d2a` (11 commits ahead of `origin/main`). Submission candidate so far:
build 29, tag `v3.0.0-ios.8` at `a60dd204`.

## 1. Verdict

The code is in good shape. The engine, the purchase flow, the privacy claims and the release
pipeline all held up under tracing, and almost every engine defect found is already in the roadmap.
The risk to November 12 is somewhere else:

1. **A new App Review risk: iPad.** Apple's device matrix lists every M1-or-later iPad and the iPad
   mini (A17 Pro) as satisfying `iphone-performance-gaming-tier`. Vocello therefore installs on
   those iPads, where its runtime guard shows only an English "Unsupported Device" screen. This is
   in build 29 and on `main`, and no roadmap item or earlier audit records it (N-1).
2. **The plan on paper is no longer the plan.** RF-41 landed on `main` on November 7 and needs a
   new candidate. The checkpoint and the release-path document still schedule the phone session on
   build 29, and the build number is still 29 (R-1).
3. **The candidate pipeline has no margin.** The archive job's 60-minute cap is smaller than the
   sum of its steps' own limits, and it already timed out once. Every candidate also waits on an
   hour-long CodeQL run and a website `npm audit` (C-1, C-2).

Taken together, a November 12 submission needs a decision today on the iPad question, a corrected
plan, and a clean first run of build 30. One failed archive or one new npm advisory moves the date.

### Method and limits

- Three read-only auditors ran in parallel (engine and runtime; iPhone and Mac apps; tooling, CI
  and process). The lead audited the release path and checked each leading finding against source
  before it entered this report.
- Nothing was built, tested or run on a device or model. Every runtime claim rests on reading
  source.
- The iPad capability fact was checked on Apple's Required Device Capabilities page on
  November 9. Nobody tried an iPad install.
- Not covered: model numerics, most of the CLI, the Mac app's views, translation quality, Dynamic
  Type on a device, and a line-by-line read of the release scripts.

### Severity

**Blocker** follows the focus lock: an App Review rejection risk, a crash or hang, data loss, a
broken purchase or restore, or a privacy or metadata mismatch on iOS. Blocker (schedule) means it
can stop or invalidate the November 12 submission. Everything else is High, Medium or Low and, by
the lock, belongs in the parked backlog.

## 2. Findings at a glance

| ID | Severity | Status | Where | Finding |
|---|---|---|---|---|
| N-1 | Blocker (rejection risk) | New | tag and main | Eligible iPads install the app and see only an "Unsupported Device" screen |
| R-1 | Blocker (schedule) | New drift on RF-41, RF-17 | docs, `project.yml` | Checkpoint and release path still plan build 29; RF-41 needs build 30 and fresh evidence |
| C-1 | High | Known, never fixed, untracked | `release.yml` | iOS archive job cap (60 min) is below its steps' limits (45 + 45 + 20) |
| C-2 | High | New | `release.yml`, `security.yml` | Each iPhone candidate waits on Swift CodeQL and a website `npm audit` |
| E-1 | High (crash class) | Known, parked (ER-02) | engine | A proactive model load running at backgrounding is neither cancelled nor covered by background time |
| A-1 | High | Known, parked (DA-07) | iPhone | A failed recording start shows nothing |
| A-2 | Medium | Known, decision B of Nov 4 | iPhone | No content filter or report path; consent is one global switch |
| C-3 | Medium | New | `ci.yml` | A dependency-graph API POST is part of `CI required` |
| S-1 | Medium | New | CI toolchain action | pip installs on signing runners have no hashes |
| G-1 | Medium | New | `.claude/settings.json` | GitHub connector `ask` rules name a server that doesn't match the tools in use |
| E-2 | Medium | Known, parked (ER-10) | engine | Crash-stranded install replicas are never swept (up to about 2 GB each) |
| E-3 | Medium | Known, parked (ER-11) | engine | A full disk at the final WAV reads as a quality failure |
| E-4 | Medium | Known, parked (ER-02) | engine | Blocking `flock` on the App Group store lock |
| E-5 | Medium | Known, parked (ER-06) | engine | A cancelled take publishes "loaded" without asking the runtime |
| P-1 | Medium | Partly known | process | 69% of the last 30 days' commits touch no product file |
| E-6 | Low | New | shared | Take file names are millisecond timestamps with no uniqueness check |
| A-3 to A-7 | Low | New | iPhone | Five small UI defects (section 5) |
| G-2 to G-5 | Low | New or parked (DA-12) | guardrails | Guard gaps for local history rewrites, remotes and staging spellings |
| T-1, T-2 | Low | New | scripts | Duplicate helpers; two release-path shell scripts no test names |
| D-1 | Low | New | docs, roadmap | Small inconsistencies (section 8) |
| W-1 | Low | New | website | The App Store privacy and support URLs sit on a `vercel.app` subdomain |

## 3. Release path

### N-1. Eligible iPads see only an "Unsupported Device" screen (Blocker, new)

**Evidence:**
- `Sources/iOS/Info.plist:55-58` requires `arm64` and `iphone-performance-gaming-tier`.
  `project.yml:586` sets `TARGETED_DEVICE_FAMILY: "1"` (iPhone only).
- Apple's Required Device Capabilities matrix, read on November 9, lists these devices for
  `iphone-performance-gaming-tier`: iPhone 15 Pro and later, iPad Pro 11-inch (3rd gen) and
  12.9-inch (5th gen) and later, iPad Air (5th gen) and later, and iPad mini (A17 Pro).
- `Sources/iOSSupport/Services/IOSDeviceEligibilityPolicy.swift:12-24` rejects every machine
  identifier that doesn't start with `iPhone`. Its header comment says Apple defines the capability
  as iPhone 15 Pro performance or later, which is incomplete.
- `Sources/iOS/QVoiceiOSApp.swift:66,137` routes unsupported hardware to `IOSUnsupportedDeviceView`.
  The reason text (`IOSDeviceEligibilityPolicy.swift:32-35`) is a hard-coded English string that
  prints the raw machine identifier.
- Neither submission document, the listing, the November 4 readiness audit nor the roadmap
  mentions iPad.

**Scenario:** an iPhone-only app runs on iPad in compatibility mode, and App Review often tests
that way. A reviewer on an M-series iPad opens Vocello and sees a dead end. Guideline 2.4.1 expects
iPhone apps to run on iPad whenever possible.

**Options, cheapest first:**
1. **Review notes only (no build).** State that Vocello requires an iPhone 15 Pro or later and
   refuses to run on iPad, and ask for review on an iPhone. Weak protection: the reviewer may never
   read it, and the screen is still a dead end.
2. **Admit eligible iPads (build 30, which RF-41 needs anyway).** Accept the iPad identifiers the
   capability covers and let the iPhone layout run in compatibility mode. These iPads have at least
   as much memory as an iPhone 15 Pro. The cost is evidence: the project has no iPad to validate
   memory, the increased-memory entitlement or the layout on, and the device farm would be the
   only route.
3. **Keep the wall but make it presentable (build 30).** Localize the text in the ten languages,
   drop the raw identifier and say plainly what is supported. This lowers the 4.0 design risk but
   not the 2.4.1 one.

**Recommendation:** decide before build 30 is cut, since both code options ride on it for free.
Option 2 is the only one that removes the risk; option 1 plus option 3 is the fallback if no iPad
evidence can be had in time. Either way, add the sentence to the review notes.

### R-1. The checkpoint and the release path still plan build 29 (Blocker, schedule)

**Evidence:**
- `git log a60dd204..HEAD -- Sources Packages project.yml` shows two product changes after the
  tag: `c878917a` (RF-38) and `f3689d2a` (RF-41), 10 files, +353 and −46 lines.
- RF-41's gate requires "a new candidate" with RF-17's records and RF-15's rows rerun on it.
- `project.yml:31` still has `CURRENT_PROJECT_VERSION: "29"`.
- `docs/development-progress.md` ("Resume now") and
  `docs/reference/release-first-execution-2026-09.md:143-187` still say "one phone session on build
  29". Neither mentions RF-41, build 30 or `v3.0.0-ios.9`.
- RF-17's five passing records are bound to `v3.0.0-ios.8` and expire on November 10. The language
  record failed and waits for a maintainer decision.
- The November 4 decision (option B: build 29 stays, no build 30) was reversed in effect by RF-41
  on November 7, but the decision text was not updated.

**The chain that actually remains, all serial:**
1. Decide N-1; land any change with RF-41's build.
2. Raise the archive timeouts (C-1) on `main`, since a tag runs its own copy of the workflow.
3. Bump the build number, push `main`, wait for CI.
4. Cut `v3.0.0-ios.9`; Security, then archive, export and upload; wait for TestFlight processing.
5. On the phone: RF-41's download lane, RF-17's records on the new tag, RF-15's rows on the
   processed build (the purchase rows need RF-02's agreement to be active), AUD-01, AUD-02, AUD-07,
   AUD-09, ASR-06, RF-35's cellular download, RF-12's export, ASR-05's screenshots.
6. ASR-09's download proof, ASR-11's readback, then the submission.

Fourteen items are due today and none of the phone rows can start before step 4 finishes.

**What helps:** `scripts/ios_candidate_tag.py:102-108` refuses a tag while App Store Connect
already holds the current build number, so a duplicate build 29 can't be cut by accident. RF-17 and
RF-15 are procedural: nothing in the pipeline enforces them for iOS.

**Recommendation:** rewrite "Next, in order" around build 30 today (30 minutes). Decide whether
RF-17 is rerun in full on the new tag or scoped to the classes RF-41's paths route to; RF-41
touches only Settings navigation and copy, so a scoped rerun is defensible. Decide the language
record. If any of this slips, move the date rather than compress the phone session.

### C-1. The iOS archive job's cap is below its steps' limits (High)

**Evidence:** `.github/workflows/release.yml:1044` sets `timeout-minutes: 60`. Inside the job,
platform readiness allows 2,700 s (line 1111), the archive 2,700 s (line 1231) and the export
1,200 s (line 1287). Readiness compiles the iOS foundation targets cold, then the archive compiles
the whole graph cold again, with no cache by design. Build 28 timed out here; the workflow was last
changed on October 24, before that failure.

**Fix (10 minutes, before the next tag):** raise the job to 120 minutes and the archive step to
about 4,500 s. No contract or test pins these values. Removing the duplicate compile is a larger
change for after the submission.

### C-2. Every iPhone candidate waits on CodeQL and a website audit (High)

**Evidence:** `release.yml:163-174`: `source-authority` needs `security`, and `archive-ios` needs
`source-authority`. `security.yml` runs Swift CodeQL (about an hour, 90-minute cap) and
`npm --prefix website audit --audit-level=high`.

**Scenario:** a high advisory published against a website development dependency on November 10
fails Security, and the iPhone archive never starts. The fix is a lockfile commit, a new CI run and
a new tag. A CodeQL infrastructure failure costs an hour per retry.

**Fix (about an hour, a maintainer decision because it changes the exact-source rule):** for
`-ios.N` tags, let the archive start beside Security and gate only the TestFlight upload on it, or
scope the npm audit to Mac and website releases. If that is too much change this week, at least
know the exposure and run `npm audit` locally before tagging.

### C-3. A dependency-graph POST is inside `CI required` (Medium)

`.github/workflows/ci.yml`: `ci-required` needs `dependency-submission`, which writes to GitHub's
dependency-graph API. A GitHub API incident turns the release commit red, and both the tag script
and the source-authority step refuse it. Fix (5 minutes): drop it from `needs` or mark the step
`continue-on-error`.

## 4. Engine and runtime

No new blocker. This area has been audited four times since September and it shows.

**Strengths, confirmed in source:**
- **Cancellation.** The prewarm gate, memory-relief admission, active-generation coordinator and
  the PCM channel close their cancel-before-suspend windows and resume each continuation once.
- **Model install.** Verification runs before linking, activation is an atomic swap, and failures
  fail closed.
- **Persistence.** Migrations are additive after v3, the outbox promotes interrupted writes and
  sets damaged entries aside, and History paths are rebased after a container move.
- **Concurrency register.** `config/concurrency-safety.json` matches source exactly: 27
  `@unchecked Sendable` and 2 `nonisolated(unsafe)` declarations, each registered.
- **Hygiene.** One TODO-class marker in 225,000 lines of Swift; four `try!`, all on constants.
- **Earlier fixes hold.** Eight spot-checked findings marked fixed (E4-01, E4-02, A2-01, E-01,
  B-14, E7-03, A-15, E5-01) all hold in today's source.

**Findings:**

- **E-1. Proactive load at backgrounding (High, parked under ER-02).**
  `MLXTTSEngine.swift:1287-1296` cancels only prompt prebuilds and the clone prime; its comment
  says a load already running finishes. `IOSBackgroundGenerationPolicy.swift:70` requests
  background time only for an active generation or Studio work. If the user leaves the app during
  a proactive load, GPU work continues with no grant as the app is suspended. The October 13 review
  called this a crash candidate, never reproduced. It is crash-class and parked by an earlier
  decision, so it deserves an explicit yes or no before the submission. Fix: count a model
  operation in `requestsBackgroundTime` and await it in the exit barrier (about half a day with
  tests).
- **E-2. Install replicas never swept (Medium, ER-10).** `SharedModelComponentStore.swift:615-618`
  and `1046-1049` create hidden replica folders in `models/`; reclamation sweeps only `trash/` and
  `staging/`. A kill between build and swap strands up to a full model on disk for good.
- **E-3. Full disk reads as a quality failure (Medium, ER-11).**
  `GenerationOutputAdapter.swift:1447-1451` swallows the final sync error. The take isn't lost or
  published, but the user sees a QC rejection instead of "storage full".
- **E-4. Blocking store lock (Medium, ER-02).** `SharedModelComponentStore.swift:1243` uses
  `flock` without `LOCK_NB`. Only short work runs under it.
- **E-5. Load state after a cancelled take (Medium, ER-06).** `MLXTTSEngine.swift:1546` publishes
  `.loaded` without asking the runtime. The behaviour is pinned by a strict `XCTExpectFailure`.
- **E-6. Take names can collide (Low, new).** `GenerationOutputFileName.swift:28-30` names a take
  by local wall-clock time to the millisecond, and publication is a replacing `rename`. Two takes
  named in the same millisecond (a clock step back, or the app and CLI writing one folder) would
  silently replace the first take's audio. Very unlikely; a short random suffix closes it (about an
  hour).
- **Low, known:** two latent traps unreachable at 24 kHz (ER-02, ER-06); a register entry that
  names a lock that doesn't exist (ER-06); a migration comment contradicted by the repository's own
  test.

**Structure:** four files carry most of the risk surface: `Qwen3TTS.swift` (6,693 lines),
`HuggingFaceDownloader.swift` (3,735), `GenerationOutputAdapter.swift` (3,725) and
`MLXTTSEngine.swift` (2,739). 37 source files exceed 1,000 lines. This is ER-12's subject.

**Test gaps:** no test constructs `IOSModelDownloadCoordinator` (its composition is covered only by
the on-device lane), and nothing calls `GenerationPersistence.persist` directly. The suites that
exist drive real product types, real GRDB and real files.

**Unconfirmed:** whether a `Retry-After: nan` header can break diagnostics encoding on the range
path; whether resume data keeps cellular permission after the switch is turned off.

## 5. iPhone and Mac apps

**Strengths, confirmed in source:**
- **StoreKit is sound.** The listener starts at the root and on every activation; unlock requires a
  verified, unrevoked, matching non-consumable; `finish()` follows the grant; pending and Ask to
  Buy show a notice; refunds can't be re-granted by a stale scan; Restore runs only on its button
  and is reachable without a model; free exports never wait on StoreKit. No purchase or restore
  defect was found. 17 state tests, 6 gate tests and an on-device purchase lane cover it.
- **Privacy claims hold.** The privacy manifest matches actual required-reason API use, and speech
  recognition is forced on-device.
- **Localization is complete.** Ten languages, 1,095 catalog entries, none missing or stale.
- **Crash hygiene.** No `try!`, `as!` or reachable `fatalError` in the iPhone app layers.
- **Earlier fixes hold:** A2-01, A14-02, A5-02 and A4-02.

**Findings:**

- **A-1. A failed recording start is invisible (High, parked as DA-07).**
  `ReferenceClipRecorder.swift:209,228` sets `recordingFailed`; its only reader is the Mac sheet.
  On iPhone, tapping Record during a call does nothing and says nothing. A reviewer testing Clone
  could hit it. Fix: a localized status in the overlay (small, one catalog key).
- **A-2. Guideline 1.2 safeguards (Medium, decision B).** Nothing changed in code since the
  November 4 audit: no content filter, no report path, one global consent switch. The mitigation is
  the review-notes paragraph. If build 30 is cut anyway, a `mailto:` "Report a problem" row is the
  cheapest product-side answer.
- **A-3. Fabricated transcript (Low, new).** `IOSPlayerSheet.swift:413` shows
  "Hi, I'm <name>. Cloned reference." for a saved voice with no transcript, in English in every
  language. It displays words the person never said.
- **A-4. Silent preview tap (Low, new).** `IOSVoicesView.swift:467-471` returns silently when the
  voice's audio file is missing.
- **A-5. Unlabelled back button (Low, new).** `IOSBottomSheets.swift:108-131`: the delivery
  picker's chevron has an identifier and no accessibility label.
- **A-6. English-only and misdirected copy (Low, partly BKL-35).** Download error strings in
  `IOSModelDeliverySupport.swift:189-205` and `IOSModelDownloadCoordinator.swift`; a
  "Settings → Privacy" path that the app calls "Privacy & Permissions".
- **A-7. Dropped Studio install request (Low, new, main only).**
  `VoiceModelsScreen.swift:149-154` consumes Studio's request and discards it while the model's
  status is still `.checking`. The user lands on Voice Models with no dialog. Nothing downloads
  unasked.

**RF-41's diff** was read in full by the lead: every route that starts a new download now passes
the confirmation, and only two call sites reach the installer. No defect beyond A-7.

**Readiness gaps from November 4:** G2 is closed in code on `main` only. G1, G3 and G7 are open at
the tag and at HEAD. G5 (demo video) and G6 (rejection log) appear in neither submission document.

**Unconfirmed:** whether SwiftUI ever drops RF-41's dialog when it is requested during the Settings
push (the device lane settles it); whether the repository page linked from Settings shows any
purchase route a reviewer could read as 3.1.1.

## 6. Tooling, CI and guardrails

**Strengths, confirmed:**
- Every action is pinned by SHA, every workflow has least-privilege permissions, there is no
  `pull_request_target`, and no untrusted expression reaches a `run:` body.
- No secrets, tokens, keys or private paths are tracked. Swift pins are exact; the npm lockfile has
  integrity on all 193 entries.
- No dead scripts: every script under `scripts/` has a referrer. All 44 shell scripts are strict.
- The contract checks assert product invariants (one StoreKit owner, the export gate, no Simulator,
  no `DEBUG`), not prose.
- Ten of the October 6 audit's hook findings were rechecked with crafted payloads and hold.

**Findings:**

- **S-1. Unhashed pip on signing runners (Medium, new).**
  `.github/actions/native-toolchain/action.yml:53-54` pins versions without hashes; transitive
  packages float. The action runs in the jobs that later import the distribution certificate. Fix
  after the submission: a hashed requirements file with `--require-hashes`.
- **G-1. GitHub connector rules match nothing (Medium, new).** `.claude/settings.json:268-273` asks
  on `mcp__claude_ai_Github__*`, but in this session the connector's tools carry a different server
  name. In an auto or accept mode, nothing repository-side stops a connector `create_branch` or
  `push_files`. Fix: a hook that blocks GitHub write verbs by tool suffix (20 minutes).
- **G-2 (Low, new).** `Bash(python3 scripts/ci/*)` auto-approves `failure_issue.py`, which creates
  GitHub issues, although `gh issue create` itself asks.
- **G-3 (Low, new).** `git commit --amend`, `rebase`, `reset --soft` and `filter-branch` pass every
  hook. A later non-fast-forward push is blocked, so the exposure is local history.
- **G-4 (Low, parked under DA-12).** `git remote add`, a push to another remote or URL, and
  `$G push --force` pass the policy guard; only the `ask` rule on `git push` stands behind them.
- **G-5 (Low, partial fix).** `git -C . stash`, `git add :/` and `git add -- .` are neither denied
  nor hooked.
- **T-1 (Low).** 18 private `load_json` copies beside `scripts/lib/jsonio.py`; ruff selects only
  `E9,F`.
- **T-2 (Low).** No test names `scripts/check_ios_catalog.sh` or
  `scripts/verify_ios_release_archive.sh`, both on the archive path.

## 7. Process and effort

Measured over non-merge commits, with lock files, the generated project and benchmark records
excluded from line counts:

| Area | 30 days: commits touching | 30 days: changed lines | 90 days: changed lines |
|---|---|---|---|
| Sources | 19% | 16.9% | 22.9% |
| Tests | 23% | 10.7% | 5.9% |
| Packages | 4% | 1.7% | 0.9% |
| scripts and their tests | 33% | 26.1% | 34.5% |
| docs | 46% | 22.0% | 12.3% |
| roadmap and checkpoint | 41% | 9.1% | 4.8% |
| config | 15% | 5.1% | 8.3% |
| website, `.github`, `.claude` | 13% | 7.3% | 1.9% |

- **Commit mix, 30 days (514 commits):** 354 (69%) touch no product file; 52 are product-only.
- **Hot files, 30 days:** `config/roadmap.json` changed in 193 commits, `docs/ROADMAP.md` in 119,
  `docs/development-progress.md` in 115.
- **Scale:** about 225,000 lines of Swift sit beside about 147,000 lines of Python tooling, 91
  config files, 17 roadmap plans (15 parked) and 23 audit documents.

**Reading (P-1):** some of this is right for a submission month. The avoidable part is ledger
mechanics: about 200 commits a month exist only to move roadmap or checkpoint state. R-1 shows
that cost isn't buying freshness where it matters, because the checkpoint was stale within an hour
of RF-41 landing. The second observation is the audit count itself: this is the project's fifth
broad audit since September, and the engine one found nearly nothing new. Further audits of the
engine have low yield until the parked remediation runs.

**Largest blocks off the release path:**
- Audio QC, prosody and language research: 67 files, about 25,000 lines of code. QC v2 is
  report-only and its own documentation says it didn't establish useful defect discrimination.
- Benchmark history and publication: 46 files, about 23,000 lines; two files alone are 9,500.

## 8. Docs and website

- **D-1.** `engine-remediation-2026-10` reads `active` at 0% with all 14 items parked, while the
  focus lock says one plan has live work. The checkpoint's front matter says
  `reviewed: 2026-10-28`. `SECURITY.md` has no supported row for the App Store iPhone app. The
  eligibility policy's comment about the capability is incomplete (N-1).
- **W-1.** The website is in good shape: a strict CSP, a privacy page that discloses Vercel Web
  Analytics, and facts bound to `config/public-product-facts.json`. The listing's privacy and
  support URLs are on `vocello.vercel.app`, a free-tier subdomain and a single point of failure
  during review. `npm audit` was not run in this audit.

## 9. Recommendations

Nothing below has been started. Each is the maintainer's call.

### Before build 30 is cut

1. **Decide N-1** (iPad): admit eligible iPads, or keep the wall, localize it and say so in the
   review notes.
2. **Correct the plan (R-1):** rewrite the checkpoint's next steps and the release-path table
   around build 30; decide RF-17's scope on the new tag and its language record.
3. **Raise the archive timeouts (C-1)** and take the dependency POST out of `CI required` (C-3).
   Both must be on `main` before the tag.
4. **Decide E-1** (proactive load at backgrounding): fix in build 30, or record the acceptance.
5. **Consider riding along,** since the build is happening anyway and each is small: A-1 (recording
   failure message), A-5 (one accessibility label), A-3 (fabricated transcript). Each adds review
   and test surface, so take them only if the phone session has room.
6. **Run `npm audit` on the website locally** before tagging, so C-2 can't surprise the tag run.

### At submission

7. Add the iPad and iPhone 15 Pro requirement sentence to the review notes, whatever N-1's
   decision.
8. Record the demo video (G5) and start the rejection log (G6).

### After the submission

9. Resume `engine-remediation-2026-10` in its recorded order; ER-02 and ER-10 first.
10. Park one backlog line each for E-6, A-4, A-6, A-7, S-1, G-1 to G-5, T-1 and T-2.
11. Decouple iPhone candidates from the full Security workflow (C-2) and remove the duplicate cold
    compile from the archive job.
12. Cut ledger overhead: fold roadmap notes into the commit that does the work, and keep the
    checkpoint to a short next-steps block.
13. Freeze or retire the QC v2 research tooling and the benchmark-publication block unless a 3.x
    goal needs them; stop opening broad audits until the parked remediation has run.
14. Move the website to a custom domain before the listing URLs are widely indexed.
