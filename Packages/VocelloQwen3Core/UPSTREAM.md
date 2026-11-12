# Upstream review points

This package is Vocello-owned product source derived from
[`Blaizzy/mlx-audio-swift`](https://github.com/Blaizzy/mlx-audio-swift). It is copied into the
repository, not tracked as a submodule and not maintained as a rebasing fork. This file is the
ledger of the upstreams Vocello tracks and where each was last reviewed. How to review and port a
change is in
[`docs/reference/qwen3-core-maintenance.md`](../../docs/reference/qwen3-core-maintenance.md#selective-upstream-intake).

## Authority

Ownership and capabilities are authoritative in:

- [`LINEAGE.json`](LINEAGE.json): the immutable origin and `lastReviewedUpstream`;
- [`COMPATIBILITY.json`](COMPATIBILITY.json), [`OWNERSHIP.json`](OWNERSHIP.json) and
  [`RUNTIME_CAPABILITIES.json`](RUNTIME_CAPABILITIES.json);
- [`CURRENT_INVENTORY.json`](CURRENT_INVENTORY.json), regenerated from the retained files with exact
  identical, modified, added and removed counts.

The immutable import and the current semantic delta are deliberately separate:

- [`UPSTREAM_BASELINE.json`](UPSTREAM_BASELINE.json) never stores null hashes or absorbs later
  additions;
- [`SEMANTIC_DELTAS.json`](SEMANTIC_DELTAS.json) maps every changed or added implementation file to
  a controlled delta with source, test, documentation, evidence, upstream-disposition and removal
  references.

[`RELOCATION_INVENTORY.json`](RELOCATION_INVENTORY.json) proves the original path move and excludes
files added after it; it is not the live inventory.

## Origin

- Imported release `v0.1.2`, commit `fcbd04daa1bfebe881932f630af2ba6ce9af3274` (2026-03-12;
  [`ORIGINS.md`](ORIGINS.md)).
- The import was specialized to Qwen3-TTS. Vocello retains `MLXAudioCore`, the Mimi subset of
  `MLXAudioCodecs`, `MLXAudioTTS` and product-owned Qwen3 tests, and adds the `VocelloQwen3Core`
  facade and `MLXAudioMark`. STT, STS, VAD, LID, G2P, UI and tools, non-Qwen TTS models and non-Mimi
  codec families are outside the package.

## Tracked upstreams

All three were last reviewed in the ER-13 model research (dated 2026-10-16; `LINEAGE.json` records
the mlx-audio-swift review point on 2026-10-17).

| Upstream | Role | Reviewed head |
|---|---|---|
| [`Blaizzy/mlx-audio-swift`](https://github.com/Blaizzy/mlx-audio-swift) | origin of this package | `dbe5eaac964e8257785f9d015c81f819a38016a8` (v0.1.5) |
| [`Blaizzy/mlx-audio`](https://github.com/Blaizzy/mlx-audio) (Python) | the port mlx-audio-swift follows; source of several fixes | no head recorded; the latest commit the review cites is `c4d29e6` (2026-10-07) |
| [`QwenLM/Qwen3-TTS`](https://github.com/QwenLM/Qwen3-TTS) (`qwen_tts`) | the official reference implementation | `022e286b98fbec7e1e916cb940cdf532cd9f488e` (2026-03-17), its last commit |

The previous mlx-audio-swift review point was `d302a5c6` (v0.1.3) on 2026-07-14. Nothing from
v0.1.4 or v0.1.5 was ported. vLLM-Omni was also read for its prompt-mode defaults and missing-EOS
safeguards; it is a reference, not a tracked upstream.

## Disposition at the 2026-10-17 review

From section 6 of the
[ER-13 model research](../../docs/audits/2026-10-17-qwen3-tts-model-research.md#6-ports-and-changes-since-the-fork),
updated for what shipped since. The parity items (A-n, D-n) are tracked in the model guide's parity
ledger ([`qwen3-tts-guide.md`](../../docs/reference/qwen3-tts-guide.md)). The leak row and the Mimi
rotary row were corrected on 2026-11-11 against the
[counter-verification review](../../docs/audits/2026-11-11-qwen3-tts-quality-report-review.md).

| Upstream change | Vocello |
|---|---|
| mlx-audio-swift `dbe5eaa` (v0.1.5): mlx-swift 0.32.3 / mlx-swift-lm 3.32.3 | pins match since CONV-21 (2026-10-16), moved independently |
| mlx-audio-swift `dbe5eaa`: range slices replace the scalar gather in RVQ decode and MRoPE | not ported (ER-08, ER-12) |
| mlx-audio-swift `dbe5eaa`: `streamingStep` evaluates before `sending` | not ported |
| mlx-audio-swift PR #270 (open): non-streaming text for CustomVoice and VoiceDesign | = D1; adopted for single takes 2026-10-20 (RF-21), long-form segments keep streaming text (RF-18) |
| mlx-audio-swift PR #286 (still open on 2026-11-11): stop the per-load initialization-graph leak. Its 110 MB figure was self-reported on Qwen3-ASR 4-bit, not on a TTS model | applies to Vocello's quantized load; not ported, and porting it is not the route. ml-explore/mlx pull request 4710 closed unmerged on 2026-10-19, and an MLX maintainer pointed to pull request 4453 ("Break the sibling cycle when an array is released by assignment", merged 2026-09-11) as the fix. The pinned MLX core is 0.32.2 (released 2026-08-25, inside mlx-swift 0.32.3) and does not contain it; the first MLX release after the merge is 0.32.3 (2026-09-29). The fix arrives with a pin move, which needs the maintainer's authorization (ER-06, ER-07) |
| mlx-audio `6549fc2`: adds the Mimi encoder with `rope_traditional=False` from the start; it is not a fix of a measured defect | Vocello still applies the adjacent-pair convention by default, as mlx-audio-swift `main` does (A-02, ER-04, with G-03's version bump); since 2026-11-11 `QWENVOICE_ENCODER_ROTARY=split-half` selects the reference convention in a diagnostics build (CODEC-002), pending the clone screen (RF-52). Measured on 2026-11-11: the stored codes match the reference encoder's on 31% of codes, and a pre-screen found no detectable effect on clone output |
| mlx-audio `6549fc2`: EOS kept after top-k/top-p | inherited, then removed on 2026-10-20 (D2) |
| mlx-audio `6549fc2`: ICL repetition-penalty floor 1.5 | not adopted; 1.05 is the reference's value |
| QwenLM reference: the clone reference is encoded as it is | Matches since 2026-11-11: the clone screen's rule `reference-padding-none` adopted encoding the reference unpadded (A-12, RF-52; conditioning version `icl-ref-unpadded-v3`); `QWENVOICE_REFERENCE_PADDING=half-second` restores Vocello's earlier 0.5 s of zeros in a diagnostics build (CLONE-003) |
| QwenLM reference: an ICL take decodes `ref_code + generated` and drops the reference's share of the samples | Matches since 2026-11-12: streamed clones decode the reference codes first and keep none of their samples, as the quality-first path does (A-04, CLONE-004; the clone screen's rule `clone-decoder-history-primed-confirm` adopted it); `QWENVOICE_CLONE_DECODER_HISTORY=cold` restores the cold decoder in a diagnostics build |
| QwenLM reference: ICL joins the reference transcript and the target text with no separator | Matches for a target whose first letter is Han or kana since 2026-11-12 (the `clone-cjk` screen's rule `icl-target-space-unspaced-scripts` adopted it, A-11, CLONE-005); every other target keeps one leading space, a fix for French first words that glued to the transcript; `QWENVOICE_ICL_TARGET_SPACE=every-target` puts it before every target again in a diagnostics build (RF-52) |
| QwenLM reference: the clone reference is conditioned on as given | Matches by default; since 2026-11-12 `QWENVOICE_REFERENCE_EDGES=trimmed` trims a transcript-backed reference's silent edges and fades it in a diagnostics build (G-07, CLONE-006), decided by the clone screen's rule `reference-edges-trimmed` (RF-52) |
| QwenLM reference: the model runs unquantized | Vocello's Speed artifacts quantize the whole talker, code predictor included, to 4 bits (the text embedding at 8); since 2026-11-12 `QWENVOICE_CODE_PREDICTOR_BITS=8` takes the code predictor from the installed 8-bit sibling of the same model in a diagnostics build (QUANT-001), so its speed and similarity can be measured before any artifact is made (RF-55) |
| QwenLM reference: the tokenizer decoder applies its 72-frame sliding window in every layer (`create_sliding_window_causal_mask`) and decodes in 300-frame chunks with 25 frames of left context | Vocello's decoder attends to the whole take (A-03); since 2026-11-11 `QWENVOICE_DECODER_WINDOW=on` applies the window in a diagnostics build (CODEC-003), pending a screen of long takes (RF-54) |
| mlx-audio `d2d02bf` (MA#882): EOS filtered like any token | matched since 2026-10-20 (D2) |
| mlx-audio `a730a68`: temperature before top-p/min-p | ported |
| mlx-audio `90ee81f`: fixes a float32 speaker embedding promoting the prefill and KV to float32 | not affected: Vocello casts the embedding at prefix construction |
| mlx-audio `c4d29e6`: fixes the transposed-conv bias being added twice at streaming chunk boundaries | not affected: input-side overlap-and-discard |
| QwenLM `5f8581d` and `6cafe55`: right-only transposed-conv trim; −1 padding and `> -1` length | matched; the dead legacy `decode` still counts `> 0` (A-22) |

Never infer parity from matching filenames, and never treat a newer upstream implementation as
equivalent without the relevant deterministic and benchmark evidence.
