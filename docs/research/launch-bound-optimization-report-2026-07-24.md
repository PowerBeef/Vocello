# Vocello Optimization: Launch-Bound Decoding, Memory Efficiency, and Quality Harness for Qwen3-TTS on MLX

> **Imported research snapshot (2026-07-24).** Converted 2026-07-25 from the external PDF
> report into the repository so corrections and review history stay tracked. The 2026-07-25
> counter-verification grounded every claim in the tree (three parallel code audits) and
> re-verified the external sources (repositories, papers, release notes, pinned package
> checkouts). Contradicted or superseded claims carry inline **Editor's note (2026-07-25)**
> blocks; the notes are the current reading, the surrounding text is the imported snapshot.
> Verification summary and the resulting staged plan:
> [`docs/reference/optimization-report-review-2026-07-25.md`](../reference/optimization-report-review-2026-07-25.md).
> Current phase status remains [`config/runtime-refactor-contract.json`](../../config/runtime-refactor-contract.json).

## TL;DR (imported)

The single highest-leverage move is to attack kernel-launch overhead directly: the closest
analog project (faster-qwen3-tts) proved Qwen3-TTS decode is launch-bound — "A single step
involves ~500 small CUDA kernel launches with Python overhead between them. The GPU spends
more time waiting for the next kernel than computing" — and that static-shape KV caches +
graph capture unlocked "RTF 5.6 on an RTX 4090 and RTF 4.2 on an H100 … with zero custom
attention code," while torch.compile gave zero speedup because dynamic KV-cache shapes defeat
the compiler. On MLX the equivalent levers are fixed-shape (RotatingKVCache) buffers +
mx.compile of the decode step + async_eval pipelining, with the code-predictor/subtalker loop
as the #1 target (it was 190ms→26ms, the biggest single win in the reference project).

Memory headroom on the 8GB floor and the 3.3GB iPhone clone peak is best won by
mixed-precision quantization (8-bit embeddings/lm_head + 4-bit layers, group-size sweeps,
DWQ/AWQ calibration) and hybrid KV quantization (quantize only older entries via
quantizedKVStart) rather than the blanket 8-bit KV cache already measured and rejected (271MB
saved but −8.6% RTF).

Delivery quality is best improved by an on-device objective metric harness (UTMOS/UTMOSv2 +
WavLM/ECAPA speaker-similarity + ASR-WER, ideally anchored by TTSDS2) to replace the LLM
listening pass, plus inference-time long-form prosody carryover (MagpieTTS-LF-style stateful
context); classifier-free guidance — the biggest instruction-adherence lever elsewhere — is
not directly usable because the shipped Qwen3-TTS checkpoint was not trained with condition
dropout.

> **Editor's note (2026-07-25).** Three TL;DR premises need correction against the tree.
> (1) There is no LLM listening pass to replace: the external-model (`agy`) judge was retired
> 2026-06-14 after flipping verdicts on byte-identical audio (`benchmarks/OPTIMIZATION.md`
> §I.3); only an optional non-blocking human annotation remains, so an objective harness
> would be net-new, not a replacement. (2) `maybeQuantizeKVCache(kvBits:kvGroupSize:quantizedKVStart:)`
> and `WiredMemoryTicket` are already available on the pinned mlx-swift-lm 2.30.6 — no
> migration needed — but `quantizedKVStart` delays whole-cache quantization onset; it does
> not keep recent entries fp16 afterward. (3) The Mimi codec decoder ships fp32 (682 MB
> speech tokenizer, zero quantized tensors), not fp16 — the precision lever is larger than
> stated, in the opposite direction.

## Key findings (imported)

1. **The launch-bound ceiling is real and has a proven fix pattern.** faster-qwen3-tts
   (Andres Marafioti, ~1.1k stars) documents Qwen3-TTS-12Hz decode as bottlenecked by
   kernel-launch overhead ("~500 small CUDA kernel launches with Python overhead between
   them"), with the GPU idle waiting on the CPU. Their fix — StaticCache (pre-allocated
   fixed-size KV, in-place index_copy_) wrapped in torch.cuda.CUDAGraph — "unlocked RTF 5.6
   on an RTX 4090 and RTF 4.2 on an H100 — with streaming support — with zero custom
   attention code" (streaming time-to-first-audio 152ms on the 4090; on Jetson Orin the same
   metric "drops from 2.6 seconds to 556ms," with RTF from 0.175 to 1.57). Critically: torch.compile gave
   "zero speedup — dynamic KV-cache shapes defeat the compiler," attention-backend choice
   (eager/SDPA/FA2) was "all identical RTF," and hand-fused RMSNorm (8.4×)/SiLU (2.2×)
   kernels netted only 1.25× end-to-end because those ops are ~4% of compute. This exactly
   matches Vocello's profile (graph-build windows GPU-IDLE, "graph capture/compile ceiling").

   > **Editor's note (2026-07-25).** Verified against the source blog and README, quote by
   > quote, including the report's own caveat that the blog and README carry different runs
   > (4090 0.6B RTF 5.56 vs 4.78). The Vocello profile match is exact: §H P0 re-capture
   > (2026-07-24) measures whole-generation GPU busy ~47%, eval-flush window ~55%, "still
   > launch/CPU-bound (« 80%)".

2. **MLX has no CUDA-Graph-style capture/replay; its equivalent is mx.compile + static
   shapes + async_eval.** MLX generates graphs dynamically and relies on lazy evaluation and
   JIT kernel fusion (mx.compile) to reduce launch count, plus async_eval to overlap CPU
   graph-building with GPU execution. The corollary of finding #1 is decisive: mx.compile
   will only help the decode loop if input shapes are held constant, which requires a
   fixed-shape KV cache (mlx-swift-lm's RotatingKVCache with a bounded window, or a padded
   static cache) so the compiled graph is not invalidated every step.

   > **Editor's note (2026-07-25).** Directionally correct and the report's most valuable
   > synthesis. Tree grounding: `compile()` is already used for the talker/code-predictor
   > SwiGLU activations (shapeless), a larger quantized-MLP compile measured −5% at 0.30.6
   > (`benchmarks/OPTIMIZATION.md` §F WS0b) because quantized parameters were marshalled per
   > call, and the rotating cache is merged but inert (env-only; generation stops one token
   > before the first rotation at the 2048-token cap). The talker's KV operand grows every
   > step (`KVCacheSimple` block growth with a growing slice), so a compiled talker step
   > would indeed recompile per token today. The code predictor is the compile-friendly
   > target the report wants: its cache is trimmed to zero every frame, so its shapes cycle
   > through a bounded set of 16 — no static-cache rework needed to make it compile-stable.

3. **The code predictor / subtalker (MTP over the residual RVQ codebooks) is the dominant
   launch contributor.** Per faster-qwen3-tts, "Qwen3-TTS runs two autoregressive
   transformers per decode step: Talker (28 layers): generates the first codebook token from
   text; Code Predictor (5 layers): generates 15 additional codebook tokens." In the
   reference project the predictor's 15-step loop was the single biggest cost (190ms→26ms
   after graph capture) vs talker 75ms→12ms. This is where compile/fusion effort pays off
   most.

   > **Editor's note (2026-07-25).** Confirmed, and the tree agrees on the structure with a
   > correction of scale: each of the 15 sequential iterations is a full 5-layer transformer
   > pass plus a separate unbatched `lmHead[i]` projection plus a full sampler call — far
   > heavier than "15 small matmuls." §H P0 (2026-07-24): the code-predictor loop is 15.4%
   > of generation wall at 0.7–0.9% GPU busy — almost pure launch overhead.

4. **Version pins are leaving concrete perf on the table, but a low-risk intermediate
   exists.** mlx-swift-lm 2.31.3 (the last 2.x tag) uses mlx-swift 0.31.3 and carries SDPA
   improvements (masking, T_q≠T_kv), faster quantize/dequantize, and tensor-core QQMM —
   without the 3.x breaking changes (which decouple the tokenizer/downloader packages and
   change the SDPA mask-mode API). 3.x additionally exposes wiredMemoryTicket, KV-cache
   serialization fixes, and a generate(...draftModel:draftCache:numDraftTokens:)
   speculative-decoding entry point.

   > **Editor's note (2026-07-25).** Release-line facts verified (2.31.3 is the last 2.x
   > tag; 3.x decouples tokenizer/downloader and adds the draft-model path). Two
   > corrections: `WiredMemoryTicket` already exists on the pinned 2.30.6
   > (`MLXLMCommon/ModelContainer.swift`), and so does
   > `maybeQuantizeKVCache(...quantizedKVStart:)` — neither needs any bump. Any pin move
   > remains gated: `fixed-mlx-dependency-pins-during-convergence` is a contract invariant
   > and the 0.31.x bump is a standing do-NOT during convergence (`benchmarks/OPTIMIZATION.md`
   > §E), so this is a throwaway-branch experiment with full matrix + QC re-validation, not
   > a default step.

5. **Speculative decoding is viable for codec TTS and partially already plumbed.** Published
   speech-specific work (Apple's Principled Coarse-Graining; MTP+speculative TTS at 4–5×
   speedup) shows draft-model acceleration works when acceptance is relaxed to
   acoustically-interchangeable token groups. mlx-swift-lm's generate loop already accepts a
   draft model — but for a launch-bound (not compute-bound) system, speculative decoding's
   benefit is muted, so it's a lower priority than graph capture.

6. **Classifier-free guidance is blocked without retraining.** CFG is the strongest
   instruction-adherence lever in other codec-LM TTS (MaskGCT sets "guidance scale and the
   classifier-free guidance rescale factor … to 2.5 and 0.75, respectively"), but it
   requires the model to have been trained with condition dropout so it has an unconditional
   mode — MaskGCT "randomly drop[s] the prompt with a probability of 0.15 to model the
   probability distribution pθ(X) without the prompt." The shipped Qwen3-TTS checkpoint was
   not trained this way, and CFG doubles per-step forward passes (worst case for a
   launch-bound loop).

7. **An on-device objective quality harness is feasible and would replace the LLM listening
   pass.** UTMOS/UTMOSv2, DNSMOS, NISQA, and TTSDS2 are all publishable. TTSDS2 (Minixhofer
   et al., SSW 2025) shows the most consistent human-MOS correlation: "across all 12
   domain–score pairs, TTSDS2 is the only objective metric that achieves a Spearman
   correlation above 0.50 with respect to every one of the subjective scores (mean 0.67),"
   based on 200 raters scoring 20 voice-cloning models — while UTMOS was unreliable in the
   wild (ρ as low as −0.12 to −0.26 on the WILD domain). Speaker similarity via
   WavLM/ECAPA-TDNN and intelligibility via ASR-WER round out a fully automatable rubric.

   > **Editor's note (2026-07-25).** TTSDS2/UTMOSv2 claims verified against the SSW 2025
   > paper and the VoiceMOS 2024 results. See the TL;DR note: there is no LLM listening pass
   > left to replace, and the repository previously surveyed and rejected neural quality
   > judges for the app itself (`docs/reference/prosody-qa-research.md`); the viable shape
   > is a dev-lane (scripts/bench) harness, which folds into the open phase 12 typed
   > quality-registry work.

## PART 1 — Performance (launch-bound), imported items P1–P8

- **P1** Make the decode step compile-stable with a fixed-shape KV cache, then mx.compile
  it. [today, on pins] — highest expected gain. Falsifiable via warm RTF matrix cells and
  GPU-busy% (currently 31–47% whole-generation; eval-flush ceiling ~55%).
- **P2** Pipeline the decode loop with async_eval on a dedicated GPU stream; ensure no
  synchronous eval (eval, item(), tolist(), printing) touches in-flight arrays.
  mlx-swift-lm's TokenIterator already uses asyncEval() — mirror its discipline.
- **P3** Collapse the subtalker/code-predictor loop into as few launches as possible; a
  sibling fork (rekuenkdr/Qwen3-TTS-streaming) reports capturing the entire 31-step codebook
  loop as one replay for 2.15× per-frame (12.94ms vs 27.88ms).
- **P4** Vectorize any per-token host-side work (repetition penalty, sampling bookkeeping);
  audit the sampler scratch path for remaining per-step host reductions.
- **P5** Codec decoder — keep it fp16, chunked, and overlapped on a separate stream; keep
  the last two decoder layers in full precision if ever quantized (T-Mimi).
- **P6** Reduce time-to-first-token via chunked prefill (design first-packet latency is 97ms
  0.6B / 101ms 1.7B; first-chunk frame constants Custom 7, Design 7, Clone 7 already lean
  this way).
- **P7** Bump to mlx-swift-lm 2.31.3 / mlx-swift 0.31.3 for SDPA + quantize kernels
  [intermediate migration, NOT full 3.x].
- **P8** Speculative / multi-token decoding [requires 3.x for the built-in path; or custom;
  PCG acceptance at Acoustic Similarity Group level].

> **Editor's note (2026-07-25).** Grounding for this part: per-token cadence is one blocking
> `eval` plus two separate `.item()` scalar reads (token id, EOS) per token, plus an
> `asArray` PCM copy per chunk; zero `Stream`/`new_stream` usage anywhere (everything on the
> default GPU stream); the single `asyncEval` on the audio chunk is immediately re-synced on
> the shipping path by the materialized `[Float]` copy. P4's premise is already satisfied:
> the repetition penalty is fully on-device (takeAlong/which/putAlong) and the per-generation
> sampler scratch removed ~17K allocations (§H P2). P5's premise is inverted: the codec runs
> fp32 today, `chunkedDecode(leftContextSize: 25)` exists but only on the non-streaming
> batch path, and codec decode is serial with the talker loop. P6's 7/7/7 first-chunk
> constants and one-shot (unchunked) prefill are confirmed.

## PART 2 — Memory efficiency, imported items M1–M6

- **M1** Mixed-precision quantization beyond the flat 4-bit/8-bit split (8-bit
  embeddings/lm_head + 4-bit layers, group-size tuning, DWQ/AWQ/GPTQ, sensitivity-driven
  recipes; keep speaker encoder, lm_head, codebook embeddings, final codec-decoder layers at
  higher precision).

  > **Editor's note (2026-07-25).** The shipped artifacts are uniform affine group-64 4-bit
  > (Speed) / 8-bit (Quality) with **no** per-layer entries — and the actual precision map is
  > the reverse of the report's assumption: the 622 MB text embedding and 126 MB of codec
  > embeddings ship **unquantized BF16** inside the "4-bit" file (more than half of the
  > 1.65 GB talker file is BF16), while `codec_head` and all 15 `lm_head` projections ARE
  > quantized. The loader already supports `perLayerQuantization`, unused by every shipped
  > config. The concrete openings are therefore: quantize the text embedding
  > (QuantizedEmbedding, ~300 MB saving at 8-bit), and evaluate a bf16 speech tokenizer
  > (682 MB fp32 today) — both offline conversions with new catalog identities.

- **M2** Hybrid / windowed KV quantization via quantizedKVStart to dodge the −8.6% RTF
  penalty; community fused quantized-SDPA (mlx-qsdpa) reports 1.7×; RotatingKVCache
  quantization is unimplemented upstream (OptiQ ships a Python fill-in).

  > **Editor's note (2026-07-25).** The −271 MB / −8.6% measurement and rejection are
  > documented in four places and remain a standing do-NOT ("don't quantize TTS KV"). The
  > existing env knob (`QVOICE_TALKER_KV_QUANT`) quantizes from step 0;
  > `maybeQuantizeKVCache(quantizedKVStart:)` exists on-pin but delays onset of whole-cache
  > quantization rather than keeping a recent fp16 window. With per-segment fresh contexts
  > and the ≤300-unit segment budget, no shipping tier has a KV-driven RAM emergency; this
  > stays parked unless segment budgets grow.

- **M3** In-memory weight sharing across custom/design/clone variants (load the shared
  backbone once, materialize only variant-specific tensors).

  > **Editor's note (2026-07-25).** Premise refuted: CustomVoice, VoiceDesign, and Base are
  > three genuinely distinct checkpoints (different repos, revisions, and tensor digests),
  > and exactly one model is resident at a time (a mode switch is a full unload+reload
  > through `MLXModelLoadCoordinator`). The valid RAM analog is the shared 682 MB fp32
  > speech tokenizer, byte-identical across all six artifacts and already hard-linked on
  > disk — but re-materialized from scratch on every model load. Keeping it resident across
  > mode switches is exactly open **phase 9 (runtime component reuse)**.

- **M4** Cache-limit and wired-memory policy tuning for the 8GB floor (256MB limit;
  wiredMemoryTicket; llama.cpp residency-set anecdotes).

  > **Editor's note (2026-07-25).** Tier table confirmed: 256 MB floor-8GB, 512 MB mid-16,
  > 1 GB high, 128 MB iPhone (single iPhone tier); no hard `Memory.memoryLimit` anywhere in
  > production (earlier caps caused spurious OOM downgrades and were reverted). No wired
  > memory / residency API is used anywhere today; `WiredMemoryTicket` is available on-pin.

- **M5** Clone-path peak reduction (3.3GB iPhone): (a) x-vector-only conditioning as a
  low-memory mode; (b) free conditioning/reference tensors after prefill; (c) windowed KV
  quant on the reference portion.

  > **Editor's note (2026-07-25).** (a) already ships: clone conditioning is typed
  > transcript-backed ICL vs genuine audio-only x-vector, contract-enforced with distinct
  > cache identities. (b) is a real opening: the engine actor deliberately retains the whole
  > clone prompt (including reference codec tokens) for the handle's lifetime, with capacity
  > 1; the 3.3 GB peak figure is confirmed (3,332 MB, canonical clone band 3.02–3.52 GB,
  > zero trims against ~6 GB entitled).

- **M6** iOS memory ceiling reality (increased-memory-limit semantics,
  os_proc_available_memory at runtime, MetricKit MXAppExitMetric, keep retire-on-idle +
  clear-cache-on-chunk).

  > **Editor's note (2026-07-25).** Every item on this list is already implemented: the
  > entitlement is on both shipping iOS configs and CI-enforced at archive time;
  > `os_proc_available_memory()` feeds the pressure bands; MetricKit exit summaries are
  > collected as delayed field evidence; idle unload is 30 s on iPhone (120 s on the Mac
  > floor tier) and clear-on-chunk is on for every constrained tier. The 900-character limit
  > is a delivery-quality gate (validated segment ceiling), not a memory gate.

## PART 3 — Delivery accuracy & quality, imported items Q1–Q7

- **Q1** Objective metric harness (UTMOS/UTMOSv2, WavLM/ECAPA SIM, ASR-WER, TTSDS2 anchor);
  treat scores as in-domain deltas, not certification.
- **Q2** Long-form prosody consistency via inference-time stateful carryover
  (MagpieTTS-LF): carry a bounded slice of the previous segment's codec/KV context into the
  next segment's prefill, and feed previous+next sentence text as planning context.
- **Q3** Instruction engineering: concrete acoustic descriptors beat persona framing;
  negative constraints endorsed; duration instructions have no effect; 0.6B "consistently
  failed to capture emotion" (favor 1.7B); no per-segment inline emotion.
- **Q4** Voice-cloning quality levers: 5–15s reference, ~6–10s sweet spot; reference
  quality dominates; adopt the 0.5s trailing-silence append before encoding the reference
  (deterministic fix for clone-start phoneme artifacts); transcript accuracy matters in ICL
  mode.
- **Q5** Sampling: official defaults already won; repetition penalty 1.05–1.1 is "the one
  lever you haven't tested."
- **Q6** CFG for instruction adherence — blocked without retraining.
- **Q7** Alternative checkpoints / fine-tunes (25Hz DiT variant heavier; 1.7B upgrade on
  high tiers; single-speaker SFT/LoRA for accent).

> **Editor's note (2026-07-25).** Q2's fresh-context premise is confirmed (each long-form
> segment is an independent generate call; continuity is sub-seeds + pause budget + loudness
> match + edge trim/fades; the assembler's boundary-jump metric is computed but does not
> gate). Q3 is confirmed aligned, except no duration-instruction guardrail exists (custom
> delivery text reaches the model unfiltered beyond a 500-char cap). Q4's silence append is
> genuinely absent (only STFT reflect padding exists) — a near-free adoption; the reference
> window is tiered 10/30/60 s with the in-app recorder enforcing 10–20 s. Q5 is wrong on the
> premise: Vocello ships the official defaults **including repetition penalty 1.05** on the
> talker (subtalker deliberately unpenalized); the untested axis is only raising it toward
> 1.1 against dropout/stutter counts. Q7's 1.7B recommendation is moot — Vocello is
> 1.7B-only by maintainer decision (0.6B ruled out; Voice Design requires 1.7B).

## Recommendations (imported)

Stage 1 — do now, on the current pins: P1+P2+P3 (fixed shapes → compile → async pipeline,
instrument per-component timing and GPU-busy%; proceed if GPU-busy% rises toward 55%+ and
warm RTF improves ≥10% on clone/long); P4 and Q4 near-free; Q1 harness as the regression
gate; M2 hybrid KV on long-form cells; M1 mixed 4/8 variant offline.

Stage 2 — targeted migration (only if Stage 1 plateaus): P7 pins to 2.31.3/0.31.3; M3/M5
in-memory sharing and x-vector-only low-memory clone mode.

Stage 3 — research bets: P8 speculative/PCG; Q2 stateful carryover; Q5 repetition-penalty
A/B; Q7 1.7B/LoRA; Q6 CFG parked until a condition-dropout checkpoint exists.

Metrics that change the plan: post-P1 GPU-busy% >85% → pivot to quantization/speculative;
<55% → keep attacking launch count.

> **Editor's note (2026-07-25).** The counter-verified staging (with the corrections above
> folded in, phases 9/12/13 integrated, and contract invariants respected) supersedes this
> section; see
> [`docs/reference/optimization-report-review-2026-07-25.md`](../reference/optimization-report-review-2026-07-25.md).

## Caveats (imported, all confirmed sound)

- faster-qwen3-tts is CUDA/NVIDIA-only; its diagnosis transfers to MLX, its magnitudes do
  not (MLX has no CUDA-Graph capture/replay).
- M2 revisits a documented rejection on new API evidence; Q5 is a new axis, not one of the
  three rejected sampling recipes (editor: partially — the penalty itself already ships).
- Objective metrics ≠ human MOS; UTMOS-family predictors are English/in-domain-biased.
- CFG and better instruction adherence are largely gated on training.
- Every pin migration must be re-validated against the full gated RTF matrix and
  reference-free QC before shipping.
- Community/secondary numbers (sampling params, per-component timings, sibling-fork replay
  figures) are directional; verify on the harness.
