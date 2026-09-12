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
descriptions are not stored as identity metadata.

The composite runtime-contract signature includes that immutable installed-artifact identity, the
validated Qwen runtime topology, and the speaker-feature algorithm identifier. The current feature
contract is `qwen-speaker-mel-v1`: 24 kHz audio, 1024-point FFT, 256-sample hop, 384-sample reflect
padding, periodic Hann window, magnitude spectrum, 128 Slaney-scale/Slaney-normalized mel bands,
and natural-log scaling. Changed weights or a runtime/feature-contract change invalidates both
in-memory and persisted prompts.
Schema-2 artifacts predate this binding and are rejected by both the compatibility reader and the
public `VocelloQwen3Core` facade; they must be rebuilt from their reference audio.

## Integrity

`integrity.json` records the exact file set, byte count, SHA-256 digest, and each tensor’s key,
shape, and dtype. Validation fails closed when any digest, length, tensor key, shape, dtype, model,
mode requirement, runtime-profile signature, or speaker-embedding finiteness check differs.

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
