---
status: active
owner: release-qa
reviewed: 2026-09-22
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
git push
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

`scripts/hooks/commit_lint.sh` (a Claude Code `PreToolUse` hook) requires branch `main` in the main
checkout or a `worktree-*` branch in an agent worktree, pushes only from `main`, a whitespace-clean
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
paths change and nightly; `darwin_only` runs inside the macOS gate. Every run prints its slowest
tests; a test that outgrows its lane moves, it does not slow every push. `pytest.ini` already passes
`-q`; adding another `-q` drops the summary line, so judge a run by pytest's exit code.

## CI

| Job | Runner | Runs when | Warm / cold |
| --- | --- | --- | --- |
| `changes` | ubuntu | always | seconds |
| `contracts` | ubuntu | always | about 1 min: the action-pin check (`supply_chain_contract.py`) first, then the complete deterministic contract gate (`check_project_inputs.sh --python none`: product contracts, invariants, privacy scan, work authority, benchmark history) |
| `python` | ubuntu | Python paths, contracts, workflow files | 3 to 4 min: product and tooling tests; research tests when routed |
| `macos-tests` | macos-26 | never on a pull request; Swift compile inputs, the lane's own scripts, build configs and benchmark evidence; also macOS XCUITest sources (`macos_ui`), which run only the bundle compile | cached DerivedData; darwin-only Python modules, macOS bundles, CLI identity (`-Onone`, same settings as the bundles, about 30 s), then `build_ui_test_bundles.sh macos --gate` compiles the macOS XCUITest bundle in the same arena (build only) |
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
splits it into `-m "not research and not darwin_only"` plus an optional `-m research` on Linux and
`-m darwin_only` in the macOS job.

Only push CI's own inputs (`.github/workflows/ci.yml`, `.github/actions/**`,
`scripts/ci/classify_changes.py`) force the three native lanes; the other workflow files route to
the Python lane, whose supply-chain tests check their pins. A lane skipped inside a green run
advances that lane's base, so a rarely-run lane never drags the others back. Caches are keyed
`<platform>-xcode<version>-<dependency graph>-<ISO week>` and saved only on an exact miss, so the
first run of each week (or of a new dependency graph) pays one save and the store holds at most a
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

## What never runs from here

XCUITest, model downloads, generated audio, benchmarks, signing, notarization, App Store work and
releases run only when the task explicitly asks for that evidence, through their canonical scripts.

## Claude Code development workflow

Claude Code is the development agent; `CLAUDE.md` owns the working agreement and `.claude/rules/`
holds the path-scoped domain rules. The lead session works on the existing local `main` checkout and
may delegate to parallel agents as described below. Before editing, record HEAD, dirty files and the
relevant roadmap item or user assignment. Preserve unrelated work; reconcile an unexpected change
before editing or staging overlapping files. Implement, run affected checks, review the diff, commit
only the assignment (explicit paths) and push. Report the behavior change, checks and limitations,
commit/CI evidence and next action. Update the existing checkpoint or roadmap only when status
changes; no transcripts or second work ledger.

Keep the loop small: focused tests while editing, one routed check before completion (`--since
origin/main` for a batch of landed commits), broader checks only for new changes or unresolved
failures. `check --paths <assigned paths...>` scopes the outer
build/lint plan when unrelated work is paused; its contract gate still selects Python tests from the
actual dirty tooling. A skipped CI lane is not a new test run. Do not add validators for prose,
plugin inventories, or tool availability. Existing product and release gates remain authoritative.

## Parallel agents and worktrees

The development Mac is a Mac mini M6 with 16 GB of memory and 12 cores. Parallel agents are allowed
when they save wall-clock time without contending for memory or files.

**Read-only agents** keep large reads out of the lead's context and may run alongside anything: the
built-in Explore and Plan agents, `xcresult-triage` for a finished UI run, `swift-review` for a Swift
diff, and the Axiom auditor subagents (concurrency, memory, SwiftUI performance, build, test failure,
crash, security/privacy, accessibility). They never edit, stage, commit, push or start native,
device, UI, model or benchmark work.

**Editing agents** are general-purpose agents started with `isolation: "worktree"` (or a session in
`EnterWorktree` / `claude --worktree <name>`). Claude Code creates `.claude/worktrees/<name>` on branch
`worktree-<name>` from local `HEAD` (`worktree.baseRef: head`), so commit the lead's pending work
first. One task per agent, with a file set that does not overlap another agent's. Inside its worktree
an agent may edit, commit on its branch (the commit lint runs there), run targeted
`python3 -m pytest`, `scripts/dev.sh py|contracts|lint|check --dry-run` and
`python3 scripts/roadmap.py validate`, and run `npm --prefix website run check` after
`npm --prefix website ci` in that worktree. **Agents do not build natively by default.** A worktree
starts with an empty `build/`, so its first native command is a cold MLX compile for each platform
(about 9 GB and many minutes), serialized behind every other build; on one Mac that erases the gain
from parallel authoring. Agents author code and tests, run only non-native checks, and hand back a
commit; the lead verifies natively once on the warm `main` cache (below). Native commands in a
worktree are an explicit exception for work that cannot be written without compiler feedback (for
example a long debugging loop); they belong in a background task. Agents never push, touch `main`,
run consent-bound lanes or XcodeBuildMCP builds (which bypass the lock), regenerate shared generated
artifacts, or edit `config/roadmap.json` and `docs/development-progress.md`; the lead owns those.

**Agent brief.** Every editing-agent prompt carries the task's roadmap entry and design, the files it
owns, and the checklist that `swift-review` otherwise finds after the fact: Mac-only value types live
in `Sources/Services` and are listed by path under `VocelloCoreTests`; logic in an app-only
`@MainActor` type is extracted into a tested value type (`Sources/iOSSupport/Services`, listed under
both test targets); new persistent directories are registered in the iOS storage-protection policy;
user-facing copy goes through the typed catalog; engine state stays actor-owned; new files under
globbed paths mean `./scripts/regenerate_project.sh --fast`.

**Integration** happens in the lead session, in the main checkout on `main`: review
`git log main..worktree-<name>` and the diff, then `git merge --ff-only worktree-<name>` (or
`git cherry-pick <sha>...` when `main` moved; no merge commits without a stated reason), verify on
the warm cache — `scripts/dev.sh build` and `scripts/dev.sh test --only <the agent's test classes>`,
`scripts/dev.sh ios` when shared or iOS sources changed — while `swift-review` reads the same diff in
parallel; fix small compile or review findings directly, send larger ones back to the agent. After
the batch, run one `scripts/dev.sh check --since origin/main` (it routes on everything the unpushed
commits changed plus the dirty tree, including the gate's Python selection) and push once.

**Cleanup:** `git worktree remove .claude/worktrees/<name>`, then `git branch -d worktree-<name>`
for a fast-forwarded branch or `git branch -D` (asks first) for a cherry-picked one, which is not an
ancestor of `main`. Claude Code locks a worktree while its agent runs, and again while a resumed
agent works; if removal reports a lock, `git worktree unlock .claude/worktrees/<name>` first.
Discarding unintegrated work (`git branch -D`, `git worktree remove --force`) asks first. The
SessionStart banner lists open worktrees until they are integrated or removed.

**Budget on 16 GB.** One native build or test at a time (the host lock enforces it). At most three
editing agents plus the lead, at most four read-only subagents, and at most five active agents in
total, including agents inside an opted-in Workflow script. One full `pytest -n auto` and one
Playwright website check at a time; parallel agents use module-targeted pytest. While a native build
holds the lock, keep other work light.

**When parallelism fits:** independent roadmap items with disjoint files, research, review, audits and
triage, and non-native checks next to a native build. **When it does not:** small or single-file
changes, overlapping files or shared generated inputs (`project.yml`, `Package.resolved`,
`config/roadmap.json`, the model catalog, inventories), native-heavy work, and anything that feeds an
evidence lane.

**Evidence lanes run alone.** Device, UI, model, memory, benchmark and release lanes run in the lead
session only, on explicit request, one at a time, with no agent worktree active, no other holder of
the native lock and no edits or integration during the run. `require_quiet_host` refuses to start
while another process holds the native lock or an agent worktree is locked
(`QVOICE_ALLOW_BUSY_HOST=1` records the reason and continues for an exploratory run).

## Claude Code setup and tool routing

`.claude/settings.json` is the tracked project configuration; opening a session never installs
tools, builds, probes a phone or starts an app.

| Hook | Matcher | Script | Effect |
| --- | --- | --- | --- |
| `SessionStart` | `startup\|resume\|clear\|compact` | `session_start.sh` | Bounded local Git, open agent worktrees, `dev.sh status` and "Resume now" context |
| `PreToolUse` | `^Bash$` | `commit_lint.sh` | In the checkout the command acts on: commits (including `git -c`/`-C` forms) need `main` in the main checkout or `worktree-*` in `.claude/worktrees/<name>`; pushes only from `main`; clean staged whitespace and a clean staged privacy scan |
| `PreToolUse` | `^Bash$` | `policy_guard.sh` | Blocks Simulator routes, whole-cache deletion, force pushes, pushes of any ref but `main`, hand-made branches/worktrees, `update-ref` and `project.pbxproj` writes; heredoc bodies are data |
| `PreToolUse` | `^(Edit\|Write\|MultiEdit\|NotebookEdit)$` | `generated_file_guard.sh` | Refuses hand edits of generated or frozen files, also inside agent worktrees, and names the generator |
| `PostToolUse` | `^(Edit\|Write\|MultiEdit)$` | `project_yml_reminder.sh` | Reminds to run `./scripts/regenerate_project.sh --fast` after a root or worktree `project.yml` edit |

`scripts/hooks/agent_hook_input.py` normalizes Claude Code hook input: Bash text from
`tool_input.command`, edit targets from `tool_input.file_path` (`notebook_path` for NotebookEdit),
resolved against the payload's `cwd`. `scripts/hooks/git_commands.py` tokenizes git commands for the
two Bash guards: every invocation (after wrappers such as `timeout` or `xargs`, inside `bash -c`,
shell heredocs and command substitutions, with abbreviated long options) and the checkout each `git
commit`/`git push` acts on (payload `cwd`, `cd`, subshells, `git -C`); a target it cannot resolve,
or one an earlier `git checkout`/`switch`/`rebase` in the same command may move, fails closed. It is
a guardrail for cooperative agents, not a sandbox: interpreter indirection (`python3 -c`, piped
shells) and hand-written `.git` files stay out of reach, and GitHub's branch protection remains the
backstop. Unreadable input, a missing path or an unexpected tool fails closed for the file guards.
Hooks resolve through `$CLAUDE_PROJECT_DIR`, which stays on the main checkout while the payload
`cwd` follows an agent into its worktree. `scripts/tests/test_agent_hooks.py` pins the exact
matcher-to-script matrix, the guard behavior, the skill and subagent metadata and the rule path
scopes; changes under `.claude/` select it locally and in CI.

Permissions encode the same boundaries. `allow` covers the routine loop: Git inspection,
explicit-path staging, commits and fast-forward pushes to `main` (the maintainer's standing
authorization; the commit lint still runs), worktree integration (`git merge --ff-only worktree-*`,
`git cherry-pick`, `git branch -d worktree-*`, `git worktree list|prune|unlock|remove
.claude/worktrees/*`), `scripts/dev.sh`, the contract gate, pytest, the roadmap, `gh run` and the
deterministic native lanes. `ask` covers the consent-bound lanes (`scripts/ui_test.sh`,
`scripts/ios_device.sh`, the `scripts/macos_test.sh` model, memory, benchmark and release-readiness
lanes, model installs), cache cleanup, workflow dispatch, destructive Git resets, discarding agent
work (`git branch -D`, `git worktree remove --force`) and the XcodeBuildMCP device and test tools.
`deny` covers force pushes, pushes of any ref but `main`, hand-made branches and worktrees,
`update-ref`, stashing, broad staging, whole-cache deletion, releases, the XcodeBuildMCP Simulator
tools and `.xcodeproj` edits. Agent worktrees (`EnterWorktree`, `Agent` with `isolation:
"worktree"`) are allowed. Hooks and permissions are guardrails, not a sandbox or proof of
authorization; programs and tools outside their coverage still follow `CLAUDE.md`. Personal
overrides belong in the ignored `.claude/settings.local.json`, where deny rules from the tracked
file still win.

After changing instructions, rules, skills or hooks, check a fresh session: the SessionStart banner
names `CLAUDE.md`, `/memory` lists `CLAUDE.md`, `/hooks` shows the five hooks, `/permissions` shows
the three lists, the four repository skills appear in the `/` menu (among any user-scope plugin
skills), and a harmless blocked fixture (an Edit of `docs/ROADMAP.md`) is refused. For the worktree
rules, start one isolated agent on a one-line docs change: its commit on `worktree-*` passes, its push
is refused, and the lead integrates it with `git merge --ff-only` and removes the worktree. Report
runtime activation as unverified until then. Never try a real destructive command as a hook test.

| Work | Authoritative route | Relevant optional assistance |
| --- | --- | --- |
| Native build/test/UI evidence | Repository scripts, owned caches and XCUITest | XcodeBuildMCP discovery, scratch builds and device debugging with the `macos`/`ios-device` profiles (its Simulator tools are denied); swift-lsp through `buildServer.json`; no alternative native UI driver |
| Apple code and diagnostics | Source, Apple documentation and test artifacts | Axiom skills (for example `axiom:axiom-tools`, `axiom:axiom-concurrency`) and auditor subagents (`axiom:concurrency-auditor`, `axiom:memory-auditor`, `axiom:swiftui-performance-analyzer`, `axiom:build-fixer`, `axiom:test-failure-analyzer`, `axiom:crash-analyzer`, `axiom:security-privacy-scanner`, `axiom:accessibility-auditor`), Apple documentation (sosumi), `swift-review`; select the relevant specialty only |
| MLX runtime | `Packages/VocelloQwen3Core`, [MLX guide](mlx-guide.md) and exact pins | `mlx-swift` and `mlx-swift-lm` skills; no implied dependency move |
| Finished UI runs | [Testing runbook](testing-runbook.md#read-a-finished-run) | `xcresult-triage` subagent |
| Website | `npm --prefix website run check` with Playwright | Claude in Chrome or chrome-devtools for visual/interactive checks; Impeccable and relevant Vercel/library guidance under `website/CLAUDE.md` |
| CI and release evidence | Exact-commit GitHub checks and repository release scripts | `gh`, the GitHub connector (claude.ai, no personal token) and Monitor for long runs; release tools require explicit publication authority |
| App Store Connect | The web portal and the release workflow's `xcodebuild`/`altool` steps | asc-* skills (they drive the tddworks `asc` CLI); reads freely, writes such as uploads, submissions or metadata edits only on explicit request |
| Model/dependency research | Receipts, exact pins and maintenance contracts | Hugging Face tools read-only and Context7 for library docs; no implied download or pin-change permission |

Use tools callable in the current session, with script/primary-documentation fallbacks. The
install commands for the optional plugins and MCP servers are in
[development setup](development-setup.md#8-claude-code). Do not install plugins, duplicate servers
or change global settings just to satisfy this table. Personal
plugins, accounts and skill caches are not CI dependencies. Generic plugin advice never overrides
physical-iPhone-only, script-owned native UI, cache ownership or consent requirements.

Four explicit skills live under `.claude/skills`: `/ios-lane`, `/macos-ui-lane`,
`/device-diagnostics` and `/release-evidence`. `disable-model-invocation: true` keeps them
user-invoked; invoking one is the explicit request for that lane. Their `allowed-tools` cover only the
lane's own script and read-only triage; they call existing scripts, not a second execution engine.
No installed specialist skill or MCP server is mandatory.

The toolchain audit is `python3 scripts/supply_chain_contract.py --installed all`; choose `native`,
`website` or `release` for focused audits. Report local compatibility separately from pinned CI and
release readiness. Keep pins/global installations unchanged unless assigned; release CLI drift does
not block ordinary development. For compiler-cache or loopback permission failures, preserve the
failed attempt and request the narrow access the existing command needs.
