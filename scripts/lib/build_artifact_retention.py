#!/usr/bin/env python3
"""Read-only child-artifact lifecycle analysis for repository build output.

The top-level build-output manifest classifies roots.  This module classifies
the run directories below the XCUITest artifact root so inventory and cleanup
share one decision model.  It deliberately performs no deletion.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable


UI_LANES = frozenset({"smoke", "benchmark", "model-download"})
UI_SUCCESS_STATUSES = frozenset({"pass", "passed", "passedWithWarnings"})
UI_FAILURE_STATUSES = frozenset({"failed"})
UI_ACTIVE_STATUSES = frozenset({"running"})
UI_PIN_FILENAME = "retention-pin.json"
UI_COMPACT_FILENAME = "retention-summary.json"


HistoryValidator = Callable[[str, str], bool]


@dataclass(frozen=True)
class UIArtifactDecision:
    path: str
    platform: str | None
    lane: str | None
    runID: str | None
    status: str | None
    allocatedBytes: int
    action: str
    reason: str
    reclaimableBytes: int

    def json_value(self) -> dict[str, Any]:
        return asdict(self)


def load_json_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def allocated_bytes(path: Path) -> int:
    if not path.exists() and not path.is_symlink():
        return 0
    try:
        if path.is_symlink() or path.is_file():
            return path.lstat().st_blocks * 512
    except FileNotFoundError:
        return 0
    total = 0
    for parent, directories, files in os.walk(path, followlinks=False):
        parent_path = Path(parent)
        kept: list[str] = []
        for name in directories:
            child = parent_path / name
            try:
                if child.is_symlink():
                    total += child.lstat().st_blocks * 512
                else:
                    kept.append(name)
            except FileNotFoundError:
                continue
        directories[:] = kept
        for name in files:
            try:
                total += (parent_path / name).lstat().st_blocks * 512
            except FileNotFoundError:
                continue
    return total


def _relative(path: Path, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return path.as_posix()


def _pinned(run_dir: Path) -> bool:
    marker = load_json_object(run_dir / UI_PIN_FILENAME)
    return bool(marker and marker.get("schemaVersion") == 1 and marker.get("pinned") is True)


def _matching_history_lightweight(repo_root: Path, run_id: str, platform: str) -> bool:
    record = load_json_object(
        repo_root / "benchmarks" / "runs" / "ui-generation" / f"{run_id}.json"
    )
    if not record:
        return False
    run = record.get("run")
    return bool(
        isinstance(run, dict)
        and run.get("id") == run_id
        and run.get("kind") == "ui-generation"
        and run.get("platform") == platform
        and run.get("status") in UI_SUCCESS_STATUSES
    )


def _repairable_benchmark(run_dir: Path, run_id: str, platform: str) -> bool:
    """Require a frozen or validator-owned matching record before preserving repair data."""

    for name in ("benchmark-history-record.json", "benchmark-evidence.json"):
        outer = load_json_object(run_dir / name)
        if not outer:
            continue
        candidate = outer.get("historyRecord", outer)
        if not isinstance(candidate, dict):
            continue
        run = candidate.get("run")
        if not isinstance(run, dict):
            continue
        if (
            run.get("id") == run_id
            and run.get("platform") == platform
            and run.get("kind", "ui-generation") == "ui-generation"
            and run.get("status") in UI_SUCCESS_STATUSES
        ):
            return True
    return False


def _run_sort_key(metadata: dict[str, Any], run_id: str) -> tuple[str, str]:
    timestamp = metadata.get("finishedAt") or metadata.get("startedAt") or ""
    return (timestamp if isinstance(timestamp, str) else "", run_id)


def _decision(
    *,
    run_dir: Path,
    repo_root: Path,
    metadata: dict[str, Any] | None,
    action: str,
    reason: str,
) -> UIArtifactDecision:
    allocated = allocated_bytes(run_dir)
    reclaimable = allocated if action in {"remove", "compact"} else 0
    return UIArtifactDecision(
        path=_relative(run_dir, repo_root),
        platform=(metadata or {}).get("platform"),
        lane=(metadata or {}).get("lane"),
        runID=(metadata or {}).get("runID"),
        status=(metadata or {}).get("status"),
        allocatedBytes=allocated,
        action=action,
        reason=reason,
        reclaimableBytes=reclaimable,
    )


def analyze_ui_artifacts(
    *,
    repo_root: Path,
    ui_root: Path,
    keep_passing: int = 1,
    keep_unresolved_failures: int = 1,
    lanes: Iterable[str] = UI_LANES,
    history_validator: HistoryValidator | None = None,
) -> list[UIArtifactDecision]:
    if keep_passing < 1 or keep_unresolved_failures < 1:
        raise ValueError("UI retention counts must be at least one")
    allowed_lanes = frozenset(lanes)
    validate_history = history_validator or (
        lambda run_id, platform: _matching_history_lightweight(repo_root, run_id, platform)
    )
    decisions: list[UIArtifactDecision] = []
    groups: dict[
        tuple[str, str], list[tuple[tuple[str, str], Path, dict[str, Any]]]
    ] = {}

    if not ui_root.is_dir() or ui_root.is_symlink():
        return decisions
    for platform_root in sorted(ui_root.iterdir(), key=lambda item: item.name):
        if platform_root.name not in {"macos", "ios"} or not platform_root.is_dir() or platform_root.is_symlink():
            continue
        for run_dir in sorted(platform_root.iterdir(), key=lambda item: item.name):
            if not run_dir.is_dir() or run_dir.is_symlink():
                continue
            if (run_dir / UI_COMPACT_FILENAME).is_file():
                metadata = load_json_object(run_dir / "run.json")
                extras = {
                    child.name
                    for child in run_dir.iterdir()
                    if child.name not in {"run.json", UI_COMPACT_FILENAME, UI_PIN_FILENAME}
                }
                action = "compact" if extras else "retain"
                reason = "incomplete-compaction" if extras else "already-compacted"
                if _pinned(run_dir):
                    action, reason = "retain", "explicitly-pinned"
                decisions.append(
                    _decision(
                        run_dir=run_dir,
                        repo_root=repo_root,
                        metadata=metadata,
                        action=action,
                        reason=reason,
                    )
                )
                continue
            metadata = load_json_object(run_dir / "run.json")
            if _pinned(run_dir):
                decisions.append(
                    _decision(
                        run_dir=run_dir,
                        repo_root=repo_root,
                        metadata=metadata,
                        action="retain",
                        reason="explicitly-pinned",
                    )
                )
                continue
            if not metadata:
                decisions.append(
                    _decision(
                        run_dir=run_dir,
                        repo_root=repo_root,
                        metadata=None,
                        action="retain",
                        reason="legacy-or-malformed-metadata",
                    )
                )
                continue
            lane = metadata.get("lane")
            run_id = metadata.get("runID")
            status = metadata.get("status")
            if not (
                metadata.get("platform") == platform_root.name
                and isinstance(lane, str)
                and lane in allowed_lanes
                and isinstance(run_id, str)
                and run_id == run_dir.name
                and status in UI_SUCCESS_STATUSES | UI_FAILURE_STATUSES | UI_ACTIVE_STATUSES
            ):
                decisions.append(
                    _decision(
                        run_dir=run_dir,
                        repo_root=repo_root,
                        metadata=metadata,
                        action="retain",
                        reason="legacy-or-malformed-metadata",
                    )
                )
                continue
            groups.setdefault((platform_root.name, lane), []).append(
                (_run_sort_key(metadata, run_id), run_dir, metadata)
            )

    for (platform, lane), candidates in sorted(groups.items()):
        candidates.sort(key=lambda item: item[0], reverse=True)
        successes = [item for item in candidates if item[2]["status"] in UI_SUCCESS_STATUSES]
        failures = [item for item in candidates if item[2]["status"] in UI_FAILURE_STATUSES]
        active = [item for item in candidates if item[2]["status"] in UI_ACTIVE_STATUSES]
        newest_success_key = successes[0][0] if successes else None

        for index, (_, run_dir, metadata) in enumerate(successes):
            run_id = metadata["runID"]
            if index < keep_passing:
                action, reason = "retain", "latest-passing-result"
            elif lane == "benchmark" and not validate_history(run_id, platform):
                if _repairable_benchmark(run_dir, run_id, platform):
                    action, reason = "retain", "benchmark-publication-repair-evidence"
                else:
                    action, reason = "compact", "unrepairable-unpublished-benchmark"
            else:
                action, reason = "remove", "superseded-passing-result"
            decisions.append(
                _decision(
                    run_dir=run_dir,
                    repo_root=repo_root,
                    metadata=metadata,
                    action=action,
                    reason=reason,
                )
            )

        unresolved = [
            item for item in failures
            if newest_success_key is None or item[0] > newest_success_key
        ]
        unresolved_paths = {
            item[1] for item in unresolved[:keep_unresolved_failures]
        }
        for _, run_dir, metadata in failures:
            if run_dir in unresolved_paths:
                action, reason = "retain", "latest-unresolved-failure"
            else:
                action, reason = "compact", (
                    "resolved-by-newer-pass" if newest_success_key is not None else "superseded-failure"
                )
            if _pinned(run_dir):
                action, reason = "retain", "explicitly-pinned"
            decisions.append(
                _decision(
                    run_dir=run_dir,
                    repo_root=repo_root,
                    metadata=metadata,
                    action=action,
                    reason=reason,
                )
            )

        for _, run_dir, metadata in active:
            decisions.append(
                _decision(
                    run_dir=run_dir,
                    repo_root=repo_root,
                    metadata=metadata,
                    action="retain",
                    reason="active-or-interrupted-run",
                )
            )

    return sorted(decisions, key=lambda item: item.path)


def summarize_decisions(decisions: Iterable[UIArtifactDecision]) -> dict[str, Any]:
    values = list(decisions)
    actions: dict[str, dict[str, int]] = {}
    reasons: dict[str, dict[str, int]] = {}
    for decision in values:
        action = actions.setdefault(decision.action, {"count": 0, "bytes": 0})
        action["count"] += 1
        action["bytes"] += decision.allocatedBytes
        reason = reasons.setdefault(decision.reason, {"count": 0, "bytes": 0})
        reason["count"] += 1
        reason["bytes"] += decision.allocatedBytes
    return {
        "allocatedBytes": sum(item.allocatedBytes for item in values),
        "reclaimableBytes": sum(item.reclaimableBytes for item in values),
        "blockedBytes": sum(
            item.allocatedBytes for item in values if item.action == "retain"
        ),
        "actions": actions,
        "reasons": reasons,
        "runs": [item.json_value() for item in values],
    }
