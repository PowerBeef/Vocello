---
name: vocello-benchmark
description: Run or assess a targeted Vocello performance, memory or audio-quality checkpoint using canonical benchmark definitions and compatible evidence.
---

# Benchmark checkpoint

Apply this procedure to the lane or benchmark ID the user asked for.

Read `docs/reference/telemetry-and-benchmarking.md`, `docs/reference/testing-runbook.md`,
`docs/reference/qc.md` and `docs/reference/tooling-and-evidence.md` as relevant. Inspect the benchmark
registry and script help before choosing the smallest applicable `scripts/macos_test.sh` or
`scripts/ios_device.sh` lane. Source-bound measurements run on committed checkpoints with complete
source identity, fixed seeds, optimized-build receipts, compatible baselines and required memory
qualification.

Join or stop every subagent first (`manage_subagents list`, `swarm status`) and confirm no other host
sessions are active in this repository, keeping host-wide native serialization. Performance, memory
and model inference/generation lanes retain load/memory preflight. Cache-only rescoring of existing
audio/results uses `check_cache_only_host`: record load/pressure without blocking, retain
ownership/native-lock checks, and make no latency or memory-qualification claim. When automated
worker tracking is unavailable, explicitly declare `QVOICE_LEAD_ONLY=1` only after joining all
workers.

Installed assets only; large downloads and publication need specific authorization. Do not edit
source during a run. Fast QC gates differ from report-only QC v2 (`scripts/qc.py`) and the separate
offline report-only `RF-72` multimodal advisory complement (`vocello-audio-qc` / `scripts/qc.py
multimodal`, strictly outside QC v2 `SCORING_SOURCES` and Fast QC); automated scores do not imply
human listening or supported product-quality claims. Preserve failures; a justified
rerun gets a new ID and explanation. Report actual verdict, source/build identity, baseline
compatibility and limits. Never publish benchmark history implicitly.
