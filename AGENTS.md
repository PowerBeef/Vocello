# AGENTS.md

Antigravity is the lead engineer on local `main`: it owns implementation, verification and
integration. Carry authorized work to a reviewable result, run the smallest meaningful checks, fix
failures and commit scoped changes. Pushes need an explicit request (including queued commits).
Preserve unrelated edits and prior commits; stage explicit paths, never stash or broadly stage.

## Start here

1. `SessionStart` injects git status, open worktrees, `scripts/dev.sh status`, cache health and
   **Resume now** (`docs/development-progress.md`). Without it, run `git status --short --branch`,
   `git rev-parse HEAD`, `python3 scripts/roadmap.py status` and read **Resume now**.
2. Domain rules load via `.agents/plugins/vocello/rules/`: `native.md` →
   `docs/reference/native-engineering.md`; `tooling.md` → `docs/reference/tooling-and-evidence.md`.
   `website/AGENTS.md` loads for website work. Loop, CI, agents, hooks and routing:
   `docs/reference/development-workflow.md`.
3. Inspect source/tests; load only applicable Axiom skills (`axiom` MCP) or
   `docs/reference/mlx-guide.md`.
4. Implement, verify, review the diff and commit assigned files on `main`. Substantive Swift gets
   read-only `vocello-swift-review` (`--trailer 'Reviewed-by: vocello-swift-review'`); hooks,
   security, persistence and release edits get focused review.
5. Report results, evidence and limits. Update roadmap/checkpoint on status changes; no other ledger.

## Product and authority

Vocello is local-first Qwen3-TTS on MLX in Swift 6: in-process runtime on macOS and iOS, `vocello`
CLI, Python tooling and React/Vite website. No bundled weights or cloud inference. iOS is
compile-safe only on `main`, iPhone-targeted (`TARGETED_DEVICE_FAMILY=1`) while admitting eligible
8 GB+ iPads in portrait compatibility mode.

Authority: `Sources/` → `project.yml` → `config/` contracts → `scripts/` → CI → this file and
reference rules → other prose (fix conflicting active prose in the same change).
`config/public-product-facts.json` and `project.yml` own public facts; `config/roadmap.json` and
`config/roadmap-archive.json` own work (`roadmap.py set|note|close` validates/renders
`docs/ROADMAP.md`). `docs/ARCHITECTURE.md` traces ownership and lifecycles.

## Architecture

- **Targets** (`project.yml`, 15 targets, Release-only, macOS/iOS 26.0, Swift 6, strict memory
  safety, `NonisolatedNonsendingByDefault`, `InferIsolatedConformances`, `MemberImportVisibility`,
  warnings-as-errors except `VocelloiOSPurchaseUITests`): `QwenVoice`, `VocelloiOS` (`QVoiceiOS`),
  `VocelloCLI`; 6 static frameworks (`QwenVoiceBackendCore`, `QwenVoiceCore`,
  `VocelloSharedPolicies`, `VocelloiOSPolicies`, `VocelloDesktopCore`, `VocelloCLICore`); 2 unit-test
  and 4 XCUITest bundles (`docs/ARCHITECTURE.md` §1).
- **Layering:** `QwenVoiceBackendCore` ← `QwenVoiceCore` ← {`VocelloSharedPolicies`,
  `VocelloiOSPolicies`} ← hosts (`VocelloiOSPolicies` links only `VocelloiOS`, `VocelloCoreTests`,
  `VocelloiOSLogicTests`, zero link on macOS/CLI; `VocelloDesktopCore` ← `VocelloCLICore` ← CLI).
  Platform code lives only in bootstraps (`MacEngineBootstrap`, `IOSAppBootstrap.swift` /
  `QVoiceiOSApp.makeBackend`, `CLIRuntime`) calling `NativeRuntimeFactory.make`. Never reintroduce a
  separate engine process.
- **Generation flow:** view → `StudioGenerationCoordinator` → `IOSSingleTakeGenerationExecutor` →
  `TTSEngineStore.generate` → `MLXTTSEngine` → `VocelloQwen3Engine` actor (`Packages/VocelloQwen3Core`)
  → suspending PCM channel → limiter, atomic WAV, watermark, Fast QC → `GenerationPersistence`
  (outbox + GRDB). CLI shares `TTSEngineStore` via `DesktopEngineHost`; `bench` drives `MLXTTSEngine`.
- **Owned package** `Packages/VocelloQwen3Core` (`MLXAudio`): Qwen3-TTS-only fork; product code
  imports only `VocelloQwen3Core` (`scripts/qwen3_core_contract.py`). Exact `mlx-swift`,
  `mlx-swift-lm`, `swift-transformers` and `swift-huggingface` pins move only with authorization and
  benchmark review (`docs/reference/mlx-guide.md` §9).
- **Model delivery:** `qwenvoice_contract.json` and the generated production catalog
  (`qwenvoice_ios_model_catalog.json` + `config/model-artifact-receipts.json`) pin exact sizes and
  SHA-256 digests; hosts download, verify, then atomically activate.
- **Audio quality:** Fast QC gates takes. Offline QC v2 (`scripts/qc.py`, exit 0/1/2/3/4
  `NOT_ASSESSED`) and the separate `RF-72` Gemini 4 Neon multimodal complement (`scripts/qc.py
  multimodal`, `vocello-audio-qc`, outside QC v2 `SCORING_SOURCES`/Fast QC, blocking personal audio)
  are report-only. No score is a quality verdict; for 3.x nobody listens (2026-10-13;
  `docs/reference/tooling-and-evidence.md`, Audio QA).
- **Website** (`website/`): React 19 + Vite SSR/prerender, Playwright acceptance, Vercel Git deploy
  (`website/AGENTS.md`).

## Commands

```sh
scripts/dev.sh doctor --json             # read-only prerequisites; no installs/downloads
scripts/dev.sh status
scripts/dev.sh check [--dry-run --json]  # lint, contracts, selected tests, touched native lanes
scripts/dev.sh check --since <ref>       # include commits since <ref>
scripts/dev.sh check --paths <p...>      # gate only these paths while unrelated dirty work waits
scripts/dev.sh test --only Class[/test]  # targeted XCTest (A,B, --ios, --repeat N)
scripts/dev.sh py scripts/tests/test_x.py::Class::test_y
scripts/dev.sh qc <args...>              # QC v2 on pinned Python
"$(python3 scripts/select_python.py)" -m pytest scripts/tests/test_x.py -k expr
scripts/dev.sh build | run               # warm incremental macOS dev build / launch
scripts/dev.sh ios [--fast] [--ui]       # generic device-SDK compile (no phone; --fast -Onone)
scripts/dev.sh regen                     # derived artifacts (+ Xcode project when inputs changed)
scripts/dev.sh triage <run-dir> --json   # summarize retained evidence
```

More commands (lint, CLI, website, commit lint): `docs/reference/development-workflow.md` ("Daily
loop"). Run targeted tests while editing, `check` before committing, and the smallest relevant
model/UI/device/perf lane at checkpoints. Adding/moving/deleting Swift files requires
`./scripts/regenerate_project.sh --fast` in the same commit. Check `config/toolchain.json` when
local Xcode differs from CI; watch CI (`gh run watch`, backgrounded) only after an authorized push.
Measured lanes need `QVOICE_LEAD_ONLY=1` or `--lead-only` (before the subcommand on
`scripts/macos_test.sh`) after confirming zero active workers.

Lane notes:
- **UI lanes take over the Mac** (`scripts/ui_test.sh macos smoke|perf|benchmark`): announced window
  only, backgrounded (`WaitMsBeforeAsync: 500`, never `&`); run UI benchmark first in a sitting.
- **Refused benchmark takes stand** as product outcomes; seeds never move (2026-11-15).
- **Website checks need Playwright browsers** (`npm --prefix website exec playwright install chromium
  webkit`; download: ask). The `browser` subagent supplements, never replaces, `npm run check`.
- **iPhone Instruments (`xctrace`) needs wired USB** (`scripts/ios_device.sh profile --kind
  cpu|memory|metal|witness`; Wi-Fi drops Instruments). Multi-run `ui_test.sh --no-publish` needs
  `--retain-result`. Read `--help` before passing lane flags.

## Hard boundaries

- **Release focus:** `focusLock` in `config/roadmap.json` owns the active plan
  (`release-first-3-0-2026-09`), `maxInFlight`, freeze commit and release order (`SessionStart`
  injects live status; no target dates; no more 3.1 TestFlight builds).
  - **Classify findings:** release blockers (App Review risk, crash/hang, data loss, broken
    purchase/restore, iOS privacy/metadata mismatch) join the plan with a gate; everything else gets
    one parked line in `post-3-0-backlog-2026-10` without investigation.
  - **Sample-altering changes** need a pre-registered machine screen and self-test noise floor
    (`RF-57`).
  - **No-iPhone backlog items stay authorized** (closed in their fixing commit); Mac-only requests
    join the plan. Ask before other out-of-plan work; open no new plans or audits.
  - **Post-freeze commits** (`focusLock.freeze`) must name a release item in their subject.
  Rules: `docs/reference/release-first-execution-2026-09.md`.
- **Main is the only published branch:** commit on local `main`; push only `main`, fast-forward, on
  explicit request. No hand-made branches/worktrees, ref rewrites or force pushes. Release tags go
  through `python3 scripts/release_tag.py` (public `v<x.y.z>`) or
  `python3 scripts/ios_candidate_tag.py` (`v<x.y.z>-ios.<n>`) on explicit maintainer request after
  `main` is pushed and CI passes (both `force_ask`-gated).
- **Subagents and worktrees:** max 4 active including lead; editing workers inherit lead's model
  (read-only research may use a lighter tier). Lead stays on main checkout. Editing workers
  (`Workspace: "share"` / `swarm(..., workspace: "share")`) use registered `subagent-*`/`swarm-*`
  worktrees from a committed checkpoint on disjoint files, commit only on their branch, and never
  push, edit roadmap/checkpoint, or run builds/devices/models/measured lanes (`agent_guard.py`
  screens worktrees; read-only `"inherit"` prompts state they edit nothing). Lead integrates
  (`git cherry-pick` or `git merge --ff-only`), validates warm on `main`, and removes worktrees and
  branches (`git worktree remove`, `git branch -d`). Procedure:
  `docs/reference/development-workflow.md` ("Parallel agents and worktrees").
- **Native execution:** all Xcode/SwiftPM builds/tests use repo scripts, host-wide native lock and
  owned caches. Join/stop all workers before measurements.
- **Physical iPhone only:** automated device testing targets a paired physical iPhone; generic iOS
  compile is phone-free and Simulator routes are unsupported. After Xcode updates, iPhone builds
  need the matching iOS platform component (ask first; `scripts/lib/ios_platform_preflight.py check`)
  and UI automation re-enabled on the phone.
- **Every UI check is an XCUITest lane** via `scripts/ui_test.sh` (2026-11-17): genuine controls, no
  hidden test UI/coordinates, never `cua-driver`, quit iPhone Mirroring before phone lanes, review
  `<run>/screenshots/index.json`; system prompts/settings/purchases stay maintainer-by-hand
  (`docs/reference/development-workflow.md`).
- **Runtime:** MLX only, in-process, actor-owned lifecycle, typed cancellation barrier, serialized
  prewarm, request-local sampling/memory, suspending bounded audio. Register unsafe concurrency in
  `config/concurrency-safety.json`.
- **Release-only:** no Debug config or generic `DEBUG`. Overrides need registered knobs,
  `VOCELLO_INTERNAL_DIAGNOSTICS` and `QWENVOICE_DEBUG=1`. Shipping iOS builds also compile out
  dormant device/perf runners (`QVOICE_DEVICE_DIAGNOSTICS`) and `QWENVOICE_*` env reads (Guideline
  2.5.19; `verify_ios_release_artifacts.py`).
- **Generated project:** edit `project.yml` and source membership, never `project.pbxproj`; shared
  generation signature controls regeneration.
- **iOS:** one StoreKit owner and export boundary; `IOSAppLanguage` owns interface language apart
  from speech; no macOS/CLI paywall; preserve accessibility identifiers and localization.
- **Evidence:** committed checkpoints, fixed seeds, compatible baselines, optimized-build receipts
  and memory qualification. Keep failed evidence; reruns need a new ID and reason
  (`docs/reference/tooling-and-evidence.md`).
- **Privacy:** no PII, private paths, prompts, transcripts, credentials or raw diagnostics in Git;
  failure summaries go through `DiagnosticPrivacy`. Raw failures stay untracked.
- **Owned output:** `config/build-output-policy.json` owns `build/`; never clear whole caches for
  contention (`scripts/clean_build_caches.sh` is selective).
- **Specific authorization:** large downloads, model installs, dependency repins, global settings,
  releases, signing/publication, App Store/Vercel deploys and external writes need explicit request.
  Local validation lanes are authorized; tool availability is not authorization.

## Antigravity harness

`.agents/hooks.json` wires `scripts/hooks/agy_hook_adapter.py` to repo guards and the external-write
ask matrix (guardrails, not authorization). Full matrix and routing:
`docs/reference/development-workflow.md` ("Antigravity setup and tool routing").

- **Worker tracking:** Antigravity has no `SubagentStart`/`SubagentStop`/`SessionEnd` hooks and the
  sandbox blocks `ps`. Before measured/model/device lanes, confirm zero active workers
  (`manage_subagents list`, `swarm status`) and no other host sessions, then set `QVOICE_LEAD_ONLY=1`
  explicitly (never to bypass a live worker or unknown lease).
- **Workspace plugin** (`.agents/plugins/vocello/`): glob-triggered `rules/` (`native.md`,
  `tooling.md`), seven `vocello-*` `skills/`, read-only `agents/` (`vocello-swift-review`,
  `vocello-xcresult-triage`).
- **Reusable workflows** (`.agents/workflows/`): `swift_adversarial_review.py`,
  `xcuitest_visual_qa.py`, `debt_burndown_pipeline.py`, `qc_experiment_synthesizer.py`
  (`run_workflow`; no external-write authority).
- **Tool routing:** repo scripts own builds, tests and evidence. `mobilebuildmcp` runs
  discovery/coverage only (no `persist: true`, Simulator, build, LLDB or UI tools); `cua-driver` is
  denied; `axiom` supplies Apple skills, read-only auditors, `xcsym`, `xcprof` and `xclog` (no
  `xcui`/simulator agents); `vercel-plugin` does not authorize CLI deploys.
- **Artifacts, chat and maintainer commands:** keep raw diagnostics, private paths, prompts,
  transcripts, reference audio and credentials out of artifacts, screenshots and chat. Give
  interactive/maintainer-run commands (logins, model installs, publication) in a plain `sh` block;
  secrets stay in the maintainer's terminal.
