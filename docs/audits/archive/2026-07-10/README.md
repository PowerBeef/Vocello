---
status: historical
owner: release-qa
summary: Corrected QwenVoice / `mlx-audio-swift` Backend Report Series. Archived point-in-time audit. Pinned historical record of findings as they stood at capture.
contentDigest: sha256:2d6de6ec31cd0d7aa1708147710fb21f64ba712ede4ef17c4690701958bf9528
---
# Corrected QwenVoice / `mlx-audio-swift` Backend Report Series

> **Historical snapshot.** This series is pinned to Vocello commit
> `05bd2b6d24b3f43351f3b388622a72d8f0d6ecce` and the upstream revisions listed below. It is
> retained as research evidence, not as the current runtime, telemetry, or benchmark contract.
> Several findings were resolved after the snapshot. For current behavior, start with
> [`docs/reference/telemetry-and-benchmarking.md`](../../../reference/telemetry-and-benchmarking.md),
> [`docs/reference/benchmarking-procedure.md`](../../../reference/benchmarking-procedure.md), and the
> generated [`benchmarks/HISTORY.md`](../../../../benchmarks/HISTORY.md).


- **QwenVoice/Vocello:** `05bd2b6d24b3f43351f3b388622a72d8f0d6ecce`
- **Recorded upstream import baseline:** `fcbd04daa1bfebe881932f630af2ba6ce9af3274` (`v0.1.2`)
- **Upstream comparison head:** `d302a5c6080d2bb97bae38c7418f82abb76013b6`
- **Review date:** 2026-07-10


This report set consolidates and corrects the backend-related research performed in this conversation. It is grounded in the pinned QwenVoice and upstream source trees, repository commit history, current package manifests, Core integration code, and committed benchmark records.

## Central conclusion

The vendored directory is an **owned Qwen3-TTS product runtime derived from `mlx-audio-swift`**, not a thin patch set. For Vocello it is stronger than upstream in product semantics, deterministic loading, streaming memory behavior, clone reuse, completion correctness, instrumentation, and several hot-path optimizations. Upstream remains stronger as a general SDK and in direct package test coverage.

## Important corrections incorporated

1. Production clone-prompt publication is already atomic at the directory level. The limitation is the low-level serializer when used directly and the absence of tensor hash/shape/dtype validation.
2. The generation-gate cancellation-transfer race remains a confirmed high-priority defect.
3. A requested speaker encoder or speech tokenizer can survive as a non-nil initialized object even when no learned weights were loaded.
4. The input-side overlap-and-discard decoder patch is a major current numerical-correctness differentiator and is now fully documented.
5. Decimal scorecards were removed because they implied unsupported precision.
6. The BackendCore boundary recommendation is now nuanced: fork-specific protocols and policy should be isolated, while neutral MLX data types may remain zero-copy exceptions.
7. Compiled SwiGLU is documented as shared with current upstream, not credited as a fork-only optimization.
8. Rotating talker KV is documented as dormant/off by default under the current token cap, not as a current memory win.

## Files in this series

1. [01 — Evidence Method and Correction Ledger](01_Evidence_Method_and_Corrections.md)
2. [02 — Exhaustive Current-State Delta Catalogue](02_Exhaustive_Current_State_Delta_Catalogue.md)
3. [03 — Performance, Memory, Streaming, and Numerical Optimizations](03_Performance_Memory_Streaming_Optimizations.md)
4. [04 — Correctness, Concurrency, Integrity, and Maintainability Findings](04_Correctness_Risk_and_Findings.md)
5. [05 — Upstream Synchronization and Ownership Strategy](05_Upstream_Sync_and_Ownership_Strategy.md)
6. [06 — Verification, Test, and Benchmark Matrix](06_Verification_Test_and_Benchmark_Matrix.md)
7. [Machine-readable CSV delta ledger](backend_delta_ledger.csv)
8. [Machine-readable JSON delta ledger](backend_delta_ledger.json)
9. [Pinned source map](SOURCE_MAP.md)

## Scope

The catalogue covers the retained vendor package and the QwenVoiceCore/app integration surfaces that materially change backend behavior. The approximately 36K deleted upstream lines are summarized by target and codec family rather than itemized line by line, because they are intentionally absent and have no active runtime semantics.

## Limitations

No Xcode build, production model load, waveform comparison, Instruments capture, or physical-device benchmark was executed in this environment. Hardware numbers are reproduced only when they are committed in the repository and are labeled as scoped benchmark evidence.
