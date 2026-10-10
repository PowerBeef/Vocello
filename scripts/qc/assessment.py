"""Coverage and qualification are separate from execution and detected defects.

No acquisition floor or diagnostic statistic in this module is a quality threshold.
Version 1 requires every feature used by a detector before declaring that dimension
assessed. Uncalibrated/provisional scores are evidence, never automatic acceptance.
"""
from __future__ import annotations

import math
from typing import Any

SCHEMA = "vocello.qc.assessment/1"
MIN_AGREEING_SECONDS = 0.3  # acquisition minimum: one sustained-shift analysis window


def finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def dimension(detector: dict, features: dict, outcome: dict, *, qualified: bool,
              relevant: bool, control: bool) -> dict:
    names = [item["name"] for item in detector["features"]]
    missing = [name for name in names if not finite((features.get(name) or {}).get("value"))]
    reasons = []
    if missing:
        reasons.append("missing-inputs")
    if detector["id"] == "prosody.pitch":
        for name in ("pitch.agreeing_seconds", "pitch.reference_agreeing_seconds"):
            value = (features.get(name) or {}).get("value")
            if not finite(value):
                missing.append(name)
                reasons.append("missing-pitch-coverage")
            elif value < MIN_AGREEING_SECONDS:
                reasons.append("insufficient-agreeing-voiced-duration")
    present = len(names) - sum(name in missing for name in names)
    coverage = "unavailable" if present == 0 else "partial" if missing or reasons else "complete"
    qualification = "qualified" if qualified else "uncalibrated"
    if not qualified:
        reasons.append("no-qualified-decision-boundary")
    decision = "not-assessed" if coverage != "complete" else "uncertain" if not qualified else "pass"
    return {"inputStatus": coverage, "qualification": qualification, "decision": decision,
            "required": relevant and not control, "missingFeatures": sorted(set(missing)),
            "reasons": sorted(set(reasons))}


def summarize(takes: list[dict], errors: list[dict], models: dict | None = None) -> dict:
    failures = []
    for role, item in (models or {}).items():
        if item.get("error") or item.get("failed", 0) or item.get("exitCode", 0) or item.get("timedOut"):
            failures.append({"role": role, "reason": "runner-failed"})
    required = [assessment for take in takes for assessment in take.get("assessment", {}).values()
                if assessment.get("required")]
    incomplete = sum(item["decision"] in ("uncertain", "not-assessed") for item in required)
    coverage = "not-assessed" if not required else "incomplete" if incomplete else "complete"
    decisions = {item["decision"] for item in required}
    decision = "fail" if "fail" in decisions else "warn" if "warn" in decisions else \
        "not-assessed" if coverage != "complete" else "pass"
    return {"schema": SCHEMA, "execution": "error" if errors or failures else "complete",
            "runnerFailures": failures, "coverage": coverage, "requiredDimensions": len(required),
            "incompleteDimensions": incomplete, "decision": decision,
            "limitations": ["native-accent-acceptance-not-qualified", "naturalness-not-assessed",
                            "emotion-adherence-not-assessed"]}
