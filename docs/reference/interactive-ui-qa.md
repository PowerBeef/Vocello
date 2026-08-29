---
status: active
owner: release-qa
reviewed: 2026-08-29
summary: Assistive computer-use policy for exploratory UI QA and lane-failure diagnosis — never a driver, gate, or replacement for the XCUITest lanes.
sourceOfTruth:
  - scripts/ui_test.sh
---
# Exploratory UI QA and failure diagnosis (computer use, assistive)

> **Currency review (2026-08-27):** localization, startup-parity, saved-voice, model-management, and
> performance lanes have expanded, but the boundary is unchanged: checked-in XCUITest is the only
> autonomous app UI driver and computer use supplies no acceptance evidence.

An assistive companion to the autonomous XCUITest lanes — never a replacement for them. An AI
agent may use computer use (screenshots, vision, and clicks on genuine visible controls) to
*explore* the app and to *diagnose* UI-lane failures: watching a lane run, checking the desktop
for blocking system dialogs, reproducing a reported flow by hand, or inspecting a state no log
explains. macOS is observed/driven directly; iOS through iPhone Mirroring on the paired physical
iPhone (never Simulator).

**History (2026-07-22):** computer-use driving was trialed as the autonomous UI driver and retired
the same day — mirror keyboard focus decays during idle gaps, popovers swallow batched clicks,
per-action round-trips are seconds each, and per-take environment injection/telemetry correlation
is impossible. As a *diagnostic* instrument it earned its place: it identified two TCC dialog
classes (app-data and speech-recognition) that no log surfaced. XCUITest
(`scripts/ui_test.sh`) is the sole autonomous app UI driver.

## Ground rules

- Exploratory/diagnostic only: findings become issues, fixes, or new XCUITest coverage — never
  acceptance evidence, CI input, or a packaging prerequisite.
- Observe and operate only genuine visible controls; no coordinate tables, hidden markers, or
  seeded state. The identifier maps in [`ios-ui-reference.md`](ios-ui-reference.md) name controls.
- System permission (TCC) dialogs are answered by the human operator, never by the agent.
- A notification banner that obstructs XCUITest is preserved as infrastructure evidence under its
  original run ID. Dismiss it only for a separately identified manual rerun; never relabel the
  first run as product failure or PASS.
- Keep device sessions burn-in-safe: a handful of generations, via the real UI.
- Screenshots worth keeping go under `build/artifacts/diagnostics/interactive-qa/<run-id>/`
  (untracked), with a short written note of what was observed.

## When to reach for it

- An XCUITest lane fails with an obstruction/evidence attachment that needs a live look.
- A TCC or system-dialog interaction needs to be observed end to end with the operator present.
- A UX review or manual repro that has no scripted coverage yet — write the XCUITest afterwards.
