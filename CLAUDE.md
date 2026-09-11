# CLAUDE.md — Vocello (QwenVoice)

> Durable repository guidance for Claude Code. Code and machine-readable contracts win; repository
> scripts are the gates; skills, plugins, MCP servers, devices and models never are.
>
> **Plans:** [`docs/ROADMAP.md`](docs/ROADMAP.md) · **Narrative:** [`docs/development-progress.md`](docs/development-progress.md)
> · **Architecture:** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · **Map:** [`docs/project-map.html`](docs/project-map.html)
> · **Domain rules:** [`.claude/rules/`](.claude/rules/) (load by path; read the one that matches your files)

## Product and authority

**Vocello** is local-first Qwen3-TTS on MLX in Swift 6: a macOS app with an XPC engine service, an
iOS app with an in-process engine, the `vocello` CLI, Python automation and benchmarks, and a
React/Vite website. No bundled weights or cloud inference; approved assets download from Hugging Face
through the production catalog.

Source-of-truth order: `Sources/` → `project.yml` → machine-readable `config/` contracts → `scripts/`
→ `.github/workflows/` → `CLAUDE.md` and `.claude/rules/` → other prose. If source or a contract
invalidates documentation, fix the documentation in the same change. Check versions, hardware and
counts against `project.yml`, `config/public-product-facts.json` and `benchmarks/`; `candidateRelease`
tracks unpublished source and public links use `stableMacRelease`. Release only on explicit request.

Key contracts: speaker schema `Sources/Resources/qwenvoice_contract.json`; generated delivery source
`Sources/Resources/qwenvoice_production_model_catalog.json` with receipts `config/model-artifact-receipts.json`
and schema `config/model-catalog-schema-v2.json`; runtime phases `config/runtime-refactor-contract.json`;
backend risks `config/backend-risk-spine.json`.

Monetization is **iOS-only** (macOS and CLI have no paywall); export eligibility uses output provenance,
one StoreKit owner, one export boundary. UI language belongs to `IOSAppLanguage`, separate from speech
and reference languages; never mutate `AppleLanguages`. Details: `.claude/rules/ios.md`.

## Commands

```sh
scripts/dev.sh check [--dry-run]             # lint, contracts, selected tests, native lanes the dirty tree touches
scripts/dev.sh test | py | lint | ios        # one lane at a time while editing
scripts/dev.sh ci                            # exactly what push CI runs, serially
./scripts/regenerate_project.sh --fast       # after editing project.yml (never edit the .xcodeproj)
python3 scripts/roadmap.py status            # work authority: plans, items, primary plan
scripts/dev.sh regen                          # regenerate roadmap render, catalog, inventories, charts
scripts/macos_test.sh test                   # macOS unit + XPC + owned-runtime tests (no UI, no model)
./scripts/build_foundation_targets.sh ios --incremental  # generic device-SDK compile, no phone
npm --prefix website run check               # website lint + tests + build + browser smoke
```

Consent-bound lanes, never run unasked: `scripts/ui_test.sh <macos|ios> <lane>`, `scripts/ios_device.sh <verb>`,
`scripts/macos_test.sh memory|lang-bench`, `.github/workflows/release.yml`. See [Explicit frontend acceptance](#explicit-frontend-acceptance).

## Start and resume work

1. `git status --short --branch` (require local `main`; preserve dirty work), then
   `python3 scripts/roadmap.py status`. Follow `config/roadmap.json`'s `primaryPlan`; other plans keep
   defect/evidence authority, not competing queues. Read the "Resume now" section of
   `docs/development-progress.md`.
2. Read the matching domain rule, then only the subsystem references that change needs. Inspect the
   exact code, tests and contracts before choosing an implementation.
3. Make the smallest coherent change; preserve module boundaries and stable accessibility IDs.
4. Update affected contracts and instructions when behavior changes; refresh derived artifacts and
   update roadmap/narrative once per coherent checkpoint, not after every edit.

Claude Code is the development environment and scripts remain the gates. Work autonomously within the
requested scope with bounded, reversible changes; ask only for missing authority, consequential product
choices, external dependencies or unsafe ambiguity. Release, publication and device consent are always
explicit; ordinary checkpoints never need a model or a phone. Programme narrative:
[`docs/reference/release-first-execution-2026-09.md`](docs/reference/release-first-execution-2026-09.md).
Test and harness changes follow the
[replace-and-retire procedure](docs/reference/repository-self-verification.md#replace-and-retire-tests-and-harnesses)
and the [programme posture](.claude/rules/release-qa.md#programme-posture-and-harness-evolution) in the release-qa rule.

## Hard invariants

| Invariant | Required behavior |
| --- | --- |
| **Main only** | Develop and commit on local `main`; no other branches or worktrees, including experiments. Preserve dirty work. |
| **Physical iPhone only** | No Simulator build, launch or test. `build_foundation_targets.sh ios` is a phone-free generic compile; `scripts/lib/ios_platform_preflight.py check` only verifies the host. |
| **One UI driver** | `scripts/ui_test.sh` and checked-in XCUITest own native UI. Computer-use, browser, coordinate, vision, Mirroring and MCP UI routes never drive Vocello, even for diagnosis. |
| **Genuine controls** | No hidden markers, preview routes, seeded UI state or onboarding bypasses in shippable targets; test-only behavior lives in test targets. |
| **Generated project** | Edit `project.yml`, never `project.pbxproj`; run `scripts/regenerate_project.sh`. iOS resources use `sources:` with `buildPhase: resources`. |
| **Release-only configuration** | No Debug configuration or `DEBUG` symbol. Production overrides are registered in `config/runtime-debug-knobs.json` and need `VOCELLO_INTERNAL_DIAGNOSTICS` plus `QWENVOICE_DEBUG=1`; distribution omits the capability. |
| **Concurrency and MLX** | Register owned unsafe concurrency in `config/concurrency-safety.json`; prefer actors and immutable values. MLX arrays stay isolated; request-local randomness; owned wired-memory reservations; pins move in lockstep; no Core ML. |
| **One lifecycle authority** | Actor-owned lifecycle, typed cancellation, serialized prewarm, request-local memory/sampling, frame-bounded suspending audio, no audio-event eviction, classified-session finalization; phases in `config/runtime-refactor-contract.json`. |
| **One work authority** | `config/roadmap.json` owns status and generates `docs/ROADMAP.md`; the narrative checkpoint is not a second ledger. |
| **Privacy and language** | Never track PII, private paths, prompts, transcripts, credentials or raw diagnostics. Reference language stays separate from Clone output; explicit target language wins. |
| **Owned output** | `config/build-output-policy.json` owns `build/`, free-space floors and retention. Reuse `build/cache/xcode/{macos,macos-tsan,ios-device}`; no ad hoc DerivedData, bypassed preflights or whole-cache deletion. Vite owns `website/dist`. |
| **Scripts outrank assists** | Skills, plugins, devices, models, MCP servers and connectors never override scripts or become CI, commit or packaging prerequisites. |
| **Deterministic publication checkpoints** | Commits, pushes, PRs, CI, candidate signing, notarization, packaging, drafts and internal TestFlight need deterministic checks only; UI/model lanes need explicit QA scope; none authorizes a release. |
| **Exact-source releases** | Candidates need a GitHub-verified annotated tag on `origin/main` with green exact-SHA `CI required` (Security runs inside the release workflow); `scripts/release_source_authority.py` fails closed. |
| **Command-bound candidate evidence** | `release-evidence.json` and `release-verification.json` come from managed commands on a clean full-tree identity, checked against `config/apple-platform-capability-matrix.json`; reject partial, stale or cross-source PASS. |
| **Separate public promotion** | Public Mac release or external TestFlight/App Review needs exact-tag `quality-promotion.json` validated by `scripts/quality_promotion.py`. Device availability delays promotion, never candidate production. |
| **Evidence retention** | Only qualified privacy-safe PASS enters `benchmarks/runs/` (then regenerate `benchmarks/HISTORY.md`). Raw WAV, telemetry, screenshots, traces and xcresult stay untracked. Publishing never stages, commits or pushes. |
| **Ephemeral profiles** | Hash, validate and publish exact-PID summaries before deleting raw traces. Never treat current apps, canonical caches, dSYMs, models, source or tracked history as scratch. |
| **Qualified memory** | `config/memory-qualification-policy.json` owns thresholds: telemetry v8/manifest v2, sidecars, zero capture failures, ≥95% coverage, no critical-pressure or forced-unload event. |
| **Autonomous audio QA** | Listening is optional, never a gate. Fixed seeds, byte-bound PCM QC, locale-locked full-WAV ASR and prosody/delivery evidence are required; one ASR family repeated is not consensus. Prompt comparisons use a run-time frozen holdout judged by `scripts/delivery_promotion_decision.py` under `config/delivery-experiment-contract.json` guardrails; the `config/delivery-acoustic-reference-base.json` panel (pinned by `config/delivery-evaluator-v2-contract.json`) is context, not a verdict. |
| **Fresh derived artifacts** | `scripts/dev.sh regen` after changing their inputs. `docs/ROADMAP.md`, the production model catalog, the owned-package inventories and the README charts are generated, never hand-edited. |

## Domain routing

| Work | Rule | Reference | Canonical route |
| --- | --- | --- | --- |
| MLX engine, downloads, model catalog, delivery measurement | `.claude/rules/backend-mlx.md` | `docs/reference/mlx-guide.md`, `docs/reference/delivery-harness.md` | Owned runtime and backend contract scripts |
| iOS app and support code, localization | `.claude/rules/ios.md` | `docs/reference/ios-app-guide.md`, `docs/reference/localization.md` | Generic device-SDK compile; physical-device XCUITest only when requested |
| macOS app and XPC stack | `.claude/rules/macos.md` | `docs/reference/macos-app-guide.md` | `scripts/macos_test.sh`; native XCUITest only when requested |
| Scripts, CI, packaging, benchmarks, release | `.claude/rules/release-qa.md` | `docs/reference/repository-self-verification.md` | Repository scripts and workflows; the complete [gate map](.claude/rules/release-qa.md#deterministic-gate-map) |
| Generated inventories | `.claude/rules/derived-artifacts.md` | — | `scripts/dev.sh regen` |
| Hooks, skills, subagents, MCP routing | `.claude/rules/claude-tooling.md` | `docs/reference/development-workflow.md` | `scripts/repo_invariants.sh` |
| Website | `website/CLAUDE.md` | `website/PRODUCT.md`, `website/DESIGN.md` | Node contracts, Vite build, browser verification |

`./scripts/check_project_inputs.sh` is the T1/T2 gate. Read repository self-verification before adding
or weakening a gate; exemptions need a reason in `config/surface-coverage-exemptions.json`.

## Verification tiers

Run `scripts/dev.sh plan`, repeat `focused` while editing, then one `checkpoint` for the coherent tree
(`--full` for the complete deterministic gate). Serialize native Xcode commands (one SwiftPM lock spans
XCTest); parallelize read-only and Python work instead. Never clear caches to evade contention.

- **T0** fast generation, adjacent Python tests, changed XCTest classes.
- **T1** derived refresh, documentation and project-input contracts, affected Python tests, platform
  native checks. The commit hook accepts only a receipt for the same content and toolchain.
- **T2** full deterministic GitHub CI on every push and PR (`CI required` is the branch-protection context).
- **T3** explicit release evidence, signing, notarization, archive and artifact verification.

Commit coherent checkpoints on `main` and push after deterministic verification; this never authorizes
a release. Commit messages end with the attribution trailer the session provides.

<!-- BEGIN CLAUDE TOOLING -->

## Claude Code tooling (optional assists; verify before relying)

Repository-owned `.claude/` configuration (hooks, permissions, rules, skills, subagents) is covered by
the hook tests in `scripts/tests/`. User-scoped skills, plugins, MCP servers and devices are
never a prerequisite: scripts remain the gates. Details and routing: `.claude/rules/claude-tooling.md`.

| Task | Optional capability |
| --- | --- |
| Verify and commit, roadmap checkpoint | Project skills `/checkpoint`, `/roadmap-checkpoint`; long gate output via the `gate-runner` subagent |
| Device, macOS UI and release lanes | User-invoked skills `/ios-lane`, `/macos-ui-lane`, `/device-diagnostics`, `/release-evidence`; triage via `xcresult-triage` |
| Xcode inner loop | `xcodebuildmcp` skill with the shared XcodeBuildMCP server: `session_show_defaults`, then profile `macos` or `ios-device`; device id at runtime only; scratch builds; never Simulator, preview or UI routes |
| Apple frameworks and compiler behavior | `axiom-apple-docs`, Sosumi MCP, Xcode documentation |
| Swift, concurrency, testing, accessibility, payments, security | `axiom-*` skills and auditors; repository invariants win |
| Crashes and profiles | `axiom:crash-analyzer` (`xcsym`), `axiom:performance-profiler` (`xcprof`) for ad hoc traces; repository lanes own evidence |
| Build and environment diagnosis | `axiom-build` / `axiom:build-fixer`, with the repository caveat: no Simulator and no cache wipes outside `scripts/clean_build_caches.sh` |
| MLX/Qwen runtime | `mlx-swift`, `mlx-swift-lm` skills; checked-in catalogs and exact pins still win |
| GitHub, Hugging Face, App Store Connect, website | GitHub MCP or `gh`; Hugging Face connector or `hf`; `app-store-connect-cli` read-only by default; browser tooling only against the local website server |

Discover assists only when needed; verify a tool is callable before relying on it.

<!-- END CLAUDE TOOLING -->

## Hooks and commit lint

`.claude/settings.json` wires `PreToolUse` hooks: `scripts/hooks/commit_lint.sh` blocks a `git commit` off
`main`, with whitespace errors, or with a private path or credential in the staged files (under 15 s,
never a build); policy and generated-file guards block Simulator destinations, whole-cache deletion,
force pushes, new branches, direct `project.pbxproj` writes and hand edits of generated files. Nothing
else blocks a commit: run `scripts/dev.sh check` before pushing and let CI on `main` be the gate.
Personal overrides live in the untracked `settings.local.json` (untracked, under `.claude/`).

## Explicit frontend acceptance

Only explicit QA scope authorizes `scripts/ui_test.sh` or model/device lanes; follow
[the testing router](docs/reference/testing-runbook.md). iOS lanes need an Apple Development identity and
an unlocked paired iPhone; preserve all user data. Runner PASS requires diagnostics, crash deltas and
restoration, not just XCTest success; no retries, and a failed run keeps its artifacts. Zero observations
never authorize resume; changed source needs new run IDs. `scripts/ios_candidate_acceptance.py` guards the
preinstalled-candidate route; the [device procedure](docs/reference/ios-device-testing.md#pause-and-resume)
owns retention and resume.

## Security and release summary

macOS: protected tag → verified draft → notarized DMG via `.github/workflows/release.yml`. iOS: optional
TestFlight archive; identity from `project.yml`. Website: Vercel rooted at `website/`. Security posture in
`SECURITY.md`; complete boundaries in `docs/ARCHITECTURE.md` and `docs/reference/privacy-storage.md`.
