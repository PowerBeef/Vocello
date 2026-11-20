---
name: vocello-macos-ui
description: Validate macOS native UI changes through repository XCUITest lanes, including smoke, localization and relevant performance acceptance.
---

# macOS UI validation

Apply this procedure to the lane and options the user asked for from `scripts/ui_test.sh help`.

Read `docs/reference/native-engineering.md`, `docs/reference/testing-runbook.md` and relevant Axiom
macOS/testing guidance via the `axiom` MCP server. Choose the smallest lane from
`scripts/ui_test.sh help`; compile-only work uses `scripts/build_ui_test_bundles.sh macos`.

Join/stop all subagents (`manage_subagents list`, `swarm status`) and commit source before
source-bound UI/performance evidence. Use the host lock, load/memory checks and installed assets; if
tracking is unavailable explicitly declare `QVOICE_LEAD_ONLY=1` after joining all workers. Run
`scripts/ui_test.sh macos <lane> <options>` from the repository root in an announced window,
backgrounded via `WaitMsBeforeAsync: 500` (never shell `&`).

Every UI check is a repository XCUITest lane (maintainer decision 2026-11-17); never use `cua-driver`
or computer use. Use genuine controls and stable identifiers, and give a check no lane covers its own
scenario. What XCUITest cannot drive (the macOS privacy grants, a Sparkle install) is the
maintainer's, by hand. After the lane, review `<run>/screenshots/index.json`: each failure frame and
each named state the row asserts, for clipping, overlap, a wrong state, untranslated text or an
unexpected dialog; report-only, each finding classified as a release blocker or a backlog line.

Keep the run ID, raw log, result bundle, ledgers and failed evidence. Triage the finished directory
with `scripts/dev.sh triage <run-directory> --json` or the read-only `vocello-xcresult-triage`
subagent; report limits. Reruns require a reason and new ID.
