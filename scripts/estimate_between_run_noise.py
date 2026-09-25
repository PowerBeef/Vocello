#!/usr/bin/env python3
"""Estimate the gate's between-run noise from identical-source runs (audit #106).

The engine gate compares a run's warm medians with a baseline pooled from
seeded runs, each metric against the largest of its floor, three median
absolute deviations of the baseline's own takes (the "gate MAD") and the range
of the pooled runs (`summarize_generation_telemetry.metric_threshold`). Three
MADs of five takes on one run describe within-run noise; drift between runs of
identical source is a different quantity, and the audit's recommendation
(delegated by the maintainer on 2026-09-25) is to estimate it before the gate
MAD changes. This tool is that estimate. It never edits a threshold.

For every group of runs that share the gate identity (hardware, matrix and
seed, models) and one clean source commit, it reports per cell and metric:

- the run medians, their relative range and the relative MAD of the run
  medians (between-run noise), beside the median within-run relative MAD and
  the 3-MAD threshold it yields;
- a leave-one-run-out replay of the gate itself (`pooled_cells` and
  `compare_summaries` from the summarizer): each run is judged against the pool
  of the others, so every flagged metric is a false regression on identical
  source.

The evidence suffices to propose a gate-MAD change only when a group holds at
least `MINIMUM_POOLED_RUNS + 1` identical-source runs on the canonical host,
so every left-out run faces a pool the gate itself would accept.

Sources: committed history records (`--records`, filtered by `--label`) and
governed baseline documents (`--baseline`, their `seededRuns`).

Usage:
  scripts/estimate_between_run_noise.py --records benchmarks/runs/engine-generation --label mac-gate-bench
  scripts/estimate_between_run_noise.py --baseline benchmarks/baselines/mac-gate-bench.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
from typing import Any, Iterable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from summarize_generation_telemetry import (  # noqa: E402
    COMPARED_METRICS,
    MINIMUM_POOLED_RUNS,
    compare_summaries,
    mad,
    metric_threshold,
    pooled_cells,
)

REPORT_SCHEMA = 1
CANONICAL_HOST_PROFILES = frozenset({"mac-mini-m6-16gb"})
# Tracked take metric -> the gate's cell metric (and its MAD key).
TAKE_METRICS = {
    "rtf": ("rtf", "rtfMAD"),
    "tokensPerSecond": ("tokps", None),
    "peakPhysicalFootprintMB": ("physFootMB", "physFootMAD"),
    "mlxPeakMB": ("mlxPeakMB", "mlxPeakMAD"),
}
QC_ORDER = {"pass": 0, "warn": 1, "fail": 2}


class NoiseError(RuntimeError):
    """The evidence cannot form a between-run estimate."""


def run_cells_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-run cell summaries (the summarizer's cell shape) from a record's takes."""
    by_key: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for take in record.get("takes") or []:
        key = (str(take.get("mode")), str(take.get("modelID")), str(take.get("warmState")),
               str(take.get("length")))
        by_key.setdefault(key, []).append(take)
    cells = []
    for key, takes in by_key.items():
        cell: dict[str, Any] = {
            "cellKey": list(key), "mode": key[0], "modelID": key[1],
            "warmState": key[2], "lenBucket": key[3], "n": len(takes),
            "ttfcMS": None, "engineFirstChunkMS": None,
        }
        for source, (metric, mad_key) in TAKE_METRICS.items():
            values = [
                float(take["metrics"][source]) for take in takes
                if isinstance((take.get("metrics") or {}).get(source), (int, float))
            ]
            cell[metric] = statistics.median(values) if values else None
            if mad_key:
                cell[mad_key] = mad(values)
        verdicts = [str((take.get("audioQC") or {}).get("verdict", "pass")) for take in takes]
        cell["qcVerdict"] = max(verdicts, key=lambda verdict: QC_ORDER.get(verdict, 3))
        cells.append(cell)
    return cells


def runs_from_records(paths: Iterable[Path], label: str | None) -> list[dict[str, Any]]:
    runs = []
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        record = value.get("historyRecord", value) if isinstance(value, dict) else {}
        run = record.get("run") or {}
        if label is not None and run.get("label") != label:
            continue
        source = record.get("source") or {}
        if source.get("dirty") is not False:
            continue
        identity = {
            "hardwareProfile": (record.get("hardware") or {}).get("profileID"),
            "matrixHash": (record.get("inputs") or {}).get("matrixHash"),
            "models": sorted(str(model.get("integrityDigest")) for model in record.get("models") or []),
            "telemetrySchemaVersion": (record.get("evidence") or {}).get("telemetrySchemaVersion"),
            "qcAlgorithmVersion": (record.get("evidence") or {}).get("qcAlgorithmVersion"),
        }
        runs.append({
            "runID": run.get("id"), "sourceCommit": source.get("commit"),
            "identity": identity, "cells": run_cells_from_record(record),
        })
    return runs


def runs_from_baseline(path: Path) -> list[dict[str, Any]]:
    document = json.loads(path.read_text(encoding="utf-8"))
    seeded = document.get("seededRuns") if isinstance(document, dict) else None
    if not isinstance(seeded, list) or not seeded:
        raise NoiseError(f"{path.name} holds no seeded runs")
    identity = document.get("identity") or {}
    return [
        {
            "runID": run.get("runID"), "sourceCommit": run.get("sourceCommit"),
            "identity": {
                "hardwareProfile": identity.get("hardwareProfile"),
                "matrixHash": identity.get("matrixHash"),
                "models": sorted(str(model.get("integrityDigest")) for model in identity.get("models") or []),
                "telemetrySchemaVersion": identity.get("telemetrySchemaVersion"),
                "qcAlgorithmVersion": identity.get("qcAlgorithmVersion"),
            },
            "cells": run.get("cells") or [],
        }
        for run in seeded
    ]


def relative(value: float | None, reference: float | None) -> float | None:
    if value is None or not reference:
        return None
    return value / abs(reference)


def group_estimate(runs: list[dict[str, Any]], states: tuple[str, ...]) -> dict[str, Any]:
    """Between-run noise and the leave-one-run-out gate replay for one source group."""
    metrics = []
    keys = sorted({tuple(cell["cellKey"]) for run in runs for cell in run["cells"]
                   if cell["cellKey"][2] in states})
    for key in keys:
        members = [
            next((cell for cell in run["cells"] if tuple(cell["cellKey"]) == key), None) for run in runs
        ]
        members = [cell for cell in members if cell is not None]
        for metric, _direction, mad_key in COMPARED_METRICS:
            medians = [cell[metric] for cell in members if isinstance(cell.get(metric), (int, float))]
            if len(medians) < 2:
                continue
            centre = statistics.median(medians)
            within = [
                relative(cell.get(mad_key), cell.get(metric)) for cell in members
            ] if mad_key else []
            within = [value for value in within if value is not None]
            within_mad = statistics.median(within) if within else None
            metrics.append({
                "cellKey": list(key), "metric": metric, "runs": len(medians),
                "runMedians": [round(value, 6) for value in medians],
                "betweenRunRelativeRange": round((max(medians) - min(medians)) / abs(centre), 6) if centre else None,
                "betweenRunRelativeMAD": round(relative(mad(medians), centre), 6) if centre else None,
                "withinRunRelativeMAD": round(within_mad, 6) if within_mad is not None else None,
                "threeWithinRunMADs": round(3 * within_mad, 6) if within_mad is not None else None,
            })
    replay = []
    for index, run in enumerate(runs):
        others = [other for position, other in enumerate(runs) if position != index]
        if not others:
            continue
        details: list[dict[str, Any]] = []
        regressions = compare_summaries(
            pooled_cells(others), run["cells"], states=states, details=details,
        )
        replay.append({
            "leftOutRun": run["runID"], "poolRunCount": len(others),
            "falseRegressions": [
                {"cellKey": list(entry["cellKey"]), "metric": entry["metric"],
                 "delta": round(entry["delta"], 6) if isinstance(entry.get("delta"), float) else entry.get("delta")}
                for entry in regressions
            ],
            "judged": [
                {"cellKey": row["cellKey"], "metric": row["metric"], "delta": round(row["delta"], 6),
                 "threshold": round(row["threshold"], 6), "basis": row["basis"]}
                for row in details if row.get("judged")
            ],
        })
    return {"metrics": metrics, "leaveOneRunOut": replay}


def estimate(runs: list[dict[str, Any]], states: tuple[str, ...] = ("warm",)) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        key = json.dumps([run["identity"], run["sourceCommit"]], sort_keys=True)
        groups.setdefault(key, []).append(run)
    reports = []
    for key, members in sorted(groups.items()):
        identity, commit = json.loads(key)
        if len(members) < 2:
            continue
        body = group_estimate(members, states)
        canonical = identity.get("hardwareProfile") in CANONICAL_HOST_PROFILES
        reports.append({
            "identity": identity, "sourceCommit": commit, "runCount": len(members),
            "runIDs": [member["runID"] for member in members],
            "falseRegressionRuns": sum(bool(entry["falseRegressions"]) for entry in body["leaveOneRunOut"]),
            "sufficientForGateChange": canonical and len(members) >= MINIMUM_POOLED_RUNS + 1,
            **body,
        })
    return {
        "schemaVersion": REPORT_SCHEMA,
        "states": list(states),
        "requirement": (
            f"a gate-MAD change needs at least {MINIMUM_POOLED_RUNS + 1} identical-source runs on the "
            "canonical host, so each left-out run faces a pool the gate accepts"
        ),
        "groups": reports,
        "sufficientEvidence": any(report["sufficientForGateChange"] for report in reports),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--records", type=Path, action="append", default=[],
                        help="committed history record(s) or a directory of them")
    parser.add_argument("--label", help="with --records: keep only runs with this label")
    parser.add_argument("--baseline", type=Path, action="append", default=[],
                        help="governed baseline document(s) whose seededRuns to replay")
    parser.add_argument("--state", action="append", default=[],
                        help="warm states the gate compares (default warm)")
    parser.add_argument("--output", type=Path, help="write the JSON report here")
    args = parser.parse_args(argv)
    try:
        paths: list[Path] = []
        for item in args.records:
            paths.extend(sorted(item.glob("*.json")) if item.is_dir() else [item])
        runs = runs_from_records(paths, args.label)
        for baseline in args.baseline:
            runs.extend(runs_from_baseline(baseline))
        if not runs:
            raise NoiseError("no clean runs were found")
        report = estimate(runs, tuple(args.state) or ("warm",))
    except (NoiseError, OSError, ValueError, KeyError) as error:
        print(f"estimate-between-run-noise: FAIL\n{error}", file=sys.stderr)
        return 1
    for group in report["groups"]:
        print(f"{group['identity'].get('hardwareProfile')} @ {str(group['sourceCommit'])[:8]}: "
              f"{group['runCount']} runs, false-regression runs {group['falseRegressionRuns']}, "
              f"sufficient for a gate change: {group['sufficientForGateChange']}")
        for row in group["metrics"]:
            print(f"  {'/'.join(row['cellKey'])} {row['metric']:<10} between-run range "
                  f"{row['betweenRunRelativeRange']} MAD {row['betweenRunRelativeMAD']} "
                  f"| within-run 3 MAD {row['threeWithinRunMADs']}")
    print(f"sufficientEvidence={str(report['sufficientEvidence']).lower()}")
    if args.output is not None:
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
