# Vocello development checkpoint

> Current maintainer checkpoint. Confirm this summary against the checkout before acting; source,
> `project.yml`, and repository scripts remain authoritative.

## Runtime convergence status — reviewed 2026-07-25

This checkpoint tracks the staged runtime convergence program. Focused Phase 4 acceptance landed
at `00c9eea637259cfce858d1fc7d43a1a2c52ff86d` (delivered by [PR #78](https://github.com/PowerBeef/Vocello/pull/78)
as `d39b9a6…`). On 2026-07-20, Phase 0/5/6 closed and Phase 4 **`overallPromotion: passed`**
(`a4bb483`). That closed the cutover gate. On 2026-07-23, Phases 7 (UI-context gap), 8 (shared-component
live validation), and 14 (mechanical retirement, 14a + 14b SPI evaporation) also closed; Phases
9–13 remain open. `config/runtime-refactor-contract.json` is the
machine-readable status record and wins over older prose that still says promotion is pending.

| Plan phase | Current state |
| --- | --- |
| 0 — Characterization | Closed 2026-07-20. Clean-tree Mac CLI ×3, Mac UI ×3, and iPhone UI ×3 short Speed warm-10 controls PASS `check_characterization_controls.py` and secret-sauce checks (soft_trim only). `config/characterization-fixtures.json` binds BenchMatrixSpec short/long `promptDigest` values, representative warm WAV digests, and `controlSessions`; status `closed`. Contract `characterizationContract`: `closed-clean-control-sessions-bound`. Post–Phase 0 full 29-take UI matrices are recorded below. |
| 1 — Correctness prerequisites | Shipping. XPC reserves before side effects, pressure snapshots are synchronized, and critical relief holds admission continuously through cancellation, terminal cleanup, and relief. |
| 2 — Plans and actor | The actor is the shipping generation-mutation authority and, since Phase 14b (2026-07-23), owns every product-reachable runtime lifecycle operation: loading (with the verbose local-diagnostics sink), post-load facts, preparation diagnostics, prewarm/priming, and schema-3 clone-artifact persistence/adoption. Immutable plans remain in shadow comparison. Reserved/generating/aborting ownership, critical-relief lease transfer, and epoch-bound Clone handles remain unchanged. |
| 3 — Classified sessions | Shipping through Phase 4. Custom, Design, and Clone materialize `[Float]` before an awaited, frame-bounded, single-consumer channel send. Producer/receiver cancellation, delayed drains, maximum-length ordering, consumer failure, typed terminal outcomes, and stale-safe product finalization remain deterministic contracts. |
| 4 — Product adapter and mode cutover | Closed 2026-07-20. Source implementation, deterministic verification, focused platform acceptance, clean Phase 0 controls, canonical 29-take matrices, Phase 5 packaging, and Phase 6 v9 sidecar authority are all closed. Contract `overallPromotion`: `passed`. QwenVoiceCore's `GenerationOutputAdapter` remains the shipping product session. |
| 5 — Request-local sampling | Closed 2026-07-20. Shipping path packages fail-closed `SamplingTakeEvidence.packagedTelemetryNotes()` (`validatedForPromotion()` + `samplingPromotionPackaged=true`). Fixed-seed equal/diverge pairs remain live identity proof. Contract `requestLocalSamplingV2`: `shipping-promotion-packaged-evidence-live`. Long-form/candidate sub-seed execution remains Phase 11/12. |
| 6 — Telemetry v9 | Closed 2026-07-20 for history sidecar authority. JSONL envelope remains schema v8 with nested transition; publication-ready transitions with exact MLX chunk instants publish complete `*.streaming-telemetry-v9.json` sidecars and stamp digests. Contract `telemetry: 9`, `telemetryV9`: `complete-sidecar-authority-with-v8-envelope`. |
| 7 — UI-context gap (implemented 2026-07-23) | **Closed in two acts** (`amendment20260723`, OPTIMIZATION.md §K). Act 1: the canonical macOS decline was XCUITest's automatic screen recording (fixed via `preferredScreenCaptureFormat: screenshots`). Act 2: the honest residual (~23%) was Liquid Glass's continuous compositor work while visible; the XPC topology itself measures ~3%. The endorsed **generation performance gate** (`generationPerformanceGate` environment value from `hasActiveGeneration`) renders glass surfaces with the shipped solid-fill fallback during generation — acceptance 1.833 one-cell, full matrix custom 1.67–1.84 / design 1.79–1.94 / clone 1.43–1.86, engine capability delivered to visible users on the floor tier. Three diagnostic engine-loop experiments remain reverted (fixed-seed QC soak required for re-introduction). Addendum 2026-07-23: the iPhone no-gate finding covers ProMotion panels; because the support gate also admits the fixed-60 Hz iPhone 16/16 Plus/16e, `iosGenerationPerformanceGate` now applies the shipped solid-fill fallback during generation on fixed-refresh displays only (inert on all ProMotion devices). |
| 8 — Shared component storage | Closed 2026-07-23. Live validation delivered all six artifacts into an isolated Mac root (single tokenizer inode nlink=7 across six models plus the store; newest full window wire = expected − 682,295,738 exactly) and all three iPhone Speed artifacts through the extended isolated lane (Custom full-wire, Design/Clone exact reuse, zero duplicates/retries). Contract `sharedComponentStorage`: `live-validated-2026-07-23-…-exact-reuse`. |
| 9 — Runtime component reuse | Not started; unblocked 2026-07-23 by the live disk-component proof. Decoder/immutable-weight reuse remains an optional isolated A/B. |
| 10 — Spoken-text planning | Shipping inside long-form v4 since 2026-07-23: the spoken-text plan (normalization, protected spans, risks) drives long-form segmentation and generation text. Single-take generation does not yet consume spoken-text normalization. |
| 11 — Long-form v4 | Stages A–C shipping 2026-07-23 (macOS): long-form segments run sequentially through the shipping streaming path with live preview narrating each segment as it generates (auto-play-gated; the request-local `suppressStreamingPreview` flag remains for silent contexts), segmentation is planner-owned with per-segment sub-seeds, the bounded assembler joins output with a frame map, and manifest v4 (plan+execution+assembly) replaces v3 writes. Per-segment and joined-output Fast QC gate the run. Stages D–E landed the same day: in-session resume reuses saved takes (long-form retry no longer degrades to line-separated), single-segment regeneration appends fail-closed accepted-replacement history (revision ≥ 2 with recorded seeds), migration v5 adds project columns keyed by plan digest, the assembled output persists as the project's single joined History row, and the History list groups projects with an expandable per-segment map. Per-project joined/manifest filenames remove a cross-project overwrite. Live in-app acceptance passed 2026-07-23 (smoke run `macos-xcui-smoke-20260723-195700-ab46482a`, 6/6 journeys): a 2,280-character script planned three ~60 s segments, streamed them sequentially, joined 3.83 M frames with a v4 manifest (plan+execution+assembly), and grouped as a History project with a working segment map — after the acceptance arc fixed the zero pause-budget app gate, tightened the planner to the delivery-validated 300-unit ceiling, calibrated duration-aware dropout thresholds, and eliminated a deterministic -O-only crash in manifest validation (OPTIMIZATION.md §K addendum). Live segment preview is enabled (auto-play-gated), the performance gate holds across the whole run (segments + QC + assembly), and the smoke lane now measures the project: first instrumented run 161.5 s of audio in 92.0 s wall, project RTF 1.76 — inside the canonical gated single-take band. Ordinary line batch is unified onto the same sequential streaming path (mandatory per-take engine QC, streaming telemetry, live preview). The caller-less legacy XPC `generateBatch` route — wire case, batch-progress channel, client/store wrappers, and both registered progress-relay `@unchecked Sendable` boxes — was retired 2026-07-24; the in-process engine batch API remains for the CLI. iOS long-form shipped 2026-07-24 (ADR amendment 2026-07-24b): the same design runs in-process on device — scripts over 900 characters route through `IOSLongFormCoordinator`/`IOSLongFormProjectRunner` with the shared planner, per-segment QC via the ported `AudioQualityGate` twin, bounded assembly, manifest v4, v5-column History with grouped project rows and a per-segment disclosure, in-session resume, and a sustained-performance hold on the fixed-refresh glass gate; single-segment regeneration remains macOS-only, and line batch remains intentionally absent from iOS (long-form is the device-validated sequential-streaming design the batch-removal invariant demanded). Device acceptance passed 2026-07-24 on the paired iPhone 17 Pro (smoke run `ios-xcui-smoke-20260724-183626-f9961535`, both journeys green): a >2,000-character script planned three segments (55.0 + 45.4 + 26.6 s), joined 127.2 s of audio, and grouped as a History project with a working per-segment map. |
| 12 — Bounded analysis and unified quality | Partial. Bounded prosody algorithm v2 is shipping; persisted-WAV consolidation and the typed registry/scheduler are not integrated. |
| 13 — Benchmark/history v3 | Not started; schema v2 remains authoritative until shipping plan/session/quality identities stabilize. |
| 14 — Organization and retirement | 14a closed 2026-07-23: the combined characterization session (`VocelloQwen3ModelGenerationSession`, its protocol/event types, and event channel), the product/priming stream APIs (`generate*Stream`, stream-based Clone priming), and the adapter filename (`GenerationOutputAdapter.swift` now holds `GenerationOutputAdapter`) are retired; Clone priming uses the completion-variant generate path. 14b closed the same day: prepared-model loading, post-load facts, preparation diagnostics, priming, and schema-3 clone-artifact persistence/adoption are actor-owned public surfaces (`load`+verbose sink, `loadedModelFacts`, `preparationDiagnostics`, `prime`, `persistCloneArtifact`/`adoptCloneArtifact`, `isCloneHandleValid`); the `VocelloQwen3LegacyCompatibility` SPI is retired with its symbols internal, `UnsafeSpeechGenerationModel` is a plain-`Sendable` actor/facts pairing, and clone conditioning flows as epoch-bound handles end to end. Contract `mechanicalRetirement`: `phase14-complete-2026-07-23-spi-retired-actor-owned-loading-metadata-priming-and-clone-artifacts`. |

**2026-07-22 amendment (maintainer-endorsed).** The backend refactor review counter-verified the
research corpus (imported under [`docs/research/`](research/)) and ran the R1 characterization
gate on the canonical Mac mini. Verdict: engine code is innocent of the post-cutover canonical
macOS slowdown — the app/XPC delivery topology starves the engine of GPU submissions (diagnostic
records `macos-engine-20260722-210927-3553c1b1`,
`macos-xcui-benchmark-20260722-{211254-273bd16d,213731-c47b0d27}`; raw Metal trace summarized
then discarded per policy). Three endorsed changes now live in `amendment20260722` of the
contract: phase 7 rescoped to the delivery-pipeline pacing fix, promotion matrices must include
a UI/app-XPC-context cell (`promotedMatrixRequiresUIContextCell`), and phase 14 retirement is
scheduled directly after the phase 7–9 block.

The post-cutover deterministic proof passed `scripts/macos_test.sh test`, including Core, XPC
transport, and 103 owned-runtime tests. The arm64 macOS build and generic iPhoneOS SDK app plus
policy-test compilation also passed without contacting a device. Runtime, documentation, vendor,
build-output, project-input, and benchmark-history contracts passed. Focused macOS runs
`macos-xcui-benchmark-20260717-192747-0ae9d73c` (Custom 2/2),
`macos-xcui-benchmark-20260717-193323-f8506265` (Design 2/2), and
`macos-xcui-benchmark-20260717-193608-51fef175` (Clone 1/1) each passed with complete ordered
engine/service/app evidence, readable output, Fast QC, and no crash delta. They are exploratory
`passedWithWarnings` records because the worktree is dirty and each observed an allowed soft trim;
they are focused parity evidence, not clean canonical controls. Physical-iPhone Phase 4 evidence is
also complete on the exact dirty worktree fingerprints: runs
`ios-xcui-benchmark-20260719-133203-d413fac1` (Custom 2/2),
`ios-xcui-benchmark-20260719-134041-9653f7cf` (Design 2/2), and
`ios-xcui-benchmark-20260719-134646-d90db984` (Clone 1/1) passed with complete ordered engine/app
evidence, readable output, Fast QC, and no crash delta. They are exploratory
`passedWithWarnings` records because each observed an allowed soft trim. These five focused takes
close the focused physical-iPhone Phase 4 acceptance requirement, but they are not clean repeated
controls or a full canonical matrix.

### Post–Phase 0 canonical UI matrices — 2026-07-20

Clean-tree 29-take UI matrices after Phase 0 close (`610125b`). Canonical scope;
`passedWithWarnings` for allowed soft_trim only. Secret-sauce short cells PASS on both.
Roadmap cross-check:
[`docs/reference/qwen3-apple-silicon-roadmap-review.md`](reference/qwen3-apple-silicon-roadmap-review.md).

| Platform | Label / record |
| --- | --- |
| macOS | `post-phase0-matrix-20260720` → `macos-xcui-benchmark-20260720-172920-591696d1` (smoke PASS; 29/29; soft_trim) |
| iPhone | `post-phase0-ios-matrix-20260720` → `ios-xcui-benchmark-20260720-174441-16fc128c` (preflight OK; 29/29; soft_trim; smoke skipped — History `historySearchField` flake) |

### Pre-research UI baselines — 2026-07-19

Exploratory dirty-worktree 29-take UI matrices (soft trim → `passedWithWarnings`), superseded for
promotion evidence by the 2026-07-20 post–Phase 0 canonical matrices above.

| Platform | Label / record |
| --- | --- |
| macOS | `pre-research-baseline-20260719` → `macos-xcui-benchmark-20260719-215547-11f8f4cf` |
| iPhone | `pre-research-baseline-ios-20260719` → `ios-xcui-benchmark-20260719-224743-1e69da39` |

### Cutover gate — closed 2026-07-20

The Phase 0–6 cutover prerequisites and `overallPromotion: passed` are on protected `main`.
Historical checklist (all done):

1. ~~Fixed-seed pairs (2026-07-19):~~ macOS CLI and physical-iPhone headless Custom/Design/Clone
   Speed short with seeds `19790615` (equal pair) and `42424242` (diverge) all PASS via matching/
   diverging SHA-256 WAV digests (local under `build/scratch/transient/phase5-seed-pairs/` and
   `phase5-seed-pairs-ios/`). Prefer telemetry `samplingSeed`/`samplingWAVDigest` +
   `SamplingTakeEvidence.validatedForPromotion()` for promotion packaging; these digests are live
   identity proof only.
2. ~~Secret-sauce latency/memory cells (2026-07-19):~~ focused UI short captures
   `secret-sauce-20260719` → `macos-xcui-benchmark-20260719-233834-98038639` and
   `secret-sauce-ios-20260719` → `ios-xcui-benchmark-20260719-234454-7df6a1e0` PASS
   `scripts/check_secret_sauce_cells.py` (required metrics present; soft_trim only; no hardTrim /
   fullUnload). Exploratory dirty-worktree records, not clean promotion controls.
3. ~~Nested-v9 producers + platform pilots (2026-07-19/20):~~ exact codec-frame ranges, lossless
   audio-channel statistics, chunk audio ranges, and model/product terminals land in the nested
   transition via `GenerationOutputAdapter` + owned Qwen stream schedule. Engine-domain nested
   transitions are publication-ready while listing non-blocking `notApplicable` transport/player
   gaps. macOS: `scripts/macos_test.sh test` + CLI verbose generate + UI smoke. iPhone: rebuilt
   install + headless Custom/Design/Clone Speed short (seed `19790615`) all engine-ready under
   `build/scratch/transient/v9-ios-pilot/` (blocking unavailable empty) + UI smoke PASS.
   Schema-v8 JSONL remains authoritative until history consumes complete v9 sidecars.
4. ~~Phase 0 live characterization (2026-07-20):~~ Mac CLI ×3, Mac UI ×3, iPhone UI ×3
   short Speed warm-10 controls PASS. Records listed in
   `config/characterization-fixtures.json` → `controlSessions`. Short
   `promptDigest=1693d060…` (35 chars); long `promptDigest=f1b3eae6…` (344 chars). Fixtures
   `status: closed`; `liveEvidencePending` cleared. Note: full iPhone smoke still flakes on
   History `historySearchField` hittability; generation UI benchmarks are unaffected.
5. ~~Fresh full 29-take matrices (2026-07-20):~~ macOS
   `macos-xcui-benchmark-20260720-172920-591696d1` and iPhone
   `ios-xcui-benchmark-20260720-174441-16fc128c` both canonical 29/29 PASS
   (`passedWithWarnings` / soft_trim only).
6. ~~Phase 5 promotion packaging + Phase 6 v9 sidecar authority (2026-07-20):~~
   `SamplingTakeEvidence.packagedTelemetryNotes()`, complete v9 sidecar publish path,
   history evidence keys for sidecar digests, and contract telemetry v9.
7. ~~`overallPromotion: passed` (2026-07-20):~~ claimed after Phase 0/5/6 close plus
   canonical macOS/iPhone 29-take matrices.

### Next convergence fork

Phases 7, 8, and 14 all closed 2026-07-23 (UI-context gap via the generation performance gate,
live all-artifact shared-component validation, and full mechanical retirement including 14b SPI
evaporation).

**2026-07-25 — optimization report counter-verified; staged plan adopted.** The external
2026-07-24 launch-bound optimization report was imported
([`docs/research/launch-bound-optimization-report-2026-07-24.md`](research/launch-bound-optimization-report-2026-07-24.md))
and counter-verified claim-by-claim (three parallel code audits + independent re-verification
of every external source). Its launch-bound thesis matches §H P0 verbatim; six of its
recommendations were already shipped, its cross-variant backbone-sharing premise is
inapplicable (three distinct checkpoints, one resident), and two of its migration flags are
wrong (the 2.30.6 pin already carries `maybeQuantizeKVCache(quantizedKVStart:)` and
`WiredMemoryTicket`). The superseding staged plan — Stage 0 near-free quality wins (clone
reference silence append, boundary gate, duration-directive guardrail, repetition-penalty
A/B), Stage 1 launch-bound attack on current pins (host-sync collapse + pipelining,
code-predictor compile, codec-stream overlap, gated talker static-shape experiment), Stage 2
memory program folding phase 9 (speech-tokenizer runtime reuse, text-embedding quantization,
codec bf16, clone prompt release), Stage 3 quality harness folding phases 12→13, Stage 4
gated pin-bump/carryover/parked bets — lives in
[`docs/reference/optimization-report-review-2026-07-25.md`](reference/optimization-report-review-2026-07-25.md).

Remaining work now follows the staged roadmap (details and falsifiability criteria in the
review doc):

1. ~~**Stage 0 — near-free quality wins**~~ — **completed 2026-07-26** in four commits
   (`b16167d`, `5fc0f3c`, Stage 0.3 delivery advisory, `f97598a`): the clone reference
   silence append shipped with a versioned conditioning identity
   (`qwen-speaker-mel-v1+icl-ref-silence500ms-v2`, fail-closed artifact migration verified
   live), the long-form boundary jump gained a warn-first manifest advisory (>4096 PCM16
   units), both apps advise on duration-style delivery directives (shared EN/FR detector,
   never blocking), and the repetition-penalty A/B kept 1.05 (1.10 showed no
   deterministic-QC win; the gated `QWENVOICE_TALKER_REPPEN` knob remains for diagnostics).
   Measurements and the pre-existing clone/long dropout-band finding:
   `benchmarks/OPTIMIZATION.md` §L.
2. **Stage 1 — launch-bound attack on current pins** (§H P0 successor program; **in progress
   2026-07-26**, measurements in `benchmarks/OPTIMIZATION.md` §M): P2a-i (pipelined chunk
   materialization) landed with byte-identical fixed-seed output and clone warm RTF
   +1.6/+3.3/+0.5%; the P2a-ii early-submit variant measured as a do-NOT (custom/long −3.9%)
   and is reverted with its record kept. **P3 (compiled code-predictor) landed the program's
   largest win: +8.3% to +10.6% warm RTF on every cell** (clone/long 1.128 → 1.243) with
   byte-identical shipping output — MLX compile's fp32 fusion rounding sits below bf16
   resolution. P5b (codec on a dedicated stream) measured as a second do-NOT (−0.4% to −4.3%
   on every cell) and is reverted with its record kept — the emerging law: remove host
   graph-build work, never add command buffers. The stage-exit GPU-busy re-capture
   (2026-07-26, §M) read **still launch-bound** (~49% busy, ≪85%), and the P1b static-shape
   talker compile ran as its branch experiment (`feat/p1b-static-talker-compile`,
   delta `DECODE-002`): **correct — eager-equivalent and byte-identical — but flat** (±1%
   decode-wall), the graph-build savings cancelling against the padded-attention tax.
   **Stage 1 closed 2026-07-26** at a net landed +10.8% clone/long (1.122 → 1.243) with
   byte-identical output throughout; the residual step-eval launch-gap idle is a 0.30.6
   structural ceiling whose re-test rides the Stage 4 pin bump. The program proceeds to
   Stage 2 (memory).
3. **Stage 2 — memory program (folds phase 9)**: speech-tokenizer runtime reuse across mode
   switches (the RAM analog of the shipped disk hard-linking), text-embedding quantization
   experiment (622 MB BF16 today inside the "4-bit" artifact), codec bf16 experiment
   (fp32 today; keep final decoder layers full precision), clone-prompt release after the
   conditioning prefix is built.
4. **Stage 3 — quality harness (folds phase 12, then 13)**: wire the typed
   `GenerationQualityReport` registry producers and persisted-WAV consolidation, add a
   dev-lane speaker-similarity gate for clone fidelity, optional advisory MOS-proxy column;
   then benchmark/history v3 once identities stabilize.
5. **Stage 4 — gated migrations/research**: mlx pin bump 2.31.3/0.31.3 on a throwaway branch
   (contract invariant), long-form carryover (history-aware text context first), with
   speculative/PCG, CFG, and KV quantization parked.
6. **Smaller open threads** — ~~§H P0 GPU-busy re-capture~~ (done 2026-07-24: whole-generation
   GPU busy 31–37% → ~47% on the shipping runtime, still launch-bound; OPTIMIZATION.md §H P0
   addendum), iOS single-segment regeneration parity, the iPhone-15-Pro memory-profile
   diagnostic, a 60 Hz-device measurement of the iOS fixed-refresh glass gate if such
   hardware becomes available, and single-take spoken-text normalization (phase 10
   remainder).
7. ~~**iOS 900-character single-take limit**~~ — shipped 2026-07-24.
   `IOSGenerationTextLimitPolicy.sharedScriptLimit` 150 → 900, aligned with the macOS long-form
   router threshold, gated on an on-device memory-qualified proof: headless 888-character
   custom/speed take on the canonical iPhone 17 Pro (`ios-engine-20260724-060000-1cc8ef23`,
   published) — RTF 1.57, physFoot peak 2,825 MB (inside the proven flat ~2.4–3.3 GB streaming
   band), 100% sampler coverage, zero pressure/warning events, QC pass; `passedWithWarnings`
   only for one allowed soft trim. The iOS UI-benchmark `long` cell keeps its fixed
   150-character text for history comparability.

Status report: [`docs/reference/runtime-refactor-status-report.md`](reference/runtime-refactor-status-report.md).
You-are-here map: trust `config/runtime-refactor-contract.json` over any older “promotion pending”
paragraph.

### Local storage-policy verification — 2026-07-18

The storage-containment/build-policy worktree passed its macOS deterministic tests and arm64 app
build after bounded cleanup. The host toolchain block recorded on 2026-07-18 is resolved: Xcode
26.6 now exposes its iOS 26.5 SDK and compatible iOS 26.5 runtime component, and both the generic
physical-device SDK destination and paired physical iPhone are eligible. The platform preflight,
device preflight, and focused Phase 4 XCUITest runs passed on 2026-07-19.

All repository iOS build routes run `scripts/lib/ios_platform_preflight.py check` before cache
creation or package resolution. The preflight remains read-only and accepts an available runtime
with the selected SDK's major/minor platform version even when Apple's SDK and runtime patch-build
identifiers differ. Restoring that component does not authorize Simulator execution.

## Current implementation

- Native app UI acceptance uses one shared XCUITest stack: `macos smoke|benchmark` on the native
  Mac host and `ios smoke|benchmark` on a paired physical iPhone.
- UI execution is explicit frontend QA. It is not required to commit, push, open or merge a pull
  request, run ordinary CI, package a release, or create an iOS archive.
- The ordinary iOS compile lane now typechecks both the app and a standalone app-host-free policy
  XCTest bundle for the generic physical-device SDK. It covers catalog/ledger, memory policy,
  cancellation, storage-path gating, and diagnostic redaction without a phone. Xcode 26 rejects
  tool-hosted app-free XCTest execution on physical-device destinations, so this target remains
  compile-only and device runtime proof stays in the headless diagnostics and XCUITest lanes.
- The physical-iPhone smoke contract now covers two distinct cancellation paths. It first cancels
  one active stream through the genuine visible Cancel control, then relaunches with the registered
  one-shot critical-memory diagnostic, requires typed `memory_pressure` cancellation to complete
  before `fullUnload`, and proves the same engine surface can complete a subsequent generation.
  Pulled run-scoped diagnostics own the pressure-event ordering verdict; unknown toggle values fail
  closed and are never tapped. Physical-iPhone run
  `ios-xcui-smoke-20260716-172350-2c6828e1` passed the expanded contract: the visible user
  cancellation and typed critical-memory cancellation both terminated without entering History,
  `fullUnload` followed the pressure cancellation, and the same engine completed and persisted the
  recovery generation.
- Generation ownership is explicit across all hosts. Final core audio uses the actor-owned,
  frame-bounded suspending channel. Frontend preview/status events use a separate per-generation,
  bounded suspending router, so audio-bearing preview events are never evicted by a
  `bufferingNewest` policy. `ActiveGenerationCoordinator` admits one active product
  task, carries typed user, memory-pressure, superseded, or shutdown cancellation, and awaits both
  model terminal and product cleanup/finalization before trim, unload, or ownership release.
- The runtime/streaming convergence program is active under
  `config/runtime-refactor-contract.json` and
  `docs/decisions/runtime-streaming-quality-convergence.md`. Its correctness prerequisites are in
  the current product path: macOS XPC reserves before creating generation side effects, pressure
  snapshots are synchronized, and critical relief closes admission continuously from cancellation
  through terminal cleanup and trim. Immutable product/core/evidence plans also run in independent
  shadow comparison, but shadow mode never starts a second model generation.
- Sampling algorithm v2 and Qwen generation-memory policy are shipping request-owned contracts.
  Every request records an effective seed and uses a fresh `MLXRandom.RandomState`; independently
  configurable talker/subtalker sampling and per-request cache cadence/window policy no longer rely
  on mutable generation globals. Existing canonical schema-v2 benchmarks predate this runtime
  change and remain valid historical evidence only. The focused macOS Custom/Design/Clone parity
  runs now pass on the current worktree on both macOS and the physical iPhone; clean repeated
  controls, the applicable full canonical matrices, and exact legacy characterization remain
  required for full promotion.
- `VocelloQwen3Engine`, the classified session, and QwenVoiceCore's
  `GenerationOutputAdapter` are now the source-level shipping generation path for Custom, Design,
  and Clone. Lazy MLX audio is evaluated and copied to `[Float]` before
  the producer awaits the size-aware channel, so a delayed mandatory drain backpressures the actual
  token/decode loop without moving an `MLXArray` across a task or actor boundary. The adapter drains
  every frame, preserves the existing limiter/WAV/Fast-QC/telemetry behavior, publishes one product
  terminal, and returns the generation/lease/finalization token before ownership can release.
  Phase 14b (2026-07-23) moved prepared-model loading, post-load facts, preparation
  diagnostics, priming, and schema-3 clone-artifact persistence/adoption onto the actor; the
  legacy compatibility SPI is retired and the actor owns every runtime lifecycle operation the
  product can reach.
  The actor's remaining correctness gaps are also closed: `reserved`, `generating`, and `aborting`
  lifecycle ownership prevents an abort-owned reservation from reopening generation and makes
  duplicate aborts join the same finalization. Typed cache-trim or full-unload relief carries the
  generation lease directly through critical relief and reopens admission only after the
  revalidated relief operation completes. A rejected atomic relief claim clears only its matching
  ownership before crossing the session barrier again; ordinary finalization therefore releases
  the generation lease in both possible acknowledgment orderings instead of stranding it.
  Clone conditioning remains tensor-opaque behind epoch-bound handles. The actor retains one handle
  by default, supports an explicit bounded capacity with LRU eviction, and makes repeated release
  fail closed. A reservation keeps the prompt it already captured; noncritical cache trim preserves
  otherwise valid handles, while model reload, critical trim, and full unload invalidate them.
  Shipping schema-v8 rows remain authoritative and embed only a partial v9 transition projection;
  Phase 4 does not complete the v9 writer/merger/publication path. Telemetry v8/evidence v2,
  manifest v3, persisted Fast QC, and the existing specialized gates remain operational truth.
  Focused physical-iPhone Phase 4 acceptance and the clean full-matrix promotion evidence both
  passed (2026-07-20 promotion, 2026-07-23 gated re-baseline); sequential streaming long-form,
  complete v9 publication, and history v3 remain pending (Phases 11–13).
- Clone conditioning is typed as transcript-backed or genuine audio-only x-vector. Both apps own
  the visible `voiceCloning_consentAcknowledgment` in Settings, persist the choice locally, and
  keep Clone Generate disabled until consent is acknowledged. Smoke and benchmark enable it through
  that real Settings control for later testing; there is no hidden test-state override. The two
  conditioning modes retain distinct cache and artifact identities.
- History persistence now fails closed with typed privacy-safe errors. An unavailable database is
  never presented as an empty library and destructive actions remain disabled; iOS exposes a Retry
  control, while macOS retries on reload or re-entry.
- Headless iOS generation, language, profiling, crash, and memory diagnostics use
  `IOSDeviceDiagnosticsRunner` through `scripts/ios_device.sh`. This is a non-UI diagnostic lane,
  not a second app driver.
- The iOS diagnostic Clone path requires the exact prepared voice ID. The canonical fixture is a
  transcript-backed Voice Design reference; a Custom Voice output is not an acceptable substitute.
- A compile-gated `scripts/ios_device.sh clone-conditioning` acceptance lane now runs exactly two
  clone takes in one physical-iPhone app/engine process: the canonical transcript-backed saved
  voice followed by an exact sidecar-free audio copy using genuine x-vector-only conditioning. It
  validates distinct prompt identities, typed runtime flags, output/ASR, telemetry-v8 memory, app
  correlation, crash delta, and scratch cleanup, then writes local evidence only. Local run
  `ios-clone-conditioning-20260716-162518-ea8e8989` passed both conditioning modes with strict
  output/ASR, memory, correlation, crash, and cleanup checks. It intentionally published no
  benchmark-history record.
- No preview/browser-mirror route, invisible accessibility state marker, alternate UI driver,
  coordinate bridge, or hidden UI bootstrap belongs in the shippable app.
- Model delivery uses one shared integrity/atomic-install implementation. iPhone now owns one
  bundle-aware app-lifetime background session plus an atomic schema-v2 request ledger, exact task
  adoption, cancellation barriers, durable delegate staging, and bounded privacy-safe diagnostics.
  macOS and CLI retain foreground delivery with terminal session teardown. Cancel discards staging;
  Retry reuses verified files. The isolated `scripts/ui_test.sh ios model-download` lifecycle proof
  is explicit QA and never joins smoke, benchmark, CI, packaging, or release gates. The 2026-07-14
  isolated Custom Speed proofs passed on both canonical platforms: macOS verified and removed its
  temporary 2.31 GB install, while the physical-iPhone test preserved monotonic progress across
  backgrounding, termination, and relaunch, installed with exact wire bytes and no retry, then
  deleted the isolated model through visible Settings. No connection or chunking default changed.
  Post-policy run `ios-xcui-model-download-20260716-163359-61377762` refreshed the physical-iPhone
  proof: expected and wire bytes both equaled 2,312,057,897, with zero retries or duplicates, one
  accepted provider redirect, HTTP/3 plus HTTP/1.1, nominal thermal state, final integrity, visible
  isolated cleanup, and all canonical model states preserved.
- iOS model cancellation now treats its ledger writes as authorization barriers. The coordinator
  durably records cancel intent and the deleted tombstone before task/staging destruction or a
  deleted UI state; a storage failure preserves recoverable state and cannot become a queued request
  after relaunch.
- The generated cross-platform production model catalog schema v2 is complete for all six
  Speed/Quality artifacts, with exact pinned revisions, sizes, per-file SHA-256 identities, and the
  shared `speech_tokenizer` content/compatibility identity. macOS, CLI, and iOS now resolve the
  same delivery plan; verified component blobs can omit exact bytes from a later download and new
  installs publish ordinary hard-linked model files atomically. Schema-v1 documents remain
  read-compatible. Resolving a schema-v2 delivery plan now authenticates all catalog files in an
  existing installation and automatically migrates or repairs its shared-component presentation;
  failed authentication contributes no reusable bytes and falls back to ordinary network repair.
  Live validation completed 2026-07-23 on both canonical platforms (six-artifact isolated Mac
  run and three-artifact iPhone lane with exact shared-component reuse; see
  `docs/reference/model-delivery.md`). The earlier isolated
  macOS/CLI Custom Speed proof at source `9a8da874…` transferred exactly 2,312,057,897 expected and
  wire bytes with zero control or duplicate bytes, zero retries, nominal thermal state, and final
  integrity. Its bounded foreground delegate ingress preserved terminal staging and metrics before
  completion, then the isolated 2.31 GB payload was removed.
- Benchmark evidence now uses collision-resistant run IDs, atomic run-scoped manifests, and a
  privacy-safe PASS-only registry. `benchmarks/HISTORY.md` is generated from canonical JSON records;
  raw telemetry, audio, screenshots, traces, and `.xcresult` bundles remain untracked.
- The canonical comparison hardware is the Mac mini `Mac14,3` (Apple M2, 8 GB) and iPhone 17 Pro
  `iPhone18,1`. Filtered runs are focused, dirty runs exploratory, and Instruments runs
  instrumented; those classes are not silently mixed into canonical timing trends.
- Generation telemetry schema v8 plus benchmark-evidence manifest v2 make RAM/pressure evidence a
  publication contract rather than optional summary data. Exact run-scoped sample sidecars carry
  start/periodic/boundary/stop samples and absolute uptime; summary counts must match, capture
  failures must be zero, and sampler coverage must be at least 95%. Critical pressure, app memory
  warnings/exits, `hardTrim`, and `fullUnload` fail publication; guarded pressure, `softTrim`, and
  95–<100% coverage are explicit warnings. macOS totals pair app and engine samples by uptime rather
  than adding independent maxima.
- CPU and memory Instruments lanes use exact-PID attachment. `profile --kind memory` records CPU
  Profiler, Allocations, VM Tracker, and `os_signpost` together; publication requires target-PID
  rows from every exportable memory schema and labels a configured but non-exportable track
  explicitly instead of claiming row verification. The separate `memory` lane runs the versioned retained-memory sequence and
  publishes `memory-qualification` only when within-mode retained-take growth stays within policy. The iOS
  `memory-field-report` command reads already-pulled,
  privacy-reduced delayed MetricKit summaries only; absence is `notYetDelivered`, not failure.
- Raw Instruments documents are diagnostic, not durable benchmark history. Successful profiles
  publish their validated digest/settings/extracted summary and then discard the raw trace unless
  `--keep-trace` was explicit. Routine cleanup also bounds failed profiles, superseded XCUITest
  results, and scratch DerivedData while preserving the current app, canonical caches, dSYMs, and
  external models. Benchmark results without a valid registry record remain available for
  idempotent publication repair; compile-safety scratch builds use only
  `build/scratch/derived-data/` and self-remove on exit.
- Generated output is classified by `config/build-output-policy.json`: two persistent platform
  Xcode caches, one shared package checkout, ephemeral scratch builds, bounded evidence/current
  symbols, and release-only `build/dist/` outputs. Public `build/Vocello.app` and `build/vocello`
  paths are symlinks to canonical macOS products; local macOS products are arm64-only.
- Repository storage inventory now distinguishes automatically eligible, blocked, and explicitly
  acknowledged evidence. UI lifecycle retention covers smoke, benchmark, and model-download lanes;
  failed raw profile traces require an exact run ID for manual compaction, while superseded or
  resolved failures compact automatically; platform/package/runtime caches can
  be removed independently. Manifest-owned free-space preflights stop heavy lanes before they create
  partial output, while ordinary successful builds remain non-destructive.
- Codex task/session storage is now a separate optional operator workflow rather than repository
  build-output policy. Its tracked schema and helper enforce aggregate metadata-only inventory for
  plain and cold-compressed rollouts, explicit current-root protection, a temporary checksummed
  descendant plan, deepest-first supported CLI deletion only after exact approval, an evolving
  non-target preservation baseline after every command, and post-verification. CI validates only
  the policy and synthetic temporary-home fixtures; live Codex state, manifests, journals, and
  identifiers remain local and never become publishing or release-evidence inputs.
- The Qwen3/Mimi implementation is now an explicitly owned monorepo core package at
  `Packages/VocelloQwen3Core`. Product targets depend on the `VocelloQwen3Core` facade, whose typed
  model-bundle, capability, sampling, memory, request, terminal, cancellation, and diagnostic
  contracts isolate application code from implementation modules. Product generation now uses
  `VocelloQwen3Engine`, its classified session, and QwenVoiceCore's
  `GenerationOutputAdapter`; loading, metadata, priming, and clone-artifact adoption are
  actor-owned public surfaces (the legacy compatibility SPI retired 2026-07-23). The legacy `MLXAudio`
  package, products, targets, modules, and public APIs remain available behind the facade for
  implementation compatibility; synthesis behavior and persistent identities did not change.
  Immutable lineage, compatibility, ownership, and runtime-capability contracts replace
  patch-stack governance. Phase 14 (2026-07-23) retired the combined characterization session, the
  stream generation/priming APIs, the old adapter filename, and — via 14b actor-owned loading —
  the named SPI itself.
- Runtime trust boundaries are machine-readable. `config/runtime-debug-knobs.json` makes every
  production-affecting environment override inert without the `QWENVOICE_DEBUG` master gate;
  `config/concurrency-safety.json` inventories and justifies every owned unchecked/unsafe
  concurrency declaration. Release/QA orchestration, evidence impact, project health, supply-chain,
  and release-candidate evidence are likewise governed by tracked contracts.
- Release-candidate evidence is now schema v2 and fail-closed. It begins from a clean full-tree
  source identity, accepts required checks only when the managed release runner executes them in
  one invocation, enforces a six-hour creation-time freshness window, and carries the exact ledger
  and step manifests inside a hashed `release-verification.json` bundle for offline asset review.
  Each managed release step is also bound to its contract-defined command template and declared
  outputs. The iOS candidate cannot reach archive/export until the same ledger has run the
  deterministic macOS gate and generic iOS device-SDK compile. It cannot proceed from export to
  evidence until a non-device schema-v2
  verifier has proved archive/IPA bundle version, build, identifier, arm64 UUID plus
  signature-normalized code continuity, root privacy-manifest identity, entitlements,
  locally trusted profile-authorized certificates, and configured team/App ID prefix consistency. App Store
  provisioning, Apple Distribution signing, and `get-task-allow` absence apply to the exported IPA;
  the archive may use either valid Apple development or distribution signing.
- The telemetry-overhead observer-effect diagnostic keeps its verdict under
  `build/artifacts/macos/` and does
  not publish schema-v2 history. Its `off` lane deliberately constructs no sampler, so requiring
  in-process memory evidence there would change the experiment rather than qualify it.
- A clean canonical macOS schema-v2 baseline exists, and a clean canonical iPhone schema-v2
  baseline exists, for the pre-convergence owned Qwen3 implementation. Mac mini M2 8 GB run
  `macos-xcui-benchmark-20260716-181853-b4c2e299` at source `9a8da874…` and iPhone 17 Pro run
  `ios-xcui-benchmark-20260716-184106-48e3a3a6` at source `bcb5265a…` each completed the exact
  29-take matrix with telemetry schema v8, complete layer correlation, qualified memory evidence,
  clean crash deltas, and the allowed `memory.pressure.soft_trim` warning. Earlier canonical
  records remain valid for their recorded source identities but do not promote the request-local
  sampling/memory or shared-component changes in this worktree; dirty records remain exploratory
  and are excluded from canonical trends.
- The physical-iPhone language lane predeclares a one-based, fixed-seed run plan; retains only the
  exact selected WAV and telemetry evidence; requires three-pass locale-locked on-device Speech
  consensus; and offers a retry-free 15-take diagnostic cohort that never publishes history. Its
  version-2 corpus uses at least 15 normalized words per alphabetic script and 24 normalized
  characters per CJK script, pins Design to the known language, and records language-appropriate
  Custom speakers where the Qwen contract supplies one. Custom pinned/Auto pairs test hint
  equivalence, while the three Speech passes test recognizer reproducibility; neither is counted as
  independent audio evidence.

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
explicit macOS fixture repair/bootstrap step.

2026-07-22 — UI QA architecture decision (round trip, same day): computer-use vision driving was
trialed as the autonomous UI driver and retired within hours — mirror keyboard focus decays,
popovers swallow batched clicks, per-action round-trips cost seconds, and per-take environment
injection/telemetry correlation is impossible. XCUITest returned as the sole autonomous driver in
a ground-up v2 stack: typed/scoped element queries (root cause of multi-second finds and
accessibility-snapshot timeouts), automatic on-failure desktop + element-tree evidence, a launch
obstruction preflight, an interruption-monitor sentinel that names blocking system dialogs without
answering them, a `/tmp` virtual-mic fixture (app-data TCC fix), five ordered state-hygienic smoke
journeys including restored mid-generation cancellation coverage, an advisory `ui-preflight` TCC
check, and two-phase lane execution (skippable `build-for-testing` + `test-without-building`).
Computer use remains assistive for exploratory QA and failure diagnosis
([`reference/interactive-ui-qa.md`](reference/interactive-ui-qa.md)) — during the trial it
identified the app-data and speech-recognition TCC dialog classes no log surfaced.

v2 acceptance (2026-07-22): macOS smoke passed 5/5 twice back-to-back (state hygiene; repeat-lane
wall 295 s with the build skip active, cold 470 s), the canonical 29-take macOS benchmark passed
with full validator/telemetry evidence and published
`macos-xcui-benchmark-20260722-172102-48c4a193` (label `v2-stack-acceptance`), and the
physical-iPhone smoke journey passed with pulled-diagnostics validation. The first v2 run's three
failures were diagnosed in minutes from the harness's own desktop/element-tree evidence: the Xcode
26 test runner cannot write `/tmp` (fixture synthesis moved into the lane), and SwiftUI propagates
row identifiers onto child elements (History assertions count unique identifiers).

2026-07-22 — Development-flow automation: gates are tiered (T0 iterate, T1 hook-enforced commit
gate with a fingerprint cache, T2 path-aware CI, T3 tag-gated release), development is trunk-based
on `main` with pushes watched and triaged from `gh run watch`, and branches are reserved for risky
work landed via auto-merge. CI gained a change-routing job, a SwiftPM cache for the macOS test
job, and a `CI required` aggregator that is now the sole branch-protection context. The commit
hook blocked its first real defect (a stale project-health summary) within minutes of activation.

2026-07-22 — Backend review, characterization gate, and roadmap amendment: the five external
research documents were counter-verified (~90 claims; zero outright errors, staleness only) and
imported under [`docs/research/`](research/) with inline editor's notes. The R1 characterization
gate then localized the post-cutover canonical macOS RTF decline to the app/XPC delivery topology
(engine flat at 1.02–1.17 in interleaved CLI A/B across the cutover; 0.69–0.81 in the UI lane;
submission-starved per the Metal System Trace, zero lossless-channel producer suspensions). The
maintainer-endorsed `amendment20260722` rescoped phase 7 to the delivery-pipeline pacing fix,
required a UI-context cell in future promotion matrices, and pulled phase 14 retirement forward.
The same day, GitHub's mixed macOS runner-image roll flapped the exact-version toolchain gate;
xcodegen (2.46.0) and ripgrep (15.2.0) now install from SHA-pinned release artifacts via
`scripts/install_pinned_tools.sh` in every native CI job. The §H P0 GPU-busy re-capture (a clean
CLI-context Metal trace) remains open follow-up work alongside the phase 7 implementation.

**2026-07-23 — Phase 7 characterization resolved the macOS decline as a benchmark observer
effect** (`benchmarks/OPTIMIZATION.md` §J): XCUITest's default automatic screen recording
(`testmanagerd` → `VTEncoderXPCService`/`replayd`) video-encoded the display through every UI
take; disabling it (`preferredScreenCaptureFormat: screenshots` on both UI schemes in
`project.yml`) moved the one-cell custom/long lane from warm RTF 0.70–0.78 to **1.196** with
clean QC. Engine code was exonerated by flat interleaved CLI A/B across the cutover, and a
one-off `-O` CLI bench measured true Mac capability at **1.81** (all prior CLI numbers were
`-Onone` dev builds). Three experimental engine-loop changes from the diagnosis were reverted
after two intermittent Fast-QC hard failures appeared with them in-tree (12/12 takes clean after
revert); the surviving instrumentation is per-generation `processTaskRole`/QoS/nice telemetry.
Pre-2026-07-23 UI-generation records carry the recording overhead in every cell; the amendment's
phase-7 objective (delivery-pipeline pacing) is now re-aimed at the remaining honest ≈1.2→1.8
UI-context gap.

## Open release work

- macOS 2.2.0 was released 2026-07-25 (tag `v2.2.0`, published with the notarized DMG, SBOMs,
  checksums, and schema-v2 evidence; notes at `docs/releases/v2.2.0.md` carry the first recorded
  Evidence section — smoke run `macos-xcui-smoke-20260725-062451-8f15c1fd` PASS including the
  scaled 12-segment long-form memory proof, bench label `release-QA-2.2.0` within noise of
  comparable records). The release arc hardened the pipeline: SHA-pinned tooling in all
  release.yml jobs, nested-framework release signing with an explicit notarization verdict check
  (Apple's issue log on non-Accepted), a fail-fast bundle check for ad-hoc frameworks,
  self-diagnosing dirty-tree errors in release evidence, and a pristine-clone-clean regenerated
  project. The GitHub repository was renamed `PowerBeef/QwenVoice` → `PowerBeef/Vocello` the same
  day, before tagging; old URLs redirect, stars/forks/issues intact, and the old name must never
  be re-occupied. macOS 2.1.0 was released 2026-06-12.
- Future macOS releases now start from a protected version tag or explicit existing tag. The
  workflow verifies source/version identity, signs and notarizes, emits SPDX/CycloneDX inventories,
  checksums, release evidence, and provenance, then verifies downloaded draft assets before the
  final publication step. Immutable Action pins, Dependabot, dependency review, scheduled CodeQL,
  and deterministic website checks are repository contracts; GitHub administrative settings still
  require maintainer authorization and API verification.
- The optional CI `archive-ios` lane is implemented with process-bound deterministic readiness,
  signed-artifact verification, and release evidence. As of 2026-07-25 the maintainer-owned
  prerequisites exist: Apple Distribution certificate, App Store provisioning profile carrying
  `increased-memory-limit`, the App Store Connect app record, an App Store Connect API key, and
  all seven repository secrets. The first TestFlight dispatch on `v2.2.0` is iterating through
  lane hardening (the tag's orchestration contract freezes the managed archive command, so
  fixes land as workflow-text/env changes on `main`: literal destination quoting, per-target
  provisioning-profile scoping via an `XCODE_XCCONFIG_FILE` macro, then a manual-signing CI
  export because cloud-managed automatic signing needs an Admin-role App Store Connect key).
  The third dispatch reached Apple's servers end-to-end; App Store Connect then rejected the
  binary content — transparent iOS icons (90717) and framework Info.plists missing
  `CFBundleShortVersionString` (90057) — which the tag freezes, so **v2.2.1** packaged those
  two fixes (full-bleed opaque iOS icon set; project-scope
  `MARKETING_VERSION`/`CURRENT_PROJECT_VERSION` inheritance) and **v2.2.2** followed the same
  day when the tag-frozen artifact verifier turned out to read version identity only from the
  target block (it now resolves with Xcode-style inheritance, regression-tested against the
  live `project.yml`). **The v2.2.2 dispatch (run `30177386286`) went green end-to-end on
  2026-07-25 — archive, export, IPA verification, schema-v2 evidence, provenance attestation,
  and the TestFlight upload — so Vocello 2.2.2 (build 21) is the first uploaded TestFlight
  build.** Remaining distribution work is App Store Connect-side: beta Test Information, the
  external group with a capped public link, and Beta App Review. Public App Store
  distribution beyond TestFlight still requires metadata, screenshots, and submission.
- The 2026-07-16 Speech-asset verification resolved the requested locales to installed `de_DE`,
  `es_ES` (for `es_419`), `ja_JP`, and `zh_CN` DictationTranscriber modules; fresh
  `SFSpeechRecognizer` instances also passed Vocello's legacy on-device gate. This is prerequisite
  evidence, not a language-generation verdict. The clean seven-cell EN/FR quick language record is
  tracked. The first post-asset
  full attempt passed the 19/19 hint gate but failed the output gate; it correctly published no
  history. That run exposed an out-of-range language-score producer bug plus genuine accuracy
  failures under the original short corpus. The strict validator, version-2 corpus/matrix, and
  CJK-aware punctuation pause budget subsequently passed a retry-free six-cell DE/ZH/JA diagnostic
  cohort with 6/6 hint/QC and 6/6 output checks. That bounded local diagnostic intentionally
  published no history. The first clean corpus-v2 full attempt then passed all 19 hint/QC checks
  but stopped at 13/18 output cells, correctly publishing no history; its failures were isolated to
  French Custom and the three German paths. Revised natural French and German scripts passed four
  retry-free exact-canonical-seed cohorts with strict QC and all 6/6 output checks. The subsequent
  full run `ios-lang-bench-20260714-153252-d2a3eea5` was intentionally interrupted while take 7
  was launching after six takes had completed. It produced no final hint/output gates and no
  history record, so it remains non-authoritative local evidence and must not be resumed or
  published. Fresh run `ios-lang-bench-20260716-164248-1ecf8361` then completed the immutable full
  plan with 19/19 hint/QC rows, 18/18 output-gated rows, zero diagnostic failures, and three-pass
  locale-locked on-device ASR. Its status is `passedWithWarnings` for the accepted Spanish Custom
  written-output/dropout warning and soft memory trims. It is tracked as `exploratory` because the
  owned-runtime worktree was dirty; it proves the exact recorded fingerprint but is excluded from
  clean comparison trends.
- Clean canonical post-cutover UI matrices landed 2026-07-20 on both platforms
  (`macos-xcui-benchmark-20260720-172920-591696d1`, `ios-xcui-benchmark-20260720-174441-16fc128c`)
  and closed overall promotion; the pre-convergence baselines are historical controls. The
  2026-07-22/23 characterization arc then explained and recovered the macOS UI decline outside
  the engine: XCUITest screen recording plus visible Liquid Glass compositor cost. With
  recording disabled and the generation performance gate shipped, fresh canonical gated
  matrices landed 2026-07-23 (macOS custom 1.68–1.83 / design 1.78–1.94 / clone 1.49–1.84;
  iOS 1.86–2.03) and pre-2026-07-23 UI records are not baselines for post-change comparisons.
  Explicit quality runs remain independent from ordinary publishing and release packaging.
- Physical-iPhone telemetry-v8/evidence-v2 acceptance is complete for the canonical UI matrix,
  retained-memory qualification, and an exact-PID memory profile. The tracked records remain bound
  to their exact source, toolchain, model, and hardware identities; new product changes require
  proportionate fresh evidence rather than reuse of local raw artifacts.
- Pre-convergence owned-core evidence passes on both platforms: the two canonical 29-take UI matrices,
  typed user and memory-pressure cancellation, the two-take physical-iPhone Clone proof,
  redirect-enforced isolated iPhone delivery, the isolated post-catalog macOS/CLI delivery proof,
  Speech prerequisites, and the full 19-cell language run. Each result remains bound to its exact
  source or worktree fingerprint; the language run remains exploratory rather than a clean trend
  baseline. It must not be presented as validation of the staged convergence runtime. Focused
  post-cutover macOS and physical-iPhone parity, clean canonical controls, and the full-matrix
  promotion QA all subsequently passed (2026-07-20 promotion; 2026-07-23 gated re-baseline); none
  of this evidence blocks deterministic source publication, packaging, or release artifact
  preservation.

## Resume rule

Review `git status`, read the applicable role playbook, and run verification proportional to the
change. Do not rely on a dated local `.xcresult`, telemetry directory, or device state as proof for a
new checkout. A tracked record proves only its exact source/toolchain/model/hardware identities;
produce fresh evidence only when that acceptance surface is explicitly requested.
