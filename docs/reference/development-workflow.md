---
status: active
owner: release-qa
reviewed: 2026-10-10
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
scripts/dev.sh check --since origin/main  # the same over an unpushed batch of commits
scripts/dev.sh test --only FooTests  # one XCTest class on the incremental test build
scripts/dev.sh py                    # Python consumers of the changed tooling (--all, --lane, or modules)
scripts/dev.sh contracts             # the contract gate alone (check_project_inputs.sh --local)
scripts/dev.sh ios                   # generic device-SDK compile (incremental, no phone)
scripts/dev.sh regen                 # regenerate roadmap render, catalog, inventories, charts, attributions
scripts/dev.sh ci                    # what push CI runs, serially, when you want the push green first time
git add <assigned-files>
git commit
git push  # only after an explicit request
```

Routing is `scripts/ci/classify_changes.py`, the same file CI uses, so the local plan and the CI
lanes agree. `scripts/dev.sh check` compiles the affected XCUITest bundles through
`scripts/build_ui_test_bundles.sh` when UI-test sources or `project.yml` change; it never runs them.
Push CI compiles both bundles too (`--gate`, after the deterministic builds in their arenas) and never
runs them. XCUITest-only sources never reach the `swift` lane, since no deterministic bundle or TSan
subset compiles them: `Tests/VocelloMacUITests` routes to `macos_ui`, which runs `macos-tests` for
the bundle compile alone, and `Tests/VocelloiOSUITests` routes to `ios` alone
(`Tests/UIAutomationSupport` stays a `swift` input because `VocelloCoreTests` compiles part of it).
On a push, CI diffs each lane against the last run on the
branch in which that lane's job passed (not against the previous push), because `cancel-in-progress`
can drop a superseded push's run and the lanes it owed must still run on the next push; a lane with
no prior green run always runs. Locally the lanes come from the dirty tree, and a clean tree routes
no lane (`--since origin/main` plans for committed work): `swift` runs the macOS
test bundles (`scripts/macos_test.sh test`, or `core-test --only` when only test classes changed),
`ios` runs the generic compile, `python` runs the reverse-dependency Python selection, `website`
runs `npm --prefix website run check`. A change to shared tooling (`scripts/lib/`,
`scripts/development_workflow.py`, `config/toolchain.json`, `config/build-output-policy.json`) runs
the whole Python suite.

## The commit lint

`scripts/hooks/commit_lint.sh` (a Codex `PreToolUse` hook) requires branch `main` in the main
checkout or a `codex/*` branch in a registered linked worktree, pushes only from `main`, a whitespace-clean
staged diff (`git diff --cached --check`) and a clean `scripts/privacy_scan.py --staged` (no developer
home path, no credential-shaped token, no key file). It never builds or tests. Two more guards block
Simulator destinations, whole-cache deletion, force pushes, pushes of any ref but `main`, hand-made
branches, `project.pbxproj` writes and hand edits of generated files;
`scripts/tests/test_agent_hooks.py` pins all of them.

## The contract gate

`./scripts/check_project_inputs.sh` runs every deterministic contract: build-output policy, generated
schemes, CLI identity, localization, saved-voice lifecycle, entitlements, support contact, public facts
(`scripts/public_facts_contract.py`: release identity, README and website copy), attribution, runtime
security (debug knobs, concurrency registry, TSan policy), owned-runtime inventory, backend wiring,
model catalog and host availability, iOS storage protection, supply chain, release steps, benchmark
history, README charts, the text-level delivery-instruction copy and audio QC take inputs (script
pool, calibration-take policy), the roadmap, the exact
product-invariant greps in `scripts/repo_invariants.sh`, the privacy scan, and the Python suite.

`--python all|selected|none` picks the Python lane: `all` (the default) runs the whole suite;
`selected` runs the modules the dirty tree affects; `none` runs the contracts without the suite.
`--local` is `selected` plus a refusal to run when `CI` or `GITHUB_ACTIONS` is set. This is also how
`scripts/dev.sh check` gets its Python tests: it never calls pytest itself but runs
`./scripts/check_project_inputs.sh --local`, whose `selected` lane calls
`scripts/development_workflow.py py`. `QVOICE_GATES=quick` makes the `all` lane skip the suite outside
CI while nothing under `scripts/` or `config/` is dirty.

## Lint and warnings

`scripts/dev.sh lint` runs `git diff --check`, the privacy scan, shellcheck on changed shell and
SwiftLint's low-noise rules in `.swiftlint.yml` on changed Swift files under `Sources/` and `Tests/`
(advisory; formatting stays Xcode's). Both linters are pinned in `config/toolchain.json`; a missing
one is reported, not silently skipped, and a SwiftLint other than the pin is named
(`./scripts/install_pinned_tools.sh swiftlint` installs the pin; CI never runs it). Owned Xcode
targets compile with `SWIFT_TREAT_WARNINGS_AS_ERRORS`, so a new warning fails the local build before
it reaches CI. Flaky tests go into `config/test-quarantine.json`
(`Tests/VocelloCoreTests/TestQuarantine.swift` for XCTest, the pytest node id for Python); push CI
sets `VOCELLO_QUARANTINE=1` and skips them, nightly runs them, and `scripts/repo_invariants.sh`
fails once an entry is 30 days old.

## Python tests

pytest with `pytest-xdist` (`-n auto`), both pinned in `config/toolchain.json`. The whole suite runs
in about 65 to 90 seconds on the development Mac (Mac mini M6). `scripts/tests/conftest.py` marks
modules by name: `research` (audio, delivery, prosody and device-analysis tooling) runs when those
paths change and nightly. No module needs the macOS host: the benchmark publisher's host probes
(`swift -e`, `devicectl`) are mocked in its tests, so every module runs on Linux. Linux jobs run on
`ubuntu-24.04` (its Python 3.12), never `ubuntu-latest`, so an image migration cannot move the
interpreter under the gate; move the label deliberately. Every run prints its slowest
tests; a test that outgrows its lane moves, it does not slow every push. `pytest.ini` already passes
`-q`; adding another `-q` drops the summary line, so judge a run by pytest's exit code.

## CI

| Job | Runner | Runs when | Warm / cold |
| --- | --- | --- | --- |
| `changes` | ubuntu | always | seconds |
| `contracts` | ubuntu | always | about 1 min: the action-pin check (`supply_chain_contract.py`) first, then the complete deterministic contract gate (`check_project_inputs.sh --python none`: product contracts, invariants, privacy scan, work authority, benchmark history) |
| `python` | ubuntu | Python paths, contracts, workflow files | 3 to 4 min: product and tooling tests; research tests when routed |
| `macos-tests` | macos-26 | never on a pull request; Swift compile inputs, build configs, the lane's own scripts and the `scripts/` modules their Python imports; also macOS XCUITest sources (`macos_ui`), which run only the bundle compile | cached DerivedData; macOS bundles, CLI identity (`-Onone`, same settings as the bundles, about 30 s), then `build_ui_test_bundles.sh macos --gate` compiles the macOS XCUITest bundle in the same arena (build only) |
| `macos-tsan` | macos-26 | never on a pull request; the `swift` lane only (never `macos_ui`) | cached `macos-tsan` DerivedData; `scripts/macos_test.sh tsan`, the deterministic core bundles under ThreadSanitizer, blocking since 2026-09-14 (`config/tsan-policy.json`); 5 to 11 min on a second runner |
| `ios-compile` | macos-26 | never on a pull request; iOS compile inputs | cached DerivedData; `build_foundation_targets.sh ios --incremental` at `-Onone` (`QVOICE_FOUNDATION_SWIFT_OPTIMIZATION`), then `build_ui_test_bundles.sh ios --gate` compiles the iOS XCUITest bundle unsigned in the same arena (build only) |
| `website` | ubuntu | `website/` | about 1 min |
| `dependency-submission` | ubuntu | push only (skipped on dispatch and pull requests) | seconds: `scripts/swift_dependency_snapshot.py` submitted to the GitHub dependency graph; needed by `CI required` |
| `CI required` | ubuntu | always | the branch-protection context; skipped lanes count as passed |

`ci.yml` triggers on `push` to `main`, on `workflow_dispatch` and on `pull_request` against `main`.
Own work still goes straight to `main`; the pull-request lane (PA-23) exists for Dependabot and outside
contributors. It is `pull_request`, never `pull_request_target`: the PR's code runs with the
workflow's read-only token and no secrets, routed on its diff against the base, and only the Linux
jobs (`contracts`, `python`, `website`) can run; every macOS job and the dependency submission skip
by event, so `CI required` on a PR aggregates the Linux lanes and the push to `main` after merging
runs the Mac lanes. Pull-request runs never count as a lane's green base. A Dependabot action bump
moves the workflow SHAs but not `config/toolchain.json`, so its PR fails the first `contracts` step
with the fix: on the Dependabot branch run `python3 scripts/supply_chain_contract.py --sync-actions`
(it copies each action's SHA and `# vX.Y.Z` comment into the manifest) and push the result there. CI
never writes back: a write-token job on PR code, or a sync commit pushed with the workflow token (which
triggers no new run), would cost more than the one command. Concurrency is keyed on the event name
and the ref, so a newer push cancels the previous push run, a PR update cancels only that PR's run,
and a manual measurement dispatch never cancels the gate run for a commit. `scripts/dev.sh ci` replays that job
graph serially: project regeneration, the complete `check_project_inputs.sh` (the Linux `contracts`
job runs it with `--python none`), `scripts/macos_test.sh test`, `scripts/macos_test.sh tsan`, the
CLI version identity, `build_foundation_targets.sh ios --incremental`, `build_ui_test_bundles.sh all
--gate`, the website supply-chain
check and `npm --prefix website run check`. It is a superset rather than a byte-identical replay: it
skips no lane by routing, and it runs the whole Python suite inside the gate in one process where CI
splits it into `-m "not research"` plus an optional `-m research` on Linux.

Only push CI's own inputs (`.github/workflows/ci.yml`, `.github/actions/**`,
`scripts/ci/classify_changes.py`) force the three native lanes; the other workflow files route to
the Python lane, whose supply-chain tests check their pins. A lane skipped inside a green run
advances that lane's base, so a rarely-run lane never drags the others back. Caches are keyed
`<platform>-xcode<version>-<dependency graph>-<ISO week>` and saved only on an exact miss by a job
whose steps all passed (a failed build never becomes the week's snapshot), so the first run of each week (or of a new dependency graph) pays one save and the store holds at most a
couple of generations per platform; the shared package checkout has its own cache keyed on the two
`Package.resolved` digests. `scripts/ci/restore_mtimes.py` gives tracked files their commit mtimes
so Xcode's task signatures hit. Dispatch with `cold: true` to skip the restore. `nightly.yml` (04:00
UTC and on dispatch) runs a cold pass of the TSan subset (`tsan`), the complete Python suite
(`python-full`) and cold compiles of both platforms (`foundation-cold`, which also compiles the
macOS app optimized with warnings as errors); a failure keeps one open issue labelled `nightly`,
titled "Nightly lane failing", commenting on it rather than filing a second
(`scripts/ci/failure_issue.py`). `release-rehearsal.yml` runs weekly, on dispatch and on pushes that
touch release inputs: without secrets it installs the release toolchain through
`.github/actions/native-toolchain`, runs the ledgered `release.sh` (ad-hoc signed, not notarized)
and the packaged-DMG verification, and validates the release evidence locally; a failure keeps one
issue labelled `release-rehearsal`. `security.yml` (CodeQL, npm audit) runs weekly, on dispatch and
inside `release.yml` on the tagged commit.

## Cache and generation policy

- `./scripts/regenerate_project.sh` (`--fast` is the historical spelling of the same default) runs
  XcodeGen and the two scheme renderers; `--verify` also runs the contract gate afterwards. Run it in
  the same commit as any file added, moved or deleted under a globbed Xcode target.
- `scripts/project_generation.py` computes one signature over specifications/includes, generator
  implementations/templates and sorted source/resource membership. Regeneration, build-cache
  freshness and local check planning use it. Added/deleted/renamed inputs and missing generated
  outputs regenerate; ordinary source content edits preserve incremental reuse.
- `./scripts/build_foundation_targets.sh ios --incremental` reuses the governed
  `build/cache/xcode/ios-device` DerivedData and matches physical-device Release optimization.
- macOS builds keep one arena per optimization level: `build/cache/xcode/macos` for the `-Onone`
  development app, CLI and deterministic test bundles, `build/cache/xcode/macos-optimized` for
  `scripts/build.sh cli-optimized`, every macOS XCUITest lane (compiled at `-O`) and the
  `build_ui_test_bundles.sh` compile check, which uses the lane's exact settings and the shared package
  checkout so it warms the lane's cache (about 10 s warm). An optimized build
  therefore never recompiles the `-Onone` arena; `build/vocello` points at whichever CLI built last.
  `scripts/macos_test.sh test` prints how many `SwiftCompile` tasks its build ran, the number that
  proves a warm cache locally and in CI.
- Internal diagnostic flags are target settings, so diagnostics never rebuild MLX and the other
  dependencies. `scripts/macos_test.sh test --coverage` is an opt-in llvm-cov export and forces a full
  rebuild of the shared cache.
- Native Xcode/SwiftPM commands are serialized host-wide: `xcb_run`, SwiftPM resolution, the UI-bundle
  compile, the macOS XCTest bundle runs and the runtime `swift build`/`swift test` hold the native lock
  (`hostNativeLock` in `config/build-output-policy.json`, `~/Library/Caches/Vocello/native-build.lock`)
  across every checkout and worktree, and a waiter prints the holder each minute. Never clear caches to
  evade contention. `config/build-output-policy.json` owns every path under `build/`.

## Operating defaults

`AGENTS.md` owns the working agreement. Read `native-engineering.md` for Swift/runtime work and
`tooling-and-evidence.md` for contracts, CI, debugging, benchmarks and release logic. These are
explicitly linked references, not automatically loaded path-scoped rules.

Use targeted deterministic tests, changed-file lint and warm incremental builds while editing.
Before committing run the routed checks and review the actual diff. Use independent Swift review
for substantive Swift changes and focused review for persistence, privacy, hooks and release paths.
At a coherent checkpoint run the smallest relevant existing model, UI, device or performance lane.
Full matrices are task/release-specific. Local validation and scoped commits on `main` are authorized;
pushes require an explicit request, including the existing unpushed commits. Do not reinterpret a
script's structural permission to push `main` as conversational authorization.

Reuse installed assets. New large downloads, model installs, dependency repins, global settings,
release/signing/deployment/publication and external writes require specific authorization.
Preserve the original failure. Investigate it before a rerun; record the reason and new run ID.

## Parallel agents and worktrees

Use selective parallelism for disjoint editing, research, review or triage. At most four agents may
be active including the lead, inheriting the selected model; `.codex/config.toml` records this limit.
One full Python suite and one browser acceptance run at a time on the 16 GB development host.
Agents doing native work remain code-only; the lead owns native builds and all measured lanes.

Create editing worktrees with Codex's managed-worktree tool, passing the lead's exact committed
checkpoint as `ref` (the tool otherwise defaults to the remote default branch). Never assume it
copies dirty files. Inspect Git metadata and commit identity. If creation returns detached HEAD,
`git switch -c codex/<scope>` inside that registered linked checkout establishes its scoped branch;
the command guard permits only this non-resetting creation there. A directory name is not proof
of repository identity. Give each worker a disjoint file set and clear validation limits.

Agents make scoped commits and never push, modify the roadmap/checkpoint or run models, devices,
native UI or native builds. The lead reviews each commit, integrates with `git cherry-pick` or
`git merge --ff-only`, and validates the combined result on the warm main cache. Do not edit scripts
used by a running lane. Archive integrated worktrees with the Codex managed-worktree tool, preserving
needed ignored evidence first; never discard unintegrated work to tidy the workspace.

Before source-bound measurements join or stop all delegated work. `scripts/active_workers.py`
uses supported SessionStart/SubagentStart/SubagentStop/SessionEnd events, host-wide leases and live
process start identities. Dead, reused-PID and non-Codex ownership records cannot establish activity.
Unknown ownership blocks measurements. A locked Git worktree may be idle and is never counted.
Root interruption/teardown does not prove workers stopped, so live worker leases remain conservative.

The startup hook emits the session's opaque `QVOICE_WORKER_SESSION` marker; pass it to measured
commands to establish *this session's* registration. Another session's receipt cannot establish it.
If hooks or ownership inventory are unavailable, join all known workers and explicitly use
`QVOICE_LEAD_ONLY=1` for the lane. Never use that declaration to bypass a known active or unknown
worker lease. Registration failures invalidate the session receipt and retain a conservative marker;
inspect unresolved markers after joining work rather than blindly deleting them. Hooks cannot prove
all clients on the host are instrumented, so the lead still checks its known workers and host posture.

`require_quiet_host` also checks native-lock ownership, load and memory pressure. The existing
`QVOICE_ALLOW_BUSY_HOST=1` path remains explicitly exploratory; it cannot override unknown worker
ownership and cannot make a loaded measurement publishable. Only existing non-timing audio-QC
model lanes may pass `agents-allowed`; they still respect host load/memory/native serialization.

## Codex setup and tool routing

Repository instructions use supported [AGENTS.md discovery](https://learn.chatgpt.com/docs/agent-configuration/agents-md).
Skills use [.agents/skills discovery](https://learn.chatgpt.com/docs/build-skills), with six thin
wrappers: `vocello-ios-validation`, `vocello-macos-ui`, `vocello-device-diagnostics`,
`vocello-benchmark`, `vocello-debug` and read-only `vocello-release-readiness`.
They may be selected implicitly for authorized local work; they do not grant external-write authority.
Read-only [custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents) live in
`.codex/agents`: `vocello-swift-review` and `vocello-xcresult-triage`. Both inherit the selected model.

The sole [hook definition](https://learn.chatgpt.com/docs/hooks) is `.codex/hooks.json`, beside
`.codex/config.toml`. Opening a session installs nothing and never builds or touches a phone.

| Event | Tool/event matcher | Handler | Effect |
| --- | --- | --- | --- |
| SessionStart | startup/resume/clear/compact | session_start.sh, worker_lifecycle.py | Bounded local Git/status/checkpoint context and current session receipt |
| PreToolUse | Bash | commit_lint.sh, policy_guard.sh | Checkout-aware Git, whitespace, privacy, cache, generated-project and physical-device safeguards |
| PreToolUse | apply_patch | generated_file_guard.sh | Protects every add/update/delete/move target in a multi-file patch |
| PreToolUse | MCP names | simulator_tool_guard.py | Refuses unsupported simulator tool routes |
| PostToolUse | apply_patch | project_yml_reminder.sh | Reminds to check the shared generation signature after project/source membership edits |
| SubagentStart / SubagentStop / SessionEnd | all | worker_lifecycle.py | Active-worker registration, completion and conservative teardown |

Hook commands locate the actual checkout with Git, quote paths with spaces, and use payload `cwd`
when judging tool actions. Codex's canonical Bash payload is `tool_input.command`; `apply_patch`
uses the same field containing the complete patch. Edit/Write matcher aliases do not change that
payload. The adapter retains legacy file-edit payload support for callable regression fixtures.
File guards fail closed on unreadable paths/patches. Tokenized Git parsing handles global options,
literal `-C`, chains, subshells and heredocs. Generated guards cover renamed sources and destinations.
These cooperative guards cannot sandbox interpreter indirection or arbitrary external programs.

Trust is a separate host decision: trust the project and review the current hook definition in
Codex's `/hooks` UI. New/changed untrusted definitions are skipped until reviewed. Managed-host policy
may prohibit repository hooks, and cloud orchestration does not support local command hooks.
Do not self-approve hooks, bypass hook trust or modify global trust/settings to make a check pass.
Report inactive/unverified hooks explicitly. `scripts/dev.sh doctor --json` inventories configuration,
tools and configuration presence; it cannot establish MCP availability or persisted hook trust.

Safeguards are also callable without activation:

```sh
scripts/hooks/commit_lint.sh --staged
git diff --check
python3 scripts/privacy_scan.py --changes
scripts/repo_invariants.sh
python3 scripts/build_output_policy.py validate
python3 -m pytest scripts/tests/test_agent_hooks.py scripts/tests/test_active_workers.py
```

`policy_guard.sh` and `generated_file_guard.sh` can read a fixture hook JSON on stdin; their tests
exercise allowed and blocked operations without running destructive commands. CI classification,
Python consumer selection and reference scanners include `.codex/` and `.agents/`, including deleted
paths; config-only edits exercise behavioral checks without triggering native builds.

For a fresh-session smoke check, verify AGENTS root/subdirectory discovery, the six repository skills,
two read-only agents and their inherited model/concurrency settings. Inspect `/hooks` for source,
trust and enabled state, then use harmless guard fixtures (never a real destructive command).
Confirm SessionStart context and worker receipt creation, SubagentStart/Stop behavior, a multi-file
patch guard and a managed checkout with spaces. Record exact client/host version and any unavailable
discovery or trust surface. Static parsing and unit tests alone do not prove fresh-session activation.

| Work | Authoritative route | Optional assistance |
| --- | --- | --- |
| Builds/tests/native UI | Repository scripts, owned caches and XCUITest | XcodeBuildMCP discovery or compatible debugging under host serialization; no alternative native UI driver |
| Apple architecture/APIs | Source, Apple primary docs and retained artifacts | Applicable Axiom skills; Sosumi for Apple docs; Context7 for libraries |
| MLX runtime | Owned facade, exact pins and mlx-guide.md | Installed swift-mlx / swift-mlx-lm skills |
| Finished native run | `scripts/dev.sh triage <run-directory> --json` and testing-runbook.md | Read-only vocello-xcresult-triage agent, xcresulttool, LLDB when indicated |
| Build/crash/trace diagnosis | Raw logs, crash reports, existing traces | Verified Axiom axbuild, xcsym and xcprof helpers with script-only fallback |
| Website | `npm --prefix website run check` | Browser tools for local rendered inspection; relevant Impeccable/Vercel guidance |
| Repository/CI | Exact-commit checks and repository release scripts | GitHub connector or gh reads; observe CI after an authorized push |
| App Store/deployment/publication | Explicitly requested release workflow | Available asc-* / Vercel tools; reads do not authorize writes |
| Model research | Receipts, exact pins and maintenance contracts | Hugging Face read-only metadata; no implied download or repin |

Detect capabilities in the current session rather than assuming installation means connection.
XcodeBuildMCP's scratch builds bypass repository serialization: prefer scripts; if diagnosis needs
such a build, the lead must hold the same native lock for the whole operation. Never run it alongside
another native action/evidence lane. Optional helpers must exist, be executable and pass a non-mutating
help/version probe via their installed Axiom location. Keep raw native logs, original exit status,
optimization flags and evidence manifests; compact helper output cannot replace their contracts.
Use xcsym for retained crash symbolication and xcprof for existing trace inspection. Do not use xcui:
its simulator UI route conflicts with this project's physical-iPhone/XCUITest rules. Missing optional
tools never block the script workflow; personal plugins, skills, accounts and credentials are not CI
dependencies. Never install or change global configuration simply to satisfy a routing table.
