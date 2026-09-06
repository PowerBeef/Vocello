---
status: active
owner: release-qa
reviewed: 2026-08-29
summary: Development-environment assistance only; Vocello reproduction and UI evidence use the repository XCUITest lanes.
sourceOfTruth:
  - scripts/ui_test.sh
---
# UI failure diagnosis and development-environment assistance

> **Currency review (2026-08-27):** localization, startup-parity, saved-voice, model-management, and
> performance lanes have expanded, but the boundary is unchanged: checked-in XCUITest is the only
> autonomous app UI driver and computer use supplies no acceptance evidence.

Use retained XCUITest screenshots, accessibility trees, logs, and source to diagnose Vocello.
Reproduce app interactions only through `scripts/ui_test.sh` and the checked-in tests, on native
macOS or a physical iPhone. Computer use may inspect the development environment (Xcode,
Instruments, or a blocking system dialog); it must not drive Vocello, including through iPhone
Mirroring. Diagnostic intent is not an exception to the sole-driver rule.

**History (2026-07-22):** computer-use driving was trialed as the autonomous UI driver and retired
the same day — mirror keyboard focus decays during idle gaps, popovers swallow batched clicks,
per-action round-trips are seconds each, and per-take environment injection/telemetry correlation
is impossible. That historical experiment identified two TCC dialog classes (app-data and
speech-recognition) that no log surfaced; it grants no current app-driving permission. XCUITest
(`scripts/ui_test.sh`) is the sole autonomous app UI driver.

## Ground rules

- Exploratory/diagnostic only: findings become issues, fixes, or new XCUITest coverage — never
  acceptance evidence, CI input, or a packaging prerequisite.
- App reproduction observes genuine controls through XCUITest; no coordinate tables, hidden
  markers, or seeded state. [`ios-ui-reference.md`](ios-ui-reference.md) is the control lookup.
- System permission (TCC) dialogs are answered by the human operator, never by the agent.
- A notification banner that obstructs XCUITest is preserved as infrastructure evidence under its
  original run ID. Dismiss it only for a separately identified manual rerun; never relabel the
  first run as product failure or PASS.
- Device scheduling, retention, and screen protection follow
  [`ios-device-testing.md`](ios-device-testing.md); do not start a device session for this assist.
- Screenshots worth keeping go under `build/artifacts/diagnostics/interactive-qa/<run-id>/`
  (untracked), with a short written note of what was observed.

## When to reach for it

- An XCUITest lane fails with an obstruction/evidence attachment that needs a live look.
- A TCC or system-dialog interaction needs to be observed end to end with the operator present.
- A missing scripted reproduction: extend the existing XCUITest owner, not an alternate driver.
