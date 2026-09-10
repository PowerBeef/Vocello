# AGENTS.md — Vocello (QwenVoice)

> Durable repository guidance. Code and machine-readable contracts win; repository scripts are
> the gates; optional assists, devices, and models never are.
>
> **Plans:** [`docs/ROADMAP.md`](docs/ROADMAP.md) · **Current narrative:**
> [`docs/development-progress.md`](docs/development-progress.md) · **Architecture:**
> [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) · **Project map:**
> [`docs/project-map.html`](docs/project-map.html) · **Domain rules:**
> [`.agents/rules/`](.agents/rules/)

## Product and authority

**Vocello** is local-first Qwen3-TTS/MLX in Swift 6: macOS/XPC, iOS/in-process, `vocello` CLI,
automation, benchmarks and React/Vite website. No bundled weights or cloud inference;
approved assets download from Hugging Face through the production catalog.

Check version, hardware and counts against `project.yml`, `config/public-product-facts.json` and benchmarks.
`candidateRelease` tracks unpublished source; public links use `stableMacRelease`. Release only on explicit request.

Monetization and App Store submission are **iOS-only**. macOS remains distributed through GitHub
Releases, with no purchase/export restrictions; the CLI likewise gains no paywall. Shared code
must not make macOS/CLI generation or export depend on an iOS StoreKit entitlement.

iOS export eligibility uses output provenance, never the current Studio mode. Keep one StoreKit
owner and one outward-export boundary; no paid preference flag or diagnostics unlock. Generation,
internal History/playback, personal-reference recovery and actual failed-storage recovery stay free.
Local StoreKit fixtures never enter shipping app resources or authorize live purchases/account edits.

iOS interface language belongs to `IOSAppLanguage`, independently of generated-speech and reference
languages. Resolve app-owned copy through the existing catalog/context; never mutate `AppleLanguages`,
swizzle bundles, recreate the application root, translate model-facing text or reformat StoreKit prices.
Offer only complete bundled locales; catalog completeness does not replace physical layout acceptance.

Source-of-truth order:

`Sources/` → `project.yml` → machine-readable `config/` contracts → `scripts/` →
`.github/workflows/` → `AGENTS.md` and `.agents/rules/` → other prose.

The model/speaker schema is `Sources/Resources/qwenvoice_contract.json`. The complete fail-closed
delivery source for all six Speed/Quality artifacts is
`Sources/Resources/qwenvoice_production_model_catalog.json`; receipts and schema live in
`config/model-artifact-receipts.json` and `config/model-catalog-schema-v2.json`. If source or a
machine-readable contract invalidates documentation, update the documentation in the same change.

## Start and resume work

1. Run `git status --short --branch`, require local `main`, then `python3 scripts/roadmap.py status`.
   Stop if returning to `main` risks existing work; preserve unrelated changes.
2. Verify `docs/development-progress.md`; follow `config/roadmap.json`'s `primaryPlan`.
   Other plans retain defect/evidence authority, not competing work queues.
3. Read the applicable domain rule, then only the subsystem references needed for this change.
4. Inspect the exact code, tests, and contracts before deciding on an implementation.
5. Read every selected skill completely and verify optional tools are callable.
6. Make the smallest coherent change. Preserve module boundaries and stable accessibility IDs.
7. Update affected instructions/contracts when behavior changes. Refresh derived documents and
   update roadmap/narrative once per coherent checkpoint, not after each edit or diagnostic.

Codex is the development environment; agent/model selection is not a quality gate. Proceed
autonomously with bounded, reversible implementation and relevant verification within the requested
scope. Do not simulate separate team-role approvals. Ask only for missing authority, consequential
product choices, external dependencies or unsafe ambiguity; preserve explicit release/device consent.

Clarify ambiguous scope. Ordinary checkpoints need deterministic checks, never models or a phone.

### Release-first execution

Follow [`docs/reference/release-first-execution-2026-09.md`](docs/reference/release-first-execution-2026-09.md)
iOS-first: defer Mac/CLI-only qualification. Keep all modes, long-form and the 201-take gate.
Use retained evidence; stop after two predeclared experiments per finding for a decision checkpoint.
No broad harness work. Serialize heavy work; verify focused changes then the tree.
Freeze source/docs during campaigns; checkpoint runs untracked. Implementation, instrumented QA,
processed-candidate proof and submission approval differ. Keep external dependencies explicit.

### Evidence-led test and harness evolution

Apply this across unit/integration/UI tests, audio evaluators, performance tools and CI/release
validators. Existing code/contracts govern execution, not unquestionable correctness; neither age,
version, model reputation nor a green suite makes an implementation a gold standard. Validate the
intended behavior independently, including real producer/consumer boundaries and known bad inputs.
Prefer one current implementation; retain compatibility only for identified consumers or evidence
with an explicit retirement condition. Version persisted/public contracts or changed measurement
meaning, not routine refactors. Preserve user data and original evidence, not known bugs or
unsupported verdicts. Use the [replacement and retirement procedure](docs/reference/repository-self-verification.md#replace-and-retire-tests-and-harnesses)
within existing roadmap items; no blanket rewrite, parallel harness or silent gate waiver.

The delivery cascade's default `config/delivery-acoustic-reference-base.json` panel is pinned by
`config/delivery-evaluator-v2-contract.json` and consumed by `scripts/delivery_acoustic_reference.py`.
It is descriptive context, not good/bad speech labels or a release gate; preserve warnings and missing
coverage. The existing [Audio QC procedure](docs/reference/audio-qc-engineering.md#default-acoustic-reference-base)
owns reference comparison and update instructions.

## Hard invariants

| Invariant | Required behavior |
| --- | --- |
| **Main only** | Develop and commit on local `main`; never create/use another development branch, including experiments. Preserve dirty work; stop if returning to main risks it. Detached CI/PR execution is not agent development. |
| **Physical iPhone only** | No Simulator build, launch or runtime/UI tests. `scripts/build_foundation_targets.sh ios` is a no-phone generic device-SDK compile; `scripts/lib/ios_platform_preflight.py check` only verifies host support. |
| **One UI driver** | `scripts/ui_test.sh` and checked-in XCUITest own native macOS/iOS UI. Computer-use, browser, coordinate, vision, Mirroring and MCP UI routes never drive Vocello, even for diagnosis. Environment assistance only. |
| **Genuine controls** | No hidden markers, preview routes, seeded UI state or onboarding bypasses in shippable targets. Test-only behavior stays in test targets; preserve accessibility IDs. |
| **Generated project** | Edit `project.yml`, never `QwenVoice.xcodeproj/project.pbxproj`; run `scripts/regenerate_project.sh` and the project gate. iOS resources use `sources:` with `buildPhase: resources`. |
| **Release-only configuration** | No generic Debug configuration or `DEBUG` symbol. Production overrides require registration in `config/runtime-debug-knobs.json`, `VOCELLO_INTERNAL_DIAGNOSTICS` and `QWENVOICE_DEBUG=1`; distribution omits the capability. |
| **Concurrency and MLX** | Register owned unsafe concurrency in `config/concurrency-safety.json`; prefer actors/Mutex/immutable values. Keep non-Sendable MLX arrays/lazy graphs isolated, evaluate deliberately, use request-local randomness, await low-level tasks after early stream exit, and own wired-memory reservations. Move MLX pins in lockstep; no Core ML. |
| **One lifecycle authority** | Actor-owned lifecycle, typed cancellation, serialized prewarm, request-local memory/sampling, frame-bounded suspending audio, no audio-event eviction and classified-session finalization remain intact. `config/runtime-refactor-contract.json` owns phase status. |
| **One work authority** | `config/roadmap.json` owns status and generates `docs/ROADMAP.md`; the current checkpoint is narrative, not another ledger. |
| **Privacy and language** | Never track PII, private paths, prompts, transcripts, credentials or raw diagnostics. Shared enrollment keeps reference language separate from Clone output; explicit target language wins. |
| **Owned output** | `config/build-output-policy.json` owns `build/`, free-space floors and retention. Reuse `build/cache/xcode/{macos,macos-tsan,ios-device}`; no ad hoc DerivedData/.build roots, bypassed preflights or whole-cache deletion when selective cleanup suffices. Vite owns `website/dist`. |
| **Scripts outrank assists** | Skills, plugins, devices, models, MCP and external connectors never override scripts or become ordinary CI/commit/packaging prerequisites. |
| **Deterministic publication checkpoints** | Commits, pushes, PRs, ordinary merges/CI and candidate signing/notarization/packaging/draft/internal TestFlight require deterministic checks only. UI/model lanes need explicit QA/public-promotion scope. None grants release authorization. |
| **Exact-source releases** | Candidates/promotion require a GitHub-verified annotated tag in `origin/main` and successful latest exact-SHA `CI required` + `Security required`; `scripts/release_source_authority.py` fails closed. |
| **Command-bound candidate evidence** | Schema-v2 `release-evidence.json` and hashed `release-verification.json` come from managed commands on a clean, fresh full-tree identity. Verify Apple signing/entitlements/UUIDs against `config/apple-platform-capability-matrix.json`; reject fabricated, partial, stale or cross-source PASS. |
| **Separate public promotion** | Public Mac release or external TestFlight/App Review requires exact-tag `quality-promotion.json`, release bytes, applicable lanes and privacy-safe hardware profiles validated by `scripts/quality_promotion.py`. Device availability may delay promotion, never candidate production. |
| **Evidence retention** | Only qualified privacy-safe PASS enters `benchmarks/runs/`; regenerate `benchmarks/HISTORY.md`. Raw WAV/telemetry/screenshots/traces/xcresult stay untracked. Publishing evidence never stages/commits/pushes automatically. |
| **Ephemeral profiles** | Hash, validate and publish exact-PID summaries before deleting raw traces; retain raw only for explicit Instruments work. Never clean current apps, canonical caches, dSYMs, models, source or tracked history as scratch. |
| **Qualified memory** | `config/memory-qualification-policy.json` owns thresholds. New evidence requires telemetry v8/manifest v2, run sidecars/boundaries, zero capture failures, ≥95% coverage and no critical-pressure/forced-unload event. Never add unrelated app/engine peaks. |
| **Autonomous audio QA** | Human listening is optional, never a required gate. Require fixed seeds, byte-bound native PCM QC, locale-locked full-WAV ASR and applicable prosody/delivery evidence. Repetitions of one ASR family are repeatability, not independent consensus. Missing, partial, contradictory or uncalibrated evidence stays inconclusive; warnings need a governed correction before clean promotion. Prompt comparisons use the frozen automated holdout in `config/delivery-experiment-contract.json` and support named measured claims, not listener-proven improvement. Listening never waives deterministic failure. |
| **Governed documentation** | `scripts/doc_metadata.py validate` checks metadata and pinned historical/superseded bodies. Active facts derive from `config/derived-doc-facts.json`; delivery copy from `config/delivery-instruction-contract.json`. Every enforced surface stays named here or in a domain rule. |
| **Fresh derived artifacts** | Run `scripts/refresh_derived_artifacts.py refresh` then `validate` for changed registered inputs. Catalogs, inventories/baselines, health, indexes, roadmap, facts and README charts are generated; narrative updates are deliberate. |

Details for runtime, lifecycle, and event-channel invariants live in `docs/ARCHITECTURE.md`,
`config/runtime-refactor-contract.json`, `config/backend-risk-spine.json`, and the backend rule.

## Domain routing

| Work | Read first | Canonical route |
| --- | --- | --- |
| MLX, engine, downloads, model catalog | `.agents/rules/backend-mlx.md`, `docs/reference/mlx-guide.md` | Owned runtime and backend contract scripts |
| Delivery/emotion measurement | `.agents/rules/backend-mlx.md`, `docs/reference/delivery-harness.md` | Fixed protocol, provenance, statistics, and ledger |
| iOS app or support code | `.agents/rules/ios.md`, `docs/reference/ios-app-guide.md` | Generic device SDK compile; physical-device XCUITest only when requested |
| UI localization | `docs/reference/localization.md` and the platform rule | Typed String Catalog copy; UI locale stays separate from generated-speech language, model instructions and stored user content |
| macOS app or XPC stack | `.agents/rules/macos.md`, `docs/reference/macos-app-guide.md` | macOS deterministic tests/build; native XCUITest only when requested |
| Scripts, CI, packaging, benchmarks | `.agents/rules/release-qa.md` | Repository scripts and workflows |
| Generated inventories | `.agents/rules/derived-artifacts.md` | `scripts/refresh_derived_artifacts.py` |
| Website | `website/AGENTS.md`, `website/PRODUCT.md`, `website/DESIGN.md` | Node contracts, Vite build, browser verification |
| Current external APIs | Relevant skill plus primary vendor docs | Sosumi/Apple docs, Context7, GitHub, or Hugging Face when callable |

### Deterministic gate map

`./scripts/check_project_inputs.sh` owns T1/T2. The complete enforced-surface catalog is in
[the release/QA rule](.agents/rules/release-qa.md#deterministic-gate-map).
Read [repository self-verification](docs/reference/repository-self-verification.md) before adding
or weakening a gate. Exemptions need reasons in `config/surface-coverage-exemptions.json`.

<!-- BEGIN OPTIONAL ASSISTS -->

## Optional assists (user-scoped; verify before relying)

No gate can validate optional assists; they are never prerequisites.

| Task | Optional capability |
| --- | --- |
| Apple frameworks and compiler behavior | `axiom-apple-docs`; Sosumi or Xcode documentation search |
| Swift design, concurrency, data, networking, security, media, accessibility, testing | `axiom-swift`, `axiom-concurrency`, `axiom-data`, `axiom-networking`, `axiom-security`, `axiom-media`, `axiom-accessibility`, `axiom-testing` |
| Build/environment diagnosis | `axiom-build`; diagnose environment before source and never apply generic Simulator/cache-clean advice against repository policy |
| MLX/Qwen runtime | `swift-mlx`, `swift-mlx-lm`; exact checked-in catalogs and pins still win |
| Xcode inner loop | `axiom-xcode-mcp`; physical-device/macOS profiles only, see below |
| macOS / iOS implementation | Applicable `build-macos-apps:*` / `build-ios-apps:swiftui-*` skills; no Simulator routes |
| GitHub context | Available GitHub connector or `gh`; verify capabilities first |
| Model source research | Hugging Face connector or `hugging-face:hf-cli`; catalog identity still wins |
| Website inspection | Available browser tool; signed-in Chrome only when needed; never Vocello UI |
| App Store Connect | `app-store-connect-cli`; exact IDs, paginated JSON, read-only default, explicit mutation authorization |
| Codex instructions, hooks, skills, or settings | `openai-docs` and current official OpenAI documentation |
| Current third-party library APIs | Context7, then primary vendor documentation |

Discover assists only when needed.

<!-- END OPTIONAL ASSISTS -->

## Codex and Xcode workflow

Review and trust `.codex/hooks.json` with `/hooks`. Its Bash hook runs
`scripts/hooks/precommit_gate.sh`; commits require `main` and a completed, matching local checkpoint.
The hook only checks that receipt; missing/stale receipts block with exit 2. Run long checks through
`scripts/dev.sh checkpoint`, never inside the hook or its host timeout.
`QVOICE_SKIP_COMMIT_GATE=1` bypasses validation once, never the `main` requirement or full CI.

With XcodeBuildMCP, read `axiom-xcode-mcp`, call `session_show_defaults`, use profile `macos`
for `QwenVoice` or `ios-device` for `VocelloiOS`, and resolve physical-device IDs only at runtime.
Never use its Simulator, preview, or UI routes; repository scripts remain authoritative.
`scripts/dev.sh assists` is the opt-in configuration check. Optional configurations and installed
tools are not required by ordinary verification.

## Verification tiers

Use `scripts/dev.sh plan`, repeat `scripts/dev.sh focused` while editing, then run one
`scripts/dev.sh checkpoint` for the coherent tree. The router preserves caches without UI/model/release work; see
[`docs/reference/development-workflow.md`](docs/reference/development-workflow.md).

Serialize native Xcode commands: the shared SwiftPM lock spans XCTest. Parallelize read-only/Python
work instead; never bypass the lock or clear caches to evade contention.

- **T0:** fast generation, adjacent Python tests, and changed XCTest classes.
- **T1:** derived refresh, relevant documentation or project-input contracts, affected Python tests
  and platform-required native checks. Unknown/tooling-authority changes broaden verification.
  `scripts/dev.sh checkpoint --full` requests the full deterministic checkpoint. The commit hook
  reuses only the same content/toolchain PASS; edits during checking invalidate it.
- **T2:** full deterministic GitHub CI for every push/PR; path-aware jobs may skip while the
  aggregate required context remains authoritative.
- **T3:** explicit release evidence, signing, notarization, archive, and artifact verification.

Commit coherent checkpoints on `main` and push after deterministic verification. This never
authorizes a release. The main-only invariant also applies to experiments and MLX pin work.

### Explicit frontend acceptance

Only explicit QA authorizes `scripts/ui_test.sh` or model/device lanes. Follow
[the testing router](docs/reference/testing-runbook.md), then the relevant platform procedure.
iOS preflight requires a valid Apple Development identity/private key and an unlocked physical
device. Preserve all user data; runner PASS requires diagnostics, crash checks and restoration,
not just XCTest success. Zero observations cannot authorize resume; changed source needs new IDs.
`scripts/ios_candidate_acceptance.py` guards the separate preinstalled-candidate route.
Before a stateful journey, verify that it records and restores observed original selections and
drafts; hard-coded resets are not restoration. Catalog coverage and partial layout captures never
substitute for complete locale/accessibility acceptance. Current gaps belong in the roadmap and
checkpoint, not additional permanent gates here.

For timed sessions reserve collection time. Frozen campaigns use untracked checkpoints, never
tracked doc edits between shards. The [device procedure](docs/reference/ios-device-testing.md#pause-and-resume)
owns retention, resume validation and the separately authorized English/French three-minute
Auto-Lock readback plus independent lock verification. No device UI follows final protection.

## Security and release summary

- macOS: protected version tag → verified draft candidate → notarized DMG via
  `.github/workflows/release.yml`.
- iOS: optional TestFlight archive; version/build identity comes from `project.yml`.
- Website: Vercel deployment rooted at `website/`.
- Security: see `SECURITY.md`; macOS sandbox is disabled for MLX, iOS uses its declared App Group
  and increased-memory entitlement, and CI preserves immutable Action pins, dependency review,
  CodeQL, SBOMs, and build attestations.

Read `docs/ARCHITECTURE.md` and `docs/reference/privacy-storage.md` for the complete boundaries.
