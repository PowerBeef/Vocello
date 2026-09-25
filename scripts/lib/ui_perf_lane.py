"""Where a ui-perf lane's time went (audit #82), shared by the macOS and iOS checkers.

Each scenario's XCUITest prints one ``VOCELLO_UIPERF_SETUP=<base64 JSON>`` line
with wall-clock stamps from its launch to the end of its measured window
(``launchStart``, ``launchReady``, ``settled``, ``windowStart``, ``windowEnd``);
the lane's required-step ledger (``required-steps.json``) records when each
step completed. The report's ``lanePhases`` combines both, so the share of the
lane spent inside measured windows is measured rather than inferred. Report
only: nothing here gates a run or enters a record.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from pathlib import Path
from typing import Iterable

SETUP_PREFIX = "VOCELLO_UIPERF_SETUP="
SETUP_KEYS = ("launchStart", "launchReady", "settled", "windowStart", "windowEnd")


def parse_setup_markers(log_path: Path) -> dict[str, dict[str, int]]:
    """Each scenario's setup stamps; a log from before the stamps yields none, and
    a malformed line is skipped: the stamps describe the lane, never gate it."""
    stamps: dict[str, dict[str, int]] = {}
    for line in Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines():
        index = line.find(SETUP_PREFIX)
        if index < 0:
            continue
        try:
            marker = json.loads(base64.b64decode(line[index + len(SETUP_PREFIX):].strip()))
        except Exception:
            continue
        scenario, values = marker.get("scenario"), marker.get("stamps")
        if isinstance(scenario, str) and isinstance(values, dict):
            stamps[scenario] = {
                key: int(value) for key, value in values.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            }
    return stamps


def _ledger_time(value) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_ledger(path: Path | None) -> dict | None:
    if path is None or not Path(path).is_file():
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def lane_phases(
    setup: dict[str, dict[str, int]], ledger: dict | None, scenarios: Iterable[str],
) -> dict:
    """Per scenario (in lane order): launch, settle, pre-window setup and the
    measured window; the windows' share of the time from each launch to its
    window's end; and the ledger's steps in completion order with the seconds
    since the previous step completed."""
    rows = []
    for name in scenarios:
        stamps = setup.get(name) or {}
        if not set(SETUP_KEYS) <= set(stamps):
            continue
        rows.append({
            "scenario": name,
            "launchMS": stamps["launchReady"] - stamps["launchStart"],
            "settleMS": stamps["settled"] - stamps["launchReady"],
            "setupMS": stamps["windowStart"] - stamps["settled"],
            "windowMS": stamps["windowEnd"] - stamps["windowStart"],
            "totalMS": stamps["windowEnd"] - stamps["launchStart"],
        })
    total = sum(item["totalMS"] for item in rows)
    result: dict = {
        "scenarios": rows,
        "windowShare": round(sum(item["windowMS"] for item in rows) / total, 4) if total > 0 else None,
    }
    if isinstance(ledger, dict) and isinstance(ledger.get("results"), dict):
        previous = _ledger_time(ledger.get("startedAt"))
        steps = []
        ordered = sorted(
            ((step, entry) for step, entry in ledger["results"].items()
             if isinstance(entry, dict) and _ledger_time(entry.get("completedAt"))),
            key=lambda item: _ledger_time(item[1]["completedAt"]),
        )
        for step, entry in ordered:
            completed = _ledger_time(entry["completedAt"])
            steps.append({
                "step": step,
                "status": entry.get("status"),
                "secondsSincePrevious": round((completed - previous).total_seconds(), 1) if previous else None,
            })
            previous = completed
        result["steps"] = steps
    return result
