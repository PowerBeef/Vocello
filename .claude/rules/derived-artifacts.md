---
status: active
owner: release-qa
summary: Domain rule for generated files — which paths are generated, and the one command that regenerates them.
sourceOfTruth:
  - scripts/refresh_derived_artifacts.py
paths:
  - "config/**"
  - "docs/**"
  - "Packages/VocelloQwen3Core/*.json"
---
# Generated files

CI fails on a stale generated file. Regenerate in the **same change** as the source edit:

```sh
scripts/dev.sh regen        # refresh_derived_artifacts.py refresh + validate
```

| Generated file | Source | Generator |
| --- | --- | --- |
| `docs/ROADMAP.md` | `config/roadmap.json` | `scripts/roadmap.py render` |
| `Sources/Resources/qwenvoice_production_model_catalog.json` | `config/model-artifact-receipts.json` | `scripts/model_catalog_contract.py rebuild` |
| `Packages/VocelloQwen3Core/CURRENT_INVENTORY.json`, `FACADE_API_BASELINE.json` | the owned package sources | `scripts/vendor_runtime_contract.py rebuild-*` |
| `docs/charts/*.svg` | benchmark records named in the generator | `scripts/generate_readme_charts.py` |
| `benchmarks/HISTORY.md` | `benchmarks/runs/` | `scripts/benchmark_history.py` |

The generated-file guard hook refuses hand edits of these paths and names the generator.
Narrative documents (`docs/development-progress.md`, decisions) are deliberate edits, never generated.
