---
status: active
owner: backend-and-platform
reviewed: 2026-10-18
summary: Read-only audit of the development workflow and tooling (dev loop, CI, hooks, verification system, Apple build and observability settings, the maintainer's Claude Code setup) with verified findings and a phased improvement programme for velocity, code accuracy and Apple-optimized engineering quality. Recommendations only; nothing is scheduled until the maintainer picks a phase.
sourceOfTruth:
  - scripts/development_workflow.py
  - scripts/ci/classify_changes.py
  - .github/workflows/ci.yml
  - .claude/settings.json
  - scripts/hooks/session_start.sh
  - scripts/hooks/agent_guard.py
  - scripts/hooks/policy_guard.sh
  - project.yml
---
# Vocello: development-workflow audit and improvement programme

**Baseline:** `1b02555f`, reviewed October 18, 2026. Requested by the maintainer: audit the development
workflow and tooling, then research and engineer a plan to improve development velocity, code
accuracy and Apple-optimized engineering quality. It follows the
[October 10 Codex workflow audit](2026-10-10-codex-workflow-audit.md) and the
[October 12 Claude Code takeover audit](2026-10-12-claude-code-takeover-audit.md), and it treats the
[October 16 engine audit](2026-10-16-engine-runtime-audit.md) as the record of what escaped testing.

## Method, evidence and limits

- Three read-only explorers:
  - the dev loop, CI and harness;
  - the verification system;
  - the Apple toolchain, with external research.
- A planning agent re-verified every load-bearing claim against the code, read-only `gh` CI logs,
  retained artifacts and pure-Python simulations of the test selector. It corrected several counts;
  this report uses the corrected figures.
- The lead checked the maintainer's personal Claude Code settings and investigated the lost build
  caches.
- Nothing was built, run, edited or downloaded. Weekly costs are estimates scaled from git history
  (October 11-17: 105 commits).
- Personal settings are described here, not copied.

**Maintainer decisions (2026-10-18):**
1. Tooling-only changes (scripts, CI, hooks, docs, Claude Code configuration) may start before the
   RF-09 freeze, because they never touch the shipped binary. Anything that changes compiled app code,
   build settings, `Package.swift` or Swift sources waits until after the 3.0 submission.
2. This report is the deliverable. The phases below are recommendations: nothing is implemented or
   added to `config/roadmap.json` until the maintainer picks a phase. After the freeze, a picked item
   is re-homed into the release plan, because every commit must then name a release item.
3. The maintainer's personal Claude Code setup is in scope. During the audit the maintainer removed the
   user-scoped TypeScript LSP plugin and enabled the Python (pyright) LSP plugin.

## Findings: velocity

| ID | Finding | Evidence |
|---|---|---|
| W-01 | **Bookkeeping dominates the commit stream.** Of 105 commits in a week, 50 touched `config/roadmap.json`, 32 the progress checkpoint and 31 the generated `docs/ROADMAP.md`; 54% touched nothing under `Sources/`, `Packages/` or `Tests/`. `roadmap.py` can only validate, render and report, so every status change is a hand edit of a 201 KB JSON (491 KB for the archive) plus a render. The checkpoint holds 78 entries (187 KB) although its header says older ones live in git. | `scripts/roadmap.py:658,672`; `docs/development-progress.md:13-16` |
| W-02 | **The Python "selection" runs almost the whole suite.** Line 122 adds each Python file's stem as a search word, and generic stems match ordinary English in docstrings (`evidence` appears in 119 script files, `qc` in 86). Out of 126 test modules, the selector picks 118-120 for a change to `roadmap.json`, `roadmap.py`, `ui_test.sh`, `macos_test.sh` or `project.yml`, so a roadmap-only `check` costs about 75 s (about 60 s of pytest plus the 14 s contract gate). A simulated fix — direct filename mentions plus the reverse import graph `classify_changes` already builds — selects 3-35. CI's Linux job still runs the full suite, so a narrower local selection stays safe. | `scripts/development_workflow.py:90-134`; `scripts/ci/classify_changes.py:152,184`; `.github/workflows/ci.yml:186,192` |
| W-03 | **UI lanes fail more often than they pass.** 62% of retained UI-lane minutes went to failed runs (288 of 465). iOS smoke passed 1 of 10, purchase 4 of 14, macOS smoke 7 of 15 and iOS model-download 0 of 3; these are lower bounds, because retention keeps one passing run per lane. Some failures are real product defects. `run.json` records only status and exit code, so infrastructure failures can't be told from product failures. | `config/build-output-policy.json` (`childRetention.uiResults`) |
| W-04 | **The CI build cache is a weekly snapshot that goes stale.** MV-01's fix works: early in ISO week 42 a warm job recompiled 2-155 files, in about 5 minutes. A run that hits the key exactly never saves again, though, so by October 16-17 the same snapshot recompiled 1,101-1,458 files and the job took 13.5-18 minutes. `project.yml` is part of the graph hash (three new cache namespaces on October 17 alone), the cache sits at about 9.5 of GitHub's 10 GB, and CI builds an index it then deletes. Toolchain setup costs about 90-100 s per macOS job. | `.github/workflows/ci.yml:214-227,289,299,386`; `scripts/macos_test.sh:170` |
| W-05 | **Local and CI toolchains differ.** Local Xcode is 27.1 while CI is pinned to 26.6. That caused 2 of 7 push failures in three weeks, and the failing test name appears only in an uploaded artifact, not in the job log. | `config/toolchain.json`; `docs/reference/native-engineering.md:186-193` |
| W-06 | **The local swift lane can verify nothing.** `swift_test_commands` reacts only to `.swift` paths. Non-Swift inputs that route to the swift lane schedule no macOS test at all, although Swift tests read them. Examples: `config/test-quarantine.json`, `config/ios-memory-budget-policy.json`, the QC calibration and parity fixtures, `scripts/lib/xctest_summary.py`, `scripts/lib/build_paths.sh`, `config/toolchain.json`, `scripts/macos_test.sh` and `scripts/build.sh`. `check` never schedules TSan, which CI runs. | `scripts/development_workflow.py:217-228,280-298` |
| W-07 | **Agent work costs integration time and hits guard walls.** There were 355 cherry-picks and 19 worktree merges in a month. Agents can't compile, by design, and build caches are per checkout. The agent guard also blocks every verb of the lane scripts, including `help`, which two skills tell agents to run, and blocks `xcodebuild -version`. | `scripts/hooks/agent_guard.py:28-30,81-88`; `.claude/skills/vocello-macos-ui/SKILL.md:4,12`; `.claude/skills/vocello-ios-validation/SKILL.md:4,14` |
| W-08 | **Session start pays a large context cost.** The SessionStart hook prints "Resume now" cut at 18 lines, mid-bullet. That drops the resume commands, so sessions open the 187 KB checkpoint (about 47k tokens). `CLAUDE.md` is 15 KB, and the two path-scoped rules (34 KB) load for any edit under `config/**`, including roadmap edits. Skills point at up to 159 KB of reference docs. | `scripts/hooks/session_start.sh:30-36` |
| W-09 | **The release rehearsal repeats push CI.** It fires on `project.yml` and build-script pushes, takes a median 32.5 minutes and failed 7 of 25 runs (28%); four of those were BKL-12's DMG disk exhaustion, since fixed in `4988c160`. It always reruns the contract gate, the full Python suite and the deterministic macOS tests that push CI just ran on the same commit. | `.github/workflows/release-rehearsal.yml:17-41,102`; `scripts/release.sh:161` |
| W-10 | **Guards and docs produce false positives.** | |
| | • The policy guard scans the whole command text, so `rg` searches and `-m` commit messages that mention `simctl boot` or `iphonesimulator` are refused. Plain `simctl list` passes. | `scripts/hooks/policy_guard.sh:54-60` |
| | • `Bash(git stash*)` also denies the read-only `git stash list`. | `.claude/settings.json:292` |
| | • `CLAUDE.md`'s `python3 -m pytest` fails: the bare Homebrew `python3` (3.15) has no pytest. Only commands routed through `dev.sh` or `select_python.py` work. | `CLAUDE.md:86` |
| | • The workflow doc claims a pytest allow rule that none of the 72 allow rules provides. | `docs/reference/development-workflow.md:301` |
| | • Hook latency itself is negligible: 0.10-0.14 s per Bash call. | |
| W-11 | **Lane scripts are duplicated and fragile.** | |
| | • Eleven functions exist in both `macos_test.sh` (2,037 lines) and `ios_device.sh` (3,299 lines) with drifted bodies. | |
| | • The three large lane scripts make 177 embedded `python3` calls. | |
| | • Twelve pytest modules (51 sites) assert shell-script source text, which the tooling rules list as a common mistake. | `docs/reference/tooling-and-evidence.md:171` |
| | • The deterministic lane has no per-test deadline; one run hung for 65 minutes on an XPC error. | `scripts/macos_test.sh:254-258` |
| W-12 | **Active prose is stale.** | |
| | • "At most two in flight" contradicts the focusLock's 4 until the freeze. | `CLAUDE.md:107`; `docs/reference/release-first-execution-2026-09.md:81` |
| | • The workflow doc says the swift lane always runs the macOS bundles, which W-06 disproves. | `docs/reference/development-workflow.md:46-48` |
| | • The October 17 checkpoint says "not pushed" after the push. | |
| | • Dependabot PRs fail by design until `--sync-actions` is run by hand; two website PRs have been open since September 14. | |
| | • The nightly reruns on an unchanged commit. | |
| W-13 | **The local Xcode build arenas were lost.** Every `build/cache/xcode/*` derived-data root (about 14 GB: macOS, optimized, TSan, iOS device, source packages) vanished at 21:15 EDT on October 17, while the data volume was 98% full. | `scripts/project_generation.py:122-127` |
| | • The repository cleaner was not the cause: it honored `--dry-run` during that window, and a real cache cleanup would also have removed the public `build/vocello` and `build/Vocello.app` links, which survived. `build/cache/swiftpm` was untouched. | |
| | • The CoreSimulator device folder changed in the same minute, so the likeliest cause is macOS's low-storage purge (unproven; the unified log no longer covers it). | |
| | • The project-generation stamp lived inside the lost arena, so the next `check` regenerates. The public links dangle, and the next native run is cold. | |
| | • The development-build free-space preflight requires only 8 GiB. | |

## Findings: code accuracy

| ID | Finding | Evidence |
|---|---|---|
| A-01 | **No Swift Testing, and no runner that could see it.** No file imports Testing, against 163 `XCTestCase` classes. About 1,676 tests run per Swift push: 1,477 in `VocelloCoreTests`, including the iOS logic suite compiled in, and 199 in `Qwen3RuntimeTests`. The UI bundles compile in CI but never execute there. Three parsers assume XCTest output, so Swift Testing results would silently drop out of selection and summaries. | `scripts/development_workflow.py:26`; `scripts/macos_test.sh:226,234`; `scripts/lib/xctest_summary.py:29-35` |
| A-02 | **Why ~200 engine defects passed green suites** (classified from the October 16 audit): | |
| | 1. Fakes stop before the code under test: the cancel fake throws in `qwen3Capabilities`, so the warm body never runs (B-02). | `Tests/VocelloCoreTests/ActiveGenerationCoordinatorTests.swift:1002-1010` |
| | 2. Assertions read published state, not what happened. A `.loaded` state and an unload count are satisfied by the wrong path. | `Tests/VocelloCoreTests/TTSEngineStoreTests.swift:1455-1497,1298` |
| | 3. 171 app-layer files (53k lines) are in no unit-test target. That includes the download coordinator, bootstrap, player view model and recorder, where E-01/E-02, D-01 to D-03, G-05 and G-07 lived. | |
| | 4. `MLXModelLoadCoordinator` (1,494 lines) is reached only through a static helper, and `NativeEngineRuntime` (2,565 lines) from a single test file. | |
| | 5. No upstream parity fixtures: A-02's Mimi RoPE convention is still open, and the one reference test, AudioSeal parity, skips in CI. | `Packages/VocelloQwen3Core/Sources/MLXAudioCodecs/Mimi/Transformer.swift:130` |
| | 6. No property tests for the planner or conversions (C-04, C-02, A-15). | |
| | 7. Tests don't run the shipped configuration: TF32 off, `-Onone`, debug package tests, and TSan without the runtime package. | `scripts/macos_test.sh:1511`; `config/tsan-policy.json` |
| | 8. Error paths aren't enforced: catch-alls treat cancellation as failure, and there are 539 `try?` in sources. | |
| | 9. No interleaving tests inside load, warm or marking. | |
| A-03 | **Static analysis is thin and mostly advisory.** | |
| | • SwiftLint runs only locally on changed files: 8 rules, `Packages/` excluded, its own config says "never a gate". | `.swiftlint.yml` |
| | • shellcheck is installed on the CI runners but never run over the 13k lines of shell. | |
| | • The owned package is not warnings-as-errors; its only flag is a debug-only concurrency warning. | `Packages/VocelloQwen3Core/Package.swift:71` |
| | • 35 `@preconcurrency` imports, 11 of them of the project's own VocelloQwen3Core. | |
| | • The analyzer allowlist's `check` command is never called. | `scripts/ios_release_analyzer_warnings.py:129` |
| | • Coverage is opt-in and "never a verdict input". | |
| | • No ASan, UBSan or Periphery. | |
| | • 77k lines of Python, 92% annotated, have no ruff, mypy or pyright config. | |
| | • The website is JSX with no type check or ESLint. | |
| A-04 | **Review checks policy, not behaviour.** The Swift review agent checks eight policy boundaries, but never asks: | `.claude/agents/vocello-swift-review.md`; `config/backend-risk-spine.json` |
| | • whether a new test would fail if the fix were reverted; | |
| | • whether the fake reaches the code under test; | |
| | • whether numerics cite a parity fixture. | |
| | Only 13 of the last 150 Swift commits record any review. The risk spine maps 10 risks to tests, none of them from the October 16 audit. | |
| A-05 | **Flakiness inputs.** Unit tests hold 49 `sleep` calls; UI tests ban sleeps but unit tests have no such rule. 21 store tests skip on host thermal state, `waitUntil` polls at 97 sites, and there are 17 `XCTSkip` sites. Quarantine is the policy, with 0 entries. | `Tests/VocelloCoreTests/TTSEngineStoreTests.swift:551-557`; `scripts/repo_invariants.sh:73-79` |

## Findings: Apple-optimized engineering

| ID | Finding | Evidence |
|---|---|---|
| E-01 | **Dev and test builds compile MLX unoptimized.** Dev, test, UI-bundle and foundation builds pass `-Onone` and `GCC_OPTIMIZATION_LEVEL=0` on the command line, which applies to package targets too, so the MLX C++ core and swift-transformers run at `-O0` in every deterministic run. The target-scoped pattern that avoids this already exists for diagnostics flags. MLX compiles in five separate arenas. The release build is unaffected. | `scripts/build.sh:146-149`; `scripts/macos_test.sh:162-164`; `scripts/build_ui_test_bundles.sh:96-97`; `project.yml:304-307,401-404`; `scripts/release.sh:276-277,306` |
| E-02 | **App code compiles twice.** About 100 app Swift files (26.6k lines) compile into both the app and `VocelloCoreTests` by path. `project.yml` changed in 73 commits since September 1. | `project.yml:419+` |
| E-03 | **Build settings are left unused.** | |
| | • `dwarf-with-dsym` on every link. | |
| | • The index store is built on CI, then deleted. | |
| | • No compilation caching, no build timing summary, no dead-code stripping. | |
| | • The nightly "optimized" compile is incremental, not whole-module, so it doesn't reproduce release codegen. | `scripts/build_foundation_targets.sh:129-130` |
| | • The project-level `SWIFT_VERSION` is XcodeGen's 5.0, overridden per target. | |
| E-04 | **Strictness the installed Xcode 27.1 offers but the project doesn't use** (confirmed in its build-setting specifications): | Xcode 27.1 `Swift.xcspec`, `CoreBuildSystem.xcspec` |
| | • warning groups; | |
| | • `SWIFT_STRICT_MEMORY_SAFETY` (migrate mode); | |
| | • InferIsolatedConformances and NonisolatedNonsendingByDefault (migrate mode); | |
| | • MemberImportVisibility; | |
| | • Enhanced Security / memory tagging. | |
| | Whether CI's Xcode 26.6 accepts them is unverified; Xcode ignores unknown settings without warning. | |
| E-05 | **Observability gaps.** | `Sources/QwenVoiceCore/GenerationOutputAdapter.swift:2150`; `scripts/macos_test.sh:216-227,412-445` |
| | • No signpost interval around AudioSeal marking (most of end-of-take time), `LongFormAssembly` or the 3,672-line downloader. | |
| | • Two identical `AppPerformanceSignposts` files, four logger subsystems, and 54 non-CLI `print` calls. | |
| | • No macOS MetricKit. | |
| | • Main Thread Checker never runs: the raw `xcrun xctest` runs don't inject it, though TSan is injected the same way. | |
| | • Profile kinds are only CPU, memory and witness. There is no Metal System Trace kind and no MLX GPU-capture knob, while Xcode 27.1 ships Metal System Trace, Swift Concurrency, Audio System Trace, Power Profiler and Processor Trace. | |
| E-06 | **Modernization backlog.** | `config/concurrency-safety.json` |
| | • 20 `ObservableObject` against 10 `@Observable`, including the 2,145-line `AudioPlayerViewModel`. | |
| | • 12 `NSLock`, 21 `AnyView` constructions. | |
| | • The concurrency-safety budget is exactly at its ceiling (33 and 6). | |
| | • vDSP use in long-form assembly and the silence gate would gain little: decode is GPU-bound. | |

### Sourced research (Xcode 26/27, Swift 6.2-6.4)

Confidence: high where the source is Apple's or swift.org's own documentation, medium otherwise.

- **Xcode 26** ([release notes](https://developer.apple.com/documentation/xcode-release-notes/xcode-26-release-notes), high): opt-in compilation caching; explicit modules by default; Processor Trace, SwiftUI, Power Profiler and CPU Counters instruments; an Enhanced Security capability; Swift Testing exit tests and attachments.
- **Compilation caching limits** ([Bitrise FAQ](https://docs.bitrise.io/en/bitrise-build-cache/build-cache-for-xcode/xcode-compilation-cache-faq), [Swift Forums](https://forums.swift.org/t/about-swift-shared-cache-across-machines/81850), medium): package dependencies were not cacheable in Xcode 26, and sharing the cache across machines is immature.
- **Xcode 27** ([release notes](https://developer.apple.com/documentation/xcode-release-notes/xcode-27-release-notes), high):
  - Swift 6.4, with duplicate Clang module names now an error.
  - ld64 removed. Nothing here passes ld64 flags, so this is a non-event.
  - A Swift Executors instrument; `xctrace` recording options and ranged export.
  - `swift test --repeat-until`; Xcode MCP build-setting tools and a headless MCP server.
- **Swift 6.3** ([swift.org](https://www.swift.org/blog/swift-6.3-released/), high): Swift Testing warning-severity issues and `Test.cancel()`.
- **Swift 6.4** ([WWDC26 session 262](https://developer.apple.com/videos/play/wwdc2026/262/), medium): per-declaration diagnostics control, `weak let` and `~Sendable`, `withTaskCancellationShield`, and Swift Build as SwiftPM's default backend.
- **Warning control and memory safety** (high): [SE-0443](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0443-warning-control-flags.md) warning-group flags; [SE-0480](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0480-swiftpm-warning-control.md) `treatAllWarnings(as:)`; [SE-0458](https://forums.swift.org/t/accepted-se-0458-opt-in-strict-memory-safety-checking/78116) strict memory safety.
- **Enhanced Security** ([Apple](https://developer.apple.com/documentation/xcode/enabling-enhanced-security-for-your-app), high): pointer authentication, typed allocators and memory tagging (A19 and M5 or later). Guard objects cost memory, which is tight on 8 GB devices; the scripts' forced `ARCHS=arm64` conflicts with an arm64e slice.
- **mlx-swift wired-memory tickets and `GPU.startCapture`** (local package checkout, medium): wired-memory debug events are emitted only in DEBUG builds, which this Release-only project never produces.

## Findings: the maintainer's Claude Code setup

| ID | Finding |
|---|---|
| U-01 | The user-level auto-mode environment text describes a different repository of the maintainer's, so Vocello sessions in auto mode are classified against the wrong project. Vocello is public; pushing publishes. |
| U-02 | `.claude/settings.local.json` allows `git push *`, contradicting the tracked ask rule and `CLAUDE.md`'s explicit-request rule, and allows arbitrary `python3 -` stdin scripts. |
| U-03 | The skill listing measured about 100k characters against a 30k budget, so descriptions are truncated. Several user-level skills target toolchains Vocello doesn't use (gcc, gdb, clang, wasm-emscripten, simd-intrinsics), and the clangd LSP is enabled although Vocello has almost no C or C++ of its own. |
| U-04 | The Python LSP is now enabled and its server is installed, but the repository has no pyright configuration. It will not find the interpreter `scripts/select_python.py` picks, so its first diagnostics will be mostly unresolved imports. |

## Programme

**Owners:**
- **A**: an editing agent in a worktree (pure Python, docs or config);
- **L**: the lead (native validation, CI observation, roadmap and checkpoint);
- **M**: the maintainer (personal settings).

### Phase 0: tooling quick wins, allowed before the freeze (about 24-30 hours)

| ID | Item | Reuse | Own | Success metric |
|---|---|---|---|---|
| P0-1 | Python selection: drop stem search words; follow the reverse import graph; count filename mentions only at depth one | `classify_changes._imported_script_modules` (`scripts/ci/classify_changes.py:152`) | A | A roadmap-only `check` under 20 s (from about 75 s); ≤ 10 modules selected; a pinned test locks the counts; CI keeps the full suite |
| P0-2 | Close the swift-lane gap. Data inputs map to the test classes that read them. Lane scripts and `scripts/lib` run `macos_test.sh test`. | `changed_swift_test_classes`, `SWIFT_PARITY_FIXTURES` | A | A parametrized test: every swift-lane input schedules a native command |
| P0-3 | Session start prints the whole first checkpoint, capped at 4 KB and cut at a bullet boundary, plus one cache-health line: missing arenas, dangling links, free disk below a floor | `with_deadline` in the hook; `scripts/lib/storage_preflight.py` | A | No mid-bullet cut; cache loss reported at session start |
| P0-4 | Trim the checkpoint to the newest five entries; git keeps the rest, as its header promises | - | L | Under 30 KB |
| P0-5 | `roadmap.py set`, `close` and `note`, which edit the JSON in stable form and re-render `ROADMAP.md` in the same call | existing `validate`/`render` | A | `ROADMAP.md` never committed alone; render-check failures 0 |
| P0-6 | Fix guard false positives. Allow lane `help`/`list` and `xcodebuild -version`/`-list`. The policy guard judges each command's own words and ignores quoted search patterns and `-m` text. Only stash mutations are denied. | `agent_hook_input._simple_commands`; `scripts/tests/test_agent_hooks.py` | A | A corpus test: every known false positive passes and every true positive still blocks |
| P0-7 | Doc drift (W-10, W-12): the pytest command, the in-flight limit, the swift-lane claim, the nonexistent allow rule | - | A | No stale claim remains |
| P0-8 | Failing test names in the CI job summary | the `test-results.json` written by `xctest_summary.py` | L | The failing test is visible in `gh run view` |
| P0-9 | CI cache. Save a rolling snapshot when a warm run compiled more than 200 files. Take `project.yml` out of the graph hash and add a hash of the build flags. Add `-showBuildTimingSummary`. | the "test bundles built: N" line | L | p50 macOS job ≤ 8 min and p90 ≤ 200 recompiled files over a week; cache under 9 GB |
| P0-10 | Personal setup (U-01 to U-03). Correct the auto-mode text to Vocello (public). Remove the local push allow and review `python3 -`. Archive the unrelated skills. Disable the clangd LSP. | - | M | Skill listing under the 30k budget |
| P0-11 | A `pyrightconfig.json` at basic level, report-only: `scripts/` roots, the selected interpreter, `build/` excluded | `scripts/select_python.py` | A | LSP diagnostics are type findings, not unresolved imports |
| P0-12 | Recover from W-13: `dev.sh regen`, then one warm-up build in an idle window before any measured lane; raise the free-space floor | `check_plan`'s automatic regeneration | L | No measured lane starts on a cold arena |

### Phase 1: structural tooling, no change to the shipped binary (about 45-65 hours)

| ID | Item | Own | Success metric |
|---|---|---|---|
| P1-1 | **Lane ledger:** one JSON line per finished lane run (lane, commit, verdict, duration, failure class); `failureClass` in `run.json`; `dev.sh status --kpi` | L | Every failed run classified |
| P1-2 | **UI readiness preflight** (unlocked, automation mode, model present) that fails in under 60 s, before the build | L (iPhone side in an announced window) | Infra failures ≤ 1 in 10 runs; failed-minute share ≤ 30% (from 62%) |
| P1-3 | **Contract validators** run in parallel and are selected by path | A | Contract gate ≤ 5 s (from about 14 s) |
| P1-4 | **Deterministic-lane deadline** with a `sample` stack capture and a TIMEOUT verdict | L | No run lasts more than twice its p95 |
| P1-5 | **Main Thread Checker**, report-only, injected like the TSan runtime | L | Violations counted in a summary |
| P1-6 | **Swift Testing groundwork:** the three parsers first; a spike proving the raw `xcrun xctest` path executes Swift Testing on 26.6 and 27.1; an executed-equals-discovered check | A + L | A mixed fixture parses exactly what ran |
| P1-7 | **shellcheck** in the CI contracts job, with a baseline; only changed files gated | A | No new findings |
| P1-8 | **ruff** (syntax and pyflakes rules, pinned binary); a new tool, so it needs approval | A | No F-class findings |
| P1-9 | **Behaviour tests** replace the 12 pytest modules that assert shell source text | A | No test reads `.sh` text |
| P1-10 | **Rehearsal:** skip gates push CI already proved on the same commit; drop the `project.yml` trigger | L | Median ≤ 20 min, failures ≤ 10% |
| P1-11 | **CI build cost:** no index store; cache pip wheels and pinned tools; whole-module nightly | L | Toolchain step ≤ 30 s |
| P1-12 | **Review agent** gains revert-adequacy, fake-reach, ground-truth, error-path and numeric-parity checks; an advisory review trailer | A | ≥ 80% of Swift commits record a review (from 13 of 150) |
| P1-13 | **Risk spine** maps every October 16 finding; offline parity fixtures generated (Mimi RoPE first) | A | Each open finding mapped or marked uncovered |
| P1-14 | **CI probe** of which newer settings Xcode 26.6 accepts; a nightly coverage report, not a verdict | L | Availability table; coverage baseline for the runtime files |
| P1-15 | **Shared library** for the eleven duplicated lane functions | L | No duplicates; `ios_device.sh` changes only in an iPhone window |

### Phase 2: after the 3.0 submission (product-side)

| ID | Item | Success metric |
|---|---|---|
| P2-1 | Target-scoped dev optimization. Owned targets read a project variable; scripts stop forcing `-Onone` globally, so MLX and packages build at `-O`. | Test execution about 30% faster; release settings unchanged |
| P2-2 | `dwarf` debug info for test builds. Compilation cache stored under `build/` and registered in the build-output policy. | Warm test build about 15% faster |
| P2-3 | A shared framework replaces compiling app files into `VocelloCoreTests` by path | No app file compiled by path |
| P2-4 | Swift Testing for new parametrized and property tests (C-04, C-02, A-15); no mass migration | Parsed counts match the result bundle |
| P2-5 | Test adequacy: fakes that reach the code; ground-truth assertions; seam tests for the load coordinator and runtime; interleaving tests; a nightly shipped-configuration run (`-O` whole-module, TF32 on) as a report | Every fixed audit defect has a test that fails on revert |
| P2-6 | Strictness ratchet: package warnings as errors (tools 6.2); own `@preconcurrency` imports removed; SwiftLint in CI; migrate modes in a report-only job; MemberImportVisibility; the analyzer `check` wired | `@preconcurrency` from 35 to ≤ 24; package warnings 0 |
| P2-7 | Observability: marking, assembly and downloader signposts; one signpost file and one subsystem; `print` to `Logger`; macOS MetricKit; Main Thread Checker as a gate; a Metal System Trace profile kind and an MLX capture knob | No non-CLI `print`; the new intervals appear in `xctrace` exports |

### Phase 3: longer term

| ID | Item |
|---|---|
| P3-1 | CI moves to Xcode 27 with CONV-21; drop the `--build-system native` workaround once Swift Build produces the test bundle |
| P3-2 | `@Observable` (split `AudioPlayerViewModel` first), `NSLock` to `Mutex`, fewer `AnyView`, a lower concurrency-safety budget, vDSP only after measuring |
| P3-3 | NonisolatedNonsendingByDefault and strict memory safety, behind the UI stall gate; an Enhanced Security trial |
| P3-4 | Periphery, a Python type checker in CI, `checkJs` plus ESLint on the website (each new tool needs approval) |
| P3-5 | Lane orchestration moves from shell into tested Python modules; `swift test --repeat-until` for flaky hunting |

## KPIs

| KPI | Baseline | Target | Cheap measurement |
|---|---|---|---|
| Roadmap- or script-only `check` | about 75 s; 118 of 126 modules | under 20 s; ≤ 10 modules | `scripts/dev.sh check --dry-run --json` plus per-command timings |
| CI macOS deterministic job | 5-18 min; up to 1,458 files recompiled | p50 ≤ 8 min; p90 ≤ 200 files | `gh run view --log` ("test bundles built") |
| UI failed-minute share | 62% (lower bound) | ≤ 30%; infra ≤ 10% of runs | `run.json` scan now, the P1-1 ledger later |
| Release rehearsal | 32.5 min median; 28% failed | ≤ 20 min; ≤ 10% | `gh run list --workflow release-rehearsal.yml` |
| Bookkeeping share of commits | 54% | ≤ 30% | `git log --name-only` over a week |
| Startup context | 187 KB checkpoint; skill listing about 100k characters | ≤ 30 KB; ≤ 30k | `wc -c`; `/context` |
| Test adequacy | 13 of 150 reviewed; 10 risks mapped | ≥ 80%; every finding mapped | trailer grep; `validate_backend_risk_spine.py` |

## Sequencing traps

1. **The CI cache key ignores script flags.** Any xcodebuild-flag change (index store, optimization,
   debug format) makes the weekly snapshot stale, and every run until Monday recompiles about 1,400
   files. Land P0-9's rolling save, or a flag hash in the key, first. Take `project.yml` out of the key
   before turning on rolling saves, because the cache is near GitHub's cap.
2. **After October 23, every commit names a release item.** A picked tooling item is re-homed into the
   release plan, with at most two in flight.
3. **Before the submission, no build-setting, `Package.swift` or Swift-source change.** Dead-code
   stripping and package warnings-as-errors change the shipped binary.
4. **Migrate modes collide with project-wide warnings-as-errors.** Run them only in a report job with
   warnings-as-errors off, or with per-group control once the CI toolchain supports it.
5. **Swift Testing needs the parsers updated first, and the raw-xctest spike.** Otherwise a PASS can
   hide tests that never ran.
6. **NonisolatedNonsendingByDefault only behind the UI stall gate.** It can move work onto the caller's
   actor.
7. **New cache storage stays under `build/`.** Compilation caching included, it is registered in the
   build-output policy and known to `clean_build_caches.sh`; whole caches are never cleared.
8. **Measurement lineage.** Don't touch the optimized or CLI build flags while the RF-18 screen reuses
   its CLI by digest; a change to what is measured bumps the measurement version.
9. **Evidence rules hold.** No automatic retries of measured lanes and no deleting failed runs.
   Pass-rate KPIs separate infrastructure failures from product failures.
10. **Division of work.**
    - Agents take P0-1/2/3/5/6/7/11 and P1-3/6/7/8/9/12/13, each on disjoint files.
    - The lead validates lane-script refactors.
    - Changes to `ios_device.sh` wait for an announced iPhone window.
11. **Guard relaxations ship with a corpus test of true and false positives.** New linters arrive with
    a baseline and gate only changed files.
12. **The local arenas are cold (W-13).** The first native run is never a measurement.

## Highest return per hour

| Rank | Item | Hours | Return |
|---|---|---|---|
| 1 | P0-1 Python selection | 3-4 | About 55 s on each of 40-60 checks a week, plus agent cycles; the root cause is one line |
| 2 | P0-9 CI cache | 2-3 | Late-week Swift jobs from 13-18 min back to about 5 |
| 3 | P0-3 + P0-4 session start and checkpoint trim | 2 | About 47k tokens per session |
| 4 | P0-5 roadmap commands | 3-4 | About 50 hand edits a week |
| 5 | P0-2 swift-lane gap | 2 | Closes a silent hole where config and lane-script edits verify nothing locally |
| 6 | P0-6 guard false positives | 2-3 | Removes blocked turns for the lead and agents |
| 7 | P1-1 lane ledger | 4-6 | Prerequisite for the largest time sink (62% failed UI minutes) |
| 8 | P0-8 + P0-10 + P0-11 | 2 | Visible CI failures, untruncated skills, useful Python diagnostics |
