# Historical upstream comparison

This package is Vocello-owned product source derived from
[`Blaizzy/mlx-audio-swift`](https://github.com/Blaizzy/mlx-audio-swift). It is copied into the
repository, not tracked as a submodule and not maintained as a rebasing fork.

Current ownership and capabilities are authoritative in:

- [`LINEAGE.json`](LINEAGE.json)
- [`COMPATIBILITY.json`](COMPATIBILITY.json)
- [`RUNTIME_CAPABILITIES.json`](RUNTIME_CAPABILITIES.json)
- [`OWNERSHIP.json`](OWNERSHIP.json)
- [`CURRENT_INVENTORY.json`](CURRENT_INVENTORY.json)

The immutable import and current semantic delta are deliberately separate:

- [`UPSTREAM_BASELINE.json`](UPSTREAM_BASELINE.json)
- [`SEMANTIC_DELTAS.json`](SEMANTIC_DELTAS.json)

`UPSTREAM_BASELINE.json` never stores null hashes or absorbs current additions.
`CURRENT_INVENTORY.json` is regenerated from current retained files and computes the exact
identical, modified, added, and removed counts. `SEMANTIC_DELTAS.json` maps every changed or added
implementation file to a controlled semantic delta with source, test, documentation, evidence,
upstream-disposition, and removal references.

`RELOCATION_INVENTORY.json` separately proves the original path-move classification and explicitly
excludes files added after that event. It must not be substituted for the live current inventory.

## Import and review points

- Imported release: `v0.1.2`
- Imported commit: `fcbd04daa1bfebe881932f630af2ba6ce9af3274`
- Last reviewed upstream head: `d302a5c6080d2bb97bae38c7418f82abb76013b6` on 2026-07-14
- Official Qwen model family: [`QwenLM/Qwen3-TTS`](https://github.com/QwenLM/Qwen3-TTS)

The import was specialized to Qwen3-TTS. Vocello retains `MLXAudioCore`, the Mimi subset of
`MLXAudioCodecs`, `MLXAudioTTS`, and product-owned Qwen3 tests. STT, STS, VAD, LID, G2P, UI/tools,
non-Qwen TTS models, and non-Mimi codec families are outside the production package surface.

## Current integration boundary

`QwenVoiceCore` owns model coordination, generation semantics, memory policy, telemetry sessions,
and the application-facing engine. The owned core package owns the lower-level Qwen3 model,
tokenizer, sampler, streaming, codec, and clone-artifact implementation.

`QwenVoiceBackendCore` does **not** re-export MLX or MLXAudio. It contains provenance, shared
generation defaults and policy vocabulary, finish reasons, and a minimal app-owned backend
abstraction.

The macOS app reaches the engine through an XPC service. The iPhone engine runs in-process. There
is no iPhone extension engine and no repository-owned Python inference runtime.

## Production posture

Production generation uses bounded chunked streaming for Custom Voice, Voice Design, and Voice
Clone. The pipeline asynchronously materializes non-final chunks, synchronizes consumers, and
uses a final barrier before reporting completion or publishing the final WAV. Full-result helpers
remain useful for explicit offline/diagnostic paths; they are not the universal production default.

Sampling follows the checkpoint’s official talker defaults. The Code Predictor/subtalker inherits
the effective talker temperature, top-k, and top-p unless a controlled diagnostic override is set.
See [`PERFORMANCE.md`](PERFORMANCE.md) for the design narrative; `RUNTIME_CAPABILITIES.json` records
each capability's production, diagnostic, internal or retired state and `SEMANTIC_DELTAS.json` each delta's
active, diagnostic, dormant, shared, superseded or removed state.

## Selective upstream intake

Future upstream intake is selective engineering, not a rebase:

1. Record the upstream head reviewed separately from the immutable origin in `LINEAGE.json`.
2. Compare it with the pinned baseline and current semantic ledger.
3. Port only behavior that preserves Vocello’s model, artifact, streaming, cancellation, memory,
   output, and telemetry contracts.
4. Update `RUNTIME_CAPABILITIES.json` and the active `SEMANTIC_DELTAS.json` semantic entries for affected
   implementation files.
5. Run `python3 scripts/qwen3_core_contract.py rebuild-current-inventory`. Benchmark evidence
   remains `diagnostic` or `unverified` after runtime-impacting changes until a matching clean
   record exists.
6. Run `scripts/dev.sh check` (its contract lane runs `python3 scripts/qwen3_core_contract.py
   validate`) and let CI on `main` gate the push. A runtime-impacting intake needs new validated
   benchmark records (schema v3 for generation lanes; `rtf` = wall ÷ audio, lower is faster, with `run.rtfDefinition`;
   `toolchain.optimization` from the hash-bound build receipt) before its evidence leaves `diagnostic`.

Never replace the directory wholesale, infer parity from matching filenames, or treat a newer
upstream implementation as equivalent without the relevant deterministic and benchmark evidence.
