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


def run_supervised(
    command: Sequence[str], *, lock_root: Path,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    maximum_rss_bytes: int = PROVISIONAL_MAXIMUM_RSS_BYTES,
    environment: dict[str, str] | None = None,
    snapshotter: Callable[[], HostSnapshot] = host_snapshot,
    rss_sampler: Callable[[int], int] = _process_rss_bytes,
) -> SupervisedResult:
    if not command or any(not isinstance(item, str) or not item for item in command):
        raise ResourceSupervisorError("supervised command must be a non-empty string vector")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ResourceSupervisorError("timeout must be positive and finite")
    if maximum_rss_bytes <= 0:
        raise ResourceSupervisorError("maximum RSS must be positive")
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
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                list(command), stdout=stdout_file, stderr=stderr_file,
                env=environment, start_new_session=True,
            )
            while process.poll() is None:
                peak_rss = max(peak_rss, rss_sampler(process.pid))
                if time.monotonic() - started > timeout_seconds:
                    timed_out = True
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
                    break
                time.sleep(SAMPLE_INTERVAL_SECONDS)
            return_code = process.wait()
            peak_rss = max(peak_rss, rss_sampler(process.pid))
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read()
            stderr = stderr_file.read()
        wall_seconds = time.monotonic() - started
        # Snapshot only after the child has exited: a next layer may not start
        # while its predecessor still owns resident model pages.
        after = snapshotter()
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
            "cleanExit": return_code == 0 and not timed_out,
            "wallSeconds": wall_seconds,
            "peakRSSBytes": peak_rss,
            "maximumAllowedRSSBytes": maximum_rss_bytes,
            "hostBefore": before.report(),
            "hostAfter": after.report(),
            "swapDeltaBytes": swap_delta,
            "postExitMemoryRecovered": memory_recovered,
            "stdoutSHA256": _digest(stdout),
            "stderrSHA256": _digest(stderr),
            "stdoutByteCount": len(stdout),
            "stderrByteCount": len(stderr),
            "qualificationFailures": failures,
            "qualified": not failures,
        }
        return SupervisedResult(report, stdout, stderr)
