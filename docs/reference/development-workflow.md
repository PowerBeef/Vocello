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
git add <assigned-files>
git commit
git push
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

`scripts/hooks/commit_lint.sh` (a Codex `PreToolUse` hook) requires
branch `main`, a whitespace-clean staged diff (`git diff --cached --check`) and a clean
`scripts/privacy_scan.py --staged` (no developer home path, no credential-shaped token, no key file).
It never builds or tests. Two more guards block Simulator destinations, whole-cache deletion, force
pushes, new branches, `project.pbxproj` writes and hand edits of generated files;
`scripts/tests/test_agent_hooks.py` pins all of them.

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

## Codex development workflow

Codex is the sole development agent; `AGENTS.md` owns the working agreement. Work on the existing
local `main` checkout without delegation. Before editing, record HEAD, dirty files and the relevant
roadmap item or user assignment. Preserve unrelated work; reconcile an unexpected change before
editing or staging overlapping files. Implement, run affected checks, review the diff, commit only
the assignment and push. Report the behavior change, checks and limitations, commit/CI evidence and
next action. Update the existing checkpoint or roadmap only when status changes; no transcripts or
second work ledger.

Keep the loop small: focused tests while editing, one routed check before completion, broader checks
only for new changes or unresolved failures. `check --paths <assigned paths...>` scopes the outer
build/lint plan when unrelated work is paused; its contract gate still selects Python tests from the
actual dirty tooling. A skipped CI lane is not a new test run. Do not add validators for prose,
plugin inventories, or tool availability. Existing product and release gates remain authoritative.

## Codex setup and tool routing

The existing environment actions expose Status, Check, Native tests, Build Mac app, Run Mac app,
Website checks and Toolchain audit. Automatic setup is empty. Opening a task never installs tools,
builds, probes a phone or starts an app. Native commands are serialized on the owned caches.

`.codex/hooks.json` wires the five repository guards. Shell calls, including unified exec and nested
code-mode tool calls, match `Bash`; patch calls match `apply_patch` and provide patch text in
`tool_input.command`. The input adapter inspects every added, updated, deleted and moved path,
including both sides of renames. Unreadable patch input is rejected. The project reminder names the
existing regeneration command. Hooks resolve from the checkout rather than a personal environment
variable. Startup prints only bounded local Git/status/checkpoint context.

Project hooks require platform trust and cover only supported tool routes. Passing fixtures do not
prove that a running session enabled them; they cannot undo post-tool side effects or replace the
sandbox. See the [hook contract](https://learn.chatgpt.com/docs/hooks) and
[instruction discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md). After changing
instructions or hooks, use a fresh session to check root/website guidance, explicit skill discovery,
the startup summary and harmless allowed/blocked fixture behavior. Report runtime activation as
unverified when a fresh trusted session is unavailable. Never try a real destructive command as a
hook test.

| Work | Authoritative route | Relevant optional assistance |
| --- | --- | --- |
| Native build/test/UI evidence | Repository scripts, owned caches and XCUITest | XcodeBuildMCP discovery/debugging with existing profiles; no alternative native UI driver |
| Apple code and diagnostics | Source, Apple documentation and test artifacts | Axiom, Apple documentation MCP, native-app and Swift/MLX skills; select the relevant specialty only |
| Website | `npm --prefix website run check` with Playwright | Codex browser tools for visual/interactive checks; Impeccable and relevant Vercel/library guidance under `website/AGENTS.md` |
| CI and release evidence | Exact-commit GitHub checks and repository release scripts | GitHub CLI or connector; release tools require explicit publication authority |
| Model/dependency research | Receipts, exact pins and maintenance contracts | Hugging Face and upstream documentation; no implied download or pin-change permission |

Use tools callable in the current session, with script/primary-documentation fallbacks. Do not
install plugins, duplicate servers or change global settings just to satisfy this table. Personal
plugins, accounts and skill caches are not CI dependencies. Generic plugin advice never overrides
physical-iPhone-only, script-owned native UI, cache ownership or consent requirements.

Four explicit shortcuts live under `.agents/skills`: `$ios-lane`, `$macos-ui-lane`,
`$device-diagnostics` and `$release-evidence`. Their `agents/openai.yaml` disables implicit invocation;
they call existing scripts, not a second execution engine. Codex triages the resulting evidence
itself using the [testing runbook](testing-runbook.md). No installed specialist skill or MCP server is
mandatory. Codex executable configuration and skill invocation metadata route into the existing
Python lane; prose alone does not select native work.

The Toolchain audit action runs `python3 scripts/supply_chain_contract.py --installed all`.
Choose `native`, `website` or `release` for focused audits. Report local compatibility separately
from pinned CI and release readiness. Keep pins/global installations unchanged unless assigned;
release CLI drift does not block ordinary development. For compiler-cache or loopback permission
failures, preserve the failed attempt and request the narrow access the existing command needs.
