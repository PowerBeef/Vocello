---
status: historical
owner: backend-and-platform
summary: Cross-check of the convergence roadmap against official Qwen3-TTS and Apple Metal/MLX guidance (reviewed 2026-07-19, position syncs through 2026-07-25). Point-in-time review; item status lives in config/roadmap.json.
contentDigest: sha256:33fd92b0ce213fac47c016f74d96fd80f444c09ca51f3247b270dd356bc8b5fa
---
# Qwen3-TTS, Apple Silicon, and Vocello roadmap review

> Cross-check of Vocello’s convergence roadmap against official Qwen3-TTS docs and
> Apple Metal/MLX guidance. Protects the low-RAM + streaming-preview “secret sauce”
> that makes the product feel fast on 8 GB Mac and physical iPhone.
>
> Reviewed 2026-07-19; position sync 2026-07-20 after `overallPromotion: passed`; roadmap
> sync 2026-07-25 after the launch-bound optimization report counter-verification
> ([`optimization-report-review-2026-07-25.md`](optimization-report-review-2026-07-25.md)).
> Code and machine-readable contracts win over this prose.

## Secret sauce (do not trade for roadmap convenience)

| Ingredient | Why it feels fast | Where it lives |
| --- | --- | --- |
| Constrained first/later codec frames (7 / 7\|14) | Early audible PCM without waiting for full decode | Generation semantics / classified session |
| Separate preview router vs lossless channel | UI hears progress without dropping final audio under backpressure | Frontend preview path + `GenerationOutputAdapter` |
| Request-local sampling + memory | No global RNG/cache thrash between takes | Sampling v2 / request-local memory config |
| Tiered `Memory.cacheLimit` + trim/unload | Stays inside 8 GB Mac / iPhone Pro budget | `NativeMemoryPolicyResolver` |
| macOS XPC engine isolation | UI process stays light while GPU work runs in service | `QwenVoiceEngineService` |
| 4-bit Speed on iOS / floor 8 GB Mac | Weight footprint fits unified memory | Production catalog + preferred variant |

Telemetry v9, long-form v4, and history v3 must not regress first-preview latency, peak
footprint, or trim/unload safety. Fail closed on `hardTrim` / `fullUnload` for the secret-sauce
characterization cells in `config/characterization-fixtures.json`.

## Official Qwen3-TTS vs Vocello

### Alignments

Three modes (Custom / Design / Clone), 12 Hz tokenizer + 24 kHz PCM, product streaming on all
released models, instruction control on 1.7B Custom/Design only, and `x_vector_only` clone with
consent match the shipping contract. Vocello’s early-frame chunks + preview delivery are the
product analogue of Qwen’s dual-track low first-packet design—not a port of the Python CUDA demos.

### Semantic traps

1. **“Streaming” means different things.** Official docs still process complete text when
   `non_streaming_mode=False`; true character-by-character input is a future Qwen update.
   Published ~97 ms first-packet figures are NVIDIA A100 + FlashAttention-2, not Apple Silicon.
   Vocello’s win is on-device first-preview + lossless finalization, not CUDA parity.
2. **0.6B for latency/memory** is ruled out (no VoiceDesign; fragments the mode matrix). Keep that
   decision visible so Phase 5–7 work does not rediscover 0.6B as an easy win.
3. **Fine-tune / vLLM / DashScope** are out of product scope.
4. When Qwen ships true incremental text input, treat it as a new Phase 7/11 spike—not a silent
   change to complete-text streaming.

## Apple Metal + MLX vs Vocello

Unified-memory MLX, quantization for on-device size, request-local KV/cache policy, and reclaim via
cache limits + soft/hard trim / `fullUnload` align with Apple and MLX guidance. Keep:

- **No hard production `Memory.memoryLimit`** (soft relief is the product model).
- **MLX-only** during convergence (no Core ML / MPS Graph / custom Metal second path).
- **Pin lockstep** for `mlx-swift` + `mlx-swift-lm` through remaining convergence (Phases 7–14).
- Tighter cache-limit A/B only after Phase 5 packaging (closed 2026-07-20), evidence-gated.
- Quantized KV remains diagnostic (standing do-NOT). `compile()` stays diagnostic for the
  talker, but the 2026-07-25 review sanctions two gated re-tests: the code-predictor step is
  compile-stable today (per-frame cache reset → bounded 16-shape cycle), and a talker
  static-shape compile experiment is branch-only with recompile-free proof plus ≥10% warm RTF
  required — the prior −5% measurement was a different variant (quantized-param marshalling).

For “lightning fast” claims, prefer `playbackScheduled` / first-chunk materialization until a true
first-render player callback exists. Nested v9 may still mark some preview domains unavailable.

## Glossary

| Term | Meaning |
| --- | --- |
| Qwen dual-track streaming | Official hybrid path aimed at low first-packet latency on CUDA-class demos |
| Vocello product streaming / preview | Early codec-frame chunks + frontend preview router for perceived speed |
| Lossless final channel | Actor-owned classified session → `GenerationOutputAdapter` → atomic WAV + Fast QC |

## Pre-research baselines (2026-07-19)

Both platforms ran exploratory full 29-take UI matrices on a dirty worktree
(`passedWithWarnings`, soft trim). They are baselines for research, not clean promotion controls.

| Platform | Record | Notes |
| --- | --- | --- |
| macOS (Mac mini M2 8 GB) | `benchmarks/runs/ui-generation/macos-xcui-benchmark-20260719-215547-11f8f4cf.json` | Smoke + gate also passed after dSYM refresh |
| iPhone 17 Pro | `benchmarks/runs/ui-generation/ios-xcui-benchmark-20260719-224743-1e69da39.json` | Smoke passed; `ios_device.sh gate` later PASS (`ios-gate-20260719-191932`); headless Phase 5 seed pairs PASS |

## Recommendations (ordered)

1. ~~Phase 5 live fixed-seed pairs before v9 authority flip~~ closed 2026-07-19/20; packaging and
   sidecar authority landed with `overallPromotion: passed`.
2. ~~Secret-sauce latency/memory cells~~ captured 2026-07-19 and re-checked on post–Phase 0
   canonical matrices; keep `scripts/check_secret_sauce_cells.py` fail-closed for later Phase 7+.
3. Do not target A100 97 ms; use Vocello clean-control regression bounds.
4. Defer Metal 4 / Neural Accelerator work until pins and hardware matrix expand further.
5. ~~Next convergence work is a fork: Phase 14 retirement, Phase 7 chunk/preview A/B, or
   Phase 8 live artifact validation~~ — all three closed 2026-07-23. The active route is now
   the 2026-07-25 staged optimization plan (Stage 0 near-free quality wins → Stage 1
   launch-bound attack on current pins → Stage 2 memory program folding phase 9 → Stage 3
   quality harness folding phases 12→13 → Stage 4 gated pin-bump/research bets):
   [`optimization-report-review-2026-07-25.md`](optimization-report-review-2026-07-25.md)
   and `docs/development-progress.md`.

Related: [`docs/decisions/runtime-streaming-quality-convergence.md`](../decisions/runtime-streaming-quality-convergence.md),
[`docs/development-progress.md`](../development-progress.md),
[`config/characterization-fixtures.json`](../../config/characterization-fixtures.json),
[`docs/reference/mlx-guide.md`](mlx-guide.md),
[`docs/reference/ios-engine-optimization.md`](ios-engine-optimization.md).
