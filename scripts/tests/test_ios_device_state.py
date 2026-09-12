#!/usr/bin/env python3
"""Device-lane shell helpers, exercised by sourcing the library (never by slicing script text)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "scripts/lib/ios_device_state.sh"


def run_helper(function: str, *arguments: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    script = f'ROOT_DIR="{ROOT}"; . "{LIB}"; {function} "$@"'
    return subprocess.run(
        ["bash", "-c", script, "helper", *arguments],
        input=stdin, text=True, capture_output=True, check=False,
    )


class IOSDeviceStateHelpersTests(unittest.TestCase):
    def test_canonical_device_cell_matches_publisher_identity(self) -> None:
        for spec, expected in (
            ("custom:speed:hello", "custom/speed/device"),
            ("design:speed:hello", "design/speed/device"),
            ("clone:quality:hello", "clone/quality/device"),
        ):
            completed = run_helper("device_benchmark_cell", spec)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout, expected)

    def test_sentinel_contract_rejects_failed_or_interrupted_runs(self) -> None:
        cases = (
            ({"status": "ok", "interruptions": []}, 0),
            ({"status": "error", "error": "generation failed"}, 1),
            ({"status": "ok", "interruptions": [{"type": "will_resign_active"}]}, 2),
        )
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "sentinel.json"
            for payload, expected in cases:
                with self.subTest(payload=payload):
                    sentinel.write_text(json.dumps(payload), encoding="utf-8")
                    completed = run_helper("require_uninterrupted_success_sentinel", str(sentinel))
                    self.assertEqual(completed.returncode, expected, completed.stderr)

    def test_xctrace_inventory_distinguishes_online_offline_and_missing_device(self) -> None:
        udid = "00008150-00181D580ED8401C"
        fixtures = (
            (f"== Devices ==\nTest iPhone (26.5) ({udid})\n", 0, udid),
            (f"== Devices Offline ==\nTest iPhone (26.5) ({udid})\n", 20, ""),
            ("== Devices ==\nMac mini (HOST-ID)\n", 21, ""),
        )
        for inventory, expected_status, expected_output in fixtures:
            with self.subTest(expected_status=expected_status):
                completed = run_helper("xctrace_inventory_status", udid, stdin=inventory)
                self.assertEqual(completed.returncode, expected_status, completed.stderr)
                self.assertEqual(completed.stdout.strip(), expected_output)


if __name__ == "__main__":
    unittest.main()
