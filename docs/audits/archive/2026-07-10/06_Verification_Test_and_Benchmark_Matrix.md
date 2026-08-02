---
status: historical
owner: release-qa
summary: 06 — Verification, Test, and Benchmark Matrix. Archived point-in-time audit. Pinned historical record of findings as they stood at capture.
contentDigest: sha256:76f1fdd7da9870fe9d7a7727261872c2ee1ab319fae8756bfa89d4030df3a30e
---
# 06 — Verification, Test, and Benchmark Matrix

> **Historical snapshot.** This report is pinned to Vocello commit
> `05bd2b6d24b3f43351f3b388622a72d8f0d6ecce`. It is research evidence, not the current runtime,
> telemetry, or benchmark contract. See the [series notice](README.md) and current documentation.


- **QwenVoice/Vocello:** `05bd2b6d24b3f43351f3b388622a72d8f0d6ecce`
- **Recorded upstream import baseline:** `fcbd04daa1bfebe881932f630af2ba6ce9af3274` (`v0.1.2`)
- **Upstream comparison head:** `d302a5c6080d2bb97bae38c7418f82abb76013b6`
- **Review date:** 2026-07-10


The fork should have a dedicated `Qwen3RuntimeTests` target, adapted from upstream's tiny-fixture approach and extended for local concurrency, persistence, streaming, and loading semantics.

## Required deterministic tests

| Area | Test | Acceptance |
| --- | --- | --- |
| Gate | FIFO transfer | Two queued callers acquire in order; no overlap. |
| Gate | Queued cancellation | Cancelled waiter is removed and resumed exactly once. |
| Gate | Cancellation after transfer | Inject cancellation immediately after resume; permit is released and third caller acquires. |
| Gate | Holder failure | Throwing operation always releases. |
| Gate | Stress | Thousands of acquire/cancel/error schedules under deterministic executor hooks. |
| Sampler | Greedy | Temperature <= 0 matches argmax after suppression/repetition. |
| Sampler | Temperature/top-p ordering | Reference implementation proves nucleus changes with temperature. |
| Sampler | Top-k | Exactly expected support and EOS restoration. |
| Sampler | Min-p | Threshold relative to maximum logit matches reference. |
| Sampler | Repetition | Incremental scratch output matches legacy Array(Set()) behavior. |
| Sampler | Fixed seed | Talker and subtalker token traces are stable under the pinned substrate. |
| Sampler | Scratch reuse | Repeated vocab sizes do not alias stale indices or dtypes. |
| Prompt | Custom speaker | All supported speakers resolve; unsupported speaker throws. |
| Prompt | Dialect override | Auto/Chinese dialect voice maps expected codec language. |
| Prompt | 0.6B instruction guard | Unsupported instruction is ignored exactly where intended. |
| Prompt | Design prefix cache | Equivalent normalized descriptions hit; meaningful differences miss. |
| Prompt | Full versus trailing text | Expected embedding lengths and text-conditioning mode flags. |
| Clone | ICL prompt | Transcript required and reference codes present. |
| Clone | x-vector-only prompt | Reference codes absent and speaker embedding requirement enforced. |
| Clone | Artifact round trip | Manifest and tensors reproduce prompt metadata and arrays. |
| Clone | Atomic replacement | Interrupted staging leaves old final artifact intact. |
| Clone | Metadata mismatch | Model/reference/runtime mismatch rejects and rebuilds. |
| Clone | Tensor shape/dtype | Wrong shape or dtype rejects at load. |
| Clone | Tensor digest | One-byte corruption rejects. |
| Clone | Extra/missing files | Exact artifact set is enforced. |
| Loading | Revision isolation | Two revisions resolve to different cache directories. |
| Loading | Prepared trust hit | Validated checkpoint avoids redundant preparation. |
| Loading | Trust invalidation | Config, weight, runtime profile, or dependency ABI change invalidates. |
| Loading | Decoder-only profile | Encoder modules and weights are absent. |
| Loading | Missing requested weights | Load throws; no initialized random component escapes. |
| Loading | Tokenizer direct/fallback | Both paths produce equivalent token IDs. |
| Loading | Cache LRU | macOS/iOS limits and eviction order are deterministic. |
| Loading | Concurrent cache access | No duplicate unsafe state or stale decoder state. |
| Generation | Minimum EOS tokens | EOS is blocked for exactly the configured minimum. |
| Generation | EOS completion | Finish reason is eos. |
| Generation | Token cap | Finish reason maxTokens and Core discards output. |
| Generation | Zero generated codes | Finish reason failed. |
| Generation | Cancellation | Cancellation propagates and decoder state resets. |
| Generation | Mode API parity | Generic compatibility wrapper matches explicit mode where promised. |
| Streaming | Bounded retention | Pending code count remains bounded across long input. |
| Streaming | First/later chunk sizing | Profile transitions occur exactly once. |
| Streaming | Final chunk barrier | Completion cannot overtake final audio callback. |
| Streaming | Consumer termination | Producer stops and state resets. |
| Decoder | Partition invariance | Full decode equals 1/2/3/4/12/25/100/300-frame partitions within strict tolerance. |
| Decoder | Random partitions | Hundreds of randomized partitions. |
| Decoder | Reset | Second stream has no residual context from first. |
| Decoder | Future block shape | Non-five-layer block uses fallback and executes every residual. |
| Decoder | Timing/no timing parity | Instrumentation callback does not change waveform. |
| Code Predictor | Fused RoPE parity | Local fused RoPE matches manual upstream reference. |
| Code Predictor | Mask memo parity | Cached and rebuilt masks produce equal outputs. |
| Code Predictor | Cache reset | Per-frame CP cache offset returns to expected state. |
| Talker KV | Simple path | Default cache is simple and telemetry says simple. |
| Talker KV | Quantized opt-in | Correct cache type and quality gate. |
| Talker KV | Rotating inert boundary | No rotation at W >= maxNewTokens. |
| Talker KV | Rotation boundary | When test cap exceeds W, first rotation happens at documented token. |
| Telemetry | Schema | Every emitted key is accepted by summarizer. |
| Telemetry | Ordering | chunkTimings immediately precedes matching audio. |
| Telemetry | Disabled overhead | No timing callback avoids expensive diagnostic computations. |
| Telemetry | Backward decode | Old KV rows decode with fallback. |
| Output | Atomic final file | Crash/error never exposes a partially published final WAV. |
| Output | Readable PCM/WAV | Final writer output is readable and frame-count accurate. |
| Integration | BackendCore fake | Core mode logic can be tested without a real model. |
| Integration | Single owner | Debug assertion catches concurrent model use. |
| Integration | XPC cancellation | Service and host agree on terminal ordering. |
| Build | Vendor package | SwiftPM production and test targets compile. |
| Build | macOS foundation | Pinned generic macOS build. |
| Build | iOS foundation | Pinned generic device-SDK build. |
| Compatibility | Current pins | Full matrix on production lock. |
| Compatibility | Candidate pins | Same matrix on upgrade branch. |
| Benchmark | Cold/warm matrix | Custom/Design/Clone × Speed/Quality × short/medium/long. |
| Benchmark | Memory | Physical footprint, GPU peak, headroom, trims. |
| Benchmark | Quality | audioQC plus blind listening. |
| Benchmark | Determinism | Seed and token trace logged. |
| Benchmark | Thermal | Sustained iOS series and thermal-state response. |

## Required CI lanes

### Every pull request touching retained vendor or BackendCore code

1. Vendor SwiftPM tests.
2. QwenVoiceCore tests.
3. Generic macOS foundation build.
4. Generic iOS device-SDK build.
5. Project-input/generated-project drift checks.
6. Fixed-seed sampler and decoder partition tests.

### Before release

1. Real Mac cold/warm generation matrix.
2. Supported iPhone on-device matrix.
3. Model load/unload/reload and memory-pressure cycles.
4. Clone artifact corruption and migration cases.
5. XPC cancellation/service termination tests.
6. Full audioQC and listening signoff.
7. Benchmark comparison against pinned baseline with explicit tolerance decisions.
8. Exact dependency lock and vendor-ledger revision included in release metadata.

## Suggested source split to enable testing

```text
Qwen3TTS/
  Qwen3TTSModel.swift
  Qwen3TTSModelLoading.swift
  Qwen3TTSPreparedComponents.swift
  Qwen3TTSPromptAssembly.swift
  Qwen3TTSClonePrompt.swift
  Qwen3TTSSampling.swift
  Qwen3TTSGenerationLoop.swift
  Qwen3TTSStreaming.swift
  Qwen3TTSPrewarm.swift
  Qwen3TTSMemoryCaches.swift
  Qwen3TTSDiagnostics.swift
  Qwen3TTSGenerationGate.swift
```

This is a behavior-preserving refactor. Require fixed-seed token traces and decoder partition parity before and after the split.
