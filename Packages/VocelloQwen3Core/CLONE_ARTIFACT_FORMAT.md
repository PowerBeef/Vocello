# Qwen3 clone artifact format

Vocello persists reusable clone prompts as a versioned, atomic artifact. The runtime source and
integrity tests are authoritative; this specification describes the compatibility contract.

## File set

A completed artifact contains the manifest and exactly the tensor files required by its mode:

- `manifest.json`
- `integrity.json`
- `ref_codes.safetensors` when reference codes are present
- `speaker_embedding.safetensors` when a speaker embedding is present

Transcript-backed ICL artifacts require both `ref_codes.safetensors` and a non-empty transcript
in the manifest. X-vector-only artifacts require `speaker_embedding.safetensors`, omit reference
codes and transcript text, and condition generation solely with that learned speaker embedding.

Speaker embeddings are stored canonically as finite `float32` tensors shaped `[1, D]`, where `D`
matches the selected model's decoded speaker-encoder dimension and talker hidden size. The runtime
may accept the official transient `[D]` vector form, but normalizes it before persistence. Prefix
construction casts the validated vector to the talker's compute dtype without changing the durable
artifact representation.

Reference audio accepts exactly one mono recording in `[T]`, `[1, T]`, or `[1, 1, T]` form. The
runtime removes only the supported singleton channel axis and normalizes all three forms to a
`[1, T]` mono batch for the speaker frontend and speech-tokenizer encoder. Batched or multi-channel
input fails; the runtime never chooses the first recording or channel implicitly.

Unexpected, missing, empty, or duplicate files fail validation. Temporary staging directories are
not valid artifacts.

## Manifest identity

Schema 3 binds the required `speakerFeatureVersion` directly in every manifest, in addition to the
model repository and pinned revision, installed model artifact version and integrity-manifest
digest, language, source-audio fingerprint, transcript presence/digest, x-vector mode,
runtime-profile signature, and creation time. Raw audio, transcript text, user paths, and voice
descriptions are not stored as identity metadata. The prompt tensors do not depend on the target
language (prompt creation takes none), so Vocello binds every artifact under the one language value
`auto` and a single artifact serves takes in every language.

The composite runtime-contract signature includes that immutable installed-artifact identity, the
validated Qwen runtime topology, and the speaker-feature identifier
(`Qwen3TTSVoiceClonePrompt.speakerFeatureVersion`,
`Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift:790-798`). That identifier joins three versions
with `+`:

1. the speaker mel frontend, `qwen-speaker-mel-v1`: 24 kHz audio, 1024-point FFT, 256-sample hop,
   384-sample reflect padding, periodic Hann window, magnitude spectrum, 128
   Slaney-scale/Slaney-normalized mel bands, and natural-log scaling;
2. the ICL reference-encode preprocessing, `icl-ref-silence500ms-v2`: 0.5 s of silence appended to
   the reference before the speech-tokenizer encode;
3. the MLX build that computed the stored tensors, `mlx-swift-<pin>` (since 2026-10-16, F-06;
   currently `mlx-swift-0.32.3`). It moves with the mlx-swift pin, and
   `scripts/qwen3_core_contract.py` fails when the two differ.

The identifier today reads `qwen-speaker-mel-v1+icl-ref-silence500ms-v2+mlx-swift-0.32.3`. Changed
weights, a runtime or feature-contract change, or an MLX move invalidates both in-memory and
persisted prompts, so each saved voice rebuilds its prompt once from its reference audio.
Schema-2 artifacts predate this binding and are rejected by both the compatibility reader and the
public `VocelloQwen3Core` facade; they must be rebuilt from their reference audio.

**Known gaps** (engine audit; the parity ledger in
[`docs/reference/qwen3-tts-guide.md`](../../docs/reference/qwen3-tts-guide.md) tracks both):

- **A-02, G-03: the encoder's RoPE convention.** The reference codes in transcript-backed artifacts
  come from a speech-tokenizer encoder that applies `RoPE(traditional: true)` (adjacent pairs,
  `Sources/MLXAudioCodecs/Mimi/Transformer.swift:130`) to weights stored for the split-half
  `rotate_half` layout, so they differ from the official tokenizer's codes. mlx-audio fixed the same
  port. The identifier does not name the encoder implementation yet; the fix adds an encoder version
  to it, so every transcript-backed artifact rebuilds once (ER-04).
- **A-12: the reference padding is Vocello's.** Upstream appends no silence to the reference before
  encoding. The 0.5 s padding is a Vocello choice, and the source comment that calls it upstream
  parity is wrong (ER-04).

## Integrity

`integrity.json` records the exact file set, byte count, SHA-256 digest, and each tensor’s key,
shape, and dtype. Validation fails closed when any digest, length, tensor key, shape, dtype, model,
mode requirement, runtime-profile signature, or speaker-embedding finiteness check differs.

Adoption and persistence run inside an MLX error scope, and the speaker embedding's finite check
runs on the CPU stream, so validating a stored artifact submits no Metal work and an MLX failure
there becomes a typed error rather than a crash (BG-01, F-01; `docs/reference/mlx-guide.md` §2.6). A
file error from MLX's own I/O fails the operation without unloading the model.

## Publication

Writers create and verify a complete sibling staging directory, synchronize its files, and replace
the destination atomically. An interrupted write must leave the previous valid artifact intact and
remove or ignore incomplete staging data.

## Compatibility and rebuild

Readers may accept only explicitly supported schema versions. A model revision, artifact version,
runtime-profile, required-file, tensor-layout, or integrity-schema change requires rebuilding the
artifact unless a tested migration is added. Silent partial reuse is forbidden.
Transcript-backed and x-vector-only artifacts are separate compatibility identities and must never
be reused across modes, even when they share the same source-audio fingerprint.

Deterministic coverage lives in
`Tests/Qwen3RuntimeTests/Qwen3CloneArtifactIntegrityTests.swift`; semantic ownership is
the `clone-artifacts` entry in `RUNTIME_CAPABILITIES.json`; `CLONE-001` and `CLONE-002` in
`SEMANTIC_DELTAS.json` are the active semantic delta entries with explicit removal criteria.
