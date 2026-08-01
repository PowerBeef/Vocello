# Historical optimization decision ledger

Durable, dated record of backend/MLX and output-quality optimization work that was investigated,
decided, shipped, or deferred through the 2026-06-16 program and its explicitly dated follow-ups.
It is not the current runtime, telemetry, memory, or benchmark acceptance contract. Use generated
[`HISTORY.md`](HISTORY.md) for current validated runs,
[`../docs/development-progress.md`](../docs/development-progress.md) for the active checkpoint, and
[`../docs/reference/telemetry-and-benchmarking.md`](../docs/reference/telemetry-and-benchmarking.md)
for current measurement semantics. Git history and `LEGACY_HISTORY.md` retain the older narrative.

## Reference baseline

[`baseline-2026-05-31-641a541.md`](baseline-2026-05-31-641a541.md) — pre-optimization reference, CLI-driven
(`vocello bench`), native floor **8 GB** tier. Headline: **RTF 0.20–0.89 (slower than realtime)**; the
**decode loop dominates wall time** and scales ~linearly with length; **clone is the heaviest** per length
and on memory (~7.4–8.7 GB physFoot in-process); `trims = 0` everywhere.

[`baseline-2026-06-16-45720dd-streaming-default.md`](baseline-2026-06-16-45720dd-streaming-default.md) —
**streaming-default** baseline after switching `vocello bench` / `vocello generate` to streaming by default.
Custom/Design Speed RTF **0.95–1.04**, physFoot **2.4–3.8 GB** (down from ~7–8 GB non-streaming); Custom
Quality RTF **0.77–0.84**, physFoot **3.1–3.6 GB**. All QC pass; `trims = 0`. Design Quality not installed
on the bench machine. Historical manual ledger: [`LEGACY_HISTORY.md`](LEGACY_HISTORY.md). New comparable
runs: generated [`HISTORY.md`](HISTORY.md).

### §K addendum — long-form QC calibration and the phase-7 QC-failure reattribution (2026-07-23)

Driving the phase-11 live long-form acceptance surfaced a chain of deterministic
QC findings:

- **The long-form segment failures were systematic, not flaky.** Three
  compounding causes: (1) the app-side segment gate ran the persisted-WAV
  analyzer with `expectedPauseCount: 0` because it never received the segment
  text, so every natural sentence pause counted as an excess dropout; (2) the
  initial planner budget (512 estimate units ≈ 1,500 chars ≈ 100 s) exceeded
  the delivery-validated ≤900-char envelope and produced genuinely degenerate
  pacing (a live ~1,100-char segment showed a 2,073 ms interior gap); (3) even
  at the 900-char scale, the dropout thresholds (egregious 1,200 ms /
  suspicious 900 ms / long-pause 350 ms) were calibrated on the ≤341-char
  canonical corpus and misclassified minute-scale narration pacing — a
  retained rejected segment (64 s, healthy RMS −24.6 dBFS) had its six >1 s
  gaps position-correlated with sentence/comma/pseudo-word boundaries, max
  1,435 ms. Fixes: pause budgets threaded through every app-side QC call, the
  planner budget bound to min(codec-safe, 300 delivery-validated units), and
  duration-aware thresholds (≥45 s content: 600/1,500/2,000 ms) pinned by a
  deterministic core test.
- **Failure evidence is no longer discarded.** A mandatory-QC rejection now
  names its rule flags in the error and, in diagnostics-enabled sessions,
  retains the rejected staged WAV (newest only) beside the session tree — the
  mechanism that produced the calibration evidence above.
- **The phase-7 intermittent QC failures are reattributed to "unknown, now
  diagnosable."** A near-silent-first-chunk failure fired on a build without
  the three reverted engine-loop experiments, so they were likely falsely
  convicted (they stay reverted — they bought no measured win). The two
  historical ≤341-char intermittents remain unattributed; any recurrence now
  self-documents via flags plus the retained WAV.
- **A deterministic `-O`-only crash in manifest validation** (`objc_release`
  of a garbage address in `LongFormManifestV4.validated()`, 4/4 reproduction
  in the optimized UI-lane build, invisible at `-Onone`) was isolated with a
  stage-breadcrumb bisect and eliminated by rewriting the validator without
  keypath-literal `map`/`allSatisfy` — an optimizer-sensitivity workaround
  with deterministic before/after evidence.
- **First long-form project measurement (2026-07-23, local evidence).** The
  smoke journey now emits the project wall clock (Generate All → settled
  outcome) and the smoke lane combines it with the newest v4 manifest into
  `long-form-project-summary.txt`. First instrumented run: 3 segments
  (60.8/51.1/49.4 s), 161.5 s joined audio, 92.0 s wall → **project RTF
  1.76**, inside the canonical gated single-take band (1.68–1.83) — the
  sequential pipeline (planning, per-segment QC, assembly, manifest) adds no
  meaningful throughput cost. Registry publication would need the benchmark
  pipeline's schema review and is deliberately not included.
- **Line batch unified onto sequential streaming (2026-07-23).** Ordinary
  multi-line batch left the legacy quality-first full-result XPC batch route:
  every item now streams like a single take (flat memory, mandatory engine
  Fast QC, standard streaming telemetry, live preview), covered by the new
  `test07_LineBatchJourney` smoke journey. Blueprint P1 is closed for both
  batch flavors.
- **The generation performance gate now holds across whole long-form runs.**
  It previously flickered per segment (off during inter-segment QC/saves and
  the CPU-heavy assembly); a sustained performance-activity refcount on the
  engine store keeps glass in its solid-fill fallback from first segment
  through assembly, without touching the single-generation busy guard.
- **Smoke nonces are pronounceable words** (hex tokens were spelled out with
  pause-inducing character breaks that consumed unbudgeted pause allowance).

## Status at a glance

| # | Workstream | Status | Where |
|---|---|---|---|
| A | Per-stage decode breakdown (measure) | ✅ done | `ac86b8a` (`summarize_generation_telemetry.py`) |
| B | The ~586 ms "dropout" investigation | ✅ done — root-caused | this doc + `641a541` baseline note |
| C | Punctuation-aware audioQC recalibration | ✅ done + verified | `ac86b8a` (now `GenerationOutputAdapter.swift`) |
| D | CodePredictor RoPE fusion | ✅ **done — closed by §H P3** (`f3cd2aa`): +26%, realtime crossed | §H |
| E | MLXSwift / mlx-swift-lm version bump (0.31.x) | ⏸ deferred — stay pinned, gated | this doc + [.claude/rules/backend-mlx.md](../.claude/rules/backend-mlx.md) "SPM pins move in lockstep" |
| F | iPhone 1.7B-4bit program — feasibility + WS0b profiling + compile/KV spikes | 🔬 see §F: compile rejected; **iOS RAM premise corrected — streaming peaks ~3 GB flat, KV windowing unneeded** | this doc + session plan |

## Grounding (the headline conclusion)

An external optimization report (a from-scratch iOS / iPhone-15-Pro playbook for Qwen3-TTS 1.7B) was
ground against Vocello's **shipped macOS engine**. Finding: the vendored `mlx-audio-swift` port **already
implements the large majority of its recommendations** — `small_to_mtp_projection` 2048→1024 bridge,
2048-dim speaker embedding, interleaved MRoPE `[24,20,20]`, Q/K RMSNorm, `MLXFast.scaledDotProductAttention`,
a single per-frame `eval()` (no per-step `.item()`), `asyncEval` streaming, the input-side decoder-drift fix
(`4fab110`), per-tier `GPU.cacheLimit`, fp16 KV cache, and a `compile(shapeless:)` SwiGLU. The report's two
"architecture corruption bugs" **do not exist here**. Adversarial verification dropped 7 of 12 candidate
levers as already-handled / overstated / infeasible. **The genuine remaining work is narrow**, and the
highest-value item was a quality finding, not a speed lever.

## A — Decode-loop measurement (done)

Added a per-stage **Decode breakdown** to the summarizer (`talker · sampCB0 · codePred · code2wav ·
stepEval · other`, from the `timingsMS` sub-keys already captured in the engine row).

**Key finding (changed the plan):** these are Swift-side wall-clock timers around **lazy** MLX ops, **not**
per-stage GPU compute. On custom/quality/long, `stepEval ≈ 77%` of decode is the **fused** compute of
Talker + 15× Code Predictor + sampling (the single per-frame `eval()`); `talker`/`codePred` measure graph
*build* time; `code2wav ≈ 0` because the decoder is `asyncEval`'d (Phase 2c) and overlaps the token loop —
pipelined, not free. **Consequence:** the wall-clock breakdown **cannot attribute decode *compute* per
stage**. Doing so needs an Instruments `xctrace` capture of the existing os_signpost intervals
("Talker Forward" / "Code Predictor Loop" / "Step Eval Flush" / "Audio Decoder"). This **gates D**.

## B — The ~586 ms "dropout" (done; root-caused — not an engine defect)

Effective sampling (all modes use `officialQualityDefault`): **temp 0.9, topK 50, topP 1.0 (nucleus off),
repetitionPenalty 1.05, minP 0.0**.

The baseline flagged a real ~586 ms mid-utterance silence. Investigation: it reproduced systematically on
long content (every long custom/design cell failed audioQC; clone passed), but objective analysis of fresh
takes showed **every interior silence ≥150 ms maps to a punctuation mark** — they are the model's **natural
prosodic pauses** at sentence/comma boundaries on long, slow narration, which the old fixed ≥400 ms detector
over-flagged. The original investigation also recorded one subjective mid-phrase-gap report adjacent to a
comma pause. That historical observation is not a current promotion gate; current diagnosis uses fixed-seed
exact WAV evidence, chunk-spanning dropout metrics, locale-locked ASR, and the prosody cohort.

**Decision:** a sampling-side fix (e.g. minP floor / silence-run penalty) would suppress the model's
*natural* pauses to chase a rare, ear-only event — wrong tool, real prosody-degradation risk. Remediation
shifted to **C** (fix the tripwire). The residual case is now covered by the autonomous evidence stack.

## C — Punctuation-aware audioQC recalibration (done, verified — `ac86b8a`)

`PCM16StreamLimiter` now records interior silence-run lengths; `makeAudioQCReport` counts **long pauses
(≥350 ms)** against the text's **pause budget** (interior punctuation boundaries, from `request.text`) and
flags only an **excess** beyond it (≥2 → fail, 1 → warn) or a single **egregious** ≥1200 ms gap (≥900 ms →
warn). Else `pass`. (`Sources/QwenVoiceCore/GenerationOutputAdapter.swift`.)

**Verified** (re-bench custom,design × speed,quality × all lengths + deterministic replication on real WAVs
+ synthetic cases): **15/16 cells now `pass`** (every false-positive `fail`/`warn` cleared); the lone
remaining `warn` is a **real-but-natural ~1116 ms sentence-boundary pause** (retained for deterministic
fixed-seed diagnosis rather than manual waiver).
Sensitivity retained — synthetic 1300 ms → fail, 11 long pauses → fail. Perf unchanged (engine untouched;
see the `3da580d` row in `LEGACY_HISTORY.md` vs the `641a541` baseline). A current promotion run must clear
the applicable deterministic QC, ASR, and prosody gates; listening is optional annotation only.

## D — CodePredictor RoPE fusion (CLOSED — implemented in §H P3, `f3cd2aa`; kept for history)

CP RoPE is hand-rolled (`Qwen3TTSCodePredictor.swift`); `MLXFast.RoPE` exists in MLX-Swift 0.30.6 and the CP
uses standard 2D RoPE, so it *could* swap in. Realistic ceiling **~2–3 % RTF (CP only)**. **Gate (revised by
A):** the wall-clock breakdown can't decide if CP compute is a worthwhile slice of the fused `stepEval`, so
D should only be attempted **after an Instruments os_signpost capture** of one long/quality generation shows
the "Code Predictor Loop" interval is a meaningful fraction of "Step Eval Flush" GPU time. Vendored edit →
follow [`../docs/reference/mlx-audio-swift-patching.md`](../docs/reference/mlx-audio-swift-patching.md);
must preserve exact numerics (KV precision).

## E — MLXSwift / mlx-swift-lm version pin (deferred; **stay pinned**)

Pinned `exact: 0.30.6` (mlx-swift) + `2.30.6` (mlx-swift-lm) in **both** `project.yml` and the vendored
`Packages/VocelloQwen3Core/Package.swift`. Latest upstream is **0.31.3** (+ `mlx-swift-lm` 2.31.x;
a separate 3.x line also exists). **Decision: keep pinned at 0.30.6 / 2.30.6.** Rationale: the backend is
vendored + hand-ported. The owned `Qwen3RuntimeTests` suite protects deterministic runtime invariants, but
cannot by itself rule out performance or perceptual drift from a compute-substrate change; the exact pin
keeps the tested substrate deterministic. 0.30.6 is the benchmarked, working version and 0.31 adds nothing
Vocello needs. 0.31 is **not
a free bump** — it changes the MLX quantization API (`Quantizable.toQuantized` gains a `QuantizationMode`;
quantize moved to a top-level fn), which touches the 4-bit (Speed) / 8-bit (Quality) model-load path, and
it's a core-MLX backend bump that can shift RTF/memory (what these benchmarks track). **When upgrading**
(quarterly review, or when a fix/model requires it): branch → bump all pin sites (project.yml mlx-swift +
vendored Package.swift mlx-swift & mlx-swift-lm, in lockstep) → `regenerate_project.sh` → both
`build_foundation_targets.sh` → `vocello bench` vs `baseline-2026-05-31-641a541.md` + fixed-seed
QC/ASR/prosody proof → keep only if RTF/quality/QC are unchanged; otherwise document the blocker and revert.
Avoid the `mlx-swift-lm` 3.x
major line unless a feature specifically requires it.

## F — iPhone 1.7B 4-bit optimization program (2026-06-01)

> **Superseded for the *current* iOS state — see [`../docs/reference/ios-engine-optimization.md`](../docs/reference/ios-engine-optimization.md).**
> §F below is the original backend-feasibility study (its decode-loop + RAM-lever findings are still valid and
> shared by both platforms). But its **process model is out of date**: the engine no longer runs in an
> ExtensionKit extension — it runs **in-process in the app** (`7822a8a`; the extension was removed in
> `aed617c` because a non-UI extension's Jetsam cap can't be raised by the entitlement). On-device generation
> now works (iPhone 17 Pro, RTF ~1.6–1.9, ~3 GB streaming peak, 0 trims). The iOS-engine doc is the live iOS
> progress + roadmap record.

Goal: get Speed (4-bit) Qwen3-TTS running on iPhone 15 Pro (8 GB). Full plan + the 57-agent verified lever
inventory live in the session plan; this records the standing findings. (Historical note: this study assumed
the engine ran in the iOS ExtensionKit extension with a separate Jetsam budget — that approach was abandoned
in favor of the in-process engine; see the doc linked above.)

**Feasibility (isolated engine, Speed 4-bit):** Custom/Design ~2.8–3.3 GB (fits under the default streaming
limit per §F.1 — the entitlement is headroom insurance, not required); Clone/long ~4.7 GB (marginal — wants
the raised limit ≥~5.2 GB or a ~400 MB cut); Quality 8-bit ~5.7 GB+ (out of scope — iPhone is 4-bit-only).
Hard floor (4-bit weights + activations) ~2.2 GB. **The increased-memory entitlement is a self-serve
capability** (enable it on the App ID — not an Apple grant; already declared in both iOS entitlements files).
The actual #1 prerequisite is re-establishing on-device build/deploy/proof tooling + on-device validation.

**WS0b decode-loop GPU attribution** — `xctrace --instrument os_signpost`, custom/speed/long, **327 frames /
31.1 s** wall, native 8 GB Mac (paired Begin/End from the raw `os-signpost` table; the `os-signpost-interval`
table collapses because the engine reuses `OS_SIGNPOST_ID_EXCLUSIVE`):

| stage (Σ over 327 frames) | total ms | % gen | mean/frame | nature |
|---|---|---|---|---|
| **Step Eval Flush** (single per-frame `eval()`) | 19072 | 61% | 58.3 ms | **GPU compute** — talker + 15×CP + sampling, fused |
| **Code Predictor Loop** | 5233 | 17% | 16.0 ms | **Swift CPU** — builds the 15-pass graph each frame |
| **Talker Forward** | 1744 | 6% | 5.3 ms | **Swift CPU** — graph build |
| inter-frame gap (Code2Wav asyncEval + chunk plumbing) | ~4000 | ~13% | — | overlapped decode |
| Sample First/Predicted + Codec Embed + EOS | ~620 | 2% | — | mostly build |

**Findings (supersedes the old workstream D ordering):**
- **`compile()` the per-frame graph — TESTED & REJECTED (2026-06-01).** The ~21 ms/frame build overhead is
  dominated by constructing the **quantized** `Linear` projections (4-bit → `QuantizedLinear` after
  `quantize(model:)`; bits 4 / group 64 / affine). A throwaway validation spike compiled the full talker
  MLP *including* the quantized projections via `compile(inputs: [gate, up, down], shapeless: true)`. Result:
  it **builds and runs correctly** (audioQC **pass** — so compiling a quantized forward IS feasible on MLX
  0.30.6), but it **regressed warm RTF ~5%** in a clean same-session A/B (custom/speed/long: **eager 0.80 vs
  compiled 0.76**; decode 24.8 s → 27.2 s). Cause: declaring the quantized module params as `inputs:` makes
  `compile` marshal their state (packed weight + scales + biases) on every call, costing more than the Swift
  build overhead it removes — and that cost **scales with the compiled region**, so a bigger region (whole
  layer / the 15-pass CP loop) would regress *more*, not less. **Conclusion: the ~22% build overhead is not
  productively attackable via MLX 0.30.6 `compile` on this quantized stack; do not pursue the fixed-shape-KV
  + compile rewrite.** (Only untested variant — baking weights as trace constants with no `inputs:` — is
  discouraged by MLX docs for module state and risks correctness; not recommended.)
- **Step Eval Flush (GPU, 61%)** is the model's real compute — largely fixed for 1.7B 4-bit at this
  precision; no transparent lever (quantization-mode work is pinned out at MLX 0.30.6, see §E).
- RoPE fusion → `MLXFast.RoPE` (CP + Talker): only a small slice of the build, and the compile spike showed
  build-time is hard to reclaim cheaply here → expected marginal/uncertain; low priority.

**RAM-lever corrections (under the strict no-degradation bar):**
- **Sliding-window KV is NOT a transparent RAM lever.** `RotatingKVCache` (mlx-swift-lm `KVCache.swift:441`)
  grows in 256-token steps and only trims once it exceeds `maxSize`; a window large enough to be lossless
  (≥ the ~500–600-token real generation length) saves ~0 RAM, while a window small enough to cap RAM **drops
  oldest context** → not transparent → fails the strict bar on long content. Its real use is fixing shapes
  for the compile lever above.
- **Eager `talkerSourceWeights` release — TESTED, no-op (2026-06-01).** Reordered to free the source dict
  *before* the talker eval (pre-extracting the speaker subset). Clean same-session A/B on custom/speed/long:
  **no measurable load-peak reduction** (cold/warm physFoot + peakGPU within noise; RTF unchanged). Confirmed
  the prediction — with no speaker encoder, `talkerSourceWeights` ≈ the talker buffers already held by the
  model (MLX arrays are ref-shared), so releasing the dict frees ~nothing. Could help only the clone/base
  **speaker-encoder** path (holds the speaker subset across the eval); re-test there with a saved voice if
  clone/long RAM becomes the focus. **Reverted (not committed).**
- **Net (revised after the compile spike):** backend speed gains for 1.7B 4-bit on this stack are **limited**
  — GPU compute (61%) is fixed at this precision, and the build overhead (22%) is not compile-attackable
  (regresses). The primary iPhone RAM unlock is the **entitlement**; transparent backend RAM cuts are modest.
  The realistic path to acceptable **iPhone RTF** is therefore the entitlement, **not** backend
  micro-optimization of the 1.7B decode loop. (A 0.6B-variant evaluation was considered and
  **ruled out 2026-07-02** — Voice Design requires 1.7B; Vocello ships 1.7B variants only.) Worth confirming with one more os_signpost capture whether the
  ~13% inter-frame gap (Code2Wav/plumbing) hides any cheap win before closing speed work.

### F.1 — STREAMING vs NON-STREAMING peak RAM (2026-06-01) — the RAM premise was wrong

Chasing the iOS RAM target via the talker KV cache: a `RotatingKVCache` sliding window for the talker was
implemented + validated (parked on `feature/rotating-kv`). It is **correct** (audioQC pass with rotation
forced; full audio; RTF unchanged) but delivers **~0 RAM benefit** — windowing ~380 KV tokens on a 69 s
generation moved peak <5 MB. The investigation's "talker KV ≈ 2.7 GB / 30–50% of peak" was an **estimate
that the measurement refutes**: the talker KV is tens of MB, not GB.

**The real driver — and the headline correction to the whole RAM analysis:** the `vocello` bench / CLI
used to default to **non-streaming** (accumulates *all* generated codec tokens + decodes the full audio at the
end), while **iOS was already streaming-first** (emits + releases chunks). Measured on the *same* 69–76 s
custom/speed input:

| path | gpuAllocPeak | physFoot |
|---|---|---|
| non-streaming (legacy bench default, now `--no-stream`) | ~8.0 GB | ~7.6 GB |
| **streaming (iOS path / current CLI default)** | **~3.0 GB** | **~3.0 GB** |

And streaming peak is **flat with length** — short 2901 MB · medium 2860 MB · long-76 s 2992 MB. So the
non-streaming numbers that drove this entire optimization program (clone ~7–8 GB, "+3.4 GB short→long", the
"marginal/infeasible" feasibility verdict) **overstate the iOS-relevant peak by ~2.5×**. In the actual iOS
streaming path, **custom/Speed peaks at ~3 GB regardless of length** — comfortably viable on iPhone 15 Pro
(at/under even the default ~3.5–4 GB process limit; the entitlement is headroom/clone insurance, not a hard
blocker for custom/design). The +3.4 GB growth is non-streaming accumulation that iOS never incurs.

**Consequences:**
- **Re-baseline the iOS feasibility verdict on the STREAMING path** (the bench non-streaming peak is the wrong
  yardstick for iOS). Custom/Design Speed ≈ 3 GB flat. Clone streaming untested (no saved voice installed) —
  expect ~3.5–4 GB (speaker conditioning + ~3 GB floor); measure when a clone voice is available.
- **Talker-KV windowing is unnecessary for iOS** (KV isn't the driver; streaming already keeps peak flat).
  Originally parked on `feature/rotating-kv`; the "multi-minute single-shot" escape hatch was later closed too
  (see **§F.2** — the token cap forecloses it). Final disposition: shipped **env-only, off by default**.
- For any future bench that wants an iOS-representative peak, use `vocello generate` or `vocello bench`
  (both stream by default), **not** the non-streaming full-result path (`--no-stream`).

### F.2 — Windowing revisited (default-on + toggle) → INERT at the token cap; shipped env-only (2026-06-01)

Revisited per a directive to enable the window on **both platforms, default-on, with a user disable toggle**.
Built the full feature — per-tier `W = 2048` default, a cross-process `NativeTalkerKVCacheGate`, a Settings
toggle on macOS + iOS, and the `initialize`-handshake relay — then two findings collapsed the rationale and it
was scoped back down:

1. **Generation is nondeterministic.** Two identical-config CLI runs of the same text differ (21.4 s vs
   22.6 s, different SHA) — the sampler is unseeded. So the plan's "byte-identical output" transparency test
   **cannot hold** regardless of cache. Transparency survives only *by construction*: `RotatingKVCache`
   returns bit-identical keys/values to `KVCacheSimple` until `offset` exceeds `maxSize`.

2. **The window is INERT at the current token cap.** `maxCacheSize = keep + W = keep + 2048`; tracing
   `updateInPlace` (`KVCache.swift:518`), the first *rotation* (overwrite of oldest generated KV) fires on
   **generated token 2049** (`idx == maxCacheSize → idx = keep`). But **`maxNewTokens = 2048`**
   (`Qwen3GenerationConfiguration()` default, `QwenVoiceBackendCore.swift:20`) — and the engine **hard-errors**
   at the cap, *discarding* the output (verified: a 535-word / 2894-char script → `NativeRuntimeError …
   "reached maxNewTokens before EOS. The output was discarded"`, exit 1). Generation therefore stops exactly
   one token *before* the first rotation. With `W = 2048 = maxNewTokens` the rotating cache **never rotates,
   never trims, never reorders** → bit-identical KV to `KVCacheSimple` on every realized generation, same peak.
   The "multi-minute single-shot" use case §F.1 left open **cannot occur** — the token cap forecloses it.

**Net:** `W ≥ maxNewTokens` ⇒ provably transparent but provably useless (no rotation; ~0 RAM benefit atop the
already-tiny talker KV per §F.1). `W < maxNewTokens` ⇒ *would* rotate, but those generations already error out
at the cap, and the talker-KV saving is still ~0. No win either way at the current config.

**Disposition (maintainer call):** dropped the default-on per-tier policy, the user-facing Settings toggles
(both platforms), and the IPC handshake relay. **Merged env-only plumbing** — the `QVOICE_TALKER_KV_WINDOW`
knob in `NativeMemoryPolicyResolver` + the vendored `RotatingKVCache` talker path — **off by default**. It is
dormant dev/insurance capability that activates only if the token ceiling is ever raised above the window
(e.g. `checkpointDefaultMaxNewTokens = 8192`). `feature/rotating-kv` deleted.

## Invariants / do-NOT (carried from the grounding)

- No hard `Memory.memoryLimit` (reverted in `b77c08e` — spurious OOM downgrades).
- No **output-side** silence gating/smoothing of dropouts (masks the root cause; risks clipping real pauses).
- Don't revert the decoder-drift fix to output-side overlap-add (`4fab110`).
- Don't pipeline the autoregressive 15-pass Code Predictor loop; don't quantize TTS KV; keep macOS
  event delivery lossless. The original unbounded-stream implementation recorded by this ledger has
  since been superseded by the current bounded, measured backpressure contract; see
  `docs/development-progress.md` rather than restoring the historical buffer choice.
- Don't "fix" the phantom 1.7B arch bugs (projection / speaker-dim / MRoPE are correct).

## iOS (now on-device-capable — see the iOS-engine doc)

iPhone is no longer compile-safe-only: on-device build/validation tooling is established, the entitlement is
enabled, and generation works on device (in-process). The `os_proc_available_memory()` gating + per-tier
policy are implemented (`NativeMemoryPolicyResolver` iPhonePro case + `IOSMemoryBudgetPolicy`); no hard
`memoryLimit` (reverted `b77c08e`). The remaining iOS levers (an 8 GB-device proof, the signed-IPA/TestFlight lane; thermal
observation + proactive-warm gate shipped 2026-07-02; the 0.6B evaluation was ruled out the same
day — Voice Design requires 1.7B) + the full progress record live in
[`../docs/reference/ios-engine-optimization.md`](../docs/reference/ios-engine-optimization.md). Entitlement
detail: [`../docs/reference/ios-increased-memory-entitlement-request.md`](../docs/reference/ios-increased-memory-entitlement-request.md).

### Live streaming playback — verified zero-cost (2026-06-06, `b961cc8`)

iOS live-preview playback (audio during generation) was checked for engine impact via an on-device A/B on
the same binary: live OFF (`QWENVOICE_STREAMING_PREVIEW_DATA=off` → `.skip` = pre-feature: no PCM, chunks
dropped, no consumer) vs ON (`.emit` = feature; the device-diagnostics runner keeps `AudioPlayerViewModel` alive so
the `AVAudioEngine` consumer is exercised too). iPhone 17 Pro, custom/speed, short+long × 3, interleaved.
**Result: no measurable cost** — RTF +0.5% overall (short −1.9% / long +0.2%, within run-to-run noise),
physFootprint peak identical (~2.7 GB, off-max 2731 vs on-max 2722 MB; inside the 2.4–3.3 GB band, far
under the 4.5 GB guard), **0 memory trims** across all 12 runs, audioQC all pass. Historical rows are in
[`LEGACY_HISTORY.md`](LEGACY_HISTORY.md). The `scripts/ios_device.sh` launch now forwards caller-set
`QWENVOICE_*`/`QVOICE_*` environment variables. A current reproduction must supply a complete diagnostics
spec and an opaque label, for example:

```sh
QWENVOICE_STREAMING_PREVIEW_DATA=off \
  scripts/ios_device.sh bench 'custom:speed:Streaming-preview-A-B.' --label streaming-preview-off
```

## G — macOS UI smoothness under engine load (2026-06-09; XPC kept)

**The architecture question, settled.** The XPC engine service was introduced (`228d3cd`, 2026-04-18)
because the SwiftUI UI lagged under engine load on RAM-constrained Macs. Investigated whether the
in-process iOS model would be more elegant. Verdict: **keep XPC** —
- Per-chunk XPC wire cost is metadata-dominated (~<2 KB; PCM travels by file path), and the per-chunk
  UI path was already clean (off-MainActor producer, `.utility` drain, zero per-chunk `@Published`).
  IPC was never the lag.
- iOS proves smoothness comes from *memory discipline*, not process model — so the discipline was
  ported instead (below).
- XPC uniquely provides (1) proven crash isolation (the 2026-05-15 MLX C++ assertion killed the
  *service*; the app survived + reconnected) and (2) the retirement lever below, which in-process can
  never have. A dev-only in-process A/B mode was considered and declined.

**Shipped (all validated live on a native 8 GB Mac):**
1. **UI-responsiveness KPI** — `MainThreadStallWatchdog` (SharedSupport/Telemetry): 100 ms main-thread
   heartbeat during generations; `uiStallCount50/250`, `uiMaxStallMS`, `uiHeartbeats` in the app-layer
   row counters; `UIstall` summarizer column + trailing `uiMaxStall ms` ledger column. "The UI lags" is
   now a number. First sample (XPC, custom/speed, native floor tier): 3 stalls >50 ms, max 241–262 ms
   per ~5 s generation.
2. **Warm-admission discipline** (iOS port) — `MacWarmupAdmissionPolicy` defers *proactive* warms while
   the app-process kernel pressure level is soft/hardTrim on floor8GB/mid16GB (+30 s post-hardTrim
   hysteresis on floor). `QWENVOICE_MAC_WARM_GATE=off|records|enforce` (default `enforce` since 2026-06-09 — pressured
   validation done: simulated hardTrim produced both `memory pressure (hardTrim)` and
   `post-hardTrim cool-down` deferral events on the native floor tier). User generations never gated.
3. **Idle-unload churn fix** (found during validation; possibly the real historical lag source) — the
   warm coordinator cleared `completedContext` on every idle transition, so after each 120 s floor-tier
   idle-unload it immediately re-warmed the ~2.3 GB model: an endless unload→reload churn that defeated
   the memory policy. Idle-unloads now stick on floor8GBMac. First post-fix generation: **0 UI stalls**
   (vs 3/max-262 ms pre-fix; small sample, watch the ledger column).
4. **Service retirement-to-reclaim** — the XPC-only lever: model unload returns weights, but MLX heap
   fragmentation + Metal shader caches stay resident until process exit. `shutdownWhenIdle` IPC +
   `MacEngineServiceLifecycleCoordinator` (floor tier, idle + hardTrim-or-5-min-dwell + 30 s grace;
   `QWENVOICE_ENGINE_RETIRE_DWELL_SECONDS` dev override). Client marks the exit expected → no error UI,
   no auto-reconnect, lazy relaunch. Measured: service exited on schedule (RSS → 0), follow-up
   generation relaunched transparently, `warmState: cold`, TTFC 2814 ms vs ~1220 ms warm.

**Residual:** the post-retirement readiness note briefly shows "Preparing Custom Voice" (cosmetic; no connection is
actually made). Ledger rows: `pre-ui-kpi baseline` and `post smoothness ws sanity` (2026-06-09).

## H — Qwen3-specialization program (2026-06-09; branch `engine-risk`)

The exhaustive backend program: specialize the vendored tree for Qwen3-TTS, close the remaining
speed/RAM levers under the standing quality gates, and build an iPhone-15-Pro memory-profile diagnostic
for the maintainer's 17 Pro. Phases P0–P6; per-phase ledger rows labeled `P<n>-…`.

### P0 — Instruments compute attribution (the long-gated capture, finally run)

Capture: `xctrace record --template "Metal System Trace" --instrument os_signpost --launch -- vocello
bench --modes custom --variants speed --lengths long --warm 2` on the native 8 GB M2 (trace overhead
≈25%: RTF 0.64–0.70 under trace vs 0.85 clean — fractions are the deliverable, not absolutes).
Signpost interval table parsed clean (no WS0b collapse on Xcode 26 xctrace). Warm-gen attribution
(consistent across both warm gens, 270–279 frames each):

| Window (signpost) | % of generation wall | GPU busy inside the window |
|---|---|---|
| Step Eval Flush (the fused per-frame eval) | 66–67% | **41–50%** |
| Code Predictor Loop (graph build, 15 passes) | 13–15% | **3–5% (idle)** |
| └ Code Predictor Step (per-pass build, ~1.0 ms × 15 × frame) | 12–13% | — |
| Talker Forward (graph build) | 4–5% | **2–5% (idle)** |
| Sampling (first + predicted codebooks) | ~1.6% | — |
| **Whole generation** | 100% | **31–37%** |

**The headline finding: the workload is kernel-launch/CPU-bound, not GPU-bound.** Even inside the
fused eval the GPU idles half the time (batch-1 tiny-matmul launch gaps in the MLX Metal scheduler);
during the ~23%-of-wall graph-build phases it is essentially idle, so every ms of Swift build cost
removed converts ≈1:1 to wall time. Decision table outcomes:

- GPU busy 31–37% « 80% → **P2 (graph-build/allocator elimination) is first-order. GO.**
- CP RoPE fusion (§D) → **GO with revised rationale**: the win is ~6 graph-build ops → 1 fused op per
  CP pass (×15×~300 frames of CPU build), not GPU time. §D's "2–3% RTF (GPU)" framing is obsolete.
- Sampling-stall lever → not opened: Sample First Codebook ≈0.2% wall; the eval-window idle is
  launch-shaped, not a token-read stall.
- Audio Decoder row: N/A in this capture — `bench` runs the quality-first batch path (no streaming
  decoder signposts). The decode shows up as the ~23% GPU-busy remainder outside stepEval.
- **Structural ceiling (recorded, not actionable at 0.30.6):** the ~50% launch-gap idle inside
  stepEval is only addressable by graph capture/compile — measured −5% at 0.30.6 (§F WS0b). Re-test
  under the gated 0.31.x bump (§E) whenever that happens.

**Post-program re-capture (2026-07-24, same command/host, current shipping runtime — post-P2/P3,
post-Phase-4 cutover, streaming-first bench, `--no-summary` diagnostic):** warm-gen attribution
(264/294 frames):

| Window | % of generation wall (was) | GPU busy inside (was) |
|---|---|---|
| Step Eval Flush | 58.9% (66–67%) | **54.9–55.5%** (41–50%) |
| Code Predictor Loop | 15.4% (13–15%) | 0.7–0.9% (3–5%) |
| Talker Forward | 7.5–7.6% (4–5%) | 0.3–0.6% (2–5%) |
| Audio Chunk Eval (streaming decode) | 3.7% (N/A) | — |
| **Whole generation** | 100% | **46.9–47.2%** (31–37%) |

Reading: the P2/P3 launch-overhead work moved GPU busy from ~1/3 to ~1/2 — the same GPU work now
packs into less CPU-idle wall, which is exactly the theory P0 predicted (build-cost ms convert
≈1:1 to wall). The structure is unchanged: still launch/CPU-bound (« 80%), graph-build windows
still essentially GPU-idle, so the remaining headroom stays behind the §E-gated graph
capture/compile ceiling, not behind more kernel work. Trace overhead was negligible this time
(RTF ≈ 1.09 under trace vs 1.07 canonical warm/long) — consistent with launch-gap reduction also
shrinking the tracer's per-launch cost surface. Raw trace digested and discarded per the
ephemeral-trace rule.
- Clone/long capture: skipped as not decision-relevant (identical per-frame loop; clone differs in
  prefill, and P4's KV decision is a physFoot A/B, not a trace question).

### P1 — Vendored tree specialized to Qwen3-TTS (`a2b5f15`)

Deleted ~36K of ~49K LOC: STT/STS/VAD/LID/G2P/UI/Tools targets+products+executables, eight non-Mimi
codec families, `Mimi/Mimi.swift`+`AudioCodecModel.swift`, dead Core files (AudioPlayer,
AudioSessionManager, PCMStreamConverter, UnigramTokenizer), unused swift-transformers/MLXLLM deps.
Compiler-arbitrated keeps: `Seanet.swift` (SeanetEncoder is the speaker-encoder front end),
`AudioUtils.swift`+`DSP.swift` (clone path uses `loadAudioArray`/`computeMelSpectrogram`). Both
foundation builds green; clone path validated post-prune (0.55 warm vs 0.56 baseline, QC pass).
Honesty note: the row labeled `P1 vendored Qwen3 specialization` benched a stale pre-P1 binary
(`build.sh build` does not rebuild the CLI) — it serves as the fresh same-day baseline instead;
P1's real gate was the link step plus the later clone validation.

### P2 — Sampler scratch + CP step constants (`0c3a313`; ~+1% wall, allocator relief)

CP sampler scratch (the 14 CP samples/frame re-allocated arange/zeros/-inf — ~17K allocs per
generation), dtype-keyed -inf row caches for topK/topP, zeros/eos caches, CP pass-0 mask memo.
Same-conditions A/B (P1-only control vs P2): warm RTF 0.80 → 0.81, stepEval/frame 67.9 → 65.8 ms,
codePred/frame 16.3 → 16.0 ms. Within noise on wall but consistently positive; main value is
allocator pressure (iPhone-relevant) + build-phase reduction. **Thermal lesson:** warm cells can
read *slower than cold* on a heat-soaked 8 GB M2 — accept/reject benching needs cool-downs and
same-day controls (the 2026-05-31 "0.85" is a fresh-machine number).

### P3 — Fused CP RoPE (`f3cd2aa`; **+26% — the 8 GB Mac crosses realtime**)

`MLXFast.RoPE` (offset-based) replaces the manual rotate-half chain in the code predictor:
~600 fewer kernel launches per frame on the launch-bound decode. **custom/speed/long warm RTF
0.81 → 1.02**; stepEval/frame 65.8 → ~50 ms; codePred build 16.0 → 11.3 ms; clone 0.55 → 0.58.
Numerics: fused kernel rotates in fp32 vs the old bf16-quantized tables — probe measured exactly
1–2 bf16 ULPs on q/k (a precision improvement, not identical token streams), so the full
perceptual gate ran: audioQC pass + agy listening on fresh custom/design/clone takes, all clean.
The talker keeps its manual path — 3D interleaved MRoPE `[24,20,20]` is not expressible by
`MLXFast.RoPE` (a possible future lever only if decode-time positions prove degenerate-equal).
§D is hereby **closed: implemented, far above its estimated ceiling** (the 2–3% estimate assumed a
GPU-bound workload; the launch-bound reality made it 10×).

### P4 — RAM levers (`6f9f04b`; KV-quant NOT shipped)

- **8-bit talker KV** (via `attentionWithCacheUpdate`, behavior-identical for plain caches):
  clone/long saves 271 MB physFoot but costs **−8.6% RTF** (dequant kernels on a launch-bound
  decode). No tier has a RAM emergency that justifies it (iPhone clone ~3.3 GB vs 5–6 GB entitled,
  0 trims) → **env-only dev knob** `QVOICE_TALKER_KV_QUANT=8|4`, default off, never combined with
  the rotating-window cache.
- **Load-peak transient**: closed without chunked binding — on-device evidence (0 trims, flat
  ~2.4–3.3 GB streaming peaks, §F) shows the load transient is not a binding constraint on any
  shipping tier.
- **GPU cacheLimit re-sweep**: not re-run this program; current per-tier values stand (set during
  the iOS program; no P0–P4 row shows cache-pressure misfit). Open as a low-priority follow-up.

### P5 — iPhone 15 Pro memory profile: validated (memory dimension PASS)

On-device under `--memory-profile iphone15pro` (5,000 MB clamp; rows stamped `memoryProfile`):
custom/long **RTF 1.89** / physFoot 2,723 MB (margin 2,277 MB ≥ the 500 MB bar); clone **RTF 1.62**
/ 3,332 MB (margin 1,668 MB ≥ 300 MB); **0 trims, QC pass, clone gate ON** (proven by execution).
On-device RTF sits at the top of the pre-program 1.6–1.9 band (P3's launch-bound win is smaller on
the A19 than the M2 — its launch overhead is lower, consistent with the P0 theory). Ops note: the
first launch of a freshly installed build can exceed the default 300 s device-diagnostics timeout
(cold Metal-shader compile) — use `QVOICE_IOS_BENCH_TIMEOUT=600` after installing a new binary.
The analytic 15 Pro compute projection (0.60× ⇒ RTF ≈ 1.0–1.1 post-§H) and the real-device gate
remain as documented in ios-engine-optimization.md §9.

### P6 — Final full-matrix validation (macOS, native floor tier)

`P6 final full-matrix (P0-P4)` ledger row + the 12-cell speed matrix: **QC pass on every cell**
(including design/long, historically warn/fail-prone). Warm medians — custom 0.99/1.11/**1.07**
(short/medium/long), design 0.99/1.11/0.99, clone 0.24/0.47/**0.63** (clone short is prefill-
dominated by design). Headline vs the same-day pre-program baseline: **custom/warm/medium
0.83 → 1.11 (+34%)**; custom/warm/long 0.80 → 1.07 (+34%); clone/long 0.55 → 0.63 (+15%);
physFoot unchanged (4493 vs 4486). Listening: agy 3-mode adjudication clean (P3 gate); nothing
flagged in the final matrix.

## I — Delivery-accuracy program (2026-06-11; deep-research-driven)

Research basis: a 7-agent sweep (HF hub map, the Qwen3-TTS technical report + instruct-TTS literature,
official docs + community practice, upstream mlx-audio survey, internal pipeline trace). Key external
facts: all 6 pinned mlx-community revisions = hub HEAD (official weights never changed since launch — no
checkpoint to chase); instruct adherence is highest for concrete acoustic wording (InstructTTSEval APS/DSD
77–85 vs role-play 61–68); negative constraints are officially endorsed; instruct-based dialect switching
does not work; clone+instruct awaits an unreleased 25Hz VoiceEditing checkpoint (watch item).

Shipped (each gated by bench `--delivery` QC + agy listening):

- **Bench delivery axis** (`fb2cd0a`): `vocello bench --delivery` instruct-bearing cells (notes.delivery
  stamp + `_d-<id>_` filenames; summarizer segregates them; review rubric is delivery-aware). Presets
  consolidated into `QwenVoiceCore/EmotionPreset.swift` (was duplicated macOS/iOS).
- **Sampler-order fix** (`1c8d9f5`, vendored; upstream mlx-audio #735): temperature scaling now precedes
  top-p/min-p truncation. No-op at official defaults; prerequisite for any topP/minP tuning.
- **Auto-language Latin fix** (`eceeb6d`): NLLanguageRecognizer-backed detection in
  `GenerationSemantics.qwenLanguageHint` — French/German/Spanish/Portuguese/Italian text under Auto now
  gets the right language token (was: english token + wrongly-appended diction reinforcement). Engine rows
  stamp `notes.languageHint`.
- **Official speaker descriptions** (`bc73b70`) + **presets v2** (`e9671c7`): anti-laughter clauses on
  happy/excited Strong, pitch/pace cues added, Surprised preset wording strengthened after a
  listening iteration, Voice Design briefs 4→8, `docs/qwen_tone.md` refreshed.

**Sampling A/Bs (first pass, single-take agy comparisons) — shipped defaults won all three; nothing
adopted:** (1) community "stability recipe" temp 0.8/topP 0.9 on calm — control steadier, treatment
drifted breathy; (2) subtalker temp 0.7 on happy-strong — treatment read flatter/neutral, not
steadier-timbred; (3) English diction reinforcement OFF — ON expressed the emotion *more* strongly and
crisper (the dilution hypothesis did not hold; the diction-token skip-list already prevents redundancy).
Knobs remain as dev A/B surfaces (resolved once at launch, official behavior when unset):
`QWENVOICE_TALKER_TEMP` / `QWENVOICE_TALKER_TOPP` (app policies), `QWENVOICE_TALKER_TOPK` /
`QWENVOICE_TALKER_MINP` / `QWENVOICE_SUBTALKER_TEMP|TOPK|TOPP` (vendored `Qwen3SamplingOverrides`),
`QWENVOICE_ENGLISH_DICTION_REINFORCEMENT=off` (GenerationSemantics). Single-take A/Bs are directional,
not conclusive — re-run with more reps + the maintainer's ear before ever shipping a non-default.

**Backend robustness verifications (no code needed):** (a) the vLLM-Omni pre-decode codec-frame filter
(clamp/drop out-of-range or negative codes) is unnecessary here — out-of-range codes are impossible by
construction in our single-stream path (talker suppresses the 1024 special/speaker rows except EOS,
which terminates the loop; the code predictor's vocab is exactly the 2048 codebook); it guards their
batched −1-padded path, which we don't have. (b) No `code > 0`-style length trimming exists in our
decode paths (the official `-1`-padding rule, QwenLM 5f8581d, applies to batch decode only).
(c) Speaker-embedding injection matches upstream #148: spk_id rows injected between the codec prefill
and the pad+bos suffix, with the dialect language-ID override (dylan→beijing, eric→sichuan under
auto/chinese). The optional degenerate-loop runaway guard (mlx-audio-swift ASR #174 pattern) stays
unadopted — existing EOS gating + the flat max-token cap + the audioQC tripwire cover that failure mode.

Deliberately NOT pursued (maintainer decision 2026-06-11): the MLX 0.31.x bump (backend is drastically
streamlined/customized — stay pinned; supersedes the §E "quarterly review" trigger list for this program),
CFG (absent from the architecture), batched talker/CP decode for `vocello batch` (future idea only).
Watch item: the promised `Qwen3-TTS-25Hz-1.7B-VoiceEditing` checkpoint (clone+instruct) — would unlock
delivery presets in Voice Cloning mode.

### I.2 — Delivery-adherence rate-based pass (2026-06-14, macOS)

Triggered by a "delivery + Voice Design adherence is seriously wrong" report. The agy review
pipeline was overhauled to be the measurement instrument: it now judges **adherence** (TEXT_MATCH /
DELIVERY_MATCH / VOICE_MATCH via multimodal hearing), reviews **every delivery + design cell**
regardless of audioQC (adherence failures produce acoustically-clean audio the old gate never
flagged), logs the expected description/delivery as ground truth, and is hardened against agy
flakiness (insists on hearing, retries once, hard-kills a hung agy after 6 min). Commits `3c92100`
(overhaul), `48a545a` (timeout).

Findings (rate-based **paired** A/Bs — same seeds ON/OFF, vocello + agy, N=6–10; single-take is
noise here, as §I already warned):
- **Voice Design *description* adherence is fine** — 4/4 distinct briefs (deep old male / bright
  young female / breathy whisper / persona-wizard) matched, clearly different voices. Not the bug.
- **Delivery adherence fails on high-arousal *positive* emotion.** `happy.strong` rendered
  flat/whispered **0/9** with the old evocative wording ("lighting up every word with bouncy,
  beaming enthusiasm"). A **concrete-acoustic rewrite** (explicit higher pitch + louder + faster
  lively pace + bright tone + "never flat or quiet") lifted it to **~70% (7/10)**, paired-beating
  the old wording on every seed (won 4 / lost 0 on the first set). Shipped (`41511aa`).
- **`excited.strong` left unchanged** — a parallel concrete rewrite *regressed* it (current wording
  already ~50%). High-arousal presets are wording- and model-sensitive: tune + rate-test **per
  preset**, never blanket-rewrite. (excited/surprised concrete-tuning = open follow-up.)
- **The English diction-reinforcement clause was ruled OUT** as the cause: paired A/B showed no
  consistent ON-vs-OFF effect on delivery adherence, and plain-English clarity was unchanged with
  it off (3/3 clean both). Kept (it's orthogonal to language detection — clarity, not selection).
- Residual ~30% high-arousal miss is model variance. Wording-only change → no RTF/QC impact.

### I.3 — agy retired for delivery decisions; objective DSP instrument + excited.strong fix (2026-06-14)

**The agy-as-ear judge is too unreliable to decide delivery on, and §I.2's agy-based rates are now
suspect.** Proven this pass: (a) agy flips its verdict on **byte-identical** audio (same WAV, same
seed → "energetic/yes" on one call, "calm/no" on another; generation is byte-deterministic, so this is
pure judge noise); (b) under a multi-vote batch (K=5 × 56 clips = 280 calls) agy mostly **stops
listening** — it returns "unclear / text-only / uncertain" on the majority of calls, flooring even a
**happy.strong positive control** at 0/8. So an agy "0%" can mean "the judge failed," not "the audio is
flat." Treat §I.2's "happy.strong 0→70%" and "excited ~50%" as soft — same instrument.

**Replacement instrument (committed): `scripts/analyze_delivery.py`** — reference-free, deterministic,
numpy-only. Measures the acoustics a delivery instruction targets directly from the WAV: median **F0**
(pitch) + p10/p90 range (intonation), **syllable rate** (energy-envelope peaks) + **duration**, and RMS.
RMS is **excluded from decisions** — the engine `PCM16StreamLimiter` normalizes level, so "louder"
barely moves RMS (a whisper take is not quieter in RMS); F0 + rate + duration are gain-independent.
Protocol: **paired neutral-vs-instructed deltas at the same seed** (generate a NEUTRAL take and an
INSTRUCTED take per seed; a real high-arousal effect = F0 up + rate up + duration down + wider F0 range
vs the same-seed neutral), compared across candidate wordings by **per-seed paired win-rate**. The
generation stayed serial (engine single-mutator); the agy fan-out is gone.

**Findings (objective, aiden, medium text; Speed 4-bit N=10 + Quality 8-bit N=8, paired):**
- **`excited.strong` rewritten** to a tight happy.strong-shaped concrete wording ("Noticeably higher
  pitch and louder…, fast driving animated pace, bright ringing energetic tone; strong rising emphasis;
  clearly thrilled and eager, never flat or quiet, without laughing or shouting"). It beats the old
  wording **8/10 seeds (Speed)** and **6/8 (Quality)** on arousal, with positive mean margins. The old
  `excited.strong` was actively poor — on Speed it rendered *calmer* than neutral (dF0 −4.4, slower,
  longer). Shipped.
- **`surprised.strong` kept as-is** — both rewrites regressed it on both variants (Quality: rewrites win
  1–2/8). The old wording carries the strongest pitch-jump (dF0 +20 Speed / +9 Quality), which is the
  surprise signature; rewrites flatten it.
- **Elaborate "concrete" rewrites regress** — a verbose judge-panel rewrite of both presets scored
  *negative* arousal on Quality (excited −1.44, surprised −2.16). Tight, happy.strong-shaped wording
  wins; verbose poetic wording loses. This is the real shape of §I.2's "a concrete rewrite regressed
  excited" — it is length/density, not concreteness, that hurts.
- Quality 8-bit follows high-arousal noticeably better than Speed 4-bit, but both respond; the agy run
  that suggested "Speed can't do it at all" was the judge failing, not the model.

Wording-only change → no RTF/QC impact. (8-bit CustomVoice model installed in the dev cache this pass.)

### I.4 — Voice Design "deep narrator → high pitch" tail quantified (2026-06-14; no lever)

Followed up the rare report that a "deep narrator" brief sometimes renders high-pitched, now measured
objectively by median F0 (`scripts/analyze_delivery.py`) — N=24 per brief × 3 briefs × both variants,
design mode. Briefs: gender-less "deep voiced narrator", "deep male narrator", and the shipped concrete
default ("A deep, low-pitched male narrator, warm and bass-resonant, with a subtle British accent").

- **Speed 4-bit: 0/72** high-pitch outliers. All briefs reliably deep (F0 medians 94–107 Hz; the
  gender-less brief 24/24 deep, max 137 Hz). The shipped concrete default is the deepest (94 Hz).
- **Quality 8-bit: 1/72** clear outlier — the shipped (maximally-specified) brief at seed 16 rendered a
  high female-ish voice (F0 ~350 Hz vs the ~95–110 Hz target; the absolute is octave-inflated by the
  analyzer on a bright high voice, but it is unambiguously 2–3× the deep target). Plus 2 borderline
  tenor males (153, 160 Hz). So the clear "deep→high" tail is **~1.4%**, real but rare, Quality-side.
- **No talker-temp lever.** The lever was gated on a >10% tail; the measured rate is ~1.4%. A 1.4% tail
  can't be A/B-tuned without N≈200+ per arm, and lowering the Voice Design talker temperature (0.9)
  directly costs the per-call voice *diversity* that design mode exists for. The outlier hit the
  most-specified brief, so it is a rare model sampling lapse, not a wording gap — the strengthened
  defaults (`d043ae3`) are validated as deepest/most-robust but cannot eliminate the ~1% tail.

Caveat: the autocorrelation F0 can octave-double on very high/bright voices (the 350 Hz reading), but
the deep-vs-not-deep classification is robust (the threshold is 2× away). No code change this pass.

### I.5 — CLI on-device ASR/WER spike: TCC blocks it (2026-06-14; deferred, reverted)

Spiked whether the `vocello` CLI could host an objective **text-adherence (WER)** instrument via
on-device `SFSpeechRecognizer` — the one adherence axis the DSP analyzers don't cover. Result:
**the API mechanism works, but macOS TCC blocks it for a headless tool**, so it stays deferred (P1.2),
now with the exact wall documented.

- ✅ A `type: tool` (no app bundle) **can carry the usage string**: `GENERATE_INFOPLIST_FILE` +
  `CREATE_INFOPLIST_SECTION_IN_BINARY` + `INFOPLIST_KEY_NSSpeechRecognitionUsageDescription` embed an
  Info.plist into the Mach-O `__TEXT,__info_plist` section (verified via `launchctl plist <binary>`).
- ❌ **`SFSpeechRecognizer.requestAuthorization` hangs in a headless/non-interactive run** — the CLI is
  `notDetermined` and waits on a TCC consent prompt that has no GUI session to display, so it never
  returns (killed at 45 s; no grant created before or after). The app (`com.qwenvoice.app`) holds a
  Speech grant; the CLI (`com.qwenvoice.cli`) is a separate TCC client and gets none.
- ⚠️ Even granted interactively (from a real Terminal), the CLI's **ad-hoc signature** churns the
  binary identity every `build.sh cli`, invalidating the grant each rebuild (the same TCC-identity pain
  the app's stable dev-signing fixed).

So WER-as-a-**macOS CLI headless gate** is not viable — which defeats that CLI's deterministic-driver purpose; a
`transcribe` command that hangs in a bench run is a footgun. The spike code (a `transcribe` subcommand +
the Info.plist build settings) was **reverted**. If revisited, the unblock options are: (a) a stably
**Developer-ID-signed** CLI + a one-time interactive grant, (b) a **TCC-free local ASR** (e.g. a
vendored whisper.cpp — but that fights the no-extra-deps/no-Python ethos), or (c) running transcription
in the app's already-granted process. The current physical-iPhone language lane implements (c): it
uses a predeclared fixed seed, exact persisted WAV, and three-pass locale-locked on-device Speech
consensus. The macOS CLI lane remains hint-only; no workflow falls back to subjective listening as a
required gate.

## J — macOS UI-benchmark observer effect and true -O capability (2026-07-23)

The phase-7 characterization program traced the apparent post-cutover macOS UI RTF decline
(canonical 1.04 → 0.88 → 0.70–0.93 across 2026-07-16→22) to a benchmark **observer effect**, not
engine or pipeline code:

- **Engine A/B across the Phase-4 cutover is flat.** Interleaved CLI benches at `9a8da874`,
  `610125b7`, and HEAD (identical `-Onone` dev builds) measured custom/long warm RTF 1.11–1.16
  in every arm; environment, backpressure (zero lossless-channel producer suspensions), thread
  priorities, actor-hop counts, executor placement, app UI animation, live-preview playback, and
  iPhone Mirroring were each individually falsified as causes.
- **XCUITest's default automatic screen recording was the load.** `VTEncoderXPCService` spawns one
  second after `testmanagerd` and, with `replayd`, video-encodes the display for the whole run
  (confirmed by `powermetrics --samplers tasks` mid-take and a Metal System Trace showing the
  compositor's GPU stream). Setting `preferredScreenCaptureFormat: screenshots` on the UI schemes
  (project.yml, both platforms) moved the same one-cell lane from warm RTF 0.70–0.78 to **1.196**
  (+55%) with clean QC. Run-to-run bimodality (0.70 vs 0.93 lanes) tracked recording-session
  variability, not code.
- **True engine capability at product optimization was never previously measured.** All historical
  CLI benches used the `-Onone` dev build; all `-O` measurements went through the recorded UI
  lane. A one-off `-O` CLI build measured custom/long warm RTF **1.81** (interactive process;
  0.97 when forced to `taskpolicy -c background`) — consistent with the iPhone 17 Pro's in-process
  1.70–1.91. The remaining UI-context gap (≈1.2 vs ≈1.8) is the honest app/XPC-topology cost and
  is the phase-7 optimization target.
- Per-generation `processTaskRole` / `processMainThreadQOS` / `processNice` self-reporting now
  lands in telemetry notes so process-class demotion can never hide in future records.
- **Registry caveat:** macOS/iOS UI-generation records published before 2026-07-23 carry the
  screen-recording overhead in every cell and are not comparable with post-change UI records
  (their `harnessHash`/`projectInputHash` differ, so the registry never links them as baselines).

## K — Honest topology-gap attribution: compositing, not XPC (2026-07-23)

With recording disabled (§J), the remaining ≈25% UI-context gap was attributed by controlled
one-cell lanes (custom/long warm, identical `-O` engine code, same session):

| Configuration | warm RTF | stepEval |
| --- | --- | --- |
| CLI, in-process | 1.84 | 8.6 s |
| XPC service, app hidden during takes (⌘H diagnostic) | 1.77–1.80 | 8.3–8.6 s |
| XPC service, app visible (canonical) | 1.37 | 12.7 s |

- **The XPC/actor topology costs ≈3%.** With the window not composited, the service matches the
  in-process CLI within noise — forwarding, per-token events, and process class are all cheap.
- **Visible-window compositing during generation costs ≈23%.** Paired Metal System Traces show
  the mechanism: WindowServer contributes ~43% of GPU channel activity (226K compositing events
  in 26 s vs 1.5K in the CLI context), and the service's command buffers pay **+48% median
  CPU→GPU queueing delay** (4.72 ms vs 3.18 ms; p90 +80%) while per-buffer execution time is
  identical. An idle app window is free (CLI bench with the app open idle: 1.86); only the
  *generating-state* window redraw load matters. Individually exonerated by controlled runs:
  live-preview playback (autoplay off: no change), the readiness spinner (static glyph: no
  change), the standalone activity spinner (both presentations equally slow), recording (§J),
  iPhone Mirroring, thermal, and the test runner's CPU.
- The per-generation silence windows between takes downclock the GPU to Minimum (idle DVFS, not
  thermal) — expected inter-take behavior, excluded from the in-take attribution.
- Diagnostic lever kept in the harness: `QVOICE_MAC_BENCH_HIDE_DURING_TAKE=1` hides the app via
  the genuine ⌘H action for each take and reactivates it before the visible completion asserts.
- **Gate v1 measured neutral; the redraw source is display-refresh-locked.** Becalming every
  named surface (static glyphs for the readiness, starting, and activity indicators; live
  playhead 10 Hz → 3 Hz) left RTF at 1.37 and WindowServer's share unchanged (~42%, 183K
  events). The trace fingerprint: WindowServer composites a steady **60.1 buffers/s comb**
  (median inter-frame 16.61 ms; no chunk/playhead/polling clusters) while the Vocello app
  process submits **zero** Metal work of its own. Cursor-parking
  (`QVOICE_MAC_BENCH_PARK_CURSOR=1`, CGEvent pointer move to the screen corner mid-take) also
  measured neutral (1.374), falsifying the hover-effect hypothesis. The kept gate-v1 changes
  stand on energy/composition grounds despite the neutral RTF result.
- **Resolved: Liquid Glass is the entire visible-window cost.** A diagnostic build with the
  `QW_UI_LIQUID` compilation condition removed (the app's shipped solid-fill fallback design,
  normally reached via Reduce Transparency) measured **1.775 cold / 1.842 warm with the app
  fully visible** — complete recovery to the engine's 1.84 capability, zero residual. The glass
  material's continuous compositor-side work (the 60 Hz comb) competes with MLX for the shared
  GPU on the 8 GB tier whenever the window is visible; this also explains why UI-context records
  trailed same-day engine capability in every era of the registry. The shipping configuration
  keeps `QW_UI_LIQUID`; the product decision (generation-time glass gate via the existing
  solid-fill fallback, a floor-tier default, or accepting 1.37-with-glass) is recorded as the
  phase 7 implementation choice.
- **Implemented (maintainer-endorsed): the generation performance gate.** A
  `generationPerformanceGate` SwiftUI environment value, injected at the window root from
  `TTSEngineStore.hasActiveGeneration`, folds into every glass-choosing branch (the four
  AppTheme styles plus the eight direct `glassEffect` sites) exactly like Reduce Transparency:
  while a generation runs, surfaces render the existing solid-fill design; glass returns at
  idle. Acceptance: one-cell custom/long warm **1.833** (vs 1.37 pre-gate, 1.842 no-glass
  diagnostic ceiling), and a full dirty-tree matrix at custom warm 1.67/1.80/1.84, design
  1.79/1.88/1.94, clone 1.43/1.70/1.86 with clean QC and the deterministic suite green. The
  UI context now delivers engine capability on the 8 GB floor tier.
- **iOS checked: no gate needed.** A headless on-device capability take
  (`ios-engine-20260723-121520-45ee4ab3`, cold, default text) measured RTF 1.585, while the
  recording-free UI canonical already runs 1.81 cold / 1.86–2.03 warm with full glass visible —
  the iPhone shows no UI-context penalty to close. Consistent with display architecture: the
  phone's adaptive-refresh panel idles for static content, so visible glass composites at
  ~nothing while the engine runs; the Mac's fixed-refresh external display composited every
  frame. That reasoning covers ProMotion panels only: the supported-hardware gate
  (iPhone 15 Pro+ via `iPhone16,1/16,2` or major ≥ 17) also admits the fixed-60 Hz
  iPhone 16, 16 Plus, and 16e, where adaptive idling does not apply. The iOS
  `iosGenerationPerformanceGate` environment (2026-07-23) therefore renders the four glass
  containers with their shipped solid-fill fallback during generation on fixed-refresh
  displays only — inert on every ProMotion device including all measured evidence hardware,
  defensive on the 60 Hz tier, and unmeasured there until a 60 Hz device is available. (Operator note: the headless bench spec's third segment is the literal text —
  `custom:speed:` uses the default sentence; `custom:speed:long` speaks the word "long" and
  fails with zero emitted frames.)

## L — Roadmap Stage 0 measurements (2026-07-26)

Stage 0 of the adopted optimization roadmap
(`docs/reference/optimization-report-review-2026-07-25.md`) landed as four commits with the
following measured outcomes on the canonical Mac mini M2 8 GB:

- **Clone reference trailing-silence append (`b16167d`).** ICL references now carry 0.5 s of
  appended silence into codec encode; the persisted-artifact conditioning version moved to
  `qwen-speaker-mel-v1+icl-ref-silence500ms-v2`. Live checks: same-seed takes byte-identical
  on the new build; before/after WAVs differ at both probe seeds (conditioning genuinely
  changed); the saved-voice artifact migrated fail-closed (old version rejected at adopt,
  rebuilt, re-persisted) with no user-visible error.
- **Clone/long intermittent dropout band (pre-existing).** One unseeded bench take hard-failed
  Fast QC (`dropout:1337ms`) on the changed tree. Twelve fixed seeds (1001–1012, bench long
  text) then passed 12/12 on **both** the pre-change build (`22e99d1`) and the changed build —
  the band is low-rate, random-seed, and predates the silence append; engine Fast QC already
  rejects such takes at generation time. Treat future single hard-fails on unseeded clone/long
  runs as this band unless a fixed-seed soak reproduces them.
- **Repetition-penalty A/B (`f97598a`).** New gated `QWENVOICE_TALKER_REPPEN` knob (talker
  only). Same 12 seeds at 1.05 vs 1.10: both arms 12/12 QC pass; interior near-silence proxy
  (50 ms RMS windows < −45 dBFS, interior only) mean 504 ms → 547 ms and over-400 ms count
  8 → 9 at 1.10. No deterministic-QC win → the official 1.05 default ships unchanged.
- **Long-form boundary advisory (`5fc0f3c`).** The assembler's `maximumSegmentBoundaryJump`
  now records a warn-first `boundary_jump:<value>` advisory above 4 096 PCM16 units; no run
  fails on it. Distribution data accumulates in manifests for a future hard threshold.
- **Post-change clone matrix record.** The full clone Speed bench (3 lengths × warm 4, label
  `stage0-clone-silence-bench`) passed 15/15 with clean QC on the silence-append runtime and
  published `macos-engine-20260726-054111-e95e1285` — the comparison record for post-change
  clone RTF against the `release-QA-2.2.0` band.

## M — Stage 1 launch-bound program (2026-07-26, in progress)

Successor to the §H P0 re-capture, executing the staged roadmap's Stage 1 on the current pins.
All measurements are -Onone CLI bench cells on the canonical Mac mini M2 8 GB; every step is
gated on fixed-seed byte-identity (scheduling-only changes must not move a single sample) plus
the §K 12-seed clone/long QC soak.

- **P2a-i — pipelined chunk materialization (landed, `549b884`).** The token loop's shipping
  eval policy became `.pipelined`: the step graph is submitted with `asyncEval` and the
  previous stream chunk's materialization + channel sends run before the token/EOS reads,
  overlapping in-flight GPU compute with identical channel event order. Identity: 12/12
  byte-identical WAVs vs the synchronous build; soak 12/12 clean. Records
  `macos-engine-20260726-054111-e95e1285` (base) → `…-055949-8e3c8639` (pipelined): clone
  warm short/medium/long **+1.6 / +3.3 / +0.5%** RTF. `.full` remains the synchronous
  attribution diagnostic.
- **P2a-ii — early talker submit (measured do-NOT, `7f01927`).** Submitting the
  talker+sampling subgraph before the 15-pass code-predictor graph build (to overlap build
  with compute) regressed warm RTF — custom/long **−3.9%**, clone/long −2.0% vs P2a-i
  (record `…-060659-99b59f93`). The second command buffer plus the fusion break at the early
  materialization boundary cost more launches than the overlap recovered. Reverted; a code
  comment marks the do-NOT at the site.
- **P3 — compiled code-predictor pass (landed 2026-07-26).** The streaming loop replays 15
  per-pass-index compiled functions (`CodePredictorCompiledPlan`, per generation) instead of
  rebuilding ~15 op graphs on the host every frame. Two design constraints drove the shape:
  the fused-RoPE `offset` is a trace-time constant while passes 1–14 share shapes (so
  functions are keyed by pass index, never by shape), and `KVCacheSimple` advances host
  state inside `update` (so the plan owns explicit K/V buffers with slices baked per pass;
  the per-frame position replay makes them exact). **Result: +8.3% to +10.6% warm RTF on
  every cell** (records `…-055949-8e3c8639` → `…-063621-2378350e`; clone/long 1.128 → 1.243,
  custom/medium warm 1.103 → 1.220). Numerics: MLX compile's fusion reorders fp32 rounding
  by ~1e-7 (unit test pins the tolerance), which sits below bf16 resolution — the shipping
  model is **byte-identical** end-to-end (12/12 identity + 12/12 QC soak). The eager path
  remains for the non-streaming loop and as the equivalence-test reference.
- **P5b — codec decode on a dedicated stream (measured do-NOT).** Building the chunk-decode
  graph under `Stream.withNewDefaultStream` regressed warm RTF on **every** cell (−0.4% to
  −4.3% vs P3; record `…-070148-150cc5e8`, byte-identity still held). Same physics as
  P2a-ii: on this launch-bound loop, an extra command queue plus cross-stream event sync
  costs more than overlapping a ~5 ms/chunk decode buys. Reverted; comment marks the site.
  The emerging Stage 1 law: **wins come from removing host graph-build work (P3) and from
  filling host-side gaps with already-queued work (P2a-i); anything that adds command
  buffers or splits the fused step loses.**
- **P1b — static-shape compiled talker decode (branch experiment, null result).** On
  `feat/p1b-static-talker-compile` (delta `DECODE-002`, diagnostic): a per-capacity-block
  compiled talker step — static per-layer K/V buffers, `putAlong` writes with the position as
  an input array, in-trace validity mask, cos/sin rotary inputs (the talker's MRoPE made a
  single trace per 256-block possible, unlike the CP's offset-baked RoPE). **Correct** — a
  258-step eager-equivalence test passes including the block re-trace, and the bf16 model is
  byte-identical at fixed seed — but **flat**: decode-wall RTF ±1% on medium/long and −2% on
  custom/short vs P3. The ~9%-of-wall talker graph-build savings cancel against the
  padded-attention compute/bandwidth tax. Not landed (pre-registered keep-gate was +≥10%);
  the branch is preserved for the sanctioned 0.31.x pin-bump re-test, where lower launch
  overhead may shift the balance.
- **Stage 1 closed 2026-07-26.** Net landed effect: clone/long 1.122 → 1.243 (+10.8%),
  custom/medium warm 1.220, all byte-identical. Ledger: P2a-i and P3 landed; P2a-ii, P5b,
  and P1b measured and declined. The loop remains launch-bound (~49% GPU busy) with the
  residual idle concentrated in the fused step eval's batch-1 launch gaps — a structural
  ceiling at the 0.30.6 pins; the sanctioned re-test rides the Stage 4 pin bump. The program
  proceeds to Stage 2 (memory).
- **Stage-exit GPU-busy re-capture (2026-07-26, post-P3).** Same §H P0 command
  (Metal System Trace over `bench custom/speed/long --warm 2`; ~25% trace overhead;
  fractions are the deliverable; whole-trace span including the cold gen, 856 frames):
  Step Eval Flush **72.8% of wall at 59.8% busy** (was 58.9% at ~55%), Code Predictor Loop
  **9.7% of wall** (was 15.4%) at 14.7% busy, Talker Forward 9.2% at 15.1%, whole-span GPU
  busy **49.4%** (was ~47% warm-only). **Verdict: still launch-bound** (≪85%) — the loop is
  now dominated by the fused step eval whose internal idle is the batch-1 launch-gap ceiling
  §H P0 identified as addressable only by compiling the talker step. That makes **P1b (the
  branch-only static-shape talker compile) the sanctioned next lever**, with P3's per-pass
  keying pattern as the template. Raw trace summarized and discarded per policy.

## N — Stage 2 memory program (2026-07-26)

- **2.1 Speech-tokenizer residency (landed; phase 9 closed).** macOS model switches adopt
  the previous model's byte-identical 682 MB tokenizer object on content-identity match
  (host-attested trust digests; hard-link inode fallback; encoder-superset rule). Evidence:
  fixed-seed switch A/B byte-identical with residency on/off; adoption drops
  `speech_tokenizer_load` 503 → 0 ms with ~260 ms better cold first-chunk latency after a
  switch; retained-memory qualification PASS on the 8 GB floor
  (`mac-memory-qualification-20260726-115343-5a1c8a85`). Registered off-switch:
  `QWENVOICE_TOKENIZER_RESIDENCY`. Local-install note: this dev machine's six models predate
  the shared-store migration (nlink=1 copies), which is why the trust-digest identity — not
  the inode path — carries the hit here.
- **2.2 Text-embedding 8-bit quantization (experiment validated; productization pending).**
  Isolated APFS-cloned data dir; the CustomVoice-4bit talker's 622.3 MB BF16
  `model.text_embedding` converted to affine 8-bit group-64 (packed 311 MB + 19 MB
  scales/biases) with the per-layer entry nested in the config `quantization` dict — the
  loader's existing `perLayerQuantization` path constructed the QuantizedEmbedding with no
  code changes. Measured on the 8 GB floor: **MLX active peak 2105.9 → 1827.7 MB
  (−278 MB, −13.2%)**, disk 1625 → 1334 MB (−292 MB per Speed artifact), warm RTF parity
  (1.161–1.169 vs 1.159–1.170), 6/6 fixed-seed takes clean EOS with plausible parallel
  durations. Fixed-seed output changes (quantization is numerics-affecting), so shipping is
  a promotion-quality artifact decision: new HF artifact uploads, catalog re-pins,
  full fail-closed delivery workflow, and fresh fixture identities — maintainer call.
- **Promotion decision battery (2026-07-26, four-arm + fp16 probe).** Bench-grade custom
  matrices (13 fixed-seed takes per arm, seed 19790615, all QC-clean, median warm
  decode-wall RTF on the M2 8 GB floor):

  | cell | control | 2.2 q8-embed | 2.3 bf16-codec | 2.3 fp16-codec | combined |
  |---|---|---|---|---|---|
  | short warm | 1.145 | 1.109 | 1.111 | 1.116 | 1.073 |
  | medium warm | 1.237 | 1.223 | 1.174 | 1.186 | 1.174 |
  | long warm | 1.262 | 1.252 | 1.203 | 1.210 | 1.203 |
  | MLX active peak MB | 2105 | **1827** | 1872 | 1872 | **1593** |

  **Verdicts:** 2.2 costs ≤1% on medium/long (−3% on the noisy 1.7 s short cell ≈ 40 ms
  absolute) for −278 MB — promote. 2.3's ~4–5% regression is real and dtype-independent
  (fp16 reproduces it at QC-clean 13/13), so it is not an M2 bf16-emulation artifact but
  half-precision conv throughput in this size class — parked, with two revival paths: the
  Stage-4 0.31.x pin-bump re-test, and an iPhone 17 Pro device measurement (A19-class
  half-precision conv throughput may show parity, which would motivate a per-platform
  artifact split only if the device data justifies it). The retained clone-prompt
  tensors total under ~100 KB (refCodes ≤ 16 codebooks × 750 frames × int32 ≈ 48 KB plus an
  8 KB x-vector), and `refCodes` is consumed by **every** clone generation — the ICL prefix
  interleaves the target text, so no request-independent "conditioning prefix" exists to
  retain instead. The report's M5b premise mischaracterized the retention cost; the iPhone
  clone peak band is weights + KV + codec activations. Nothing to reclaim; no change made.
- **2.3 Codec bf16 (experiment validated with a perf caveat; productization pending).**
  Same isolated methodology: all 492 speech-tokenizer tensors cast fp32 → bf16 except the
  final two decoder layers (`decoder.decoder.5` output snake, `.6` output conv, per T-Mimi).
  Measured: shared component 682 → **341 MB on disk**, MLX active peak 2105.9 →
  **1872 MB (−234 MB)**; 3/3 fixed-seed takes clean EOS with durations *identical* to the
  fp32-codec baseline at every seed (the untouched talker produces the same token
  sequences — only the decoded waveform changes in low bits). Caveat: CLI warm RTF read
  ~2–4% lower (1.119–1.137 vs 1.159–1.167) — needs bench-grade confirmation before
  promotion. Combined with 2.2, the two validated conversions total **−512 MB resident /
  −633 MB installed** per Speed artifact chain at experiment grade; both are
  numerics-affecting artifact decisions (new HF uploads, catalog re-pins, fresh fixture
  identities, ASR/prosody promotion gates) awaiting the maintainer.
- **2.2 promotion executed (2026-07-26, maintainer-approved).** After the four-arm battery,
  the adopted call was: promote 2.2 alone; park 2.3 (dtype-independent conv regression, two
  revival paths above). All six production artifacts (Speed + Quality × CustomVoice /
  VoiceDesign / Base) were converted with the pinned deterministic tooling
  (`scripts/convert_text_embedding_8bit.py`, python-mlx 0.32.0; output byte-matches the
  validated experiment arm) and uploaded to six new public `PowerBeef02/<folder>` Hugging
  Face repos with Apache-2.0 attribution to the exact `mlx-community` source revisions.
  The contract, iOS catalog, and Quality receipts were re-pinned to the uploaded revisions
  as artifactVersion **2026.07.26.1** (Speed talker 1625 → 1333/1357 MB on disk;
  8-bit 2417 → 2102/2126 MB), the production catalog regenerated, and
  `model_catalog_contract.py validate --require-complete` passed; pinned
  `model.safetensors` URLs were spot-verified live with exact byte counts. Fresh fixture
  identities, delivery proof, and memory re-qualification ride the release-QA battery.

## O — Gate 0: MPP TensorOps `matmul2d` vs MLX on the M2 floor (2026-08-01)

The pre-registered go/no-go from the Metal 4 feasibility study
(`docs/reference/metal4-tensor-feasibility-2026-07-31.md`, roadmap 1.1): can
MetalPerformancePrimitives `matmul2d` reach parity with MLX's kernels at the engine's real
batch-1 GEMM shapes on the canonical Mac mini M2 8 GB floor? **Verdict: no-go.** MPP never
exceeds parity; where it ties, launch overhead is doing the tying. Per the
pre-registration this closes Candidates A/B (fused MPP-based kernels) until Apple's
portable fallback improves or the canonical floor changes, and removes the conditional
Gate 2 prototype from the 2026-08 roadmap's Tier 3.

- **Probe.** Standalone untracked SwiftPM executable (session scratch), path-dependent on
  the pinned mlx-swift 0.30.6 checkout; macOS 26.5, Xcode 26 SDK, runtime
  `device.makeLibrary(source:)` MSL with `#include <metal_tensor>` +
  `#include <MetalPerformancePrimitives/MetalPerformancePrimitives.h>`, classic
  `MTLComputePipelineState`/`MTLComputeCommandEncoder`, `tensor_inline` over plain device
  pointers — exactly the dispatch shape `MLXFast.metalKernel` produces. fp16, the seven
  batch-1 GEMM shapes from the loaded CustomVoice-4bit config (talker attn-out/MLP/head,
  code-predictor MLP/head). Metrics: median wall µs for a single dispatched GEMM (launch
  included — what the launch-bound engine pays per op) and per-GEMM time with 100
  dispatches in one command buffer (amortized — kernel execution cost, what an MPP matmul
  would cost as a building block inside a fused kernel). In-kernel results verified
  against a CPU reference; MLX arm evaluated per iteration (single) and as 100
  distinct-input matmuls per eval (amortized, CSE-defeated).
- **Structural finding 1 — batch-1 is inexpressible at parallel scope.** MPP
  `matmul2d_descriptor` statically requires `M % 8 == 0` (or 16) under
  `execution_simdgroups`; `static_assert` fires at pipeline creation for M=1. A batch-1
  decode row therefore runs either padded to M=8 (7 of 8 rows wasted) or serially under
  `execution_thread`. Three variants measured: `m8t` (M=8 padded, 32-column tile per
  threadgroup — the strongest reasonable configuration), `m8` (M=8 padded, single
  threadgroup), `t1` (M=1, `execution_thread`).
- **Structural finding 2 — silent wrong results, no error.** The single-threadgroup `m8`
  variant at 8×1024 (K=3072) reproducibly wrote zeros for the upper half of the output
  (n ≥ 512) with no API or validation error, twice, while the same kernel text verified
  clean at six other shapes. Tiling to 32-column threadgroups cleared it. A cooperative
  API that silently drops half the output at some descriptor aspect ratios is itself
  disqualifying evidence for shipping on this SDK without exhaustive per-shape
  verification.
- **Numbers (median µs per GEMM; M2 8 GB floor).**

  | shape (K×N) | m8t 1× | mlx 1× | m8t amort | mlx amort | mlx edge (amort) |
  |---|---|---|---|---|---|
  | talker attn out 2048×2048 | 283.9 | 301.2 | 76.0 | 62.0 | 1.23× |
  | talker mlp up 2048×6144 | 497.9 | 504.7 | 277.8 | 269.6 | 1.03× |
  | talker mlp down 6144×2048 | 488.9 | 478.4 | 267.8 | 228.6 | 1.17× |
  | talker head 2048×3072 | 356.8 | 360.1 | 135.7 | 107.6 | 1.26× |
  | cp mlp up 1024×3072 | 248.7 | 262.9 | 55.6 | 46.3 | 1.20× |
  | cp mlp down 3072×1024 | 250.9 | 247.6 | 55.5 | 43.7 | 1.27× |
  | cp head 1024×2048 | 230.1 | 277.7 | 40.2 | 26.3 | 1.53× |

  The naive variants are not competitive: single-threadgroup `m8` runs 0.8–17.4 ms and
  serial `t1` 9.6–67 ms per GEMM. Single-dispatch parity (±10%) across every shape shows
  both stacks pay the same ~250 µs launch/commit/wait cost — consistent with §H P0/§M:
  the engine's bound is launches, not kernels, and a per-op MPP swap has nothing to win.
  Amortized, MLX's tuned split-k GEMV beats the best MPP configuration on all seven
  shapes (geomean ≈ 1.24×). Notably the 8× M-padding is nearly free — these GEMV-like
  shapes are weight-bandwidth-bound, so the padded rows ride along — yet MPP's portable
  fallback still loses. This matches MLX upstream's own routing decision: MPP kernels are
  gated to M5/A19-class hardware (NAX), and hand-tuned steel kernels serve everything
  below. On floor hardware there is no MPP building-block advantage for a fused kernel to
  inherit; launch elimination remains P1b (static-shape compile) territory inside MLX
  itself.

## P — Delivery-fidelity and clone-fidelity diagnosis (2026-08-01)

Full findings and method: `docs/reference/delivery-fidelity-report-2026-08-01.md`.
Headlines from the autonomous harness (7-seed × 18-cell paired preset matrix
banked as `delivery-cal-s*` records; three 8-seed neutral cohorts; 6-take clone
lane with negative controls):

- Presets steer prosody with preset/intensity-dependent reliability: angry
  (pitch +1.00 win-rate), sad/happy/fearful/whisper strong; **dramatic and
  surprised barely move prosody** (0.64) and are the product-side fix
  candidates. Two seeded gate assumptions were corrected by data (angry raises
  pitch; fearful reads low-arousal) and the promoted delivery gate is now
  calibrated from the banked distributions.
- **Neutral cross-seed wander is real and by-construction** (no instruct turn
  is sent): 2.70 st pitch / 1.97 Hz rate spread across 8 seeds at shipping
  defaults; `consistent` variation does not help across seeds (3.99 st) and an
  explicit steadying instruction helps pitch (~21%) but not rate. Engine-level
  stabilization would be its own experiment.
- Reproducible defect pinned: seed 20260802 × `sad.strong` × medium corpus
  fails Fast QC with `dropout:excess2`, identically on repeat.
- **Clone identity is strong**: ECAPA 0.814–0.871 vs 0.103/0.390 negative
  controls; 5/6 takes prosody-fidelity clean (one expressiveness overshoot);
  5/6 match the reference's SER emotion. The clone-tone complaint is
  occasional expressiveness drift, not identity loss.
- Advisory SER column pinned (Apache-2.0, revision-locked, fail-closed
  loading after the first candidate checkpoint proved to initialize a random
  classifier head); peak RSS 2.4 GB inside the 8 GB envelope, sequential-only.

## Q — Sanctioned pin bump: mlx-swift 0.31.6 + mlx-swift-lm 3.31.4 (2026-08-01)

The roadmap Tier-3.1 experiment on `chore/pin-bump-mlx-0.31.6`. mlx-swift-lm's
2→3 major externalized the Hub/Tokenizers implementations (swift-transformers
left its graph), so the runtime now pins swift-transformers 1.1.9 — the exact
version the 2.30.6 graph resolved — directly, keeping tokenization
byte-comparable across the A/B; `Tokenizer`/`TokenizerError` are re-pinned to
the Tokenizers module by module-scope typealiases against MLXLMCommon 3.x's
new same-named protocols. mlx-swift 0.31.x's CudaBuild build-tool plugin
cannot receive interactive fingerprint approval headlessly; `xcb_run` now
passes `-skipPackagePluginValidation` unconditionally (justification in
`scripts/lib/build_cache.sh` — exact-version pins and lockstep-checked
resolved files carry supply-chain identity; the plugin is inert on Darwin).
F7 was **not** triggered: 0.31.6 vendors mlx core 0.31.1 (< 0.32), so the
macOS/iOS 26.0 floors stand.

- **Keep verdict: PASS (same-day A/B at seed 19790615, canonical M2 floor).**
  58-take full matrix under new pins vs a 20-take 0.30.6 control rebuilt the
  same afternoon: warm RTF deltas +0.6…+2.0% (noise band); QC verdict
  distributions identical — including the deterministic `design/speed/long`
  warn (dropout + near_silent, all three reps, both pin sets: a property of
  that prompt × seed, not a regression); clone audio durations byte-equal
  across pins (identical token counts ⇒ the request-local sampling path is
  behaviorally stable). The earlier ±20–46% swings vs
  `benchmarks/baselines/full-matrix-speed.json` were staleness of that
  baseline, not the pins. Control run published as clean-source 0.30.6 record
  `macos-engine-20260801-155513-991ccaf6` (exploratory: stash-dirty tree).
- **2.3 codec-bf16 revival probe: negative, with a mechanism correction.** A
  scratch conv-stack probe at the codec decoder's exact geometry (initial
  1024→1536 k7, convT [8,5,4,3] k=2r, k7 residuals, final →1; batch 1;
  L0 ∈ {7, 13, 63}) measured fp32/f16/bf16 under both pins with era-matched
  metallibs: half-precision conv is *faster* than fp32 on **both** 0.30.6 and
  0.31.6 (f16 −14…−26%, bf16 −4…−17%), and the two pins are within ~1% of
  each other. The pin bump changes nothing at the conv level, and §N 2.3's
  "half-precision conv throughput" attribution does not reproduce in
  isolation — if 2.3 is ever revived, the ~4–5% end-to-end regression must be
  sought elsewhere in the bf16 decode path (dtype boundaries, snake
  activations, or the decoder transformer). 2.3 stays parked; the remaining
  revival path is the iPhone 17 Pro device measurement.
- **P1b re-test (DECODE-002): confirmed null on 0.31.6 by a paired soak;
  do-NOT stands (maintainer-ratified 2026-08-01).** The preserved
  `feat/p1b-static-talker-compile` experiment cherry-picked onto the new pins:
  the 258-step eager-equivalence test passes unchanged. An initial cross-run
  read of −0.5…−2.1% prompted a §K-style paired soak (seeds 1001–1006 of the
  planned 1001–1012, maintainer-stopped early once the answer was clear;
  custom/speed medium+long, warm reps 1–2, per-seed build-order alternation,
  both builds from the same pin tree): **P1b is +0.74% slower on medium
  (95% CI [−0.41, +1.88], slower on 6/6 seeds) and +0.16% on long
  (CI [−0.17, +0.49], 4/6)** — the apparent gain was cross-run noise; paired
  same-seed measurement resolves to flat-to-negative. QC 84/84 pass across
  both builds. The per-generation trace-build cost still cancels the
  graph-build savings, exactly as on 0.30.6. Reverted from the pin-bump
  branch; the P1b branch stays preserved for a future pin generation. Soak
  CSV is session-scratch; its bench runs and the earlier P1b-build run
  (`macos-engine-20260801-161901`) were removed from the registry because
  their source states are the reverted experiment.

## Status

The optimization program tracked in this document is wrapped up. The §H P0–P6 work has been
completed and validated, streaming is now the default generation path, and the remaining
delivery-accuracy work is recorded in §I. For UI smoothness (G), compare the typed heartbeat and
playback metrics in compatible records indexed by generated `HISTORY.md`; the former
`uiMaxStall ms` column remains historical context in `LEGACY_HISTORY.md`. The §J observer-effect
correction (2026-07-23) re-baselines UI-lane expectations; §K attributes the residual UI-context
gap to generating-state window compositing (XPC ≈3%); §H P0's GPU-busy re-measurement was
completed 2026-07-24 on the shipping runtime (whole-generation GPU busy 31–37% → ~47%,
eval-flush window → ~55%; structure unchanged, launch/CPU-bound).
