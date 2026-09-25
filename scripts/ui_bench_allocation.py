#!/usr/bin/env python3
"""Resolve or derive a declared UI benchmark matrix (audit #30).

  ui_bench_allocation.py resolve [--version NAME]
      Print the version's allocation in the runner's form (`mode/length=n,...`,
      empty for a uniform matrix) and its warm repetitions; scripts/ui_test.sh
      reads it for --matrix-version.

  ui_bench_allocation.py derive RECORD... [--phases take-phases.jsonl ...]
                               [--budget-seconds N] [--overhead-seconds N] [--write NAME]
      Compute a warm-repetition allocation from measured ui-generation records
      (paths or run IDs under benchmarks/runs/ui-generation): the pooled
      within-run spread of each warm cell's log RTF and each take's cost, spent
      under the canonical matrix's own time budget by default. --write adds it
      to config/ui-bench-matrix.json as a derived version; making it canonical
      stays a separate, reviewed edit of canonicalVersion.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from lib import ui_bench_matrix as matrix  # noqa: E402

RUNS_ROOT = SCRIPT_DIR.parent / "benchmarks" / "runs" / "ui-generation"


def load_record(reference: str) -> dict:
    path = Path(reference)
    if not path.is_file():
        path = RUNS_ROOT / f"{reference}.json"
    if not path.is_file():
        raise matrix.MatrixError(f"no ui-generation record {reference!r}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_phases(paths: list[str]) -> list[dict]:
    rows: list[dict] = []
    for path in paths:
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=matrix.CONFIG_PATH)
    commands = parser.add_subparsers(dest="command", required=True)
    resolve = commands.add_parser("resolve", help="print a version's runner allocation")
    resolve.add_argument("--version", default=None, help="default: the canonical version")
    resolve.add_argument("--field", choices=("allocation", "warm", "canonical", "name"), default="allocation")
    derive = commands.add_parser("derive", help="derive an allocation from measured records")
    derive.add_argument("records", nargs="+", metavar="RECORD")
    derive.add_argument("--phases", nargs="*", default=[], metavar="JSONL",
                        help="take-phases.jsonl of the same runs (per-take harness cost)")
    derive.add_argument("--budget-seconds", type=float, default=None)
    derive.add_argument("--overhead-seconds", type=float, default=matrix.DEFAULT_OVERHEAD_SECONDS)
    derive.add_argument("--write", metavar="NAME", help="add the result to the contract as this version")
    args = parser.parse_args(argv)
    try:
        config = matrix.load_config(args.config)
        if args.command == "resolve":
            name = args.version or config["canonicalVersion"]
            warm, allocation = matrix.version_matrix(config, name)
            if args.field == "name":
                print(name)
            elif args.field == "warm":
                print(warm)
            elif args.field == "canonical":
                print("yes" if name == config["canonicalVersion"] else "no")
            else:
                print(matrix.format_allocation(allocation))
            return 0
        version = matrix.derive(
            [load_record(reference) for reference in args.records],
            phases=load_phases(args.phases) or None,
            budget_seconds=args.budget_seconds,
            overhead_seconds=args.overhead_seconds,
            config=config,
        )
    except (matrix.MatrixError, OSError, KeyError, ValueError) as error:
        print(f"ui-bench matrix FAILED: {error}", file=sys.stderr)
        return 1
    if args.write:
        if args.write in config["versions"] and config["versions"][args.write]["status"] == "canonical":
            print(f"ui-bench matrix FAILED: {args.write} is the canonical version", file=sys.stderr)
            return 1
        config["versions"][args.write] = version
        args.config.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        print(f"ui-bench matrix {args.write} ({version['takeCount']} takes) -> {args.config}")
    else:
        sys.stdout.write(json.dumps(version, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
