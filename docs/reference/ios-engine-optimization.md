---
status: active
owner: ios
summary: Standing record of iPhone engine bring-up and optimization — measured memory/latency work, shipped changes, Jetsam posture, and the prioritized future items.
sourceOfTruth:
  - config/runtime-debug-knobs.json
  - config/memory-qualification-policy.json
---
# iOS Engine Optimization — Progress & Roadmap

The standing record of how Vocello's **iPhone** TTS engine was made to run on-device, what has
been measured/optimized/shipped, and the prioritized future work. The iOS engine is a distinct
optimization problem from the macOS engine (different process model, a hard per-app Jetsam ceiling,
streaming-first), so it gets its own doc.

All Vocello-owned production-affecting environment overrides named below are registered in
`config/runtime-debug-knobs.json` and are inert unless `QWENVOICE_DEBUG=1`. Bounded observability and
the separately compiled physical-device diagnostics target are classified independently by that
registry.

Companion docs: [`../../benchmarks/OPTIMIZATION.md`](../../benchmarks/OPTIMIZATION.md) (backend/MLX
decode-loop + output-quality work, shared by both platforms — the deep §A–§F findings live there),
[`ios-increased-memory-entitlement-request.md`](ios-increased-memory-entitlement-request.md) (the
entitlement), [`ios-device-testing.md`](ios-device-testing.md) (how to build/bench on device),
[`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md) (the telemetry schema).

**Source-of-truth rule (from `CLAUDE.md`): if this doc disagrees with the code, the code wins — fix
this doc.** All claims below are cited to a file or commit; re-verify before relying on a number.

---

## TL;DR — latest clean canonical evidence (iPhone 17 Pro)

- **In-process, Speed (4-bit) only.** The engine runs inside the app process (`MLXTTSEngine` via
  `NativeRuntimeFactory`); the ExtensionKit extension was removed (it could never load the model —
  see §1). iPhone runs the 4-bit Speed variant only; 8-bit Quality is macOS-only by contract.
- **Faster than realtime with bounded memory.** The clean 29-take schema-v2 record
  [`ios-xcui-benchmark-20260716-184106-48e3a3a6`](../../benchmarks/runs/ui-generation/ios-xcui-benchmark-20260716-184106-48e3a3a6.json)
  measured per-cell median RTF **1.70–1.89** and peak physical footprint **2.56–3.52 GB**. Every
  take recorded the allowed `memory.pressure.soft_trim` warning, with no memory warning or exit (§6).
- **Streaming-first is the headline RAM win.** The canonical path stays in the ~2.6–3.6 GB band
  vs ~7–8.7 GB for the legacy non-streaming bench path (`--no-stream`) — iOS never incurs the accumulation (§3).
- **Entitlement enabled, self-serve.** `increased-memory-limit` is on the app App ID; measured
  entitled per-app limit ≈ **~6 GB** on the 17 Pro, ~5–5.5 GB on 8 GB devices. No hard
  `Memory.memoryLimit` on any tier (§2).
- **Remaining work (§9):** an 8 GB-device proof (only the 17 Pro is measured), App Store
  credential/metadata setup, and the gated mlx-swift 0.31 bump. (The 0.6B variant evaluation was
  **ruled out 2026-07-02** — see §9 P2.)

---

## 1. Architecture — why the engine runs in-process

iOS generation runs **in-process in the app**: `IOSAppBootstrap` selects `MLXTTSEngine` via
`NativeRuntimeFactory` on real hardware only. The MLX engine cannot initialize on the iOS Simulator,
so all iOS UI tests and generation validation run on a paired iPhone. The engine is wrapped in
`TTSEngineStore` like macOS. (`Sources/iOS/IOSAppBootstrap.swift` engine-selection block.)

It did **not** start here. The original design ran generation out-of-process in a `VocelloEngineExtension`
ExtensionKit extension (mirroring the macOS XPC split). That can never work on iOS: a **non-UI
ExtensionKit extension is Jetsam-capped at a tiny per-process budget that the
`increased-memory-limit` entitlement does *not* raise** — only the *app* process gets the raised
budget. On device the extension was jetsam-killed (`per-process-limit`) while loading the ~2.3 GB
model. The migration to in-process landed in `7822a8a`; the dead extension was un-embedded
(`30c3792`), then removed entirely (`aed617c`), and its leftover memory-diagnostics fields were
cleaned up (`72c95fc`). There is no iOS engine-extension App ID. (See [`ios-device-testing.md`](ios-device-testing.md)
"Why this exists" and the entitlement guide.)

**Consequence for optimization:** on iOS the engine and the UI share one Jetsam budget, so every
byte the engine holds counts against the app. The whole iOS memory story below follows from that.

---

## 2. The memory model — the central constraint

### 2.1 Per-app Jetsam budget + the entitlement

iOS terminates a process when its **physical footprint** crosses a per-app Jetsam ceiling (≈ 50% of
device RAM by default; the `com.apple.developer.kernel.increased-memory-limit` entitlement raises it,
community-estimated to ~75% — Apple publishes no exact number). The authoritative runtime read is
`os_proc_available_memory()` (bridged as `IOSMemorySnapshot.availableHeadroomBytes`); the entitled
per-app limit is computed as `impliedProcessLimitBytes = physFootprint + availableHeadroom`.

**Measured** (iPhone 17 Pro, 12 GB): entitled per-app limit ≈ **~6 GB**. 8 GB devices
(15/16/17 non-Pro and Pro through 16 Pro Max) ≈ **~5–5.5 GB**. The latest clean canonical clone
peak was 3.52 GB physical footprint (§6)
fits every entitled device. The entitlement is **self-serve** (enable on the App ID, regenerate the
profile — no Apple grant) and is enabled on `com.patricedery.vocello`. Full detail + device-free
verification: [`ios-increased-memory-entitlement-request.md`](ios-increased-memory-entitlement-request.md).

**No hard `Memory.memoryLimit` on any tier.** A floor-8GB 6 GB cap and an iPhonePro 5 GB default were
tried and **reverted in `b77c08e`** (the cap over-promised headroom above the real Jetsam ceiling and
risked spurious OOM downgrades during cold-load peaks). `NativeMemoryPolicyResolver.apply(_:)` only
sets `Memory.memoryLimit` if a tier supplies one, and none do (iPhonePro only sets it under the
`QVOICE_IOS_MLX_MEMORY_LIMIT_MB` debug override). The cache limit is set; the hard memory limit is not.
(`Sources/QwenVoiceCore/NativeMemoryPolicyResolver.swift`.)

### 2.2 Per-tier policy — the `iPhonePro` class

The device tier is resolved by `NativeMemoryPolicyResolver` (enum `NativeDeviceMemoryClass` in
`SemanticTypes.swift`: `floor8GBMac` / `mid16GBMac` / `highMemoryMac` / `iPhonePro`). On iPhone the
tier is always `iPhonePro`; on Mac it's picked by RAM (`≤10 GB → floor`, `≤24 GB → mid`, else `high`).
A forced class for testing comes from `QWENVOICE_FORCE_MEMORY_CLASS` (`NativeDeviceClassGate`,
relayed to the engine over the `initialize` handshake; `vocello bench --force-class 8gb`).

The `iPhonePro` policy is the most aggressive tier (it shares the app's budget):

| Knob | `iPhonePro` | `floor8GBMac` (contrast) | `highMemoryMac` |
|---|---|---|---|
| MLX cache limit | **128 MB** | 256 MB | 1 GB |
| Hard `Memory.memoryLimit` | **none** | none | none |
| Clear MLX cache after each generation | **always** | `!isBatch` | false |
| Clear MLX cache on each stream chunk emit | **true** | true | false |
| MLX token-memory clear cadence | **every 50 tokens** | 50 | 200 |
| Idle-unload window | **30 s** | 120 s (adaptive 30/10 under trim) | never |
| Pressure monitor active | **yes** | yes | no |

(`NativeMemoryPolicyResolver.swift` — iPhonePro block. The 128 MB cache + per-chunk clear + 50-token
cadence + 30 s idle-unload are what keep the streaming peak flat.)

### 2.3 Pressure bands, admission, and cache clearing

`IOSMemoryBudgetPolicy` (`Sources/QwenVoiceCore/IOSMemorySnapshot.swift`) computes a pressure band
from **two independent criteria**, and the engine band is the worse of them:

- **Headroom band** (`band(for:)`): healthy ≥ 768 MB `os_proc_available_memory` headroom, guarded
  ≥ 384 MB, else critical (also critical if GPU working-set usage ≥ 80%).
- **Footprint band** (`aggregateBand`): healthy < 4.5 GB physFootprint, guarded ≥ 4.5 GB, critical
  ≥ 5.2 GB. (`pressureBand = maxBand(headroomBand, footprintBand)`.)

> After the in-process migration these two bands measure the *single* app process (the second,
> "engine extension" snapshot is gone — `72c95fc`). The footprint band is **not** dead: it is a
> distinct live admission criterion (footprint-based, not headroom-based), and it stays.

`NativeMemoryPressureMonitor` maps kernel pressure → trim: `.warning → softTrim`,
`.critical → hardTrim`, `.normal → clear`. It is started on `iPhonePro` (and the constrained Mac
tiers). Warning pressure keeps the existing non-interrupting soft-trim policy. Critical pressure
uses the typed `.memoryPressure` reason to cancel the active generation and await its terminal
barrier before the hard trim can begin. On iPhone hard-trim / unload / failure,
`NativeEngineRuntime.clearQwen3MemoryCachesIfNeeded()`
calls `Qwen3TTSMemoryCaches.clearAll()` — **iPhone-only**; macOS deliberately preserves Qwen3
prepared/conditioning/decoder cache warmth across trims so warm-after-idle stays fast.

**Admission semantics (corrected 2026-07-02 to match code).**
`TTSEngineStore.guardModelAdmission(...)` refreshes the memory context, records a
`model_admission_observed` event, and **throws `insufficientMemory` when the headroom/GPU
band is critical** (`allowsModelAdmission(for:)` with `includesAggregatePressure: false`).
Two nuances:

- **Footprint-only critical does NOT block admission** — the aggregate (footprint) band is
  excluded from the admission decision; it still elevates `pressureBand` for warm gating,
  post-generation trim, and the in-flight critical-cancel guard.
- The earlier "records-only" description dated from before the critical-headroom block
  landed; measuring real Jetsam behavior remains the intent for the footprint dimension.
  There is **no** Quality→Speed OOM fallback on any tier — picking a variant loads that
  variant and surfaces the real error if it can't fit.

---

## 3. The headline optimization — streaming-first

The single most important iOS memory finding (OPTIMIZATION.md §F.1): the `vocello`/CLI bench
used to default to **non-streaming** (accumulates *all* codec tokens, decodes the whole clip at the end),
but **iOS is streaming-first** (emits + releases each chunk), and the macOS CLI now streams by default as
well. On the same 69–76 s custom/Speed input:

| path | gpuAlloc peak | physFootprint |
|---|---|---|
| non-streaming (legacy CLI default, now `--no-stream`) | ~8.0 GB | ~7.6 GB |
| **streaming (iOS / current CLI default)** | **~3.0 GB** | **~3.0 GB** |

That dated long-input experiment was nearly flat with length — short 2901 MB · medium 2860 MB ·
long-76 s 2992 MB — and showed why the original non-streaming "iPhone is marginal/infeasible"
verdict overstated the iOS-relevant peak. The newer canonical UI matrix (§6) measured Custom at
2.54–2.71 GB, Design at 2.89–3.16 GB, and Clone at 2.94–3.51 GB. Use that tracked record for current
cross-length evidence instead of generalizing the older ~3 GB experiment.

How the streaming path stays flat (all `iPhonePro`-tuned, §2.2):

- **Lossless bounded core audio.** Final PCM uses the single-consumer, frame-bounded suspending
  classified-session channel. `MLXTTSEngine.events` is backed by a separate per-generation
  suspending router with capacity 96 on iOS and 256 on macOS;
  `GenerationEventDeliveryProbe` accounts for accepted/terminated/unobserved sends.
- **Preview only after durable drain.** `GenerationOutputAdapter` writes each frame to the
  incremental WAV before frontend preview publication. Preview PCM uses the bounded suspending
  event router and is never evicted. The debug-gated `QWENVOICE_STREAMING_PREVIEW_DATA=off` remains
  available for memory-isolated benchmarks or debugging.
- **Per-chunk + per-50-token MLX cache clears.** `NativeMemoryPolicyResolver` resolves
  `VocelloQwen3MemoryConfiguration` at the host boundary; the facade converts it into one immutable
  request-local `Qwen3RequestMemoryPolicy` with `clearCacheOnStreamChunk=true` and
  `tokenMemoryClearCadence=50`. Generation never mutates a process-global tuning singleton.
- **Streaming requests everywhere.** Custom / Design / Clone all build their `GenerationRequest` with
  `shouldStream: true` (the three coordinators in `Sources/ViewModels/`).

`Qwen3RequestMemoryPolicy.talkerKVGeneratedWindow` is `nil` by default (unbounded
`KVCacheSimple`). The talker-KV sliding window remains **debug-gated and off** through
`QVOICE_TALKER_KV_WINDOW`; its value is resolved into the request before generation and is inert at
the current token cap (§9, OPTIMIZATION.md §F.2).

---

## 4. Load profiles & lifecycle

- **Clone gate (measured, not RAM-guessed).** `IOSAppBootstrap.cloneCapableLoadProfile()` picks
  `.fullCapabilities` (clone encoders resident, ~0.6 GB on top of the model) only when the **measured
  entitled per-app limit** `IOSMemorySnapshot.capture(role: .app).impliedProcessLimitBytes ≥
  4_500_000_000` (4.5 GB); otherwise `.iOSProductionDefault` (= `withoutCloneEncoders`). It logs
  `[bootstrap] clone gate: entitled per-app limit ≈ N MB → …`. (This replaced an earlier total-RAM
  gate that mis-fired; the runtime `os_proc_available_memory` read is authoritative.)
- **No dedicated custom prewarm.** `customPrewarmPolicy: .skipDedicatedCustomPrewarm` — the prewarm
  cost moves into the first generation rather than a startup memory spike (matches the floor-8GB Mac
  policy).
- **Proactive warm is band-gated only.** `TTSEngineStore.allowsProactiveWarmOperations` warms on the
  physical-device Release build when the memory band is healthy (the old blanket "disabled on Release"
  caution was removed once the entitlement + band guard were in place). Escape hatch:
  debug-gated `QVOICE_IOS_DISABLE_PROACTIVE_PREFETCH=1` (A/B / battery testing).
- **Clone is warm-by-design.** Clone primes its reference conditioning before generating (the
  device-diagnostics runner calls `ensureCloneReferencePrimed`), so a "cold" clone cell in a bench is a bench artifact,
  not the production path.

---

## 5. Backend compute — what's already optimal, what's bounded

The owned Vocello Qwen3 Core runtime already implements the large majority of the standard
iPhone-Qwen3-TTS optimization playbook (OPTIMIZATION.md "Grounding"): `small_to_mtp_projection`
2048→1024 bridge, 2048-dim speaker embedding, interleaved MRoPE `[24,20,20]`, Q/K RMSNorm,
`MLXFast.scaledDotProductAttention`, a single per-frame `eval()` (no per-step `.item()`), `asyncEval`
streaming, the input-side decoder-drift fix (`4fab110`), per-tier `GPU.cacheLimit`, fp16 KV cache, and
a `compile(shapeless:)` SwiGLU. Backend speed for 1.7B 4-bit on this stack is **bounded**, not freely
improvable:

- **GPU compute is ~61% of decode and fixed at this precision.** An os_signpost capture
  (custom/speed/long, 327 frames / 31.1 s) attributes 61% of wall time to the per-frame fused `eval()`
  (talker + 15× Code Predictor + sampling) — the model's real compute, with no transparent lever at
  4-bit on MLX 0.30.6. (OPTIMIZATION.md §F WS0b.)
- **`compile()` the per-frame graph — tested and rejected.** Compiling the quantized talker MLP
  (`compile(inputs:…, shapeless: true)`) builds + runs correctly (audioQC pass) but **regressed warm
  RTF ~5%** (eager 0.80 → compiled 0.76): declaring quantized params as `inputs:` marshals their packed
  state every call, costing more than the ~22% Swift build overhead it removes — and it scales *up*
  with region size. Do not pursue the fixed-shape-KV + compile rewrite. (OPTIMIZATION.md §F.)
- **RoPE fusion (`MLXFast.RoPE`) is low-priority** — only a small slice of the build overhead, and the
  compile spike showed build-time is hard to reclaim cheaply; gated on a future Instruments capture.
- **Talker-KV sliding window is ~0 RAM benefit** — the talker KV is tens of MB, not GB (the streaming
  path already keeps peak flat); shipped env-only/off (§3).

**Net:** 1.7B-4bit is already faster-than-realtime on device (§6) and the decode loop is
bounded (§5). The smaller 0.6B variant was considered as the next speed/footprint lever but
**ruled out by maintainer decision (2026-07-02)** — Voice Design requires the 1.7B model, and
the product ships one model family across all three modes. iPhone speed work therefore
focuses on 1.7B variants only (mlx-swift bump when gated review passes, kernel-level work).

---

## 6. Measured on-device performance

Latest clean canonical record: iPhone 17 Pro · Speed (4-bit) · in-process · streaming · 29 XCUITest
takes · source `bcb5265a…` ·
[`ios-xcui-benchmark-20260716-184106-48e3a3a6`](../../benchmarks/runs/ui-generation/ios-xcui-benchmark-20260716-184106-48e3a3a6.json).
Warm rows below are per-cell medians across three takes; cold rows contain one take. Peak footprint is
the maximum within the cell. This record directly covers the current owned-core runtime source.

| mode | state/length | median RTF | peak physFoot MB | max soft trims | audioQC |
|---|---|---:|---:|---:|---|
| custom | cold/medium | 1.701 | 2649 | 1 | pass |
| custom | warm/short | 1.728 | 2564 | 1 | pass |
| custom | warm/medium | 1.804 | 2697 | 1 | pass |
| custom | warm/long | 1.798 | 2704 | 1 | pass |
| design | cold/medium | 1.892 | 3072 | 1 | pass |
| design | warm/short | 1.854 | 2559 | 1 | pass |
| design | warm/medium | 1.880 | 3079 | 1 | pass |
| design | warm/long | 1.875 | 3134 | 1 | pass |
| clone | warm/short | 1.862 | 3024 | 1 | pass |
| clone | warm/medium | 1.841 | 3377 | 1 | pass |
| clone | warm/long | 1.842 | 3517 | 1 | pass |

**Reading it:**
- **RTF > 1 in every canonical cell** — all three modes generated faster than realtime at this
  pinned source. Clone was slower than Custom and Design, so “1.6–1.9 everywhere” was not accurate.
- **Peak physical footprint was 2.56–3.52 GB** — under the ~6 GB implied entitled limit. Clone was
  the heaviest because its encoders remain resident.
- **Every take performed one policy soft trim.** The run is therefore `passedWithWarnings`, not a
  zero-trim pass. It recorded no iOS memory warning, critical pressure, memory-limit exit, hard trim,
  or full unload. The run's worst thermal state was `fair`.
- **Compare like with like:** use compatible iOS streaming records in
  [`benchmarks/HISTORY.md`](../../benchmarks/HISTORY.md). Historical macOS non-streaming or Quality
  baselines are not iPhone performance comparisons.

`stepEval` dominates the decode breakdown (the fused per-frame `eval()`); `code2wav ≈ 0` because the
audio decoder is `asyncEval`'d and overlaps the token loop — these are Swift-side wall-clock timers
around lazy ops, not per-stage GPU attribution (OPTIMIZATION.md §A).

---

## 7. Output quality on device

The reference-free `audioQC` verdict (per engine row; `pass` / `warn` / `fail:flags` —
nonfinite/clipping/clicks/dropout/near_silent) is the first objective gate. Promotion additionally
requires exact fixed-seed WAV identity and the applicable locale-locked ASR/prosody evidence. Human
listening is optional annotation and cannot clear a deterministic failure or warning.

- **`dropout` is punctuation-aware** (OPTIMIZATION.md §B/§C, `ac86b8a`). The original ~586 ms
  "dropout" was root-caused as the model's **natural prosodic pauses** at sentence/comma boundaries on
  long slow narration; the detector now counts long interior silences against the text's punctuation
  **pause budget** and flags only an *excess* (≥2 → fail, 1 → warn) or a single egregious ≥1200 ms gap.
  A sampling-side "fix" was rejected — it would suppress real prosody without repeatable
  fixed-seed, chunk, WAV, and ASR evidence of a defect.
- **Latest canonical result:** all 29 takes in the clean schema-v2 iPhone UI record passed audioQC.
  Earlier accumulated rows with Design dropout/click warnings remain historical diagnostic leads;
  they are not the current acceptance verdict and cannot override the run-scoped canonical record.

---

## 8. Optimization timeline (commits)

| commit | date | what it changed / achieved |
|---|---|---|
| `b77c08e` | 2026-05-28 | Reverted the floor-8GB 6 GB + iPhonePro 5 GB hard `Memory.memoryLimit` (spurious OOM downgrades); back to no-hard-limit. |
| `7822a8a` | 2026-06-01 | **In-process engine** — run the TTS engine in the app, not the ExtensionKit extension (the unlock). |
| `17e0b87` | 2026-06-02 | **Clone in-process works** on device: opened the proactive-warm gate, gated clone on the measured entitled per-app limit (≥4.5 GB), primed the reference. |
| `43a3b68` | 2026-06-02 | Runtime-gated the on-device experimentation knobs so they work on Release builds (no `#if DEBUG`). |
| `e6258e2` | 2026-06-02 | Fixed the in-process memory-context **double-count** (was counting the app twice and inflating the band). |
| `30c3792` | 2026-06-02 | Stopped embedding the dormant extension (`.appex` no longer in the bundle). |
| `aed617c` | 2026-06-02 | **Removed the dead `VocelloEngineExtension` target entirely** (~2,000 LOC dead code). |
| `72c95fc` | 2026-06-02 | Dropped the now-always-nil engine-extension memory-diagnostics fields (memctx cleanup). |

The blow-by-blow is in git history; per-run perf is in `benchmarks/HISTORY.md`.

---

## 9. Roadmap (prioritized)

**P1 — 8 GB-device proof.** All on-device numbers are from the 12 GB iPhone 17 Pro. The 8 GB tier
(entitled ≈ 5–5.5 GB) is where Clone (up to 3.52 GB in the current canonical record) + headroom is
tightest. Run `ios_device.sh bench` Custom + Clone on a real 8 GB device and confirm RTF, bounded
soft-trim behavior, no memory warning/exit or hard trim, and clone-gate-on. Until then, 8 GB
viability is inferred from the bounded streaming evidence, not proven.

*Memory-profile diagnostic (2026-06-09, OPTIMIZATION.md §H P5):* the **iPhone 15 Pro profile** runs
the full on-device matrix on the 17 Pro under the 8 GB tier's entitled budget —
`scripts/ios_device.sh bench --memory-profile iphone15pro …` clamps the effective per-process limit to
**5,000 MB** (the conservative bottom of the entitled band) inside `IOSMemorySnapshot.capture()`, so
bands, admission, and the clone gate (5,000 ≥ 4,500 ⇒ stays ON) all behave as on the smaller device;
rows self-stamp `notes.memoryProfile`. **Measured 2026-06-09 (iPhone 17 Pro, post-§H engine):
custom/long RTF 1.89, physFoot 2,723 MB (margin 2,277 MB); clone RTF 1.62, physFoot 3,332 MB
(margin 1,668 MB); 0 trims, QC pass, clone gate ON (proven by execution) — profiled PASS on the
memory dimension.** **The profile changes the memory budget only.** It cannot emulate compute:
A17 Pro sustained GPU ≈ **0.60×** A19 Pro (band 0.55–0.65; LPDDR5 ~60 vs
~68 GB/s; A17 throttles harder). The resulting **historical analytic 15 Pro projection was
RTF ≈ 0.9–1.2** — brushing realtime, which is exactly why the real-device gate above
stays open (streaming playback tolerance to sub-realtime decode is the question only hardware
answers). A memory-profile row is labeled diagnostic evidence, never different-device proof.

**P2 — App Store distribution setup.** The manual `archive-ios` CI job already archives, verifies,
exports, and optionally uploads. It still needs maintainer-owned iOS Distribution credentials, an
App Store provisioning profile carrying the increased-memory entitlement, the App Store Connect
record and metadata, and an explicit dispatch. Local on-device build/test is already established
(`ios-device-testing.md`); optional frontend proof is independent of archive packaging.

**P2 — 0.6B variant: RULED OUT (maintainer decision, 2026-07-02).** The 0.6B checkpoints exist
(`Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice`; mlx-community publishes a 4-bit of the Base only), but
**Voice Design is only available with the 1.7B model** — shipping a 0.6B tier would fragment the
mode matrix (Custom-only tier) for a speed win the 1.7B doesn't need (already >1× realtime on
device). Vocello stays **1.7B-variants-only** (Speed 4-bit / Quality 8-bit). Do not resurrect
without a new maintainer decision.

**P3 — mlx-swift 0.31.x / mlx-swift-lm 2.31.x bump (gated).** Deferred — **stay pinned at 0.30.6 /
2.30.6**. 0.31 changes the quantization API (`Quantizable.toQuantized` gains a `QuantizationMode`;
quantize moves to a top-level fn), which lands on the 4-bit/8-bit model-load path, so it's not a free
bump. Procedure (OPTIMIZATION.md §E, `.claude/rules/backend-mlx.md` "SPM pins move in lockstep"): throwaway branch → bump all pin
sites in lockstep (`project.yml` *and* owned `Packages/VocelloQwen3Core/Package.swift`) →
`regenerate_project.sh` → both `build_foundation_targets.sh` → fixed-seed `vocello bench` vs the
committed baseline + applicable automated language/prosody gates → keep only if RTF/quality/QC are
unchanged.

**P3 — thermal-state monitoring + proactive-warm gate: implemented.**
`TTSEngineStore.startThermalObservation` observes `ProcessInfo.thermalState`; serious/critical state
blocks prewarm and clone priming without silently changing models or cancelling user generation.
`QVOICE_IOS_THERMAL_GATE=off` is a debug-gated diagnostic override. A reduced-length/cooldown product
policy remains future work and requires separate on-device evidence; the 0.6B fallback remains ruled
out because Voice Design needs 1.7B.

**Research question — Quality (8-bit) on a 12 GB iPhone.** Currently iPhone is Speed-4bit-only by
contract (`platforms: ["iOS","macOS"]` for Speed, `["macOS"]` for Quality). The 17 Pro's ~6 GB
entitled limit *might* fit 8-bit under the streaming path (the non-streaming ~5.7 GB+ figure is the
wrong yardstick, §3), but this is unproven and device-fragmenting (8 GB devices can't). Treat as a
research spike behind the 8 GB proof + a streaming-path 8-bit footprint measurement, not a commitment.

**Done / disposed (do not re-open):** the talker-KV sliding window (inert at the 2048-token cap;
shipped env-only via `QVOICE_TALKER_KV_WINDOW`, OPTIMIZATION.md §F.2); `compile()` on the quantized
stack (tested, ~5% regression, §5); the punctuation-aware audioQC recalibration (`ac86b8a`); the
memctx cosmetic cleanup (`72c95fc`).

---

## 10. Invariants / do-NOT (iOS-specific)

- **Do not reintroduce `bufferingNewest` for product events.** Keep the 96-event iOS and 256-event
  macOS suspending router plus `GenerationEventDeliveryProbe` accounting; audio-bearing preview
  sends must backpressure rather than evict an older event.
- **No hard `Memory.memoryLimit` on any tier** (reverted in `b77c08e`) — it over-promised headroom
  and caused spurious downgrades. Gate on `os_proc_available_memory()` / the band instead.
- **`Qwen3TTSMemoryCaches.clearAll()` runs on iPhone hard-trim/unload/failure only** — macOS preserves
  cache warmth. Don't make macOS clear, don't stop iPhone clearing.
- **No Quality→Speed OOM fallback** — iPhone is Speed-only by contract; picking a variant loads it and
  surfaces the real error (no silent downgrade).
- **Admission blocks on critical headroom/GPU only** (`guardModelAdmission` throws
  `insufficientMemory` at critical headroom band; footprint-only critical never blocks — it
  gates warmth/trim/in-flight-cancel instead). Don't widen the block to the footprint band
  without a maintainer decision.
- **The footprint-based aggregate band is live, not dead** — it's a distinct criterion from the
  headroom band even on the single in-process process (§2.3). Don't remove it as "redundant."
- **Inline PCM preview is emitted by default on every platform** — the debug-gated
  `QWENVOICE_STREAMING_PREVIEW_DATA=off` opt-out exists only for memory-isolated benchmarks or
  debugging.
- Carry the backend invariants from OPTIMIZATION.md (don't revert the decoder-drift fix `4fab110`,
  don't pipeline the 15-pass Code Predictor loop, don't quantize the TTS KV).
