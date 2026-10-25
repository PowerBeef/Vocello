---
name: vocello-debug
description: Triage a Vocello failure from retained evidence and use focused native, runtime or tooling diagnostics without losing the original failure.
argument-hint: "[run-directory or failure description]"
---

# Evidence-first debugging

Arguments: $ARGUMENTS

Read docs/reference/testing-runbook.md and the relevant docs/reference/native-engineering.md or
tooling-and-evidence.md sections. Begin with `scripts/dev.sh triage <run-directory> --json` when
artifacts exist. Inspect the deciding ledger/test, first raw-log failure, crash delta and attachments.
Classify product failure, infrastructure failure, interruption or incomplete evidence before action.
Load applicable Axiom build/concurrency/performance guidance, swift-mlx/swift-mlx-lm skills for runtime
issues and Sosumi/Context7 for authoritative API research. Hand a finished native run to the read-only
`vocello-xcresult-triage` agent when a second reading helps. Detect optional MobileBuildMCP/LLDB
capabilities in this session; do not assume a device/LLDB route exists. Keep native serialization;
XCUITest is the only automated UI evidence, and computer use may reproduce a report between lanes
(`/vocello-ui-autonomy`).
Use verified Axiom xcsym for symbolication and xcprof for existing traces as appropriate; locate
helpers under the Claude plugin cache (`scripts/dev.sh doctor --json` lists them), check executability
and non-mutating help before use. Never xcui or simulator agents.
Repository raw logs, exit statuses, optimization settings and artifact contracts remain authoritative;
retain script-only fallbacks. Reproduce with the smallest deterministic test or justified new lane ID.
Preserve the original failure. No blanket cache clearing, automatic retry or unsupported PASS claim.
