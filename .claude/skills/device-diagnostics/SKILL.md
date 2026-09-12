---
name: device-diagnostics
description: Run one headless (non-UI) physical-iPhone diagnostic verb through scripts/ios_device.sh — doctor, device-state, crashes, bench, lang-bench, memory, profile, gate. User-invoked only.
argument-hint: "<doctor|device-state|crashes|bench|lang-bench|memory|profile|gate> [options]"
disable-model-invocation: true
allowed-tools: Bash(scripts/ios_device.sh *) Bash(python3 scripts/lib/ios_coredevice_probe.py probe) Bash(ls *) Read Grep Glob
---

# iPhone headless diagnostics

Authority: `docs/reference/ios-device-testing.md` and `.claude/rules/native.md`. `scripts/ios_device.sh` is
the deterministic physical-device driver; it is not a UI driver. Verbs that generate speech (`bench`,
`lang-bench`, `memory`, `profile`) need the on-device models and minutes of device time.

## Steps

1. `scripts/ios_device.sh doctor` first when the environment is uncertain (signing identity, paired
   device, platform support).
2. Require a verb as the first argument. Never use `install` or `launch` against a distribution
   candidate here; the candidate route is `scripts/ui_test.sh ios smoke --preinstalled-candidate <verified-release-dir>`.
3. Say what the verb does and how long it takes before running: `scripts/ios_device.sh $ARGUMENTS`.
4. Report the verb's own verdict, the artifacts under `build/artifacts/diagnostics/ios/` or
   `build/artifacts/ios/`, and whether a crash delta appeared. Do not publish benchmark records from
   here; publication goes through `scripts/publish_benchmark_history.py` on explicit request.
