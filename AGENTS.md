# AGENTS.md

Antigravity is the lead engineer on the existing local `main` checkout: it owns implementation,
verification and integration. Carry authorized work through to a reviewable result, make routine
engineering decisions, use the smallest meaningful checks, fix failures and commit scoped changes.
Pushes require an explicit request, including commits already waiting to be pushed. Preserve
unrelated edits and prior commits; stage explicit paths, never stash or broadly stage.

## Start here

1. The `SessionStart` hook injects branch/dirty state, open agent worktrees, `scripts/dev.sh status`,
   cache health and the **Resume now** head of `docs/development-progress.md`. Without it, run
   `git status --short --branch`, `git rev-parse HEAD`, `python3 scripts/roadmap.py status` and read
   **Resume now**. Reconcile overlapping changes before editing.
2. Domain rules load on demand through `.agents/plugins/vocello/rules/`: `native.md` (Swift, packages,
   tests, `project.yml`) points to `docs/reference/native-engineering.md` and `tooling.md` (scripts,
   CI, config, evidence) points to `docs/reference/tooling-and-evidence.md`. `website/AGENTS.md`
   loads automatically for website work. The daily loop, CI, agents, hooks, guards and tool routing
   are in `docs/reference/development-workflow.md`.
3. Inspect source and tests. Load relevant Axiom skills (via the `axiom` MCP server) for Apple
   domains and MLX guidance (`docs/reference/mlx-guide.md`) for runtime changes; load only what applies.
4. Implement, verify, review the actual diff and commit the assigned files on `main`. Substantive Swift
   changes get the read-only `vocello-swift-review` subagent (recorded with
   `git commit --trailer 'Reviewed-by: vocello-swift-review'`); hooks, security, persistence and
   release changes get a focused security/code review. Record larger unrelated work in the roadmap.
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
(`python3 scripts/roadmap.py render`). Change items with `roadmap.py set|note|close`, which validate
and re-render in one call. `docs/ARCHITECTURE.md` traces ownership and lifecycles.

## Architecture

- **Targets** (`project.yml`, Release only, macOS/iOS 26.0, Swift 6, warnings as errors except the iOS
  UI-test bundle; strict memory safety, NonisolatedNonsendingByDefault, InferIsolatedConformances and
  MemberImportVisibility on): `QwenVoice` (macOS app `Vocello.app`), `VocelloiOS` (module
  `QVoiceiOS`), `VocelloCLI` (`vocello`); static frameworks `QwenVoiceCore` (product engine),
  `QwenVoiceBackendCore` (provenance/policy vocabulary), `VocelloDesktopCore` (the Mac app's UI-free
  History, settings, engine store, long-form and line-batch logic, compiled by path for the CLI) and
  `VocelloCLICore` (the CLI's runtime and parsing, which the tests import instead of compiling by
  path); `VocelloCoreTests` (macOS host for core and iOS-logic tests), compile-only
  `VocelloiOSLogicTests`, and three XCUITest bundles. The macOS app compiles about 20 `Sources/iOS`
  and `Sources/iOSSupport` files by path; that shared code, not a shared data folder, is the "shared
  store".
- **Layering:** `QwenVoiceBackendCore` ← `QwenVoiceCore` ← {apps, `VocelloDesktopCore` ←
  `VocelloCLICore` ← CLI}. Platform differences live only in the bootstraps (`MacEngineBootstrap`,
  `IOSAppBootstrap`, `CLIRuntime`), which all call `NativeRuntimeFactory.make`. Never reintroduce a
  separate engine process.
- **Generation flow:** view → coordinator (`StudioGenerationCoordinator`, attempt tokens) →
  `IOSSingleTakeGenerationExecutor` (the one short-form executor; long-form and Mac line batches have
  their own runners) → `TTSEngineStore.generate` (admission) → `MLXTTSEngine` (typed cancellation,
  `MLXModelLoadCoordinator`, prewarm/clone conditioning) → `VocelloQwen3Engine` actor in
  `Packages/VocelloQwen3Core` → bounded suspending PCM channel → limiter, atomic WAV writer, watermark,
  Fast QC → `GenerationPersistence` (outbox sidecar, idempotent GRDB commit). The CLI's product
  commands host `MLXTTSEngine` through the same store (`DesktopEngineHost`); `bench` drives it directly.
- **Owned package** `Packages/VocelloQwen3Core` (SwiftPM name `MLXAudio`): a Qwen3-TTS-only fork. App
  code imports only the `VocelloQwen3Core` facade; `FACADE_API_BASELINE.json` and
  `scripts/qwen3_core_contract.py` enforce it. The mlx-swift, mlx-swift-lm, swift-transformers and
  swift-huggingface pins are exact and move only with authorization and benchmark review (couplings:
  `docs/reference/mlx-guide.md` §9).
- **Model delivery:** `Sources/Resources/qwenvoice_contract.json` (models, speakers) and the generated
  production catalog carry exact sizes and SHA-256 digests. Its receipts come from the bundled iPhone
  catalog (`Sources/Resources/qwenvoice_ios_model_catalog.json`), plus
  `config/model-artifact-receipts.json` for a Mac-only artifact.
  Hosts download, verify, then atomically activate complete artifacts; never infer checksums.
- **Audio quality:** three separate systems. In-app Fast QC ships with every take; QC v2
  (`scripts/qc.py`, `scripts/qc/`, `config/qc/`) is an offline, report-only harness whose `gate`
  exits 0 pass, 1 fail, 2 error, 3 warn, 4 NOT_ASSESSED; older prosody/delivery/clone gates remain.
  No automated score is a quality verdict. For 3.x nobody listens (maintainer decision 2026-10-13):
  machine screens catch gross failures only, and subtle defects ship as a documented known limitation
  (detail: `docs/reference/tooling-and-evidence.md`, Audio QA).
- **Website** (`website/`): React 19 + Vite SSR/prerender, Playwright acceptance, deployed by Vercel
  from Git. Its rules are in `website/AGENTS.md`.

## Commands

```sh
scripts/dev.sh doctor --json          # read-only capabilities; no installs or downloads
scripts/dev.sh status
scripts/dev.sh check --dry-run --json # the routed plan check would run
scripts/dev.sh check                  # lint, contracts, selected tests, touched native lanes
scripts/dev.sh check --since <ref>    # also everything committed since <ref>
scripts/dev.sh check --paths <p...>   # plan, lint and gate only these paths while unrelated dirty work waits
scripts/dev.sh test --only Class      # targeted XCTest (also Class/testMethod and A,B); --repeat N hunts flakes
scripts/dev.sh py scripts/tests/test_x.py::Class::test_y   # selected pytest node ids
scripts/dev.sh qc <args...>           # QC v2 harness (scripts/qc.py) on the selected Python
"$(python3 scripts/select_python.py)" -m pytest scripts/tests/test_x.py -k expr  # -k: not in dev.sh py
scripts/dev.sh build | run            # warm incremental macOS development build / launch
scripts/dev.sh ios                    # generic device-SDK compile; no phone involved
scripts/dev.sh regen                  # derived artifacts, and the project when its inputs changed
scripts/dev.sh triage <run-dir> --json  # summarize retained evidence without rerunning
```

The rest of the loop (lint, the CLI build, the website check, the commit lint called directly) is in
`docs/reference/development-workflow.md`, "Daily loop".

Edit while running targeted deterministic tests; run the routed `check` before committing; at a coherent
checkpoint run the smallest relevant existing model, UI, device or performance lane. Adding, moving or
deleting Swift files needs `./scripts/regenerate_project.sh --fast` and the regenerated project in the
same commit. Local Xcode may be newer than the CI pin (`config/toolchain.json`); a local build does not
prove the pinned compiler accepts the change. Observe CI (`gh run watch` in the background) only after an authorized push. For QC v2 use
`scripts/dev.sh qc ...` (which selects the pinned Python automatically). For measured lanes pass
`--lead-only` (or `QVOICE_LEAD_ONLY=1`) after confirming zero active workers.

Lanes, learned on the 3.1 run (2026-11-14):

- **UI lanes take over the Mac** (`scripts/ui_test.sh macos smoke|perf|benchmark`): run them only in a
  window the maintainer gives, backgrounded via the tool's async execution (`WaitMsBeforeAsync: 500`,
  never shell `&`).
- **In a release sitting, the most failure-prone lane runs first** (the UI benchmark).
- **A benchmark take the audio check refuses is a product outcome.** It stands, and the seeds never
  move for it (decision of 2026-11-15).
- **The website check needs Playwright's browsers** (`npx playwright install chromium webkit`, a
  download: ask). The `browser` subagent is a stand-in, not the verdict.
- **Read a lane's `--help` before passing options.**

## Hard boundaries

- **Release focus (until the 3.1 iOS submission; the Mac and CLI 3.1 ship first, RF-61):** the
  `focusLock` in `config/roadmap.json` makes `release-first-3-0-2026-09` the only plan with live work,
  at most `focusLock.maxInFlight` items in flight (`roadmap.py validate` enforces it).
  `focusLock.decision` is the authority for the order and the gates: no target dates, and the core
  overhaul and the output-quality remediation come before the iOS submission.
  - **Classify every new finding.** A release blocker joins that plan with a gate: an App Review
    rejection risk, a crash or hang, data loss, a broken purchase or restore, or a privacy or metadata
    mismatch on iOS. Anything else becomes one parked line in `post-3-0-backlog-2026-10`, with no
    investigation.
  - **A change that alters samples** lands only behind a machine screen whose decision rule is recorded
    before its takes are generated, and a screen is first run against itself, so its noise floor is
    known (RF-57).
  - **Backlog items that need no iPhone stay authorized**, each closed in the change that fixes it,
    and a Mac-only request joins the plan as an item. Ask the maintainer before any other work outside
    the plan, and open no new plans or audits.
  - **Every commit after the recorded freeze** (`focusLock.freeze`) names a release item in its subject.

  Path, decisions and rules: `docs/reference/release-first-execution-2026-09.md`.
- **Main is the only published branch:** commit on local `main`; push only `main`, fast-forward, on
  explicit request. No hand-made branches or worktrees, ref rewrites or force pushes. Release tags are
  maintainer-run, except an iPhone TestFlight candidate: on the maintainer's request, after `main` is
  pushed and its CI passed, `python3 scripts/ios_candidate_tag.py` signs and pushes the next
  `v<version>-ios.N` tag, whose push archives the app and uploads it to TestFlight.
- **Subagents and worktrees:** at most four active including the lead. Editing subagents inherit the
  lead's model; read-only research subagents may use a lighter one. The lead works in the main
  checkout, never in a worktree. An editing subagent (`invoke_subagent(..., Workspace: "share")` or
  `swarm(..., workspace: "share")`) works in its own registered linked worktree (`subagent-*` or
  `swarm-*` branch) from a committed checkpoint, on a disjoint file set. Subagents commit only on
  their branch, never push, never run native builds, devices, models or measured lanes, and never edit
  the roadmap or checkpoint. `agent_guard.py` screens every call whose `cwd` is a linked worktree (a
  guardrail, not a sandbox); a read-only subagent sharing the main checkout (`Workspace: "inherit"`)
  must state in its prompt that it edits nothing. The lead integrates with `git cherry-pick` or
  `git merge --ff-only`, validates warm on `main`, then removes the worktree (`git worktree remove`)
  and branch (`git branch -d`; note `manage_subagents kill` does not delete `share` worktrees). Never
  discard unintegrated work. Procedure: `docs/reference/development-workflow.md`, "Parallel agents and
  worktrees".
- **Native execution:** every Xcode/SwiftPM build and test goes through the repository scripts and the
  host-wide native lock and owned caches. Join or stop all subagents before measurements.
- **Physical iPhone only:** generic iOS compilation is phone-free; Simulator routes are unsupported.
  After an Xcode update, every iPhone build waits on the matching iOS platform component (a multi-GB
  download: ask first; `scripts/lib/ios_platform_preflight.py check` reports it), and the phone may
  need UI automation allowed again ("Timed out while enabling automation mode").
- **Every UI check is an XCUITest lane** via `scripts/ui_test.sh` (maintainer decision 2026-11-17,
  which retires computer-use / GUI-driver / iPhone Mirroring routes): genuine shipped controls, no
  hidden test UI or committed coordinates, and a check no lane covers gets its own scenario. Never use
  `cua-driver` for Vocello app or website UI checks. The iPhone runs only in an announced window, with
  iPhone Mirroring quit (XCUITest breaks under it). What XCUITest cannot drive (iPhone system settings,
  permission prompts, the passcode, audio routing, VoiceOver, purchase confirmations, macOS privacy
  grants) is the maintainer's, by hand. Review each lane's screenshots (`<run>/screenshots/index.json`).
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
  ID and explanation. Fast QC gates and report-only QC v2 differ. Host preflight, cache-only analysis
  and publication rules: `docs/reference/tooling-and-evidence.md`.
- **Privacy:** no PII, private paths, prompts, transcripts, credentials or raw diagnostics in Git;
  persist failure summaries through `DiagnosticPrivacy`. Raw failures stay untracked.
- **Owned output:** `config/build-output-policy.json` owns caches and artifacts under `build/`; never
  clear whole caches to resolve contention (`scripts/clean_build_caches.sh` is selective).
- **Specific authorization:** new large downloads, model installs, dependency repins, global settings,
  releases, signing/publication, App Store or Vercel deployment and other external writes need a specific
  request. Local validation lanes are authorized; reuse installed assets. Tool availability is not
  authorization.

## Antigravity harness

`.agents/hooks.json` wires `scripts/hooks/agy_hook_adapter.py`, which delegates to the repository
guards in `scripts/hooks/` and enforces the hard-deny and external-write ask matrix. Hooks are
guardrails, not authorization: every write through an optional tool (plugins, MCP servers, `browser`,
`gh`, `hf`, `asc`, the Vercel CLI) needs an explicit request. The hook matrix, guard rules, sandbox
notes and tool-routing table live in `docs/reference/development-workflow.md`, "Antigravity setup and
tool routing".

- **Worker tracking:** Antigravity does not expose `SubagentStart`/`SubagentStop`/`SessionEnd` hooks
  or `CLAUDE_ENV_FILE`, and the default terminal sandbox blocks `ps`. Before any measured/model/device
  lane, verify zero active workers (`manage_subagents list`, `swarm status`) and confirm no other host
  sessions are active in this repository, then declare `QVOICE_LEAD_ONLY=1` explicitly. Never use
  `QVOICE_LEAD_ONLY=1` to bypass a known active worker or unknown lease.
- **Workspace plugin** (`.agents/plugins/vocello/`):
  - **Domain rules (`rules/`):** glob-triggered `native.md` and `tooling.md`.
  - **Skills (`skills/`):** `vocello-ios-validation`, `vocello-macos-ui`, `vocello-device-diagnostics`,
    `vocello-benchmark`, `vocello-debug`, read-only `vocello-release-readiness`. They wrap the scripts
    and add no gate or permission.
  - **Read-only subagents (`agents/`):** `vocello-swift-review` for Swift diffs and
    `vocello-xcresult-triage` for a finished run directory. Editing subagents use
    `invoke_subagent(..., Workspace: "share")`.
- **Tool routing:** repository scripts own builds, tests and evidence. `mobilebuildmcp` runs only its
  project-discovery and coverage tools (never `persist: true`, never Simulator/build/UI tools, even if
  global env exposes them). `cua-driver` is denied. `axiom` MCP supplies Apple skills, read-only
  auditors, `xcsym`, `xcprof` and `xclog` (never `xcui` or simulator agents). `vercel-plugin` does not
  authorize Vercel CLI deploys; Vercel deploys from Git. Missing optional tools never block scripts.
- **Artifacts and chat:** artifacts, screenshots and notifications carry no raw diagnostics, private
  paths, prompts, transcripts, reference audio or credentials.
- **Interactive or maintainer-run commands** (logins, model installs, publication): prepare them in a
  plain `sh` block for the maintainer to run in their terminal; any secret is typed there, never in chat.
