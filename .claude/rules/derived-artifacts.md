---
status: active
owner: release-qa
summary: Domain rule for generated-inventory freshness — which paths require refresh_derived_artifacts.py in the same change, and the manual narrative-sync exception.
sourceOfTruth:
  - scripts/refresh_derived_artifacts.py
---
# Derived artifacts freshness

CI fail-closes on stale generated inventories. Refresh them in the **same change** as the source edit. Do **not** auto-rewrite narrative progress prose — but do keep it current by hand: the companion working norm (root `CLAUDE.md` "Before you edit") is that narrative docs land in the same change as the work they describe, with a `docs: currency pass` commit closing any dense workstream.

## Before commit/push after touching these paths

| Changed paths | Refresh |
| --- | --- |
| `Packages/VocelloQwen3Core/**` | `python3 scripts/refresh_derived_artifacts.py refresh` (or vendor rebuilds + project-health) |
| `config/project-health-contract.json`, evidence/benchmarks that feed health | `python3 scripts/project_health.py rebuild-summary` |
| `config/documentation-contract.json`, docs group membership | `python3 scripts/documentation_contract.py rebuild-index` |
| Model catalog sources / receipts | `python3 scripts/model_catalog_contract.py rebuild` |
| Benchmark records named in `scripts/generate_readme_charts.py`, or the generator itself | `python3 scripts/generate_readme_charts.py` (README `docs/charts/*.svg`) |
| `config/runtime-refactor-contract.json` phase/status tokens | Manually sync `docs/development-progress.md`, ADR, status-report in the same change |

## Preferred one-shot

```sh
python3 scripts/refresh_derived_artifacts.py status
python3 scripts/refresh_derived_artifacts.py refresh   # stale only
python3 scripts/refresh_derived_artifacts.py validate
```

Authority: `CLAUDE.md` hard rule **Derived catalogs stay fresh**. Scripts win over this rule.
