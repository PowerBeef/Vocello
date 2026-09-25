#!/usr/bin/env python3
"""The between-run noise estimate replays the gate on identical-source runs (audit #106)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import estimate_between_run_noise as noise  # noqa: E402


def record(run_id: str, *, commit: str = "c" * 40, rtfs=(0.27, 0.27, 0.271), profile="mac-mini-m6-16gb",
           footprint=2500.0, dirty=False) -> dict:
    takes = [{
        "cell": f"custom/speed/medium/warm#{index}", "mode": "custom", "modelID": "pro_custom_speed",
        "warmState": "warm", "length": "medium", "audioQC": {"verdict": "pass"},
        "metrics": {"rtf": rtf, "tokensPerSecond": 51.0, "peakPhysicalFootprintMB": footprint + index,
                    "mlxPeakMB": 2376.2},
    } for index, rtf in enumerate(rtfs)]
    return {
        "run": {"id": run_id, "label": "mac-gate-bench"},
        "source": {"commit": commit, "dirty": dirty},
        "hardware": {"profileID": profile},
        "inputs": {"matrixHash": "m" * 64},
        "models": [{"integrityDigest": "d" * 64}],
        "evidence": {"telemetrySchemaVersion": 8, "qcAlgorithmVersion": 8},
        "takes": takes,
    }


class BetweenRunNoiseTests(unittest.TestCase):
    def write(self, directory: Path, records: list[dict]) -> Path:
        for item in records:
            (directory / f"{item['run']['id']}.json").write_text(json.dumps(item))
        return directory

    def test_record_cells_take_the_summarizer_shape(self) -> None:
        cells = noise.run_cells_from_record(record("r1"))
        self.assertEqual(len(cells), 1)
        cell = cells[0]
        self.assertEqual(cell["cellKey"], ["custom", "pro_custom_speed", "warm", "medium"])
        self.assertEqual((cell["n"], cell["rtf"], cell["tokps"], cell["mlxPeakMB"]), (3, 0.27, 51.0, 2376.2))
        self.assertEqual(cell["physFootMB"], 2501.0)
        self.assertEqual(cell["qcVerdict"], "pass")

    def test_identical_source_runs_estimate_noise_and_replay_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = self.write(Path(directory), [
                record("r1"), record("r2", rtfs=(0.272, 0.272, 0.273)), record("r3", rtfs=(0.269,) * 3),
                record("r4"),
                # Another commit and a dirty run never join the identical-source group.
                record("other", commit="e" * 40), record("dirty", dirty=True),
            ])
            report = noise.estimate(noise.runs_from_records(sorted(root.glob("*.json")), "mac-gate-bench"))
        self.assertEqual(len(report["groups"]), 1)
        group = report["groups"][0]
        self.assertEqual(group["runCount"], 4)
        rtf = next(row for row in group["metrics"] if row["metric"] == "rtf")
        self.assertAlmostEqual(rtf["betweenRunRelativeRange"], (0.272 - 0.269) / 0.27, places=5)
        self.assertEqual(len(group["leaveOneRunOut"]), 4)
        self.assertTrue(all(entry["poolRunCount"] == 3 for entry in group["leaveOneRunOut"]))
        self.assertEqual(group["falseRegressionRuns"], 0)
        # Four identical-source runs on the canonical host suffice to propose a change.
        self.assertTrue(group["sufficientForGateChange"])
        self.assertTrue(report["sufficientEvidence"])

    def test_a_drifting_run_is_a_false_regression_and_three_runs_are_not_enough(self) -> None:
        runs = [
            {"runID": name, "sourceCommit": "c", "identity": {"hardwareProfile": "mac-mini-m6-16gb"},
             "cells": noise.run_cells_from_record(record(name, rtfs=rtfs))}
            for name, rtfs in (("a", (0.27,) * 3), ("b", (0.27,) * 3), ("c", (0.30,) * 3))
        ]
        report = noise.estimate(runs)
        group = report["groups"][0]
        drifting = next(entry for entry in group["leaveOneRunOut"] if entry["leftOutRun"] == "c")
        self.assertEqual([item["metric"] for item in drifting["falseRegressions"]], ["rtf"])
        self.assertFalse(group["sufficientForGateChange"])
        self.assertFalse(report["sufficientEvidence"])

    def test_a_baseline_document_replays_its_seeded_runs(self) -> None:
        cells = noise.run_cells_from_record(record("r1"))
        document = {
            "schemaVersion": 2,
            "identity": {"hardwareProfile": "mac-mini-m6-16gb", "matrixHash": "m" * 64,
                         "models": [{"integrityDigest": "d" * 64}]},
            "seededRuns": [{"runID": f"s{index}", "sourceCommit": "c" * 40, "cells": cells}
                           for index in range(3)],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            path.write_text(json.dumps(document))
            runs = noise.runs_from_baseline(path)
            report = noise.estimate(runs)
            self.assertEqual(report["groups"][0]["runCount"], 3)
            self.assertFalse(report["sufficientEvidence"])
            path.write_text(json.dumps({"schemaVersion": 2, "cells": []}))
            with self.assertRaises(noise.NoiseError):
                noise.runs_from_baseline(path)


if __name__ == "__main__":
    unittest.main()
