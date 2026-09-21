---
name: ios-lane
description: Run one explicit iPhone XCUITest lane through scripts/ui_test.sh on the paired physical device, with the device probe, storage floor and consent statement first, then triage the run. User-invoked only.
---

# iPhone lane

Authority: `docs/reference/ios-device-testing.md` (lanes, pause/resume, retention) and
`docs/reference/agent-rules/native.md`. This is explicit QA scope: it drives the paired physical iPhone, may generate
speech with real models, and takes minutes to hours. It never runs unasked and never retries.

All commands and authority paths below are relative to the repository root.

## Preflight

1. Require a lane name as the first argument; refuse anything else.
2. `python3 scripts/lib/ios_coredevice_probe.py probe`: the device must be reachable and unlocked.
   Print only reachability and lock state, never the identifier.
3. Free space: `scripts/ui_test.sh` enforces the `heavyLanePreflight` floor for `ui-<lane>` from
   `config/build-output-policy.json`; mention the floor so the user can free space before the build.
4. State the consent sentence before running: "This drives the paired iPhone for the `<lane>` lane, keeps
   all user data, does not retry, and records a new run id; a failed run keeps its artifacts."

## Run

`scripts/ui_test.sh ios <requested lane and options>`

Keep the terminal output; the run id, artifacts directory (`build/artifacts/ui-tests/ios/<run_id>/`)
and the final aggregate verdict are the result. Do not rerun on failure.

## Triage

Read the run artifacts directly using the triage procedure in `docs/reference/testing-runbook.md`. Report: run id, verdict, required-step
ledger summary, whether the failure (if any) is product, infrastructure bootstrap, interruption or a
restoration gap, and the attachment paths a human should open. If the lane closes or reopens a
roadmap item, update `config/roadmap.json` and re-render with `python3 scripts/roadmap.py render`.
