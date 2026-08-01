# Roadmap 2026-08 — convergence residuals × Metal 4 study × Stage 4

> Adopted 2026-07-31 (maintainer call: interleave by cost; recorded in-repo as the resume
> authority). Merges the open contract-phase residuals, the phone-gated evidence-battery
> remainder, and Stage 4 as revised by the
> [Metal 4 tensor feasibility study](metal4-tensor-feasibility-2026-07-31.md). Supersedes
> the Stage-4/open-threads item lists in the
> [2026-07-25 roadmap review](optimization-report-review-2026-07-25.md) as the working
> order; that review remains the authority for stage-closure evidence and falsifiability
> rails. Phase status authority stays `config/runtime-refactor-contract.json`; current
> measurements stay `benchmarks/OPTIMIZATION.md`. No item implies a release; releases are
> cut only on an explicit maintainer call.

## Ground state (2026-07-31)

Stages 0–3 closed; v2.3.0 shipped on the 2026.07.26.1 artifacts. Open contract residuals:
`spokenTextPlanning` (single-take normalization not wired), `longFormV4` (iOS
single-segment regeneration macOS-only), `boundedAnalyzers` (persisted-WAV consolidation
pending), `unifiedQuality` (standard/canonical depths pending), `historyV3` (UI-checker
quality-identity fold pending; UI records publish v2). The evidence battery is mid-flight
(six of nine control lanes banked; remainder checkpointed and phone-gated). Standing
do-NOTs: no KV quantization, no hard `Memory.memoryLimit`, engine-loop changes need the
§K fixed-seed soak, artifact changes ride the fail-closed catalog, speculative/PCG/CFG
parked while GPU-busy ≈49% < 85%. OS-floor policy (study F7): hold macOS/iOS 26.0 with
runtime-gated capability ladders; the first pin bump vendoring mlx core ≥ 0.32.0 triggers
the 26.2 floor raise.

## Tier 1 — cheap, no-phone, ungated

Each item lands with its evidence, contract-token flip, and narrative sync (progress doc
+ status report/ADR) in one change. Any order.

| Item | Scope | Gate |
| --- | --- | --- |
| 1.1 Gate 0 micro-benchmark | Standalone probe (untracked scratch): MPP `matmul2d` (fp16, `execution_simdgroups`, `tensor_inline`, runtime-compiled MSL 4.0) vs MLX at the engine's real batch-1 GEMM shapes on the canonical M2; methodology + numbers become a new `benchmarks/OPTIMIZATION.md` section and the study's Gate 0 verdict | **Go/no-go: MPP ≥ parity on the floor.** No-go closes the custom-kernel question until the fallback or the floor changes |
| 1.2 Single-take spoken-text normalization | Route `SpokenTextPlanner` output into the single-take path in `QwenVoiceCore` (long-form already has it); tests in `Tests/VocelloCoreTests/SpokenTextPlanningTests.swift` extend to the single-take route | Core tests + bench-grade fixed-seed A/B with QC (text change is quality-affecting); flip `spokenTextPlanning` |
| 1.3 Persisted-WAV consolidation + composed emission | Call `GenerationQualityReportProducer.deepReport(...)` (standard/canonical policies) from a real lane call site; `deepEvidence` assembled from the existing typed analyzers; fail closed on missing analyzers | Deterministic suites; flips `boundedAnalyzers` + `unifiedQuality` residuals; retires the "composed lane emission deferred" note |
| 1.4 UI-checker quality-identity fold | Fold per-take quality identity into `scripts/check_ios_ui_benchmark.py`, `scripts/check_macos_xpc_bench.py`, and `scripts/publish_benchmark_history.py` (v3 stamps only when every take carries identity) | Checker self-tests + one local macOS UI benchmark publishing v3; flip the `historyV3` residual. **Land before Tier 2 so the canonical iOS matrix is the first v3 UI record** |
| 1.5 iOS single-segment regeneration (implementation half) | Expose the shared manifest-v4 `replacements` machinery in the iOS long-form UI (`IOSLongFormProjectRunner`, History project surface); stable identifiers, `IOSScrollView`, no hidden test UI | `./scripts/build_foundation_targets.sh ios`; token flip waits for Tier 2 on-device acceptance; record "implemented, device acceptance pending" honestly |
| 1.6 Delivery-chip audio previews (optional rider) | Ten curated fixed-seed CLI preview clips; Listen delivery chips play them via the shared audio element; waveforms via `website/scripts/render-waveforms.mjs` | Website `npm run check`; do only with slack |

## Tier 2 — next phone window (one sitting; phone unlocked, Auto-Lock Never)

1. **Battery remainder** (task checkpoint is authoritative): re-run iOS control 3
   (`phase0-ios-control-3`, short/warm-10 shape) → canonical filter-free
   `scripts/ui_test.sh ios benchmark` → `scripts/check_characterization_controls.py` +
   `scripts/check_secret_sauce_cells.py` → memory re-qualification on both platforms
   (`scripts/macos_test.sh memory --label retained-check`; `scripts/ios_device.sh memory
   --voice-id <saved-voice-id> --label retained-check`) → rebind
   `config/characterization-fixtures.json` to the 2026.07.26.1 identities with the
   mid-battery engine-delta caveat + progress-doc sync in the same change → registry
   `validate --all` + `rebuild-index --check` → close-out. Cleanup: the desktop staging
   folder and the two reference files in the phone's app Documents.
2. **Riders while the phone is present:** 1.5's on-device acceptance (flip `longFormV4`
   residual); the iPhone-15-Pro memory-profile diagnostic on the new artifacts
   (diagnostic-only, no history); iOS studio marketing screenshot recapture.

## Tier 3 — gated performance block

**Hard precondition: Tier 2's fixture rebind is complete**, so every comparison runs
against current-artifact baselines.

1. **Pin bump experiment** (the contract invariant's only sanctioned pin route;
   throwaway branch): newest lockstep mlx-swift / mlx-swift-lm pair confirmed at bump
   time (0.31.6-era; the old 0.31.3 target is stale). Bump all pin sites →
   `./scripts/regenerate_project.sh` → both foundation compiles →
   `attentionWithCacheUpdate` routing re-validation → full bench matrix + fixed-seed QC
   vs the rebound baselines. Riders: (a) re-test the preserved
   `feat/p1b-static-talker-compile` branch under the new pins; (b) parked 2.3 codec-bf16
   revival check per its recorded path; (c) **OS-floor trigger check (F7)**: inspect the
   vendored core for the 0.32.0 NAX deployment-target-26.2 requirement — if present, the
   keep decision bundles the 26.2 floor raise per policy (verify against the actual
   vendored core; never assume). Keep only with unchanged RTF/quality/QC; otherwise
   record the blocker and revert. The 0.31 quantization-API change touches the 4/8-bit
   load path.
2. **P1b static-shape talker compile** on the surviving pins, per the §M P3 per-pass
   keying pattern. Pre-registered keep-gate **+≥10% warm RTF on the M2 floor**; §K
   12-seed soak; byte-identity verified, not assumed. Keep or record the do-NOT with
   numbers.
3. **Gate 2 — Candidate A fused code-predictor kernel (conditional)**: only if Gate 0
   was go AND a post-P1b GPU-busy re-capture still shows launch-bound AND P1b
   under-delivered. One `MLXFast.metalKernel` for the 15-pass code-predictor loop (fp16,
   explicit dequant at the 26.0 floor, Algorithm-v2 RNG semantics reproduced exactly),
   behind a registered debug knob on a throwaway branch. Keep-gate ≥10% on the floor,
   12/12 §K soak, GPU-busy delta recorded; numerics deltas route to the promotion
   battery, never a waiver. Fold the outcome into OPTIMIZATION.md and the study's gate
   ledger either way.

## Tier 4 — after the performance block

- **Long-form text-context carryover (Q2, text first)**: adjacent-sentence text into
  segment planning (no acoustic risk), long-form assembly fixtures + fixed-seed segment
  comparison; the bounded acoustic/KV carryover experiment only after, assessed against
  segment memory budgets first.
- **Opportunistic**: MOS-proxy advisory column (UTMOSv2, dev-lane advisory only, never a
  gate); 60 Hz-device glass-gate measurement if hardware appears.

## Parked (with unpark conditions)

P8 speculative/PCG (until compute-bound ≥85% GPU busy); Q6 CFG (until a
condition-dropout checkpoint exists); Q7 LoRA; M2 KV quantization (standing do-NOT);
custom Metal-4 host-side work beyond MLXFast (upstream MLX territory); macOS/iOS 27
tensor formats (an artifact-promotion decision, per the study's F7).

## Dependency rules

- 1.4 before Tier 2's canonical matrix (soft: makes it the first v3 UI record).
- Tier 2's fixture rebind before all of Tier 3 (hard: baseline currency).
- 1.5 implementation before its Tier 2 acceptance rider (hard).
- Tier 3.3 requires 1.1 go plus the post-3.2 launch-bound re-check (hard).
- The OS floor moves only through Tier 3.1's trigger check (policy).
- Every contract-token flip lands with its narrative sync in the same change; heavy
  gates batch at change-set ends; dense workstreams close with a `docs: currency pass`.
