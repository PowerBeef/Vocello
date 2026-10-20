#!/usr/bin/env python3
"""scripts/ios_device.sh lanes read their own run's engine rows from the pulled mirror.

The mirror holds every run's subtree (smoke, benchmark and diagnostics runs mirror there too), so
the first generations.jsonl a search returns can be another run's. The iPhone memory
qualification of 2026-10-20 failed that way (CONV-21). The helper runs as shipped, from the
sourced lane, over trees shaped like that pull.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from shell_stubs import LaneShell, quote


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


if __name__ == "__main__":
    unittest.main()
