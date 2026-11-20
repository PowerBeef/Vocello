---
name: vocello-ios-validation
description: Validate an iOS change with the smallest repository compile or physical-iPhone XCUITest lane; use for iOS acceptance and targeted device UI verification.
---

# iOS validation

Apply this procedure to the lane and options the user asked for from `scripts/ui_test.sh help`.

Read `docs/reference/native-engineering.md`, `docs/reference/ios-device-testing.md` and the
applicable Axiom build/testing guidance via the `axiom` MCP server. Commands run from the repository
root. Use `scripts/dev.sh ios` for a generic device-SDK compile. Choose the smallest relevant
existing lane from `scripts/ui_test.sh help` for physical-iPhone acceptance; do not substitute
another driver.

Before a measured lane join/stop all subagents (`manage_subagents list`, `swarm status`), commit the
checkpoint, check `scripts/dev.sh doctor`, and probe reachability with
`python3 scripts/lib/ios_coredevice_probe.py probe`; never print device IDs. Before any phone lane
quit iPhone Mirroring (`scripts/ios_device.sh mirroring stop`): XCUITest breaks under it and
`ui-preflight` refuses while it runs; the phone must then be unlocked. When lifecycle tracking is
unavailable, declare `QVOICE_LEAD_ONLY=1` only after joining all workers. Explain the lane and
expected device interaction, then run `scripts/ui_test.sh ios <lane> <options>`.

Use installed models; new large downloads need specific authorization. Preserve failed artifacts.
Read `scripts/dev.sh triage <run-directory> --json` (the read-only `vocello-xcresult-triage` subagent
can take the run directory); report the actual verdict and evidence path. Never retry silently; a
justified rerun gets a new ID and explanation. No Simulator, third-party UI-automation MCP,
`cua-driver`, computer use or iPhone Mirroring session: every UI check is an XCUITest lane
(maintainer decision 2026-11-17), a check no lane covers gets its own scenario, and what XCUITest
cannot drive (system settings, permission prompts, the passcode, TestFlight installs) is the
maintainer's, by hand. After the lane, review `<run>/screenshots/index.json`: each failure frame and
each named state the row asserts, for clipping, overlap, a wrong state, untranslated text or an
unexpected dialog; report-only, each finding classified as a release blocker or a backlog line.
