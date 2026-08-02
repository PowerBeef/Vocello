# Project health scorecard

> Generated inventory and evidence-freshness snapshot. It is not a release verdict and does not
> execute models, devices, UI tests, signing, or network checks.

- Current source identity and dirty state: local JSON report only (kept out of the tracked snapshot to avoid self-referential drift)
- Swift tests: 448 cases in 61 files
- Python tests: 797 cases in 63 files
- Required-step assurance: 59 steps across 13 workflows, all covered by forced-failure fixtures
- Unsafe-concurrency annotations: 47 (47 registered with owner and invariant; contract complete)

## Canonical hardware evidence

| Platform | Latest canonical run | Captured |
| --- | --- | --- |
| macos | `macos-xcui-benchmark-20260801-182943-b0b5a448` | 2026-08-01T18:43:00Z |
| ios | `ios-xcui-benchmark-20260801-132415-abbec96b` | 2026-08-01T13:38:28Z |

## Critical-domain coverage and freshness

| Domain | Owner | Production files | Direct test files / cases | Hardware evidence |
| --- | --- | ---: | ---: | --- |
| generation-terminal | backend | 4 | 2 / 16 | macos: fresh, ios: fresh |
| clone-conditioning | backend | 31 | 2 / 32 | macos: stale, ios: stale |
| event-delivery | backend | 3 | 2 / 10 | macos: fresh, ios: fresh |
| memory-policy | backend-platform | 6 | 2 / 25 | macos: stale, ios: stale |
| model-delivery | backend-platform | 17 | 3 / 37 | macos: stale, ios: stale |
| xpc-transport | macos | 3 | 3 / 15 | macos: fresh |
| benchmark-validation | release-qa | 6 | 4 / 118 | macos: stale, ios: stale |
| orchestration-assurance | release-qa | 3 | 1 / 12 | not hardware-gated |
| release-supply-chain | release-qa | 6 | 3 / 51 | macos: fresh |
| persistence-privacy | platform-release-qa | 4 | 2 / 7 | not hardware-gated |
| runtime-hardening | backend-release-qa | 5 | 2 / 17 | not hardware-gated |

## Interpretation

- `stale` means a production path owned by that domain changed after the latest canonical hardware record; it does not block ordinary development publishing.
- Test inventory proves discoverable direct coverage, not that those tests passed in this invocation.
- Dependency age and open P0/P1 issue state require authoritative online sources and are intentionally not guessed offline.
- Run `python3 scripts/project_health.py report --output build/artifacts/project-health/` for the complete local JSON inventory.
