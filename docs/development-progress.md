# Vocello development checkpoint

> Current maintainer checkpoint. Confirm this summary against the checkout before acting; source,
> `project.yml`, and repository scripts remain authoritative.
>
> **One authority per fact:** convergence status lives in
> [`config/runtime-refactor-contract.json`](../config/runtime-refactor-contract.json);
> measurements live in [`benchmarks/OPTIMIZATION.md`](../benchmarks/OPTIMIZATION.md) and the
> PASS-only registry ([`benchmarks/HISTORY.md`](../benchmarks/HISTORY.md)); the staged roadmap
> and its closure evidence live in
> [`docs/reference/optimization-report-review-2026-07-25.md`](reference/optimization-report-review-2026-07-25.md);
> engine invariants live in [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) and the ADR
> [`docs/decisions/runtime-streaming-quality-convergence.md`](decisions/runtime-streaming-quality-convergence.md).
> This file is the thin checkpoint: where things stand, what to do next, and pointers.

## Runtime convergence status

Phase 4 `overallPromotion: passed` closed the cutover gate on 2026-07-20 (with Phases 0/5/6).
Phases 7, 8, and 14 closed 2026-07-23. Phase 9 closed 2026-07-26; Phase 12 ships the fast-depth
quality registry with the deep producer landed; Phase 13 (history v3) went live 2026-07-29 with
the first schema-v3 records committed, and the UI-checker fold (2026-08-01) extended v3 to ui-generation records; phase 10–11 remainders stay open. The contract JSON is the
machine-readable status record and wins over any older prose.

| Plan phase | Current state |
| --- | --- |
| 0 — Characterization | Closed 2026-07-20. Clean-tree Mac CLI/UI and iPhone UI controls bound in `config/characterization-fixtures.json` (`status: closed`, `controlSessions` recorded). |
| 1 — Correctness prerequisites | Shipping: XPC reserves before side effects, synchronized pressure snapshots, continuous critical-relief admission. |
| 2 — Plans and actor | The actor is the shipping generation-mutation authority and, since 14b, owns every product-reachable runtime lifecycle operation (loading, facts, diagnostics, priming, schema-3 clone artifacts). Immutable plans stay in shadow comparison. Invariant detail: ADR + `.claude/rules/backend-mlx.md`. |
| 3 — Classified sessions | Shipping through Phase 4: `[Float]` materialized before the awaited frame-bounded single-consumer channel send; typed terminal outcomes; stale-safe product finalization. |
| 4 — Product adapter and mode cutover | Closed 2026-07-20 (`overallPromotion: passed`). `GenerationOutputAdapter` is the shipping product session. |
| 5 — Request-local sampling | Closed 2026-07-20. Fail-closed promotion packaging (`samplingPromotionPackaged=true`) live on the shipping path. |
| 6 — Telemetry v9 | Closed 2026-07-20: complete v9 sidecars are the history authority; the JSONL envelope remains schema v8. |
| 7 — UI-context gap | Closed 2026-07-23 in two acts (OPTIMIZATION.md §J/§K): XCUITest screen recording was the canonical decline (fixed via `preferredScreenCaptureFormat: screenshots`); the honest residual was Liquid Glass compositor work, shipped as the generation performance gate (macOS; iOS applies it on fixed-refresh displays only). XPC topology itself measures ~3%. |
| 8 — Shared component storage | Closed 2026-07-23 with live all-artifact validation on both canonical platforms (exact reuse, single tokenizer inode; `docs/reference/model-delivery.md`). |
| 9 — Runtime component reuse | Closed 2026-07-26. Speech-tokenizer residency ships on macOS behind host-attested content identity; byte-identical fixed-seed switch A/B, adoption probe 503→0 ms, retained-memory qualification PASS on the 8 GB floor (`mac-memory-qualification-20260726-115343-5a1c8a85`). iOS stays disabled (Jetsam headroom). Off-switch: `QWENVOICE_TOKENIZER_RESIDENCY`. |
| 10 — Spoken-text planning | Closed 2026-08-01: every take now speaks the conservatively normalized script at the engine entry (prompt assembly, language detection, QC pause budget, and telemetry evidence all see the same spoken text; transformed takes record `spokenTextTransformations` + digest). The fixed bench corpus is normalization-invariant by a standing core test, and the fixed-seed A/B on the medium corpus text was byte-identical across the change. Long-form/batch upstream planning passes through unchanged (idempotent). |
| 11 — Long-form v4 | Stages A–E shipping on both platforms: planner-owned segmentation with per-segment sub-seeds, sequential streaming execution, bounded assembly, manifest v4, resume, grouped History projects. macOS acceptance 2026-07-23 (`macos-xcui-smoke-20260723-195700-ab46482a`); iPhone acceptance 2026-07-24 (`ios-xcui-smoke-20260724-183626-f9961535`). iOS single-segment regeneration device-accepted 2026-08-01 (smoke run `ios-xcui-smoke-20260801-142416-79615150`: the retained project's segments chip opens a confirmation dialog, segment 1 regenerates with a fresh recorded seed, the joined output reassembles, and History keeps the lineage searchable — longFormV4 residual closed); line batch stays removed from iOS by design; legacy XPC `generateBatch` retired 2026-07-24. |
| 12 — Bounded analysis and unified quality | Fast-depth registry shipping 2026-07-26 (typed `GenerationQualityReport` + fail-closed `QualityGateRegistry` verdict in telemetry notes on every finalization, live-verified). Same-day additions: the standard/canonical `deepReport` producer, per-take prosody gate verdicts on the bench sidecar (folded into history warnings), typed `languageASR` and `longFormContinuity` gates, and the advisory speaker-similarity dev metric. Composed standard-depth verdicts went live on the delivery bench 2026-08-01 (`bench-quality-composed.json`, proof run `macos-engine-20260801-010135-6607009f`): the sidecar prosody gate folds into `deepReport` with a fast-consistency guard and fail-closed missing analyzers. Canonical depth followed the same day: the promoted delivery-adherence rule v1 (per-preset signed expectations + intensity scaling in prosody profile v2, warn-first) emits a real `.delivery` gate per delivery take, the publisher banks the paired neutral-vs-instructed deltas, and the first canonical proof run (`macos-engine-20260801-024556-e826c4ec`, 18 delivery cells, seed 20260801) composed 3 pass / 15 warning / 0 fail across all seven gates. Open: threshold recalibration from the banked seed matrix; optional MOS-proxy. |
| 13 — Benchmark/history v3 | Live 2026-07-29: the first schema-v3 records are committed (three clean `phase0-cli-control-*` engine records plus one exploratory run that also exposed and fixed the summarizer's v3 pin). `benchmarks/schema-v3.json` adds the typed quality identity to generation takes (pass/warning only, five fast gates required, machine-code issues); v1/v2 records stay valid immutable history; the publisher stamps v3 only when every take carries the identity. The UI benchmark checkers folded the same identity 2026-08-01: ui-generation records now publish v3 (first: the focused `v3-fold-proof` record `macos-xcui-benchmark-20260801-003208-403989cf`); the canonical iOS matrix publishes v3 at the next phone window. |
| 14 — Organization and retirement | Closed 2026-07-23 (14a + 14b): compatibility SPI retired, actor-owned loading/metadata/priming/clone artifacts, clone conditioning epoch-bound end to end. |

## Resume here (2026-07-31)

Stages 0–3 of the adopted roadmap are complete (the 2.2 artifact promotion included);
Stage 4 stays gated. **v2.3.0 was cut 2026-07-31 on an explicit maintainer call** with the
evidence battery deliberately mid-flight (deterministic publishing rule; deferral recorded
below and in the release notes). The battery on the 2026.07.26.1 artifacts is more than
half banked, and its device lanes surfaced and shipped real fixes along the way:

- **Banked (committed, PASS):** three clean CLI engine controls (the first schema-v3
  records), three macOS UI controls, two clean iOS UI controls
  (`phase0-ios-control-1..2`; the wiped phone's benchmark clone voice was re-enrolled with
  the new opt-in `scripts/ui_test.sh ios enroll-clone-fixture` lane), the canonical
  29-take macOS matrix (`passedWithWarnings`, schema v2 pending the UI-checker
  quality-identity fold), and retained-memory qualification on both canonical platforms —
  the memory re-qualification predates the artifact re-pin and rides the deferred
  remainder below.
- **Fixes shipped by the battery:** the summarizer's v3 schema pin; the ui-lane long-form
  probe silently killing non-long-form runs; the iOS download-ledger artifact-update brick;
  clone priming on voice selection; a completed model load no longer discarded on late task
  cancellation (`VocelloQwen3Core`); the clone prime rerouted from a memory-spiking bounded
  completion (~2.0→5.1 GB resident on iPhone) to the ordinary prewarm; the project-health
  inventory now counts only git-tracked files. Model delivery additionally gained
  Wi-Fi-pinned downloads (`allowsCellularAccess=false`, retiring the Wi-Fi Assist LTE
  reroute that collapsed downloads to sub-MB/s), a pullable download-diagnostics mirror,
  and an autonomous transfer-health verdict in the opt-in
  `scripts/ui_test.sh ios model-download` lane (live PASS: 6.6/6.3/5.7 MB/s, zero retries,
  exact shared-component reuse).

The working order now lives in the adopted
[2026-08 roadmap](reference/roadmap-2026-08.md) (interleave-by-cost: Tier 1 no-phone
residuals plus the study's Gate 0 micro-benchmark, Tier 2 phone window, Tier 3 gated
performance block after the fixture rebind, Tier 4 carryover). Immediate specifics:

1. **Battery remainder completed 2026-08-01** (Tier-2 phone window): control 3 re-ran
   clean (`ios-xcui-benchmark-20260801-130748-c3630f44`, first schema-v3 iOS UI record),
   the canonical 29-take matrix published as the first canonical iOS v3 record
   (`ios-xcui-benchmark-20260801-132415-abbec96b`), both control evaluators PASS over
   the current-artifact trio, and `config/characterization-fixtures.json` is rebound to
   the 2026.07.26.1 identities with the mid-battery caveat recorded in its
   `rebindNotes`. Memory qualification on both platforms was already banked 2026-07-29
   against these artifacts (the only later memory-relevant change — the clone-prime
   reroute — strictly removes a transient spike, so the banked evidence stays
   conservative-valid; the task checkpoint is authoritative over the roadmap's
   redundant re-qual listing). Every take carries only the familiar
   `memory.pressure.soft_trim` advisory plus one warn-level design-short dropout,
   consistent with the R2a boundary finding.
2. **v2.3.0 released 2026-07-31** (maintainer call): the combined 2.2-promotion + Stage 1
   story is the headline (up to ~10% faster warm, ~280 MB less memory, ~1 GB smaller Speed
   footprint); notes in [`docs/releases/v2.3.0.md`](releases/v2.3.0.md) with the standing
   smoke-lane ledger. iOS build 22 ships the clone-prime and Wi-Fi-pin fixes that build 21
   carried as exposures.
3. **Delivery/clone fidelity verification program complete (2026-08-01):** the
   maintainer's preset-adherence and clone-tone complaints are now measured
   rather than perceived — see
   [`docs/reference/delivery-fidelity-report-2026-08-01.md`](reference/delivery-fidelity-report-2026-08-01.md)
   and OPTIMIZATION.md §P. The promoted delivery gate is calibrated from a
   banked 7-seed × 18-cell paired matrix (canonical composed depth live on the
   delivery bench), neutral cross-seed wander is quantified as by-construction
   (2.7 st / 2.0 Hz at shipping defaults; cohort bounds sit above baseline),
   clone identity measures strong (ECAPA 0.81–0.87 vs 0.10–0.39 negative
   controls), and the SER advisory + clone-fidelity lanes are standing tools.
   Product follow-ups recorded: dramatic/surprised instruction rewrites;
   optional engine-level neutral stabilization experiment. The adopted
   remediation tracks (R1 preset rewrites → R2 defect sweeps → R3 gated
   neutral experiment → R4 process riders) live in
   [`docs/reference/delivery-remediation-plan-2026-08.md`](reference/delivery-remediation-plan-2026-08.md).
4. **Tier 1 is complete (2026-08-01):** the UI-checker v3 fold, quality-report
   consolidation (composed standard verdicts on delivery benches), single-take
   normalization, and the iOS segment-regeneration implementation half all landed with
   evidence; Gate 0 ran and returned **no-go** (`benchmarks/OPTIMIZATION.md` §O — MPP
   never beats MLX on the floor and batch-1 is inexpressible at parallel scope), which
   withdraws the conditional fused-kernel Gate 2 from Tier 3. The optional delivery-chip
   audio rider was skipped. What remains: the Tier-2 phone window (battery remainder +
   riders, including 1.5's on-device acceptance), then the gated performance block, now
   pin bump → P1b only, once the fixture rebind gives current baselines.

## Staged roadmap state

Stage-by-stage details, closure evidence, and falsifiability criteria live in the
[roadmap review doc](reference/optimization-report-review-2026-07-25.md); measurements in
`benchmarks/OPTIMIZATION.md` §L–§N. Summary:

1. ~~Stage 0 — near-free quality wins~~ **completed 2026-07-26** (clone reference silence
   append with versioned conditioning identity, warn-first long-form boundary advisory,
   duration-directive delivery advisory, repetition-penalty A/B kept 1.05) → §L.
2. ~~Stage 1 — launch-bound attack~~ **completed 2026-07-26** at net **+11% warm RTF,
   byte-identical** (P2a-i + P3 landed; P2a-ii, P5b, P1b measured and declined with do-NOT
   records; stage-exit GPU busy ~47% — still launch-bound, so quant/speculative stays
   parked) → §M.
3. ~~Stage 2 — memory program~~ **completed 2026-07-26, including the 2.2 promotion**
   (phase 9 closed; six converted artifacts on public `PowerBeef02/<folder>` repos, catalog
   artifactVersion **2026.07.26.1** with fail-closed validation, isolated delivery proof,
   the canonical Mac install upgraded in place, stale-artifact update detection shipped
   end to end — Core probe, CLI `models status/install`, macOS `settings_update_<id>`, iOS
   `iosModelUpdate_<id>`; 2.3 codec conversion parked on a dtype-independent conv
   regression; 2.4 declined with M5b's premise corrected) → §N.
4. ~~Stage 3 — quality harness~~ **completed 2026-07-26** (phase 12/13 rows above; MOS-proxy
   and composed lane emission deliberately deferred).
5. **Stage 4 — gated migrations/research**: mlx pin bump to the newest lockstep pair
   (mlx-swift 0.31.6-era; the old 0.31.3 target is stale — see the
   [Metal 4 tensor feasibility study](reference/metal4-tensor-feasibility-2026-07-31.md),
   which also adds a cheap pre-registered MPP-on-M2 micro-benchmark rider, parks any
   custom fused tensor kernel behind P1b, and records the adopted OS-floor policy: hold
   26.0 with runtime-gated capability ladders; the first pin bump vendoring mlx core
   ≥ 0.32.0 triggers the 26.2 floor raise, per the study's F7) on a
   throwaway branch (contract invariant), long-form carryover (text context first), with
   speculative/PCG, CFG, and KV quantization parked. Working order and dependency rules:
   [roadmap-2026-08](reference/roadmap-2026-08.md).
6. **Smaller open threads**: iOS single-segment regeneration parity, the iPhone-15-Pro
   memory-profile diagnostic, a 60 Hz-device measurement of the iOS fixed-refresh glass
   gate if such hardware becomes available, and single-take spoken-text normalization
   (phase 10 remainder).
7. ~~iOS 900-character single-take limit~~ **shipped 2026-07-24**
   (`IOSGenerationTextLimitPolicy.sharedScriptLimit` 150 → 900, memory-qualified on-device
   proof `ios-engine-20260724-060000-1cc8ef23`; the iOS UI-benchmark `long` cell keeps its
   fixed 150-character text for history comparability).

Status report: [`docs/reference/runtime-refactor-status-report.md`](reference/runtime-refactor-status-report.md).

## Historical milestones (compressed; details in the cited authorities)

- **2026-07-20 — cutover gate closed.** Phase 0 characterization controls, fixed-seed
  equal/diverge pairs, secret-sauce cells, nested-v9 producers, promotion packaging, v9
  sidecar authority, and clean canonical 29-take matrices on both platforms
  (`macos-xcui-benchmark-20260720-172920-591696d1`,
  `ios-xcui-benchmark-20260720-174441-16fc128c`) → `overallPromotion: passed`. Control and
  fixture identities: `config/characterization-fixtures.json`; records in the registry.
- **2026-07-22 — backend review + characterization gate + amendment.** Five external research
  documents counter-verified (~90 claims, staleness only) and imported under
  [`docs/research/`](research/); the R1 gate localized the post-cutover macOS UI decline to
  the delivery topology, endorsed as `amendment20260722` (phase 7 rescope, UI-context cell
  required in promotion matrices, phase 14 pulled forward). Same day: gates tiered
  (T0–T3, hook-enforced T1, path-aware CI, sole `CI required` context), trunk-based flow
  adopted, and xcodegen/ripgrep pinned to SHA-verified release artifacts after a runner-image
  roll flapped the toolchain gate.
- **2026-07-22 — UI QA architecture round trip.** Computer-use vision driving trialed and
  retired the same day; XCUITest returned as the sole autonomous driver in a ground-up v2
  stack (typed scoped queries, on-failure evidence, obstruction preflight, interruption
  sentinel, virtual-mic fixture, two-phase build/test). v2 acceptance passed on both
  platforms (`macos-xcui-benchmark-20260722-172102-48c4a193`). Computer use stays assistive
  ([`reference/interactive-ui-qa.md`](reference/interactive-ui-qa.md)).
- **2026-07-23 — the macOS UI decline resolved as a benchmark observer effect** (§J):
  XCUITest's automatic screen recording video-encoded every UI take; disabling it recovered
  the lane, engine code exonerated by flat interleaved CLI A/B. Phase 7 then closed via the
  generation performance gate (§K). Pre-2026-07-23 UI records carry the recording overhead
  and are not baselines. Fresh canonical gated matrices landed 2026-07-23 (macOS custom
  1.68–1.83 / design 1.78–1.94 / clone 1.49–1.84; iOS 1.86–2.03).
- **2026-07-24 — §H P0 GPU-busy re-capture completed** on the shipping runtime:
  whole-generation GPU busy ~47%, still launch-bound (§H P0 addendum).
- **2026-07-25 — optimization report counter-verified; staged plan adopted** (the roadmap
  review doc above). Same day: macOS 2.2.0 released and the repository renamed
  `PowerBeef/QwenVoice` → `PowerBeef/Vocello` (see Open release work).
- **2026-07-26 — Stages 0–3 executed and closed**, including the 2.2 artifact promotion and
  the benchmark-registry supersession rule (immutable records with a strictly older
  artifactVersion stay valid; new publications fail closed on current pins).
- **2026-07-28 — TestFlight public beta live; marketing surfaces grounded and refreshed.**
  Apple approved the Public Beta group (build 21, v2.2.2) and the public link went live. A
  commissioned promotion report was counter-verified against the tree and its repo-facing
  items landed in one arc: current repo description, a curated `good first issue` on-ramp
  (#86 CLI version fallback, #87 shell completion), README conversion pass (privacy hook,
  "Not a Python wrapper" block, CLI debug-RTF reproducibility caveat, coding-agents
  authorship line), website TestFlight front door (hero link, `#iphone` band with the
  cleaned `ios-studio.png`, nav/FinalCTA links), a factual local-versus-cloud comparison
  table in WhyCloud, two new Listen samples (Japanese preset take, 31 s calm narration),
  cookieless Vercel Web Analytics with the privacy policy scoped to disclose it, the page
  title retargeted to Mac + iPhone, and an instant-reveal fix for in-page anchor jumps.
  Outreach and social items from the report stay maintainer-owned outside the repository.
- **2026-07-31 — v2.3.0 released (macOS DMG + iOS TestFlight build 22)** on an explicit
  maintainer call, shipping the 2026.07.26.1 artifact generation, the Stage 1 warm-speed
  wins, delivery hardening, and the clone-prime/Wi-Fi-pin fixes. The evidence battery was
  deliberately paused mid-flight for the release window (deterministic publishing rule);
  its banked lanes, the aborted iOS control 3, and the exact remainder are itemized in
  Resume here. Same day: the public RTF wording was reframed as a realtime multiple
  (PRs #89/#90) and the wiped phone's clone fixture was re-enrolled via the new opt-in
  `enroll-clone-fixture` UI lane.

## Current implementation

- Native app UI acceptance uses one shared XCUITest stack: `macos smoke|benchmark` on the native
  Mac host and `ios smoke|benchmark` on a paired physical iPhone.
- UI execution is explicit frontend QA. It is not required to commit, push, open or merge a pull
  request, run ordinary CI, package a release, or create an iOS archive.
- The ordinary iOS compile lane typechecks both the app and a standalone app-host-free policy
  XCTest bundle for the generic physical-device SDK. It covers catalog/ledger, memory policy,
  cancellation, storage-path gating, and diagnostic redaction without a phone. Xcode 26 rejects
  tool-hosted app-free XCTest execution on physical-device destinations, so this target remains
  compile-only and device runtime proof stays in the headless diagnostics and XCUITest lanes.
- The physical-iPhone smoke contract covers two distinct cancellation paths (visible Cancel, then
  the registered one-shot critical-memory diagnostic requiring typed `memory_pressure`
  cancellation before `fullUnload`, then a completed recovery generation). Proven by
  `ios-xcui-smoke-20260716-172350-2c6828e1`.
- Generation ownership is explicit across all hosts. Final core audio uses the actor-owned,
  frame-bounded suspending channel. Frontend preview/status events use a separate per-generation,
  bounded suspending router, so audio-bearing preview events are never evicted by a
  `bufferingNewest` policy. `ActiveGenerationCoordinator` admits one active product
  task, carries typed user, memory-pressure, superseded, or shutdown cancellation, and awaits both
  model terminal and product cleanup/finalization before trim, unload, or ownership release.
- The shipping generation path is `VocelloQwen3Engine`, its classified session, and
  QwenVoiceCore's `GenerationOutputAdapter` for Custom, Design, and Clone; the actor owns every
  product-reachable runtime lifecycle operation, clone conditioning stays tensor-opaque behind
  epoch-bound handles, and sampling algorithm v2 plus the request-owned memory policy are
  shipping contracts (every request has its own seed and `MLXRandom.RandomState`). Invariant
  detail: the ADR, `docs/ARCHITECTURE.md` §4, and `.claude/rules/backend-mlx.md`.
- Clone conditioning is typed as transcript-backed or genuine audio-only x-vector. Both apps own
  the visible `voiceCloning_consentAcknowledgment` in Settings, persist the choice locally, and
  keep Clone Generate disabled until consent is acknowledged. Smoke and benchmark enable it through
  that real Settings control for later testing; there is no hidden test-state override. The two
  conditioning modes retain distinct cache and artifact identities. The compile-gated
  `scripts/ios_device.sh clone-conditioning` lane proved both modes in one device process
  (`ios-clone-conditioning-20260716-162518-ea8e8989`, local-only evidence).
- History persistence fails closed with typed privacy-safe errors. An unavailable database is
  never presented as an empty library and destructive actions remain disabled; iOS exposes a Retry
  control, while macOS retries on reload or re-entry.
- Headless iOS generation, language, profiling, crash, and memory diagnostics use
  `IOSDeviceDiagnosticsRunner` through `scripts/ios_device.sh` — a non-UI diagnostic lane, not a
  second app driver. The diagnostic Clone path requires the exact prepared voice ID (canonical
  fixture: a transcript-backed Voice Design reference).
- No preview/browser-mirror route, invisible accessibility state marker, alternate UI driver,
  coordinate bridge, or hidden UI bootstrap belongs in the shippable app.
- Model delivery uses one shared integrity/atomic-install implementation. iPhone owns one
  bundle-aware app-lifetime background session plus an atomic schema-v2 request ledger, exact task
  adoption, cancellation barriers (ledger writes are authorization barriers), durable delegate
  staging, and bounded privacy-safe diagnostics. macOS and CLI retain foreground delivery with
  terminal session teardown. Cancel discards staging; Retry reuses verified files. The isolated
  `scripts/ui_test.sh ios model-download` lifecycle proof is explicit QA only; the standing proofs
  are recorded in [`docs/reference/model-delivery.md`](reference/model-delivery.md)
  (e.g. `ios-xcui-model-download-20260716-163359-61377762`, exact wire bytes, zero retries).
- The generated cross-platform production model catalog (schema v2) is complete for all six
  Speed/Quality artifacts with exact pinned identities and the shared `speech_tokenizer`
  component; all hosts resolve the same delivery plan; reconciliation authenticates every catalog
  file before reuse and failed checks grant no bytes. Since 2026-07-26 the pins are the
  `PowerBeef02` 8-bit-embedding artifacts at **2026.07.26.1**, and installed models carry
  stale-artifact update detection with visible Update states on both platforms (repair runs
  through the ordinary authenticated delivery path). Live delivery validation: 2026-07-23
  six-artifact isolated Mac run + three-artifact iPhone lane; 2026-07-26 isolated Mac proof from
  the new pins.
- Benchmark evidence uses collision-resistant run IDs, atomic run-scoped manifests, and a
  privacy-safe PASS-only registry; `benchmarks/HISTORY.md` is generated from canonical records.
  Canonical comparison hardware is the Mac mini `Mac14,3` (M2, 8 GB) and iPhone 17 Pro
  (`iPhone18,1`); focused/dirty/instrumented classes never silently mix into canonical trends.
  Telemetry schema v8 + evidence manifest v2 make RAM/pressure evidence a publication contract
  (exact sidecars, ≥95% coverage, zero capture failures; critical pressure/`hardTrim`/
  `fullUnload` fail publication). History schema v3 adds the typed quality identity (phase 13
  row above). Records with a strictly older pinned artifactVersion remain valid immutable
  history after a catalog re-pin; new publications fail closed on current pins.
- CPU and memory Instruments lanes use exact-PID attachment; successful profiles publish digest/
  settings/summary then discard the raw trace unless `--keep-trace` was explicit. The `memory`
  lanes run the versioned retained-memory sequence; `memory-field-report` reads already-pulled
  delayed MetricKit aggregates only. The telemetry-overhead observer-effect diagnostic stays
  local by design.
- Generated output is classified by `config/build-output-policy.json` (two persistent platform
  caches, one shared package checkout, ephemeral scratch, bounded evidence/symbols, release-only
  `build/dist/`). Storage inventory distinguishes automatically eligible, blocked, and explicitly
  acknowledged reclamation; manifest-owned free-space preflights stop heavy lanes early. Codex
  task/session storage is a separate optional operator workflow (policy + synthetic fixtures in
  CI; live state never becomes repository evidence).
- The Qwen3/Mimi implementation is the owned monorepo package `Packages/VocelloQwen3Core` behind
  the typed `VocelloQwen3Core` facade; immutable lineage/compatibility/ownership/capability
  contracts replace patch-stack governance. Runtime trust boundaries are machine-readable
  (`config/runtime-debug-knobs.json` master-gated overrides; `config/concurrency-safety.json`
  concurrency exceptions), and release-candidate evidence is schema-v2 fail-closed
  (process- and command-bound; iOS adds the non-device archive/IPA verifier).
- The physical-iPhone language lane predeclares a one-based fixed-seed run plan, requires
  three-pass locale-locked on-device Speech consensus, and offers a retry-free diagnostic cohort
  that never publishes history. Its version-2 corpus enforces minimum script lengths and pins
  Design to the known language. The all-iOS platform preflight
  (`scripts/lib/ios_platform_preflight.py check`) runs read-only before any iOS build route and
  never authorizes Simulator execution.

## Publishing boundary

Routine verification is deterministic:

```sh
./scripts/check_project_inputs.sh
scripts/macos_test.sh test
./scripts/build.sh build
./scripts/build_foundation_targets.sh ios
```

Stop there for ordinary development publishing. A model download, paired phone, or UI result is
required only for the explicit quality task that needs it. Audio promotion quality is decided by
deterministic QC, fixed-seed evidence, ASR/prosody gates, and telemetry; listening is optional
annotation rather than a prerequisite.

## Explicit frontend acceptance

```sh
scripts/ui_test.sh macos smoke
scripts/ui_test.sh macos benchmark

scripts/ios_device.sh preflight
scripts/ui_test.sh ios smoke
scripts/ui_test.sh ios benchmark
```

Generation UI tests visibly require Custom, Design, and Clone Speed to be ready, Generate to be
enabled, and the prepared Clone voice to exist before the first take. Use `models ensure` only as an
explicit macOS fixture repair/bootstrap step. XCUITest is the sole autonomous app UI driver
(v2 stack since 2026-07-22 — see Historical milestones); computer use stays assistive per
[`reference/interactive-ui-qa.md`](reference/interactive-ui-qa.md).

## Open release work

- **macOS 2.3.0 is the released version** (2026-07-31; notes under
  [`docs/releases/`](releases/)) — the 2026.07.26.1 artifact generation, Stage 1 warm-speed
  wins, delivery hardening, and the clone-prime/Wi-Fi-pin fixes, cut with the evidence
  battery deliberately mid-flight per the deterministic publishing rule. Before it,
  2.2.0 → 2.2.1 → 2.2.2 landed in one day on 2026-07-25. The 2.2.0 arc hardened the
  pipeline (SHA-pinned
  tooling in release jobs, nested-framework signing with an explicit notarization verdict check,
  self-diagnosing dirty-tree evidence errors) and renamed the repository
  `PowerBeef/QwenVoice` → `PowerBeef/Vocello` before tagging; old URLs redirect and the old name
  must never be re-occupied. macOS 2.1.0 was released 2026-06-12. Future releases start from a
  protected version tag; the workflow verifies identity, signs/notarizes, emits SBOMs/checksums/
  evidence/provenance, and verifies draft assets before publication.
- **First TestFlight build is uploaded**: the v2.2.2 dispatch (run `30177386286`) went green
  end-to-end on 2026-07-25 — archive, export, IPA verification, schema-v2 evidence, provenance
  attestation, TestFlight upload — making Vocello 2.2.2 (build 21) the first uploaded build.
  2.2.1/2.2.2 packaged the two App Store Connect binary rejections (opaque iOS icons;
  framework `CFBundleShortVersionString` inheritance) and an artifact-verifier inheritance fix.
  On 2026-07-27 the maintainer opened TestFlight distribution: beta Test Information completed,
  an Internal group (maintainer) received build 21 immediately, and a **Public Beta external
  group** was submitted to Beta App Review with the public link
  `https://testflight.apple.com/join/Cvp6yCv7` (open to everyone, no tester cap). Apple approved
  the build and the **public link went live 2026-07-28** — the README, repo description, and
  website all link it. Public App Store distribution additionally needs metadata, screenshots,
  and submission.
- **GitLab mirror exists** (2026-07-28, single-point-of-failure insurance): public project
  `gitlab.com/VocelloApp/vocello`, imported with full history and all tags, plus a
  `Vocello 2.2.2 (mirror)` release entry carrying the published SHA-256 digests, the release
  identity, and a link to the canonical GitHub DMG. Canonical development stays on GitHub; the
  mirror has no automatic sync yet (gitlab.com pull mirroring is a paid feature), so re-sync is
  currently a manual push and the mirror may lag main. The DMG binary itself still needs a
  one-time manual attach on the GitLab release.
- **Language-path acceptance state**: Speech assets for `de_DE`/`es_ES`/`ja_JP`/`zh_CN` verified
  2026-07-16; the corpus-v2/matrix arc closed with full run
  `ios-lang-bench-20260716-164248-1ecf8361` — 19/19 hint/QC, 18/18 output-gated, three-pass
  locale-locked ASR, `passedWithWarnings` (accepted Spanish Custom warning + soft trims),
  tracked `exploratory` because the worktree was dirty. It proves its exact fingerprint and is
  excluded from clean trends. Earlier failed/interrupted attempts correctly published no history.
- **Canonical UI evidence state**: a clean canonical macOS schema-v2 baseline exists
  (`macos-xcui-benchmark-20260716-181853-b4c2e299`, source `9a8da874…`) and a clean canonical
  iPhone schema-v2 baseline exists (`ios-xcui-benchmark-20260716-184106-48e3a3a6`, source
  `bcb5265a…`) for the pre-convergence owned runtime, each bound to its recorded source
  identity. Clean post-cutover matrices closed promotion 2026-07-20; the
  observer-effect correction re-baselined 2026-07-23 (fresh gated canonical matrices; macOS
  custom 1.68–1.83 / design 1.78–1.94 / clone 1.49–1.84, iOS 1.86–2.03). Physical-iPhone
  telemetry-v8/evidence-v2 acceptance is complete (canonical matrix, retained-memory
  qualification, exact-PID memory profile). Pre-2026-07-23 UI records are not baselines for
  post-change comparisons; every tracked record binds to its exact source/toolchain/model/
  hardware identities, and the 2026.07.26.1 artifacts still need their fresh fixture identities
  (see Resume here).

## Resume rule

Review `git status`, read the applicable role playbook, and run verification proportional to the
change. Do not rely on a dated local `.xcresult`, telemetry directory, or device state as proof for a
new checkout. A tracked record proves only its exact source/toolchain/model/hardware identities;
produce fresh evidence only when that acceptance surface is explicitly requested.
