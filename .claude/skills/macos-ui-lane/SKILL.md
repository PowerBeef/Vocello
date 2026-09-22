---
name: macos-ui-lane
description: Run one explicit macOS XCUITest lane (smoke, benchmark, perf, localization, marketing) through scripts/ui_test.sh, then triage the run. User-invoked only.
argument-hint: "<smoke|benchmark|perf|localization|marketing> [ui_test options]"
disable-model-invocation: true
allowed-tools: Bash(scripts/ui_test.sh macos *), Bash(scripts/macos_test.sh models check*), Bash(xcrun xcresulttool *), Bash(ls *), Read, Grep, Glob, Agent
---

# macOS UI lane

Authority: `docs/reference/macos-testing.md` and `.claude/rules/native.md`. Explicit QA scope: the lane
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

`scripts/ui_test.sh macos $ARGUMENTS`

The run id and `build/artifacts/ui-tests/macos/<run_id>/` are the result.

## Triage

Delegate the run directory to the `xcresult-triage` subagent, or read it directly with
`docs/reference/testing-runbook.md`, and report verdict, ledger summary, crash delta and attachment
paths. UI-perf ceilings are warn-only; say so when they trip. `marketing` refreshes product images
(`evidenceClass: marketing-assets`) and never counts as acceptance, promotion or benchmark evidence.
