#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ios_memory_field_report.py"


class IOSMemoryFieldReportTests(unittest.TestCase):
    def run_report(self, source: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT), str(source)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_missing_payload_is_an_explicit_nonfatal_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            completed = self.run_report(Path(directory))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "notYetDelivered")
        self.assertEqual(payload["recordCount"], 0)
        self.assertIn("not a benchmark failure", completed.stderr)

    def test_aggregates_bounded_summary_and_memory_field_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = root / "pull" / "diagnostics" / "metrickit-memory-exit-summaries.json"
            summary.parent.mkdir(parents=True)
            summary.write_text(
                json.dumps(
                    {
                        "schemaVersion": 1,
                        "records": [
                            {
                                "kind": "metricPayload",
                                "intervalStart": "2026-07-10T00:00:00Z",
                                "intervalEnd": "2026-07-11T00:00:00Z",
                                "peakMemoryMB": 3500.5,
                                "foregroundExitCounts": {"normal": 2, "memoryPressure": 1},
                                "uiResponsiveness": {
                                    "scrollHitchTimeRatioMSPerS": 4.5,
                                    "hangEventCount": 2,
                                    "hangTimeTotalSecondsApprox": 0.75,
                                    "hangTimeMaxBucketEndSeconds": 0.5,
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            jsonl = root / "pull" / "diagnostics" / "memory-field" / "aggregate.jsonl"
            jsonl.parent.mkdir(parents=True)
            jsonl.write_text(
                json.dumps(
                    {
                        "intervalStart": "2026-07-11T00:00:00Z",
                        "intervalEnd": "2026-07-12T00:00:00Z",
                        "peakMemoryMB": 3600,
                        "foregroundExits": {"normal": 1},
                        "backgroundExitCounts": {"memoryResourceLimit": 2},
                        "diagnosticCounts": {"crash": 1, "hang": 3},
                        "uiResponsiveness": {
                            "scrollHitchTimeRatioMSPerS": 2.0,
                            "hangEventCount": 1,
                            "hangTimeTotalSecondsApprox": 0.25,
                            "hangTimeMaxBucketEndSeconds": 1.0,
                            "notAllowlisted": 99,
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            completed = self.run_report(root)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["sourceFileCount"], 2)
        self.assertEqual(payload["recordCount"], 2)
        self.assertEqual(payload["peakMemoryMB"], 3600.0)
        self.assertEqual(payload["foregroundExitCounts"], {"memoryPressure": 1, "normal": 3})
        self.assertEqual(payload["backgroundExitCounts"], {"memoryResourceLimit": 2})
        self.assertEqual(payload["diagnosticCounts"], {"crash": 1, "hang": 3})
        # Sums accumulate hang counts/time; maxima keep the worst hitch ratio
        # and bucket end; unknown keys are silently dropped by the allowlist.
        self.assertEqual(
            payload["uiResponsiveness"],
            {
                "hangEventCount": 3.0,
                "hangTimeTotalSecondsApprox": 1.0,
                "hangTimeMaxBucketEndSeconds": 1.0,
                "scrollHitchTimeRatioMSPerS": 4.5,
            },
        )
        self.assertNotIn(str(root), completed.stdout)

    def test_malformed_selected_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagnostics" / "memory-field" / "bad.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"peakMemoryMB": "a lot"}), encoding="utf-8")
            completed = self.run_report(path.parent.parent.parent)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("peakMemoryMB must be numeric", completed.stderr)


if __name__ == "__main__":
    unittest.main()
