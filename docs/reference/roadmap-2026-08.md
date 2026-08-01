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
| 1.1 Gate 0 micro-benchmark — **done 2026-08-01: NO-GO** | Standalone probe (untracked scratch): MPP `matmul2d` (fp16, `execution_simdgroups`, `tensor_inline`, runtime-compiled MSL 4.0) vs MLX at the engine's real batch-1 GEMM shapes on the canonical M2; methodology + numbers in `benchmarks/OPTIMIZATION.md` §O and the study's Gate 0 ledger | Verdict: MPP ties only where launch overhead dominates and loses amortized on all seven shapes (MLX 1.03–1.53× faster); `M % 8 == 0` makes batch-1 inexpressible at parallel scope; one silent-wrong-result aspect ratio observed. Candidates A/B closed until the fallback or the floor changes — **Tier 3 item 3 is withdrawn** |
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

1. **Pin bump experiment — done 2026-08-01: KEEP (0.31.6 + 3.31.4).** Same-day A/B at
   the canonical seed on the M2 floor: warm RTF within +0.6…+2.0% (noise), QC verdict
   distributions identical, clone durations byte-equal (sampling stable). The lm 2→3
   major externalized Hub/Tokenizers — swift-transformers 1.1.9 (the exact 2.30.6-era
   resolution) is now a direct dependency; CudaBuild plugin fingerprint validation is
   skipped unconditionally with reviewed justification in `scripts/lib/build_cache.sh`.
   Riders: (a) P1b re-test → item 2; (b) codec-bf16 revival probe **negative** — conv
   µ-throughput identical across pins and half-precision already beat fp32 on 0.30.6,
   so §N 2.3's conv attribution does not reproduce in isolation (2.3 stays parked;
   iPhone 17 Pro measurement is the remaining path); (c) **F7 not triggered** — 0.31.6
   vendors mlx core 0.31.1 (< 0.32), floors stay 26.0. Full record:
   `benchmarks/OPTIMIZATION.md` §Q.
2. **P1b static-shape talker compile — done 2026-08-01: confirmed null on 0.31.6
   (do-NOT, maintainer-ratified after a paired soak).** Cherry-picked onto the new pins:
   258-step eager equivalence passes; the paired §K-style soak (6 seeds, both builds,
   order-alternated) resolved the initial −0.5…−2.1% cross-run read to **+0.74% slower
   on medium (6/6 seeds) and +0.16% on long** — noise-free confirmation that the
   trace-build cost cancels the graph-build savings. Reverted from the pin-bump branch;
   the preserved `feat/p1b-static-talker-compile` branch remains for a future pin
   generation (DECODE-002 updated in `benchmarks/OPTIMIZATION.md` §Q).
3. **Gate 2 — Candidate A fused code-predictor kernel: WITHDRAWN (2026-08-01).** Gate 0
   returned no-go (`benchmarks/OPTIMIZATION.md` §O): MPP offers no building-block
   advantage on the floor, so the fused-kernel bet fails its first hard precondition.
   Launch elimination remains item 2's (P1b) territory inside MLX itself. Revisit only
   if Apple's portable MPP fallback improves or the canonical floor changes.

## Tier 4 — after the performance block

- **Long-form text-context carryover (Q2, text first) — planner half done 2026-08-01:**
  planner v2 ships R-tail orphan rebalancing (context-aware final-boundary repair;
  identity re-versioned via the serialized algorithm version, retained projects replay
  recorded plans untouched) with self-calibrating fixtures that also caught and removed
  a dead rule pre-ship (`docs/decisions/long-form-context-planning-v2.md`). The Q2
  acoustic remainder closed the same day: the pre-registered clone-ICL continuation
  probe measured join pitch −16.4% (under the ≥25% gate) with rate −54% and identity
  intact — **do-NOT**, parked on the single unpark condition of a register/pitch
  conditioning mechanism appearing upstream
  (`docs/decisions/long-form-acoustic-carryover-experiment.md`). With that, Tier 4's
  substantive work is complete; only the opportunistic riders below remain.
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
- Tier 3.3 required 1.1 go plus the post-3.2 launch-bound re-check (hard) — settled:
  1.1 returned no-go on 2026-08-01, so 3.3 is withdrawn.
- The OS floor moves only through Tier 3.1's trigger check (policy).
- Every contract-token flip lands with its narrative sync in the same change; heavy
  gates batch at change-set ends; dense workstreams close with a `docs: currency pass`.
