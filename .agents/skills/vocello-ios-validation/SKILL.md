---
name: vocello-ios-validation
description: Validate an iOS change with the smallest repository compile or physical-iPhone XCUITest lane; use for iOS acceptance and targeted device UI verification.
---

# iOS validation

Read docs/reference/native-engineering.md, docs/reference/ios-device-testing.md and
the applicable Axiom build/testing guidance. Commands run from the repository root.
Use `scripts/dev.sh ios` for a generic device-SDK compile. Choose the smallest relevant existing
lane from `scripts/ui_test.sh help` for physical-iPhone acceptance; do not substitute another driver.
Before a measured lane join/stop all workers, commit the checkpoint, use `scripts/dev.sh doctor`,
and probe reachability with `python3 scripts/lib/ios_coredevice_probe.py probe`; never print device IDs.
When lifecycle tracking is unavailable, declare `QVOICE_LEAD_ONLY=1` only after joining all workers.
Explain the lane and expected device interaction, then run `scripts/ui_test.sh ios <lane> <options>`.
Use installed models; new large downloads need specific authorization. Preserve failed artifacts.
Read `scripts/dev.sh triage <run-directory> --json`; report the actual verdict and evidence path.
Never retry silently; a justified rerun gets a new ID and explanation. No Simulator or MCP UI driving.
