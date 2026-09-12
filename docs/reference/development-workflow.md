---
status: active
owner: release-qa
reviewed: 2026-09-12
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
agree. Neither `scripts/dev.sh check` nor push CI compiles the XCUITest bundles: after editing
`Tests/*UITests` or `Tests/UIAutomationSupport`, run `xcodebuild build-for-testing` for `VocelloMacUI`
and `VocelloiOSUI` (generic iOS destination, unsigned, `-skipPackagePluginValidation`) before
committing. On a push, CI diffs each lane against the last run on the branch in which that lane's job
passed (not against the previous push), because `cancel-in-progress` can drop a superseded push's run
and the lanes it owed must still run on the next push; a lane with no prior green run always runs.
Locally the lanes come from the dirty tree: `swift` runs the macOS test bundles (`scripts/macos_test.sh test`, or `core-test --only` when
only test classes changed), `ios` runs the generic compile, `python` runs the reverse-dependency Python
selection, `website` runs `npm --prefix website run check`. A change to shared tooling
(`scripts/lib/`, `scripts/development_workflow.py`, `config/toolchain.json`,
`config/build-output-policy.json`) runs the whole Python suite.

## The commit lint

`scripts/hooks/commit_lint.sh` (a Claude Code `PreToolUse` hook in `.claude/settings.json`) requires
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
| `contracts` | ubuntu | always | about 1 min: action pins, invariants, privacy scan, roadmap |
| `python` | ubuntu | Python or workflow paths | 2 to 3 min: product and tooling tests; research tests when routed |
| `macos-tests` | macos-26 | Swift, config, scripts or workflow paths | cached DerivedData; contract gate (darwin-only Python), macOS bundles, CLI identity |
| `ios-compile` | macos-26 | iOS-relevant paths | cached DerivedData; `build_foundation_targets.sh ios --incremental` |
| `website` | ubuntu | `website/` | about 4 min |
| `dependency-submission` | ubuntu | push only (skipped on dispatch) | seconds: `scripts/swift_dependency_snapshot.py` submitted to the GitHub dependency graph; needed by `CI required` |
| `CI required` | ubuntu | always | the branch-protection context; skipped lanes count as passed |

`ci.yml` triggers on `push` to `main` and on `workflow_dispatch` only; it has no `pull_request`
trigger, so `CI required` is always produced by a maintainer's push to `main`. `scripts/dev.sh ci`
replays that job graph serially: the supply-chain contract, `scripts/repo_invariants.sh`, the privacy
scan, `roadmap.py validate` and `render --check`, project regeneration, the complete
`check_project_inputs.sh`, `scripts/macos_test.sh test`, the CLI version identity,
`build_foundation_targets.sh ios --incremental`, the website supply-chain check and
`npm --prefix website run check`. It is a superset rather than a byte-identical replay: it skips no
lane by routing, and it runs the whole Python suite inside the gate in one process where CI splits it
into `-m "not research and not darwin_only"` plus an optional `-m research` on Linux and
`--python darwin-only` in the macOS job.

Caches are keyed on the toolchain and dependency graph and saved after every run on `main`;
`scripts/ci/restore_mtimes.py` gives tracked files their commit mtimes so Xcode's task signatures hit.
Dispatch with `cold: true` to skip the restore. `nightly.yml` (04:00 UTC and on dispatch) runs the TSan
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
- Internal diagnostic flags are target settings, so diagnostics never rebuild MLX and the other
  dependencies. `scripts/macos_test.sh test --coverage` is an opt-in llvm-cov export and forces a full
  rebuild of the shared cache.
- Serialize native Xcode commands (one SwiftPM lock spans XCTest); never clear caches to evade
  contention. `config/build-output-policy.json` owns every path under `build/`.

## What never runs from here

XCUITest, model downloads, generated audio, benchmarks, signing, notarization, App Store work and
releases run only when the task explicitly asks for that evidence, through their canonical scripts.
