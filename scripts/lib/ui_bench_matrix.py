"""Declared UI benchmark matrices and the spread-driven reallocation (audit #30).

``config/ui-bench-matrix.json`` names the matrix versions. The canonical version
is the 29-take matrix every published record measured; another version
reallocates warm repetitions per mode and length (``warmAllocation``), and a run
of it is focused until the maintainer makes it canonical. The XCUITest matrix
(`VocelloUIBenchMatrix`) reads the same allocation from
``QVOICE_<PLATFORM>_BENCH_ALLOCATION`` (``mode/length=n,...``), so the runner and
the checkers agree on the ordered cells.

``derive`` computes an allocation from measured records: per warm cell, the
within-run spread of log RTF (the part more takes can shrink; the take after a
cold take is left out, as cell aggregate 2 does) and the per-take cost (the
harness phases of ``take-phases.jsonl`` when given, else the take's own wall
time plus a fixed harness overhead). It then spends a time budget, by default
what the canonical matrix's warm takes cost, one take at a time on the cell
whose median has the largest standard error (``minimax-se-v1``), within
``[MINIMUM_REPETITIONS, MAXIMUM_REPETITIONS]``.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path
from typing import Any, Iterable

from lib import rtf as rtf_semantics

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "ui-bench-matrix.json"
MODES = ("custom", "design", "clone")
LENGTHS = ("short", "medium", "long")
DEFAULT_WARM = 3
DERIVATION_RULE = "minimax-se-v1"
MINIMUM_REPETITIONS = 2
MAXIMUM_REPETITIONS = 8
# Harness time around a take when no take-phases.jsonl is given: the audit's
# 5-9.5 s per take (#31), before the playback wait, which the take cost adds.
DEFAULT_OVERHEAD_SECONDS = 7.0
# The median of n takes has a standard error of about 1.2533 s / sqrt(n).
MEDIAN_EFFICIENCY = math.sqrt(math.pi / 2)
_ENTRY_RE = re.compile(r"^(custom|design|clone)/(short|medium|long)=([1-9][0-9]?)$")


class MatrixError(ValueError):
    pass


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("schemaVersion") != 1:
        raise MatrixError(f"unsupported UI benchmark matrix contract: {path}")
    versions = config.get("versions")
    if not isinstance(versions, dict) or config.get("canonicalVersion") not in (versions or {}):
        raise MatrixError(f"the matrix contract must name its canonical version among its versions: {path}")
    for name, version in versions.items():
        warm = version.get("warmRepetitions") if isinstance(version, dict) else None
        if isinstance(warm, bool) or not isinstance(warm, int) or warm < 1:
            raise MatrixError(f"matrix version {name} needs a positive warmRepetitions")
        allocation = version.get("warmAllocation")
        if not isinstance(allocation, dict):
            raise MatrixError(f"matrix version {name} needs a warmAllocation object")
        parse_allocation(format_allocation(allocation))
        status = version.get("status")
        canonical = name == config["canonicalVersion"]
        if (status == "canonical") != canonical or status not in {"canonical", "provisional", "derived"}:
            raise MatrixError(f"matrix version {name} has status {status!r}; only the canonical version is canonical")
    return config


def parse_allocation(text: str | None) -> dict[str, int]:
    """`custom/short=5,custom/long=2` -> {"custom/short": 5, ...}; empty for uniform."""
    allocation: dict[str, int] = {}
    for entry in (part.strip() for part in (text or "").split(",")):
        if not entry:
            continue
        match = _ENTRY_RE.match(entry)
        if match is None:
            raise MatrixError(f"invalid matrix allocation entry {entry!r} (mode/length=repetitions)")
        cell = f"{match.group(1)}/{match.group(2)}"
        if cell in allocation:
            raise MatrixError(f"matrix allocation names {cell} twice")
        allocation[cell] = int(match.group(3))
    return allocation


def format_allocation(allocation: dict[str, int]) -> str:
    """The runner's environment form, in mode and length order."""
    cells = [f"{mode}/{length}" for mode in MODES for length in LENGTHS]
    unknown = sorted(set(allocation) - set(cells))
    if unknown:
        raise MatrixError(f"matrix allocation names unknown cells: {', '.join(unknown)}")
    return ",".join(f"{cell}={allocation[cell]}" for cell in cells if cell in allocation)


def warm_repetitions(mode: str, length: str, warm: int, allocation: dict[str, int] | None) -> int:
    return (allocation or {}).get(f"{mode}/{length}", warm)


def expected_cells(
    modes: list[str], lengths: list[str], warm: int, allocation: dict[str, int] | None = None,
) -> list[str]:
    """The ordered take cells `VocelloUIBenchMatrix.takes(configuration:)` runs."""
    cells: list[str] = []
    cold_length = "medium" if "medium" in lengths else lengths[0]
    for mode in modes:
        if mode != "clone":
            cells.append(f"{mode}/{cold_length}/cold#0")
        for length in lengths:
            for repetition in range(warm_repetitions(mode, length, warm, allocation)):
                cells.append(f"{mode}/{length}/warm#{repetition}")
    return cells


def version_matrix(config: dict[str, Any], name: str) -> tuple[int, dict[str, int]]:
    try:
        version = config["versions"][name]
    except KeyError:
        raise MatrixError(f"unknown UI benchmark matrix version {name!r}") from None
    return int(version["warmRepetitions"]), dict(version["warmAllocation"])


def is_canonical(
    modes: list[str], lengths: list[str], warm: int, allocation: dict[str, int] | None,
    config: dict[str, Any] | None = None,
) -> bool:
    """Whether a run measured the declared canonical matrix, cell for cell."""
    config = config or load_config()
    canonical_warm, canonical_allocation = version_matrix(config, config["canonicalVersion"])
    return (
        list(modes) == list(MODES) and list(lengths) == list(LENGTHS)
        and expected_cells(modes, lengths, warm, allocation)
        == expected_cells(list(MODES), list(LENGTHS), canonical_warm, canonical_allocation)
    )


# --- derivation --------------------------------------------------------------

def _cell_of(take: dict[str, Any]) -> str:
    return re.sub(r"#\d+$", "", str(take.get("cell", "")))


def _counted_warm_takes(record: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """Warm takes, less the take after a cold take (flagged or by position)."""
    takes = record.get("takes", [])
    for position, take in enumerate(takes):
        if take.get("warmState") != "warm":
            continue
        after_cold = take.get("followsColdTake") is True or (
            position > 0 and takes[position - 1].get("warmState") == "cold"
        )
        if not after_cold:
            yield take


def cell_spreads(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per warm cell (mode/length): the pooled within-run SD of log RTF."""
    per_cell: dict[str, list[tuple[float, int]]] = {}
    for record in records:
        grouped: dict[str, list[float]] = {}
        for take in _counted_warm_takes(record):
            value, _ = rtf_semantics.take_rtf(record, take)
            if value is not None and value > 0:
                grouped.setdefault(_cell_of(take).replace("/warm", ""), []).append(math.log(value))
        for cell, values in grouped.items():
            if len(values) >= 2:
                per_cell.setdefault(cell, []).append((statistics.variance(values), len(values) - 1))
    spreads = {}
    for cell, parts in per_cell.items():
        freedom = sum(df for _, df in parts)
        pooled = sum(variance * df for variance, df in parts) / freedom
        spreads[cell] = {"logSD": math.sqrt(pooled), "degreesOfFreedom": freedom, "runs": len(parts)}
    return spreads


def take_costs(
    records: list[dict[str, Any]], phases: list[dict[str, Any]] | None = None,
    overhead_seconds: float = DEFAULT_OVERHEAD_SECONDS,
) -> dict[str, float]:
    """Per warm cell, the median wall seconds one take costs the lane."""
    samples: dict[str, list[float]] = {}
    if phases:
        for row in phases:
            cell = str(row.get("cell", ""))
            if "/warm#" in cell and isinstance(row.get("endMS"), (int, float)):
                samples.setdefault(re.sub(r"/warm#\d+$", "", cell), []).append(row["endMS"] / 1000.0)
    if not samples:
        for record in records:
            for take in _counted_warm_takes(record):
                metrics = take.get("metrics", {})
                completed = metrics.get("submitToCompletedMS")
                audio = metrics.get("audioSeconds") or (take.get("output") or {}).get("durationSeconds")
                if isinstance(completed, (int, float)) and isinstance(audio, (int, float)):
                    samples.setdefault(_cell_of(take).replace("/warm", ""), []).append(
                        completed / 1000.0 + audio + overhead_seconds
                    )
    return {cell: statistics.median(values) for cell, values in samples.items()}


def allocate(
    spreads: dict[str, float], costs: dict[str, float], budget_seconds: float,
    minimum: int = MINIMUM_REPETITIONS, maximum: int = MAXIMUM_REPETITIONS,
) -> dict[str, int]:
    """Spend the budget one take at a time on the cell with the largest median SE."""
    cells = [f"{mode}/{length}" for mode in MODES for length in LENGTHS if f"{mode}/{length}" in spreads]
    missing = [cell for cell in cells if cell not in costs]
    if missing:
        raise MatrixError(f"no per-take cost for {', '.join(missing)}")
    allocation = {cell: minimum for cell in cells}
    spent = sum(minimum * costs[cell] for cell in cells)
    if spent > budget_seconds:
        raise MatrixError(
            f"the budget of {budget_seconds:.0f} s cannot give every cell {minimum} takes ({spent:.0f} s)"
        )
    while True:
        candidates = [
            cell for cell in cells
            if allocation[cell] < maximum and spent + costs[cell] <= budget_seconds
        ]
        if not candidates:
            return allocation
        cell = max(candidates, key=lambda item: (spreads[item] / math.sqrt(allocation[item]), -cells.index(item)))
        allocation[cell] += 1
        spent += costs[cell]


def derive(
    records: list[dict[str, Any]], *, phases: list[dict[str, Any]] | None = None,
    budget_seconds: float | None = None, overhead_seconds: float = DEFAULT_OVERHEAD_SECONDS,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """A derived matrix version from measured UI benchmark records of one profile."""
    if not records:
        raise MatrixError("a derivation needs at least one UI benchmark record")
    identities = {
        (record.get("run", {}).get("kind"), record.get("run", {}).get("platform"),
         record.get("hardware", {}).get("profileID"))
        for record in records
    }
    if len(identities) != 1 or next(iter(identities))[0] != "ui-generation":
        raise MatrixError(f"derivation inputs must be ui-generation records of one platform and profile: {sorted(map(str, identities))}")
    config = config or load_config()
    spreads = cell_spreads(records)
    expected = {f"{mode}/{length}" for mode in MODES for length in LENGTHS}
    if set(spreads) != expected:
        raise MatrixError(
            "every warm cell needs at least two counted takes in one run; missing: "
            + ", ".join(sorted(expected - set(spreads)))
        )
    costs = take_costs(records, phases, overhead_seconds)
    canonical_warm, canonical_allocation = version_matrix(config, config["canonicalVersion"])
    if budget_seconds is None:
        budget_seconds = sum(
            warm_repetitions(*cell.split("/"), canonical_warm, canonical_allocation) * costs[cell]
            for cell in sorted(expected)
        )
    sd = {cell: spreads[cell]["logSD"] for cell in spreads}
    allocation = allocate(sd, costs, budget_seconds)
    cold_takes = sum(1 for mode in MODES if mode != "clone")
    run_ids = [record["run"]["id"] for record in records]
    inputs = {
        cell: {
            "logSD": round(sd[cell], 5),
            "degreesOfFreedom": spreads[cell]["degreesOfFreedom"],
            "costSeconds": round(costs[cell], 2),
            "repetitions": allocation[cell],
            "medianRelativeSE": round(MEDIAN_EFFICIENCY * sd[cell] / math.sqrt(allocation[cell]), 5),
            "canonicalMedianRelativeSE": round(
                MEDIAN_EFFICIENCY * sd[cell]
                / math.sqrt(warm_repetitions(*cell.split("/"), canonical_warm, canonical_allocation)),
                5,
            ),
        }
        for cell in sorted(allocation)
    }
    return {
        "status": "derived",
        "description": (
            f"Derived with {DERIVATION_RULE} from {len(records)} run(s) ({', '.join(run_ids)}): warm "
            f"repetitions that minimize the largest median standard error under a {budget_seconds:.0f} s "
            f"budget ({'phases' if phases else 'take wall time plus overhead'} as the per-take cost), "
            f"between {MINIMUM_REPETITIONS} and {MAXIMUM_REPETITIONS} takes per cell."
        ),
        "rule": DERIVATION_RULE,
        "derivedFrom": run_ids,
        "budgetSeconds": round(budget_seconds, 1),
        "takeCount": sum(allocation.values()) + cold_takes,
        "warmRepetitions": canonical_warm,
        "warmAllocation": allocation,
        "derivationInputs": inputs,
    }
