---
status: active
owner: release-qa
reviewed: 2026-09-12
summary: Testing entry point and evidence boundaries; platform guides own execution, the development workflow owns the edit loop, and delivery research stays opt-in.
sourceOfTruth:
  - scripts/check_project_inputs.sh
  - scripts/macos_test.sh
  - scripts/ios_device.sh
  - scripts/ui_test.sh
  - config/orchestration-contract.json
---
# Testing runbook

Start with the [current checkpoint](../development-progress.md) and primary roadmap, not a dated
run command. Source, project settings, contracts, and repository scripts outrank this guide.
This page routes work; it does not duplicate platform procedures or establish another gate.

When a lane is replaced or retired, preserve tested user protections and evidence, not legacy
implementation details or unsupported scores. A passing inherited suite does not prove correctness;
a newer suite is not exempt from independent validation. Replace or consolidate demonstrated
weaknesses within their existing owner, then retire the obsolete execution path.

## Choose the route

| Task | Authoritative procedure | Boundary |
| --- | --- | --- |
| Routine edit | [Development workflow](development-workflow.md) | `scripts/dev.sh check`, commit on `main`, push; CI is the gate; no UI/model/phone |
| macOS UI / XPC acceptance | [macOS testing](macos-testing.md) | Existing `scripts/ui_test.sh macos` lanes only when requested |
| Generic iOS SDK compile | [Host prerequisite](ios-device-testing.md#host-toolchain-prerequisite) | No phone or Simulator; matching Xcode components required |
| iPhone control / generation / candidate checks | [iOS testing](ios-device-testing.md) | Physical-device XCUITest; candidate proof remains distinct from diagnostics |
| Device deadline / pause / resume / lock | [Pause and resume](ios-device-testing.md#pause-and-resume) | Frozen progress stays untracked; validate restoration and exact identities |
| Model download lifecycle | [Model delivery](model-delivery.md) | Explicit isolated root; preserve canonical data and failed evidence |
| Benchmark operation / publication | [Benchmarking procedure](benchmarking-procedure.md) | Exact-source qualified PASS only; no automatic Git changes |
| Telemetry fields / schema / knobs | [Telemetry reference](telemetry-and-benchmarking.md) | Interpretation, not another operator runbook |
| Delivery / emotion research | [Delivery harness](delivery-harness.md) | Serial local analyzers after TTS exits; frozen independent-reference automated holdouts, measured claims only; listening optional |
| Release / submission programme | [Release-first plan](release-first-execution-2026-09.md) | Implementation, candidate verification, publication approval are separate |
| Gate or contract changes | [Development workflow](development-workflow.md), `.claude/rules/release.md` | Add a check only for a product invariant; prove rejection as well as success; never assert another file's wording |

## Claude Code routes

Claude Code sessions reach the same procedures through repository-owned skills and subagents
(`CLAUDE.md`, Hooks and assists). They add no gate and change no evidence rule: a skill runs the
named script, and a subagent only reads what the run produced. Routine edits, derived files and the
roadmap need no skill: `scripts/dev.sh check`, `scripts/dev.sh regen` and
`python3 scripts/roadmap.py validate` are the commands.

| Route | Skill (user-invoked) | Triage | Evidence owner |
| --- | --- | --- | --- |
| macOS UI lanes | `/macos-ui-lane <lane>` | `xcresult-triage` | [macOS testing](macos-testing.md) |
| iPhone XCUITest lanes | `/ios-lane <lane>` | `xcresult-triage`, then `axiom:test-failure-analyzer` (when installed) for interruption patterns | [iOS testing](ios-device-testing.md) |
| iPhone headless diagnostics | `/device-diagnostics <verb>` | `axiom:crash-analyzer` (when installed) for `.ips` | [iOS testing](ios-device-testing.md) |
| Release readiness (read-only) | `/release-evidence <tag>` | — | [Quality promotion](quality-promotion.md) |
| Swift change review | `swift-review` subagent, `/code-review` | — | Domain rules under `.claude/rules/` |

XcodeBuildMCP (`macos` and `ios-device` profiles) is an inner-loop assist for scratch builds and single
XCTest classes; it never produces evidence and never drives the UI. Axiom's Simulator-only tools are not
used. Physical-device and model lanes stay explicit and are never scheduled by a skill on its own.
What actually stops a session from starting a consent-bound lane is the permission list in
`.claude/settings.json`: `scripts/ui_test.sh`, `scripts/ios_device.sh`, `scripts/macos_test.sh
memory|lang-bench`, `scripts/clean_build_caches.sh`, `git commit` and `git push` are `ask`;
`scripts/release.sh`, `gh release create|edit`, Simulator lifecycle commands and `rm -rf build/cache`
are `deny`. Independently of that list, the `scripts/hooks/policy_guard.sh` hook blocks Simulator
destinations, whole-cache deletion, force pushes, new branches, worktrees and `project.pbxproj` writes.

## Model readiness

Generation UI tests require visible Settings readiness, Generate enabled, and the exact required
Clone reference. macOS fixture repair uses `scripts/macos_test.sh models ensure` or `install`
only after visible readiness fails. iOS model repair uses visible Settings controls; no headless
inventory substitutes for UI readiness. The isolated model-download lane is explicitly selected,
never an implicit smoke/benchmark bootstrap. Restart the affected lane after repair.

## Evidence and verdicts

- XCTest owns visible assertions, activities, screenshots and attachments. The runner additionally
  owns source/app/device identity, crash deltas, required collection, validators and restoration.
- `config/orchestration-contract.json` defines required steps. Missing, interrupted, duplicate,
  failed or unknown required evidence prevents PASS, even when every XCTest case passed.
- Preserve the first failed result. No automatic retries, seed substitution or merging a later
  pass into the failed bundle. The platform guide defines typed infrastructure classification.
- Resume uses the existing source/build/device/plan-bound validator, never a guessed row count.
  A zero-observation shard provides no cursor; changed source cannot reuse old acceptance.
- Generated audio, transcripts, database copies, raw telemetry, screenshots, traces and result
  bundles remain untracked. Compact published benchmark records must be privacy-safe and qualified.
- Partial-utterance ASR consensus is a verifier gap, not product failure or PASS. Warnings do not
  become clean promotion evidence merely because an operational lane completed.

## Storage and concurrency

`config/build-output-policy.json` owns free-space floors, caches, artifact lifetimes and cleanup.
Use `scripts/clean_build_caches.sh --routine --dry-run` before bounded cleanup; never assume all
artifacts or caches are disposable. Multi-run evidence is pinned before launch.
Serialize native Xcode commands under the existing shared lock. On the 8 GB Mac, generation and
heavy analyzers also run serially; timing lanes refuse to start on a busy host, and neural
evaluators start only after the TTS process exits. The busy-host rule is `require_quiet_host` in
`scripts/lib/host_preflight.sh`: a one-minute load above twice the core count or a kernel
memory-pressure level above normal refuses the lane before any model loads.
`QVOICE_ALLOW_BUSY_HOST=1` records the numbers and continues for an explicitly exploratory run, which
the publisher then classifies from the run's own load sample.

## CI and release

Ordinary CI and `scripts/dev.sh check` are deterministic. Models, a phone and UI tests never block
commits, pushes or candidate packaging. Neither compiles the XCUITest bundles, so an edit under
`Tests/*UITests` or `Tests/UIAutomationSupport` is proven by `xcodebuild build-for-testing` for
`VocelloMacUI` and `VocelloiOSUI` before it is committed. Public promotion separately requires all applicable
exact-source acceptance lanes. Consult the platform release guide for command-bound evidence, signing
and artifact verification; a development build is not a processed distribution candidate.

## Historical procedures

Former recipes, including operator-local ML setup, are in git history (the runbook before
2026-09-06). Dated pins and commands there are not current authority. For current analyzer
configuration use the delivery harness and its checked-in contracts.
