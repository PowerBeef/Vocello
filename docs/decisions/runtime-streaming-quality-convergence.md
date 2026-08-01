# Runtime, streaming, and quality convergence

- **Status:** Accepted; Phase 4 overall promotion passed (Phases 0–6 closed 2026-07-20; Phases 7, 8, and 14 closed 2026-07-23 by amendment). Phases 9–13 remain open.
- **Date:** 2026-07-20
- **Owners:** Backend/MLX, macOS, iOS, and Release/QA
- **Machine contract:** [`config/runtime-refactor-contract.json`](../../config/runtime-refactor-contract.json)

## Glossary

| Term | Meaning |
| --- | --- |
| Qwen dual-track streaming | Official Qwen3-TTS hybrid path for low first-packet latency (CUDA-class demos; not Vocello’s API) |
| Vocello product streaming / preview | Early codec-frame chunks plus the frontend preview router that makes generation feel immediate |
| Lossless final channel | Actor-owned classified session drain through `GenerationOutputAdapter` to atomic WAV + Fast QC |

### Secret-sauce invariants

Keep early first/later codec frames, the preview-vs-lossless split, request-local sampling v2, tiered
`Memory.cacheLimit` with soft relief (no hard production `memoryLimit`), XPC engine isolation on
macOS, and the 1.7B Speed/Quality matrix. Do not chase A100 first-packet figures, reopen 0.6B, or
add Core ML / custom Metal during convergence. Latency/memory cells are named in
`config/characterization-fixtures.json` (`secretSauceCells`); roadmap cross-check:
[`docs/reference/qwen3-apple-silicon-roadmap-review.md`](../reference/qwen3-apple-silicon-roadmap-review.md).

## Context

The owned Qwen3 runtime is production-capable, memory-qualified, and covered by clean canonical
macOS and physical-iPhone evidence at the pre-convergence source identities. Its remaining risk
comes from authority split across product, runtime, and compatibility layers rather than from a
missing replacement backend. At the start of this program, XPC admission occurred after some side
effects, pressure state crossed isolation unsafely, final-audio events used mixed
`bufferingNewest` streams, sampling and memory used process globals, and model termination was
separated from final output publication only by convention.

The implementation blueprint reviewed on 2026-07-17 was grounded against the owned package and
product sources. Its convergence direction is accepted with these corrections:

- The existing inner Qwen generation gate remains defense-in-depth during migration.
- A runtime operation is not complete at model end. Product WAV finalization, Fast QC, atomic
  publication, public terminal, and an opaque finalization acknowledgment remain inside the same
  admission lease.
- Lossless audio requires a suspending, size-aware producer channel. Changing an `AsyncStream`
  buffer policy is insufficient.
- Request-local MLX random state is a separately versioned migration because fixed-seed output may
  change.
- Clone artifacts already use schema 3, and the current first/later stream schedule already exists.
- Disk component deduplication and in-memory decoder reuse are independent decisions.
- Existing three-pass ASR consensus remains the promotion authority; a one-pass diagnostic cannot
  replace it.
- Timing and memory thresholds remain candidate budgets until repeated clean controls establish
  measurement noise.

## Decision

Vocello will converge incrementally on one public actor-owned Qwen3 runtime. The actor owns loaded
model identity, prepared components, clone tensors, request-local random state, generation, trim,
and unload. Product code retains private text, output destinations, persistence, frontend delivery,
and quality publication. MLX arrays and mutable conditioning tensors never cross the runtime
boundary.

Generation uses reserve, bind, and open admission. A reservation creates no model task until the
mandatory product output adapter owns the single audio drain. The operation lease remains active
through model terminal and product finalization. Duplicate identical finalization acknowledgment is
idempotent; stale, conflicting, or cross-generation acknowledgment cannot release a later lease.

Core audio delivery becomes ordered, bounded by frames or audio duration, single-consumer, and
lossless. Prepared state is replay-latest, progress is monotonic and coalesced, diagnostics are
bounded and PCM-free, and terminal completion is independent. Critical memory relief closes
admission before cancellation and reopens it only after product cleanup and trim or unload.

Immutable plans use three privacy boundaries:

1. `ProductGenerationPlan` owns original/spoken text, local destination, output, and review policy.
2. `CoreGenerationPlan` owns only model-facing input and explicit runtime policy.
3. `GenerationEvidenceIdentity` contains only privacy-safe counts, versions, and digests.

Dependency-specific digests ensure an output-policy change cannot invalidate model preparation or
conditioning. The initial plan types are shadow-only and cannot run a second model generation.

## Delivery and rollback

Correctness prerequisites landed before actor/session cutover. Plans remain in comparison-only
shadow mode, while Custom, Design, and Clone now share the actor/classified-session/product-adapter
source path. The named `VocelloQwen3LegacyCompatibility` SPI remains only for prepared-model
load/prewarm and validated schema-3 conditioning adoption; it is not product generation authority.
Sampling, telemetry, preview calibration, component storage, long-form, and unified quality remain
separately promotable changes.

No permanent feature flag or dual backend is introduced. Each small pull request must leave `main`
releasable and is independently revertible. Protected remote history is the rollback surface; no
local Git bundle or migration tag is required.

## Promotion requirements

Runtime behavior changes require deterministic macOS/Core/XPC tests and iOS device-SDK compilation.
Mode cutover or shared generation changes additionally require explicit model-dependent focused and
full macOS/physical-iPhone evidence. Ordinary commits and merges remain deterministic-only.

Promotion must prove ordered complete final audio, one model and product terminal, readable atomic
WAV output, unchanged mandatory QC and language outcomes, qualified memory evidence, and no hard
trim or full unload. Performance budgets are derived from compatible clean repeated controls rather
than assumed from a single benchmark record.

## Non-goals

- Replacing the macOS XPC or iPhone in-process topology.
- Adding a second backend, permanent dual session, Simulator, or alternate UI driver.
- Upgrading MLX dependencies during convergence.
- Parallel model candidates, hidden retries, or hidden sampling/memory globals.
- Buffering full long-form audio or weakening autonomous three-pass language proof.
- Promoting decoder-object reuse or a speaker evaluator without isolated evidence and resource
qualification on the 8 GB support floor.

## Implementation checkpoint

The machine-readable contract distinguishes implemented shipping behavior from foundations that
must not yet be treated as product authority. At this checkpoint:

- XPC reserve-before-side-effects, synchronized pressure snapshots, and continuous critical-relief
  admission are implemented on the current product path.
- Sampling algorithm v2 and Qwen generation-memory behavior are request-local and shipping. Every
  request has an effective seed, independent talker/subtalker policy, explicit cache cadence and KV
  window; the process-global MLX RNG is not mutated. MLX allocator limits remain process-wide
  because that is the allocator API boundary, not request policy.
- Immutable product/core/evidence plans run in comparison-only shadow mode and never start a second
  model generation. Raw text, conditioning, and destination plans are non-encodable; only the safe
  evidence identity is serializable. The shipping runtime captures its resolved prompt, model,
  sampling, chunk, memory, output, and quality values independently before comparing every field.
- The engine actor, frame-bounded suspending channel, classified session, and stale-safe
  finalization acknowledgment now serve Custom, Design, and Clone product generation through
  QwenVoiceCore's `GenerationOutputAdapter`. Each lazy audio
  chunk is evaluated and copied to `[Float]` before an awaited channel send, so channel pressure
  suspends the actual Qwen token/decode loop without transferring `MLXArray` across isolation.
  Deterministic coverage includes delayed drains, receiver and producer cancellation, consumer
  failure, maximum-length ordering, bounded high-water evidence, and terminal/finalization lease
  ordering. `VocelloQwen3Engine` is the shipping generation-mutation authority; the old combined
  event session is package-internal. QwenVoiceCore imports `VocelloQwen3LegacyCompatibility` only
  for the remaining load/prewarm and conditioning bridge, so the actor is not yet described as the
  sole MLX mutator. The actor correctness closure remains complete:
  explicit reserved/generating/aborting ownership makes duplicate aborts join one finalization and
  rejects open after abort ownership begins; typed cache-trim/full-unload relief transfers the
  generation lease directly into critical relief and reopens admission only after that relief
  completes. Rejected atomic relief claims clear their ownership before session reconciliation, so
  ordinary finalization cannot strand the generation lease in either acknowledgment ordering.
  Epoch-bound Clone handles retain one prompt by default, use bounded LRU eviction when
  configured larger, support explicit fail-closed release, survive noncritical cache trim, and are
  invalidated by model reload, critical trim, or full unload. The source wiring, deterministic
  verification, and focused macOS Custom/Design/Clone acceptance have passed. Physical-iPhone runs
  `ios-xcui-benchmark-20260719-133203-d413fac1` (Custom 2/2),
  `ios-xcui-benchmark-20260719-134041-9653f7cf` (Design 2/2), and
  `ios-xcui-benchmark-20260719-134646-d90db984` (Clone 1/1) also passed with complete telemetry,
  Fast QC, readable output, and no crash delta. They are exploratory `passedWithWarnings` evidence
  because the worktree was dirty and soft trims were observed. Those focused runs closed Phase 4
  platform acceptance; clean Phase 0 controls, canonical 29-take matrices, Phase 5 packaging, and
  Phase 6 v9 sidecar authority later closed overall promotion on 2026-07-20
  (`overallPromotion: passed` in the machine contract).
- Production catalog schema v2 and the shared-component store are integrated into macOS, CLI, and
  iOS delivery. Exact verified content is published atomically, surfaced through ordinary hard
  links, and read alongside legacy schema-v1 installations. Delivery-plan resolution now
  authenticates and automatically migrates or repairs each existing installed artifact locally;
  live all-artifact proof remains pending, and runtime component-object reuse is still a separate
  experiment. Long-form v4 stages A–C shipped 2026-07-23: the spoken-text planner and
  long-form planner drive segmentation, segments execute sequentially through the shipping
  streaming path with preview publication suppressed, the bounded PCM16 assembler joins the
  output, and manifest v4 (plan + execution + assembly evidence) replaces v3 writes (v3 stays
  read-compatible). Resume/replacement and History/UI integration remain open (stages D–E).
- The low-dependency prosody analyzer is now two-pass and bounded-memory, while the typed unified
  quality registry remains a foundation. Existing persisted-WAV Fast QC and specialized language,
  delivery, and prosody gates still own shipping decisions.
- Telemetry JSONL remains schema v8 with a nested transition projection. Publication-ready
  transitions with exact MLX chunk instants publish complete `*.streaming-telemetry-v9.json`
  sidecars; those sidecars are the history authority for streaming detail. Benchmark history
  schema v2 remained authoritative until Phase 13 shipped (2026-07-26): schema v3 adds the
  typed quality-registry identity to every generation take, the publisher folds it from the
  phase-12 telemetry notes (v3 only when every take carries it; mixed records refuse), and
  v1/v2 records stay valid immutable history; the UI benchmark checkers folded the same
  identity on 2026-08-01, so ui-generation records publish v3 under the same all-or-none
  rule. Non-blocking layer gaps (`notApplicable`,
  aggregate-only transport list, missing player render callback) may remain listed.

Overall Phase 4 promotion is closed. The broader convergence program remains open for Phases
9–13; Phases 8 and 14 (14a + 14b) closed 2026-07-23 (see the amendments below).

## Amendment 2026-07-22 — characterization-gate resequencing (maintainer endorsed)

The R1 characterization gate (backend refactor review) proved the engine innocent of the
post-cutover canonical macOS RTF decline: interleaved CLI A/B benches across the cutover
(`9a8da874` vs `610125b7` vs HEAD) are flat at 1.02–1.17 while the app/XPC topology measures
0.69–0.81 on identical engine code — the engine is submission-starved in the delivery pipeline
(zero lossless-channel producer suspensions, normal thread priorities, ~83% of its command-buffer
timeline submission-side idle in a Metal System Trace). Because the Phase 0 promotion controls
were CLI-context short-cell runs, the topology-bound regression could not be seen by the gate
that passed. Three changes, recorded machine-readably in `amendment20260722` of
`config/runtime-refactor-contract.json`:

1. **Phase 7 is rescoped** from raw chunk/preview RTF experiments to the delivery-pipeline
   pacing fix (coalesce per-frame actor hops, move v9 per-chunk publication off the generation
   path, evaluate larger macOS chunk schedules), preserving first-preview latency and
   trim/unload safety.
2. **Promotion characterization matrices must include at least one UI/app-XPC-context cell**
   (`characterization.promotedMatrixRequiresUIContextCell`).
3. **Phase 14 mechanical retirement is pulled forward** to immediately after the phase 7–9
   block, before phases 10–13, so quality/long-form phases build against one topology.

## Amendment 2026-07-23 — observer-effect correction (supersedes the 07-22 diagnosis)

The phase 7 characterization program (`benchmarks/OPTIMIZATION.md` §J) found the dominant cause
of the canonical macOS UI decline outside the product entirely: XCUITest's default automatic
screen recording (`testmanagerd` → `VTEncoderXPCService`/`replayd`) video-encoded the display
through every UI take. With `preferredScreenCaptureFormat: screenshots` on both UI schemes
(`project.yml`), the one-cell custom/long lane moved from warm RTF 0.70–0.78 to **1.196** with
clean QC. Engine code remains exonerated (flat interleaved CLI A/B across the cutover), and true
Mac capability at the product's `-O` optimization measured **1.81** in an interactive CLI process
(all historical CLI benches were `-Onone` dev builds). Machine-readable record:
`amendment20260723`. Consequences:

1. **Phase 7's objective becomes the honest UI/XPC-context gap** (≈1.2 → ≈1.8) with recording
   disabled, instrumented by the new per-generation `processTaskRole`/`processMainThreadQOS`/
   `processNice` telemetry notes.
2. **Pre-2026-07-23 UI-generation records carry the recording overhead** in every cell and are
   not baselines for post-change comparisons (their comparison keys already differ).
3. **Three diagnostic engine-loop experiments were reverted** (generation-task priority pin,
   per-token `publishProgress` coalescing, dedicated `userInteractive` actor executor) after two
   intermittent Fast-QC hard failures appeared with them in-tree; 12/12 takes passed QC after
   the revert. Re-introducing any of them requires a fixed-seed QC soak.
4. The UI-context promotion-cell requirement and the phase 14 pull-forward from the 07-22
   amendment stand unchanged.


## Amendment 2026-07-23b — Phase 14a mechanical retirement (complete)

Phase 14a executed the mechanical half of Phase 14 immediately after the Phase-7 topology-gap
closure, per the 07-22 resequencing:

- **Combined characterization session retired.** `VocelloQwen3ModelGenerationSession`, the
  `VocelloQwen3GenerationSession` protocol, `VocelloQwen3GenerationEvent`, the internal event
  channel, and their seven facade characterization tests are deleted. The classified session is
  the sole generation session; `VocelloQwen3TerminalState` survives as its shared terminal latch.
  `COMPATIBILITY.json` `internalCharacterizationSurfaces` is now empty and
  `runtime_security_contract.py` enforces the retired state.
- **Stream trio retired.** `UnsafeSpeechGenerationModel.generate*Stream`, the package
  `customVoiceStream`/`voiceDesignStream`/`voiceCloneStream` factories, and the stream-based
  Clone priming loop are deleted. `NativeEngineRuntime.primeCloneConditioning` now uses the
  completion-variant `generateVoiceClone` with an explicit empty-audio guard.
- **Filename retired.** `NativeStreamingSynthesisSession.swift` →
  `Sources/QwenVoiceCore/GenerationOutputAdapter.swift`; contracts, health/risk registries,
  benchmark harness fingerprint inputs, and live docs updated in the same change. Point-in-time
  research/audit archives and published benchmark records keep the historical name.
- **Remaining Phase 14 surface: `VocelloQwen3LegacyCompatibility` only** (prepared-model
  loading, prewarm/conditioning, loaded-model adoption, validated clone-prompt adoption). Its
  retirement (14b) requires actor-owned loading — a design decision with product consequences,
  recorded separately before implementation. Contract token:
  `phase14a-complete-2026-07-23-combined-session-stream-trio-and-filename-retired-spi-surface-remains-for-14b`.

## Amendment 2026-07-23c — Phase 14b SPI evaporation (complete)

Phase 14b retired the `VocelloQwen3LegacyCompatibility` SPI by making every remaining bridge
capability an actor-owned public surface:

- **Actor-owned loading.** `VocelloQwen3Engine.load` gains the documented
  `VocelloQwen3VerboseLoadDiagnosticSink` local-diagnostics channel (package-defined load-stage
  breadcrumbs, confined to untracked local diagnostics), preserving the detail fidelity the
  transitional `compatibilityDiagnosticSink` overload existed for; that overload is deleted and
  `VocelloQwen3Runtime.loadPreparedModel` is internal.
- **Metadata and diagnostics.** `loadedModelFacts()` (identity, sample rate, capabilities, load
  diagnostics) and `preparationDiagnostics()`/`resetPreparationDiagnostics()` replace direct
  loaded-model reads; `UnsafeSpeechGenerationModel` becomes a plain-`Sendable` pairing of the
  actor with immutable facts and request bindings, and its concurrency-safety registry entry is
  retired.
- **Actor-owned priming.** `prime(request:cloneHandle:)` runs the bounded completion generation
  inside the actor and returns only frame counts; Clone priming and prewarm route through it and
  `prewarm(request:)`.
- **Handle-based clone artifacts.** `persistCloneArtifact`/`adoptCloneArtifact` move schema-3
  artifact write/read inside the actor, `makeCloneHandle` validates the built prompt's mode, and
  `isCloneHandleValid` lets the product's identity-keyed cache drop epoch-invalidated entries.
  `ResolvedCloneConditioning` carries an epoch-bound handle instead of a prompt value, so clone
  tensors never cross the actor boundary anywhere in the product.
- **Enforcement inverted.** The vendor/security contracts now fail closed on any reappearance of
  the SPI attribute, a public loaded-model surface, or the temporary-SPI compatibility record;
  `COMPATIBILITY.json` records `retiredLegacySPI` with empty inventories, and
  `phase14DeferredSurfaces` is empty. Contract token:
  `phase14-complete-2026-07-23-spi-retired-actor-owned-loading-metadata-priming-and-clone-artifacts`.

## Amendment 2026-07-23d — Long-form v4 stages A–C (sequential streaming cutover)

Phase 11's core contradiction — long-form used the memory-heavy non-streaming path even though
streaming is the project's primary RAM architecture — is resolved for the macOS product:

- **Sequential streaming execution.** Long-form no longer routes through the native batch call.
  Each planned segment runs the ordinary streaming path (actor → classified session →
  `GenerationOutputAdapter`) one at a time while incremental WAV, Fast QC, and telemetry
  behavior stay identical; memory stays flat at audiobook scale. Live preview publication is
  enabled (2026-07-23 follow-up): the player narrates segments as they generate through its
  ordinary per-generation live sessions, gated by the user's auto-play preference — note the
  final joined output additionally carries edge trims, inserted boundary pauses, and loudness
  matching. The new request-local `suppressStreamingPreview` flag remains available for
  contexts that need silent long-form generation.
- **Planner-owned segmentation.** `SpokenTextPlanner` + `LongFormPlanner` replace the
  character/sentence segmenter (retired): boundary-kind precedence with protected spans,
  conservative token estimates against the shipping codec-token cap, digest-bound identity, and
  per-segment `effectiveSubseed`s that supersede the shared batch seed — closing the Phase-5
  deferral of long-form sub-seed execution.
- **Bounded assembly.** After every segment passes QC, `BoundedLongFormAssembler` joins the
  output (`long_form_joined_<planDigest8>.wav`): punctuation-aware pauses from boundary kinds, edge trims,
  verified non-speech fades, loudness matching, and a per-segment output frame map. The joined
  file must itself pass Fast QC.
- **Manifest v4 authoritative.** `LongFormManifestV4` gains optional execution and assembly
  evidence sections (fail-closed consistency with the plan) and replaces v3 writes; v3 documents
  remain readable. Manifests stay privacy-safe: no text, paths, or user data — identities,
  verdicts, and timing only.
- **Stages D–E followed the same day** (amendment 2026-07-23e below). iOS long-form remains a
  later arc; this sequential-streaming design is the basis its batch-removal invariant requires.

## Amendment 2026-07-23e — Long-form v4 stages D–E (resume, replacement, History projects)

- **In-session resume.** The batch coordinator retains the long-form request (and therefore the
  plan identity); "Resume Missing Segments" re-runs the same plan, re-verifies and reuses every
  already-saved take, and generates only missing or failed segments before reassembling. The
  long-form retry no longer degrades to a line-separated batch.
- **Accepted replacement history.** Regenerating one segment produces a new take with a fresh
  recorded seed at revision ≥ 2 (`LongFormSegmentReplacementEvidence`: segmentID, strictly
  increasing per-segment revisions, seed, QC verdict — fail-closed in `validated()`). A take that
  fails QC leaves the prior accepted take and history untouched; an accepted take reassembles the
  joined output and rewrites the manifest with the appended history.
- **History projects.** Migration v5 adds nullable `longFormProjectID`/`longFormRole` columns
  (plan digest as the stable project identity). Segments save as project-tagged rows; the
  assembled output saves as the project's single `joined` row (replaced atomically on
  reassembly). The History list renders joined rows as project rows with a segment-map
  disclosure — segments collapse beneath their project, expand in generation order for
  per-segment replay, stay flat during search, and orphaned segments (no joined row yet) remain
  visible. Joined output and manifest filenames are per-project
  (`long_form_joined_<planDigest8>.wav`, `long_form_manifest_<planDigest8>.json`), removing the
  cross-project overwrite the fixed names allowed.
- **Open.** Live long-form acceptance in the app UI, then iOS long-form as its own arc.

## Amendment 2026-07-23f — long-form QC calibration (acceptance-driven)

Driving the live long-form acceptance exposed three compounding QC defects, all
fixed deterministically (full evidence: `benchmarks/OPTIMIZATION.md` §K
addendum):

1. The app-side segment gate ran with a zero pause budget (no segment text) —
   budgets are now threaded through every segment, resume, regeneration, and
   joined-output check, with the joined budget crediting the assembler's
   inserted boundary pauses.
2. The planner budget allowed ~100 s segments beyond the delivery-validated
   envelope — now bound to min(codec-safe cap/4, 300 delivery-validated
   estimate units ≈ 900 characters).
3. Dropout thresholds calibrated on ≤341-char content misclassified
   minute-scale narration pacing — now duration-aware (≥45 s: long-pause
   600 ms, suspicious 1,500 ms, egregious 2,000 ms), pinned by a core test and
   calibrated from a retained rejected segment whose >1 s gaps
   position-correlate with text boundaries.

Acceptance also exposed a deterministic `-O`-only crash: `objc_release` of a
garbage address inside `LongFormManifestV4.validated()` (inlined into the
manifest persist), reproduced 4/4 in the optimized UI-lane build and invisible
to `-Onone` dev builds and core tests. A stage-breadcrumb bisect isolated the
validate step; rewriting `validated()` without keypath-literal
`map(\.segmentID)`/`allSatisfy` (explicit loops, identical semantics)
eliminated it 1/1 with the full construct → validate → encode → write flow
restored. Recorded as an optimizer-sensitivity workaround with deterministic
before/after reproduction, not a proven compiler-bug diagnosis.

Mandatory-QC rejections now name their rule flags and retain the rejected
staged WAV (newest only, diagnostics-gated). The three phase-7-era reverted
engine-loop experiments are reattributed as likely innocent of the historical
intermittent QC failures (which remain unattributed but now self-document on
recurrence); they stay reverted on cost/benefit grounds.

## Amendment 2026-07-23g — line batch unified onto sequential streaming

Ordinary line-separated batch no longer routes through the native XPC
`generateBatch` call: every batch item runs the same sequential streaming path
long-form uses — flat memory, mandatory engine Fast QC per take, standard
streaming telemetry, live preview (auto-play-gated), and the sustained
performance gate across the run. This closes the blueprint's P1 finding
("long-form batch contradicts the streaming memory pillar") for both batch
flavors. Batch markers (`batchIndex`/`batchTotal`) are no longer sent on
singular generates; item order lives in the visible list. The XPC batch API
remains wired but has no app-side caller — a retirement candidate for a later
cleanup. A new smoke journey (`test07_LineBatchJourney`) covers the unified
path; fixing its editor access also re-homed the `batch_textEditor`
accessibility identifier from a non-hittable wrapper onto the actual text
view (same stable value).

## Amendment 2026-07-24 — XPC `generateBatch` route retired

The caller-less XPC batch surface left by amendment 2026-07-23g is deleted:
the `EngineCommand.generateBatch` wire case, the `.generationResults` reply,
the `.batchProgress` event envelope with its `EngineBatchProgressUpdate`
payload type, the service-host handler and `normalizedBatchResult`, the
client's batch-progress registry and both `@unchecked Sendable` progress-relay
boxes (removed from `config/concurrency-safety.json`), the
`MacTTSEngine`/`TTSEngineStore` batch wrappers, and the batch entries in the
command-name/timeout tables. The single-envelope wire protocol now carries
exactly the commands the app can issue. The in-process engine batch API
(`MLXTTSEngine.generateBatch`) is unaffected: the CLI `batch` command still
uses it directly, and iOS never linked this surface. Verified by the
deterministic macOS suite (Core, XPC transport, runtime) and both foundation
compiles.

## Amendment 2026-07-24b — iOS long-form projects (sequential-streaming port)

iOS ships the long-form v4 design the macOS acceptance arc proved: scripts
above the 900-character single-take limit route to a planned project of
ordinary sequential in-process streaming takes — shared planner segmentation
with per-segment sub-seeds, live per-segment narration (auto-play-gated),
per-segment and joined-output QC through the ported `AudioQualityGate` twin
(same pause budgets and duration-aware thresholds), bounded assembly, manifest
v4 with the shared per-project filenames, and one joined History row per plan
digest (the iOS `Generation` record and `DatabaseService` gained the v5
columns and joined-row replacement that the shared migration had already put
in the schema). History groups projects behind a per-segment disclosure and
flattens during search; in-session resume reuses saved takes; a
sustained-performance refcount holds the iOS fixed-refresh glass gate across
whole runs. Single-segment regeneration stays macOS-only for now (iOS
manifests carry empty `replacements`), and line-separated batch remains
absent from iOS: long-form is the device-validated sequential-streaming
design that the 2026-07-02 batch-removal decision required, not a batch
reintroduction. Acceptance passed 2026-07-24 on the paired iPhone 17 Pro
(smoke run `ios-xcui-smoke-20260724-183626-f9961535`, both journeys green):
the new `testZLongFormProjectJourney` planned a >2,000-character script into
three segments, streamed them sequentially (55.0 s + 45.4 s + 26.6 s), joined
127.2 s of audio, and verified the search-flattened rows plus the grouped
History project with a working per-segment map. The acceptance arc fixed two
lane-level issues, not product behavior: the iOS smoke lane now selects the
whole smoke class (it had pinned the single pre-long-form journey), and the
expansion assertion counts nonce-bearing rows instead of a total-row delta
(the lazy History list drops older rows out of the instantiated accessibility
window as segment rows appear, so a total-count delta is not stable).

## Amendment 2026-07-26 — Phase 9 speech-tokenizer residency (complete)

Phase 9 closes with in-memory speech-tokenizer reuse across macOS model
switches. The byte-identical 682 MB component is adopted from the previous
model when the content identity matches: the host coordinator attests the
trusted-checkpoint weights + config digests through the load behavior, with
the shared-store hard-link inode identity as the in-package fallback, and an
encoder-superset capability rule (an encoder-carrying resident may serve a
decoder-only load, never the reverse). Ownership follows the registered
lock-protected cache invariant — one logical user at a time with the cache
holding the handoff between sequential loads — and the lifecycle is
pressure-safe by construction: `Qwen3TTSMemoryCaches.clearAll` (memory relief
and explicit/idle unload) clears the slot, so only an in-process switch
preserves it. iOS remains disabled; its switch path deliberately pre-clears
for Jetsam headroom, and enabling there requires its own device A/B. Promotion
evidence per this ADR's constraint (isolated evidence + resource
qualification on the 8 GB support floor): fixed-seed switch A/B byte-identical
with residency on and off, live adoption (`speech_tokenizer_load` 503 → 0 ms,
~260 ms better cold first-chunk latency), and retained-memory qualification
PASS `mac-memory-qualification-20260726-115343-5a1c8a85`
(Custom→Design→Clone, three retained takes per mode). The registered
`QWENVOICE_TOKENIZER_RESIDENCY` knob is the gated diagnostic off-switch.
