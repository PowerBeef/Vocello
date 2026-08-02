---
status: historical
owner: backend-mlx
summary: Research corpus (imported point-in-time snapshots). Imported point-in-time research snapshot. Pinned: superseded figures carry inline editor's notes; contract JSON remains status authority.
contentDigest: sha256:0a0ff98e0fd05a7d73676cc05777925b062c67a05fdb399a55ae9cbef3dffdde
---
# Research corpus (imported point-in-time snapshots)

The first five documents in this directory are the research bundle that shaped the staged
backend runtime convergence program (`config/runtime-refactor-contract.json`). They were
authored externally on 2026-07-16/17 against `main` at `079757ab` and imported into the
repository on 2026-07-22 so that corrections, review history, and provenance stay tracked
next to the work they direct. A sixth snapshot, the 2026-07-24 launch-bound optimization
report, was imported and counter-verified on 2026-07-25.

| Document | Role |
| --- | --- |
| [`refactor-blueprint-2026-07-17.md`](refactor-blueprint-2026-07-17.md) | Master plan: the R0–R9 performance/streaming/quality refactor program the contract phases realize |
| [`performance-deep-dive-2026-07-17.md`](performance-deep-dive-2026-07-17.md) | Performance evidence review and optimization roadmap |
| [`qwen3tts-leverage-assessment-2026-07-16.md`](qwen3tts-leverage-assessment-2026-07-16.md) | External Qwen3-TTS research bundle: what to adopt, adapt, or reject |
| [`audio-quality-review-system-2026-07-16.md`](audio-quality-review-system-2026-07-16.md) | Autonomous audio-quality review system reference |
| [`exhaustive-project-review-2026-07-16.md`](exhaustive-project-review-2026-07-16.md) | Whole-project review; its P0/P1 findings (H-01, H-02) are fixed on `main` |
| [`launch-bound-optimization-report-2026-07-24.md`](launch-bound-optimization-report-2026-07-24.md) | Launch-bound decoding, memory, and quality-harness optimization proposals; counter-verified 2026-07-25 → [`docs/reference/optimization-report-review-2026-07-25.md`](../reference/optimization-report-review-2026-07-25.md) |

## Verification status

The 2026-07-22 backend refactor review counter-verified ~90 claims from this corpus against
the tree, the benchmark registry, pinned Hugging Face artifacts, MLX sources, and the cited
external papers. Outcome: **zero fabricated citations, zero invented numbers, zero wrong
mechanisms, zero outright factual errors.** Every external citation is genuine and fairly
characterized. The corpus's one systematic defect is that measured figures are not
date-stamped, and several were superseded by later canonical evidence — most importantly the
macOS RTF picture, which fell sub-realtime in the 2026-07-20 post-Phase-4-cutover canonical
matrix. Those sites now carry inline **Editor's note (2026-07-22)** blocks; the notes are the
current reading, the surrounding text is the historical snapshot.

The 2026-07-25 review applied the same procedure to the launch-bound optimization report:
every claim grounded in the tree by three parallel code audits, external sources re-verified
against the cited repositories, papers, and the pinned package checkouts. Outcome: the
central launch-bound thesis matches the repository's own §H P0 measurements verbatim and all
external citations are genuine; the defect pattern is staleness (six recommendations already
shipped, one premise structurally inapplicable, two "requires migration" flags wrong because
the pinned mlx-swift-lm 2.30.6 already carries the named APIs). Verdicts, corrections, and
the superseding staged plan live in
[`docs/reference/optimization-report-review-2026-07-25.md`](../reference/optimization-report-review-2026-07-25.md).

These documents are research input, not status authority. Current phase status lives in
[`config/runtime-refactor-contract.json`](../../config/runtime-refactor-contract.json);
current performance evidence lives in the canonical records under
[`benchmarks/runs/`](../../benchmarks/runs/) and
[`benchmarks/OPTIMIZATION.md`](../../benchmarks/OPTIMIZATION.md).
