# Metal 4 tensors + MPP in MLX custom kernels — feasibility study (2026-07-31)

> Repo-authored research synthesis, in the tradition of
> [`optimization-report-review-2026-07-25.md`](optimization-report-review-2026-07-25.md).
> Question: can Vocello, targeting macOS/iOS 26+, use Metal 4 shader-side tensors and the
> MetalPerformancePrimitives (MPP) TensorOps library inside `MLXFast.metalKernel` custom
> kernels — and is that a lever worth pulling for the launch-bound engine?
> Method: three parallel research tracks (WWDC25/26 + Tech Talk transcripts; Apple SDK
> headers, sample code, and the MPP Programming Guide PDF; the pinned mlx-swift 0.30.6
> checkout plus upstream release history), including empirical probes compiled and run on
> the canonical Mac mini M2 class hardware (macOS 26.5). This document is research input,
> not status authority; the roadmap and `config/runtime-refactor-contract.json` govern.

## Verdict

**Mechanically feasible today, on our exact stack — but the wrong first lever, and gated
behind a cheap pre-registered go/no-go.** The full chain was verified end to end on M2:
runtime-compiled MSL 4.0 source with `#include <metal_tensor>` and
`#include <MetalPerformancePrimitives/MetalPerformancePrimitives.h>`, a classic
`MTLComputePipelineState`, a classic `MTLComputeCommandEncoder`, plain `setBuffer`
bindings, and in-shader `tensor_inline` construction over raw device pointers produce
bit-correct `mpp::tensor_ops::matmul2d` results. That is precisely the dispatch shape
`MLXFast.metalKernel` produces, and MLX itself already ships MPP-based kernels through the
same runtime compiler (its NAX path). Nothing architectural blocks a custom tensor-ops
kernel inside the MLX stream, and no host-side Metal 4 command API is required.

What keeps this parked behind other work: the engine is launch-bound (~49% whole-span GPU
busy), so only a *fusion* kernel (fewer dispatches) can pay, and MLX's own behavior — it
restricts its MPP kernels to M5/A19-class GPUs and keeps hand-tuned steel kernels
everywhere else — is a strong signal that the MPP portable fallback does not beat good
conventional kernels on our M2 canonical floor. A custom kernel must win **on the floor**
to be shippable evidence.

## Findings

### F1 — The compatibility chain (all confirmed)

1. **Shader-side tensors do not need host `MTLTensor`s.** `tensor_inline` constructs a
   tensor inside the kernel from a plain bound pointer plus extents (and optionally
   strides); threadgroup-memory tensors and `slice` views also exist. Host-created
   `MTLTensor`s bind to classic encoders only via argument buffers
   (`gpuResourceID` + `useResource`) — not needed for our path. A plain buffer bound at a
   *top-level* `tensor<...>` kernel parameter does **not** work (verified: reads zeros);
   `tensor_inline` over an ordinary `device T*` parameter is the correct form.
2. **Classic dispatch is blessed.** `MTLTensorUsageCompute` documents classic
   `MTLComputeCommandEncoder` alongside `MTL4ComputeCommandEncoder`, and Apple's own
   MPP header example dispatches through the classic API. Only the
   `MTL4MachineLearningCommandEncoder` whole-network route is genuinely Metal-4-command-API
   bound; inline tensor ops are not.
3. **Runtime source compilation works.** `makeLibrary(source:)` resolves the MSL tensor
   and MPP headers; MPP's implementation is `air.externally_defined`, resolved by the OS
   GPU compiler at pipeline creation — nothing to link. MSL 4.0 is required
   (`.version3_2` fails with `use of undeclared identifier 'dextents'`); on OS 26 the
   runtime default is already ≥ 4.0.
4. **MLX's custom-kernel path already speaks MSL 4.0 on OS 26.** At pin 0.30.6,
   `Device::build_library_` selects `MTL::LanguageVersion4_0` whenever the OS is 26+
   (not configurable, fast-math off, ASCII-only source). User `header` strings may carry
   system-framework `#include`s — MLX's own JIT NAX kernels retain
   `#include <MetalPerformancePrimitives/MetalPerformancePrimitives.h>` through the same
   compiler. Inputs/outputs bind as raw `MTLBuffer`s at sequential indices; grid is
   total-threads (`dispatchThreads`) with per-axis clamping; template args are
   Int32/Bool/DType.

### F2 — Hardware and OS ladder (floor-relevant)

- API floor: every tensor/MPP surface is macOS 26.0 / iOS 26.0+ — present on the entire
  supported fleet (Metal 4 language needs M1+/A14+; floors are M2 and A17 Pro).
- Neural accelerators are `MTLGPUFamily.apple10` — **M5/A19 class only**. On earlier GPUs
  TensorOps "falls back to optimized shader implementations" (portable M1→M5); Apple
  publishes no fallback performance numbers, and all demo speedups are measured on M5.
- Feature ladder inside the 26 cycle (runtime-gate anything above 26.0): 26.0 base
  fp16/fp32 matmul2d + convolution2d; 26.1 bfloat; 26.3 cooperative tensors as matmul
  inputs (the custom-dequant/FlashAttention pattern; before that, staging through
  threadgroup memory); 26.4 int4/int8 tensor types. FP8/FP4, int2, and E8M0 block-scale
  planes are 27-cycle. One unresolved discrepancy: MPP's availability macro keys on
  deployment target 26.2 while the int4/int8 *types* are stated as 26.4.
- Consequence for us: our 4-bit quantized weights cannot ride MPP's packed-int right
  operand at the 26.0 floor (26.4 gate), and the efficient cooperative dequant pattern is
  26.3+. A floor-safe kernel is fp16 (bf16 with a 26.1 gate) with explicit dequant.

### F3 — What our pin already contains (do-nothing wins)

mlx-swift 0.30.6 vendors mlx core 0.30.6, which **already includes** the NAX
neural-accelerator kernels (steel gemm fused/split-K/gather, quantized qmm, SDPA) written
against MPP tensor ops, JIT-compiled, and gated by `is_nax_available()`:
**OS ≥ 26.2 and GPU arch generation ≥ 17 (≥ 18 for phone-class)** — i.e. M5 Macs and
A19-class iPhones. An M5 Mac or the canonical iPhone 17 Pro on iOS 26.2+ takes the
neural-accelerator path in ordinary engine matmuls today, with zero Vocello work. The
canonical M2 and the A17 Pro floor keep the steel kernels. This should temper any
"adopt Metal 4 for speed" framing: on new hardware we already have it; on floor hardware
Apple's fallback is unproven against what we already run.

### F4 — Upstream state and the Stage-4 pin-bump target (revision)

- Upstream mlx has **no host-side Metal 4 adoption** (zero `MTL4`/`MTLTensor` hits):
  command submission remains one classic `MTLCommandQueue` per stream with batched command
  buffers. No surveyed release claims per-dispatch launch-overhead reduction — nothing
  upstream is about to fix the launch-bound profile for us.
- The roadmap's Stage-4 bump target "0.31.3" is stale: mlx-swift is at **0.31.6**
  (2026-07-02), vendoring core 0.31.1. Relevant post-pin items: core 0.31.2's
  multi-threaded submission restructure and NAX refactor, and core 0.32.0's
  `fast.metal_kernel` **`math_mode`** option (safe/relaxed/fast; the current pin is
  permanently fast-math-off), custom-kernel dtype use-after-free fix, and NAX
  deployment-target tightening (26.2). **No mlx-swift release ships core ≥ 0.31.2 yet**,
  so those custom-kernel improvements are currently unreachable from Swift. Bump target
  at experiment time: newest lockstep mlx-swift / mlx-swift-lm pair (0.31.6-era; confirm
  the paired `mlx-swift-lm` tag then), same throwaway-branch contract as before.

### F5 — Fit against the engine's actual bottleneck

The engine's measured profile (OPTIMIZATION.md §H P0/§M) is launch-bound: ~49% whole-span
GPU busy, dominated by batch-1 launch gaps inside the fused step eval, with the
code-predictor's per-pass graph build (~1.0 ms × 15 passes × frame, 12–13% of wall)
already identified as CPU-side overhead. Faster individual kernels do not close launch
gaps; fewer launches do. Candidate custom kernels, judged on that basis:

- **Candidate A — single-kernel fused code-predictor loop.** Collapse the 15 sequential
  code-predictor passes for one frame into one dispatch (simdgroup-scope `matmul2d`
  chain + sampling per codebook inside the kernel). Attacks both the dispatch count and
  the 15× per-frame graph-build cost. Blockers to cost: 4-bit weights need explicit
  dequant at the 26.0 floor (F2), and in-kernel categorical sampling must reproduce
  Algorithm v2's request-local RNG semantics exactly or the change is numerics-affecting
  (it almost certainly is → promotion-grade). Strongest candidate; still second in line
  behind P1b, which attacks the same structure with MLX's own compiled-graph machinery
  at far lower maintenance cost.
- **Candidate B — fused sampling chain** (softmax + top-k + categorical per step):
  smaller win, same RNG-identity burden.
- **Candidate C — Mimi decoder convolutions via `convolution2d`: rejected.** The decoder
  is already asyncEval-overlapped with the token loop (measured exposed cost ≈ 0 in the
  chunk timeline); accelerating hidden work buys nothing.

### F6 — Risks and standing constraints

- Numerics-affecting kernels change fixed-seed outputs → full §K 12-seed soak plus the
  promotion-quality battery, like the q8-embedding promotion. Scheduling-only claims
  require 12/12 byte-identical WAVs.
- The MPP fallback on M2 is the load-bearing unknown: if it loses to MLX's steel kernels
  at our shapes, a custom MPP kernel can regress the canonical floor while flattering
  M5/A19 — unacceptable for canonical evidence (M2 8 GB is the published basis).
- Maintenance: a hand-fused kernel forks engine math out of MLX's tested ops; every MLX
  pin bump then carries a private-kernel revalidation burden.
- `MLXFast.metalKernel` at the pin is fast-math-off with no override (core 0.32.0's
  `math_mode` would help, once vendored into a Swift release).
- "MLX is the only backend" holds: everything here stays inside MLXFast within the MLX
  stream. A side-channel Metal pipeline remains off the table.
- MPP has **no web documentation**; the authorities are the SDK headers, the MPP
  Programming Guide PDF (v1, 2026-03-16, developer.apple.com/metal/resources/), WWDC26
  session 330, WWDC25 sessions 205/262, and Tech Talk 111432.

## Pre-registered prototype scope (throwaway branch, in order, each gate blocking)

1. **Gate 0 — floor micro-benchmark (cheap, decisive).** Standalone probe (no engine
   changes): MPP `matmul2d` (fp16, `execution_simdgroups`) vs the same GEMM through MLX,
   on the canonical M2, at the engine's real shapes (talker step and code-predictor
   GEMMs; batch 1). **Go only if MPP ≥ parity on the floor.** Expected cost: hours. If
   no-go, record the numbers in OPTIMIZATION.md and close the question until Apple's
   fallback or our floor changes.
2. **Gate 1 — sequencing.** Run only after the Stage-4 pin bump (revised target, F4) and
   the P1b static-shape talker compile have both landed or been closed out; P1b may
   consume the same headroom cheaper.
3. **Gate 2 — Candidate A prototype** behind a registered debug knob on a throwaway
   branch: fused code-predictor loop as one `MLXFast.metalKernel`, fp16, explicit
   dequant, RNG semantics reproduced from Algorithm v2. Keep-gate: **≥ 10% warm RTF on
   the M2 8 GB floor** with 12/12 §K soak clean; GPU-busy delta recorded. Numerics
   deltas route to the promotion battery, not a waiver.
4. **Fold-back.** Whatever the outcome, record measurements in OPTIMIZATION.md §-next and
   revisit `is_nax_available()`-style runtime gating (26.x point-release features per F2)
   only if Gate 2 passes.

## Roadmap deltas proposed by this study

1. Revise the Stage-4 pin-bump target from 0.31.3 to the newest lockstep pair (F4).
2. Add the Gate-0 micro-benchmark as a cheap Stage-4 rider; park Candidates A/B behind
   P1b explicitly.
3. Note the do-nothing NAX win (F3) wherever new-hardware performance is next discussed;
   canonical evidence hardware is unchanged.
