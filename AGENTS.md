# AGENTS.md — Vocello (QwenVoice)

> Durable repository guidance for Codex and other coding agents. Code and machine-readable
> contracts win over prose. Repository scripts are the gates; optional skills, plugins, MCP
> servers, devices, and models never are.
>
> **Plans:** [`docs/ROADMAP.md`](docs/ROADMAP.md) · **Current narrative:**
> [`docs/development-progress.md`](docs/development-progress.md) · **Architecture:**
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · **Project map:**
> [`docs/project-map.html`](docs/project-map.html) · **Domain rules:**
> [`.agents/rules/`](.agents/rules/)

## Product and authority

**Vocello** is a local-first text-to-speech application for Apple Silicon using Qwen3-TTS and
MLX with Swift 6. The checkout and Xcode project retain the historical `QwenVoice` name. The
repository ships a macOS app with an XPC engine, an iOS app with an in-process engine, the
`vocello` CLI, deterministic automation, benchmarks, and a React/Vite website. Supported targets
are macOS and iOS 26+. No model weights are bundled and no cloud inference is used; approved
artifacts download from Hugging Face through the complete production model catalog.

Current public facts are derived from `project.yml`, `config/public-product-facts.json`, and the
benchmark catalog. Do not hand-copy a release, build, hardware, preset, or speaker count without
checking those sources. Releases happen only on an explicit maintainer request.

Source-of-truth order:

`Sources/` → `project.yml` → machine-readable `config/` contracts → `scripts/` →
`.github/workflows/` → `AGENTS.md` and `.agents/rules/` → other prose.

The model/speaker schema is `Sources/Resources/qwenvoice_contract.json`. The complete fail-closed
delivery source for all six Speed/Quality artifacts is
`Sources/Resources/qwenvoice_production_model_catalog.json`; receipts and schema live in
`config/model-artifact-receipts.json` and `config/model-catalog-schema-v2.json`. If source or a
machine-readable contract invalidates documentation, update the documentation in the same change.

## Start and resume work

1. Run `git status --short --branch` and require the local branch to be exactly `main`, then run
   `python3 scripts/roadmap.py status`. If `main` cannot be checked out without risking existing
   work, stop and ask; do not continue implementation on another branch. Do not overwrite unrelated
   user changes.
2. Read `docs/development-progress.md` and confirm its checkpoint against the current checkout.
3. Read the applicable file under `.agents/rules/` and the authoritative subsystem reference.
4. Inspect the exact code, tests, and contracts before deciding on an implementation.
5. Select only skills and MCP tools relevant to the task. Read every selected `SKILL.md` completely
   before acting. Verify optional tools are currently callable.
6. Make the smallest coherent change. Preserve module boundaries and stable accessibility IDs.
7. Land source, tests, evidence, contracts, and narrative updates together. After a dense workstream,
   perform a documentation currency pass before starting another arc.

When task scope, target platform, or requested acceptance level is genuinely ambiguous, ask. The
default development checkpoint is deterministic verification; model downloads, a paired phone,
and UI evidence are never prerequisites for preserving ordinary work.

## Hard invariants

| Invariant | Required behavior |
| --- | --- |
| **Development work is `main`-only** | Start, resume, edit, validate, and commit directly on the local `main` branch. Never create, switch to, or continue implementation on another local branch. If returning to `main` is not safe, stop and ask instead of moving or discarding work. GitHub pull-request refs and detached CI checkouts remain valid execution contexts, but agents do not develop from them. |
| **iOS runtime and UI use a physical device** | Never select Simulator. XCUITest is the only autonomous native UI driver. `scripts/build_foundation_targets.sh ios` is a generic physical-device SDK compile and needs no phone; `scripts/lib/ios_platform_preflight.py check` verifies host platform support without downloading or starting a Simulator. |
| **XCUITest owns app UI** | Native macOS and iOS UI evidence comes only from `scripts/ui_test.sh` and the checked-in XCUITest targets. Computer-use, browser, coordinate, vision, simulator, and MCP UI automation never drive Vocello or substitute for XCUITest evidence. Computer-use may assist with the development environment only. |
| **No hidden test UI** | Tests observe genuine visible controls. Shippable targets contain no preview routes, invisible state markers, seeded UI state, or onboarding bypasses. Test-only behavior stays in test targets. |
| **`project.yml` owns the project** | Never hand-edit `QwenVoice.xcodeproj/project.pbxproj`. After manifest changes run `./scripts/regenerate_project.sh` and the project gate. iOS resources use `sources:` with `buildPhase: resources`. |
| **Release-only configuration** | There is no generic Debug configuration or `DEBUG` symbol. Production-affecting environment overrides must be registered in `config/runtime-debug-knobs.json` and remain inert unless `QWENVOICE_DEBUG=1` enables the master gate. |
| **Concurrency exceptions are registered** | Every owned `@unchecked Sendable`, `nonisolated(unsafe)`, or equivalent escape requires a justification in `config/concurrency-safety.json`. Prefer actors, `Mutex`, immutable adapters, and value types. Run `python3 scripts/runtime_security_contract.py`. |
| **MLX isolation and pins** | `MLXArray` is non-`Sendable`; keep arrays and lazy graphs inside one isolation domain, call `eval` deliberately, use request-local randomness, await low-level generation tasks after early stream exit, and coordinate active/reservation memory through wired-memory tickets. Move `mlx-swift` and `mlx-swift-lm` pins in lockstep. No Core ML backend. |
| **Engine authority is singular** | Preserve actor-owned lifecycle mutation, typed cancellation, prewarm-slot serialization, request-local sampling and memory policy, frame-bounded suspending audio delivery, non-eviction of audio-bearing events, and classified-session/product-finalization authority. `config/runtime-refactor-contract.json` is the sole phase-status authority. |
| **Roadmap state has one home** | `config/roadmap.json` owns plans and items and generates `docs/ROADMAP.md`; the runtime-refactor contract owns convergence phase status; `docs/development-progress.md` is narrative and cites both. Do not create another status ledger. |
| **Privacy is fail-closed** | No PII, device identity, usernames, absolute user paths, prompts, transcripts, secrets, private metadata, or unredacted diagnostics in tracked files or published evidence. |
| **Generated output has one policy** | `config/build-output-policy.json` owns native output under `build/`, cache placement, retention, and free-space floors. Persistent caches are `build/cache/xcode/{macos,ios-device}`. Never add ad hoc DerivedData or `.build` paths, bypass a preflight, or delete an entire cache when selective cleanup suffices. `website/dist` remains Vite-owned. |
| **Scripts are final authority** | Skills, plugins, MCP servers, Xcode integrations, browsers, GitHub, and Hugging Face tools are assists only. They are not CI, packaging, commit, or release prerequisites and never override repository scripts or contracts. |
| **Ordinary publication is deterministic-only** | Commits, pushes, PRs, ordinary merges, CI, signing, notarization, candidate packaging, draft artifacts, and internal TestFlight uploads require deterministic checks only. Frontend/model lanes run only for explicit QA or public promotion work. |
| **Public promotion is source-bound** | Making a macOS draft public or submitting an iOS candidate for external TestFlight/App Review requires `quality-promotion.json` validated by `scripts/quality_promotion.py` against the exact tag, release-evidence bytes, path-classified lanes, and privacy-safe hardware profiles. Device/model availability may delay public promotion but never candidate production. |
| **Release evidence is command-bound** | Release candidates require schema-v2 `release-evidence.json` and hashed `release-verification.json` produced by the contract-defined managed subprocess against a clean full-tree identity within the freshness window. Apple archive, entitlement, signing, and UUID continuity are checked against `config/apple-platform-capability-matrix.json`. Self-authored, substituted, partial, stale, or cross-source PASS files cannot authorize publication. |
| **Benchmark history is PASS-only** | Publish only privacy-safe, qualified PASS records under `benchmarks/runs/` and regenerate `benchmarks/HISTORY.md`. Raw audio, telemetry, screenshots, traces, and `.xcresult` bundles stay untracked. Publishing must never stage, commit, or push automatically. |
| **Profile traces are ephemeral** | Exact-PID traces are hashed, validated, summarized, and published before raw trace removal. Keep a trace only for an explicit Instruments session. Routine cleanup must not touch current apps, canonical caches, dSYMs, models, source, or tracked history. |
| **Memory evidence is qualified** | `config/memory-qualification-policy.json` owns thresholds. Publishable generation evidence requires telemetry schema v8 and benchmark manifest v2, run-scoped sidecars, lifecycle boundaries, zero capture failures, at least 95% sampler coverage, and no critical-pressure or forced-unload event. Do not add independent app and engine peaks. |
| **Audio QA is autonomous** | Ordinary promotion uses deterministic PCM QC, fixed seeds, locale-locked ASR consensus, and applicable prosody/delivery gates. Listening never waives a deterministic failure. A prompt change claiming improved semantic emotion/tone additionally needs the local blinded holdout in `config/delivery-experiment-contract.json`; this research decision is not an ordinary release prerequisite. `passedWithWarnings` is not promotion quality until a deterministic rule or implementation fix clears it. |
| **Documentation is governed** | Markdown under `docs/` and `.agents/rules/` carries metadata validated by `python3 scripts/doc_metadata.py validate`. Historical/superseded bodies are digest-pinned. Active facts come from `config/derived-doc-facts.json`. Delivery copy is checked by `scripts/check_delivery_instructions.py` against `config/delivery-instruction-contract.json`. Every enforced surface must be named in this file or a domain rule. |
| **Derived catalogs stay fresh** | Run `python3 scripts/refresh_derived_artifacts.py refresh` then `validate` when registered inputs change. This includes owned-runtime inventories/baselines, `docs/project-health.md`, `docs/INDEX.md`, `docs/INDEX.json`, `docs/ROADMAP.md`, derived facts, README charts, and the production model catalog. Narrative progress remains a deliberate manual update. |

Details for runtime, lifecycle, and event-channel invariants live in `docs/ARCHITECTURE.md`,
`config/runtime-refactor-contract.json`, `config/backend-risk-spine.json`, and the backend rule.

## Domain routing

| Work | Read first | Canonical route |
| --- | --- | --- |
| MLX, engine, downloads, model catalog | `.agents/rules/backend-mlx.md`, `docs/reference/mlx-guide.md` | Owned runtime and backend contract scripts |
| Delivery/emotion measurement | `.agents/rules/backend-mlx.md`, `docs/reference/delivery-harness.md` | Fixed protocol, provenance, statistics, and ledger |
| iOS app or support code | `.agents/rules/ios.md`, `docs/reference/ios-app-guide.md` | Generic device SDK compile; physical-device XCUITest only when requested |
| macOS app or XPC stack | `.agents/rules/macos.md`, `docs/reference/macos-app-guide.md` | macOS deterministic tests/build; native XCUITest only when requested |
| Scripts, CI, packaging, benchmarks | `.agents/rules/release-qa.md` | Repository scripts and workflows |
| Generated inventories | `.agents/rules/derived-artifacts.md` | `scripts/refresh_derived_artifacts.py` |
| Website | `website/AGENTS.md`, `website/PRODUCT.md`, `website/DESIGN.md` | Node contracts, Vite build, browser verification |
| Current external APIs | Relevant skill plus primary vendor docs | Sosumi/Apple docs, Context7, GitHub, or Hugging Face when callable |

### Deterministic gate map

`./scripts/check_project_inputs.sh` is the T1/T2 repository gate. Its enforced surfaces include:

| Check | Contract |
| --- | --- |
| `build_output_policy.py` | output ownership and storage floors |
| `cli_version_contract.py` | embedded CLI build identity and exact source-built version output |
| `saved_voice_lifecycle_contract.py` | transactional review, deletion, XPC, cache, and iOS accessibility surfaces |
| `documentation_contract.py`, `doc_metadata.py`, `check_surface_coverage.py` | links, lifecycle, facts, pinned bodies, and guidance completeness |
| `roadmap.py`, `project_health.py`, `evidence_impact.py` | work authority, health, and change-to-evidence mapping |
| `check_delivery_instructions.py` | delivery-copy parity and conflicts |
| `model_catalog_contract.py`, `vendor_runtime_contract.py` | production artifacts, owned-runtime inventory, and facade baseline |
| `runtime_security_contract.py`, `validate_backend_risk_spine.py` | debug/concurrency registries and backend risks |
| `check_convergence_promotion_gate.py` | convergence promotion preconditions |
| `check_qwen3_backend_only.sh`, `check_backend_resource_contract.sh` | MLX-only and native resource wiring |
| `check_test_workflows.sh` | one UI stack, retired-harness exclusion, and script self-tests |
| `python_test_contract.py` | discovery-complete Python inventory, runner compatibility, and zero-test rejection |
| `benchmark_history.py`, `supply_chain_contract.py`, `required_step_ledger.py`, `codex_session_storage.py`, `check_release_notes.py` | history, supply chain, release steps, task storage, and release-note contracts |

Exemptions require a reason in `config/surface-coverage-exemptions.json`. Read
`docs/reference/repository-self-verification.md` before adding or weakening a gate.

<!-- BEGIN OPTIONAL ASSISTS -->

## Optional assists (user-scoped; verify before relying)

User-scoped capabilities are outside the repository, so **no gate can validate this table**.
Confirm that a capability is callable and read its skill before use. Every entry is optional;
nothing here is a prerequisite for a commit, push, release, or acceptance result. Repository
scripts and domain rules remain authoritative.

| Task | Optional capability |
| --- | --- |
| Apple frameworks and compiler behavior | `axiom-apple-docs`; Sosumi or Xcode documentation search |
| Swift design, concurrency, data, networking, security, media, accessibility, testing | `axiom-swift`, `axiom-concurrency`, `axiom-data`, `axiom-networking`, `axiom-security`, `axiom-media`, `axiom-accessibility`, `axiom-testing` |
| Build/environment diagnosis | `axiom-build`; diagnose environment before source and never apply generic Simulator/cache-clean advice against repository policy |
| MLX/Qwen runtime | `swift-mlx`, `swift-mlx-lm`; exact checked-in catalogs and pins still win |
| Xcode inner loop | `axiom-xcode-mcp` plus XcodeBuildMCP: call `session_show_defaults`, select only `macos` or `ios-device`, set a physical device ID only at runtime, and never use its Simulator/UI automation routes |
| macOS implementation/release | Applicable `build-macos-apps:*` skills for build/debug, SwiftUI/AppKit, Liquid Glass, signing, notarization, telemetry, windows, and test triage |
| iOS SwiftUI implementation | Applicable `build-ios-apps:swiftui-*` skills; exclude simulator-centric debugger/browser workflows |
| GitHub context, CI, reviews, publication | `github:github`, `github:gh-fix-ci`, `github:gh-address-comments`, `github:yeet`; use `gh` when the connector is unavailable |
| Model repository/source research | Hugging Face connector and `hugging-face:hf-cli`; never infer production artifact identity from a live listing |
| Website inspection | `browser:control-in-app-browser`; Chrome only for explicitly needed signed-in state; computer-use never drives Vocello UI |
| Codex instructions, hooks, skills, or settings | `openai-docs` and current official OpenAI documentation |
| Current third-party library APIs | Context7, then primary vendor documentation |

Do not install an external plugin merely because it appears in a recommendation list. Install or
connect one only when the user requests it or an in-scope task genuinely requires unavailable
external data.

<!-- END OPTIONAL ASSISTS -->

## Codex and Xcode workflow

Repository hooks live in `.codex/hooks.json`. Project-local hooks are skipped until the exact
definition is reviewed and trusted with `/hooks`. The `PreToolUse` Bash hook calls
`scripts/hooks/precommit_gate.sh` and inspects `tool_input.command`. Before `git commit`, it rejects
any worktree whose symbolic branch is not exactly `main`, then runs
`QVOICE_GATES=quick ./scripts/check_project_inputs.sh`. Exit code 2 blocks either violation.
`QVOICE_SKIP_COMMIT_GATE=1` is an emergency one-shot validation bypass; it never bypasses the
`main`-branch requirement, and full CI still runs.

When XcodeBuildMCP is available:

1. Read `axiom-xcode-mcp` and call `session_show_defaults`.
2. Use repository profile `macos` for scheme `QwenVoice` or `ios-device` for scheme `VocelloiOS`.
3. Resolve a physical device identifier at runtime; never commit it.
4. Do not use Simulator, preview, or UI-automation routes for Vocello.
5. Treat repository scripts as the final build/test verdict.

## Verification tiers

```sh
./scripts/regenerate_project.sh                         # only after project.yml changes
python3 scripts/refresh_derived_artifacts.py refresh   # registered generated inputs changed
QVOICE_GATES=quick ./scripts/check_project_inputs.sh   # edit/checkpoint loop
scripts/macos_test.sh test                             # macOS core, XPC, owned runtime
./scripts/build.sh build                               # macOS compile
./scripts/build_foundation_targets.sh ios              # generic physical-device SDK compile
npm --prefix website run check                         # website changes
```

- **T0:** targeted typecheck and focused tests while editing.
- **T1:** the hook-enforced quick gate at every commit. Quick mode skips the longer Python
  self-test suite only when neither `scripts/` nor `config/` has pending changes.
- **T2:** full deterministic GitHub CI for every push/PR; path-aware jobs may skip while the
  aggregate required context remains authoritative.
- **T3:** explicit release evidence, signing, notarization, archive, and artifact verification.

Development is performed directly on `main`. Commit coherent checkpoints and push when
deterministic verification passes. Do not create feature, experiment, throwaway, or worktree
branches for repository development, including MLX pin work. If a task cannot be performed safely
on `main`, stop and ask rather than changing branches. Never release implicitly because roadmap
work landed.

### Explicit frontend acceptance

Only run these lanes when the user requests frontend/device acceptance:

```sh
scripts/ui_test.sh macos smoke|benchmark|perf
scripts/macos_test.sh gate

scripts/ios_device.sh preflight
scripts/ui_test.sh ios smoke|benchmark|perf
scripts/ui_test.sh ios saved-voice-lifecycle
scripts/ios_device.sh gate
```

iOS uses the paired physical iPhone only. The platform `gate` commands are device diagnostics and
do not consume XCUITest results. Model download and clone-enrollment UI lanes remain explicit,
isolated opt-ins documented in the platform rules.

## Key paths

| Path | Purpose |
| --- | --- |
| `Sources/QwenVoiceBackendCore/`, `Sources/QwenVoiceCore/` | backend vocabulary, engine, downloads, generation, telemetry |
| `Packages/VocelloQwen3Core/` | owned Qwen3-TTS/Mimi runtime and stable facade |
| `Sources/QwenVoiceNative/`, `Sources/QwenVoiceEngineService/`, `Sources/QwenVoiceEngineSupport/` | macOS XPC stack |
| `Sources/iOS/`, `Sources/iOSSupport/`, `Sources/SharedSupport/` | iOS app and shared player/persistence/transcription |
| `Tests/VocelloCoreTests/`, `Tests/VocelloEngineIntegrationTests/` | deterministic core and XPC tests |
| `Tests/UIAutomationSupport/`, `Tests/VocelloMacUITests/`, `Tests/VocelloiOSUITests/` | checked-in XCUITest stack |
| `Tests/VocelloiOSLogicTests/` | compile-only generic device-SDK policy contracts |
| `config/runtime-debug-knobs.json`, `config/concurrency-safety.json` | debug and concurrency exception registries |
| `config/model-management-diagnostics-schema-v1.json`, `scripts/check_ios_model_management.py` | correlated physical-iPhone model-delivery and progress diagnosis contract |
| `config/runtime-refactor-contract.json`, `config/roadmap.json` | convergence and work-state authorities |
| `config/language-bench-*.json` | language corpus and matrices |
| `benchmarks/`, `scripts/benchmark_history.py` | privacy-safe PASS registry and generated history |
| `scripts/ui_test.sh`, `scripts/macos_test.sh`, `scripts/ios_device.sh` | native test and diagnostic entry points |
| `docs/reference/model-delivery.md` | download/restoration/retry diagnostics and live-proof rules |
| `config/delivery-experiment-contract.json`, `config/delivery-evaluator-v2-contract.json`, `config/delivery-evaluation-corpus.json` | pre-registered prompt arms, compact local evaluator, sampling, multilingual scripts, holdouts, and semantic-promotion limits |
| `docs/reference/delivery-harness.md` | delivery/emotion protocol, provenance, layered evaluation, statistics, and results |
| `website/` | marketing site governed by `website/AGENTS.md` |

Full lanes: `docs/reference/macos-testing.md`, `docs/reference/ios-device-testing.md`,
`docs/reference/benchmarking-procedure.md`, and `.agents/rules/release-qa.md`.

## Security and release summary

- macOS: protected version tag → verified draft candidate → notarized DMG via
  `.github/workflows/release.yml`.
- iOS: optional TestFlight archive; version/build identity comes from `project.yml`.
- Website: Vercel deployment rooted at `website/`.
- Security: see `SECURITY.md`; macOS sandbox is disabled for MLX, iOS uses its declared App Group
  and increased-memory entitlement, and CI preserves immutable Action pins, dependency review,
  CodeQL, SBOMs, and build attestations.

Read `docs/ARCHITECTURE.md` and `docs/reference/privacy-storage.md` for the complete boundaries.
