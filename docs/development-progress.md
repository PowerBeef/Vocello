---
status: active
owner: backend-and-platform
reviewed: 2026-11-20
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
`3eeed981` holds October 26 through November 15, `20533a12` holds October 23 to 25, and
`a0597deb` every checkpoint before them.

## Resume now

### November 20, evening: Antigravity harness Phase A hardening & macOS lane verification (resume here)

Live macOS XCUITest verification and Phase A of the Antigravity harness upgrade landed on local
`main` (ahead of `origin/main` `670f7e77`; **not yet pushed**), with zero product-binary regressions
and four authorized backlog items closed (`BKL-63`, `BKL-74`, `BKL-87`, `BKL-90`).

- **Live macOS lanes (PASS):** `macos-xcui-smoke-20261120-202030-03d22d24` (layout smoke PASS) and
  `macos-xcui-perf-20261120-223253-e83975d8` (12/12 scenarios PASS, no warnings) after fixing the
  Sparkle incremental `CodeSign` race (`BKL-74`) and mirroring macOS build-for-testing logs into
  `$out/xcodebuild-build.log` + `$out/xcodebuild.log` (`0e207be0`).
- **Antigravity hooks & worker tracking (`39991806`, closes `BKL-63`):** upgraded irreversible external
  writes, `git push`, live `scripts/ios_candidate_tag.py`, `sudo`, `asc`, `vercel`, `gh`/`hf` writes,
  `failure_issue.py`, destructive Git and remote MCP writes to uncacheable `"force_ask"`; wired
  `PostInvocation` drift reminders (Swift membership vs `project.pbxproj`, `roadmap*.json` vs
  `docs/ROADMAP.md`) and non-looping `Stop` staged-whitespace guard; moved `agent_guard` in-process;
  updated `scripts/active_workers.py` for `Antigravity`/`agy` host ancestry with worktree worker
  lease tracking; fixed single-quoted backtick false blocks on `git rebase` commit messages; cleaned
  stale `.claude/worktrees` excludes and prose.
- **CI blind spots & candidate build log (`3eeed981`, closes `BKL-87`, `BKL-90`):** added
  `scripts/ios_control_audit.py validate` (`<0.2s` stdlib validator) to `scripts/lib/contract_gate.py`
  so CI's always-run `contracts` job catches iOS control-audit drift on every push/PR; replaced
  `if: failure()` on `nightly.yml` and `release-rehearsal.yml` `report` jobs with
  `always() && !cancelled() && (needs.<job>.result != 'success' || ...)`; mirrored iOS
  `candidate-runner-build.log` into `$out/xcodebuild.log`.
- **Workflow kit & docs:** added reusable `.agents/workflows/` scripts (`swift_adversarial_review.py`,
  `xcuitest_visual_qa.py`, `debt_burndown_pipeline.py`, `qc_experiment_synthesizer.py`) documented in
  `docs/reference/development-workflow.md` with Gemini 4 (Carbon / Neon / Hydrogen) model routing,
  trimmed this checkpoint below 25 KB, and closed `BKL-63`, `BKL-74`, `BKL-87`, `BKL-90`.
- **Next:** push local `main` when explicitly requested, observe CI, then resume iOS 3.1.0 candidate
  work (`RF-12`/`RF-15`/`RF-35`–`RF-42`) in the next iPhone window.

### November 20: Antigravity harness takeover

The repository-owned agent harness moved from Claude Code (`.claude/`, `CLAUDE.md`,
`website/CLAUDE.md`) to Antigravity (`AGENTS.md`, `website/AGENTS.md`, `.agents/hooks.json`,
`.agents/plugins/vocello/` and `scripts/hooks/agy_hook_adapter.py`) under `RF-67`, with zero Swift
or product-binary changes. Pushed through `670f7e77` with CI green (`44831811307`). `main` stays on
the iOS 3.1.0 TestFlight candidate track (`v3.1.0-ios.3`, `focusLock` active; `RF-35`, `RF-41`,
`RF-42` remain in flight awaiting an iPhone window).

- **Live verification (2026-11-20):** Antigravity loaded `AGENTS.md`, all six `vocello-*` skills and
  both read-only subagents (`vocello-swift-review`, `vocello-xcresult-triage`). Live `PreToolUse`
  probes denied `git push --force --dry-run origin main`, `edit_file` on `docs/ROADMAP.md`,
  `mobilebuildmcp:list_sims` and `cua-driver_cua-driver:list_apps`, while allowing
  `git status --short --branch` and `mobilebuildmcp:list_schemes`. `RF-67` is closed.

### November 17: Vocello 3.1.0 is public on the Mac

The maintainer uploaded the promotion manifest to the v3.1.0 draft and dispatched **Promote verified
release** from the tag (run 44036811898, approved on the `release` environment). Every step passed,
and at 07:17 UTC the release went public as the latest: 13 assets, and `releases/latest`'s
`appcast.xml` now resolves to v3.1.0, so Sparkle offers it. Two stray drafts that a release-edit
link had created on the phone were deleted first. `main` was pushed through `f99b5c33` with CI and
the release rehearsal green.

The post-promotion refresh is committed on local `main` (`ac173582`): the six promotion records,
and the README chart, performance art and website pooled over the two build-31 records through
`0b6bc26b` (0.29 to 0.41 warm RTF).

The published, notarized 3.1.0 CLI then passed `cli_package.py qualify` on this Mac: Built-in
English, French Voice Design and Clone (a Vocello-generated reference) each with a strict QC pass
and EOS, the two-item batch, cancellation (exit 130, cleanup acknowledged, no output) and the error
exits. Its report stays untracked under `build/artifacts/macos/release`. RF-61 is closed. The 3.1
website is live; its pooled performance numbers deploy with the next push of `main`.

### November 16, night: the follow-up release's Mac backlog, first wave

At the maintainer's request (work for a follow-up release, Mac-only, no lanes on the screen), the
roadmap gained a `needs` tag (mac, keyboard, iphone) on every open item and the first wave of
Mac-only backlog fixes landed on `main` with tests; the routed check, the full macOS deterministic
suite, the CLI, the iPhone compiles and the UI-test bundles pass.

- **Closed:** BKL-18, 20, 21, 22, 24, 25, 26, 32, 37, 46, 47, 48, 58, 64, 66, 70 and 73; DA-14;
  RF-64, superseded by RF-63 (iPhone Settings already has a Help & Support row).
- **Engine-remediation parts done:** B-02 (BKL-73), B-12 (`_exit` in the CLI's forced exit), C-13
  (the QC observer above 102.4 kHz) and BKL-01 (control-token-only scripts have nothing to speak).
- **Fixed, waiting on a run:** BKL-33 and BKL-19 on the next macOS smoke, BKL-28 on the marketing
  lane, BKL-23 on a production Mac language bench, BKL-50 on the next Linux CI run, BKL-60 on the
  phone.
