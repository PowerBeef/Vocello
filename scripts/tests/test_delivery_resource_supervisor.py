#!/usr/bin/env python3
"""Deterministic contracts for serial delivery-analyzer supervision."""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

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

    def test_denied_shutdown_preserves_output_and_observed_exit(self) -> None:
        # An exit racing killpg must not discard the resource envelope. EPERM
        # is not proof of either successful termination or a dead process.
        with patch("delivery_resource_supervisor.os.killpg", side_effect=PermissionError("private details")):
            result = run_supervised(
                [sys.executable, "-c", "import time; print('completed', flush=True); time.sleep(.15)"],
                lock_root=self.root, snapshotter=self._snapshot,
                rss_sampler=lambda _: 6 * 1024**3,
            )
        self.assertEqual(result.stdout.strip(), b"completed")
        self.assertEqual(result.report["returnCode"], 0)
        self.assertTrue(result.report["processExitConfirmed"])
        self.assertFalse(result.report["qualified"])
        self.assertIn("process-group-signal-denied", result.report["qualificationFailures"])
        self.assertNotIn("private details", str(result.report))

    def test_unconfirmed_exit_retains_serial_lock_and_never_claims_recovery(self) -> None:
        children = []
        spawn = subprocess.Popen

        def capture(*args, **kwargs):
            child = spawn(*args, **kwargs)
            children.append(child)
            return child

        try:
            with patch("delivery_resource_supervisor.subprocess.Popen", side_effect=capture), \
                 patch("delivery_resource_supervisor.os.killpg", side_effect=PermissionError()), \
                 patch("delivery_resource_supervisor.SHUTDOWN_WAIT_SECONDS", .01), \
                 patch("delivery_resource_supervisor.time.sleep"), \
                 patch.object(self, "_snapshot", wraps=self._snapshot) as snapshots:
                result = run_supervised(
                    [sys.executable, "-c", "import time; time.sleep(.5)"],
                    lock_root=self.root, snapshotter=snapshots,
                    rss_sampler=lambda _: 6 * 1024**3,
                )
                self.assertEqual(snapshots.call_count, 1)
            self.assertIsNone(result.report["returnCode"])
            self.assertFalse(result.report["processExitConfirmed"])
            self.assertFalse(result.report["outputCaptureComplete"])
            self.assertFalse(result.report["postExitMemoryRecovered"])
            self.assertEqual(result.report["recoverySnapshotCount"], 0)
            self.assertIn("process-exit-unconfirmed", result.report["qualificationFailures"])
            with self.assertRaisesRegex(ResourceSupervisorError, "already active"):
                run_supervised([sys.executable, "-c", "print('forbidden overlap')"], lock_root=self.root)
        finally:
            for child in children:
                child.wait(timeout=3)
        # No permanently stale lock after the owned child really exits.
        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(.1)"],
            lock_root=self.root, snapshotter=self._snapshot, rss_sampler=lambda _: 1024,
        )
        self.assertTrue(result.report["qualified"])

    def test_denied_term_escalates_to_owned_group_kill_and_reaps(self) -> None:
        killpg = os.killpg
        signals = []

        def deny_term(pid, sig):
            signals.append(sig)
            if sig == signal.SIGTERM:
                raise PermissionError()
            killpg(pid, sig)

        with patch("delivery_resource_supervisor.os.killpg", side_effect=deny_term), \
             patch("delivery_resource_supervisor.SHUTDOWN_WAIT_SECONDS", .05):
            result = run_supervised(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                lock_root=self.root, snapshotter=self._snapshot, rss_sampler=lambda _: 6 * 1024**3,
            )
        self.assertEqual(signals, [signal.SIGTERM, signal.SIGKILL])
        self.assertEqual(result.report["returnCode"], -signal.SIGKILL)
        self.assertTrue(result.report["processExitConfirmed"])
        self.assertFalse(result.report["qualified"])

    def test_group_disappears_during_exit_still_reaps_child(self) -> None:
        with patch("delivery_resource_supervisor.os.killpg", side_effect=ProcessLookupError()):
            result = run_supervised(
                [sys.executable, "-c", "import time; print('done'); time.sleep(.1)"],
                lock_root=self.root, snapshotter=self._snapshot, rss_sampler=lambda _: 6 * 1024**3,
            )
        self.assertEqual(result.report["returnCode"], 0)
        self.assertTrue(result.report["processExitConfirmed"])
        self.assertEqual(result.report["shutdownFailures"], [])

    def test_physical_footprint_stops_child_even_when_rss_is_small(self) -> None:
        child_ids = []

        def footprint(pid):
            child_ids.append(pid)
            return 6 * 1024**3

        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            lock_root=self.root, snapshotter=self._snapshot,
            rss_sampler=lambda _: 12 * 1024**2,
            physical_footprint_sampler=footprint,
        )
        self.assertFalse(result.report["qualified"])
        self.assertTrue(result.report["resourceLimitTerminated"])
        self.assertFalse(result.report["cleanExit"])
        self.assertEqual(result.report["peakPhysicalFootprintBytes"], 6 * 1024**3)
        self.assertIn("provisional-physical-footprint-ceiling-exceeded", result.report["qualificationFailures"])
        with self.assertRaises(ProcessLookupError):
            os.kill(child_ids[0], 0)

    def test_rss_limit_is_enforced_not_just_reported(self) -> None:
        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            lock_root=self.root, snapshotter=self._snapshot,
            rss_sampler=lambda _: 6 * 1024**3,
        )
        self.assertTrue(result.report["resourceLimitTerminated"])
        self.assertIn("provisional-rss-ceiling-exceeded", result.report["qualificationFailures"])
        self.assertFalse(result.report["physicalFootprintMeasurementRequested"])
        self.assertIsNone(result.report["peakPhysicalFootprintBytes"])

    def test_measured_footprint_at_ceiling_is_qualified_without_adding_rss(self) -> None:
        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(.15)"],
            lock_root=self.root, snapshotter=self._snapshot,
            rss_sampler=lambda _: 12 * 1024**2,
            physical_footprint_sampler=lambda _: 64 * 1024**2,
            maximum_physical_footprint_bytes=64 * 1024**2,
        )
        self.assertTrue(result.report["qualified"])
        self.assertFalse(result.report["resourceLimitTerminated"])
        self.assertTrue(result.report["physicalFootprintMeasurementRequested"])
        self.assertGreater(result.report["physicalFootprintSampleCount"], 0)
        self.assertEqual(result.report["peakPhysicalFootprintBytes"], 64 * 1024**2)

    def test_boolean_footprint_cannot_qualify_as_measurement(self) -> None:
        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            lock_root=self.root, snapshotter=self._snapshot,
            rss_sampler=lambda _: 12 * 1024**2,
            physical_footprint_sampler=lambda _: True,
        )
        self.assertFalse(result.report["qualified"])
        self.assertIn("physical-footprint-unavailable", result.report["qualificationFailures"])

    def test_missing_requested_footprint_fails_closed(self) -> None:
        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            lock_root=self.root, snapshotter=self._snapshot,
            rss_sampler=lambda _: 12 * 1024**2,
            physical_footprint_sampler=lambda _: None,
        )
        self.assertFalse(result.report["qualified"])
        self.assertIn("physical-footprint-unavailable", result.report["qualificationFailures"])
        self.assertIn("resource-probe-failed", result.report["qualificationFailures"])

    def test_probe_exception_reaps_child_and_redacts_error(self) -> None:
        child_ids = []

        def broken(pid):
            child_ids.append(pid)
            raise RuntimeError("private probe details")

        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            lock_root=self.root, snapshotter=self._snapshot, rss_sampler=broken,
        )
        self.assertIn("resource-probe-failed", result.report["qualificationFailures"])
        self.assertNotIn("private probe details", str(result.report))
        with self.assertRaises(ProcessLookupError):
            os.kill(child_ids[0], 0)

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
