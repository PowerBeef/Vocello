---
status: active
owner: release-qa
reviewed: 2026-11-20
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
scripts, CI, `AGENTS.md` and the Antigravity configuration. What it cannot contain is the machine:
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
  the judge; the report-only `xcode-preview.yml` shows the differences daily, and moving CI to Xcode
  27 is part of roadmap item DW-04.
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
npx --prefix website playwright install --with-deps chromium webkit  # as CI and website/AGENTS.md do
npm --prefix website run check
```

Node and npm pin only their major version (`config/toolchain.json` `website.node` 24, `website.npm`
11): CI's `setup-node` takes the latest 24.x with its bundled npm, and Homebrew's `node@24` follows the
same line, so `scripts/dev.sh ci` and `supply_chain_contract.py --installed website` pass on it. The
dependencies themselves stay exact through `website/package-lock.json`. Vercel deploys through its Git
integration; `vercel link --repo` is needed only to use the Vercel CLI.

`npm ci` does not download Playwright's browser builds, and the check's last part, the browser
tests, needs chromium, the chromium headless shell and webkit. `scripts/dev.sh doctor` reports
whether they are in the Playwright cache (`PLAYWRIGHT_BROWSERS_PATH`, else the platform cache) in
one line and as `websiteBrowsers` in `--json`. When `scripts/dev.sh check` or `ci` reaches the
website check on a host without them, it stops before the step, names the missing builds and the
install command (`npm --prefix website exec playwright install chromium webkit`) and installs
nothing: the download needs the maintainer's word. The probe is presence only, so a build left by
another Playwright version counts and Playwright itself names the revision it wants.

### 5. Git

Set a global identity (`git config --global user.name …` and `user.email …`) and do not add a
repository-local override. HTTPS credentials come from `gh auth login` or the macOS keychain. There
are no Git hooks, submodules or LFS files; the guards are supplementary Antigravity hooks. Release tags must be
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

### 8. Antigravity

Open the clone in Antigravity at the repository root; Antigravity automatically discovers `AGENTS.md`,
`website/AGENTS.md` (when touching website files), `.agents/hooks.json` and the workspace plugin
under `.agents/plugins/vocello/` (glob-triggered domain rules, six `vocello-*` skills and two
read-only subagents). Verify hooks and discovery in a fresh session following the
[fresh-session procedure](#antigravity-setup-and-tool-routing).

`scripts/dev.sh doctor --json` inventories prerequisites without installing anything, downloading
models or touching devices: tools and their pins, the selected Python and its test packages,
Playwright's browser builds for the website check and the repository's Antigravity harness files.
Detect MCP tools in the live session.

The maintainer's global Antigravity toolset is optional assistance, never a CI dependency. Detect
tools in the live session rather than assuming installation means connection:

- **MCP servers:** `axiom` (skills, read-only auditors, `xcsym`, `xcprof`, `xclog`), `mobilebuildmcp`
  (discovery and coverage only; Simulator, build and UI tools are denied by `.agents/hooks.json`),
  `sosumi`, `context7_context7` and `huggingface` (`hf_fs`, `hub_repo_search`, `hub_repo_details`,
  `hf_whoami`; Space-running tools ask).
- **Plugins & skills:** `asc` (App Store Connect CLI skills and rule), `chrome-devtools-plugin`
  (browser/a11y/perf debugging), `axiom` and `mobilebuildmcp` skills. `cua-driver` is denied in
  Vocello (UI checks are XCUITest-only); `vercel-plugin` does not authorize direct CLI deploys
  (Vercel deploys from Git).
- **Built-in surfaces:** the `browser` subagent for local website inspection and `invoke_subagent` /
  `swarm` for bounded parallel work.
- **CLIs:** `hf`, `asc` and `gh`.
- **Terminal sandbox:** Antigravity's default sandbox hides host paths outside the repository.
  Allowlist read access to `~/.qwenvoice-pinned-tools`, `~/Library/Python`,
  `~/Library/Caches/ms-playwright` and `~/Library/Application Support/QwenVoice`, plus read/write
  access to `~/Library/Caches/Vocello` (`native-build.lock`), so deterministic checks run smoothly
  inside the sandbox; commands needing Xcode, CoreDevice, Keychain or network run outside the sandbox
  with prefix-matchable command shapes.

`.mobilebuildmcp/config.yaml` enables only MobileBuildMCP's project-discovery and coverage workflows,
with macOS and physical-device profiles for scheme and settings lookups; repository scripts own
canonical builds and host serialization, and `.agents/hooks.json` hard-denies Simulator, build, UI
and `persist: true` calls even if global MCP environment variables expose extra workflows. Native UI
evidence comes only from XCUITest.

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
scripts/dev.sh lint                  # changed-file advisory SwiftLint, shellcheck, privacy
scripts/dev.sh build | run           # warm incremental macOS development build / launch
./scripts/build.sh cli && build/vocello models list  # the development CLI
npm --prefix website run check       # the website's lint, tests, build and browser tests
scripts/hooks/commit_lint.sh --staged  # the commit safeguard, callable directly
scripts/dev.sh ios                   # generic device-SDK compile (incremental, no phone)
scripts/dev.sh regen                 # regenerate roadmap render, docs index, catalog, inventories, charts, attributions
scripts/dev.sh ci                    # every gate push CI runs, serially, when you want the push green first time
git add <assigned-files>
git commit
git push  # only after an explicit request
```

Routing is `scripts/ci/classify_changes.py`, the same file CI uses, so the local plan and the CI
lanes agree. `scripts/dev.sh check` compiles the affected XCUITest bundles through
`scripts/build_ui_test_bundles.sh` when UI-test sources or `project.yml` change; it never runs them.
It also builds the `vocello` executable (`./scripts/build.sh cli --version`, CI's command) when a
source the CLI links changes (`Sources/VocelloCLI`, the cores, `Packages/`) or `project.yml` does:
the macOS test host never compiles the executable's own sources (BKL-75).
Push CI compiles all three bundles too (Mac, iOS and iOS candidate; `--gate`, after the deterministic builds in their arenas) and never
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

`scripts/hooks/commit_lint.sh` (invoked via `.agents/hooks.json` and `agy_hook_adapter.py`) requires
branch `main` in the main checkout, or a `subagent-*`, `swarm-*` or `worktree-*` branch in a
registered linked worktree; pushes only from `main` in the main checkout; a whitespace-clean staged
diff (`git diff --cached --check`); and a clean `scripts/privacy_scan.py --staged` (no developer home
path, no credential-shaped token, no key file). It never builds or tests.

Two checks only advise. Each returns a warning, never a block, and a message the hook cannot read
(an editor, a computed or reused message) skips it:

- behaviour-bearing Swift committed without the Swift review's trailer (see Operating defaults);
- while `config/roadmap.json` records a freeze (`focusLock.freeze`), a commit whose subject names
  no item of the focus plan, as in `... (RF-61)`. It is the rule `roadmap.py validate` applies to
  every commit after the freeze, said before the commit exists; the plan's open and archived items
  and their legacy ids count.

Two more guards (`policy_guard.sh` and `generated_file_guard.sh`) block Simulator destinations,
whole-cache deletion, force pushes, pushes of any ref but `main`, hand-made branches, broad staging,
`git commit -a`, stashing, `project.pbxproj` writes and hand edits of generated files. Staging is
judged on the parsed command, so every spelling is refused:

- `git add` with `-A`, `--all`, `-u` or `--update` anywhere among its options, or with a pathspec
  that names the current directory, a parent or the whole tree (`.`, `./`, `..`, `:/`, `:(top)`,
  `*`, `"$PWD"`, an exclusion such as `:!docs`);
- `git commit -a` or `--all`, alone or in a cluster such as `-am`;
- every `git stash` but `list` and `show`.

Named files, directories and globs below the current directory, and computed paths such as
`"$file"`, stay allowed. A command one of the policy parsers (git, build-output and project-file,
Simulator) cannot read is refused with the reason, never allowed unjudged: run it in a simpler
form, one command per call. `scripts/tests/test_agent_hooks.py` pins all of them.

## The contract gate

`./scripts/check_project_inputs.sh` runs every deterministic contract: build-output policy, generated
schemes, CLI identity, localization, saved-voice lifecycle, entitlements, support contact, public facts
(`scripts/public_facts_contract.py`: release identity, README and website copy), attribution, runtime
security (debug knobs, concurrency registry, TSan policy), owned-runtime inventory, backend wiring,
model catalog and host availability, iOS storage protection, supply chain, release steps, benchmark
history, README charts, the text-level delivery-instruction copy and audio QC take inputs (script
pool, calibration-take policy), the roadmap, the documentation index (`docs/INDEX.md`, fresh
against `python3 scripts/docs_index.py render`), the exact
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
defect rules selected in `ruff.toml`: syntax errors (`E9`), pyflakes (`F`), invalid escapes (`W6`),
pylint's errors (`PLE`), mutable defaults (`B006`) and debugger calls (`T10`); the file records why
the style families stay out (Python 3.10; 3.9 for the hooks and `scripts/select_python.py`), and
SwiftLint's `.swiftlint.yml` rules over every tracked Swift file its
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

`scripts/dev.sh` and the contract gate (`scripts/check_project_inputs.sh`) each select an
already-installed Python and propagate it to their child commands. Both source
`scripts/lib/python.sh`, which exports `VOCELLO_PYTHON` from `scripts/select_python.py` and puts the
repository shim (`scripts/lib/python-bin`) first on `PATH`, so every `python3` of the gate, of its
validators and of the Python suite runs on the selected interpreter. The release preflight, the
lanes and a direct call therefore reach the gate with the right interpreter without going through
`scripts/dev.sh`, even when the shell's bare `python3` has no pytest.
Use `VOCELLO_PYTHON=/absolute/path/to/python3 scripts/dev.sh ...` for an explicit interpreter;
this changes only that invocation, with no global PATH or package installation, and an explicit
interpreter never falls back to another. `doctor --json`
reports the selected executable, installed test-package versions and their pin compatibility.
Keep CI's declared Python environment; a missing local package is a prerequisite failure, not a
reason to skip tests. Other standalone `python3` commands still use the caller's shell environment.

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
| `dependency-submission` | ubuntu | push only (skipped on dispatch and pull requests) | seconds: `scripts/swift_dependency_snapshot.py` submitted to the GitHub dependency graph; needed by `CI required`, which it fails only when the snapshot cannot be generated: a failed or stalled POST (bounded at two minutes) is a warning annotation (BKL-58) |
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
inside `release.yml` on the tagged commit. `xcode-preview.yml` (daily and on dispatch, report-only)
runs the deterministic suites on GitHub's `xcode-27` preview image, so a difference between the two
toolchains shows before a push meets it; it blocks nothing and files no issue.
`swift-dependency-watch.yml` (weekly, read-only) compares the exact Swift pins with upstream releases
and open Dependabot alerts ([`mlx-guide.md` §9.4](mlx-guide.md#94-scheduled-release-and-advisory-watch)).
Jobs on the pinned toolchain install it through `.github/actions/native-toolchain`; the preview
selects its image's newest Xcode 27 instead.

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

`AGENTS.md` owns the working agreement: the edit-verify-commit loop, push and authorization rules and
the review routing. `native-engineering.md` (Swift/runtime) and `tooling-and-evidence.md` (contracts,
CI, debugging, benchmarks, release) are referenced by glob-triggered domain rules under
`.agents/plugins/vocello/rules/` when matching files are touched. Read them directly when planning.

The Swift review (`vocello-swift-review`) checks the policy boundaries, then test adequacy for every
behavioural change: a test that fails when the fix is reverted, fakes that reach the changed code,
assertions on what happened rather than on a state another path also publishes, cancellation and
swallowed errors on error paths, and a named parity fixture or seeded canary for numerics. Record a
completed review in the commit message with the trailer `Reviewed-by: vocello-swift-review`
(`git commit --trailer 'Reviewed-by: vocello-swift-review'`); for an agent's commit reviewed before
integration, `git cherry-pick -n <sha>`, then `git commit -C <sha> --trailer '...'`. The commit lint
warns, never blocks, when a commit of Swift under `Sources/QwenVoiceCore`, `Sources/iOS`,
`Sources/Services`, `Sources/ViewModels` or `Packages/*/Sources` lacks it.

A script's structural permission to push `main` is not conversational authorization: pushes still
need the explicit request `AGENTS.md` requires. Preserve the original failure and investigate it
before a rerun; record the reason and the new run ID.

## Parallel agents and worktrees

Use selective parallelism for disjoint editing, research, review or triage. At most four agents may be
active including the lead, inheriting the selected model for editing work (read-only research subagents
may use a lighter model). Run one full Python suite and one browser acceptance run at a time on the
16 GB development host. Subagents stay code-only; the lead owns native builds and every measured lane.

**Subagents and swarms.** Create editing subagents with `invoke_subagent(..., Workspace: "share")` (or
`swarm(..., workspace: "share")`). Antigravity creates a registered linked worktree under
`~/.gemini/antigravity/worktrees/<conversation-id>/subagent-*` on a `subagent-*` (or `swarm-*`) branch
from local HEAD, so commit the lead checkpoint first: dirty files do not carry over. Inspect Git
metadata and commit identity; a directory name is not proof of repository identity. Give each worker a
disjoint file set and clear validation limits. Subagents make scoped commits on their branch and never
push, edit the roadmap or checkpoint, or run models, devices, native UI or native builds. Hand-made
branches and worktrees stay denied. Read-only subagents (`Workspace: "inherit"`) share the main
checkout unscreened, so their prompt must state that they edit nothing.

**Guards.** `agy_hook_adapter.py` prepends the agent rules on `SessionStart` when a session starts in a
linked worktree, and `agent_guard.py` screens every call whose `cwd` is a linked worktree. It refuses
pushes, commits in the main checkout, native builds and tests, device, model and measured-lane scripts
(sourcing a lane script or a `scripts/lib` shell library included) and writes to the roadmap files or
`docs/development-progress.md`. It is a guardrail, not a sandbox. The commit lint accepts `subagent-*`,
`swarm-*` and `worktree-*` branches there.

**Integration.** The lead reviews each commit, integrates with `git cherry-pick` or
`git merge --ff-only`, and validates the combined result on the warm main cache. Do not edit scripts
used by a running lane. Note that `manage_subagents kill` does not delete `Workspace: "share"`
worktrees or branches: after integration, remove the worktree with `git worktree remove <path>` and its
branch with `git branch -d <branch>` (preserving needed ignored evidence first; `--force` and
`git branch -D` ask first). A cherry-picked branch is never merged, so `-d` refuses it: when
`git cherry main <branch>` prints only `-` lines, every commit is on `main` and `-D` loses nothing.

**Worker tracking.** Antigravity does not expose `SubagentStart`/`SubagentStop`/`SessionEnd` hooks or
`CLAUDE_ENV_FILE`, and the default terminal sandbox blocks `ps`. Before any source-bound measurement,
join or stop every subagent and swarm worker (`manage_subagents list`, `swarm status`), confirm no
other sessions are active in this repository, and explicitly pass `QVOICE_LEAD_ONLY=1` to the measured
lane. Never use `QVOICE_LEAD_ONLY=1` to bypass a known active worker or unknown lease. The host checks
a measured lane runs before any model loads (`require_quiet_host`, `check_cache_only_host`,
`QVOICE_ALLOW_BUSY_HOST`) are in [`tooling-and-evidence.md`](tooling-and-evidence.md), Host preflight.

## Antigravity setup and tool routing

Antigravity reads `AGENTS.md` at the repository root and `website/AGENTS.md` when website files are
touched. `.agents/plugins/vocello/` packages the glob-triggered domain rules (`rules/native.md`,
`rules/tooling.md`), the six `vocello-*` skills (`skills/`) and the two read-only subagents
(`agents/vocello-swift-review.md`, `agents/vocello-xcresult-triage.md`). No skill grants external-write
authority.

`.agents/hooks.json` is the sole lifecycle hook definition, dispatching to
`scripts/hooks/agy_hook_adapter.py` (working directory `.agents/`, so relative paths never depend on
the agent's `cwd`). Opening a session installs nothing and never builds or touches a phone.

| Event | Tool matcher | Handler (`agy_hook_adapter.py`) | Effect |
| --- | --- | --- | --- |
| SessionStart | — | `session-start` (`session_start.sh`) | Bounded local Git/status/cache-health/checkpoint `injectSteps` banner, plus agent rules when starting in a linked worktree |
| PreToolUse | `run_command` | `pre-command` (`policy_guard.sh`, `commit_lint.sh`, `agent_guard.py`, command policy) | Checkout-aware Git, staging, whitespace, privacy, cache, generated-project and physical-device hard denies; subagent worktree limits; explicit `ask` on pushes, destructive Git, downloads, installers, external writes (`gh`, `hf`, `asc`, `vercel`, `failure_issue.py`) |
| PreToolUse | `edit_file\|write_file` | `pre-edit` (`generated_file_guard.sh`, `agent_guard.py`) | Refuses hand edits of generated and frozen files, naming the generator; subagents never edit the roadmap or checkpoint |
| PreToolUse | `call_mcp_tool` | `pre-mcp` | Hard-denies `cua-driver`, Simulator MCP routes, MobileBuildMCP build/UI/clean/`persist: true` calls and Axiom `xcui`/simulator agents; prompts (`ask`) on Hugging Face Space runs (`dynamic_space`, `gr*`) and GitHub connector writes (denied in worktrees) |

`agy_hook_adapter.py` translates Antigravity's camelCase `toolCall` payloads into the repository's
tested guard scripts and converts exit-2 blocks into `{"decision": "deny", "reason": ...}` and
authorization-bound commands into `{"decision": "ask", "reason": ...}`. These cooperative guards
cannot sandbox interpreter indirection or arbitrary external programs; `policy_guard.sh` fails closed
when a command parser cannot read a shell command.

Safeguards remain directly callable without hook activation:

```sh
scripts/hooks/commit_lint.sh --staged
git diff --check
python3 scripts/privacy_scan.py --changes
scripts/repo_invariants.sh
python3 scripts/build_output_policy.py validate
scripts/dev.sh py scripts/tests/test_agent_hooks.py scripts/tests/test_active_workers.py
```

CI classification, Python consumer selection and reference scanners include `.agents/`, `AGENTS.md`,
`website/AGENTS.md` and the two rule sources, and keep the retired `.claude/` and `.codex/` prefixes
routed so a deletion or reintroduction still runs the hook tests; harness-only edits exercise
behavioral checks without triggering native builds.

For a fresh-session smoke check, start a new Antigravity conversation at the repository root. Confirm:
the `SessionStart` banner ("AGENTS.md: Start here"); `AGENTS.md` loaded (and no `CLAUDE.md`); the six
`vocello-*` skills and both read-only subagents discoverable; harmless guard fixtures denied
(`git switch -c smoke`, an `edit_file` on `docs/ROADMAP.md`, `call_mcp_tool` to `mobilebuildmcp`
`list_sims` or `cua-driver_cua-driver` `list_apps`); an external write (`git push --dry-run` or
`huggingface` `dynamic_space`) triggering an `ask` prompt; and `scripts/dev.sh doctor --json` reporting
the Antigravity harness configured.

| Work | Authoritative route | Optional assistance |
| --- | --- | --- |
| Builds/tests/native UI | Repository scripts, owned caches and XCUITest (`scripts/ui_test.sh`) | `mobilebuildmcp` discovery and coverage reads only; agent review of lane screenshots (`<run>/screenshots/index.json`) |
| Apple architecture/APIs | Source, Apple primary docs and retained artifacts | `axiom` MCP skills and read-only auditor agents; `sosumi`; Xcode's bundled documentation |
| Libraries | Pinned versions in `config/toolchain.json` and package manifests | `context7_context7` |
| MLX runtime | Owned facade, exact pins and `docs/reference/mlx-guide.md` | Installed MLX guidance |
| Code review | The actual diff and the reference rules | Read-only `vocello-swift-review` subagent (`Reviewed-by: vocello-swift-review`) |
| Finished native run | `scripts/dev.sh triage <run-directory> --json` and `testing-runbook.md` | Read-only `vocello-xcresult-triage` subagent, `xcresulttool`, LLDB when indicated |
| Build/crash/trace diagnosis | Raw logs, crash reports, existing traces | `axiom` MCP `xcsym`, `xcprof` and `xclog` tools, with script-only fallback |
| Website | `npm --prefix website run check` | Local Vite dev/preview (`IsDaemon: true`) + Antigravity `browser` subagent or `chrome-devtools` skills; Vercel deploys from Git (`vercel` CLI asks) |
| Repository/CI | Exact-commit checks and repository release scripts | `gh` CLI reads; `gh run watch` in the background after an authorized push |
| App Store/deployment/publication | Explicitly requested release workflow | `asc` plugin skills over Homebrew `/opt/homebrew/bin/asc`, and `vercel` CLI (both ask on writes) |
| Model research | Receipts, exact pins and maintenance contracts | `huggingface` MCP reads (`hf_fs`, `hub_repo_search`, `hub_repo_details`, `hf_whoami`) and `hf` CLI reads; downloads, Space runs and writes ask |
| Audio quality | `scripts/qc.py` machine screens and report-only QC v2 (`docs/reference/qc.md`); nobody listens for 3.x (maintainer decision 2026-10-13) | Hugging Face discovery for candidate models; rendered evidence images. The agent cannot hear audio and never issues listening verdicts |
| Antigravity configuration | Tracked `.agents/`, `AGENTS.md`, `website/AGENTS.md` and `scripts/tests/test_agent_hooks.py` | Built-in `agy-customizations` skill |

Detect capabilities in the current session rather than assuming installation means connection.
`mobilebuildmcp` reads `.mobilebuildmcp/config.yaml`, which enables only its project-discovery and
coverage workflows; if global MCP environment variables expose Simulator, build or UI tools anyway,
`.agents/hooks.json` hard-denies them as a backstop. Never persist session defaults (`persist: true`
writes the tracked file and is denied by the hook). Never use `cua-driver`, Axiom `xcui`, or Axiom's
simulator/test-runner agents. Keep raw native logs, original exit status, optimization flags and
evidence manifests; compact helper output cannot replace their contracts. Missing optional tools never
block the script workflow; personal plugins, skills, accounts and credentials are not CI dependencies.
Never install or change global configuration simply to satisfy a routing table.

### UI checks, waiting and privacy in Antigravity

- **UI checks are XCUITest lanes** (maintainer decision 2026-11-17, retiring computer-use and iPhone
  Mirroring routes). Every Mac and iPhone UI check runs through `scripts/ui_test.sh`; a check no lane
  covers gets its own scenario. Never use `cua-driver`. The iOS `ui-preflight` refuses a lane while
  iPhone Mirroring is open (`scripts/ios_device.sh mirroring stop`, then the maintainer unlocks the
  phone). What XCUITest cannot drive stays the maintainer's, by hand (iPhone system settings,
  permission prompts, passcode/Face ID, audio routing, VoiceOver, app deletion, purchase confirmations,
  TestFlight installs, macOS privacy grants in [`macos-app-guide.md` §7](macos-app-guide.md#7-macos-permissions-tcc)).
  Review `<run>/screenshots/index.json` after every lane (report-only).
- **Waiting and background lanes.** Use `run_command`'s native async execution (`WaitMsBeforeAsync: 500`,
  or `IsDaemon: true` for Vite dev/preview servers) and reactive wakeup instead of shell `&` or `sleep`
  polling loops.
- **Maintainer-run commands.** Commands requiring interactive secrets or logins (`asc auth login`,
  `hf auth login`, release tags, model installs) go in a plain `sh` block for the maintainer to run in
  their terminal; never type secrets in chat.
- **Artifacts and privacy.** Antigravity artifacts, screenshots and summaries carry no raw diagnostics,
  private paths, prompts, transcripts, reference audio or credentials; failure text goes through
  `DiagnosticPrivacy` summaries, and screenshots showing any of these stay local and untracked.

### Host and release prerequisites

The development host may use a newer Xcode than the exact CI/release pin. `doctor` reports this
mismatch without changing the selected developer directory, and local success does not establish
pinned-compiler acceptance (New Mac setup, section 1). Release
checks consume exact tools from `config/toolchain.json`; select the existing pinned-tool bin
directory when available and verify with `scripts/supply_chain_contract.py --installed release`.
An ambient newer `gh` is fine for ordinary read-only inspection but cannot qualify a pinned release.
Missing pinned tools require the existing authorized installation workflow before a release;
do not repin dependencies or change global settings to make the inventory green.

For macOS XCUITest, keep one stable interactive desktop session and avoid simultaneous UI work.
Check visible blocking dialogs and competing automation before starting, then leave the desktop
available until collection
finishes. Report XCTest display or screenshot errors from retained evidence. Do not automatically
close unrelated apps or modify display settings. Failed UI runs retain their original identities.
