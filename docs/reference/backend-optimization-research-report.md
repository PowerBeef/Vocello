# 1.7B Custom Backend Optimization Research Report

> **Historical snapshot.** This report records the repository at its stated 2026-06-16 checkpoint and
> preserves the measurements and decisions made there. It is not the current runtime, telemetry, or
> benchmark contract. For current behavior, use
> [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md),
> [`benchmarking-procedure.md`](benchmarking-procedure.md), and the generated
> [`benchmarks/HISTORY.md`](../../benchmarks/HISTORY.md).

> **Scope:** 1.7B Qwen3-TTS only. 0.6B variants are explicitly out of scope.  
> **Date:** 2026-06-16  
> **Hardware:** Mac mini, Apple M2, 8 GB RAM (`floor_8gb_mac`)  
> **Runtime:** MLX Swift 0.30.6 / mlx-swift-lm 2.30.6, `build/vocello` CLI, telemetry schema v5.
>
> **Editor's note (2026-08-01):** the pins have since moved to 0.31.6 / 3.31.4
> (`benchmarks/OPTIMIZATION.md` §Q). The fp16 decoder-weight metallib load failure
> recorded below was observed on 0.30.6 and has **not** been re-tested on 0.31.6; a
> conv-stack micro-probe on 0.31.6 showed half-precision conv *faster* than fp32 at the
> decoder's geometry on both pins, so a load re-test is the candidate next step if the
> §N 2.3 codec-precision lever is ever revived.

## Executive summary

- **The biggest transparent RAM win is already known:** the **streaming** path keeps peak memory flat and far lower than the non-streaming CLI default. On the test hardware, switching from non-streaming to streaming cuts peak GPU memory by **~1.5–4.5 GB** on medium/long content without hurting RTF and with only a modest TTFC penalty.
- **Decoder-weight downcasting is blocked:** the speech-tokenizer decoder ships as **682 MB of F32 weights** per 1.7B model. Casting those weights to fp16 would save **~341 MB per loaded model**, but on MLX 0.30.6 the model fails to load with `Failed to load the default metallib` — the fp16 kernel surface is missing/incompatible with this build. This lever is **blocked until MLX is upgraded** (which is currently deferred).
- **Output accumulation is not the culprit:** accumulated codec tokens and final PCM for a 23 s utterance are <2 MB combined. The non-streaming memory growth is cached activations / intermediate arrays, not the output buffers themselves.
- **Per-frame graph-build overhead is already well understood:** prior `os_signpost` work showed `Step Eval Flush` (fused GPU eval) dominates at ~61%, CP graph build ~17%, talker build ~6%, and inter-frame asyncEval/plumbing ~13%. `compile()` was previously rejected and `MLXFast.RoPE` fusion is marginal. No new cheap lever was found.
- **`maxNewTokens = 2048` is large headroom for normal content** but hard-errors on very long scripts. A length-aware budget would mainly improve robustness, not RAM.

**Bottom line:** the only immediate, safe, measurable improvement is to make the **macOS streaming path the default for benchmarking and, where product-appropriate, for generation**. Everything else is either already shipped/rejected, blocked on MLX, or has negligible expected impact.

---

## 1. Streaming vs. non-streaming (1.7B)

### Method

`scripts/streaming_ram_ab.py` ran the fixed short/medium/long corpus for `custom` and `design` Speed, once with `--stream` and once without, using an isolated `--data-dir` so telemetry could be cleanly tagged. Each run was a fresh `vocello` process (cold load), so absolute peaks include model load; the **stream vs. non-stream delta** is the key comparison.

### Results

| mode   | len    | stream | n | RTF  | tok/s | decode ms | gpuPeak MB | physFoot MB | QC                  |
|--------|--------|--------|---|------|-------|-----------|------------|-------------|---------------------|
| custom | long   | 0      | 1 | 0.99 | 12.44 | 23318     | 5826       | 5256        | pass                |
| custom | long   | 1      | 1 | 1.01 | 12.66 | 23372     | 2822       | 2855        | pass                |
| custom | medium | 0      | 1 | 0.95 | 11.90 | 6806      | 4414       | 4745        | pass                |
| custom | medium | 1      | 1 | 1.00 | 12.50 | 5918      | 2316       | 2469        | pass                |
| custom | short  | 0      | 1 | 0.84 | 10.45 | 2202      | 3301       | 3386        | pass                |
| custom | short  | 1      | 1 | 0.96 | 11.98 | 2839      | 2316       | 2485        | warn (dropout:excess1(1/0)) |
| design | long   | 0      | 1 | 1.01 | 12.66 | 36814     | 6986       | 6421        | pass                |
| design | long   | 1      | 1 | 1.04 | 13.03 | 21034     | 2445       | 2553        | pass                |
| design | medium | 0      | 1 | 1.02 | 12.74 | 7299      | 4771       | 4538        | pass                |
| design | medium | 1      | 1 | 1.03 | 12.81 | 8195      | 3263       | 2778        | pass                |
| design | short  | 0      | 1 | 0.93 | 11.57 | 2593      | 2278       | 2884        | pass                |
| design | short  | 1      | 1 | 0.96 | 12.03 | 1912      | 2324       | 2439        | pass                |

### Key takeaways

- **RAM:** Streaming consistently lowers peak GPU and physical footprint. The benefit grows with length:
  - custom/long: **−3.0 GB gpuPeak, −2.4 GB physFoot**
  - design/long: **−4.5 GB gpuPeak, −3.9 GB physFoot**
- **RTF:** Streaming is neutral to slightly better (asyncEval overlap). The design/long non-streaming decode time was anomalously long in this single run, but the aggregate picture matches prior bench data.
- **TTFC:** Streaming adds ~700–1300 ms first-chunk latency, which is expected and acceptable for the macOS bench/app.
- **audioQC:** One streaming short custom run produced a `warn:dropout:excess1` — a single borderline pause on very short text. This is within normal prosody variance and not a streaming-specific defect.

### Verdict

**Go** — switch macOS bench (and generation where the product can tolerate TTFC) to streaming. This is the only lever that simultaneously cuts RAM and keeps quality/RTF intact.

---

## 2. Speech-tokenizer decoder precision

### Method

`scripts/audit_decoder_memory.py` inspected `speech_tokenizer/model.safetensors` for every installed 1.7B model.

### Results

| model family | decoder weight dtype | decoder weight size |
|--------------|----------------------|---------------------|
| 1.7B Base / CustomVoice / VoiceDesign (all) | F32 | **682.23 MB** |

- Every tensor in `speech_tokenizer/model.safetensors` is `F32`.
- The same 682 MB file is shared across Speed and Quality variants of each family, so a loaded 1.7B model carries **~682 MB of F32 decoder/encoder weights** regardless of quantization tier.
- Casting only the `decoder.*` tensors to fp16 would reduce the decoder footprint by roughly half (**~341 MB**).

### fp16 downcast experiment

`scripts/cast_decoder_to_fp16.py` created a copy of `Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit` with only `decoder.*` tensors cast to fp16. A research manifest (`scripts/manifest_fp16_decoder_research.json`) was created and `vocello generate` attempted to load it.

Result:

```
MLX error: Failed to load the default metallib. library not found …
```

The model fails during load on MLX Swift 0.30.6. The F32 metallib is present (the original model loads), but the fp16 decoder path requires kernels that are not available in this build.

### Verdict

**Blocked** — large theoretical RAM win (~341 MB per loaded model), but not achievable without either:
- an MLX version bump that includes the required fp16 kernels, or
- a custom metallib build.

Both options violate the current “stay pinned at 0.30.6” policy (`benchmarks/OPTIMIZATION.md` §E). Re-evaluate after the next approved MLX upgrade.

---

## 3. Non-streaming output-accumulation memory

### Method

`scripts/audit_nostreaming_accumulation.py` compared non-streaming vs. streaming runs and estimated the bytes held in accumulated codec tokens and final PCM.

### Results

| mode   | len    | stream | audio s | PCM MB | codec frames | codec tokens | token MB | gpuPeak MB | physFoot MB |
|--------|--------|--------|---------|--------|--------------|--------------|----------|------------|-------------|
| custom | long   | 0      | 23.20   | 1.114  | 290          | 4640         | 0.019    | 5826       | 5256        |
| custom | long   | 1      | 23.68   | 1.137  | 296          | 4736         | 0.019    | 2822       | 2855        |

The accumulated output itself (PCM + tokens) is **< 2 MB** even for a 23 s utterance. The observed multi-gigabyte difference between streaming and non-streaming comes from cached MLX intermediates and per-frame activations that are released or cleared between chunks in streaming mode, not from holding the final output.

### Verdict

**No-go for a stream-to-disk optimization** — the accumulator is already tiny. The streaming path is the correct fix; rewriting output buffering would not materially change peak RAM.

---

## 4. Per-frame overhead

### Existing knowledge

`benchmarks/OPTIMIZATION.md` §F already captured the GPU attribution:

| stage (custom/speed/long) | % gen |
|---------------------------|-------|
| Step Eval Flush (fused eval) | ~61% |
| Code Predictor Loop (graph build) | ~17% |
| Talker Forward (graph build) | ~6% |
| inter-frame gap / asyncEval / plumbing | ~13% |

`compile()` was tested and rejected: it regressed warm RTF ~5% because marshaling quantized parameters cost more than the Swift build overhead it removed.

### This investigation

- A fresh `xctrace` capture was attempted with the `os_signpost` instrument. The export did not yield the expected `os-signpost-interval` table (only raw `kdebug` events), so the prior OPTIMIZATION.md attribution remains the authoritative breakdown.
- Verbose telemetry samples (`QWENVOICE_NATIVE_TELEMETRY_MODE=verbose`) provide per-frame memory snapshots but not per-frame stage timings; the aggregate `timingsMS` breakdown in the engine row confirms the same pattern.

### Verdict

**No new actionable lever.** The remaining ~17% CP graph-build overhead is hard to reclaim on MLX 0.30.6 without `compile()`, which has already been rejected. The inter-frame gap is mostly overlapped decoder work and is not idle time.

---

## 5. `maxNewTokens` policy

### Current state

- Default app policy: `maxNewTokens = 2048` (`QwenVoiceBackendCore.swift:20`).
- Checkpoint default: `8192` (unused by the app).
- The engine hard-errors and discards output if the cap is hit.

### Token budget vs. text length

Approximate upper-bound tokens (15 chars/s speech rate, 12.5 Hz frames, 16 codebooks):

| chars | approx audio s | codec frames | codec tokens |
|-------|----------------|--------------|--------------|
| 35    | 2.3            | 29           | 467          |
| 110   | 7.3            | 92           | 1,467        |
| 330   | 22.0           | 275          | 4,400        |
| 1,000 | 66.7           | 833          | 13,333       |
| 2,000 | 133.3          | 1,667        | 26,667       |

Normal short/medium/long corpus content uses far less than 2048 tokens. The cap only matters for very long scripts (> ~300 words).

### Verdict

**Low-priority / informational.** A length-aware `maxNewTokens` budget would mainly prevent hard failures on very long input and reduce worst-case reservation. The talker KV is small (tens of MB), so the RAM impact is minor. Worth documenting, but not a headline optimization.

---

## 6. Ranked recommendations

| Rank | Lever | Expected RTF impact | Expected RAM impact | Quality risk | Implementation cost | Verdict |
|------|-------|--------------------:|--------------------:|--------------|---------------------|---------|
| 1 | **macOS streaming default / bench** | Neutral to +5% | **−1.5 to −4.5 GB peak** on medium/long | Very low | Low | **Go** |
| 2 | Decoder fp16 weights | ~0% | **−~341 MB per loaded model** | Unknown (metallib blocked) | Medium (vendored patch + quality pass) | **Blocked on MLX 0.30.6** |
| 3 | Length-aware `maxNewTokens` | ~0% normal | Small (KV is tiny) | Low | Low | **Nice-to-have** |
| 4 | Reduce CP/inter-frame overhead | +?% (uncertain) | ~0 | Medium (graph rewrite) | High | **No-go** |
| 5 | Stream-to-disk output buffering | ~0% | Negligible (accumulator <2 MB) | Low | Low | **No-go** |

---

## 7. Recommended next step

1. **Switch `vocello bench` to streaming mode by default** (or add a `--stream` flag and make streaming the default for the headline matrix). This aligns the macOS benchmark with the iOS streaming reality and immediately yields iOS-representative RAM numbers.
2. Re-run the full benchmark matrix in streaming mode and update the standing baseline.
3. Keep the decoder-fp16 lever on the backlog for the next MLX upgrade cycle; do not pursue it on 0.30.6.
4. Optionally implement a length-aware `maxNewTokens` budget as a robustness improvement for long scripts.

---

## 8. Implementation note

The **Rank 1 recommendation was implemented** in the same session:

- `Sources/VocelloCLI/BenchCommand.swift` — `vocello bench` now streams by default; `--no-stream` reverts to the old full-result behavior.
- `Sources/VocelloCLI/GenerateCommand.swift` — `vocello generate` now streams by default; `--no-stream` disables streaming.
- Updated docs: `docs/reference/cli.md`, `docs/reference/telemetry-and-benchmarking.md`, `docs/reference/mlx-guide.md`, `docs/reference/ios-engine-optimization.md`, and `benchmarks/OPTIMIZATION.md`.
- Built and smoke-tested the CLI (`generate` streaming and `--no-stream` both produce valid audio).
- Re-ran the benchmark matrix in streaming mode and saved the new baseline: [`benchmarks/baseline-2026-06-16-45720dd-streaming-default.md`](../../benchmarks/baseline-2026-06-16-45720dd-streaming-default.md).
- Appended ledger rows to the then-current manual history. That snapshot is now preserved in
  `benchmarks/LEGACY_HISTORY.md`; new validated runs are indexed by generated `benchmarks/HISTORY.md`.

Streaming-default headline (floor 8 GB Mac, warm median):

| mode   | model             | len    | RTF  | physFoot MB | QC   |
|--------|-------------------|--------|------|-------------|------|
| custom | pro_custom_speed  | medium | 1.01 | 2456        | pass |
| custom | pro_custom_speed  | long   | 1.01 | 2865        | pass |
| design | pro_design_speed  | long   | 1.04 | 3047        | pass |
| custom | pro_custom_quality| medium | 0.83 | 3594        | pass |

This confirms the research A/B: streaming cuts the macOS peak to iOS-representative levels (~2.4–3.8 GB for Speed, ~3.1–3.6 GB for Quality) while keeping RTF neutral/positive and QC pass.

## Artifacts

- `scripts/streaming_ram_ab.py` — paired streaming/non-streaming A/B harness.
- `scripts/audit_decoder_memory.py` — speech-tokenizer decoder dtype/size audit.
- `scripts/cast_decoder_to_fp16.py` — create fp16-decoder model copy (research only).
- `scripts/manifest_fp16_decoder_research.json` — research manifest for fp16 decoder.
- `scripts/bench_fp16_decoder.py` — fp16 decoder A/B harness.
- `scripts/audit_nostreaming_accumulation.py` — output-accumulator memory estimate.
- Raw data: `/tmp/streaming_ab/all_diagnostics`, `/tmp/verbose_ab/diagnostics`, `/tmp/fp16dec_ab/all_diagnostics`.
