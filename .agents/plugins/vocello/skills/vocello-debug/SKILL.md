---
name: vocello-debug
description: Triage a Vocello failure from retained evidence and use focused native, runtime or tooling diagnostics without losing the original failure.
---

# Evidence-first debugging

Apply this procedure to the run directory or failure description the user asked for.

Read `docs/reference/testing-runbook.md` and the relevant `docs/reference/native-engineering.md` or
`docs/reference/tooling-and-evidence.md` sections. Begin with
`scripts/dev.sh triage <run-directory> --json` when artifacts exist. Inspect the deciding ledger/test,
first raw-log failure, crash delta and attachments. Classify the run with the runbook's verdict
classes (`PASS`, product failure, infrastructure failure, external interruption, restoration gap or
incomplete evidence) before taking action.

Load applicable Axiom guidance via the `axiom` MCP server, `docs/reference/mlx-guide.md` for runtime
issues, and Sosumi or Context7 for authoritative API research. Hand a finished native run to the
read-only `vocello-xcresult-triage` subagent when a second reading helps. Detect optional
`mobilebuildmcp` discovery/coverage tools in the live session (its debugging/LLDB MCP tools are
denied and disabled); use LLDB strictly through `scripts/macos_test.sh debug` or
`scripts/ios_device.sh debug`. Keep native serialization; a UI reproduction is an XCUITest lane or a new
scenario, never a `cua-driver` or computer-use session.

Use `axiom` MCP's `axiom_xcsym_*` tools for retained crash symbolication and `axiom_xcprof_*` for
existing trace inspection when appropriate. Never use Simulator tools or agents. Repository raw logs,
exit statuses, optimization settings and artifact contracts remain authoritative; retain script-only
fallbacks. Reproduce with the smallest deterministic test or justified new lane ID. Preserve the
original failure. No blanket cache clearing, automatic retry or unsupported PASS claim.
