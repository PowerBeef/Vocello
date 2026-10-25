---
name: vocello-ios-validation
description: Validate an iOS change with the smallest repository compile or physical-iPhone XCUITest lane; use for iOS acceptance and targeted device UI verification.
argument-hint: "[lane from scripts/ui_test.sh help] [options]"
---

# iOS validation

Arguments: $ARGUMENTS

Read docs/reference/native-engineering.md, docs/reference/ios-device-testing.md and
the applicable Axiom build/testing guidance. Commands run from the repository root.
Use `scripts/dev.sh ios` for a generic device-SDK compile. Choose the smallest relevant existing
lane from `scripts/ui_test.sh help` for physical-iPhone acceptance; do not substitute another driver.
Before a measured lane join/stop all workers, commit the checkpoint, use `scripts/dev.sh doctor`,
and probe reachability with `python3 scripts/lib/ios_coredevice_probe.py probe`; never print device IDs.
Before any phone lane quit iPhone Mirroring (`scripts/ios_device.sh mirroring stop`): XCUITest breaks
under it and `ui-preflight` refuses while it runs; the phone must then be unlocked.
When lifecycle tracking is unavailable, declare `QVOICE_LEAD_ONLY=1` only after joining all workers.
Explain the lane and expected device interaction, then run `scripts/ui_test.sh ios <lane> <options>`.
Use installed models; new large downloads need specific authorization. Preserve failed artifacts.
Read `scripts/dev.sh triage <run-directory> --json` (the read-only `vocello-xcresult-triage` agent can
take the run directory); report the actual verdict and evidence path.
Never retry silently; a justified rerun gets a new ID and explanation. No Simulator or third-party
UI-automation MCP; computer use through iPhone Mirroring covers what XCUITest cannot, never during a
lane (`/vocello-ui-autonomy`). After the lane, review `<run>/screenshots/index.json`.
