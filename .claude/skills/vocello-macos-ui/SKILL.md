---
name: vocello-macos-ui
description: Validate macOS native UI changes through repository XCUITest lanes, including smoke, localization and relevant performance acceptance.
argument-hint: "<lane from scripts/ui_test.sh help> [options]"
---

# macOS UI validation

Arguments: $ARGUMENTS

Read docs/reference/native-engineering.md, docs/reference/testing-runbook.md and relevant Axiom
macOS/testing guidance. Choose the smallest lane from `scripts/ui_test.sh help`; compile-only work
uses `scripts/build_ui_test_bundles.sh macos`.
Join/stop workers and commit source before source-bound UI/performance evidence. Use the host lock,
load/memory checks and installed assets; if tracking is unavailable explicitly declare lead-only
after joining all workers. Run `scripts/ui_test.sh macos <lane> <options>` from the repository root.
Repository XCUITest is the only automated native UI evidence; use genuine controls and stable
identifiers. Computer use covers what XCUITest cannot, between lanes and never while one runs
(`/vocello-ui-autonomy`). After the lane, review `<run>/screenshots/index.json`.
Keep the run ID, raw log, result bundle, ledgers and failed evidence. Triage the finished directory
with `scripts/dev.sh triage <run-directory> --json` or the read-only `vocello-xcresult-triage` agent;
report limits. Reruns require a reason and new ID.
