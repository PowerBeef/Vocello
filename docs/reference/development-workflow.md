---
status: active
owner: release-qa
reviewed: 2026-10-12
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
test bundles, `ios` runs the generic compile, `python` runs the Python selection, `website`
runs `npm --prefix website run check`. Push CI also runs the TSan subset with `swift`; the local
check does not.

The `swift` lane runs `core-test --only` for the test classes that changed and for the classes whose
sources name a changed record or fixture by file name (`config/ios-memory-budget-policy.json`, the
parity fixtures). Any other input runs the whole `scripts/macos_test.sh test`: product Swift, lane
scripts and their imports, `scripts/lib/`, build and toolchain configs, project and workflow files,
and a record that only a helper without a test class or the owned runtime package's tests read (the
package tests have no focused runner). A `swift` lane that would schedule nothing runs it too.

The Python selection follows the import graph CI builds (`scripts/ci/classify_changes.py`) in
reverse: a changed module reaches every file that imports it, transitively, and a module inside a
package such as `scripts/qc/` reaches every importer of the package. A test module runs when it is
one of those files, or names the changed file or one of them by file name or repository path. Name
matching is one step deep and never iterated; only when no test imports or names an input do the
scripts that name it stand in for it, one step further. A change to `development_workflow.py` or
`ci/classify_changes.py` always runs both routing suites. An input with no test consumer, and shared
tooling (`scripts/lib/`, `scripts/tests/fixtures/`, `scripts/tests/conftest.py`, `pytest.ini`,
`config/toolchain.json`, `config/build-output-policy.json`), run the whole suite. A config or roadmap
edit selects a handful of modules, so a test that reaches its input only through another script can
be missed locally; the Linux CI job still runs the whole suite.

## The commit lint

`scripts/hooks/commit_lint.sh` (a Claude Code `PreToolUse` hook) requires branch `main` in the main
checkout or a `worktree-*` branch in a registered linked worktree (a Claude Code agent worktree), pushes
only from `main`, a whitespace-clean
staged diff (`git diff --cached --check`) and a clean `scripts/privacy_scan.py --staged` (no developer
home path, no credential-shaped token, no key file). It never builds or tests. Its one advisory check
returns a warning, not a block, when behaviour-bearing Swift is committed without the Swift review's
trailer (see Operating defaults); a message it cannot read skips the check. Two more guards block
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
`scripts/lib/contract_gate.py` lists the validators and runs them in parallel, one per core, printing
each one's output as one block in their fixed order; every validator runs even after one fails, and
any failure fails the gate (about 3 s, where running them one after another took about 11 s).

With `--local`, a validator runs only when a changed path falls under the inputs `contract_gate.py`
declares for it (its script, the modules it imports, the files and directories it reads or tests for
existence), and one line says how many were skipped. A validator whose result also depends on every
tracked file, git history or the date declares no inputs and always runs: the build-output policy,
runtime security, `roadmap.py validate`, `repo_invariants.sh` and the privacy scan. Everything runs on
a clean tree, when git cannot list the changes or when the gate itself changed; a roadmap-only change
runs six validators in about 2 s. The changed paths are the dirty tree (renames as both sides) plus
`check --since` work, or `QVOICE_CHANGED_PATHS` (one path per line) when a caller sets it. CI, the
release and `scripts/dev.sh ci` never pass `--local`, so they run every validator. A validator that
starts reading a new path updates its entry in `contract_gate.py` in the same change.

`--python all|selected|none` picks the Python lane: `all` (the default) runs the whole suite;
`selected` runs the modules the dirty tree affects; `none` runs the contracts without the suite.
`--local` is `selected` plus the validator selection above, and is refused when `CI` or
`GITHUB_ACTIONS` is set. This is also how
`scripts/dev.sh check` gets its Python tests: it never calls pytest itself but runs
`./scripts/check_project_inputs.sh --local`, whose `selected` lane calls
`scripts/development_workflow.py py`. `QVOICE_GATES=quick` makes the `all` lane skip the suite outside
CI while nothing under `scripts/` or `config/` is dirty.

## Lint and warnings

`scripts/dev.sh lint` runs `git diff --check`, the privacy scan, shellcheck on changed shell and
SwiftLint's low-noise rules in `.swiftlint.yml` on changed Swift files under `Sources/` and `Tests/`
(advisory locally, where it reports every finding on a changed file; formatting stays Xcode's). Both
linters are pinned in `config/toolchain.json`; a missing one is reported, not silently skipped, and a
SwiftLint other than the pin is named (`./scripts/install_pinned_tools.sh swiftlint` installs the pin;
CI gates it, below). Owned Xcode targets compile with `SWIFT_TREAT_WARNINGS_AS_ERRORS`, so a new
warning fails the local build before it reaches CI. Flaky tests go into `config/test-quarantine.json`
(`Tests/VocelloCoreTests/TestQuarantine.swift` for XCTest, the pytest node id for Python); push CI
sets `VOCELLO_QUARANTINE=1` and skips them, nightly runs them, and `scripts/repo_invariants.sh`
fails once an entry is 30 days old.

CI's `contracts` job lints the whole tree through `scripts/lint_baseline.py`: shellcheck
(`-x -S warning`) over every tracked shell script, ruff over every tracked Python file with only
syntax errors (`E9`) and pyflakes (`F`) selected in `ruff.toml` (Python 3.10; 3.9 for the hooks and
`scripts/select_python.py`), and SwiftLint's `.swiftlint.yml` rules over every tracked Swift file its
`excluded` list leaves in (`Sources/`, `Tests/` and `scripts/`; not `Packages/`). All three are
SHA-pinned in `config/toolchain.json` (`artifactPins`; the runner installs the `-linux-x86_64`
entries, for SwiftLint its fully static binary, which needs no Swift toolchain because none of the
rules uses SourceKit). Only a finding absent from `config/lint-baseline/<tool>.json` fails; the
SwiftLint baseline was empty when its gate began (DW-03), so any finding of its rules fails. A
finding is keyed by file, rule and the text of its line, not its line number, so editing a line that
carries a baselined finding makes it new: fix it then. The baselines only shrink: `python3
scripts/lint_baseline.py shellcheck|ruff|swiftlint` reproduces the gate locally and names entries
that no longer occur, `--update` removes them, and nothing adds one.

## Python tests

`scripts/dev.sh` selects an already-installed Python and propagates it to its child commands.
Use `VOCELLO_PYTHON=/absolute/path/to/python3 scripts/dev.sh ...` for an explicit interpreter;
this changes only that invocation, with no global PATH or package installation. `doctor --json`
reports the selected executable, installed test-package versions and their pin compatibility.
Keep CI's declared Python environment; a missing local package is a prerequisite failure, not a
reason to skip tests. Standalone `python3` commands still use the caller's shell environment.

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

`CLAUDE.md` owns the working agreement. `native-engineering.md` (Swift/runtime) and
`tooling-and-evidence.md` (contracts, CI, debugging, benchmarks, release) are path-scoped rules: their
`paths:` front matter loads them through the `.claude/rules` symlinks when matching files are touched.
Read them directly when planning.

Use targeted deterministic tests, changed-file lint and warm incremental builds while editing.
Before committing run the routed checks and review the actual diff. Use independent Swift review
for substantive Swift changes and focused review for persistence, privacy, hooks and release paths.
The Swift review (`vocello-swift-review`) checks the policy boundaries, then test adequacy for every
behavioural change: a test that fails when the fix is reverted, fakes that reach the changed code,
assertions on what happened rather than on a state another path also publishes, cancellation and
swallowed errors on error paths, and a named parity fixture or seeded canary for numerics. Record a
completed review in the commit message with the trailer `Reviewed-by: vocello-swift-review`
(`git commit --trailer 'Reviewed-by: vocello-swift-review'`); for an agent's commit reviewed before
integration, `git cherry-pick -n <sha>`, then `git commit -C <sha> --trailer '...'`. The commit lint
warns, never blocks, when a commit of Swift under `Sources/QwenVoiceCore`, `Sources/iOS`,
`Sources/Services`, `Sources/ViewModels` or `Packages/*/Sources` lacks it.
At a coherent checkpoint run the smallest relevant existing model, UI, device or performance lane.
Full matrices are task/release-specific. Local validation and scoped commits on `main` are authorized;
pushes require an explicit request, including the existing unpushed commits. Do not reinterpret a
script's structural permission to push `main` as conversational authorization.

Reuse installed assets. New large downloads, model installs, dependency repins, global settings,
release/signing/deployment/publication and external writes require specific authorization.
Preserve the original failure. Investigate it before a rerun; record the reason and new run ID.

## Parallel agents and worktrees

Use selective parallelism for disjoint editing, research, review or triage. At most four agents may be
active including the lead, inheriting the selected model. This limit is an instruction: a hook cap would
misread a subagent that died without SubagentStop as still active until its session ends.
One full Python suite and one browser acceptance run at a time on the 16 GB development host.
Agents doing native work remain code-only; the lead owns native builds and all measured lanes.

Create editing agents with the Agent tool and `isolation: "worktree"`. Claude Code creates
`.claude/worktrees/<name>` on branch `worktree-<name>` from local HEAD (`worktree.baseRef: head` in
`.claude/settings.json`), so commit the lead checkpoint first: dirty files do not carry over. An unchanged
agent worktree is removed automatically. Inspect Git metadata and commit identity; a directory name is not
proof of repository identity. Give each worker a disjoint file set and clear validation limits; the
SubagentStart hook repeats the agent rules to every subagent, and `agent_guard.py` enforces them: only a
subagent's hook input carries `agent_id`, so it alone is refused pushes, commits in the main checkout,
native builds and tests, device, model and measured-lane scripts (sourcing a lane script or a
`scripts/lib` shell library included, since that leaves `build` or `xcb_run` callable by bare name) and
edits of `config/roadmap.json` or `docs/development-progress.md`. Hand-made branches and worktrees stay
denied.

Agents make scoped commits on their `worktree-*` branch and never push, modify the roadmap/checkpoint or
run models, devices, native UI or native builds. The lead reviews each commit, integrates with
`git cherry-pick` or `git merge --ff-only`, and validates the combined result on the warm main cache. Do
not edit scripts used by a running lane. Remove integrated worktrees with
`git worktree remove .claude/worktrees/<name>` and `git branch -d worktree-<name>`, preserving needed
ignored evidence first; never discard unintegrated work to tidy the workspace (`--force` and
`git branch -D` ask first). A cherry-picked branch is never merged, so `-d` refuses it: when
`git cherry main worktree-<name>` prints only `-` lines, every commit is on `main` and `-D` loses nothing.

Before source-bound measurements join or stop all delegated work. `scripts/active_workers.py`
uses the SessionStart/SubagentStart/SubagentStop/SessionEnd hook events, host-wide leases and the live
start identity of the native `claude` process. Dead, reused-PID and non-Claude ownership records
(including retired Codex leases and Node-hosted clients) cannot establish activity.
Unknown ownership blocks measurements. A locked Git worktree may be idle and is never counted.
Root interruption/teardown does not prove workers stopped, so live worker leases remain conservative.

The SessionStart hook exports the session's opaque `QVOICE_WORKER_SESSION` marker to later Bash calls
through `CLAUDE_ENV_FILE` and names it in the session context; it establishes *this session's*
registration. Another session's receipt cannot establish it.
If hooks or ownership inventory are unavailable, join all known workers and explicitly use
`QVOICE_LEAD_ONLY=1` for the lane. Never use that declaration to bypass a known active or unknown
worker lease. Registration failures invalidate the session receipt and retain a conservative marker;
inspect unresolved markers after joining work rather than blindly deleting them. Hooks cannot prove
all clients on the host are instrumented, so the lead still checks its known workers and host posture.

`require_quiet_host` also checks native-lock ownership, load and memory pressure. The existing
`QVOICE_ALLOW_BUSY_HOST=1` path remains explicitly exploratory; it cannot override unknown worker
ownership and cannot make a loaded measurement publishable. Only existing non-timing audio-QC
model lanes may pass `agents-allowed`; they still respect host load/memory/native serialization.
Cache-only audio rescoring uses `check_cache_only_host` instead: load and memory pressure are
recorded without blocking. This deterministic analysis makes no latency or memory-qualification
claim; worker ownership and native-lock checks remain. Do not use it for inference, generation,
UI, performance or memory measurements.

## Claude Code setup and tool routing

Claude Code reads `CLAUDE.md` at the repository root and `website/CLAUDE.md` once website files are
touched. `.claude/rules/native.md` and `.claude/rules/tooling.md` are symlinks to the two reference
rules above. Six thin skills live in `.claude/skills` and run as `/vocello-*`:
`vocello-ios-validation`, `vocello-macos-ui`, `vocello-device-diagnostics`, `vocello-benchmark`,
`vocello-debug` and read-only `vocello-release-readiness`. They may also be selected for authorized local
work; they grant no external-write authority. Read-only agents live in `.claude/agents`:
`vocello-swift-review` and `vocello-xcresult-triage`, both `model: inherit`.

`.claude/settings.json` is the sole hook and permission definition. Opening a session installs nothing
and never builds or touches a phone.

| Event | Tool/event matcher | Handler | Effect |
| --- | --- | --- | --- |
| SessionStart | startup/resume/clear/compact/fork | worker_lifecycle.py, session_start.sh | Session receipt and exported marker; bounded local Git/status/checkpoint context |
| PreToolUse | Bash | commit_lint.sh, policy_guard.sh, agent_guard.py | Checkout-aware Git, whitespace, privacy, cache, generated-project and physical-device safeguards; subagent limits |
| PreToolUse | Edit, Write, MultiEdit, NotebookEdit | generated_file_guard.sh, agent_guard.py | Refuses hand edits of generated and frozen files, naming the generator; subagents never edit the roadmap or checkpoint |
| PreToolUse | MCP tools (`^mcp__`) | simulator_tool_guard.py | Refuses unsupported-destination tool routes |
| PostToolUse | Edit, Write, MultiEdit, NotebookEdit | project_yml_reminder.sh | Reminds to check the shared generation signature after project/source membership edits |
| SubagentStart / SubagentStop / SessionEnd | all | worker_lifecycle.py | Active-worker registration with agent rules, completion and conservative teardown |

Hook commands resolve through `$CLAUDE_PROJECT_DIR`, so they never depend on the working directory and
always run the main checkout's copy, while the guards judge each tool action by the payload `cwd`, which
follows an agent worktree. Bash payloads carry `tool_input.command`; file tools carry
`tool_input.file_path` (`notebook_path` for NotebookEdit). Any other tool, including the retired Codex
patch tool, fails closed in the file guard. Tokenized Git parsing handles global options, literal `-C`,
chains, subshells and heredocs. These cooperative guards cannot sandbox interpreter indirection or
arbitrary external programs.

The same file holds the permissions, mirroring the policy rather than replacing review. `allow` covers
the routine loop: read-only Git, scoped staging and commits, worktree integration, `scripts/dev.sh`,
contract and privacy scripts, the website check and the local `macos_test.sh`, `ui_test.sh` and
`ios_device.sh` lanes. It also covers read-only Hugging Face queries: the `hf` CLI's `version`,
`auth whoami`, `models` and `datasets` card/info/list, `papers`, and `cache` list/verify, plus the
`hf-mcp-server` read tools (`hf_fs`, `hub_repo_search`, `hub_repo_details`, `hf_whoami`). No rule
allows pytest by itself: run it through `scripts/dev.sh py` or
`"$(python3 scripts/select_python.py)" -m pytest`.

`ask` covers pushes, destructive Git, model installs and downloads, cache cleanup, pinned-tool
installation, benchmark publication, workflow dispatch, installers, global settings and external writes.
External writes include GitHub, the Vercel CLI and App Store Connect. On Hugging Face they include
`hf download`/`upload`, `repos`, `cp`/`sync`/`buckets`, `jobs`/`sandbox`/`endpoints`, `spaces`,
`collections`, `discussions`, `webhooks`, CLI `extensions`/`skills`/`update`, `auth login`/`logout`/
`switch` and cache removal, and the MCP's Space-running tools (`dynamic_space`, `gr*`).

`deny` covers force and non-main pushes, hand-made branches and worktrees, `update-ref`, stashing,
broad staging, releases, `.xcodeproj` edits and `hf auth token`, which prints the stored credential. It
also covers unsupported-destination and UI-driving MCP tools (by wildcard, so no literal tool name
enters the tree) and the Axiom simulator/test agents. Ask rules still prompt in auto mode and deny
wins in every mode. Rules merge with the untracked `.claude/settings.local.json`, which holds personal
overrides and cannot lift a tracked deny.

Claude Code applies edits to the tracked settings to the running session immediately, so change them
deliberately and in the same commit as their tests. `/hooks` and `/permissions` show what is active. Do
not self-approve trust prompts or modify global settings to make a check pass; report inactive or
unverified hooks. `scripts/dev.sh doctor --json` inventories configuration, tools and Axiom helpers; it
cannot establish MCP availability or hook activation.

Safeguards are also callable without activation:

```sh
scripts/hooks/commit_lint.sh --staged
git diff --check
python3 scripts/privacy_scan.py --changes
scripts/repo_invariants.sh
python3 scripts/build_output_policy.py validate
scripts/dev.sh py scripts/tests/test_agent_hooks.py scripts/tests/test_active_workers.py
```

`policy_guard.sh` and `generated_file_guard.sh` can read a fixture hook JSON on stdin; their tests
exercise allowed and blocked operations without running destructive commands. CI classification,
Python consumer selection and reference scanners include `.claude/`, `CLAUDE.md` and the two rule
sources, and still route the retired `.codex/` and `.agents/` prefixes so a deletion runs the hook
tests; config-only edits exercise behavioral checks without triggering native builds.

For a fresh-session smoke check, start a new `claude` session at the repository root. Confirm the
SessionStart output ("CLAUDE.md: Start here"), `/memory` (CLAUDE.md and no AGENTS.md), `/hooks` (the
project hooks), `/permissions` (no invalid rules), a non-empty `QVOICE_WORKER_SESSION` and
`python3 scripts/active_workers.py status` reporting `trackingAvailable: true`, a trivial subagent moving
`activeWorkers` to 1 and back, harmless guard fixtures refused (`git switch -c smoke`, an Edit of a
generated file), no unsupported-destination MobileBuildMCP tools offered, a rule loading when a matching
file is read, and the six skills and two agents listed. Record the client version and anything
unavailable. Without restarting the interactive session (for example when working remotely), a headless
`claude -p '<prompt>' --model haiku --max-turns 4 --allowedTools 'Bash(echo *)'
'Bash(python3 scripts/active_workers.py status)' --output-format stream-json --verbose < /dev/null`
from the repository root exercises the same SessionStart and SessionEnd hooks in a fresh session; its
init message lists the tools, agents and skills it received. The 2026-10-12 migration session already observed settings applying live, the wildcard
deny rules removing those MCP tools and the three Axiom simulator/test agents, the tooling rule loading
through its symlink, and a denied `git add -A` being refused; SessionStart, worker receipts and
SubagentStart/Stop still need the fresh-session check.

| Work | Authoritative route | Optional assistance |
| --- | --- | --- |
| Builds/tests/native UI | Repository scripts, owned caches and XCUITest | MobileBuildMCP discovery and coverage reads; no alternative native UI driver |
| Apple architecture/APIs | Source, Apple primary docs and retained artifacts | Axiom skills and read-only auditor agents; sosumi; Xcode's bundled documentation |
| Libraries | Pinned versions in `config/toolchain.json` and package manifests | Context7 |
| MLX runtime | Owned facade, exact pins and mlx-guide.md | Installed swift-mlx / swift-mlx-lm skills |
| Code review | The actual diff and the reference rules | vocello-swift-review; `/code-review`; `/security-review` for hooks, security, persistence and release |
| Finished native run | `scripts/dev.sh triage <run-directory> --json` and testing-runbook.md | Read-only vocello-xcresult-triage agent, xcresulttool, LLDB when indicated |
| Build/crash/trace diagnosis | Raw logs, crash reports, existing traces | Verified Axiom axbuild, xcsym and xcprof helpers and the crash-analyzer agent, with script-only fallback |
| Website | `npm --prefix website run check` | Claude in Chrome or chrome-devtools for local rendered inspection; Vercel deploys from Git (no Vercel plugin; the `vercel` CLI asks) |
| Repository/CI | Exact-commit checks and repository release scripts | GitHub connector or gh reads; `gh run watch` in the background after an authorized push |
| App Store/deployment/publication | Explicitly requested release workflow | The `asc` plugin skills over the Homebrew `asc` CLI, and the `vercel` CLI; reads do not authorize writes |
| Model research | Receipts, exact pins and maintenance contracts | The `hf` CLI and the `hf-mcp-server` MCP for hub search, cards, file sizes, licenses and papers; downloads, Space runs and Jobs need a specific request; no implied repin |
| Audio quality | `scripts/qc.py`, labels and the maintainer's ear (`docs/reference/qc.md`) | Hugging Face discovery for candidate models; rendered evidence images. Claude cannot hear audio and never issues listening verdicts |
| Code navigation | Source, tests and the reference rules | swift-lsp (clangd-lsp for C) through the LSP tool when a symbol server is configured (development-setup.md) |
| Claude Code configuration | Tracked `.claude/`, `CLAUDE.md` and `scripts/tests/test_agent_hooks.py` | skill-creator for project skills; claude-md-management for `CLAUDE.md` upkeep; `/update-config` for settings |

Detect capabilities in the current session rather than assuming installation means connection.
MobileBuildMCP (the renamed XcodeBuildMCP) reads only `.mobilebuildmcp/config.yaml`, which enables its
project-discovery and coverage workflows. Its macOS and device workflows are build, install, launch and
test tools that bypass repository serialization and the evidence scripts, and its debugging workflow
attaches only to the Simulator, so all three stay off; the unsupported-destination tools are also
denied in the permissions. Never persist session defaults (`persist: true` writes the tracked file). If
a diagnosis ever needs an MCP build, enable it deliberately and hold the native lock for the whole
operation. Never run it alongside another
native action/evidence lane. Optional helpers must exist, be executable and pass a non-mutating
help/version probe from their installed Axiom location
(`~/.claude/plugins/cache/axiom-marketplace/axiom/<version>/bin`). Keep raw native logs, original exit
status, optimization flags and evidence manifests; compact helper output cannot replace their
contracts. Use xcsym for retained crash symbolication and xcprof for existing trace inspection. Do not
use xcui or the Axiom simulator-tester, test-runner and test-debugger agents (denied): their simulator
and rerun routes conflict with this project's physical-iPhone/XCUITest rules. Missing optional tools
never block the script workflow; personal plugins, skills, accounts and credentials are not CI
dependencies. Never install or change global configuration simply to satisfy a routing table.

### Host and release prerequisites

The development host may use a newer Xcode than the exact CI/release pin. `doctor` reports this
mismatch without changing the selected developer directory. CONV-21 retains the compiler
qualification boundary: local success does not establish pinned-compiler acceptance. Release
checks consume exact tools from `config/toolchain.json`; select the existing pinned-tool bin
directory when available and verify with `scripts/supply_chain_contract.py --installed release`.
An ambient newer `gh` is fine for ordinary read-only inspection but cannot qualify a pinned release.
Missing pinned tools require the existing authorized installation workflow before a release;
do not repin dependencies or change global settings to make the inventory green.

For macOS XCUITest, keep one stable interactive desktop session and avoid simultaneous UI work.
Check visible blocking dialogs and competing automation before starting, then leave the desktop
available until collection finishes. Report XCTest display/screenshot errors from retained evidence;
the earlier Unity modal and display-ID error do not establish a causal link. Do not automatically
close unrelated apps or modify display settings. Failed UI runs retain their original identities.
