---
name: vocello-debug
description: Triage a Vocello failure from retained evidence and use focused native, runtime or tooling diagnostics without losing the original failure.
---

# Evidence-first debugging

Read docs/reference/testing-runbook.md and the relevant docs/reference/native-engineering.md or
tooling-and-evidence.md sections. Begin with `scripts/dev.sh triage <run-directory> --json` when
artifacts exist. Inspect the deciding ledger/test, first raw-log failure, crash delta and attachments.
Classify product failure, infrastructure failure, interruption or incomplete evidence before action.
Load applicable Axiom build/concurrency/performance guidance, MLX skills for runtime issues and
Sosumi/Context7 for authoritative API research. Detect optional XcodeBuildMCP/debugger capabilities;
do not assume a device/LLDB route exists. Keep native serialization and XCUITest-only UI driving.
Use verified Axiom xcsym for symbolication and xcprof for existing traces as appropriate; locate
helpers through the installed skill, check executability and non-mutating help before use.
Repository raw logs, exit statuses, optimization settings and artifact contracts remain authoritative;
retain script-only fallbacks. Reproduce with the smallest deterministic test or justified new lane ID.
Preserve the original failure. No blanket cache clearing, automatic retry or unsupported PASS claim.
