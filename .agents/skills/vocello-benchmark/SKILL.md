---
name: vocello-benchmark
description: Run or assess a targeted Vocello performance, memory or audio-quality checkpoint using canonical benchmark definitions and compatible evidence.
---

# Benchmark checkpoint

Read docs/reference/telemetry-and-benchmarking.md, docs/reference/testing-runbook.md,
docs/reference/qc.md and docs/reference/tooling-and-evidence.md as relevant. Inspect the benchmark registry and
script help before choosing the smallest applicable `scripts/macos_test.sh` or `scripts/ios_device.sh`
lane. Source-bound measurements run on committed checkpoints with complete source identity,
fixed seeds, optimized-build receipts, compatible baselines and required memory qualification.
Join/stop workers first, keep host-wide native serialization and load/memory preflight. If worker
tracking is unavailable explicitly declare lead-only only after joining them. Installed assets only;
large downloads and publication need specific authorization. Do not edit source during a run.
Fast QC gates differ from report-only QC v2 (`scripts/qc.py`); automated scores do not imply human
listening or supported product-quality claims. Preserve failures; a justified rerun gets a new ID
and explanation. Report actual verdict, source/build identity, baseline compatibility and limits.
Never publish benchmark history implicitly.
