#!/usr/bin/env python3
"""Serial resource supervisor for operator-local delivery analyzers.

It enforces one governed child at a time and records a compact, privacy-safe
resource envelope. The 5 GiB ceiling is provisional until two clean runs on
the canonical M2/8 GB host qualify a final policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import fcntl
import hashlib
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
from typing import Any, Callable, Sequence


SCHEMA_VERSION = 1
PROVISIONAL_MAXIMUM_RSS_BYTES = 5 * 1024**3
MEANINGFUL_SWAP_GROWTH_BYTES = 64 * 1024**2
DEFAULT_TIMEOUT_SECONDS = 900.0
SAMPLE_INTERVAL_SECONDS = 0.05
DEFAULT_RECOVERY_TIMEOUT_SECONDS = 15.0
RECOVERY_SAMPLE_INTERVAL_SECONDS = 0.5


class ResourceSupervisorError(RuntimeError):
    """A process could not run inside the serial resource contract."""


@dataclass(frozen=True)
class HostSnapshot:
    free_percent: float | None
    swap_used_bytes: int | None
    pressure_warning: bool | None

    def report(self) -> dict[str, Any]:
        return {
            "freeMemoryPercent": self.free_percent,
            "swapUsedBytes": self.swap_used_bytes,
            "pressureWarning": self.pressure_warning,
        }


@dataclass(frozen=True)
class SupervisedResult:
    report: dict[str, Any]
    stdout: bytes
    stderr: bytes


def _run_probe(command: Sequence[str]) -> str | None:
    try:
        result = subprocess.run(
            list(command), check=False, capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (result.stdout + "\n" + result.stderr).strip()


def host_snapshot() -> HostSnapshot:
    pressure_text = _run_probe(("/usr/bin/memory_pressure", "-Q"))
    free_percent: float | None = None
    warning: bool | None = None
    if pressure_text:
        match = re.search(r"System-wide memory free percentage:\s*([0-9.]+)%", pressure_text)
        if match:
            free_percent = float(match.group(1))
            warning = free_percent < 10.0
        elif "warn" in pressure_text.lower() or "critical" in pressure_text.lower():
            warning = True
    swap_text = _run_probe(("/usr/sbin/sysctl", "-n", "vm.swapusage"))
    swap_used: int | None = None
    if swap_text:
        match = re.search(r"used\s*=\s*([0-9.]+)([KMG])", swap_text)
        if match:
            scale = {"K": 1024, "M": 1024**2, "G": 1024**3}[match.group(2)]
            swap_used = int(float(match.group(1)) * scale)
    return HostSnapshot(free_percent, swap_used, warning)


def _process_rss_bytes(process_id: int) -> int:
    try:
        result = subprocess.run(
            ["/bin/ps", "-o", "rss=", "-p", str(process_id)],
            check=False, capture_output=True, text=True, timeout=2,
        )
        return max(0, int(result.stdout.strip() or "0") * 1024)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return 0


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _terminate_owned_process(process: subprocess.Popen) -> None:
    """Signal this invocation's group and reap its child, including on probe failure."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def run_supervised(
    command: Sequence[str], *, lock_root: Path,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    maximum_rss_bytes: int = PROVISIONAL_MAXIMUM_RSS_BYTES,
    environment: dict[str, str] | None = None,
    snapshotter: Callable[[], HostSnapshot] = host_snapshot,
    rss_sampler: Callable[[int], int] = _process_rss_bytes,
    recovery_timeout_seconds: float = DEFAULT_RECOVERY_TIMEOUT_SECONDS,
    physical_footprint_sampler: Callable[[int], int | None] | None = None,
    maximum_physical_footprint_bytes: int = PROVISIONAL_MAXIMUM_RSS_BYTES,
) -> SupervisedResult:
    if not command or any(not isinstance(item, str) or not item for item in command):
        raise ResourceSupervisorError("supervised command must be a non-empty string vector")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ResourceSupervisorError("timeout must be positive and finite")
    if maximum_rss_bytes <= 0:
        raise ResourceSupervisorError("maximum RSS must be positive")
    if maximum_physical_footprint_bytes <= 0:
        raise ResourceSupervisorError("maximum physical footprint must be positive")
    if not math.isfinite(recovery_timeout_seconds) or recovery_timeout_seconds < 0:
        raise ResourceSupervisorError("recovery timeout must be finite and nonnegative")
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_path = lock_root / "delivery-analysis-supervisor.lock"
    with lock_path.open("a+b") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ResourceSupervisorError(
                "another generator or heavy delivery analyzer is already active"
            ) from error
        before = snapshotter()
        started = time.monotonic()
        timed_out = False
        peak_rss = 0
        peak_footprint = 0
        footprint_samples = 0
        resource_limit_terminated = False
        resource_probe_failed = False
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                list(command), stdout=stdout_file, stderr=stderr_file,
                env=environment, start_new_session=True,
            )
            try:
                while process.poll() is None:
                    try:
                        peak_rss = max(peak_rss, rss_sampler(process.pid))
                        if physical_footprint_sampler is not None:
                            footprint = physical_footprint_sampler(process.pid)
                            if type(footprint) is not int or footprint <= 0:
                                # A process may exit between the liveness check and
                                # the probe; missing live measurements fail closed.
                                resource_probe_failed = process.poll() is None
                            else:
                                footprint_samples += 1
                                peak_footprint = max(peak_footprint, footprint)
                    except Exception:
                        resource_probe_failed = True
                    resource_limit_terminated = (
                        peak_rss > maximum_rss_bytes
                        or peak_footprint > maximum_physical_footprint_bytes
                    )
                    timed_out = time.monotonic() - started > timeout_seconds
                    if timed_out or resource_limit_terminated or resource_probe_failed:
                        break
                    time.sleep(SAMPLE_INTERVAL_SECONDS)
            finally:
                _terminate_owned_process(process)
            return_code = process.wait()
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read()
            stderr = stderr_file.read()
        wall_seconds = time.monotonic() - started
        # Snapshot only after the child has exited: a next layer may not start
        # while its predecessor still owns resident model pages.
        recovery_started = time.monotonic()
        after = snapshotter()
        recovery_snapshot_count = 1
        while (
            before.free_percent is not None
            and after.free_percent is not None
            and after.free_percent < before.free_percent - 5.0
            and time.monotonic() - recovery_started < recovery_timeout_seconds
        ):
            time.sleep(RECOVERY_SAMPLE_INTERVAL_SECONDS)
            after = snapshotter()
            recovery_snapshot_count += 1
        recovery_wait_seconds = time.monotonic() - recovery_started
        swap_delta = (
            after.swap_used_bytes - before.swap_used_bytes
            if before.swap_used_bytes is not None and after.swap_used_bytes is not None
            else None
        )
        pressure_clean = before.pressure_warning is False and after.pressure_warning is False
        swap_clean = swap_delta is not None and swap_delta <= MEANINGFUL_SWAP_GROWTH_BYTES
        memory_recovered = (
            before.free_percent is not None and after.free_percent is not None
            and after.free_percent >= before.free_percent - 5.0
        )
        failures: list[str] = []
        if timed_out:
            failures.append("timeout")
        if return_code != 0:
            failures.append("nonzero-exit")
        if peak_rss <= 0:
            failures.append("peak-rss-unavailable")
        elif peak_rss > maximum_rss_bytes:
            failures.append("provisional-rss-ceiling-exceeded")
        if physical_footprint_sampler is not None and footprint_samples == 0:
            failures.append("physical-footprint-unavailable")
        if peak_footprint > maximum_physical_footprint_bytes:
            failures.append("provisional-physical-footprint-ceiling-exceeded")
        if resource_probe_failed:
            failures.append("resource-probe-failed")
        if resource_limit_terminated:
            failures.append("resource-limit-termination")
        if not pressure_clean:
            failures.append("host-pressure-not-clean")
        if not swap_clean:
            failures.append("swap-recovery-unqualified")
        if not memory_recovered:
            failures.append("post-exit-memory-recovery-unqualified")
        report = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "delivery-analyzer-resource-envelope",
            "provisionalPolicy": True,
            "promotionAuthority": False,
            "timeoutSeconds": timeout_seconds,
            "timedOut": timed_out,
            "returnCode": return_code,
            "cleanExit": return_code == 0 and not (timed_out or resource_limit_terminated or resource_probe_failed),
            "wallSeconds": wall_seconds,
            "peakRSSBytes": peak_rss,
            "maximumAllowedRSSBytes": maximum_rss_bytes,
            "physicalFootprintMeasurementRequested": physical_footprint_sampler is not None,
            "peakPhysicalFootprintBytes": peak_footprint if footprint_samples else None,
            "physicalFootprintSampleCount": footprint_samples,
            "maximumAllowedPhysicalFootprintBytes": maximum_physical_footprint_bytes,
            "resourceLimitTerminated": resource_limit_terminated,
            "hostBefore": before.report(),
            "hostAfter": after.report(),
            "swapDeltaBytes": swap_delta,
            "postExitMemoryRecovered": memory_recovered,
            "recoverySnapshotCount": recovery_snapshot_count,
            "recoveryWaitSeconds": recovery_wait_seconds,
            "stdoutSHA256": _digest(stdout),
            "stderrSHA256": _digest(stderr),
            "stdoutByteCount": len(stdout),
            "stderrByteCount": len(stderr),
            "qualificationFailures": failures,
            "qualified": not failures,
        }
        return SupervisedResult(report, stdout, stderr)
