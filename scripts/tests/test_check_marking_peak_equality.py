#!/usr/bin/env python3
"""Fixtures for the CP-2 within-take marking peak checker (fail-closed).

The checker asserts, per successful take, that no sample at or after the
`before_marking` boundary exceeds that take's pre-marking peak beyond
tolerance, and that the marking boundaries exist at all (they are captured
only when marking actually executes, so a knob-disabled run fails)."""

from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_marking_peak_equality", ROOT / "scripts/check_marking_peak_equality.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def sidecar_rows(pre_peaks, mark_peaks, boundaries=True):
    """Synthesize a sampler sidecar: pre-marking samples, the marking
    boundaries, then samples inside/after the marking interval."""
    rows, t = [], 1_000
    for v in pre_peaks:
        rows.append({"kind": "sample", "capturedUptimeNS": t, "physFootprintMB": v})
        t += 500
    if boundaries:
        rows.append({"kind": "boundary", "boundary": "before_marking",
                     "capturedUptimeNS": t, "physFootprintMB": pre_peaks[-1]})
        t += 100
    for v in mark_peaks:
        rows.append({"kind": "sample", "capturedUptimeNS": t, "physFootprintMB": v})
        t += 500
    if boundaries:
        rows.append({"kind": "boundary", "boundary": "after_marking",
                     "capturedUptimeNS": t, "physFootprintMB": mark_peaks[-1]})
    return rows


class MarkingPeakEqualityTests(unittest.TestCase):
    def run_checker(self, takes, *extra: str) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            engine = root / "runtime" / "diagnostics" / "engine"
            engine.mkdir(parents=True)
            record_takes = []
            for i, (cell, rows) in enumerate(takes):
                gid = f"FIXTURE-{i}"
                (engine / f"samples-{gid}.jsonl").write_text(
                    "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
                record_takes.append(
                    {"cell": cell, "generationID": gid, "status": "success"})
            manifest = root / "benchmark-evidence.json"
            manifest.write_text(
                json.dumps({"historyRecord": {"takes": record_takes}}),
                encoding="utf-8")
            return MODULE.main([str(manifest), *extra])

    def test_marking_below_take_peak_passes(self) -> None:
        rows = sidecar_rows(pre_peaks=[400, 858, 420], mark_peaks=[430, 438])
        self.assertEqual(self.run_checker([("custom/speed/medium/cold#0", rows)]), 0)

    def test_marking_within_floor_tolerance_passes(self) -> None:
        rows = sidecar_rows(pre_peaks=[500], mark_peaks=[540])  # +40 < 48 floor
        self.assertEqual(self.run_checker([("design/warm#1", rows)]), 0)

    def test_marking_raising_take_peak_fails_closed(self) -> None:
        # The cache-stacking signature: marking lands on the still-resident
        # generation working set and adds hundreds of MB.
        rows = sidecar_rows(pre_peaks=[400, 858], mark_peaks=[1290])
        self.assertEqual(self.run_checker([("custom/cold#0", rows)]), 1)

    def test_missing_boundaries_fail_closed(self) -> None:
        # QWENVOICE_MARKING=off: the seam captures no boundaries, so an
        # unmarked run can never publish as marking evidence.
        rows = sidecar_rows(pre_peaks=[400, 858], mark_peaks=[420], boundaries=False)
        self.assertEqual(self.run_checker([("custom/cold#0", rows)]), 1)

    def test_missing_sidecar_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manifest = pathlib.Path(tmp) / "benchmark-evidence.json"
            manifest.write_text(json.dumps({"historyRecord": {"takes": [
                {"cell": "clone/cold#0", "generationID": "GONE", "status": "success"}
            ]}}), encoding="utf-8")
            self.assertEqual(MODULE.main([str(manifest)]), 1)

    def test_one_bad_take_fails_the_run(self) -> None:
        good = sidecar_rows(pre_peaks=[800], mark_peaks=[810])
        bad = sidecar_rows(pre_peaks=[479], mark_peaks=[900])
        self.assertEqual(
            self.run_checker([("custom/warm#1", good), ("design/warm#1", bad)]), 1)

    def test_empty_record_fails_closed(self) -> None:
        self.assertEqual(self.run_checker([]), 1)


if __name__ == "__main__":
    unittest.main()
