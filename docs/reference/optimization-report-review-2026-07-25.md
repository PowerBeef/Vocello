# Optimization report review — counter-verification and staged plan (2026-07-25)

> Review of the imported research snapshot
> [`docs/research/launch-bound-optimization-report-2026-07-24.md`](../research/launch-bound-optimization-report-2026-07-24.md)
> ("Vocello Optimization: Launch-Bound Decoding, Memory Efficiency, and Quality Harness for
> Qwen3-TTS on MLX"). Every claim was grounded in the tree by three parallel code audits
> (decode loop, memory policy, quality/status) and the external sources were independently
> re-verified (repositories, papers, release notes, and the pinned package checkouts on
> disk). This document records the verdicts and the resulting staged implementation plan,
> which folds the open runtime-convergence phases 9, 12, and 13.
> [`config/runtime-refactor-contract.json`](../../config/runtime-refactor-contract.json)
> remains the status authority; `benchmarks/OPTIMIZATION.md` remains the measurement log.

## Headline verdict

The report's central thesis is **correct and matches Vocello's own measurements verbatim**:
the decode loop is launch/CPU-bound (§H P0 re-capture 2026-07-24: whole-generation GPU busy
~47%, eval-flush window ~55%, code-predictor loop 15.4% of wall at under 1% GPU busy), the
CUDA analog project's diagnosis transfers, and the remaining RTF headroom sits behind
compile/pipelining work, not more kernel fusion. Its external citations are genuine and
fairly characterized — the same result as the 2026-07-22 corpus review.

The report's defect pattern is also the same as last time: **staleness against a
fast-moving tree, plus a few premises the code refutes.** Six of its recommendations are
already shipped (x-vector-only clone mode, on-device repetition penalty at the official
1.05 default, vectorized sampler scratch, os_proc_available_memory pressure bands, MetricKit
exit collection, the increased-memory-limit entitlement), one is structurally inapplicable
(cross-variant backbone sharing — the three modes are genuinely different checkpoints and
only one is ever resident), and two of its "requires migration" flags are wrong
(`maybeQuantizeKVCache(quantizedKVStart:)` and `WiredMemoryTicket` are both on the pinned
mlx-swift-lm 2.30.6). Its two best genuinely-new items are near-free: the 0.5 s
trailing-silence append to clone references, and the observation that the code predictor is
compile-friendly today because its per-frame cache reset gives it a bounded shape set.

## Claim-by-claim verdicts

### Performance (P1–P8)

| Item | Claim | Verdict | Grounding |
| --- | --- | --- | --- |
| P1 | Decode is launch-bound; fixed shapes then compile | **Thesis confirmed; mechanism needs care** | §H P0: GPU busy 31–37% → ~47% after P2/P3, eval-flush ~55%, "still launch/CPU-bound". Talker KV is upstream `KVCacheSimple` (256-step block growth, growing slice) so per-step shapes DO vary; the rotating cache is merged but inert (env-only; token cap 2048 stops one token before first rotation). Whole-step compile was measured −5% at 0.30.6 (§F WS0b) — but that variant marshalled quantized MLP params, not a static-shape step. |
| P2 | async_eval pipelining on a dedicated stream | **Confirmed absent; implementable on-pin** | One blocking `eval` per token plus two `.item()` reads (token id, EOS); zero `Stream` usage anywhere; the single `asyncEval(audioChunk)` is re-synced ~19 lines later by the shipping `[Float]` materialization. The pinned mlx-swift-lm's own `TokenIterator` demonstrates the asyncEval discipline. |
| P3 | Code-predictor loop is the #1 launch contributor | **Confirmed, heavier than stated** | 15 sequential 5-layer transformer passes + 15 unbatched `lmHead[i]` projections + 15 sampler calls per frame; CP cache trimmed to zero each frame (bounded 16-shape cycle → compile-friendly). §H P0: 15.4% of wall, 0.7–0.9% GPU busy. |
| P4 | Vectorize per-token host work | **Already done** | Repetition penalty is on-device (`takeAlong`/`which`/`putAlong`); per-generation sampler scratch (§H P2) removed ~17K allocations. Remaining host syncs are the two `.item()` reads + per-chunk `asArray`, which belong to P2. |
| P5 | Codec fp16, chunked, overlapped | **Inverted premise** | The speech tokenizer ships **fp32** (682 MB, zero quantized tensors; DecoderRMSNorm even upcasts). `chunkedDecode(leftContextSize: 25)` exists only on the non-streaming batch path; streaming uses persistent per-layer state with 1-sample upsample left context. Codec decode is serial with the talker on the default stream. |
| P6 | Chunked prefill / time-to-first-audio | **Grounded** | Prefill is one-shot (no chunked-prefill code); first-chunk constants are 7/7/7 as claimed (0.6 s floor × 12.5 Hz), later chunks 7/14/14. |
| P7 | Bump pins to 2.31.3 / 0.31.3 | **Accurate facts; gated by contract** | 2.31.3 is the last 2.x tag; but `fixed-mlx-dependency-pins-during-convergence` is a contract invariant and §E records the bump as a standing do-NOT. Throwaway-branch experiment only, with full matrix + QC. |
| P8 | Speculative / PCG decoding | **Correctly deprioritized** | PCG (arXiv:2511.13732, ICASSP 2026) verified; needs 3.x or custom; muted while launch-bound. Park. |

### Memory (M1–M6)

| Item | Claim | Verdict | Grounding |
| --- | --- | --- | --- |
| M1 | Mixed-precision quantization | **Right lever, wrong map** | Shipped artifacts are uniform affine group-64 (4-bit Speed / 8-bit Quality) with no per-layer entries; the 622 MB text embedding + 126 MB codec embeddings are **unquantized BF16** inside the "4-bit" file (over half the talker file is BF16) while `codec_head`/`lm_head` ARE quantized. Loader already supports `perLayerQuantization` (unused). Real openings: QuantizedEmbedding for the text embedding; bf16 speech tokenizer (fp32 today). |
| M2 | Hybrid KV quant via quantizedKVStart | **On-pin, but semantics differ; stays parked** | −271 MB / −8.6% rejection documented in four places + raw A/B rows; "don't quantize TTS KV" is a standing do-NOT. `maybeQuantizeKVCache(quantizedKVStart:)` exists on 2.30.6 but delays whole-cache quantization onset — it does not keep a recent fp16 window. With per-segment fresh contexts and the ≤300-unit segment budget there is no KV RAM emergency (iPhone clone peaks 3.02–3.52 GB, 0 trims, ~6 GB entitled). |
| M3 | Share backbone weights across variants | **Not applicable; redirects to phase 9** | Three genuinely distinct checkpoints (distinct repos/revisions/digests); strictly one resident (mode switch = full unload+reload). The valid RAM analog is the byte-identical 682 MB fp32 speech tokenizer, hard-linked on disk but re-materialized every model load — exactly open phase 9. |
| M4 | Cache-limit + wired-memory tuning | **Confirmed facts; minor lever** | 256 MB / 512 MB / 1 GB / 128 MB per tier; no hard memoryLimit in production (earlier caps reverted for spurious OOM downgrades); no wired/residency API used anywhere; `WiredMemoryTicket` available on-pin (report's 3.x flag wrong). |
| M5 | Clone peak reduction | **(a) shipped; (b) real opening** | x-vector-only conditioning is a shipping typed mode. The engine actor deliberately retains the full clone prompt (incl. reference codec tokens) for the handle lifetime (capacity 1); 3.3 GB peak confirmed (3,332 MB). Dropping retained `refCodes` after the conditioning prefix is built is the targeted win. |
| M6 | iOS ceiling hygiene | **Entirely already implemented** | Entitlement on both shipping configs + CI-enforced at archive; `os_proc_available_memory()` feeds pressure bands; MetricKit exit summaries collected (delayed field evidence); idle unload 30 s iPhone / 120 s Mac floor; 900-char limit is a delivery gate, not memory. |

### Quality (Q1–Q7)

| Item | Claim | Verdict | Grounding |
| --- | --- | --- | --- |
| Q1 | Objective harness to replace the LLM listening pass | **Valuable, but net-new; no pass to replace** | The external-model judge was retired 2026-06-14 (verdict flips on byte-identical audio, §I.3); only optional human annotation remains. No neural metric exists anywhere; the repo previously rejected in-app neural judges for footprint. Viable shape: dev-lane scripts harness (speaker-SIM first, MOS-proxy advisory), folded into phase 12's typed registry. TTSDS2/UTMOSv2 external claims verified. |
| Q2 | Long-form stateful carryover | **Premise confirmed; stage carefully** | Fresh context per segment confirmed; continuity is sub-seeds + pause budget + loudness match + edge trim/fades; `maximumSegmentBoundaryJump` is computed by the assembler but never gates. MagpieTTS-LF (arXiv:2606.18485) verified as inference-time-only. Cheap first steps exist before any acoustic carryover. |
| Q3 | Instruction engineering edges | **Aligned; one gap** | Preset canon already uses concrete descriptors + negative constraints with per-preset empirical provenance. No duration-instruction guardrail exists (custom delivery text passes through beyond a 500-char cap). |
| Q4 | 0.5 s reference silence append; trim toward ~10 s | **Genuinely absent; near-free** | No silence padding anywhere in the clone path (only STFT reflect padding). Reference window is tiered 10/30/60 s; in-app recorder already enforces 10–20 s. Upstream applies the append by default. |
| Q5 | Repetition penalty untested | **Premise wrong; narrow axis remains** | Vocello ships the official defaults including repetition penalty 1.05 on the talker (subtalker deliberately unpenalized); official default temp is 0.9. Untested axis: raising toward 1.08–1.15 against dropout/stutter counts, per the community troubleshooting band. |
| Q6 | CFG blocked without retraining | **Confirmed** | MaskGCT params (2.5/0.75, dropout 0.15) verified; park. |
| Q7 | Favor 1.7B; LoRA for accent | **Already satisfied / future** | Vocello is 1.7B-only by maintainer decision (0.6B ruled out; Voice Design requires 1.7B). LoRA remains future work. |

## External-source verification

All primary citations check out: faster-qwen3-tts (launch diagnosis, StaticCache+CUDAGraph
RTFs including the blog/README divergence the report itself flags, torch.compile null
result, fused-kernel 1.25× e2e, per-component 190→26 ms / 75→12 ms, x-vector ~10 vs 80+
prefill tokens, silence-append default), rekuenkdr/Qwen3-TTS-streaming (31-step loop as one
replay, 2.15× per-frame), the Qwen3-TTS technical report (12.5 Hz tokenizer, causal ConvNet
decoder, 97/101 ms first packet, 1.7B > 0.6B emotion), TTSDS2 (only metric of 16 with
Spearman >0.50 everywhere, mean 0.67), MagpieTTS-LF, PCG/ASG, MaskGCT CFG parameters,
UTMOSv2, mlx-qsdpa, OptiQ's RotatingQuantizedKVCache (Python-only), and mlx-lm's
DWQ/AWQ/mixed-quant tooling. Corrections found: `WiredMemoryTicket` and
`maybeQuantizeKVCache(quantizedKVStart:)` are already on the 2.30.6 pin; `quantizedKVStart`
is delayed-onset, not an fp16 recency window; official Qwen3-TTS defaults already are
temp 0.9 / repetition 1.05 (so "community consensus temp≈0.8" is a stability recipe, and
the penalty is not an untested lever); the InstructTTSEval-adjacent failure-mode specifics
(duration directives, accent bleed) could not all be independently located and stay
directional.

## Staged implementation plan

Supersedes the imported report's Recommendations section. Folds the open convergence phases
(9, 12, 13), the smaller open threads, and the corrections above. Ordering within a stage is
by expected value per unit risk; every engine-loop change carries the §K lesson — a
fixed-seed QC soak (12/12 clean takes) before it may stay in-tree, because two prior
diagnostic engine-loop edits produced intermittent Fast-QC hard failures.

### Stage 0 — near-free wins (no engine-loop risk beyond QC soaks) — **completed 2026-07-26**

> All four items landed 2026-07-26 (commits `b16167d`, `5fc0f3c`, the delivery-advisory
> commit, `f97598a`). Item 4's A/B kept the 1.05 default (no deterministic-QC win at 1.10).
> Evidence and the pre-existing clone/long dropout-band finding: `benchmarks/OPTIMIZATION.md`
> §L.

1. **Clone reference trailing-silence append (Q4).** Append 0.5 s of silence to the
   reference audio before `speechTokenizer.encode` on the ICL path (upstream applies this by
   default; deterministic fix for clone-start phoneme artifacts). Evidence: fixed-seed
   before/after WAV pairs + WER on clone cells; artifact-rate comparison. Note: changes
   clone prompt identity → prepared-conditioning caches and schema-3 clone artifacts must
   version the change.
2. **Long-form boundary gate (Q2-lite).** The assembler already computes
   `maximumSegmentBoundaryJump`; surface it in evidence and gate it (warn-first) in the
   long-form runners. Zero new measurement code.
3. **Duration-instruction guardrail (Q3).** Advisory detection/rewrite of duration-style
   directives ("finish within N seconds") in custom delivery text before prompt assembly.
4. **Repetition-penalty A/B (Q5, corrected).** Bench-lane A/B of talker penalty 1.05
   (shipped default) vs ~1.10 against dropout-ms/continuity-failure counts at fixed seeds.
   Adopt only on a deterministic-QC win; subtalker stays unpenalized.

### Stage 1 — the launch-bound attack (on current pins; the §H P0 successor program) — **completed 2026-07-26**

> Closed at **net +11% warm RTF, byte-identical output**: P2a-i (fused host syncs +
> pipelined materialization) and P3 (compiled code-predictor step) landed; P2a-ii, P5b,
> and P1b were measured and declined with do-NOT records (§M). Stage-exit GPU-busy
> re-capture: ~47% whole-generation — still launch-bound, so quant/speculative work stays
> parked per the decision metric below.

Instrument first, change second; every step falsifiable against the §H P0 methodology
(Metal System Trace GPU-busy% + warm RTF matrix cells).

1. **Collapse per-token host syncs (P2a).** Fuse the two `.item()` reads (token id + EOS)
   into one transfer; move EOS decision device-side where possible. Then pipeline: keep one
   token step in flight (`asyncEval`) while the next graph builds, double-buffering the
   per-chunk `[Float]` materialization so the lossless-channel contract (materialize before
   the awaited send) is preserved without re-syncing the in-flight step. Success: GPU busy
   >55% whole-generation, warm RTF +≥5% on custom/long.
2. **Compile the code-predictor step (P3/P1a).** The CP is compile-stable today (per-frame
   cache reset → bounded 16-shape cycle; pad to a single shape if compile-cache churn
   shows). Compile the 5-layer forward + head projection per iteration; keep the RVQ
   dependency ordering. Success: CP loop share of wall 15.4% → <8%.
3. **Overlap codec decode on a second stream (P5b).** Move streaming chunk decode to a
   dedicated MLX stream so codec reconstruction overlaps the talker's next-token graph
   build. Success: Audio Chunk Eval window (3.7% of wall) overlapped; earlier first audible
   chunk on the 7-frame first chunk.
4. **Talker static-shape compile experiment (P1b).** Branch-only: padded fixed-size talker
   KV (StaticCache analog with explicit mask, or rotating cache pre-filled to window) +
   compiled step. Proceed past experiment only if compile logging shows no per-step
   recompilation AND warm RTF +≥10% on clone/long with clean QC — the prior −5% compile
   measurement was a different variant (quantized-param marshalling), so this is a genuine
   re-test, not a re-litigation.

Decision metric (adopted from the report, thresholds kept): if post-stage GPU-busy% >85%,
the loop has become compute-bound → quantization/speculative work gains priority; if it
stays <55%, keep attacking launch count before anything else.

### Stage 2 — memory program (folds phase 9) — **completed 2026-07-26, including the 2.2 promotion**

> 2.1 shipped (phase 9 closed: byte-identical switch A/B, memory-qualified on the 8 GB
> floor). 2.2 validated, then **promoted the same day** (maintainer-approved): all six
> artifacts converted with the pinned tooling, uploaded to public `PowerBeef02/<folder>`
> repos, catalog re-pinned as artifactVersion 2026.07.26.1 with fail-closed validation,
> isolated Mac delivery proof, the canonical Mac install upgraded in place, and
> stale-artifact update detection shipped end to end (CLI + macOS/iOS Settings). 2.3
> parked (dtype-independent conv regression; revival via the Stage-4 pin-bump re-test or
> an iPhone measurement). 2.4 declined: the retained clone tensors measure <100 KB and
> `refCodes` is a required per-generation input (the ICL prefix interleaves the target
> text), correcting M5b's premise. Measurements: `benchmarks/OPTIMIZATION.md` §N.

1. **Phase 9: speech-tokenizer runtime reuse (M3 corrected).** Keep the verified,
   byte-identical 682 MB fp32 speech tokenizer resident across mode switches (the RAM
   analog of the shipped disk hard-linking), behind the load coordinator. Isolated A/B on
   the 8 GB floor with memory-qualified evidence, per the phase 9 contract scope
   (decoder/immutable-weight reuse, resource-qualified).
2. **Text-embedding quantization experiment (M1a).** Offline conversion: 8-bit
   QuantizedEmbedding for the 622 MB BF16 text embedding on the Speed artifacts
   (`perLayerQuantization` is already supported by the loader). ~300 MB artifact/resident
   saving if QC holds. New catalog identities → full fail-closed catalog workflow +
   explicit delivery evidence.
3. **Codec bf16 experiment (M1b/P5a).** Half-precision speech tokenizer (keep the final
   two decoder layers fp32 per T-Mimi) — ~340 MB resident saving + bandwidth. Gate on
   fixed-seed QC digests and ASR/prosody gates; this changes bit-exact outputs, so it is a
   promotion-quality decision, not a silent swap.
4. **Clone prompt release (M5b).** Drop retained reference codec tokens once the
   conditioning prefix is built (rebuild path on handle miss), targeting the iPhone clone
   peak band. Respect the epoch-bound handle lifecycle contract.

### Stage 3 — quality harness (folds phase 12, then 13) — **completed 2026-07-26 (two items deliberately deferred)**

> Shipped: fast-depth registry on the shipping finalization path; the standard/canonical
> `deepReport` producer (fail-closed on missing analyzer evidence); per-take prosody gate
> verdicts on the bench sidecar and folded into PASS-only history as machine warnings;
> the typed `languageASR` gate on the iOS lang-bench sentinel; the `longFormContinuity`
> gate derived from v4 assembly evidence; the revision-pinned ECAPA speaker-similarity
> dev-lane metric; and benchmark/history **schema v3** (typed quality identity on every
> generation take; live since 2026-07-29 with the first records committed). Deferred with
> rationale: composed standard/canonical report emission at a lane call site (all
> per-gate evidence already lands typed; the aggregate waits for a consumer) and the
> optional MOS-proxy advisory column.

1. **Phase 12: wire the typed quality registry.** Emit and validate
   `GenerationQualityReport` from a real scheduler; fold persisted-WAV Fast QC into the
   typed `persistedWAV` gate. The registry's 11 gates and measurement keys (incl.
   `boundaryDiscontinuity`, `pitchRangeSemitones`) already exist as foundation-only code.
2. **Speaker-similarity gate (Q1a).** ECAPA/WavLM cosine SIM as a dev-lane (scripts/)
   metric for clone fidelity — the one rubric axis with no coverage today. PASS-only
   publication rules unchanged.
3. **MOS-proxy annotation (Q1b, optional).** UTMOSv2 as an advisory bench-lane column
   (in-domain deltas only, never certification, never a promotion gate). TTSDS2 stays a
   watch item (heavier dependency stack).
4. **Phase 13: benchmark/history v3** once plan/session/quality identities from phase 12
   stabilize — unchanged scope, unblocked by (1).

### Stage 4 — gated migrations and research bets

1. **Pin bump experiment (P7).** mlx-swift-lm 2.31.3 / mlx-swift 0.31.3 on a throwaway
   branch (contract invariant: pins move only with benchmark-gated review), re-validating
   `attentionWithCacheUpdate` routing, the full RTF matrix, and QC. Also the prerequisite
   for re-testing the §E compile ceiling upstream said to re-test at 0.31.x.
2. **Long-form carryover (Q2 full).** History-aware *text* context first (feed adjacent
   sentence text into segment planning — no acoustic risk), then the MagpieTTS-LF-style
   bounded acoustic/KV carryover experiment (interacts with segment memory budgets).
3. **Parked:** P8 speculative/PCG (until compute-bound), Q6 CFG (until a condition-dropout
   checkpoint exists), Q7 LoRA (deployment-specific accent work), M2 KV quantization
   (standing do-NOT; revisit only if segment budgets grow).

### Standing open threads (unchanged, tracked here for completeness)

iOS single-segment regeneration parity (long-form); iPhone-15-Pro memory-profile
diagnostic; 60 Hz-device measurement of the iOS fixed-refresh glass gate; single-take
spoken-text normalization (phase 10 remainder).

## Guardrails

- `fixed-mlx-dependency-pins-during-convergence` (contract invariant) — Stage 4.1 is the
  only sanctioned route to a pin change.
- "Don't quantize TTS KV" and "no hard `Memory.memoryLimit` in production" remain standing
  do-NOTs unless their recorded evidence is superseded by new measurements.
- Engine-loop changes require the §K fixed-seed QC soak before staying in-tree.
- Artifact-changing experiments (Stage 2.2/2.3) go through the fail-closed catalog
  contract: exact identities, `model_catalog_contract.py validate --require-complete`, and
  explicit post-change delivery evidence.
- Sampling changes ship only on deterministic-QC wins; listening stays optional annotation.
- All evidence rules unchanged: telemetry v8 + evidence manifest v2, PASS-only history,
  memory-qualified publication.
