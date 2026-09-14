#!/usr/bin/env python3
"""Analyze a lane's played-audio captures without the benchmark telemetry checker.

The macOS smoke lane taps the app's output for its completed-generation
journey (PC-02: "the smoke lane captures too") but publishes no benchmark
record, so this writes the same `summary.json` the benchmark lane gets:
per-take status, the seven comparison metrics, warn codes and the gate
verdict against the shared thresholds in scripts/lib/playback_capture.py.
Advisory by default; `--gate` exits 1 when a captured take fails.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import jsonio, playback_capture  # noqa: E402


def analyze(capture_dir: Path, outputs_dir: Path | None, mode: str) -> dict:
    captures = playback_capture.collect_captures(capture_dir)
    takes = []
    for (index, cell), entry in sorted(captures.items()):
        sidecar = entry["sidecar"]
        reference = None
        stamps = [v for v in (sidecar.get("submitClickEpochMS"), sidecar.get("captureStartEpochMS"))
                  if isinstance(v, (int, float))]
        if outputs_dir is not None and entry["wav"] is not None and stamps:
            stop = sidecar.get("stopEpochMS")
            stop = float(stop) if isinstance(stop, (int, float)) else min(stamps) + 600_000.0
            reference = playback_capture.resolve_reference_wav(
                outputs_dir, cell.split("/")[0] if "/" in cell else mode, min(stamps) - 2_000.0, stop + 5_000.0, None,
            )
        try:
            result = playback_capture.analyze_take(sidecar, entry["wav"], reference)
        except playback_capture.PlaybackCaptureError as error:
            result = {"status": "aborted", "metrics": {}, "warnings": [], "digest": None, "error": str(error)}
        gate = playback_capture.gate_failures(result["status"], result["metrics"])
        take = {"takeIndex": index, "cell": cell, "status": result["status"],
                "reference": reference.name if reference is not None else None,
                "metrics": result["metrics"], "warnings": result["warnings"]}
        if result.get("error"):
            take["error"] = result["error"]
        if gate:
            take["gateFailures"] = gate
        takes.append(take)
    return {
        "schemaVersion": 1,
        "runID": (jsonio.load_json(capture_dir / "capture-run.json") or {}).get("runID")
        if (capture_dir / "capture-run.json").is_file() else None,
        "takes": takes,
        "captured": sum(1 for t in takes if t["status"] == "captured"),
        "expected": len(takes),
        "gate": {
            "coverageMin": playback_capture.GATE_COVERAGE_MIN,
            "residualMaxDBFS": playback_capture.GATE_RESIDUAL_MAX_DBFS,
            "dropoutMax": playback_capture.GATE_DROPOUT_MAX,
            "misalignedMaxMS": playback_capture.GATE_MISALIGNED_MAX_MS,
            "failedTakes": [t["takeIndex"] for t in takes if t.get("gateFailures")],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("capture_dir", type=Path)
    parser.add_argument("--outputs-dir", type=Path, default=None)
    parser.add_argument("--mode", default="custom", help="mode used to resolve the reference WAV when the cell does not name it")
    parser.add_argument("--gate", action="store_true", help="exit 1 when a captured take fails the gate")
    args = parser.parse_args(argv)
    if not args.capture_dir.is_dir():
        print(f"playback capture: no capture directory at {args.capture_dir}")
        return 0
    summary = analyze(args.capture_dir, args.outputs_dir, args.mode)
    jsonio.atomic_json(args.capture_dir / "summary.json", summary)
    failed = summary["gate"]["failedTakes"]
    print(f"playback capture: {summary['captured']}/{summary['expected']} captured, gate failures: {failed or 'none'}")
    return 1 if (args.gate and failed) else 0


if __name__ == "__main__":
    sys.exit(main())
