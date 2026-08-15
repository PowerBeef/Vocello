---
status: active
owner: release-qa
summary: The evidence-impact contract — mapping changed repository paths to proportionate deterministic merge and release evidence via scripts/evidence_impact.py.
sourceOfTruth:
  - scripts/evidence_impact.py
  - config/evidence-impact.json
---
# Evidence impact contract

`config/evidence-impact.json` maps changed repository paths to proportionate deterministic merge
and release evidence. `scripts/evidence_impact.py` validates the map, computes its stable digest,
and classifies a path set:

```sh
python3 scripts/evidence_impact.py validate
python3 scripts/evidence_impact.py digest
python3 scripts/evidence_impact.py classify Sources/QwenVoiceCore/MLXTTSEngine.swift
python3 scripts/evidence_impact.py classify --base origin/main
```

The output separates three sets:

- `mergeRequiredEvidence`: deterministic proof required for ordinary development publication.
- `releaseRequiredEvidence`: deterministic proof required when the changed surface is packaged.
- `qualityEvidence`: model-, UI-, or device-dependent acceptance appropriate to the product risk.

The validator rejects any contract that places model-dependent, UI, or physical-device evidence
in an ordinary merge or release-required set. Those checks remain valuable for explicit quality
acceptance, but unavailable models or hardware never block a commit, push, pull request, merge,
signing run, or artifact upload. Unknown paths use the deterministic `repository-other` fallback
instead of silently receiving no evidence classification.

The model-delivery class illustrates the boundary: catalog reproducibility, deterministic tests,
and device-SDK compilation are publication proof; isolated Mac and physical-iPhone downloads are
non-blocking lifecycle evidence before activating a new catalog or delivery route.
