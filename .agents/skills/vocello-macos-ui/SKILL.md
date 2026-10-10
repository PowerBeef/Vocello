---
name: vocello-macos-ui
description: Validate macOS native UI changes through repository XCUITest lanes, including smoke, localization and relevant performance acceptance.
---

# macOS UI validation

Read docs/reference/native-engineering.md, docs/reference/testing-runbook.md and relevant Axiom
macOS/testing guidance. Choose the smallest lane from `scripts/ui_test.sh help`; compile-only work
uses `scripts/build_ui_test_bundles.sh macos`.
Join/stop workers and commit source before source-bound UI/performance evidence. Use the host lock,
load/memory checks and installed assets; if tracking is unavailable explicitly declare lead-only
after joining all workers. Run `scripts/ui_test.sh macos <lane> <options>` from the repository root.
Repository XCUITest is the sole native UI driver; use genuine controls and stable identifiers.
Keep the run ID, raw log, result bundle, ledgers and failed evidence. Triage the finished directory
with `scripts/dev.sh triage <run-directory> --json`; report limits. Reruns require a reason and new ID.
