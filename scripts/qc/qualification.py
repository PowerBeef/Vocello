"""Private, report-only qualification of retained QC event candidates.

This module runs no inference and grants no detector or acceptance-policy level.
The panel explicitly records annotation coverage and leakage groups; absence of a
label or of an acoustic result is never a clean negative. Historical QC fit/eval
artifacts are intentionally not rewritten by this diagnostic evaluation.
"""
from __future__ import annotations

import hashlib
import math
import re
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from qc import store

PANEL_SCHEMA = "vocello.qc.panel/1"
EVENTS_SCHEMA = "vocello.qc.events/1"
REPORT_SCHEMA = "vocello.qc.qualification/1"
MATCHING_CONTRACT = "vocello.qc.event-matching/1"
GROUPS = ("speaker", "reference", "source", "prompt", "derived")
SPLITS = {"train", "calibration", "heldout"}
LABEL_COVERAGE = {"complete", "positive-only", "uncertain", "unreviewed"}
INPUT_STATUS = {"complete", "partial", "unavailable", "unsupported"}
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")


class QualificationError(ValueError):
    """Retained evidence cannot support the requested diagnostic evaluation."""


def _digest(path: Path) -> str:
    # Verify current bytes, rather than trusting a memo keyed only by file metadata.
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _identifier(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QualificationError(f"{what}: a nonempty identity is required")
    return value


def _sha(value: Any, what: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise QualificationError(f"{what}: an exact SHA-256 is required")
    return value


def _number(value: Any, what: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise QualificationError(f"{what}: a finite number is required")
    return float(value)


def _private(layout: store.Layout, path: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(layout.private.resolve()):
        raise QualificationError("panel and evaluation output must remain under the private QC store")
    return path


def _models(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        raise QualificationError("models: an explicit identity map is required")
    result = {}
    for role, item in value.items():
        _identifier(role, "model role")
        if not isinstance(item, dict):
            raise QualificationError("model identity must be an object")
        if item.get("available") is False:
            continue
        result[role] = {"id": _identifier(item.get("id"), "model id"),
                        "runnerSHA256": _sha(item.get("runnerSHA256"), "runnerSHA256")}
    return result


def _events(value: Any, duration: float, *, labels: bool, classes: set[str]) -> list[dict]:
    if not isinstance(value, list):
        raise QualificationError("events: an explicit list is required")
    ids = set()
    result = []
    for item in value:
        if not isinstance(item, dict):
            raise QualificationError("event must be an object")
        event_id = _identifier(item.get("id"), "event id")
        if event_id in ids:
            raise QualificationError("duplicate event id")
        ids.add(event_id)
        class_id = _identifier(item.get("class"), "event class")
        if labels and class_id not in classes:
            raise QualificationError("label event class is outside the panel classes")
        start = _number(item.get("start"), "event start")
        end = _number(item.get("end"), "event end")
        if start < 0 or end <= start or end > duration:
            raise QualificationError("event span is reversed, empty or outside the audio duration")
        if not labels and item.get("status") != "candidate":
            raise QualificationError("event evidence must be descriptive candidates, not truth or acceptance")
        result.append(dict(item, start=start, end=end))
    return result


def _identity(document: dict, scoring: str, models: dict) -> None:
    if document.get("scoringSHA256") != scoring:
        raise QualificationError("retained scoring identity differs from the panel")
    if _models(document.get("models")) != models:
        raise QualificationError("retained model identities differ from the panel")


def _load_runs(layout: store.Layout, run_ids: Iterable[str], scoring: str,
               models: dict) -> tuple[dict[str, dict], dict[str, dict]]:
    rows, receipts = {}, {}
    names = list(run_ids)
    if not names or len(names) != len(set(names)):
        raise QualificationError("name distinct retained run IDs")
    for run_id in names:
        if not isinstance(run_id, str) or not NAME.fullmatch(run_id):
            raise QualificationError("invalid retained run ID")
        directory = _private(layout, layout.runs / run_id)
        files = {name: directory / name for name in ("takes.json", "features.json", "events.json")}
        documents = {name: store.read_json(path) for name, path in files.items()}
        if any(not isinstance(document, dict) for document in documents.values()):
            raise QualificationError("retained documents must be objects")
        takes, features, events = (documents[name] for name in files)
        if takes.get("schema") != store.TAKES_SCHEMA or events.get("schema") != EVENTS_SCHEMA:
            raise QualificationError("unsupported takes or events schema")
        if features.get("schema") != "vocello.qc.features/1":
            raise QualificationError("unsupported features schema")
        if events.get("run") != run_id or features.get("run") != run_id:
            raise QualificationError("retained run identity differs from its directory")
        _identity(features, scoring, models)
        _identity(events, scoring, models)
        for document in (takes, features, events):
            if (not isinstance(document.get("takes"), list)
                    or any(not isinstance(item, dict) for item in document["takes"])):
                raise QualificationError("retained take inventories must be lists of objects")
        feature_tokens = [_identifier(item.get("token"), "feature take token") for item in features["takes"]]
        event_rows = events.get("takes")
        if not isinstance(event_rows, list) or len(feature_tokens) != len(set(feature_tokens)):
            raise QualificationError("malformed retained take rows")
        by_token = {}
        for item in event_rows:
            token = _identifier(item.get("token"), "event take token")
            if token in by_token:
                raise QualificationError("duplicate event take token")
            by_token[token] = item
        if set(feature_tokens) != set(by_token):
            raise QualificationError("feature and event take inventories differ")
        seen = set()
        for take in takes.get("takes", []):
            token = _identifier(take.get("token"), "take token")
            if token in rows or token in seen:
                raise QualificationError("duplicate take token across retained runs")
            seen.add(token)
            if token not in by_token:
                raise QualificationError("take lacks retained event evidence")
            rows[token] = {"take": take, "evidence": by_token[token], "run": run_id}
        if seen != set(by_token):
            raise QualificationError("take and event inventories differ")
        receipts[run_id] = {name: _digest(path) for name, path in files.items()}
    return rows, receipts


def _load_panel(layout: store.Layout, panel_path: Path, run_ids: Iterable[str]) -> tuple[dict, list[dict], dict]:
    panel = store.read_json(panel_path)
    if not isinstance(panel, dict) or panel.get("schema") != PANEL_SCHEMA:
        raise QualificationError("unsupported private panel schema")
    _identifier(panel.get("id"), "panel id")
    if panel.get("purpose") not in {"challenge", "deployment"}:
        raise QualificationError("panel purpose must be challenge or deployment")
    scoring = _sha(panel.get("scoringSHA256"), "scoringSHA256")
    _sha(panel.get("annotationProtocolSHA256"), "annotationProtocolSHA256")
    models = _models(panel.get("models"))
    classes = panel.get("classes")
    if (not isinstance(classes, list) or not classes or any(not isinstance(c, str) or not c.strip() for c in classes)
            or len(set(classes)) != len(classes)):
        raise QualificationError("declare distinct panel classes")
    policy = panel.get("policy")
    if not isinstance(policy, dict) or set(policy) != {"minimumIntersectionOverUnion"}:
        raise QualificationError("declare the supported event-matching policy explicitly")
    iou = _number(policy["minimumIntersectionOverUnion"], "minimumIntersectionOverUnion")
    if not 0 < iou <= 1:
        raise QualificationError("minimumIntersectionOverUnion must be greater than zero and at most one")
    if _sha(panel.get("policySHA256"), "policySHA256") != store.sha256_text(store.canonical_json(policy)):
        raise QualificationError("policy digest mismatch")
    records, receipts = _load_runs(layout, run_ids, scoring, models)
    panel_rows = panel.get("takes")
    if not isinstance(panel_rows, list) or not panel_rows:
        raise QualificationError("panel must enumerate its takes")
    seen, grouped, audio_splits, reference_splits, result = set(), {}, {}, {}, []
    for item in panel_rows:
        if not isinstance(item, dict):
            raise QualificationError("panel take must be an object")
        token = _identifier(item.get("token"), "panel take token")
        if token in seen or token not in records:
            raise QualificationError("duplicate or unavailable panel take")
        seen.add(token)
        take, evidence = records[token]["take"], records[token]["evidence"]
        digest = _sha(item.get("audioSHA256"), "panel audioSHA256")
        if digest != take.get("audioSHA256") or digest != evidence.get("audioSHA256"):
            raise QualificationError("audio identity differs between panel and run")
        audio = Path(take.get("audio") or "")
        if not audio.is_file() or _digest(audio) != digest:
            raise QualificationError("audio bytes differ from retained identity")
        try:
            with wave.open(str(audio), "rb") as handle:
                duration = handle.getnframes() / handle.getframerate()
        except (wave.Error, EOFError, ZeroDivisionError) as error:
            raise QualificationError("cannot verify WAV duration") from error
        if duration <= 0 or _number(evidence.get("durationSeconds"), "durationSeconds") != duration:
            raise QualificationError("retained duration differs from audio frames")
        split = item.get("split")
        if split not in SPLITS:
            raise QualificationError("every take needs an explicit train/calibration/heldout split")
        groups = item.get("groups")
        if not isinstance(groups, dict) or set(groups) != set(GROUPS):
            raise QualificationError("speaker/reference/source/prompt/derived group identities are required")
        for kind, group in groups.items():
            if kind == "reference" and group is None:
                if take.get("reference") or take.get("referenceSHA256"):
                    raise QualificationError("reference group is missing for a reference-conditioned take")
                continue
            group = _identifier(group, f"{kind} group")
            key = (kind, group)
            if key in grouped and grouped[key] != split:
                raise QualificationError(f"{kind} group leaks across panel splits")
            grouped[key] = split
        if digest in audio_splits and audio_splits[digest] != split:
            raise QualificationError("identical audio leaks across panel splits")
        audio_splits[digest] = split
        if take.get("reference") or take.get("referenceSHA256"):
            reference_digest = _sha(take.get("referenceSHA256"), "referenceSHA256")
            reference = Path(take.get("reference") or "")
            if not reference.is_file() or _digest(reference) != reference_digest:
                raise QualificationError("reference bytes differ from retained identity")
            if reference_digest in reference_splits and reference_splits[reference_digest] != split:
                raise QualificationError("identical reference audio leaks across panel splits")
            reference_splits[reference_digest] = split
        if item.get("origin") not in {"human-observed", "synthetic-control"}:
            raise QualificationError("declare human-observed or synthetic-control label origin")
        coverage = item.get("labelCoverage")
        if (not isinstance(coverage, dict) or set(coverage) != set(classes)
                or any(value not in LABEL_COVERAGE for value in coverage.values())):
            raise QualificationError("explicit per-class annotation coverage is required")
        labels = _events(item.get("events"), duration, labels=True, classes=set(classes))
        if any(coverage[event["class"]] not in {"complete", "positive-only"} for event in labels):
            raise QualificationError("event truth requires complete or positive-only annotation coverage")
        candidates = _events(evidence.get("events"), duration, labels=False, classes=set(classes))
        if evidence.get("inputStatus") not in INPUT_STATUS:
            raise QualificationError("explicit retained inputStatus is required")
        dimensions = evidence.get("dimensions") or {}
        if not isinstance(dimensions, dict):
            raise QualificationError("retained dimensions must be an object")
        result.append(dict(item, durationSeconds=duration, events=labels, candidates=candidates,
                           inputStatus=evidence["inputStatus"], dimensions=dimensions,
                           run=records[token]["run"]))
    if not any(row["split"] == "heldout" for row in result):
        raise QualificationError("panel has no protected heldout takes")
    return panel, result, receipts


def _matches(truth: list[dict], candidates: list[dict], minimum: float) -> list[tuple[int, int]]:
    """Maximum-cardinality bipartite matching; each annotation/candidate is used once."""
    edges = []
    for label in truth:
        targets = []
        for index, candidate in enumerate(candidates):
            intersection = max(0.0, min(label["end"], candidate["end"]) - max(label["start"], candidate["start"]))
            union = max(label["end"], candidate["end"]) - min(label["start"], candidate["start"])
            if intersection / union >= minimum:
                targets.append(index)
        edges.append(targets)
    assigned: dict[int, int] = {}

    def visit(index: int, visited: set[int]) -> bool:
        for candidate in edges[index]:
            if candidate in visited:
                continue
            visited.add(candidate)
            if candidate not in assigned or visit(assigned[candidate], visited):
                assigned[candidate] = index
                return True
        return False

    for index in range(len(truth)):
        visit(index, set())
    return sorted((index, candidate) for candidate, index in assigned.items())


def _ratio(numerator: int | float, denominator: int | float) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _metrics(rows: list[dict], class_id: str, minimum: float) -> dict:
    tp, fp, fn, assessed_positive, assessed_hits = 0, 0, 0, 0, 0
    clean, clean_assessed, clean_flagged, available, labelled, seconds = 0, 0, 0, 0, 0, 0.0
    details = []
    defective_clips, missed_clips = 0, 0
    for row in rows:
        coverage = row["labelCoverage"][class_id]
        truth = [event for event in row["events"] if event["class"] == class_id]
        candidates = [event for event in row["candidates"] if event["class"] == class_id]
        dimension = row["dimensions"].get(class_id) or {}
        if not isinstance(dimension, dict):
            raise QualificationError("retained class dimension must be an object")
        status = dimension.get("inputStatus", "unsupported" if dimension.get("decision") == "not-assessed"
                               else row["inputStatus"])
        if status not in INPUT_STATUS:
            raise QualificationError("dimension inputStatus must be explicit and supported")
        complete = status == "complete"
        available += complete
        if coverage not in {"complete", "positive-only"}:
            details.append({"token": row["token"], "status": "unlabelled", "inputStatus": status})
            continue
        labelled += 1
        matched = _matches(truth, candidates, minimum) if complete else []
        defective_clips += bool(truth)
        missed_clips += bool(truth) and not matched
        tp += len(matched)
        fn += len(truth) - len(matched)
        if complete:
            assessed_positive += len(truth)
            assessed_hits += len(matched)
        if coverage == "complete":
            clean += not truth
            if complete:
                fp += len(candidates) - len(matched)
                seconds += row["durationSeconds"]
                clean_assessed += not truth
                clean_flagged += bool(candidates) and not truth
        details.append({"token": row["token"], "status": "assessed" if complete else "abstained",
                        "inputStatus": status, "labelCoverage": coverage,
                        "truthEvents": len(truth), "candidateEvents": len(candidates),
                        "matched": [{"label": truth[a]["id"], "candidate": candidates[b]["id"]} for a, b in matched]})
    # Positive-only annotations cannot establish precision: unannotated events may be real.
    precision_supported = all(row["labelCoverage"][class_id] == "complete" for row in rows)
    return {"truePositives": tp, "falsePositives": fp, "falseNegatives": fn,
            "precision": _ratio(tp, tp + fp) if precision_supported else None,
            "precisionSupported": precision_supported, "recall": _ratio(tp, tp + fn),
            "conditionalRecall": _ratio(assessed_hits, assessed_positive),
            "defectiveClips": defective_clips, "missedDefectiveClips": missed_clips,
            "clipMissRate": _ratio(missed_clips, defective_clips),
            "inputCoverage": {"completeClips": available, "totalClips": len(rows), "rate": _ratio(available, len(rows))},
            "labelledClips": labelled, "cleanClips": clean, "assessedCleanClips": clean_assessed,
            "falsePositiveClips": clean_flagged, "cleanClipFalsePositiveRate": _ratio(clean_flagged, clean_assessed),
            "falseAlarmsPerMinute": _ratio(fp, seconds / 60), "takes": details}


def evaluate(layout: store.Layout, panel_path: Path | str, *, run_ids: Iterable[str],
             name: str | None = None) -> tuple[Path, dict]:
    """Validate exact private inputs and evaluate heldout candidates; never qualify gates.

    The caller must provide fresh run IDs explicitly. Output directories are immutable:
    a rerun needs a new name and preserves every earlier diagnostic report.
    """
    path = _private(layout, Path(panel_path))
    panel_digest = _digest(path)
    evaluator_path = Path(__file__)
    evaluator_digest = _digest(evaluator_path)
    panel, rows, receipts = _load_panel(layout, path, run_ids)
    now = datetime.now(timezone.utc)
    name = name or f"qualification-{now:%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
    if not NAME.fullmatch(name):
        raise QualificationError("invalid private evaluation name")
    directory = _private(layout, layout.private / "qualification" / name)
    if directory.exists():
        raise QualificationError("evaluation already exists; retain it and choose a new identity")
    heldout = [row for row in rows if row["split"] == "heldout"]
    minimum = panel["policy"]["minimumIntersectionOverUnion"]
    report = {"schema": REPORT_SCHEMA, "evaluation": name, "createdAt": now.isoformat(),
              "panel": panel["id"], "panelSHA256": panel_digest, "policySHA256": panel["policySHA256"],
              "annotationProtocolSHA256": panel["annotationProtocolSHA256"],
              "scoringSHA256": panel["scoringSHA256"], "models": _models(panel["models"]), "runFiles": receipts,
              "purpose": panel["purpose"], "reportOnly": True, "qualification": "not-qualified",
              "acceptancePolicyChanged": False, "matchingPolicy": panel["policy"],
              "evaluator": {"file": "scripts/qc/qualification.py", "sha256": evaluator_digest,
                            "contract": MATCHING_CONTRACT},
              "splits": {split: sum(row["split"] == split for row in rows) for split in sorted(SPLITS)},
              "heldoutOrigins": {origin: sum(row["origin"] == origin for row in heldout)
                                 for origin in ("human-observed", "synthetic-control")},
              "limitations": ["candidate-matching-is-not-acceptance-qualification", "point-estimates-only",
                              "declared-group-disjointness-does-not-prove-complete-training-provenance",
                              "challenge-panel-precision-is-not-deployment-risk"],
              "classes": {class_id: _metrics(heldout, class_id, minimum) for class_id in panel["classes"]}}
    if any(row["origin"] == "synthetic-control" for row in heldout):
        report["limitations"].append("synthetic-controls-do-not-establish-real-failure-recall")
    if _digest(path) != panel_digest or _digest(evaluator_path) != evaluator_digest or any(
            _digest(layout.runs / run_id / filename) != digest
            for run_id, files in receipts.items() for filename, digest in files.items()):
        raise QualificationError("qualification inputs changed during evaluation")
    directory.mkdir(parents=True, exist_ok=False)
    output = directory / "report.json"
    store.write_json_atomic(output, report)
    return output, report
