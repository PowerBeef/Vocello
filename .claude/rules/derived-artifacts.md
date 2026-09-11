---
status: active
owner: release-qa
summary: Domain rule for generated-inventory freshness — which paths require refresh_derived_artifacts.py in the same change, and the manual narrative-sync exception.
sourceOfTruth:
  - scripts/refresh_derived_artifacts.py
paths:
  - "config/**"
  - "docs/**"
  - "Packages/VocelloQwen3Core/*.json"
---
# Derived artifacts freshness

CI fail-closes on stale generated inventories. Refresh them in the **same change** as the source
edit. Update narrative progress deliberately at the coherent checkpoint described in root
`CLAUDE.md` (Start and resume work); do not create a separate routine documentation commit.
During a frozen acceptance campaign, keep progress untracked until a deliberate source checkpoint.
Finalize intended tracked-file membership before refreshing inventories: project-health counts
tracked files, so adding files to the index after refresh can make that output stale even when
the content fingerprint has not changed. Never change index membership during a running gate.

## Before commit/push after touching these paths

| Changed paths | Refresh |
| --- | --- |
| `Packages/VocelloQwen3Core/**` | `python3 scripts/refresh_derived_artifacts.py refresh` (or vendor rebuilds + project-health) |
| `config/project-health-contract.json`, evidence/benchmarks that feed health | `python3 scripts/project_health.py rebuild-summary` |
| `config/documentation-contract.json`, docs group membership | `python3 scripts/documentation_contract.py rebuild-index` |
| Model catalog sources / receipts | `python3 scripts/model_catalog_contract.py rebuild` |
| Benchmark records named in `scripts/generate_readme_charts.py`, or the generator itself | `python3 scripts/generate_readme_charts.py` (README `docs/charts/*.svg`) |
| `config/runtime-refactor-contract.json` phase/status tokens | Sync the current checkpoint and applicable active references in the same change; never rewrite pinned historical ADR/status-report bodies |

## Preferred one-shot

```sh
python3 scripts/refresh_derived_artifacts.py status
python3 scripts/refresh_derived_artifacts.py refresh   # stale only
python3 scripts/refresh_derived_artifacts.py validate
```

Authority: `CLAUDE.md` hard invariant **Fresh derived artifacts**. Scripts win over this rule.
