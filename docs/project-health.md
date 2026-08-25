# Project health scorecard

> Generated inventory and evidence-freshness snapshot. It is not a release verdict and does not
> execute models, devices, UI tests, signing, or network checks.

- Current source identity and dirty state: local JSON report only (kept out of the tracked snapshot to avoid self-referential drift)
- Swift tests: 584 cases in 81 files
- Python tests: 1194 cases in 99 files
- Required-step assurance: 81 steps across 18 workflows, all covered by forced-failure fixtures
- Unsafe-concurrency annotations: 49 (49 registered with owner and invariant; contract complete)
- Evidence routing: 809/809 critical paths explicit; 0 use repository-other fallback

## Hardware evidence by domain selector

| Selector | Platform / kind | Latest qualifying run | Captured |
| --- | --- | --- | --- |
| ios-memory-qualification | ios / memory-qualification | `ios-memory-qualification-20260802-004801-03ebafe1` | 2026-08-02T00:49:27Z |
| ios-ui-generation | ios / ui-generation | `ios-xcui-benchmark-20260801-132415-abbec96b` | 2026-08-01T13:38:28Z |
| ios-ui-performance | ios / ui-perf | `ios-xcui-perf-20260815-173719-6e425c28` | 2026-08-15T17:47:07Z |
| macos-memory-qualification | macos / memory-qualification | `mac-memory-qualification-20260807-022819-3eb4d25b` | 2026-08-07T02:29:39Z |
| macos-ui-generation | macos / ui-generation | `macos-xcui-benchmark-20260801-182943-b0b5a448` | 2026-08-01T18:43:00Z |
| macos-ui-performance | macos / ui-perf | `macos-xcui-perf-20260805-202246-f7d85c1e` | 2026-08-05T20:30:14Z |

## Critical-domain coverage and freshness

| Domain | Owner | Production files | Direct test files / cases | Hardware evidence |
| --- | --- | ---: | ---: | --- |
| generation-terminal | backend | 4 | 2 / 16 | macos-ui-generation: stale, ios-ui-generation: stale |
| clone-conditioning | backend | 33 | 2 / 32 | macos-ui-generation: stale, ios-ui-generation: stale |
| event-delivery | backend | 3 | 2 / 10 | macos-ui-generation: stale, ios-ui-generation: stale |
| memory-policy | backend-platform | 6 | 2 / 29 | macos-memory-qualification: stale, ios-memory-qualification: stale |
| model-delivery | backend-platform | 17 | 3 / 46 | external promotion: macos-model-download-lifecycle, ios-model-download-lifecycle |
| ui-performance | platform | 77 | 17 / 57 | macos-ui-performance: stale, ios-ui-performance: stale |
| xpc-transport | macos | 3 | 4 / 18 | macos-ui-generation: stale |
| benchmark-validation | release-qa | 6 | 4 / 121 | macos-ui-generation: stale, ios-ui-generation: stale |
| orchestration-assurance | release-qa | 3 | 1 / 12 | not hardware-gated |
| release-supply-chain | release-qa | 9 | 4 / 67 | not hardware-gated |
| persistence-privacy | platform-release-qa | 4 | 2 / 8 | not hardware-gated |
| runtime-hardening | backend-release-qa | 7 | 3 / 32 | not hardware-gated |

## Interpretation

- `stale` means a production path owned by that domain changed after its latest qualifying hardware record; `missing` means no record matches that domain's selector. Neither blocks ordinary development publishing.
- Test inventory proves discoverable direct coverage, not that those tests passed in this invocation.
- Dependency age and open P0/P1 issue state require authoritative online sources and are intentionally not guessed offline.
- Run `python3 scripts/project_health.py report --output build/artifacts/project-health/` for the complete local JSON inventory.
