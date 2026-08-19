---
status: historical
owner: backend-and-platform
summary: Point-in-time Codex takeover review of Vocello architecture, repository governance, validation health, delivery state, engineering risks, and optional capability routing on 2026-08-19.
contentDigest: sha256:192d48f91df3ea613eb88ff94743d5b9c69821589e68994ce73bbc4258e45bfa
---
# Vocello Codex Handover Review — 2026-08-19

This report records the repository state reviewed for the Codex takeover. It is descriptive,
pinned evidence rather than a new source of product or delivery truth. Current work status remains
owned by `config/roadmap.json`; convergence phase status remains owned by
`config/runtime-refactor-contract.json`; source, `project.yml`, and machine-readable contracts
continue to override this snapshot.

## Executive assessment

Vocello is a mature, unusually well-governed local-first Apple-platform speech project. The core
engineering posture is fail-closed: product inputs, release evidence, benchmark publication,
documentation, concurrency escapes, generated inventories, and UI automation all have explicit
contracts. The strongest takeover decision is therefore preservation, not reinvention. Codex
should use the existing deterministic scripts as the final verdict and treat skills, plugins, MCP
servers, models, browsers, and devices as conditional assists.

The checkout was clean on `main` at commit `c2aa3762` before the migration. The current public
release identity was 2.4.0, build 23. The model catalog reported complete identities for every
Speed/Quality artifact. No product runtime API, model schema, persistence format, deployment target,
or dependency version needed to change for the takeover.

## Product and target map

| Surface | Role | Runtime boundary |
| --- | --- | --- |
| macOS app (`QwenVoice`) | Desktop composition, history, playback, settings, downloads | App talks to the dedicated XPC engine stack |
| XPC engine/service | Model ownership, synthesis, telemetry, lifecycle isolation | Owns the shipping macOS MLX process boundary |
| iOS app (`VocelloiOS`) | Mobile studio, local history/playback, downloads | Runs the engine in process and validates UI on a physical iPhone |
| `vocello` CLI | Diagnostics, benchmarks, model and synthesis workflows | Uses the in-process engine path |
| `VocelloQwen3Core` package | Owned Qwen3-TTS and Mimi implementation plus stable facade | Encapsulates MLX implementation products and upstream lineage |
| Website | React/Vite marketing, privacy, release and TestFlight links | Independent web build deployed from `website/` |

The generated Xcode project contains 13 targets. The manifest is `project.yml`; direct pbxproj
editing is prohibited. All configurations are Release-derived. Important exact package pins at the
snapshot included GRDB 7.10.0, MLX Swift 0.31.6, SwiftHuggingFace 0.9.0, and MLX Swift LM 3.31.4.
MLX Swift and MLX Swift LM move together, and the product has no Core ML fallback.

## Runtime and data flow

```text
visible UI or CLI request
  -> shared product vocabulary and engine facade
  -> macOS XPC engine OR iOS/CLI in-process engine
  -> actor-owned request plan, sampling, cancellation, and memory policy
  -> VocelloQwen3Core facade
  -> MLX lazy graph evaluation on Apple Silicon
  -> framed PCM/audio events
  -> player, history, telemetry, and qualified evidence
```

Model delivery follows a separate fail-closed route:

```text
checked-in production catalog + receipts
  -> shared downloader and restoration ledger
  -> local artifact verification
  -> model loader / prewarm slot
  -> request-local synthesis state
```

The important ownership invariant is that lifecycle mutation is singular and typed. The engine
actor owns loading, active requests, cancellation, prewarming, sampling, wired-memory policy, event
completion, and product finalization. Audio-bearing events use a bounded suspending route and are
not evicted. MLX arrays and unevaluated graphs remain within one isolation domain because
`MLXArray` is intentionally non-`Sendable`.

## Repository scale and test shape

The inspected tree contained approximately:

- 243 Swift source files and 87,436 source lines;
- 32 Swift files and 17,270 lines in the owned runtime package;
- 63 Swift test files and 15,109 test lines;
- 11 owned-runtime test files and 4,468 owned-runtime test lines;
- 153 Python scripts with 63,850 lines and 29 shell scripts with 9,488 lines;
- 61 `XCTestCase` classes and roughly 510 `test...` methods;
- 17 JSX files, three JavaScript data/entry files, and two large shared CSS files in the website.

The suite intentionally remains XCTest-based; Swift Testing migration is not an implicit takeover
task. No meaningful TODO/FIXME backlog was found. Four `try!` and five `fatalError` sites were
present, concentrated in owned-runtime configuration invariants, one AppKit coder initializer, and
one deliberate iOS diagnostic-crash route rather than ordinary recoverable product flow.

## Governance and delivery state

The source-of-truth split is clear:

- `config/roadmap.json` owns work plans and items and generates `docs/ROADMAP.md`.
- `config/runtime-refactor-contract.json` owns convergence phase status.
- `docs/development-progress.md` is a narrative checkpoint and must not become a status database.
- `config/build-output-policy.json` owns repository output, caches, cleanup eligibility, and
  storage floors.
- release evidence, supply chain, required-step ledgers, benchmark history, documentation
  metadata, derived facts, and surface coverage each have dedicated validators.

One active roadmap plan, `delivery-prompting-2026-08`, was 92% complete: 21 items done, two
declined, one parked, and one planned. The remaining planned item, DP-25, calibrates normal-tier
gate floors and prosody profile v4 from DP-22 sidecars stored in local `outputs/bench-archive`.
Those sidecars are deliberately untracked, so resuming DP-25 depends on their continued local
availability or an explicit regeneration decision.

## Validation evidence

The following read-only validation was completed during review:

- `QVOICE_GATES=quick ./scripts/check_project_inputs.sh`: PASS in approximately 28 seconds.
  Build-output, catalog, evidence, benchmark history, owned runtime, documentation, supply chain,
  orchestration, project health, security, convergence, delivery-copy, derived-fact, roadmap,
  surface-coverage, and UI-workflow checks all passed.
- `python3 scripts/project_health.py rebuild-summary --check`: PASS.
- `npm --prefix website run check`: PASS. Source contract, seven Node tests, rendered
  accessibility contract, client build, SSR build, and prerender all completed successfully.
- Documentation metadata reported 88 annotated documents, zero unannotated documents, and 14
  non-blocking source-freshness warnings.

`scripts/macos_test.sh test` did not reach a source verdict inside the managed workspace sandbox.
Xcode/SwiftPM were denied writes to `~/.cache/clang/ModuleCache` and
`~/Library/Caches/org.swift.swiftpm`, producing `Operation not permitted` followed by standard
library load failures. The captured artifact was
`build/artifacts/macos/tests/mac-test-20260819-021117`. The correct follow-up is to rerun the same
repository command with approved unsandboxed cache access. This result does not justify a code fix,
Simulator use, cache deletion, or a new DerivedData location.

## Strengths to preserve

1. **Local-first privacy:** no cloud synthesis, no bundled weights, and strict tracked-evidence
   redaction.
2. **Contract-driven change control:** source, generated artifacts, evidence, and prose are bound
   by scripts rather than convention alone.
3. **Generated project discipline:** target/resource identities stay in `project.yml`.
4. **Owned runtime boundary:** upstream lineage and compatibility remain visible while product code
   imports a stable facade.
5. **Deterministic publishing:** models, devices, and UI evidence cannot block commits, PRs,
   signing, notarization, or uploads.
6. **Real-device UI evidence:** XCUITest is the single native UI driver and iOS acceptance uses a
   paired physical phone.
7. **Evidence quality:** benchmark history is PASS-only, privacy-safe, source-bound, and qualified
   against telemetry/memory contracts.
8. **Website contracts:** accessibility, metadata, anchors, assets, copy, performance claims, and
   prerendering are checked without relying on visual inspection alone.

## Risks and focused watch areas

- The snapshot contained 42 `@unchecked Sendable` declarations and 10 `nonisolated(unsafe)` uses.
  They are governed by `config/concurrency-safety.json`, but every new escape remains a high-risk
  review point.
- MLX lazy evaluation, non-Sendable arrays, request cancellation, generation-task completion, and
  wired-memory tickets form a coupled correctness/performance boundary.
- Exact dependency pins and owned-runtime baselines make package upgrades intentionally
  cross-cutting; pin bumps require isolated branch evidence and lockstep updates.
- Physical-device-only iOS UI evidence is high quality but depends on hardware availability and is
  slower than deterministic compilation.
- Fourteen documentation freshness warnings were non-blocking at capture and should be triaged
  during the next relevant currency pass rather than hidden or bulk-reset.
- DP-25 relies on local benchmark sidecars. The roadmap should continue to say so until the item is
  completed, declined, or redesigned.
- Release-only configuration and registered debug knobs reduce hidden behavioral divergence but
  make accidental production-affecting environment checks especially important to review.

## Codex capability map

The takeover workflow uses optional capabilities only when installed and callable:

| Work | Preferred optional assist | Repository authority |
| --- | --- | --- |
| Apple APIs and compiler behavior | `axiom-apple-docs`, Sosumi | selected SDK/Xcode and source contracts |
| Build and environment diagnosis | `axiom-build` | repository preflights and build scripts |
| Swift/concurrency/testing | applicable Axiom skills | checked-in code and deterministic tests |
| MLX/Qwen | `swift-mlx`, `swift-mlx-lm` | owned runtime, exact pins, catalogs, validators |
| Xcode inner loop | `axiom-xcode-mcp`, one XcodeBuildMCP | `macos`/`ios-device` profiles and scripts |
| GitHub | GitHub skills/connector, then `gh` | workflows and protected required context |
| Hugging Face research | connector or `hugging-face:hf-cli` | checked-in production catalog and receipts |
| Website | in-app browser | Node contracts and Vite build |
| Codex configuration | `openai-docs` | `AGENTS.md`, `.agents/rules/`, `.codex/hooks.json` |

XcodeBuildMCP must begin with `session_show_defaults`, use only repository profiles `macos` or
`ios-device`, resolve a physical device ID at runtime, and never drive Vocello UI or select a
Simulator. Computer-use remains development-environment assistance only. No uninstalled plugin was
needed for the takeover.

## Handover conclusion

Codex should continue development from the active roadmap and narrative checkpoint, not from this
report. For every task: inspect repository state, read the applicable `.agents/rules/` document,
select only relevant optional assists, implement a minimal coherent change, run deterministic
repository gates, refresh registered derived artifacts, and add model/device/UI evidence only when
the user requests that acceptance tier.
