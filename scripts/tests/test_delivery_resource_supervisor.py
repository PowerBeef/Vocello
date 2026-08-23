#!/usr/bin/env python3
"""Deterministic contracts for serial delivery-analyzer supervision."""

from __future__ import annotations

import fcntl
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_resource_supervisor import (  # noqa: E402
    HostSnapshot,
    ResourceSupervisorError,
    run_supervised,
)


class DeliveryResourceSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _snapshot() -> HostSnapshot:
        return HostSnapshot(free_percent=55.0, swap_used_bytes=1024, pressure_warning=False)

    def test_clean_child_records_resource_and_digests(self) -> None:
        result = run_supervised(
            [sys.executable, "-c", "import time; print('ok'); time.sleep(.15)"],
            lock_root=self.root, snapshotter=self._snapshot,
            rss_sampler=lambda _pid: 12 * 1024**2,
        )
        self.assertEqual(result.stdout.strip(), b"ok")
        self.assertTrue(result.report["qualified"])
        self.assertGreater(result.report["peakRSSBytes"], 0)
        self.assertNotIn(str(self.root), str(result.report))

    def test_timeout_is_typed_and_child_exits(self) -> None:
        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            lock_root=self.root, timeout_seconds=0.1, snapshotter=self._snapshot,
            rss_sampler=lambda _pid: 12 * 1024**2,
        )
        self.assertTrue(result.report["timedOut"])
        self.assertIn("timeout", result.report["qualificationFailures"])

    def test_active_lock_rejects_overlap(self) -> None:
        self.root.mkdir(exist_ok=True)
        path = self.root / "delivery-analysis-supervisor.lock"
        with path.open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ResourceSupervisorError, "already active"):
                run_supervised(
                    [sys.executable, "-c", "print('no')"],
                    lock_root=self.root, snapshotter=self._snapshot,
                    rss_sampler=lambda _pid: 12 * 1024**2,
                )

    def test_pressure_swap_and_recovery_fail_closed(self) -> None:
        snapshots = iter((
            HostSnapshot(60.0, 0, False),
            HostSnapshot(40.0, 128 * 1024**2, True),
        ))
        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(.1)"],
            lock_root=self.root, snapshotter=lambda: next(snapshots),
            rss_sampler=lambda _pid: 12 * 1024**2,
            recovery_timeout_seconds=0,
        )
        failures = set(result.report["qualificationFailures"])
        self.assertIn("host-pressure-not-clean", failures)
        self.assertIn("swap-recovery-unqualified", failures)
        self.assertIn("post-exit-memory-recovery-unqualified", failures)

    def test_transient_post_exit_drop_is_sampled_until_recovered(self) -> None:
        snapshots = iter((
            HostSnapshot(60.0, 0, False),
            HostSnapshot(52.0, 0, False),
            HostSnapshot(56.0, 0, False),
        ))
        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(.1)"],
            lock_root=self.root, snapshotter=lambda: next(snapshots),
            rss_sampler=lambda _pid: 12 * 1024**2,
            recovery_timeout_seconds=1,
        )
        self.assertTrue(result.report["postExitMemoryRecovered"])
        self.assertEqual(result.report["recoverySnapshotCount"], 2)
        self.assertTrue(result.report["qualified"])


if __name__ == "__main__":
    unittest.main()
