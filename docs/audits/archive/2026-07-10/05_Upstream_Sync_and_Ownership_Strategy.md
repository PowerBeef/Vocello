---
status: historical
owner: release-qa
summary: 05 — Upstream Synchronization and Ownership Strategy. Archived point-in-time audit. Pinned historical record of findings as they stood at capture.
contentDigest: sha256:e1789bc188aaea7c7e81068d682e869f4fffa8097bdf08a2bb20dae7c02260ae
---
# 05 — Upstream Synchronization and Ownership Strategy

> **Historical snapshot.** This report is pinned to Vocello commit
> `05bd2b6d24b3f43351f3b388622a72d8f0d6ecce`. It is research evidence, not the current runtime,
> telemetry, or benchmark contract. See the [series notice](README.md) and current documentation.


- **QwenVoice/Vocello:** `05bd2b6d24b3f43351f3b388622a72d8f0d6ecce`
- **Recorded upstream import baseline:** `fcbd04daa1bfebe881932f630af2ba6ce9af3274` (`v0.1.2`)
- **Upstream comparison head:** `d302a5c6080d2bb97bae38c7418f82abb76013b6`
- **Review date:** 2026-07-10


## Recommended model

Use **selective porting**, not rebasing.

The local tree has intentionally deleted most of upstream and has added product APIs, persistent artifact formats, concurrency, caches, diagnostics, and policy. A wholesale snapshot replacement would erase tested product invariants and create a very large review surface.

## Ownership layers

### Layer 1 — Upstream-derived mathematical kernel

Keep structurally close where practical:

- Qwen talker/code-predictor modules;
- Mimi convolution, transformer, quantization, and SEANet primitives;
- speech-tokenizer mathematical layers;
- generic array helpers.

Local correctness/performance patches in this layer must have parity tests and patch-ledger entries.

### Layer 2 — Owned Qwen3 runtime

Own explicitly:

- prepared loading/capability profiles;
- mode-specific APIs;
- clone artifact;
- prompt/prefix caches;
- generation gate;
- sampling scratch/order;
- streaming/full-result policy;
- finish reasons;
- typed diagnostics.

### Layer 3 — BackendCore adapter

Own:

- model contract and revision mapping;
- request sampling variation;
- device/runtime policy injection;
- diagnostic translation;
- app-safe errors;
- MLX model wrapper ownership.

### Layer 4 — Product orchestration

Own:

- XPC/in-process lifecycle;
- model delivery;
- memory admission;
- output files/history;
- playback;
- UI readiness/cancellation.

## Immediate upstream candidates

1. Temperature-before-top-p/min-p sampling order plus deterministic tests.
2. Incremental repetition token set and reusable sampler scratch.
3. Streaming pending-code retention instead of full generated-code history.
4. Code Predictor fused RoPE and causal-mask memoization.
5. Input-side overlap-and-discard decoder step plus partition tests.
6. Exact block-count fast-path guard.
7. Revision-separated ModelUtils cache.
8. Structured completion/finish reason as an additive API.
9. PCM helper stream cancellation propagation.

## Keep local

- product mode APIs;
- persistent clone artifact and metadata;
- prepared-checkpoint trust;
- platform cache limits;
- prewarm-depth policy;
- speed/chunk profiles;
- user variation modes and seed recording;
- XPC/iOS process policy;
- product telemetry schema;
- Qwen-only package pruning.

## Selective upstream ports to evaluate

1. Tiny Qwen fixture tests.
2. Typed speaker/dialect configuration.
3. Generic StreamingWAVWriter buffer reuse.
4. New Mimi convolution wrappers, only with the MLX compatibility branch.
5. Useful Qwen correctness fixes in retained files.
6. Tokenizer/model-loading fixes that do not reintroduce broad model dependencies.

## Do not port by default

- unrelated model families;
- STT/STS/VAD/LID/G2P/UI targets;
- broad tools/examples;
- generic model registries;
- remote-main production loading;
- upstream full-history streaming retention;
- overloaded Custom Voice string conventions;
- any change that returns token-capped audio as success.

## Automated watch list

```text
Package.swift
Package.resolved
Sources/MLXAudioCore/Generation/**
Sources/MLXAudioCore/AudioUtils.swift
Sources/MLXAudioCore/ModelUtils.swift
Sources/MLXAudioCore/DSP.swift
Sources/MLXAudioCodecs/Mimi/Conv.swift
Sources/MLXAudioCodecs/Mimi/Quantization.swift
Sources/MLXAudioCodecs/Mimi/Transformer.swift
Sources/MLXAudioCodecs/Mimi/Seanet.swift
Sources/MLXAudioTTS/Generation.swift
Sources/MLXAudioTTS/TTSModel.swift
Sources/MLXAudioTTS/Models/Qwen3TTS/**
Tests/*Qwen*
Tests/MLXAudioTTSTests.swift
Tests/MLXAudioCodecsTests.swift
```

A scheduled workflow should compare the recorded reviewed upstream SHA with upstream `main`, filter to the watch list, and open/update one review issue. Every changed file receives a disposition:

- port;
- already equivalent;
- superseded by local design;
- irrelevant;
- blocked by dependencies;
- requires benchmark;
- requires waveform/token parity.

## Patch ledger schema

The included CSV/JSON should be committed or converted into a repository-native manifest. Minimum fields:

- stable ID;
- path and symbol;
- category;
- local behavior;
- upstream behavior;
- rationale;
- current/reverted/dormant state;
- defect status;
- evidence class;
- provenance commit;
- upstreamability;
- required tests;
- removal criteria.

## Dependency upgrade lane

Run quarterly or when a required fix lands:

1. branch from a known release baseline;
2. update Swift tools/MLX/MLX-LM and regenerate lock/project files;
3. compile macOS and generic iOS;
4. run backend unit tests;
5. run fixed-seed token traces;
6. test batch versus streamed decoder partition parity;
7. test 4-bit and 8-bit load verification;
8. compare load time, TTFA, RTF, physical footprint, GPU peak, and trims;
9. run audioQC and listening matrix;
10. keep only with documented evidence.

Do not combine dependency upgrades with sampling, prompt, or memory-policy changes.
