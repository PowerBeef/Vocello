# Development workflow

Local verification is fast and advisory; CI on `main` is the gate. Nothing blocks a commit except a
15-second lint.

## Daily loop

```sh
scripts/dev.sh check --dry-run       # what the dirty tree needs
scripts/dev.sh check                 # lint, contracts, selected Python tests, native lanes touched
scripts/dev.sh test --only FooTests  # one XCTest class on the incremental test build
scripts/dev.sh py --changed          # Python tests that consume the changed tooling
scripts/dev.sh ios                   # generic device-SDK compile (incremental, no phone)
scripts/dev.sh regen                 # regenerate roadmap render, catalog, inventories, charts
git add -A && git commit && git push
```

Routing is `scripts/ci/classify_changes.py`, the same file CI uses, so the local plan and the CI lanes
agree: `swift` runs the macOS test bundles (`scripts/macos_test.sh test`, or `core-test --only` when
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

`--local` selects Python tests by the dirty tree; `--python darwin-only` runs only the modules that need
the macOS host (CI runs the rest on Linux); the default runs everything.

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
| `CI required` | ubuntu | always | the branch-protection context; skipped lanes count as passed |

Caches are keyed on the toolchain and dependency graph and saved after every run on `main`;
`scripts/ci/restore_mtimes.py` gives tracked files their commit mtimes so Xcode's task signatures hit.
Dispatch with `cold: true` to skip the restore. `nightly.yml` runs the TSan subset, the complete Python
suite and cold compiles of both platforms and files one `nightly` issue on failure; `security.yml`
(CodeQL, npm audit) runs weekly, on dispatch and inside `release.yml` on the tagged commit.

## Cache and generation policy

- `./scripts/regenerate_project.sh --fast` runs XcodeGen and the two scheme renderers; the plain form
  also runs the contract gate afterwards.
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
