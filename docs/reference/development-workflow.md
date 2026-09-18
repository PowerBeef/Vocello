---
status: active
owner: release-qa
reviewed: 2026-09-18
summary: The local edit loop, the commit lint and how push CI routes lanes; scripts/dev.sh is the interface and CI on main is the gate.
sourceOfTruth:
  - scripts/dev.sh
  - scripts/development_workflow.py
  - scripts/ci/classify_changes.py
  - .github/workflows/ci.yml
---
# Development workflow

Local verification is fast and advisory; CI on `main` is the gate. Nothing blocks a commit except a
15-second lint.

## Daily loop

```sh
scripts/dev.sh check --dry-run       # what the dirty tree needs
scripts/dev.sh check                 # lint, contracts, selected Python tests, native lanes touched
scripts/dev.sh test --only FooTests  # one XCTest class on the incremental test build
scripts/dev.sh py                    # Python tests that consume the changed tooling (default selection; --all, --lane product|research|darwin, or module paths)
scripts/dev.sh contracts             # the contract gate alone (check_project_inputs.sh --local)
scripts/dev.sh ios                   # generic device-SDK compile (incremental, no phone)
scripts/dev.sh regen                 # regenerate roadmap render, catalog, inventories, charts
scripts/dev.sh ci                    # what push CI runs, serially, when you want the push green first time
git add -A && git commit && git push
```

Routing is `scripts/ci/classify_changes.py`, the same file CI uses, so the local plan and the CI lanes
agree. `scripts/dev.sh check` compiles the affected XCUITest bundles through
`scripts/build_ui_test_bundles.sh` when UI-test sources or `project.yml` change; it never runs them.
Push CI does not compile those bundles. On a push, CI diffs each lane against the last run on the branch in which that lane's job
passed (not against the previous push), because `cancel-in-progress` can drop a superseded push's run
and the lanes it owed must still run on the next push; a lane with no prior green run always runs.
Locally the lanes come from the dirty tree: `swift` runs the macOS test bundles (`scripts/macos_test.sh test`, or `core-test --only` when
only test classes changed), `ios` runs the generic compile, `python` runs the reverse-dependency Python
selection, `website` runs `npm --prefix website run check`. A change to shared tooling
(`scripts/lib/`, `scripts/development_workflow.py`, `config/toolchain.json`,
`config/build-output-policy.json`) runs the whole Python suite.

## The commit lint

`scripts/hooks/commit_lint.sh` (a shared `PreToolUse` hook wired by both assistants) requires
branch `main`, a whitespace-clean staged diff (`git diff --cached --check`) and a clean
`scripts/privacy_scan.py --staged` (no developer home path, no credential-shaped token, no key file).
It never builds or tests. Two more guards block Simulator destinations, whole-cache deletion, force
pushes, new branches, `project.pbxproj` writes and hand edits of generated files;
`scripts/tests/test_claude_hooks.py` pins all of them.

## The contract gate

`./scripts/check_project_inputs.sh` runs every deterministic contract: build-output policy, generated
schemes, CLI identity, localization, saved-voice lifecycle, entitlements, support contact, public facts
(`scripts/public_facts_contract.py`: release identity, README and website copy), attribution, runtime
security (debug knobs, concurrency registry, TSan policy), owned-runtime inventory, backend wiring,
model catalog and host availability, App Store readiness, supply chain, release steps, benchmark
history, README charts, the text-level delivery and prosody contracts, the roadmap, the exact
product-invariant greps in `scripts/repo_invariants.sh`, the privacy scan, and the Python suite.

`--python all|darwin-only|selected|none` picks the Python lane: `all` (the default) runs the whole
suite; `darwin-only` runs only the modules that need the macOS host (CI runs the rest on Linux);
`selected` runs the modules the dirty tree affects; `none` runs the contracts without the suite.
`--local` is `selected` plus a refusal to run when `CI` or `GITHUB_ACTIONS` is set. This is also how
`scripts/dev.sh check` gets its Python tests: it never calls pytest itself but runs
`./scripts/check_project_inputs.sh --local`, whose `selected` lane calls
`scripts/development_workflow.py py`. `QVOICE_GATES=quick` makes the `all` lane skip the suite outside
CI while nothing under `scripts/` or `config/` is dirty.

## Lint and warnings

`scripts/dev.sh lint` runs `git diff --check`, the privacy scan, shellcheck on changed shell and, when
SwiftLint is installed, the low-noise rules in `.swiftlint.yml` on changed Swift files under `Sources/`
and `Tests/` (advisory; formatting stays Xcode's). Owned Xcode targets compile with
`SWIFT_TREAT_WARNINGS_AS_ERRORS`, so a new warning fails the local build before it reaches CI. Flaky
tests go into `config/test-quarantine.json` (`Tests/VocelloCoreTests/TestQuarantine.swift` for XCTest,
the pytest node id for Python); push CI sets `VOCELLO_QUARANTINE=1` and skips them, nightly runs them,
and `scripts/repo_invariants.sh` fails once an entry is 30 days old.

## Python tests

pytest with `pytest-xdist` (`-n auto`), both pinned in `config/toolchain.json`. The whole suite runs in
about 90 seconds on an M2. `scripts/tests/conftest.py` marks modules by name: `research` (audio,
delivery, prosody and device-analysis tooling) runs when those paths change and nightly; `darwin_only`
runs inside the macOS gate. Every run prints its slowest tests; a test that outgrows its lane moves,
it does not slow every push.

## CI

| Job | Runner | Runs when | Warm / cold |
| --- | --- | --- | --- |
| `changes` | ubuntu | always | seconds |
| `contracts` | ubuntu | always | about 1 min: the complete deterministic contract gate (`check_project_inputs.sh --python none`: product contracts, invariants, privacy scan, work authority, benchmark history) |
| `python` | ubuntu | Python paths, contracts, workflow files | 3 to 4 min: product and tooling tests; research tests when routed |
| `macos-tests` | macos-26 | Swift compile inputs, the lane's own scripts, build configs and benchmark evidence | cached DerivedData; darwin-only Python modules, macOS bundles, CLI identity (`-Onone`, same settings as the bundles, about 30 s) |
| `macos-tsan` | macos-26 | Swift compile inputs (same routing as `macos-tests`) | cached `macos-tsan` DerivedData; `scripts/macos_test.sh tsan`, the deterministic core bundles under ThreadSanitizer, blocking since 2026-09-14 (`config/tsan-policy.json`); 5 to 11 min on a second runner |
| `ios-compile` | macos-26 | iOS compile inputs | cached DerivedData; `build_foundation_targets.sh ios --incremental` at `-Onone` (`QVOICE_FOUNDATION_SWIFT_OPTIMIZATION`) |
| `website` | ubuntu | `website/` | about 4 min |
| `dependency-submission` | ubuntu | push only (skipped on dispatch) | seconds: `scripts/swift_dependency_snapshot.py` submitted to the GitHub dependency graph; needed by `CI required` |
| `CI required` | ubuntu | always | the branch-protection context; skipped lanes count as passed |

`ci.yml` triggers on `push` to `main` and on `workflow_dispatch` only; it has no `pull_request`
trigger, so `CI required` is always produced by a maintainer's push to `main`. Concurrency is keyed
on the event name and the ref, so a newer push cancels the previous push run while a manual
measurement dispatch never cancels the gate run for a commit. `scripts/dev.sh ci`
replays that job graph serially: project regeneration, the complete `check_project_inputs.sh`
(the Linux `contracts` job runs it with `--python none`), `scripts/macos_test.sh test`,
`scripts/macos_test.sh tsan`, the CLI version identity, `build_foundation_targets.sh ios --incremental`, the website supply-chain check
and `npm --prefix website run check`. It is a superset rather than a byte-identical replay: it skips
no lane by routing, and it runs the whole Python suite inside the gate in one process where CI splits
it into `-m "not research and not darwin_only"` plus an optional `-m research` on Linux and
`-m darwin_only` in the macOS job.

Only push CI's own inputs (`.github/workflows/ci.yml`, `.github/actions/**`,
`scripts/ci/classify_changes.py`) force the three native lanes; the other workflow files route to the
Python lane, whose supply-chain tests check their pins. A lane skipped inside a green run advances
that lane's base, so a rarely-run lane never drags the others back. Caches are keyed
`<platform>-xcode<version>-<dependency graph>-<ISO week>` and saved only on an exact miss, so the
first run of each week (or of a new dependency graph) pays one save and the store holds at most a
couple of generations per platform; the shared package checkout has its own cache keyed on the two
`Package.resolved` digests. `scripts/ci/restore_mtimes.py` gives tracked files their commit mtimes so
Xcode's task signatures hit. Dispatch with `cold: true` to skip the restore. `nightly.yml` (04:00 UTC and on dispatch) runs a cold pass of the TSan
subset (`tsan`), the complete Python suite (`python-full`) and cold compiles of both platforms
(`foundation-cold`, which also compiles the macOS app optimized with warnings as errors); a failure
keeps one open issue labelled `nightly`, titled "Nightly lane failing", commenting on it rather than
filing a second. `security.yml` (CodeQL, npm audit) runs weekly, on dispatch and inside `release.yml`
on the tagged commit.

## Cache and generation policy

- `./scripts/regenerate_project.sh` (`--fast` is the historical spelling of the same default) runs
  XcodeGen and the two scheme renderers; `--verify` also runs the contract gate afterwards. Run it in
  the same commit as any file added, moved or deleted under a globbed Xcode target.
- `./scripts/build_foundation_targets.sh ios --incremental` reuses the governed
  `build/cache/xcode/ios-device` DerivedData and matches physical-device Release optimization.
- macOS builds keep one arena per optimization level: `build/cache/xcode/macos` for the `-Onone`
  development app, CLI and deterministic test bundles, `build/cache/xcode/macos-optimized` for
  `scripts/build.sh cli-optimized` and every macOS XCUITest lane (compiled at `-O`). An optimized build
  therefore never recompiles the `-Onone` arena; `build/vocello` points at whichever CLI built last.
  `scripts/macos_test.sh test` prints how many `SwiftCompile` tasks its build ran, the number that
  proves a warm cache locally and in CI.
- Internal diagnostic flags are target settings, so diagnostics never rebuild MLX and the other
  dependencies. `scripts/macos_test.sh test --coverage` is an opt-in llvm-cov export and forces a full
  rebuild of the shared cache.
- Serialize native Xcode commands (one SwiftPM lock spans XCTest); never clear caches to evade
  contention. `config/build-output-policy.json` owns every path under `build/`.

## What never runs from here

XCUITest, model downloads, generated audio, benchmarks, signing, notarization, App Store work and
releases run only when the task explicitly asks for that evidence, through their canonical scripts.

## Claude and Codex handoffs

Claude is the primary developer. Codex independently reviews and implements explicitly assigned work.
Both read `CLAUDE.md` and the same domain rules; `AGENTS.md` and `website/AGENTS.md` are small discovery
entry points. Work takes place on local `main`, with one editor and one native command at a time.
Reviews are read-only unless the assignment also requests implementation. Do not automatically launch
the other assistant, add another task ledger, or copy conversation transcripts into the repository.

1. Identify the roadmap item, objective, current assistant, permitted scope and acceptance criteria.
2. Record `git rev-parse HEAD`, `git status --short --branch` and any pre-existing dirty paths before
   editing. Prefer a coherent committed checkpoint for transfer; a dirty handoff must name exactly
   which changes belong to whom.
3. Make or review the assigned change, using the relevant rule and authoritative scripts. Never
   assume another assistant's claim of PASS proves the current source.
4. Record the implementation or findings, commands and verdicts, source identity, skipped checks and
   next action. Findings need a concrete trigger, impact, file/line, correction and regression case.
5. The receiving assistant checks HEAD, the actual diff and dirty paths against the handoff. If they
   differ unexpectedly, preserve the changes and reconcile ownership before editing or staging
   overlapping files. Never stash, reset, broadly stage or overwrite another assistant's work to
   make the handoff fit.

Use this compact handoff in the task response, or as a technical checkpoint in an existing relevant
reference document when durable evidence is needed. Roadmap status remains in `config/roadmap.json`:

```text
Assignment: roadmap ID; objective; Claude or Codex; review or implementation
Baseline: commit SHA; pre-existing dirty paths and ownership
Scope and acceptance: allowed areas; observable success criteria
Result: changed behavior or severity-ordered findings with file/line references
Verification: source identity; exact commands; PASS/FAIL/BLOCKED; artifact references
Open issues: existing roadmap IDs; unresolved hypotheses; deferred device/UI/model checks
Handoff: resulting commit/dirty paths; next action; ownership transferred by the user
```

The [2026-09-18 review](project-review-2026-09-18.md) records the initial cross-project assessment and
revalidation of the earlier audit. Reports explain evidence; they are not another status ledger.

## Codex project setup and tool routing

`.codex/environments/environment.toml` exposes Status, Check, Native tests, Build Mac app, Run Mac app,
Website checks and Toolchain audit using existing commands. Automatic setup is empty; opening a task
does not install dependencies, start an app or launch a build. Select the existing local checkout in
Codex; the repository prohibits worktrees. Actions that build or test native code must be serialized.

`.codex/hooks.json` runs the same five shell hooks as Claude. The shell matcher is `Bash`; file edits
arrive as `apply_patch`, with patch text in `tool_input.command`. `agent_hook_input.py` normalizes that
input and Claude file/notebook paths, including all patch operations and both sides of a rename.
Generated-file inspection rejects unreadable patch payloads. The PostToolUse reminder identifies the
root `project.yml`, including a move to or from that path. See the
[official hook contract](https://learn.chatgpt.com/docs/hooks) and
[instruction discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md).

Codex requires project hooks to be reviewed and trusted before they execute. The repository does not
alter that trust, global model choices, sandbox policy or personal tool configuration. Start a fresh
session after setup/trust changes; verify that the session summary appears and that root and website
tasks read the right entry points. A configuration file or a passing fixture is not evidence that a
particular app session has activated its hooks. Hooks have limited tool coverage and do not replace
the sandbox, source review or repository checks; they also cannot undo PostToolUse side effects.

| Need | Authoritative route | Optional assistance |
| --- | --- | --- |
| Native compile and deterministic tests | `scripts/dev.sh`, repository lane scripts and owned caches | XcodeBuildMCP discovery/debugging, with the checked-in profiles; never an alternative native UI driver |
| Apple behavior and diagnostics | Current source, Apple documentation, test artifacts | Axiom skills, Apple documentation tools, symbolication and crash analysis |
| CI and release evidence | GitHub check results for the exact commit | `gh` or connected GitHub tools; a skipped lane is not a freshly executed test |
| Website acceptance | `npm --prefix website run check`, including Playwright production-browser tests | Connected browser tools only as permitted by `website/CLAUDE.md` |
| Model and dependency research | Checked-in receipts, exact pins and maintenance contracts | Hugging Face and primary upstream documentation; availability never authorizes downloads or pin changes |

Ordinary development needs no new plugin or second MCP server. A missing optional connection is a
reason to use the script route, not to change a product gate. Deployment and release tools do not
grant publication authority.

Use `python3 scripts/supply_chain_contract.py --installed native|website|release|all` to compare the
installed tools with the manifest (choose one value after `--installed`). The Toolchain audit action
uses `all` and returns nonzero for drift. Report native/website readiness separately from release
readiness; an old release CLI does not prevent editing or deterministic development checks. The dated
review records this machine's observed versions. Keep local Xcode compatibility results distinct from
the pinned CI verdict; do not update pins or global installations merely to make the audit green.

Claude/Codex executable configuration changes select the shared hook tests locally and the Python
lane in CI. A native failure caused by restricted compiler-cache access, or a browser failure caused
by a denied loopback listener, is an environment blocker: preserve the failed attempt and request the
narrow host permission needed for the existing command, without clearing caches or weakening checks.
