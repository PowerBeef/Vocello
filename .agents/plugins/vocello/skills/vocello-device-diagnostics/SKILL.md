---
name: vocello-device-diagnostics
description: Inspect or debug the paired physical iPhone through the repository headless device driver and retained diagnostics.
---

# Physical-device diagnostics

Apply this procedure to the verb and options the user asked for from `scripts/ios_device.sh help`.

Read `docs/reference/ios-device-testing.md` and `docs/reference/native-engineering.md`. Use
`scripts/ios_device.sh help` to select its current verb; begin with `doctor` or `device-state` when
the environment is uncertain. Prefer retained logs and crashes first. Run only the relevant
`scripts/ios_device.sh <verb> <options>`; this driver is headless, not a native UI driver.

Use a quiet committed checkpoint for measured bench, lang-bench, memory and profile lanes, after
joining all subagents (`manage_subagents list`, `swarm status`) and confirming no other host sessions
are active, declaring `QVOICE_LEAD_ONLY=1` when worker tracking is unavailable. No new models or
downloads, distribution-candidate install/launch or external publication without specific
authorization. Candidate acceptance uses the documented preinstalled-candidate route.

Print only privacy-safe summaries; retain raw artifacts untracked. Classify the result and crash
delta accurately. Never retry silently or replace failed evidence. `mobilebuildmcp` runs only its
discovery and coverage tools (never Simulator, device, build or UI tools); repository scripts own
the final evidence.
