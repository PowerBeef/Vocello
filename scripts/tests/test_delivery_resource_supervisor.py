#!/usr/bin/env python3
"""Deterministic contracts for serial delivery-analyzer supervision."""

from __future__ import annotations

import fcntl
import copy
import json
import os
import signal
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_resource_supervisor import (  # noqa: E402
    FootprintSample,
    HostSnapshot,
    ProcessSample,
    ResourceSupervisorError,
    host_snapshot,
    owned_process_sample,
    parse_free_percent,
    parse_macos_footprint_peak,
    parse_macos_footprint_report,
    parse_swap_used_bytes,
    macos_footprint_sampler,
    run_supervised,
)

GIB = 1024**3
MIB = 1024**2
# `sysctl -n vm.swapusage` and `memory_pressure -Q` as the fr_CA host prints them.
FR_CA_SWAP = "total = 2048,00M  used = 12,50M  free = 2035,50M  (encrypted)"
FR_CA_PRESSURE = (
    "The system has 17179869184 (1048576 pages with a page size of 16384).\n"
    "System-wide memory free percentage: 71%"
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

    def _probe_exit_race(self, error, *, exits=True, sampled=True, exit_code=0):
        """Kernel probe loses the child before Popen has observed its exit."""
        child = Mock(pid=123456)
        status = {"code": None}
        child.poll.side_effect = lambda: status["code"]

        def wait(timeout):
            if not exits and status["code"] is None:
                raise subprocess.TimeoutExpired("fixture", timeout)
            status["code"] = exit_code if status["code"] is None else status["code"]
            return status["code"]

        def stop(_pid, _sig):
            status["code"] = -signal.SIGTERM

        child.wait.side_effect = wait
        samples = ([1024] if sampled else []) + [error]
        with patch("delivery_resource_supervisor.subprocess.Popen", return_value=child), \
             patch("delivery_resource_supervisor.os.killpg", side_effect=stop) as kill, \
             patch("delivery_resource_supervisor.time.sleep"):
            result = run_supervised(
                ["fixture"], lock_root=self.root, snapshotter=self._snapshot,
                rss_sampler=lambda _: 1024,
                physical_footprint_sampler=Mock(side_effect=samples),
            )
        return result.report, kill.call_count

    def test_typed_probe_exit_is_confirmed_before_signalling(self) -> None:
        report, signals = self._probe_exit_race(ProcessLookupError("private kernel report"))
        self.assertEqual(signals, 0)
        self.assertTrue(report["qualified"])
        self.assertEqual(report["physicalFootprintSampleCount"], 1)
        self.assertEqual(report["terminalProbeCount"], 1)
        self.assertNotIn("private kernel report", str(report))

    def test_probe_lookup_error_does_not_excuse_a_live_child(self) -> None:
        report, signals = self._probe_exit_race(ProcessLookupError(), exits=False)
        self.assertGreater(signals, 0)
        self.assertFalse(report["qualified"])
        self.assertIn("resource-probe-failed", report["qualificationFailures"])

    def test_confirmed_exit_without_a_sample_cannot_qualify(self) -> None:
        report, signals = self._probe_exit_race(ProcessLookupError(), sampled=False)
        self.assertEqual(signals, 0)
        self.assertFalse(report["qualified"])
        self.assertIn("physical-footprint-unavailable", report["qualificationFailures"])

    def test_confirmed_nonzero_exit_cannot_qualify(self) -> None:
        report, signals = self._probe_exit_race(ProcessLookupError(), exit_code=1)
        self.assertEqual(signals, 0)
        self.assertIn("nonzero-exit", report["qualificationFailures"])

    def test_permission_and_unknown_probe_errors_remain_failures(self) -> None:
        for error in (PermissionError("private path"), RuntimeError("private path")):
            with self.subTest(error=type(error).__name__):
                report, _ = self._probe_exit_race(error)
                self.assertFalse(report["qualified"])
                self.assertIn("resource-probe-failed", report["qualificationFailures"])
                self.assertNotIn("private path", str(report))

    def test_footprint_parser_requires_exact_pid_byte_measurement(self) -> None:
        payload = {"unit": "byte", "bytes per unit": 1, "errors": [], "warnings": [],
                   "processes": [{"pid": 42, "footprint": 1024}]}
        self.assertEqual(parse_macos_footprint_report(payload, 42), 1024)
        mutations = [
            {"unit": "MiB"}, {"bytes per unit": True}, {"bytes per unit": 1024},
            {"processes": [{"pid": 43, "footprint": 1024}]},
            {"processes": [{"pid": 42, "footprint": 1024}] * 2},
            {"errors": ["permission denied: private path"]},
            {"warnings": "malformed"},
        ] + [{"processes": [{"pid": 42, "footprint": value}]}
             for value in (None, True, -1, 0, 1.5, "1024")]
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(ResourceSupervisorError):
                parse_macos_footprint_report(payload | mutation, 42)

    def test_footprint_parser_types_only_allowlisted_kernel_teardown(self) -> None:
        payload = {
            "unit": "byte", "bytes per unit": 1,
            "errors": ["mach_vm_region_recurse - (os/kern) invalid argument"],
            "warnings": ["Unable to retrieve ledger entry info - No such process",
                         "vm.get_owned_vmobjects - No such process"],
            "processes": [{"pid": 42, "footprint": None}],
        }
        with self.assertRaises(ProcessLookupError):
            parse_macos_footprint_report(payload, 42)
        for field, value in (("errors", "permission denied"), ("warnings", "unexplained warning")):
            invalid = copy.deepcopy(payload)
            invalid[field].append(value)
            with self.assertRaises(ResourceSupervisorError):
                parse_macos_footprint_report(invalid, 42)
        with self.assertRaises(ResourceSupervisorError):
            parse_macos_footprint_report(payload, 43)

    def test_footprint_sampler_retains_reports_and_refuses_stderr_or_directory_reuse(self):
        raw = self.root / "samples"
        sample = macos_footprint_sampler(raw)
        with self.assertRaises(FileExistsError):
            macos_footprint_sampler(raw)
        def run(command, **kwargs):
            self.assertEqual(command[:3], ["/usr/bin/footprint", "-p", "42"])
            self.assertEqual(kwargs["env"]["LC_ALL"], "C")
            Path(command[-1]).write_text(json.dumps({
                "unit": "byte", "bytes per unit": 1, "errors": [], "warnings": [],
                "processes": [{"pid": 42, "footprint": 1024,
                               "auxiliary": {"phys_footprint_peak": 4096, "phys_footprint": 1024}}],
            }))
            return subprocess.CompletedProcess(command, 0, b"", b"")
        with patch("delivery_resource_supervisor.subprocess.run", side_effect=run):
            # The tool's lifetime peak is kept beside the current footprint (audit #38).
            self.assertEqual(sample(42), FootprintSample(1024, 4096))
        self.assertTrue((raw / "footprint-0000.json").is_file())
        with patch("delivery_resource_supervisor.subprocess.run", return_value=
                   subprocess.CompletedProcess([], 1, b"", b"permission denied: private path")), \
             self.assertRaises(ResourceSupervisorError):
            sample(42)
        self.assertEqual((raw / "footprint-0001.stderr.log").read_bytes(), b"permission denied: private path")

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

    # -- owned-process-probe-v3: locale-free host probes (audit #7) ----------

    def test_fr_ca_formatted_host_text_parses(self) -> None:
        self.assertEqual(parse_swap_used_bytes(FR_CA_SWAP), int(12.5 * MIB))
        self.assertEqual(parse_swap_used_bytes("total = 0,00M  used = 0,00M  free = 0,00M  (encrypted)"), 0)
        self.assertEqual(parse_swap_used_bytes("total = 4.00G  used = 1.25G  free = 2.75G"), int(1.25 * GIB))
        self.assertIsNone(parse_swap_used_bytes("swap usage unavailable"))
        self.assertEqual(parse_free_percent(FR_CA_PRESSURE), 71.0)
        self.assertEqual(parse_free_percent("System-wide memory free percentage: 71,5%"), 71.5)
        self.assertIsNone(parse_free_percent("memory_pressure: unknown option"))

    def test_host_snapshot_reads_sysctl_without_spawning_a_probe(self) -> None:
        values = {"kern.memorystatus_level": 71, "vm.swapusage": 12 * MIB,
                  "kern.memorystatus_vm_pressure_level": 1, "hw.memsize": 16 * GIB}

        def no_probe(command):
            raise AssertionError(f"text probe spawned: {command}")

        snapshot = host_snapshot(read_sysctl=values.get, run_probe=no_probe)
        self.assertEqual(snapshot, HostSnapshot(71.0, 12 * MIB, False, 1, 16 * GIB, ()))
        self.assertEqual(snapshot.report()["kernelPressureLevel"], 1)

    def test_text_fallback_probes_run_in_the_c_locale(self) -> None:
        calls = []

        def run(command, **kwargs):
            calls.append((command, kwargs["env"]))
            output = FR_CA_PRESSURE if command[0].endswith("memory_pressure") else FR_CA_SWAP
            return subprocess.CompletedProcess(command, 0, output, "")

        with patch("delivery_resource_supervisor.subprocess.run", side_effect=run):
            snapshot = host_snapshot(read_sysctl=lambda _name: None)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(env["LC_ALL"] == "C" and env["LANG"] == "C" for _, env in calls))
        self.assertEqual((snapshot.free_percent, snapshot.swap_used_bytes), (71.0, int(12.5 * MIB)))
        self.assertEqual(snapshot.probe_failures,
                         ("kernel-pressure-level-unavailable", "physical-memory-unavailable"))

    def test_supervised_run_under_fr_ca_host_output_is_qualified(self) -> None:
        """Roadmap BT-05: a trivial supervised child under fr_CA comes back qualified."""
        def fr_ca_probe(command):
            return FR_CA_PRESSURE if command[0].endswith("memory_pressure") else FR_CA_SWAP

        def snapshot():
            kernel = {"kern.memorystatus_vm_pressure_level": 1, "hw.memsize": 16 * GIB}
            return host_snapshot(read_sysctl=kernel.get, run_probe=fr_ca_probe)

        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(.15)"],
            lock_root=self.root, snapshotter=snapshot, rss_sampler=lambda _pid: 12 * MIB,
        )
        self.assertTrue(result.report["qualified"], result.report["qualificationFailures"])
        self.assertEqual(result.report["hostBefore"]["swapUsedBytes"], int(12.5 * MIB))
        self.assertEqual(result.report["hostAfter"]["probeFailures"], [])
        self.assertEqual(result.report["swapDeltaBytes"], 0)

    def test_unparsed_host_probe_is_typed_apart_from_swap_growth(self) -> None:
        def snapshot():
            kernel = {"kern.memorystatus_level": 70, "kern.memorystatus_vm_pressure_level": 1,
                      "hw.memsize": 16 * GIB}
            return host_snapshot(read_sysctl=kernel.get, run_probe=lambda _command: "unexpected text")

        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(.1)"],
            lock_root=self.root, snapshotter=snapshot, rss_sampler=lambda _pid: 12 * MIB,
        )
        failures = result.report["qualificationFailures"]
        self.assertFalse(result.report["qualified"])
        self.assertIn("host-swap-probe-failed", failures)
        self.assertNotIn("swap-recovery-unqualified", failures)
        self.assertNotIn("post-exit-memory-recovery-unqualified", failures)
        self.assertEqual(result.report["hostBefore"]["probeFailures"], ["swap-usage-unparsed"])

    # -- in-process sampling (audit #38, #101) --------------------------------

    def test_default_probe_samples_the_child_in_process(self) -> None:
        def no_probe_process(*args, **kwargs):
            raise AssertionError("a probe subprocess was spawned during supervision")

        with patch("delivery_resource_supervisor.subprocess.run", side_effect=no_probe_process):
            result = run_supervised(
                [sys.executable, "-c", "import time; time.sleep(.3)"],
                lock_root=self.root, snapshotter=self._snapshot,
            )
        report = result.report
        self.assertTrue(report["qualified"], report["qualificationFailures"])
        self.assertEqual(report["probeAlgorithmVersion"], "owned-process-probe-v4")
        self.assertIn(report["processProbe"], ("libproc-rusage-v4", "procfs-status"))
        self.assertGreater(report["peakRSSBytes"], 0)
        self.assertGreaterEqual(report["resourceSampleCount"], 2)
        self.assertEqual(report["sampleIntervalSeconds"], 0.05)
        self.assertLess(report["maximumSampleGapSeconds"], 1.0)
        self.assertEqual(report["probeFailureCount"], 0)
        # The kernel's lifetime maximum RSS from the reap, kept apart from the samples.
        self.assertGreater(report["waitMaxRSSBytes"], 0)

    def test_failed_process_sample_is_counted_never_read_as_zero(self) -> None:
        def broken(_pid):
            raise ResourceSupervisorError("private probe detail")

        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            lock_root=self.root, snapshotter=self._snapshot, process_sampler=broken,
        )
        self.assertFalse(result.report["qualified"])
        self.assertIn("resource-probe-failed", result.report["qualificationFailures"])
        self.assertEqual(result.report["probeFailures"], [{"stage": "process", "reason": "probe-exception"}])
        self.assertEqual(result.report["probeFailureCount"], 1)
        self.assertNotIn("private probe detail", str(result.report))

    def test_scripted_spike_between_samples_is_caught_by_the_lifetime_peak(self) -> None:
        readings = iter([
            ProcessSample(64 * MIB, 128 * MIB, 128 * MIB),
            ProcessSample(64 * MIB, 128 * MIB, 128 * MIB),
            # The spike rose and fell between two samples: only the kernel's
            # lifetime high-water mark saw it.
            ProcessSample(64 * MIB, 128 * MIB, 6 * GIB),
        ])

        def sampler(_pid):
            return next(readings, ProcessSample(64 * MIB, 128 * MIB, 6 * GIB))

        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            lock_root=self.root, snapshotter=self._snapshot,
            process_sampler=sampler, measure_physical_footprint=True,
        )
        report = result.report
        self.assertTrue(report["resourceLimitTerminated"])
        self.assertEqual(report["sampledPeakPhysicalFootprintBytes"], 128 * MIB)
        self.assertEqual(report["lifetimeMaxPhysicalFootprintBytes"], 6 * GIB)
        self.assertEqual(report["peakPhysicalFootprintBytes"], 6 * GIB)
        self.assertIn("provisional-physical-footprint-ceiling-exceeded", report["qualificationFailures"])

    @unittest.skipUnless(sys.platform == "darwin", "proc_pid_rusage is a macOS probe")
    def test_real_child_spike_is_kept_through_exit(self) -> None:
        code = (
            "import time; time.sleep(.15); b = bytearray(96 * 1024 * 1024); "
            "b[::16384] = b'x' * len(b[::16384]); del b; time.sleep(.15)"
        )
        result = run_supervised(
            [sys.executable, "-c", code], lock_root=self.root, snapshotter=self._snapshot,
            measure_physical_footprint=True,
        )
        report = result.report
        self.assertTrue(report["qualified"], report["qualificationFailures"])
        self.assertTrue(report["terminalLifetimePeakRead"])
        self.assertGreaterEqual(report["lifetimeMaxPhysicalFootprintBytes"], 96 * MIB)
        self.assertEqual(report["peakPhysicalFootprintBytes"], report["lifetimeMaxPhysicalFootprintBytes"])
        self.assertTrue(report["physicalFootprintCeilingEvaluated"])

    @unittest.skipUnless(sys.platform == "darwin", "proc_pid_rusage is a macOS probe")
    def test_owned_process_sample_reads_the_live_child(self) -> None:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(.3)"])
        try:
            sample = owned_process_sample(child.pid)
        finally:
            child.wait(timeout=5)
        self.assertGreater(sample.resident_bytes, 0)
        self.assertGreater(sample.lifetime_max_physical_footprint_bytes, 0)
        with self.assertRaises(ProcessLookupError):
            owned_process_sample(child.pid)

    def test_unmeasured_footprint_ceiling_is_marked_not_evaluated(self) -> None:
        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(.1)"],
            lock_root=self.root, snapshotter=self._snapshot, rss_sampler=lambda _pid: 12 * MIB,
        )
        self.assertTrue(result.report["qualified"])
        self.assertFalse(result.report["physicalFootprintCeilingEvaluated"])
        self.assertIsNone(result.report["peakPhysicalFootprintBytes"])

    def test_requested_in_process_footprint_is_evaluated(self) -> None:
        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(.15)"],
            lock_root=self.root, snapshotter=self._snapshot,
            process_sampler=lambda _pid: ProcessSample(64 * MIB, 128 * MIB, 256 * MIB),
            measure_physical_footprint=True,
        )
        report = result.report
        self.assertTrue(report["qualified"], report["qualificationFailures"])
        self.assertTrue(report["physicalFootprintMeasurementRequested"])
        self.assertTrue(report["physicalFootprintCeilingEvaluated"])
        self.assertEqual(report["peakPhysicalFootprintBytes"], 256 * MIB)
        self.assertEqual(report["processProbe"], "injected")

    def test_footprint_peak_parser_reads_the_tool_lifetime_peak(self) -> None:
        payload = {"unit": "byte", "bytes per unit": 1, "errors": [], "warnings": [],
                   "processes": [{"pid": 42, "footprint": 1024,
                                  "auxiliary": {"phys_footprint_peak": 8192}}]}
        self.assertEqual(parse_macos_footprint_peak(payload, 42), 8192)
        payload["processes"][0].pop("auxiliary")
        self.assertIsNone(parse_macos_footprint_peak(payload, 42))

    # -- post-exit recovery attribution (audit #102; the rule is unchanged) --

    def _attributed(self, *, child_lifetime: int, ceiling: int = 5 * GIB) -> dict:
        snapshots = iter((
            HostSnapshot(60.0, 0, False, 1, 16 * GIB),
            HostSnapshot(40.0, 0, False, 2, 16 * GIB),
        ))
        return run_supervised(
            [sys.executable, "-c", "import time; time.sleep(.1)"],
            lock_root=self.root, snapshotter=lambda: next(snapshots),
            process_sampler=lambda _pid: ProcessSample(64 * MIB, 128 * MIB, child_lifetime),
            measure_physical_footprint=True, maximum_physical_footprint_bytes=ceiling,
            recovery_timeout_seconds=0,
        ).report

    def test_drop_larger_than_the_child_peak_is_attributed_to_another_allocator(self) -> None:
        report = self._attributed(child_lifetime=GIB)
        attribution = report["recoveryAttribution"]
        self.assertEqual(attribution["status"], "drop-exceeds-child-peak")
        self.assertEqual(attribution["freePercentDropPoints"], 20.0)
        self.assertEqual(attribution["childPeakPercentOfPhysicalMemory"], 6.25)
        self.assertEqual(attribution["childPeakBasis"], "physical-footprint")
        self.assertEqual(attribution["kernelPressureLevelAfter"], 2)
        self.assertFalse(attribution["ruleChanged"])
        # Report only: the five-point recovery rule still fails the run.
        self.assertIn("post-exit-memory-recovery-unqualified", report["qualificationFailures"])

    def test_drop_within_the_child_peak_is_attributed_to_the_child(self) -> None:
        report = self._attributed(child_lifetime=4 * GIB, ceiling=8 * GIB)
        self.assertEqual(report["recoveryAttribution"]["status"], "drop-within-child-peak")
        self.assertEqual(report["recoveryAttribution"]["childPeakPercentOfPhysicalMemory"], 25.0)
        self.assertIn("post-exit-memory-recovery-unqualified", report["qualificationFailures"])

    def test_recovered_run_is_attributed_as_recovered(self) -> None:
        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(.1)"],
            lock_root=self.root, snapshotter=self._snapshot, rss_sampler=lambda _pid: 12 * MIB,
        )
        self.assertEqual(result.report["recoveryAttribution"]["status"], "recovered")
        self.assertEqual(result.report["recoveryAttribution"]["childPeakBasis"], "resident")
        candidate = result.report["candidateRecoveryRule"]
        self.assertEqual(candidate["algorithm"], "attributed-post-exit-recovery-v2")
        self.assertFalse(candidate["binding"])

    # -- the recommended rule, report-only until M6 evidence (audit #102) --

    def _candidate(self, before: HostSnapshot, after: HostSnapshot, *, child: int) -> dict:
        snapshots = iter((before, after))
        return run_supervised(
            [sys.executable, "-c", "import time; time.sleep(.1)"],
            lock_root=self.root, snapshotter=lambda: next(snapshots),
            process_sampler=lambda _pid: ProcessSample(64 * MIB, 128 * MIB, child),
            measure_physical_footprint=True, maximum_physical_footprint_bytes=8 * GIB,
            recovery_timeout_seconds=0,
        ).report

    def test_the_candidate_rule_frees_a_concurrent_allocator_only_under_normal_pressure(self) -> None:
        # A 20-point drop the child's 1 GiB (6.25 %) cannot explain, kernel level normal.
        report = self._candidate(
            HostSnapshot(60.0, 0, False, 1, 16 * GIB), HostSnapshot(40.0, 0, False, 1, 16 * GIB), child=GIB,
        )
        self.assertIn("post-exit-memory-recovery-unqualified", report["qualificationFailures"])
        self.assertFalse(report["qualified"], "the binding five-point rule is unchanged")
        candidate = report["candidateRecoveryRule"]
        self.assertEqual((candidate["qualified"], candidate["attribution"]), (True, "drop-exceeds-child-peak"))
        # The same drop under a warning kernel pressure level fails the candidate too.
        warned = self._candidate(
            HostSnapshot(60.0, 0, False, 1, 16 * GIB), HostSnapshot(40.0, 0, False, 2, 16 * GIB), child=GIB,
        )["candidateRecoveryRule"]
        self.assertEqual(warned["failures"], ["kernel-pressure-not-normal"])

    def test_the_candidate_rule_still_fails_a_drop_the_child_explains(self) -> None:
        report = self._candidate(
            HostSnapshot(60.0, 0, False, 1, 16 * GIB), HostSnapshot(40.0, 0, False, 1, 16 * GIB), child=4 * GIB,
        )
        self.assertEqual(report["candidateRecoveryRule"]["failures"], ["post-exit-recovery-attributed-to-child"])
        # Without a kernel level, the binding free-percent warning judges pressure.
        fallback = self._candidate(
            HostSnapshot(60.0, 0, False, None, 16 * GIB), HostSnapshot(8.0, 0, True, None, 16 * GIB), child=GIB,
        )["candidateRecoveryRule"]
        self.assertIn("host-pressure-not-clean", fallback["failures"])

    def test_the_recovery_report_counts_what_the_candidate_would_flip(self) -> None:
        from delivery_resource_supervisor import envelopes_in, main, recovery_report

        concurrent = self._candidate(
            HostSnapshot(60.0, 0, False, 1, 16 * GIB), HostSnapshot(40.0, 0, False, 1, 16 * GIB), child=GIB,
        )
        child = self._candidate(
            HostSnapshot(60.0, 0, False, 1, 16 * GIB), HostSnapshot(40.0, 0, False, 1, 16 * GIB), child=4 * GIB,
        )
        evidence = {"producer": {"resourceEnvelope": concurrent}, "rows": [{"envelope": child}]}
        self.assertEqual(len(envelopes_in(evidence)), 2)
        summary = recovery_report(envelopes_in(evidence))
        self.assertEqual(summary["bindingRecoveryFailures"], 2)
        self.assertEqual(summary["candidateFailures"], 1)
        self.assertEqual(summary["candidateWouldQualifyBindingFailure"], 1)
        self.assertEqual(summary["attribution"], {"drop-exceeds-child-peak": 1, "drop-within-child-peak": 1})
        path = self.root / "evidence.json"
        path.write_text(json.dumps(evidence))
        self.assertEqual(main(["recovery-report", str(path)]), 0)


    def test_the_recovery_report_counts_only_provably_serial_envelopes(self) -> None:
        """Admitted envelopes are serial only when the one-worker cap also held back every Stage 1."""
        from delivery_resource_supervisor import recovery_report

        base = self._candidate(
            HostSnapshot(60.0, 0, False, 1, 16 * GIB), HostSnapshot(59.0, 0, False, 1, 16 * GIB), child=GIB,
        )
        admitted = {"judge": "asr.whisper-small@1", "workerCap": 1, "serialScope": "workers-and-stage1"}
        serial = {**base, "admission": admitted, "sessionID": "session-a", "hostProfileID": "mac-mini-m6-16gb"}
        # Before Stage 1 counted against the cap, another orchestrator's DSP could run beside it.
        overlapped = {**base, "admission": {**admitted, "serialScope": None}, "sessionID": "session-b",
                      "hostProfileID": "mac-mini-m6-16gb"}
        uncapped = {**base, "admission": {**admitted, "workerCap": None}, "sessionID": "session-b",
                    "hostProfileID": "mac-mini-m6-16gb"}
        standalone = {**base, "sessionID": "session-c", "hostProfileID": None}
        summary = recovery_report([serial, overlapped, uncapped, standalone])
        self.assertEqual((summary["kind"], summary["schemaVersion"]), ("delivery-analyzer-recovery-report", 1))
        self.assertEqual(summary["serialEnvelopes"], 2)
        self.assertEqual(summary["overlapPossibleEnvelopes"], 2)
        self.assertEqual(summary["serialByJudge"], {"asr.whisper-small@1": 1})
        self.assertEqual(summary["byJudge"], {"asr.whisper-small@1": 3})
        self.assertEqual(summary["sessionIDs"], ["session-a", "session-b", "session-c"])
        self.assertEqual((summary["hostProfileIDs"], summary["envelopesWithoutHost"]), (["mac-mini-m6-16gb"], 1))

    def test_every_envelope_names_its_session_and_host(self) -> None:
        from delivery_resource_supervisor import PROCESS_SESSION_ID, host_hardware_profile_id

        report = run_supervised([sys.executable, "-c", "print(1)"], lock_root=self.root,
                                snapshotter=self._snapshot, rss_sampler=lambda _pid: MIB).report
        self.assertEqual(report["sessionID"], PROCESS_SESSION_ID)
        self.assertEqual(report["hostProfileID"], host_hardware_profile_id())
        named = run_supervised([sys.executable, "-c", "print(1)"], lock_root=self.root, session_id="run-7",
                               snapshotter=self._snapshot, rss_sampler=lambda _pid: MIB).report
        self.assertEqual(named["sessionID"], "run-7")

    # -- owned-process-probe-v4: the child's whole process group ----------

    def test_the_ceiling_binds_the_process_group_sum_live(self) -> None:
        """A descendant's memory counts while it runs, so a group above the ceiling is stopped."""
        leader_ids = []

        def group(leader):
            leader_ids.append(leader)
            return [leader, 999_001, 999_002]

        def resident(pid):
            return {999_001: 40 * MIB, 999_002: 30 * MIB}.get(pid, 20 * MIB)

        started = __import__("time").monotonic()
        result = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            lock_root=self.root, snapshotter=self._snapshot, rss_sampler=resident, group_lister=group,
            maximum_rss_bytes=64 * MIB,
        )
        report = result.report
        self.assertLess(__import__("time").monotonic() - started, 10.0)
        self.assertTrue(report["resourceLimitTerminated"])
        self.assertEqual(report["peakRSSBytes"], 90 * MIB)
        self.assertEqual(report["maximumSampledProcessCount"], 3)
        self.assertEqual((report["sampledProcessScope"], report["groupProbe"]), ("process-group", "injected"))
        # A member that exits between the listing and its sample is skipped, never a failure.
        vanished = run_supervised(
            [sys.executable, "-c", "import time; time.sleep(.2)"],
            lock_root=self.root, snapshotter=self._snapshot, group_lister=lambda leader: [leader, 999_003],
            rss_sampler=lambda pid: (_ for _ in ()).throw(ProcessLookupError()) if pid == 999_003 else MIB,
        ).report
        self.assertTrue(vanished["qualified"], vanished["qualificationFailures"])
        self.assertEqual(vanished["maximumSampledProcessCount"], 1)

    def test_the_real_group_probe_lists_the_child_and_its_command(self) -> None:
        from delivery_resource_supervisor import process_group_members

        result = run_supervised(
            [sys.executable, "-c",
             "import subprocess, sys, time; child = subprocess.Popen([sys.executable, '-c', "
             "'import time; time.sleep(1)']); time.sleep(.6); child.wait()"],
            lock_root=self.root, snapshotter=self._snapshot,
        )
        self.assertTrue(result.report["qualified"], result.report["qualificationFailures"])
        self.assertGreaterEqual(result.report["maximumSampledProcessCount"], 2)
        self.assertIn(os.getpid(), process_group_members(os.getpgid(0)))

if __name__ == "__main__":
    unittest.main()
