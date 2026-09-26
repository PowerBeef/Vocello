"""The Stage 3 verdict composer (audit section 3.3). Pure and never cached.

Each detector verdict names its detector (id@version), its detector class and
stage, the judges it consumed and its calibration record (or null). The
composer first normalizes each verdict against its record:

- `pass`, `warn` or `fail` with no calibration record is `uncalibrated`
  ("no-qualified-record"): a judge without a record prints UNQUALIFIED.
- A record whose scope does not cover the take turns the verdict into
  `abstain` ("out-of-scope", A1).
- A `fail` from a detector qualified only at warn is `warn` (section 3.3).
- A `legacy-unqualified` record keeps its verdict (A10: the existing Fast QC
  bounds stay until a qualified successor replaces them) and is marked legacy.

Then, per lane, the first matching rule decides the take:

1. any gating `fail` -> `fail`;
2. any gating `unavailable` -> `unavailable` (fails closed);
3. any gating `abstain` -> `inconclusive` (blocks a claimed pass, not a defect);
4. any `warn` (a qualified warn is informative in any lane) -> `warn`;
5. any gating `uncalibrated` -> `uncalibrated` (ranks above pass, as #41);
6. otherwise `pass`; advisory uncalibrated verdicts are listed only.

A lane whose required detector sent no verdict, or that has no gating verdict
at all, is `unavailable`: a pass is never composed from nothing. The Swift
registry spells the same order fail (unavailable folds into it) > abstained >
warning > uncalibrated > pass.
"""

from __future__ import annotations

import re
from typing import Iterable, Mapping, Sequence

COMPOSITION = "worst-of-gating/1"
SCHEMA = "vocello.audioqc.take-verdict/1"
DETECTOR_STATUSES = ("pass", "warn", "fail", "abstain", "uncalibrated", "unavailable")
TAKE_STATUSES = ("pass", "warn", "fail", "inconclusive", "uncalibrated", "unavailable")
# Detector statuses in composition order; `abstain` composes as take `inconclusive`.
PRECEDENCE = ("fail", "unavailable", "abstain", "warn", "uncalibrated", "pass")
TAKE_STATUS_OF = {"fail": "fail", "unavailable": "unavailable", "abstain": "inconclusive", "warn": "warn",
                  "uncalibrated": "uncalibrated", "pass": "pass"}
ABSTAIN_REASONS = frozenset({
    "out-of-scope", "families-disagree", "repeatability-disagreement", "low-confidence",
    "unqualified-text-class",
})
UNAVAILABLE_REASONS = frozenset({
    "missing-model", "digest-drift", "crash", "timeout", "envelope-breach", "analysis-failed", "missing-verdict",
})
CALIBRATION_LEVELS = ("fail", "warn", "legacy-unqualified")
DETECTOR_CLASSES = tuple("ABCDEFGHIJ")
STAGES = (0, 1, 2)
LANE_GATING = {
    "publication": {"stages": [0], "classes": []},
    "language-bench": {"stages": [], "classes": ["B", "C", "D"]},
    "clone-lane": {"stages": [], "classes": ["E"]},
    "delivery-bench": {"stages": [], "classes": ["H"]},
    "release-promotion": {"stages": [0], "classes": ["B", "C", "D", "E", "H"]},
}
_VERSIONED_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*@[0-9]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CompositionError(ValueError):
    """A verdict or a lane definition the composer refuses to read."""


def _reasons(verdict: Mapping) -> list[str]:
    reasons = verdict.get("reasons", [])
    if not isinstance(reasons, list) or any(not isinstance(item, str) or not item for item in reasons):
        raise CompositionError(f"{verdict.get('detector')}: reasons must be a list of codes")
    return list(reasons)


def _calibration(verdict: Mapping) -> dict | None:
    if "calibration" not in verdict:
        raise CompositionError(f"{verdict.get('detector')}: every verdict names its calibration record "
                               "(null when none exists)")
    record = verdict["calibration"]
    if record is None:
        return None
    if not isinstance(record, Mapping):
        raise CompositionError(f"{verdict.get('detector')}: calibration must be an object or null")
    digest, level, in_scope = record.get("recordSHA256"), record.get("level"), record.get("inScope")
    if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
        raise CompositionError(f"{verdict.get('detector')}: calibration.recordSHA256 must be a SHA-256")
    if level not in CALIBRATION_LEVELS:
        raise CompositionError(f"{verdict.get('detector')}: calibration.level must be one of {CALIBRATION_LEVELS}")
    if not isinstance(in_scope, bool):
        raise CompositionError(f"{verdict.get('detector')}: calibration.inScope must be a boolean")
    return {"recordSHA256": digest, "level": level, "inScope": in_scope}


def normalize(verdict: Mapping) -> dict:
    """Validate one detector verdict and apply its calibration record."""
    detector = verdict.get("detector")
    if not isinstance(detector, str) or not _VERSIONED_ID.fullmatch(detector):
        raise CompositionError(f"detector must be an id@version, got {detector!r}")
    detector_class = verdict.get("class")
    if detector_class not in DETECTOR_CLASSES:
        raise CompositionError(f"{detector}: class must be one of A-J")
    stage = verdict.get("stage")
    if isinstance(stage, bool) or stage not in STAGES:
        raise CompositionError(f"{detector}: stage must be 0, 1 or 2")
    judges = verdict.get("judges")
    if (not isinstance(judges, list) or not judges
            or any(not isinstance(judge, str) or not _VERSIONED_ID.fullmatch(judge) for judge in judges)):
        raise CompositionError(f"{detector}: judges must name at least one id@version")
    reported = verdict.get("status")
    if reported not in DETECTOR_STATUSES:
        raise CompositionError(f"{detector}: status must be one of {DETECTOR_STATUSES}")
    reasons = _reasons(verdict)
    calibration = _calibration(verdict)
    if reported == "abstain" and not (reasons and set(reasons) <= ABSTAIN_REASONS):
        raise CompositionError(f"{detector}: an abstention needs reasons from {sorted(ABSTAIN_REASONS)}")
    if reported == "unavailable" and not (reasons and set(reasons) <= UNAVAILABLE_REASONS):
        raise CompositionError(f"{detector}: an unavailable verdict needs reasons from "
                               f"{sorted(UNAVAILABLE_REASONS)}")
    status = reported
    legacy = bool(calibration and calibration["level"] == "legacy-unqualified")
    if reported in ("pass", "warn", "fail"):
        if calibration is None:
            status, reasons = "uncalibrated", reasons + ["no-qualified-record"]
        elif not calibration["inScope"]:
            status, reasons = "abstain", reasons + ["out-of-scope"]
        elif reported == "fail" and calibration["level"] == "warn":
            status, reasons = "warn", reasons + ["qualified-at-warn-only"]
    return {"detector": detector, "class": detector_class, "stage": stage, "judges": sorted(judges),
            "calibration": calibration, "reportedStatus": reported, "status": status,
            "reasons": sorted(set(reasons)), "legacy": legacy}


def _gating_set(lane: str, gating_sets: Mapping[str, Mapping]) -> tuple[frozenset, frozenset]:
    if lane not in gating_sets:
        raise CompositionError(f"unknown lane {lane!r}")
    entry = gating_sets[lane]
    return frozenset(entry.get("stages", [])), frozenset(entry.get("classes", []))


def compose(verdicts: Iterable[Mapping], lane: str, *, required: Sequence[str] = (),
            gating_sets: Mapping[str, Mapping] = LANE_GATING) -> dict:
    """Compose one take's verdict for one lane from its detector verdicts."""
    stages, classes = _gating_set(lane, gating_sets)
    normalized: dict[str, dict] = {}
    for verdict in verdicts:
        entry = normalize(verdict)
        if entry["detector"] in normalized:
            raise CompositionError(f"duplicate verdict for {entry['detector']}")
        entry["gating"] = entry["stage"] in stages or entry["class"] in classes
        normalized[entry["detector"]] = entry
    for detector in required:
        if detector not in normalized:
            normalized[detector] = {"detector": detector, "class": None, "stage": None, "judges": [],
                                    "calibration": None, "reportedStatus": None, "status": "unavailable",
                                    "reasons": ["missing-verdict"], "legacy": False, "gating": True}
        else:
            normalized[detector]["gating"] = True
    ordered = [normalized[key] for key in sorted(normalized)]
    gating = [entry for entry in ordered if entry["gating"]]
    if not gating:
        status, deciding = "unavailable", []
        lane_reasons = ["no-gating-verdict"]
    else:
        lane_reasons = []
        status, deciding = "pass", []
        for candidate in PRECEDENCE[:-1]:
            pool = ordered if candidate == "warn" else gating
            deciding = [entry["detector"] for entry in pool if entry["status"] == candidate]
            if deciding:
                status = TAKE_STATUS_OF[candidate]
                break
    return {
        "schema": SCHEMA,
        "lane": lane,
        "composition": COMPOSITION,
        "status": status,
        "decidedBy": deciding,
        "reasons": lane_reasons,
        "gating": [entry["detector"] for entry in gating],
        "advisory": [entry["detector"] for entry in ordered if not entry["gating"]],
        "verdicts": ordered,
    }
