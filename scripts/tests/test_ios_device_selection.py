#!/usr/bin/env python3
"""scripts/ios_device.sh picks the physical iPhone and its own run's engine rows.

The pulled diagnostics mirror holds every run's subtree (smoke, benchmark and diagnostics runs
mirror there too), so the first generations.jsonl a search returns can be another run's, and
Xcode 27's CoreDevice lists Simulator runtimes as paired devices beside the phone. The iPhone
memory qualification of 2026-10-20 failed both ways (CONV-21). The helpers run as shipped, from
the sourced lane, over trees and device lists shaped like that window's.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest

from shell_stubs import LaneShell, quote

DEVICE_LIST = r'''
[[ "$1 $2 $3" == "devicectl list devices" ]] || exit 97
while (( $# )); do case "$1" in --json-output) output="$2"; shift 2 ;; *) shift ;; esac; done
printf '%s\n' "$QV_DEVICE_LIST" >"$output"
'''


class RunDiagnosticsDirTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shell = LaneShell(self, "ios_device.sh")
        self.dest = self.shell.path / "device-diagnostics"

    def write_rows(self, directory: Path) -> None:
        (directory / "engine").mkdir(parents=True, exist_ok=True)
        (directory / "engine" / "generations.jsonl").write_text("{}\n", encoding="utf-8")

    def resolve(self, run: str) -> str:
        sentinel = self.dest / run / "memory-qualification-result.json"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("{}", encoding="utf-8")
        result = self.shell.run(f"run_diagnostics_dir {quote(self.dest)} {quote(sentinel)}")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_reads_the_rows_beside_its_own_sentinel_among_other_runs(self) -> None:
        self.write_rows(self.dest)
        for other in ("ios-xcui-smoke-20261020-160313-80e6aba4", "ios-xcui-smoke-20261014-002614-3f711b56"):
            self.write_rows(self.dest / other)
        run = "ios-memory-qualification-20261020-174011-67cdd64d"
        self.write_rows(self.dest / run)
        self.assertEqual(self.resolve(run), str(self.dest / run))

    def test_without_rows_of_its_own_it_reads_the_whole_mirror(self) -> None:
        self.write_rows(self.dest)
        self.write_rows(self.dest / "ios-xcui-smoke-20261020-160313-80e6aba4")
        self.assertEqual(self.resolve("ios-logs-20261020-130125"), str(self.dest))


class ResolveDeviceTests(unittest.TestCase):
    PHONE = {
        "identifier": "physical-phone",
        "hardwareProperties": {"reality": "physical"},
        "deviceProperties": {"name": "A paired iPhone"},
        "connectionProperties": {"pairingState": "paired"},
    }
    # Named like the device the lane prefers by name, so only the reality filter refuses it.
    SIMULATED = {
        "identifier": "simulated-runtime",
        "hardwareProperties": {"reality": "simulated"},
        "deviceProperties": {"name": "iPhone 17 Pro"},
        "connectionProperties": {"pairingState": "paired"},
    }

    def resolve(self, devices: list[dict]) -> subprocess.CompletedProcess[str]:
        shell = LaneShell(self, "ios_device.sh")
        shell.tool("xcrun", DEVICE_LIST)
        return shell.run(
            "unset QVOICE_IOS_DEVICE_ID\nresolve_device\n",
            env={"QV_DEVICE_LIST": json.dumps({"result": {"devices": devices}})},
        )

    def test_a_simulated_runtime_is_never_chosen_or_counted(self) -> None:
        result = self.resolve([self.SIMULATED, self.PHONE])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "physical-phone")

    def test_only_a_simulated_runtime_finds_no_iphone(self) -> None:
        result = self.resolve([self.SIMULATED])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no paired iPhone found", result.stderr)


if __name__ == "__main__":
    unittest.main()
