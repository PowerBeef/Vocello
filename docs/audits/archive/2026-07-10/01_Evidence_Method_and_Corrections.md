# 01 — Evidence Method and Correction Ledger

> **Historical snapshot.** This report is pinned to Vocello commit
> `05bd2b6d24b3f43351f3b388622a72d8f0d6ecce`. It is research evidence, not the current runtime,
> telemetry, or benchmark contract. See the [series notice](README.md) and current documentation.


- **QwenVoice/Vocello:** `05bd2b6d24b3f43351f3b388622a72d8f0d6ecce`
- **Recorded upstream import baseline:** `fcbd04daa1bfebe881932f630af2ba6ce9af3274` (`v0.1.2`)
- **Upstream comparison head:** `d302a5c6080d2bb97bae38c7418f82abb76013b6`
- **Review date:** 2026-07-10


## Method

The audit used four evidence layers:

1. **Current local source** at the pinned QwenVoice commit.
2. **Current upstream source** at the pinned upstream head.
3. **Imported upstream baseline** at `v0.1.2` for provenance.
4. **Repository commit/benchmark records** for intent and measured outcomes.

Current behavior is never inferred from a commit message alone. A historical optimization is marked active only when its implementation remains in the pinned source.


### Evidence labels

- **Confirmed in source:** directly present in the pinned implementation and, where relevant, compared with the pinned upstream file.
- **Source plus repository benchmark evidence:** active code is confirmed and the repository contains a scoped hardware result.
- **Repository benchmark evidence:** a committed experiment or result; it is not automatically universal or current on other hardware.
- **Recommendation:** a proposed maintenance or architecture change, not an existing defect.
- **Active defect:** a source-level failure mode that remains reachable in the pinned code.


## Correction ledger

| Earlier statement | Corrected statement | Grounding | Effect |
| --- | --- | --- | --- |
| Clone-prompt artifacts are not transactionally published. | The Core production path stages a complete directory and atomically moves/replaces it. The public low-level serializer is not independently transactional, and tensor contents are not structurally or cryptographically validated. | [`Sources/QwenVoiceCore/NativeCloneSupport.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/Sources/QwenVoiceCore/NativeCloneSupport.swift) and [`third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift) | Remove the prior High publication finding; retain an integrity-validation finding and serializer API-hardening recommendation. |
| The report fully represented the important loader risks. | It omitted a fail-open component-load path: requested learned components can remain non-nil when their sanitized weight maps are empty. | [`third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift) | Add a Medium-High correctness finding. |
| The deepest codec layer remains largely close to upstream. | That is broadly true, but it underplayed a major active divergence: transposed-convolution streaming uses input-side overlap-and-discard rather than upstream output-tail overlap-add. | [`third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift) versus [`Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift`](https://github.com/Blaizzy/mlx-audio-swift/blob/d302a5c6080d2bb97bae38c7418f82abb76013b6/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift) | Promote to a first-class correctness optimization and upstream candidate. |
| CodePredictor compiled SwiGLU is a fork optimization. | It is important active behavior but current upstream also uses the shapeless compiled SwiGLU interior. | [`third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSCodePredictor.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSCodePredictor.swift) and [`Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSCodePredictor.swift`](https://github.com/Blaizzy/mlx-audio-swift/blob/d302a5c6080d2bb97bae38c7418f82abb76013b6/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSCodePredictor.swift) | Document as inherited/shared, not fork-only. |
| Only BackendCore should import any MLXAudio product. | Fork-specific Qwen protocols, loading, policy, and diagnostics should be isolated behind BackendCore. Neutral MLXArray/Core types may remain explicit exceptions where copying or artificial wrappers would be harmful. | [`project.yml`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/project.yml) | More practical anti-corruption boundary. |
| Decimal score values precisely rank the two implementations. | The relative qualitative ranking is defensible, but decimal values were subjective and are removed. | Assessment-method correction. | No false precision. |
| Rotating KV is a current memory optimization. | The plumbing exists, but it is off by default and a 2048 window is inert under the current 2048 output-token cap. Repository measurements found negligible benefit. | [`benchmarks/OPTIMIZATION.md`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/benchmarks/OPTIMIZATION.md) and [`third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSTalker.swift`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/third_party_patches/mlx-audio-swift/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSTalker.swift) | Classify as dormant insurance capability, not a shipped RAM win. |
| All reported performance timing fields directly represent GPU stage compute. | Most Swift-side timers surround lazy graph construction. The explicit eval interval contains fused GPU work; Instruments/signposts are needed for kernel attribution. | [`benchmarks/OPTIMIZATION.md`](https://github.com/PowerBeef/Vocello/blob/05bd2b6d24b3f43351f3b388622a72d8f0d6ecce/benchmarks/OPTIMIZATION.md) | Prevents invalid performance conclusions. |

## Source-of-truth order

1. Active implementation at the pinned commit.
2. Tests that execute the implementation.
3. Build/package manifests.
4. Current architecture/reference documentation.
5. Commit messages and benchmark history.
6. Recommendations and proposed architecture.

## Cross-repository comparison caveat

The two repositories do not share one Git object graph, so the analysis is a retained-file and symbol comparison rather than a single native `git diff`. Every ledger row names the relevant local and upstream paths; intentional bulk deletions are grounded in the specialization commit and package manifests.

## Confidence summary

| Evidence class | Count |
| --- | --- |
| Confirmed in source | 119 |
| Repository benchmark evidence | 4 |
| Source plus repository benchmark evidence | 2 |
| Confirmed by source and specialization commit | 1 |
| Repository benchmark methodology | 1 |
