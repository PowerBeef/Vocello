# Project health scorecard

> Generated inventory and evidence-freshness snapshot. It is not a release verdict and does not
> execute models, devices, UI tests, signing, or network checks.

- Current source identity and dirty state: local JSON report only (kept out of the tracked snapshot to avoid self-referential drift)
- Swift tests: 396 cases in 54 files
- Python tests: 650 cases in 51 files
- Required-step assurance: 55 steps across 12 workflows, all covered by forced-failure fixtures
- Unsafe-concurrency annotations: 46 (46 registered with owner and invariant; contract complete)

## Canonical hardware evidence

| Platform | Latest canonical run | Captured |
| --- | --- | --- |
| macos | `macos-xcui-benchmark-20260723-083313-d02005ae` | 2026-07-23T08:44:14Z |
| ios | `ios-xcui-benchmark-20260723-061044-f986bf4d` | 2026-07-23T06:29:03Z |

## Critical-domain coverage and freshness

| Domain | Owner | Production files | Direct test files / cases | Hardware evidence |
| --- | --- | ---: | ---: | --- |
| generation-terminal | backend | 4 | 2 / 16 | macos: stale, ios: stale |
| clone-conditioning | backend | 30 | 2 / 31 | macos: stale, ios: stale |
| event-delivery | backend | 3 | 2 / 10 | macos: stale, ios: stale |
| memory-policy | backend-platform | 6 | 2 / 25 | macos: stale, ios: stale |
| model-delivery | backend-platform | 17 | 3 / 36 | macos: fresh, ios: fresh |
| xpc-transport | macos | 3 | 3 / 15 | macos: stale |
| benchmark-validation | release-qa | 6 | 4 / 111 | macos: stale, ios: stale |
| orchestration-assurance | release-qa | 3 | 1 / 12 | not hardware-gated |
| release-supply-chain | release-qa | 6 | 3 / 51 | macos: stale |
| persistence-privacy | platform-release-qa | 4 | 2 / 7 | not hardware-gated |
| runtime-hardening | backend-release-qa | 5 | 2 / 17 | not hardware-gated |

## Interpretation

- `stale` means a production path owned by that domain changed after the latest canonical hardware record; it does not block ordinary development publishing.
- Test inventory proves discoverable direct coverage, not that those tests passed in this invocation.
- Dependency age and open P0/P1 issue state require authoritative online sources and are intentionally not guessed offline.
- Run `python3 scripts/project_health.py report --output build/artifacts/project-health/` for the complete local JSON inventory.
