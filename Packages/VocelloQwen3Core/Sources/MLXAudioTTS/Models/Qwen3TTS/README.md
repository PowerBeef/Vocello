---
status: active
owner: backend-mlx
reviewed: 2026-09-06
summary: Owned Qwen3 implementation API routing; compatibility examples are not production catalog or facade instructions.
sourceOfTruth:
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift
  - Packages/VocelloQwen3Core/COMPATIBILITY.json
---
# Qwen3-TTS implementation reference

This directory implements the runtime behind [the owned facade](../../../../README.md).
Vocello product code uses `VocelloQwen3Engine`, classified sessions and materialized PCM, not
direct imports of `MLXAudioTTS` or the generic compatibility stream. Follow
[COMPATIBILITY.json](../../../../COMPATIBILITY.json) for supported boundaries and
[RUNTIME_CAPABILITIES.json](../../../../RUNTIME_CAPABILITIES.json) for capabilities.

## Explicit mode routing

The implementation's named methods keep conditioning channels separate:

| Mode | Quality-first entry point | Conditioning |
| --- | --- | --- |
| CustomVoice | `generateCustomVoice` / `generateCustomVoiceQualityFirst` | Separate `speaker` and optional `instruct` |
| VoiceDesign | `generateVoiceDesign` / `generateVoiceDesignQualityFirst` | `voiceDescription` |
| Base Clone | `generateVoiceClone` / `generateVoiceCloneQualityFirst` | Prepared `voiceClonePrompt`; no delivery instruction |

Each takes the target text/language plus caller-owned generation parameters, request sampling
policy and request memory policy. Do not invent defaults or share mutable random state.
The corresponding explicit streaming methods remain implementation/compatibility surfaces;
product generation follows the facade's isolation, single-consumer and cancellation contracts.

The generic `generate(text:voice:refAudio:refText:language:...)` forwards `voice` as an
instruction. It does **not** parse a combined speaker-and-emotion string. In particular,
`voice: "Vivian, very happy"` is not a CustomVoice speaker selector. Base cloning has no
built-in speaker roster, and model families must not be inferred from this compatibility API.

## Models, scripts and reference audio

Approved artifact identities, model variants and native speaker languages come from the root
`Sources/Resources/qwenvoice_contract.json` and complete production model catalog. Example Hub
repository names are not permission to bypass those immutable delivery plans. The production
catalog, not this directory, determines supported variants and instruction capability.

Keep a reviewed reference transcript aligned with its audio. Reference language is conditioning
metadata; it must not select the target output language. Transcript-backed and audio-only
conditioning remain distinct recorded modes.

## Streaming and sequential work

Streaming interval affects publication cadence, not permission to alter request-local sampling,
drop audio or raise token limits. Product PCM must be materialized in its owning isolation domain
before transport. Reaching a token cap without EOS is incomplete output, not successful truncation.
Do not copy legacy examples that retain a whole unbounded chunk list or send MLX arrays across tasks.

Use the existing product batch/long-form runners for sequential work; do not turn compatibility
method calls into concurrent generation. Accepted-output ownership, per-item identity, QC and
cancellation remain the caller's governed transaction, not a new batch API in this README.
