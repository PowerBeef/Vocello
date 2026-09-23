---
status: active
owner: release-qa
reviewed: 2026-09-22
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
| macOS UI acceptance | [macOS testing](macos-testing.md) | Existing `scripts/ui_test.sh macos` lanes only when requested |
| Generic iOS SDK compile | [Host prerequisite](ios-device-testing.md#host-toolchain-prerequisite) | No phone or Simulator; matching Xcode components required |
| iPhone control / generation / candidate checks | [iOS testing](ios-device-testing.md) | Physical-device XCUITest; candidate proof remains distinct from diagnostics |
| Device deadline / pause / resume / lock | [Pause and resume](ios-device-testing.md#pause-and-resume) | Frozen progress stays untracked; validate restoration and exact identities |
| Model download lifecycle | [Model delivery](model-delivery.md) | Explicit isolated root; preserve canonical data and failed evidence |
| Benchmark operation / publication | [Benchmarking procedure](benchmarking-procedure.md) | Exact-source qualified PASS only; no automatic Git changes |
| Telemetry fields / schema / knobs | [Telemetry reference](telemetry-and-benchmarking.md) | Interpretation, not another operator runbook |
| Delivery / emotion research | [Delivery harness](delivery-harness.md) | Serial local analyzers after TTS exits; frozen independent-reference automated holdouts, measured claims only; listening optional |
| Release / submission programme | [Release-first plan](release-first-execution-2026-09.md) | Implementation, candidate verification, publication approval are separate |
| Gate or contract changes | [Development workflow](development-workflow.md), `.claude/rules/release.md` | Add a check only for a product invariant; prove rejection as well as success; never assert another file's wording |

## Claude Code QA shortcuts

Routine edits use `scripts/dev.sh`; no skill is required. The four explicit repository skills under
`.claude/skills` are user-invoked shortcuts to the procedures below and add no gate or new evidence
rule.

| Work | Explicit shortcut | Authority |
| --- | --- | --- |
| macOS UI lanes | `/macos-ui-lane <lane>` | [macOS testing](macos-testing.md) |
| iPhone XCUITest lanes | `/ios-lane <lane>` | [iOS testing](ios-device-testing.md) |
| iPhone headless diagnostics | `/device-diagnostics <verb>` | [iOS testing](ios-device-testing.md) |
| Release readiness, read-only | `/release-evidence <tag>` | [Quality promotion](quality-promotion.md) |

Only an explicit device/UI/benchmark request authorizes its lane; publication is separately
explicit. Hook guards are best-effort checks, not a permissions system. XcodeBuildMCP and Axiom can
assist relevant discovery and diagnostics but never replace repository native UI/evidence routes.

### Read a finished run

Claude reads the artifacts directly, or hands the run directory to the read-only `xcresult-triage`
subagent, and stops when the deciding evidence is clear:

1. Read `run.json`, the required-step ledger and aggregate result. A missing required step is not PASS.
   The lane's own verdict (`verdict.txt`, or its `test verdict:` / `<platform> <lane> PASS` line)
   decides, never a wrapper's or pipe's exit code; when a lane runs in the background, capture its
   exit status directly.
2. Inspect the failed test and xcresult summary, then nearby log context. Use the existing bootstrap
   and external-interruption classifiers when applicable; zero launched cases can be infrastructure.
3. Check the crash delta and attachment manifest for relevant screenshots or control observations.
4. Report run id, verdict (product failure, infrastructure, interruption, restoration gap or PASS),
   deciding step and artifact paths. Never turn a failed run into a pass or silently rerun it.

For Swift review, the read-only `swift-review` subagent reads every Swift diff against the native
domain rules, in parallel with the lead's verification; it adds no CI gate.

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
Native Xcode/SwiftPM commands are serialized by the host-wide native lock across every checkout and
agent worktree. Generation and heavy analyzers run serially in the lead session (the 8 GB support
floor sets the budget even on the 16 GB development Mac); timing lanes refuse to start on a busy host,
and neural evaluators start only after the TTS process exits. The busy-host rule is
`require_quiet_host` in `scripts/lib/host_preflight.sh`: a one-minute load above twice the core
count, a kernel memory-pressure level above normal, another holder of the native lock or a running
agent worktree refuses the lane before any model loads.
`QVOICE_ALLOW_BUSY_HOST=1` records the numbers and continues for an explicitly exploratory run, which
the publisher then classifies from the run's own load sample.

## CI and release

Ordinary CI and `scripts/dev.sh check` are deterministic. Models, a phone and UI tests never block
commits, pushes or candidate packaging. `scripts/dev.sh check` compiles the affected XCUITest bundles
(`scripts/build_ui_test_bundles.sh`, build only) when `Tests/*UITests`, `Tests/UIAutomationSupport`
or `project.yml` change; push CI never compiles or runs them. Public promotion separately requires all applicable
exact-source acceptance lanes. Consult the platform release guide for command-bound evidence, signing
and artifact verification; a development build is not a processed distribution candidate.

## Historical procedures

Former recipes, including operator-local ML setup, are in git history (the runbook before
2026-09-06). Dated pins and commands there are not current authority. For current analyzer
configuration use the delivery harness and its checked-in contracts.
