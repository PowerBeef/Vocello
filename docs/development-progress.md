---
status: active
owner: backend-and-platform
reviewed: 2026-09-12
summary: Current resume checkpoint; config/roadmap.json owns open work, config/roadmap-archive.json holds finished work, and older narrative lives in git history.
sourceOfTruth:
  - config/roadmap.json
  - config/runtime-refactor-contract.json
---
# Vocello development checkpoint

Start here, then follow `config/roadmap.json`'s `primaryPlan` and the
[release-first execution plan](reference/release-first-execution-2026-09.md).
This is a narrative, not a second work ledger. Product source, contracts and scripts win.
Checkpoints older than the ones below live in git history (`git log -p -- docs/development-progress.md`,
last full copy at commit 25a895ed).

## Resume now

### Benchmark harness and XCUITest review (September 11 to 12)

Three read-only audits of the XCUITest suites (20 files, 7,747 lines), the benchmark harness
(~18k lines of scripts) and the 291 published records answered the maintainer's question "is the
benchmarking accurate, and does it cover CLI- and UI-driven runs on both platforms?" with: the harness
exists on every axis and its design is sound (no clocks in the UI tests, monotonic in-app telemetry,
three-layer authority on macOS, uptime-paired memory, hash-bound `-O` provenance on the macOS CLI), but
the published numbers were not accurate. Two RTF definitions shared one key (decode-loop speedup in UI
records, end-to-end audio/wall in CLI records, 10 to 28 % apart), bench wall time came from `Date()`,
iOS optimization labels were literals, and the gate bench judged single takes at a flat 5 % without
looking at host load. The maintainer decided to adopt the industry-standard RTF from now on.

Commits so far: `458a7410` makes `rtf` the standard real-time factor (engine request wall ÷ audio,
lower is faster) on every surface, derived from the engine's monotonic stage recorder as
`requestWallSeconds` / `realTimeFactor`; the decode speedup survives as `decodeSpeedupX`, UI records add
`rtfAppEndToEnd`, records declare `run.rtfDefinition`, legacy records are never rewritten and render a
derived `~` value, comparison lineages never mix, the README and website charts moved to the newest
canonical record (`0b234262`) with generated alt text and a stale-pin check. `7c2f9af2` binds every
optimization label to a build receipt that names the executable and its digest
(`scripts/lib/build_provenance.py`), makes `ios_device.sh bench` build `-O` and poll only the completion
sentinel, stamps the CLI's own digest into `bench-results.json`, moves the gate bench to three warm takes
compared by median with MAD-widened thresholds, an inconclusive verdict (exit 3) under host load or heat,
OS/Xcode identity in the baseline, and publishes full-matrix engine runs as canonical. The following
commits fix the UI perf lane (fractional window attribution, refresh fail-closed, contract-owned
designations, macOS environment row, marker flush, readiness-free generation windows, sleep hold on
every lane, iOS cell-length and per-mode seed checks) and the runner/test hygiene items from the audit.

Open follow-ups are roadmap items AV-13 (macOS coverage lanes), ICA-20 (iOS coverage and the last
English-label lookups) and AV-14 (consent-bound re-baseline runs: three-take gate baseline, one canonical
macOS and iOS benchmark run and one perf run per platform under the new definition, then repin the
charts). The first push's macOS CI job failed once in
`Qwen3DecoderPartitionTests.testReplayCachePolicyPreservesBothPartitionsAndBoundsObservations` (an MLX
cache-bytes assertion in the owned package, untouched by the change) and passed on the next commit;
AV-14 carries the watch.

### Lean verification migration (September 11)

Seven commits replaced the gate-and-governance machinery the Codex and GPT phases left behind. Local
verification is `scripts/dev.sh check` (lint, contracts, selected tests, the native lanes the dirty
tree touches) and nothing blocks a commit except a 15-second lint (`scripts/hooks/commit_lint.sh`:
branch `main`, clean whitespace, no private path or credential); CI on `main` is the gate. CI routes
pushes by `scripts/ci/classify_changes.py`, restores the persistent DerivedData caches on the macOS
jobs, runs the Python suite on Linux and the darwin-only modules inside the macOS gate; `security.yml`
runs weekly and inside the release workflow; `nightly.yml` owns TSan, the complete Python suite and
cold compiles. The Python suite runs under pytest with `-n auto` in about 90 seconds (300 serial
before), with `research` and `darwin_only` lanes by marker. Deleted: the checkpoint receipt and its
fingerprint, `check_test_workflows.sh`, the documentation contract, doc metadata pins, surface
coverage and its byte budget, the project-health and Python-test contracts, the 254-path existence
list, the workflow token assertions, seven governance test modules, the 53 pinned historical
documents (release notes and decisions stay), and the Codex-era instruction sprawl. `CLAUDE.md` is
under 8 KB with two rules (`native.md`, `release.md`) plus `website/CLAUDE.md`. `config/roadmap.json`
now holds only open work (finished items and completed plans moved to `config/roadmap-archive.json`,
notes capped at 1,200 characters); `docs/ROADMAP.md` lists open items with their blockers.

Product invariants kept an executable check throughout: `scripts/repo_invariants.sh` (exact greps),
`scripts/privacy_scan.py`, `scripts/public_facts_contract.py`, and the product contracts in
`./scripts/check_project_inputs.sh`. The quality additions landed in the seventh commit: owned Xcode
targets compile with warnings as errors (five real warnings fixed, one of them visible only at `-O`; the
nightly lane now also compiles the macOS app optimized), flaky tests have a 30-day quarantine
(`config/test-quarantine.json`), and `scripts/dev.sh lint` runs the low-noise SwiftLint rules in
`.swiftlint.yml` on changed files. swift-format was measured and not adopted: with a four-space
configuration it still rewrote 310 files and 23,500 lines of a codebase that already follows one
consistent Xcode style, for no correctness gain. Next measurement: the warm-cache time of the macOS
CI job on the second push after the cache save.

### Claude Code adoption (September 11)

Claude Code replaced Codex as the development environment in six checkpointed commits on `main`
(roadmap plan `claude-code-adoption-2026-09`, CCA-01 to CCA-12, all done and the plan complete). `AGENTS.md` became a
177-line `CLAUDE.md`; the five domain rules moved to path-scoped `.claude/rules/` with a new
always-loaded `claude-tooling.md`; the nested website guidance became `website/CLAUDE.md`. Every gate that
named the old files was rewired in the same commit, the Codex hook config and session-storage tooling
were retired (runbook pinned historical), and a configuration contract validated the repository-owned
`.claude/` files inside the project gate (retired on September 11 in favour of the hook behaviour tests). `.claude/settings.json` wires the unchanged
commit gate plus `policy_guard.sh` (Simulator destinations, whole-cache deletion, force pushes, new
branches, `project.pbxproj` writes, unacknowledged gate skips), `generated_file_guard.sh` (generated
and frozen files, pinned bodies ask first), a `project.yml` regeneration reminder and a session-start
ritual; `scripts/dev.sh status` reports branch, verification class, receipt state and primary plan.
Seven project skills and four read-mostly subagents route to the existing scripts and documents;
device, model and release lanes stay user-invoked only.

Two harness findings were recorded with evidence rather than assumed. The checkpoint receipt no longer
binds PATH membership (`local-v3`): the hook environment lacks the plugin `bin` entries the tool shell
appends, which made a fresh receipt read as stale. For CCA-09 the direct `xcrun xctest` runner stays:
bounded `xcodebuild test-without-building` trials on the same xctestrun passed one class in 4 s but
took 95 s for the full bundles and failed two tests that pass under the direct runner on every
checkpoint (`CLIExecutionTests.testRealSignalsReachNativeSupervisorAndAwaitCleanup` at 31.4 s and
`PreparedVoiceRepositoryTests.testTwoNativeProcessesExcludePreparationReplacementAndDeletion` at
45.2 s, both real native-process boundaries timing out under the xcodebuild test host). The lane now
writes `core`, `transport` and `runtime` `test-results.json` summaries through the shared
`scripts/lib/xctest_summary.py`, and `scripts/macos_test.sh test --coverage` is an opt-in,
non-blocking llvm-cov export. The Python test roots are one root (`scripts/tests/`); the
2026-08-21 omitted-tests finding was already closed, and full discovery runs every module (130 modules, 1736 declared tests; discovery ran 1736 tests in 302.029s).

Follow-ups scheduled, not started: TSan characterization before its 2026-09-30 deadline
(`config/tsan-policy.json`, one of three consecutive passes recorded) with `axiom:concurrency-auditor`
first; an `axiom:iap-auditor` pass over the iOS export unlock before RF-13; an
`axiom:accessibility-auditor` pass for ISU-4; the optional `swift-lsp` build-server setup. Product
critical path is unchanged: ISU-4 localization qualification and RF-13 remain next; the adoption track
is closed.

Later the same day the follow-up audits ran through Axiom and CI on `main` was repaired in two steps: the
first push fixed a gitignored path quoted in prose and a PyYAML import the runner cannot satisfy (`main`
had been red since the previous day); that run still failed on a French plural test that depended on the
process locale, fixed in `2f06f21a` by binding formatted copy to the interface locale. The StoreKit audit found the export unlock clean against every invariant
(one low note on generic error copy). The concurrency audit found no unregistered unsafe declaration and no
confirmed race; the registry text for the engine service host now describes the per-method MainActor
discipline the code really uses, the performance gate model is class-isolated (F-24), and the unchecked
Sendable budget sits at its ceiling. The TSan lane failure was not a race: every helper xctest child spawned
from the instrumented parent aborts at load on this toolchain (three launch variants tried), and the bundle
then crashed on an unguarded index; the two helper-process tests now skip under the sanitizer with the
exclusion recorded, the lane runs to completion with zero reports, and the scheduled workflow gains the
pinned numpy its toolchain step verifies (AV-12). The accessibility audit named a credible root cause for
ISU-4: the tab dock had no Dynamic Type ceiling and grew into the scroll-gesture zone at AX-XXXL; the dock
is now capped at the first accessibility size, the compact toggles regain the switch role, the tab icon is
hidden from VoiceOver and the App Language rows adapt their layout (ISU-5, source landed; the physical
English/French AX-XXXL and pseudo-localization walks remain the explicit qualification step).

### Roadmap reconciliation (September 11)

`config/roadmap.json` was compared item by item against tree `2f06f21a` by three read-only audits.
The ledger is structurally sound and every evidence and source path resolves, but about a third of the
open items were inaccurate. What changed, all in the ledger and active docs, no product code:

- Blocker topology was understated: eleven items were in flight although their only open clause is
  packaged, frozen-source or device evidence owned by a parked or unfrozen owner. They are now
  `planned` with the owner in `blockedBy` (F-05/15/18/20/21/23 behind RF-10, F-17 behind RF-08,
  ICA-04 behind RF-09, ICA-05 behind ICA-04, ISR-06 behind ISR-04, DP-32 behind DP-31). RF-11 no
  longer lists the done RF-07. Of the items still in flight, source work can move today on roughly a
  dozen; the rest wait for RF-09's freeze or a device window.
- F-19 (attempt-scoped terminal ownership) and F-22 (cross-process Saved Voice transactions) had fully
  discharged gates and are done. ASR-04 was `planned` with shipped source and is in flight.
- RF-06's title and gate now say what the September 7 amendment decided: known limitation, causal
  research deferred, incidence measured by the frozen campaign.
- Stale notes were corrected on F-16 (iOS long-form acceptance passed September 7), ISR-04 and VLR-07
  (runner, schema and classifier changed after their last revalidation), ISU-4 (next action is the
  post-ISU-5 physical walk), ICA-04 (five control families added after the frozen snapshot), AV-07
  (empty approved external catalog digests block the licensed-reference pilot), AV-08 and DP-29 (the
  September 2 language run is exploratory, partial and dirty-source with every cell
  `passedWithWarnings`, no Korean), AV-09 (the controllable-clock clause is untouched). ICA-06 carries a
  maintainer-visible re-scope proposal because seed-exact reproduction is unreachable through the UI.
- Evidence anchors that resolved to "Historical only" redirect stubs now point at the pinned
  `development-history-2026-09-06.md` sections. `config/delivery-evaluator-v2-contract.json` names the
  live `polyphase-kaiser5-v2` resampler instead of the retired one. The CLAUDE.md holdout invariant now
  says where the holdout really comes from.
- Two code defects were filed, not fixed: F-25 (a busy Saved Voice store is fatal to engine
  initialization, untyped and unlocalized; the exact app+CLI coexistence F-22 was for) and F-26 (CLI
  `afplay` children outlive a signalled process, signal sources install after the task starts, and a
  failure coinciding with a signal is reported as cancelled). ISU-5 carries a note on the stacked
  App Language row layout to decide before the physical walk.
- The September 11 host cleanup removed every retained run bundle and diagnostics directory under
  `build/artifacts`. No run id cited in the ledger is inspectable locally and `scripts/ui_test.sh
  --resume` has nothing to validate; the 201-take campaign restarts from take 1 on the frozen source.

Critical path is unchanged: ISU-4's post-ISU-5 walk, RF-13, then RF-09's freeze.
