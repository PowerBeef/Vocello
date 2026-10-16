# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Claude Code is the lead engineer on the existing local `main` checkout: it owns implementation,
verification and integration. Carry authorized work through to a reviewable result, make routine
engineering decisions, use the smallest meaningful checks, fix failures and commit scoped changes.
Pushes require an explicit request, including commits already waiting to be pushed. Preserve
unrelated edits and prior commits; stage explicit paths, never stash or broadly stage.

## Start here

1. The SessionStart hook prints branch/dirty state, open agent worktrees, `scripts/dev.sh status` and
   the **Resume now** head of `docs/development-progress.md`. Without it, run `git status --short
   --branch`, `git rev-parse HEAD`, `python3 scripts/roadmap.py status` and read **Resume now**.
   Reconcile overlapping changes before editing.
2. Domain rules load on demand: `.claude/rules/native.md` (Swift, packages, tests, `project.yml`) and
   `.claude/rules/tooling.md` (scripts, CI, config, evidence) are symlinks to
   `docs/reference/native-engineering.md` and `docs/reference/tooling-and-evidence.md`.
   `website/CLAUDE.md` loads for website work. Daily loop, agents and tool routing:
   `docs/reference/development-workflow.md`.
3. Inspect source and tests. Load relevant Axiom skills for Apple domains and the swift-mlx skills for
   runtime changes; load only what applies.
4. Implement, verify, review the actual diff and commit the assigned files on `main`. Substantive Swift
   changes get the `vocello-swift-review` agent; hooks, security, persistence and release changes get a
   focused review (`/code-review`, `/security-review`). Record larger unrelated work in the roadmap.
5. Report results, evidence and real limitations. Update the roadmap and checkpoint when status changes;
   do not create another task ledger.

## Product and authority

Vocello is local-first Qwen3-TTS on MLX in Swift 6. macOS and iOS host the runtime in-process; the
repository also owns the `vocello` CLI, Python tooling and the React/Vite website. No bundled weights
and no cloud inference. iOS is compile-safe only on `main`; the iOS app is iPhone-only.

Authority: `Sources/` → `project.yml` → `config/` contracts → `scripts/` → CI → this file and the
reference rules → other prose. Fix conflicting active prose in the same change.
`config/public-product-facts.json` and `project.yml` own public facts. `config/roadmap.json` owns open
work and `config/roadmap-archive.json` completed work; `docs/ROADMAP.md` is generated
(`python3 scripts/roadmap.py render`). `docs/ARCHITECTURE.md` traces ownership and lifecycles.

## Architecture

- **Targets** (`project.yml`, Release only, macOS/iOS 26.0, Swift 6, warnings as errors):
  `QwenVoice` (macOS app `Vocello.app`), `VocelloiOS` (module `QVoiceiOS`), `VocelloCLI` (`vocello`),
  static frameworks `QwenVoiceCore` (product engine) and `QwenVoiceBackendCore` (provenance/policy
  vocabulary), `VocelloCoreTests` (macOS host for core and iOS-logic tests), compile-only
  `VocelloiOSLogicTests`, and three XCUITest bundles. The macOS target compiles about 20 `Sources/iOS`
  files by path; that shared code, not a shared data folder, is the "shared store".
- **Layering:** `QwenVoiceBackendCore` ← `QwenVoiceCore` ← {apps, CLI}. Platform differences live only
  in the bootstraps (`MacEngineBootstrap`, `IOSAppBootstrap`, `CLIRuntime`), which all call
  `NativeRuntimeFactory.make`. Never reintroduce a separate engine process.
- **Generation flow:** view → coordinator (`StudioGenerationCoordinator`, attempt tokens) →
  `IOSSingleTakeGenerationExecutor` (the one short-form executor; long-form and Mac line batches have
  their own runners) → `TTSEngineStore.generate` (admission) → `MLXTTSEngine` (typed cancellation,
  `MLXModelLoadCoordinator`, prewarm/clone conditioning) → `VocelloQwen3Engine` actor in
  `Packages/VocelloQwen3Core` → bounded suspending PCM channel → limiter, atomic WAV writer, watermark,
  Fast QC → `GenerationPersistence` (outbox sidecar, idempotent GRDB commit). The CLI drives
  `MLXTTSEngine` directly.
- **Owned package** `Packages/VocelloQwen3Core` (SwiftPM name `MLXAudio`): a Qwen3-TTS-only fork. App code
  imports only the `VocelloQwen3Core` facade; `FACADE_API_BASELINE.json` and
  `scripts/qwen3_core_contract.py` enforce it. mlx-swift, mlx-swift-lm and swift-transformers pins are
  exact and move together only with authorization and benchmark review.
- **Model delivery:** `Sources/Resources/qwenvoice_contract.json` (models, speakers) and the generated
  production catalog (from `config/model-artifact-receipts.json`) carry exact sizes and SHA-256 digests.
  Hosts download, verify, then atomically activate complete artifacts; never infer checksums.
- **Audio quality:** three separate systems. In-app Fast QC ships with every take; QC v2
  (`scripts/qc.py`, `scripts/qc/`, `config/qc/`) is an offline, report-only harness whose `gate`
  exits 0 pass, 1 fail, 2 error, 3 warn, 4 NOT_ASSESSED; older prosody/delivery/clone gates remain.
  No automated score is a quality verdict. For 3.0 nobody listens (maintainer decision 2026-10-13):
  machine screens catch gross failures only, and subtle defects ship as a documented known limitation.
- **Website** (`website/`): React 19 + Vite SSR/prerender, Playwright acceptance, deployed by Vercel
  from Git. Its rules are in `website/CLAUDE.md`.

## Commands

```sh
scripts/dev.sh doctor --json          # read-only capabilities; no installs or downloads
scripts/dev.sh status
scripts/dev.sh check --dry-run --json # the routed plan check would run
scripts/dev.sh check                  # lint, contracts, selected tests, touched native lanes
scripts/dev.sh check --since <ref>    # also everything committed since <ref>
scripts/dev.sh check --paths <p...>   # only assigned paths when unrelated dirty work must wait
scripts/dev.sh test --only Class      # targeted XCTest; Class/testMethod and A,B also work
scripts/dev.sh py scripts/tests/test_x.py::Class::test_y   # selected pytest node ids
python3 -m pytest scripts/tests/test_x.py -k expr          # -k is not accepted by dev.sh py
scripts/dev.sh lint                   # changed-file advisory SwiftLint, shellcheck, privacy
scripts/dev.sh build | run            # warm incremental macOS development build / launch
scripts/dev.sh ios                    # generic device-SDK compile; no phone involved
scripts/dev.sh regen                  # project and derived artifacts
scripts/dev.sh triage <run-dir> --json  # summarize retained evidence without rerunning
./scripts/build.sh cli && build/vocello models list
npm --prefix website run check
scripts/hooks/commit_lint.sh --staged  # the commit safeguard, callable directly
```

Edit while running targeted deterministic tests; run the routed `check` before committing; at a coherent
checkpoint run the smallest relevant existing model, UI, device or performance lane. Adding, moving or
deleting Swift files needs `./scripts/regenerate_project.sh --fast` and the regenerated project in the
same commit. Local Xcode may be newer than the CI pin (`config/toolchain.json`); a local build does not
prove the pinned compiler accepts the change. Observe CI (`gh run watch` in the background) only after an
authorized push. For QC v2 use `"$(python3 scripts/select_python.py)" scripts/qc.py ...`.

## Hard boundaries

- **Release focus (until the 3.0 iOS submission):** the `focusLock` in `config/roadmap.json` makes
  `release-first-3-0-2026-09` the only plan with live work, at most two items in flight
  (`roadmap.py validate` enforces it).
  - **Classify every new finding.** A release blocker joins that plan with a due date. A release
    blocker is an App Review rejection risk, a crash or hang, data loss, a broken purchase or restore,
    or a privacy or metadata mismatch on iOS.
  - **Anything else** becomes one parked line in `post-3-0-backlog-2026-10`, with no investigation.
  - **Ask the maintainer** before starting work outside the plan, and open no new plans or audits.
  - **After the freeze**, every commit names a release item in its subject.

  Path, decisions and rules: `docs/reference/release-first-execution-2026-09.md`.
- **Main is the only published branch:** commit on local `main`; push only `main`, fast-forward, on
  explicit request. No hand-made branches or worktrees, ref rewrites or force pushes.
- **Agents:** at most four active including the lead, inheriting its model. Editing agents run through
  the Agent tool with `isolation: "worktree"` (`.claude/worktrees/<name>` on `worktree-<name>`, based on
  local HEAD; commit the checkpoint first because uncommitted files do not carry over). Give each a
  disjoint file set. Agents commit only on their branch, never push, never run native builds, devices,
  models or measured lanes, and never edit the roadmap or checkpoint; `agent_guard.py` enforces this
  for every call that carries an `agent_id`. The lead integrates with
  `git cherry-pick` or `git merge --ff-only`, validates warm on `main`, then runs `git worktree remove
  .claude/worktrees/<name>` and `git branch -d worktree-<name>`. Never discard unintegrated work.
- **Native execution:** every Xcode/SwiftPM build and test goes through the repository scripts and the
  host-wide native lock and owned caches. Join or stop agents before measurements.
- **Physical iPhone only:** generic iOS compilation is phone-free; Simulator routes are unsupported.
  After an Xcode update, every iPhone build waits on the matching iOS platform component (a
  multi-GB download: ask first; `scripts/lib/ios_platform_preflight.py check` reports it), and the
  phone may need UI automation allowed again ("Timed out while enabling automation mode").
- **One native UI driver:** repository XCUITest via `scripts/ui_test.sh`. No computer-use, coordinate,
  browser or MCP native UI driving; genuine shipped controls only, no hidden test UI.
- **Runtime:** MLX only, in-process, actor-owned lifecycle, typed cancellation barrier, serialized
  prewarm, request-local sampling and memory, suspending bounded audio. Register unsafe concurrency in
  `config/concurrency-safety.json`.
- **Release-only:** no Debug configuration or generic `DEBUG`. Production overrides need registered
  diagnostics, `VOCELLO_INTERNAL_DIAGNOSTICS` and `QWENVOICE_DEBUG=1`.
- **Generated project:** edit `project.yml` and source membership, never `project.pbxproj`; the shared
  generation signature controls regeneration.
- **iOS:** one StoreKit owner and export boundary; `IOSAppLanguage` owns interface language separately
  from generated speech; no macOS or CLI paywall; preserve accessibility identifiers and localization.
- **Evidence:** source-bound measurements use committed checkpoints, fixed seeds, compatible baselines,
  optimized-build receipts and memory qualification. Keep failed evidence; a justified rerun gets a new
  ID and explanation. Fast QC gates and report-only QC v2 differ. Cache-only audio analysis uses
  `check_cache_only_host` (records load without blocking, keeps worker and native-lock checks, makes no
  latency or memory claim).
- **Privacy:** no PII, private paths, prompts, transcripts, credentials or raw diagnostics in Git;
  persist failure summaries through `DiagnosticPrivacy`. Raw failures stay untracked.
- **Owned output:** `config/build-output-policy.json` owns caches and artifacts under `build/`; never
  clear whole caches to resolve contention (`scripts/clean_build_caches.sh` is selective).
- **Specific authorization:** new large downloads, model installs, dependency repins, global settings,
  releases, signing/publication, App Store or Vercel deployment and other external writes need a specific
  request. Local validation lanes are authorized; reuse installed assets. Tool availability is not
  authorization.

## Claude Code harness

- **`.claude/settings.json`** wires the repository guards from `scripts/hooks/`: `session_start.sh` and
  `worker_lifecycle.py` (SessionStart), `commit_lint.sh` and `policy_guard.sh` (Bash),
  `generated_file_guard.sh` (Edit/Write/MultiEdit/NotebookEdit), `agent_guard.py` (subagent Bash and
  edits), `simulator_tool_guard.py` (MCP tools),
  `project_yml_reminder.sh` (after edits) and `worker_lifecycle.py` (SubagentStart/Stop, SessionEnd).
  Permissions allow the routine loop and local lanes; ask before pushes, destructive git, model
  installs, cache cleanup, installers, global settings and external writes; deny force or non-main
  pushes, branch/worktree creation by hand, broad staging, stashing, releases, `.xcodeproj` edits and
  unsupported-destination MCP tools. Hooks and permissions are guardrails, not authorization; personal
  overrides go in the untracked `.claude/settings.local.json`. `scripts/tests/test_agent_hooks.py` pins
  the wiring.
- **Worker tracking:** the SessionStart hook exports `QVOICE_WORKER_SESSION` to Bash; measured lanes
  refuse unknown or active agent leases. If tracking is unavailable, join every agent, then run the lane
  with `QVOICE_LEAD_ONLY=1`.
- **Skills** (`.claude/skills`, invoked as `/vocello-*`): `vocello-ios-validation`, `vocello-macos-ui`,
  `vocello-device-diagnostics`, `vocello-benchmark`, `vocello-debug`, read-only
  `vocello-release-readiness`. They wrap the scripts and add no gate or permission.
- **Agents** (`.claude/agents`, read-only): `vocello-swift-review` for Swift diffs and
  `vocello-xcresult-triage` for a finished run directory. Explore/Plan and the Axiom auditor agents
  research and audit; editing agents are general-purpose agents with worktree isolation.
- **Tool routing:** repository scripts own builds, tests and evidence. Apple APIs: Axiom skills, the
  sosumi MCP and Xcode's bundled documentation; libraries: Context7; MLX: swift-mlx/swift-mlx-lm and
  `docs/reference/mlx-guide.md`. Retained crashes and traces: Axiom `xcsym`/`xcprof` (never `xcui` or
  simulator agents). MobileBuildMCP runs only its discovery and coverage workflows
  (`.mobilebuildmcp/config.yaml`; never persist session defaults into it).
  Website: Claude in Chrome or chrome-devtools for rendered inspection; Vercel deploys from Git and only
  its CLI remains (no Vercel plugin). CI and GitHub: `gh` and the GitHub connector, reads by default.
  Hugging Face: the `hf` CLI and the `hf-mcp-server` MCP (hub reads allowed; downloads, uploads, repo,
  Space and Job actions ask; `hf auth token` is denied). App Store Connect: the `asc` plugin skills
  over the Homebrew `asc` CLI. All of them stay read-only unless the user requests a write. Code
  navigation: the swift-lsp plugin. Use the Workflow tool only on explicit opt-in. Missing optional
  tools never block the script workflow, and CI never depends on personal plugins.
- **Interactive or maintainer-run commands** (logins, model installs, publication): prepare them and let
  the user run them with the `!` prefix.
