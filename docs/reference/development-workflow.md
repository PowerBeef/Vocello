---
status: active
owner: release-qa
reviewed: 2026-10-20
summary: Setting up a new Mac, the local edit loop, the commit lint and how push CI routes lanes; scripts/dev.sh is the interface and CI on main is the gate.
sourceOfTruth:
  - scripts/dev.sh
  - scripts/development_workflow.py
  - scripts/ci/classify_changes.py
  - .github/workflows/ci.yml
  - config/toolchain.json
  - scripts/install_pinned_tools.sh
  - scripts/lib/ios_platform_preflight.py
  - scripts/supply_chain_contract.py
---
# Development workflow

Local verification is fast and advisory; CI on `main` is the gate. Nothing blocks a commit except a
15-second lint.

## New Mac setup

A fresh clone contains the whole project: source, the tracked Xcode project and schemes, contracts,
scripts, CI, `CLAUDE.md` and the Claude Code configuration. What it cannot contain is the machine:
Xcode and its downloadable components, command-line tools, Python and Node toolchains, credentials,
signing identities, privacy grants, downloaded models and caches. This guide sets those up in order.
Versions are never repeated here; `config/toolchain.json` is the pin authority and the commands below
read it.

```sh
git clone https://github.com/PowerBeef/Vocello.git
cd Vocello
```

### 1. Xcode and its components

- An Apple Silicon Mac on macOS 26 or newer with **full Xcode**; the Command Line Tools alone cannot
  build any product. CI pins the version in `config/toolchain.json` (`native.xcode`). A newer local
  Xcode (27) builds the project, but it accepts some code the pinned CI Xcode rejects, so push CI stays
  the judge; the toolchain move is roadmap item CONV-21.
- Select it and finish its first launch:

  ```sh
  sudo xcode-select -s /Applications/Xcode.app/Contents/Developer
  xcodebuild -runFirstLaunch
  ```

- MLX compiles Metal shaders. Xcode 27 ships the Metal toolchain as a separate one-time download:
  `xcodebuild -downloadComponent MetalToolchain`.
- The phone-free iOS compile (`scripts/dev.sh ios`) needs the iOS platform component:
  `xcodebuild -downloadPlatform iOS -architectureVariant arm64`, then
  `python3 scripts/lib/ios_platform_preflight.py check`. The repository never downloads it for you
  and never uses it to run a Simulator.

### 2. Command-line tools (Homebrew plus the pinned installer)

Homebrew supplies the general tools; the four tools whose exact version matters to the build come
from the repository's SHA-pinned installer instead:

```sh
brew install gh python node@24
./scripts/install_pinned_tools.sh
./scripts/install_pinned_tools.sh swiftlint ruff   # optional: the local lints CI gates
cat >> ~/.zprofile <<'EOF'
export PATH="$HOME/.qwenvoice-pinned-tools/bin:/opt/homebrew/opt/node@24/bin:$PATH"
EOF
exec zsh -l        # reload PATH, then check: which xcodegen rg python3 node
gh auth login
```

`./scripts/install_pinned_tools.sh` downloads xcodegen, ripgrep, xcbeautify and shellcheck from the
release artifacts pinned in `config/toolchain.json`, verifies each SHA-256 and installs them into
`~/.qwenvoice-pinned-tools/bin`; CI runs the same script, and naming other pinned tools (such as `gh`)
installs those instead. Keep that directory first on `PATH` so a Homebrew copy never shadows it:
xcodegen's version decides the bytes of the generated Xcode project. xcodegen is needed on the very
first build even if you never edit `project.yml`, because the build scripts regenerate the project
whenever their generation stamp under `build/` is missing; `rg` is required by
`scripts/repo_invariants.sh` and the contract gate. `node@24` is keg-only, hence its `PATH` entry.
SwiftLint and ruff are optional locally and pinned the same way (installed only when named):
`scripts/dev.sh lint` runs SwiftLint on changed files and reports it missing or not the pinned
version, and `python3 scripts/lint_baseline.py <shellcheck|ruff|swiftlint|pyright>` runs the gate CI's
`contracts` job runs against `config/lint-baseline/`. `gh` is the CI and release interface (`gh run watch`).

### 3. Python

The tooling needs Python 3.11 or newer as `python3`, ahead of Apple's `/usr/bin/python3` on `PATH`;
Homebrew's `python` provides it (`which python3` should print `/opt/homebrew/bin/python3`). The test
suite also needs numpy, pytest and pytest-xdist at the pinned versions; this reads them from the
manifest exactly as CI does:

```sh
python3 -m pip install --user --break-system-packages $(python3 -c 'import json; n = json.load(open("config/toolchain.json"))["native"]; print(" ".join(k + "==" + n[k]["version"] for k in ("numpy", "pytest", "pytest-xdist")))')
```

Homebrew marks its Python as externally managed; `--user` installs the pins into your user
site-packages without touching Homebrew's files (CI passes the same flag). The scripts always run
`python3 -m pytest`, so the user `bin` directory does not need to be on `PATH`. After a Homebrew Python
upgrade to a new minor version, run the command again. Audio QC models run in their own pinned
venvs under `build/cache/qc/runtimes/`, never in this interpreter; see [`qc.md`](qc.md).

### 4. Website

```sh
npm --prefix website ci
npx --prefix website playwright install chromium webkit
npm --prefix website run check
```

Node and npm pin only their major version (`config/toolchain.json` `website.node` 24, `website.npm`
11): CI's `setup-node` takes the latest 24.x with its bundled npm, and Homebrew's `node@24` follows the
same line, so `scripts/dev.sh ci` and `supply_chain_contract.py --installed website` pass on it. The
dependencies themselves stay exact through `website/package-lock.json`. Vercel deploys through its Git
integration; `vercel link --repo` is needed only to use the Vercel CLI.

### 5. Git

Set a global identity (`git config --global user.name …` and `user.email …`) and do not add a
repository-local override. HTTPS credentials come from `gh auth login` or the macOS keychain. There
are no Git hooks, submodules or LFS files; the guards are supplementary Claude Code hooks. Release tags must be
signed and GitHub-verified (`git tag -s`), so configure a signing key only if you cut releases
([`macos-release-qa.md`](macos-release-qa.md)).

### 6. First run

```sh
scripts/dev.sh status
python3 scripts/supply_chain_contract.py --installed native     # a newer local Xcode shows as drift; expected
python3 scripts/supply_chain_contract.py --installed website    # any Node 24.x / npm 11.x passes
scripts/dev.sh check                                            # first run: regenerate, resolve packages, cold build
scripts/dev.sh build && scripts/dev.sh run
```

The first `check` resolves the Swift packages over the network and compiles everything cold, which
takes a while; later runs reuse the owned caches under `build/` ([`config/build-output-policy.json`](../../config/build-output-policy.json)).
Never copy `build/` from another machine; rebuild it.

### 7. Signing, permissions, models and devices

- **Signing.** Local macOS builds sign with the first Apple Development identity in the keychain and
  fall back to ad-hoc with a warning (ad-hoc grants for microphone and speech reset on every rebuild).
  Sign in under Xcode → Settings → Accounts, or import the old Mac's certificate together with its
  private key. Release signing lives only in CI secrets.
- **Permissions.** Run `scripts/permissions_doctor.sh` and follow
  [`macos-app-guide.md` §7](macos-app-guide.md#7-macos-permissions-tcc): the UI-test runner's System Audio Recording and
  Accessibility grants are added by hand in System Settings, and reading the privacy database needs
  Full Disk Access for the terminal. macOS UI lanes also need Automation Mode without a password
  prompt: run `sudo automationmodetool enable-automationmode-without-authentication` once, and keep
  the session unlocked while a lane runs.
- **Models.** The apps download the production catalog on first use into
  `~/Library/Application Support/QwenVoice`. Test fixtures come from `scripts/macos_test.sh models
  ensure` on explicit request; copying that folder from the old Mac also works.
- **iPhone.** Device lanes need an Apple Development identity with its key, an iPhone paired with and
  trusting this Mac, and Developer Mode enabled on the phone ([`ios-device-testing.md`](ios-device-testing.md)).
  Pair once over USB; afterwards CoreDevice reaches the unlocked phone over the local network
  (`scripts/ios_device.sh device-state`). With the Apple ID signed in under Xcode → Settings →
  Accounts, the first `scripts/ios_device.sh build` creates the team development provisioning profile.

### 8. Claude Code

Open the clone with `claude` at the repository root and trust the workspace; Claude Code reads
`CLAUDE.md`. The tracked `.claude/settings.json` holds the supplementary hooks, permissions and
`worktree.baseRef`; skills live in `.claude/skills`, read-only agents in `.claude/agents` and the
path-scoped rules in `.claude/rules`. Check `/hooks` and `/permissions` in the first session and follow
the [fresh-session procedure](development-workflow.md#claude-code-setup-and-tool-routing).
Personal overrides go in the untracked `.claude/settings.local.json`; do not change global trust or
settings automatically. Agent worktrees under `.claude/worktrees` stay untracked. The Claude desktop
app's Code tab runs the same Claude Code with the same hooks, permissions, skills and agents: open
the lead session on the repository folder itself, without a worktree
([The Claude desktop app](#the-claude-desktop-app)).

`scripts/dev.sh doctor --json` inventories prerequisites without installing anything, downloading
models or touching devices. Detect MCP tools in the live session.

The maintainer's toolset is optional assistance, never a CI dependency. As of 2026-10-24 it is:

- **Plugins:** axiom, context7, swift-lsp, clangd-lsp, chrome-devtools-mcp, skill-creator,
  claude-md-management and asc.
- **MCP servers:** MobileBuildMCP, sosumi and `hf-mcp-server`.
- **Skills:** the swift-mlx skills.
- **Desktop app:** the Claude desktop app's Code tab, with its browser pane, Terminal panel and
  computer use.
- **Browser and connectors:** Claude in Chrome and the claude.ai GitHub connector.
- **CLIs:** `hf`, `asc` and `gh`.

The Vercel, Hugging Face skills, Unity and playground plugins are uninstalled. Hugging Face work goes
through the `hf` CLI and `hf-mcp-server`. Use existing plugins when connected; no duplicate servers or
automatic global installs. Uninstall an unwanted plugin rather than disabling it in settings.
`.mobilebuildmcp/config.yaml` enables only MobileBuildMCP's project-discovery and coverage workflows,
with macOS and physical-device profiles for scheme and settings lookups; repository scripts own
canonical builds and host serialization. Native UI evidence comes only from XCUITest.

For a symbol server, `buildServer.json` is ignored because it holds machine paths. The swift-lsp
plugin's sourcekit-lsp reads it for the LSP tool. When explicitly setting up an installed
xcode-build-server, its config can target the warm `build/cache/xcode/macos` arena. Optional setup never replaces pinned repository tools or authorizes installation/repinning.

### Troubleshooting

- A build that fails on missing Xcode stat caches right after a disk cleanup means `build/cache` was
  deleted: rebuild with `scripts/dev.sh ci` or the individual lanes. The LSP stays broken until the
  `build/cache/xcode/macos` arena is rebuilt.
- `xcodegen` not found: the pinned tools directory is not on `PATH` (section 2).
- The iOS compile refuses to start: the iOS platform component is missing or does not match the
  selected Xcode (section 1).

## Daily loop

```sh
scripts/dev.sh check --dry-run       # what the dirty tree needs
scripts/dev.sh check                 # lint, contracts, selected Python tests, native lanes touched
scripts/dev.sh check --since origin/main  # the same over an unpushed batch of commits
scripts/dev.sh test --only FooTests  # one XCTest class on the incremental test build
scripts/dev.sh test --only FooTests --repeat 50  # flaky hunting: up to 50 runs, stops at the first failure
scripts/dev.sh py                    # Python consumers of the changed tooling (--all, --lane, or modules)
scripts/dev.sh contracts             # the contract gate alone (check_project_inputs.sh --local)
scripts/dev.sh ios                   # generic device-SDK compile (incremental, no phone)
scripts/dev.sh regen                 # regenerate roadmap render, catalog, inventories, charts, attributions
scripts/dev.sh ci                    # every gate push CI runs, serially, when you want the push green first time
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
rules uses SourceKit). Pyright follows in `pyrightconfig.json`'s basic mode over the tracked
`scripts/` Python, at the npm version in `npmPins`, against a fresh interpreter with no packages so
its findings never depend on the host; its import-resolution rules are therefore not judged. Only a
finding absent from `config/lint-baseline/<tool>.json` fails; the
SwiftLint baseline was empty when its gate began (DW-03), so any finding of its rules fails. A
finding is keyed by file, rule and the text of its line, not its line number, so editing a line that
carries a baselined finding makes it new: fix it then. The baselines only shrink: `python3
scripts/lint_baseline.py shellcheck|ruff|swiftlint|pyright` reproduces the gate locally and names entries
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
| `contracts` | ubuntu | always | about 1 min: the action-pin check (`supply_chain_contract.py`) first, then the complete deterministic contract gate (`check_project_inputs.sh --python none`: product contracts, invariants, privacy scan, work authority, benchmark history), then the shellcheck, ruff, SwiftLint and Pyright gates, each failing on findings absent from `config/lint-baseline/` (`scripts/lint_baseline.py`) |
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
job runs it with `--python none`), the four `lint_baseline.py` gates, `scripts/macos_test.sh test`, `scripts/macos_test.sh tsan`, the
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
(`scripts/ci/failure_issue.py`). Its report-only jobs file no issue and gate nothing: `coverage`,
`migration-warnings`, `shipped-config` (`scripts/macos_test.sh test --shipped-config`: owned code
`-O` whole-module, the runtime package in release with TF32 on) and `dead-code`, where
`scripts/dead_code_report.sh` compiles the macOS app,
the CLI and the iOS app into one scratch root with the index store kept (`QVOICE_INDEX_STORE=1`),
runs the pinned Periphery over all three schemes and keeps owned code only, and
`scripts/ci/periphery_report.py` summarizes the findings. `release-rehearsal.yml` runs weekly, on
dispatch and on pushes that touch release inputs: without secrets it installs the release toolchain
through `.github/actions/native-toolchain`, runs the ledgered `release.sh` (ad-hoc signed, not notarized)
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
active including the lead, inheriting the selected model; desktop app side sessions count. This limit
is an instruction: a hook cap would misread a subagent that died without SubagentStop as still active
until its session ends.
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

The Claude desktop app adds side sessions: separate sessions the lead starts (`start_session`) or the
maintainer opens, each with its own transcript. They follow the agent rules, and the lead stays in the
main checkout. A read-only side session (CI or release watching, triage, research) shares the main
checkout (`use_worktree: false`), often on a cheaper model, and its brief says it edits nothing. An
editing side session gets the app's own worktree (`use_worktree: true`; omitted, a side session of a
lead in a plain folder shares that folder, where no guard can tell it from the lead),
`.claude/worktrees/<name>` on `claude/<name>` (the
Code tab's default branch prefix `claude` and in-project worktree location; keep both), cut from local
HEAD, so commit the checkpoint first. The SessionStart hook tells a session that starts in a linked
worktree that it is a side session, and `agent_guard.py` screens every call made from a linked
worktree as it screens a subagent's, `agent_id` or not; a lead that `cd`s into a worktree is screened
the same way until it leaves. The commit lint accepts the `claude/*` branch there. The lead integrates
it like an agent branch (`git cherry main claude/<name>`, then cherry-pick or `merge --ff-only`),
archives the session in the app and removes any worktree and branch left behind.

Before source-bound measurements join or stop all delegated work. `scripts/active_workers.py`
uses the SessionStart/SubagentStart/SubagentStop/SessionEnd hook events, host-wide leases and the live
start identity of the native `claude` process. Dead, reused-PID and non-Claude ownership records
(including retired Codex leases and Node-hosted clients) cannot establish activity.
Unknown ownership blocks measurements. A locked Git worktree may be idle and is never counted.
Another live session in this repository (a desktop side session, a second terminal) counts like a
worker: `active_workers.py check` reports `other-sessions(N)` and the lane waits until those sessions are
stopped or archived; `--agents-allowed` lanes tolerate them.
Root interruption/teardown does not prove workers stopped, so live worker leases remain conservative.

The SessionStart hook exports the session's opaque `QVOICE_WORKER_SESSION` marker to later Bash calls
through `CLAUDE_ENV_FILE` and names it in the session context; it establishes *this session's*
registration. Another session's receipt cannot establish it.
If hooks or ownership inventory are unavailable, join all known workers and explicitly use
`QVOICE_LEAD_ONLY=1` for the lane. Never use that declaration to bypass a known active or unknown
worker lease. Registration failures invalidate the session receipt and retain a conservative marker;
inspect unresolved markers after joining work rather than blindly deleting them. Without the marker no
session can be told from another, so the lead-only declaration also covers side sessions: stop or
archive them first. Hooks cannot prove
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
| SessionStart | startup/resume/clear/compact/fork | worker_lifecycle.py, session_start.sh | Session receipt and exported marker; the agent rules for a session started in a linked worktree; bounded local Git/status/checkpoint context |
| PreToolUse | Bash | commit_lint.sh, policy_guard.sh, agent_guard.py | Checkout-aware Git, whitespace, privacy, cache, generated-project and physical-device safeguards; subagent and side-session limits |
| PreToolUse | Edit, Write, MultiEdit, NotebookEdit | generated_file_guard.sh, agent_guard.py | Refuses hand edits of generated and frozen files, naming the generator; subagents and side sessions never edit the roadmap or checkpoint |
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
the routine loop: read-only Git, scoped staging and commits, worktree integration (`worktree-*` and
`claude/*` branches), `scripts/dev.sh`,
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
also covers unsupported-destination and UI-driving MCP tools (the simulator tools by wildcard, the
desktop app's iOS Simulator server, a dozen MobileBuildMCP UI tools by name) and the Axiom
simulator/test agents. Computer use is not denied (maintainer decision 2026-10-24); the app asks the
maintainer to approve each application it controls. Ask rules still prompt in auto mode and deny
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
through its symlink, and a denied `git add -A` being refused. SessionStart, worker receipts and
SubagentStart/Stop have since been observed in live sessions (a subagent receives the SubagentStart
context from `worker_lifecycle.py`). In the desktop app, run the same check in a new session opened on
the repository folder without a worktree, and confirm that `preview_start` with `website` serves the
home page and that no `mcp__Claude_Code_iOS_Simulator__*` tool is offered. The first desktop session
(2026-10-24) observed the SessionStart output, a non-empty marker, `trackingAvailable: true` with the
app's `claude` process as owner, and the `website` preview.

| Work | Authoritative route | Optional assistance |
| --- | --- | --- |
| Builds/tests/native UI | Repository scripts, owned caches and XCUITest | MobileBuildMCP discovery and coverage reads; computer use to explore, never for evidence ([The Claude desktop app](#the-claude-desktop-app)) |
| Apple architecture/APIs | Source, Apple primary docs and retained artifacts | Axiom skills and read-only auditor agents; sosumi; Xcode's bundled documentation |
| Libraries | Pinned versions in `config/toolchain.json` and package manifests | Context7 |
| MLX runtime | Owned facade, exact pins and mlx-guide.md | Installed swift-mlx / swift-mlx-lm skills |
| Code review | The actual diff and the reference rules | vocello-swift-review; `/code-review`; `/security-review` for hooks, security, persistence and release |
| Finished native run | `scripts/dev.sh triage <run-directory> --json` and testing-runbook.md | Read-only vocello-xcresult-triage agent, xcresulttool, LLDB when indicated |
| Build/crash/trace diagnosis | Raw logs, crash reports, existing traces | Verified Axiom axbuild, xcsym and xcprof helpers and the crash-analyzer agent, with script-only fallback |
| Website | `npm --prefix website run check` | The desktop app's browser pane (`.claude/launch.json`), Claude in Chrome or chrome-devtools for local rendered inspection; Vercel deploys from Git (no Vercel plugin; the `vercel` CLI asks) |
| Repository/CI | Exact-commit checks and repository release scripts | GitHub connector or gh reads; `gh run watch` in the background after an authorized push |
| App Store/deployment/publication | Explicitly requested release workflow | The `asc` plugin skills over the Homebrew `asc` CLI, and the `vercel` CLI; reads do not authorize writes |
| Model research | Receipts, exact pins and maintenance contracts | The `hf` CLI and the `hf-mcp-server` MCP for hub search, cards, file sizes, licenses and papers; downloads, Space runs and Jobs need a specific request; no implied repin |
| Audio quality | `scripts/qc.py` machine screens and report-only QC v2 (`docs/reference/qc.md`); nobody listens for 3.0 (maintainer decision 2026-10-13) | Hugging Face discovery for candidate models; rendered evidence images. Claude cannot hear audio and never issues listening verdicts |
| Code navigation | Source, tests and the reference rules | swift-lsp (clangd-lsp for C) through the LSP tool when a symbol server is configured (New Mac setup, above) |
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

### The Claude desktop app

The Code tab of the Claude desktop app is the maintainer's client since 2026-10-24. It runs the same
Claude Code and loads the same `CLAUDE.md`, hooks, permissions, skills and agents; its session process
is named `claude`, so worker tracking works unchanged. What it adds, and the rules for each:

- **Sessions.** The lead opens the repository folder without a worktree. Side sessions follow
  [Parallel agents and worktrees](#parallel-agents-and-worktrees). The task list, chapters, diff pane
  and next-step box belong to the app and change nothing in the repository's loop.
- **Browser pane.** `.claude/launch.json` defines `website` (the Vite dev server on 127.0.0.1:5173) and
  `website-preview` (the built site on 4174, after `npm --prefix website run build`; 4173 stays free
  for the preview Playwright starts in `npm run check`). `preview_start` with either name opens the
  pane; `resize_window` sets the widths `website/CLAUDE.md` asks for, and `read_page` or
  `get_page_text` reads the page before any screenshot. Claude in Chrome stays for pages behind the
  maintainer's sign-ins, chrome-devtools for Lighthouse, performance traces and heap snapshots. The pane
  supplements `npm --prefix website run check`, never replaces it.
- **Computer use** (maintainer decision 2026-10-24). Computer use may drive the Mac app (a development
  build or the installed release), Xcode, Device Hub and the paired iPhone through iPhone Mirroring: to
  explore a change before writing its XCUITest, to reproduce a report, to look for a blocking dialog
  before a UI lane, or for a setup chore such as installing a TestFlight candidate on the phone. Only
  the lead uses it, never while a native, device or measured lane runs (it shares the display, the
  phone and the host's load, and iPhone Mirroring needs the phone locked, which device lanes cannot
  use), and the iPhone only in a window the maintainer announced. What it shows is never a lane verdict,
  an evidence record or a substitute for XCUITest. It never signs in, enters a credential, accepts terms,
  grants a privacy permission or changes a system or security setting (the TCC grants in
  [`macos-app-guide.md` §7](macos-app-guide.md#7-macos-permissions-tcc), Developer Mode, UI Automation,
  airplane mode): those stay the maintainer's. The app asks the maintainer to approve each application it
  controls. Simulator routes stay unsupported.
- **Terminal panel.** A command the maintainer must run (a login such as `asc auth login` or
  `hf auth login`, a model install, a publication step) goes in a `bash` block, whose Run button runs it,
  or in a Terminal panel tab; any secret is typed there, never in chat. A watcher the maintainer wants to
  see may also run in a tab.
- **Waiting.** A background Bash command re-invokes the session when it exits: wait for one event (a run
  finishing, a deployment waiting for approval) with an `until` loop in the background, and use Monitor
  for a stream of events; never poll with `sleep`. The app keeps the Mac from idle-sleeping while a
  session works; before a wait that outlasts the turn (a release run, a lane checked later) call
  `request_keep_awake` with `until: "session_idle"`. It prevents idle sleep only: a closed lid still
  sleeps, and a macOS UI lane still needs the session unlocked.
- **Notifications and Remote Control.** The maintainer may follow a session from the phone.
  `PushNotification` is for what they must act on now (a `release` approval, a failed lane, a phone to
  unlock in an announced window), never routine progress; `SendUserFile` hands over a finished report.
- **Artifacts.** An artifact is hosted on claude.ai, so publish one only on request. Artifacts, file
  cards and notifications follow the privacy rule: no raw diagnostics, private paths, prompts,
  transcripts, reference audio or credentials; failure text goes through `DiagnosticPrivacy` summaries,
  and screenshots showing any of these stay local and untracked.
- **iOS Simulator panel.** Denied (`mcp__Claude_Code_iOS_Simulator__*` in the permissions, and
  `simulator_tool_guard.py`); the physical-iPhone lanes stay the only iOS route.

The Code tab's settings (branch prefix, worktree location, keep-awake, notifications) are the
maintainer's: Claude proposes a change through the app and never changes one to make a check pass.

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
Check visible blocking dialogs and competing automation before starting (a computer-use screenshot may
look; computer use stops before the lane starts), then leave the desktop
available until collection finishes. Report XCTest display/screenshot errors from retained evidence;
the earlier Unity modal and display-ID error do not establish a causal link. Do not automatically
close unrelated apps or modify display settings. Failed UI runs retain their original identities.
