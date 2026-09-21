---
name: macos-ui-lane
description: Run one explicit macOS XCUITest lane (smoke, benchmark, perf, localization) through scripts/ui_test.sh, then triage the run. User-invoked only.
---

# macOS UI lane

Authority: `docs/reference/macos-testing.md` and `docs/reference/agent-rules/native.md`. Explicit QA scope: the lane
launches the built app, may generate speech with real models, and owns the screen while it runs. It
never runs unasked and never retries.

All commands and authority paths below are relative to the repository root.

## Preflight

1. Require a lane name as the first argument.
2. `benchmark` with the clone mode needs the clone fixture: `scripts/macos_test.sh models check` first.
3. The runner reads microphone and speech-recognition TCC state as an advisory; if it warns, tell the
   user a permission prompt may appear on first launch.
4. State before running: "This launches Vocello on this Mac for the `<lane>` lane, records a new run id,
   does not retry, and keeps artifacts on failure."

## Run

`scripts/ui_test.sh macos <requested lane and options>`

The run id and `build/artifacts/ui-tests/macos/<run_id>/` are the result.

## Triage

Read the run artifacts directly using `docs/reference/testing-runbook.md` and report verdict, ledger summary, crash
delta and attachment paths. UI-perf ceilings are warn-only; say so when they trip.
