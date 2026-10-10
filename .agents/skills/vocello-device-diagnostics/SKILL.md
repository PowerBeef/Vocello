---
name: vocello-device-diagnostics
description: Inspect or debug the paired physical iPhone through the repository headless device driver and retained diagnostics.
---

# Physical-device diagnostics

Read docs/reference/ios-device-testing.md and docs/reference/native-engineering.md. Use
`scripts/ios_device.sh help` to select its current verb; begin with `doctor` or `device-state` when
the environment is uncertain. Prefer retained logs/crashes first. Run only the relevant
`scripts/ios_device.sh <verb> <options>`; this driver is headless, not a native UI driver.
Use a quiet committed checkpoint for measured bench/lang-bench/memory/profile lanes, after joining
workers. No new models/downloads, distribution-candidate install/launch or external publication
without specific authorization. Candidate acceptance uses the documented preinstalled-candidate route.
Print only privacy-safe summaries; retain raw artifacts untracked. Classify the result and crash
delta accurately. Never retry silently or replace failed evidence. Compatible MCP discovery/debug
can assist under native serialization; repository scripts own the final evidence.
