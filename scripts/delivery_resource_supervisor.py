#!/usr/bin/env python3
"""Serial resource supervisor for operator-local delivery analyzers.

It enforces one governed child at a time and records a compact, privacy-safe
resource envelope. The 5 GiB ceiling is sized for the 8 GB support floor and is
provisional until two clean runs on the canonical benchmark host (the Mac mini M6,
roadmap AV-17) qualify a final policy.

``owned-process-probe-v3`` (audit #7, #38, #101, #102):

- The owned child is sampled in-process (``proc_pid_rusage`` on macOS), never by
  spawning a probe per tick, so the cadence is the 50 ms sleep and a failed
  sample is counted and fails closed instead of reading as zero memory.
- Physical footprint, when measured, peaks at the larger of the samples and the
  kernel's lifetime high-water mark, read once more from the exited child before
  it is reaped. ``ru_maxrss`` from the reap is recorded beside the sampled RSS.
- Host memory is read through ``sysctlbyname`` (locale-free); the text fallbacks
  run under ``LC_ALL=C`` and accept either decimal separator, and a host probe
  failure is typed apart from a real pressure, swap or recovery failure.
- The post-exit recovery rule is unchanged (five points of host free memory).
  The envelope adds the kernel pressure level and attribution fields so an
  unqualified recovery can be told apart from a concurrent allocation before
  anyone proposes a rule change.
- The recommended rule change rides beside it, report-only (audit #102; the
  maintainer delegated the decision to the audit's recommendation on
  2026-09-25, which is to measure on the M6 before relaxing anything):
  ``candidateRecoveryRule`` (``attributed-post-exit-recovery-v2``) judges
  pressure by the kernel pressure level the timing lanes use and fails a
  post-exit drop only when the child's own peak can explain it (or nothing
  attributes it); a drop larger than the child's peak is a concurrent
  allocator's. ``recovery-report`` tabulates the binding and candidate
  verdicts over saved envelopes, the evidence a rule change needs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import ctypes
import errno
import fcntl
import functools
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
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
RECOVERY_TOLERANCE_PERCENT_POINTS = 5.0
PRESSURE_WARNING_FREE_PERCENT = 10.0
SHUTDOWN_WAIT_SECONDS = 2.0
PROBE_EXIT_WAIT_SECONDS = 0.25
REAP_POLL_SECONDS = 0.01
PROBE_ALGORITHM_VERSION = "owned-process-probe-v3"
# Text probes are only a fallback for the sysctl reads; they run in the C
# locale so a decimal comma (fr_CA prints "0,00M") never reaches the parser.
PROBE_ENVIRONMENT_OVERRIDES = {"LC_ALL": "C", "LANG": "C"}


class ResourceSupervisorError(RuntimeError):
    """A process could not run inside the serial resource contract."""


@dataclass(frozen=True)
class ProcessSample:
    """One in-process observation of the owned child (bytes)."""

    resident_bytes: int
    physical_footprint_bytes: int | None = None
    lifetime_max_physical_footprint_bytes: int | None = None


@dataclass(frozen=True)
class FootprintSample:
    """A physical-footprint reading with the kernel's lifetime peak when known."""

    current_bytes: int
    lifetime_peak_bytes: int | None = None


def _footprint_report_row(payload: Any, process_id: int) -> dict[str, Any]:
    invalid = ResourceSupervisorError("invalid physical-footprint report")
    if (type(process_id) is not int or process_id <= 0 or not isinstance(payload, dict)
            or payload.get("unit") != "byte" or type(payload.get("bytes per unit")) is not int
            or payload["bytes per unit"] != 1):
        raise invalid
    rows = payload.get("processes")
    if (not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict)
            or type(rows[0].get("pid")) is not int or rows[0]["pid"] != process_id):
        raise invalid
    errors, warnings = payload.get("errors"), payload.get("warnings")
    if (not isinstance(errors, list) or not isinstance(warnings, list)
            or any(not isinstance(item, str) for item in errors + warnings)):
        raise invalid
    return rows[0]


def parse_macos_footprint_report(payload: Any, process_id: int) -> int:
    """Exact-PID byte measurement; only known kernel teardown is typed as exit.

    A ProcessLookupError is a probe observation, NOT proof of child exit. The
    supervisor must still reap its owned Popen child before accepting shutdown.
    Do not expose kernel diagnostics, process names or paths in compact reports.
    """
    row = _footprint_report_row(payload, process_id)
    errors, warnings = payload["errors"], payload["warnings"]
    value = row.get("footprint")
    if type(value) is int and value > 0 and not errors and not warnings:
        return value
    teardown_warnings = {
        "Unable to retrieve ledger entry info - No such process",
        "vm.get_owned_vmobjects - No such process",
    }
    if ("footprint" in row and value is None and warnings
            and set(warnings) <= teardown_warnings
            and set(errors) <= {"mach_vm_region_recurse - (os/kern) invalid argument"}):
        raise ProcessLookupError("physical-footprint target disappeared")
    raise ResourceSupervisorError("invalid physical-footprint report")


def parse_macos_footprint_peak(payload: Any, process_id: int) -> int | None:
    """The kernel's lifetime peak (``auxiliary.phys_footprint_peak``), when reported."""
    row = _footprint_report_row(payload, process_id)
    auxiliary = row.get("auxiliary")
    if not isinstance(auxiliary, dict):
        return None
    value = auxiliary.get("phys_footprint_peak")
    return value if type(value) is int and value > 0 else None


def macos_footprint_sampler(raw_root: Path) -> Callable[[int], FootprintSample]:
    """Retain every raw probe in a new operator-owned, untracked directory."""
    raw_root.mkdir(parents=True, exist_ok=False)
    index = 0

    def sample(process_id: int) -> FootprintSample:
        nonlocal index
        target = raw_root / f"footprint-{index:04d}.json"
        index += 1
        result = subprocess.run(
            ["/usr/bin/footprint", "-p", str(process_id), "--noCategories",
             "-f", "bytes", "-j", str(target)],
            capture_output=True, check=False, timeout=5,
            env={**os.environ, **PROBE_ENVIRONMENT_OVERRIDES},
        )
        if result.stderr:
            target.with_suffix(".stderr.log").write_bytes(result.stderr)
            raise ResourceSupervisorError("physical-footprint command diagnostics")
        # Even a failed tool can retain a typed kernel teardown report. Parse
        # that first; a valid measurement additionally needs successful exit.
        payload = json.loads(target.read_text())
        value = parse_macos_footprint_report(payload, process_id)
        if result.returncode != 0:
            raise ResourceSupervisorError("physical-footprint command failed")
        return FootprintSample(value, parse_macos_footprint_peak(payload, process_id))

    return sample


# --------------------------------------------------------------------------- #
# In-process probes (no subprocess per tick)
# --------------------------------------------------------------------------- #

_RUSAGE_INFO_V4 = 4
_RUSAGE_INFO_V4_FIELDS = (
    "ri_user_time", "ri_system_time", "ri_pkg_idle_wkups", "ri_interrupt_wkups",
    "ri_pageins", "ri_wired_size", "ri_resident_size", "ri_phys_footprint",
    "ri_proc_start_abstime", "ri_proc_exit_abstime", "ri_child_user_time",
    "ri_child_system_time", "ri_child_pkg_idle_wkups", "ri_child_interrupt_wkups",
    "ri_child_pageins", "ri_child_elapsed_abstime", "ri_diskio_bytesread",
    "ri_diskio_byteswritten", "ri_cpu_time_qos_default", "ri_cpu_time_qos_maintenance",
    "ri_cpu_time_qos_background", "ri_cpu_time_qos_utility", "ri_cpu_time_qos_legacy",
    "ri_cpu_time_qos_user_initiated", "ri_cpu_time_qos_user_interactive",
    "ri_billed_system_time", "ri_serviced_system_time", "ri_logical_writes",
    "ri_lifetime_max_phys_footprint", "ri_instructions", "ri_cycles", "ri_billed_energy",
    "ri_serviced_energy", "ri_interval_max_phys_footprint", "ri_runnable_time",
)


class _RusageInfoV4(ctypes.Structure):
    """``struct rusage_info_v4`` from <sys/resource.h>."""

    _fields_ = [("ri_uuid", ctypes.c_uint8 * 16)] + [
        (name, ctypes.c_uint64) for name in _RUSAGE_INFO_V4_FIELDS
    ]


class _XswUsage(ctypes.Structure):
    """``struct xsw_usage`` from <sys/sysctl.h> (``vm.swapusage``)."""

    _fields_ = [
        ("xsu_total", ctypes.c_uint64),
        ("xsu_avail", ctypes.c_uint64),
        ("xsu_used", ctypes.c_uint64),
        ("xsu_pagesize", ctypes.c_uint32),
        ("xsu_encrypted", ctypes.c_int32),
    ]


@functools.lru_cache(maxsize=1)
def _darwin_libraries() -> tuple[Any, Any] | None:
    if sys.platform != "darwin":
        return None
    try:
        libc = ctypes.CDLL("/usr/lib/libc.dylib", use_errno=True)
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    except OSError:
        return None
    libproc.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
    libproc.proc_pid_rusage.restype = ctypes.c_int
    libc.sysctlbyname.argtypes = [
        ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
        ctypes.c_void_p, ctypes.c_size_t,
    ]
    libc.sysctlbyname.restype = ctypes.c_int
    return libc, libproc


def _darwin_process_sample(process_id: int) -> ProcessSample:
    libraries = _darwin_libraries()
    if libraries is None:
        raise ResourceSupervisorError("in-process probe is unavailable")
    info = _RusageInfoV4()
    if libraries[1].proc_pid_rusage(process_id, _RUSAGE_INFO_V4, ctypes.byref(info)) != 0:
        code = ctypes.get_errno()
        if code == errno.ESRCH:
            raise ProcessLookupError("owned process disappeared")
        if code == errno.EPERM:
            raise PermissionError("owned process probe denied")
        raise ResourceSupervisorError("owned process probe failed")
    # An exited, unreaped child reads zero current footprint while its lifetime
    # peak survives: absence, never a zero-byte measurement.
    current = int(info.ri_phys_footprint) or None
    lifetime = int(info.ri_lifetime_max_phys_footprint) or None
    return ProcessSample(int(info.ri_resident_size), current, lifetime)


def _procfs_process_sample(process_id: int) -> ProcessSample:
    try:
        text = Path(f"/proc/{process_id}/status").read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ProcessLookupError("owned process disappeared") from None
    except PermissionError:
        raise PermissionError("owned process probe denied") from None
    except OSError:
        raise ResourceSupervisorError("owned process probe failed") from None
    match = re.search(r"^VmRSS:\s*([0-9]+)\s*kB\s*$", text, re.MULTILINE)
    if match is None:
        # A zombie has no resident set: the child has exited.
        raise ProcessLookupError("owned process has no resident set")
    return ProcessSample(int(match.group(1)) * 1024)


def owned_process_sample(process_id: int) -> ProcessSample:
    """One in-process sample of an owned child: resident, footprint, lifetime peak."""
    if type(process_id) is not int or process_id <= 0:
        raise ResourceSupervisorError("owned process identity is invalid")
    if sys.platform == "darwin":
        return _darwin_process_sample(process_id)
    return _procfs_process_sample(process_id)


def process_probe_identity(sampler: Callable[[int], ProcessSample]) -> str:
    if sampler is not owned_process_sample:
        return "injected"
    return "libproc-rusage-v4" if sys.platform == "darwin" else "procfs-status"


def _darwin_sysctl(name: str) -> int | None:
    """One locale-free host value (``vm.swapusage`` yields its used bytes)."""
    libraries = _darwin_libraries()
    if libraries is None:
        return None
    libc = libraries[0]
    if name == "vm.swapusage":
        value: Any = _XswUsage()
    elif name == "hw.memsize":
        value = ctypes.c_uint64(0)
    else:
        value = ctypes.c_int32(0)
    size = ctypes.c_size_t(ctypes.sizeof(value))
    if libc.sysctlbyname(name.encode("ascii"), ctypes.byref(value), ctypes.byref(size), None, 0) != 0:
        return None
    if size.value != ctypes.sizeof(value):
        return None
    return int(value.xsu_used) if name == "vm.swapusage" else int(value.value)


def _run_probe(command: Sequence[str]) -> str | None:
    try:
        result = subprocess.run(
            list(command), check=False, capture_output=True, text=True, timeout=5,
            env={**os.environ, **PROBE_ENVIRONMENT_OVERRIDES},
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (result.stdout + "\n" + result.stderr).strip()


_DECIMAL = r"([0-9]+(?:[.,][0-9]+)?)"


def parse_free_percent(text: str) -> float | None:
    """``memory_pressure -Q``'s free percentage, in any decimal convention."""
    match = re.search(r"System-wide memory free percentage:\s*" + _DECIMAL + r"\s*%", text)
    return float(match.group(1).replace(",", ".")) if match else None


def parse_swap_used_bytes(text: str) -> int | None:
    """``sysctl -n vm.swapusage``'s used bytes; a decimal comma (fr_CA) parses too."""
    match = re.search(r"used\s*=\s*" + _DECIMAL + r"\s*([KMGT])", text)
    if match is None:
        return None
    scale = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}[match.group(2)]
    return int(float(match.group(1).replace(",", ".")) * scale)


@dataclass(frozen=True)
class HostSnapshot:
    free_percent: float | None
    swap_used_bytes: int | None
    pressure_warning: bool | None
    # Attribution only (audit #102): the kernel's pressure level (1 normal,
    # 2 warn, 4 critical) and the physical memory the child's peak is set
    # against. Neither enters qualification.
    kernel_pressure_level: int | None = None
    physical_memory_bytes: int | None = None
    probe_failures: tuple[str, ...] = field(default_factory=tuple)

    def report(self) -> dict[str, Any]:
        return {
            "freeMemoryPercent": self.free_percent,
            "swapUsedBytes": self.swap_used_bytes,
            "pressureWarning": self.pressure_warning,
            "kernelPressureLevel": self.kernel_pressure_level,
            "physicalMemoryBytes": self.physical_memory_bytes,
            "probeFailures": list(self.probe_failures),
        }


def host_snapshot(
    *, read_sysctl: Callable[[str], int | None] = _darwin_sysctl,
    run_probe: Callable[[Sequence[str]], str | None] = _run_probe,
) -> HostSnapshot:
    """Host memory from ``sysctlbyname``; locale-independent text probes as fallback."""
    failures: list[str] = []
    level = read_sysctl("kern.memorystatus_level")
    free_percent = float(level) if level is not None and 0 <= level <= 100 else None
    if free_percent is None:
        text = run_probe(("/usr/bin/memory_pressure", "-Q"))
        if not text:
            failures.append("free-percent-unavailable")
        else:
            free_percent = parse_free_percent(text)
            if free_percent is None:
                failures.append("free-percent-unparsed")
    swap_used = read_sysctl("vm.swapusage")
    if swap_used is None:
        text = run_probe(("/usr/sbin/sysctl", "-n", "vm.swapusage"))
        if not text:
            failures.append("swap-usage-unavailable")
        else:
            swap_used = parse_swap_used_bytes(text)
            if swap_used is None:
                failures.append("swap-usage-unparsed")
    kernel_level = read_sysctl("kern.memorystatus_vm_pressure_level")
    if kernel_level is None:
        failures.append("kernel-pressure-level-unavailable")
    physical_memory = read_sysctl("hw.memsize")
    if physical_memory is None or physical_memory <= 0:
        physical_memory = None
        failures.append("physical-memory-unavailable")
    warning = None if free_percent is None else free_percent < PRESSURE_WARNING_FREE_PERCENT
    return HostSnapshot(free_percent, swap_used, warning, kernel_level, physical_memory, tuple(failures))


# --------------------------------------------------------------------------- #
# Owned-child lifecycle
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class SupervisedResult:
    report: dict[str, Any]
    stdout: bytes
    stderr: bytes


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _exited_unreaped(process: subprocess.Popen) -> bool | None:
    """True once the owned child exited but is not reaped (its kernel accounting is
    still readable), False while it runs, None when that cannot be observed without
    reaping it (already reaped, not a direct child, or no ``waitid``)."""
    if process.returncode is not None:
        return None
    try:
        observed = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except (AttributeError, ChildProcessError, OSError, TypeError):
        return None
    return observed is not None


def _still_running(process: subprocess.Popen) -> bool:
    state = _exited_unreaped(process)
    if state is None:
        return process.poll() is None
    return not state


def _reap_exited(process: subprocess.Popen) -> Any | None:
    """Reap an exited child with ``wait4`` so its ``ru_maxrss`` is kept."""
    try:
        reaped, status, usage = os.wait4(process.pid, os.WNOHANG)
    except (AttributeError, ChildProcessError, OSError, TypeError):
        return None
    if reaped == 0:
        return None
    process.returncode = os.waitstatus_to_exitcode(status)
    return usage


def _wait_owned(process: subprocess.Popen, timeout: float) -> Any | None:
    """Bounded wait for the owned child; returns its rusage when this reaped it."""
    deadline = time.monotonic() + timeout
    while True:
        state = _exited_unreaped(process)
        if state is None:
            process.wait(timeout=max(0.0, deadline - time.monotonic()))
            return None
        if state:
            usage = _reap_exited(process)
            if usage is None and process.returncode is None:
                process.wait(timeout=max(0.0, deadline - time.monotonic()))
            return usage
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(process.args, timeout)
        time.sleep(REAP_POLL_SECONDS)


def _max_rss_bytes(usage: Any | None) -> int | None:
    value = getattr(usage, "ru_maxrss", None)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return None
    # macOS reports bytes; Linux reports kibibytes.
    return value if sys.platform == "darwin" else value * 1024


def _terminate_owned_process(process: subprocess.Popen) -> tuple[list[str], Any | None]:
    """Bounded shutdown; a signal error never proves exit or discards evidence."""
    failures: list[str] = []
    if not _still_running(process):
        usage = _reap_exited(process) if _exited_unreaped(process) else None
        return failures, usage
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            # The child may have exited between poll and killpg; wait still
            # owns the authoritative exit status, not the signal result.
            pass
        except PermissionError:
            failures.append("process-group-signal-denied")
        except OSError:
            failures.append("process-group-signal-failed")
        try:
            usage = _wait_owned(process, SHUTDOWN_WAIT_SECONDS)
            return sorted(set(failures)), usage
        except subprocess.TimeoutExpired:
            continue
    if process.poll() is None:
        failures.append("process-exit-unconfirmed")
    return sorted(set(failures)), None


_MALFORMED = object()


def _footprint_values(observed: Any) -> tuple[Any, int | None]:
    """(current bytes | None | malformed, lifetime peak bytes | None)."""
    if observed is None:
        return None, None
    if isinstance(observed, ProcessSample):
        return observed.physical_footprint_bytes, observed.lifetime_max_physical_footprint_bytes
    if isinstance(observed, FootprintSample):
        current, lifetime = observed.current_bytes, observed.lifetime_peak_bytes
    else:
        current, lifetime = observed, None
    if type(current) is not int or current <= 0:
        return _MALFORMED, None
    if lifetime is not None and (type(lifetime) is not int or lifetime <= 0):
        lifetime = None
    return current, lifetime


def recovery_attribution(
    before: HostSnapshot, after: HostSnapshot, *, child_peak_bytes: int | None,
    child_peak_basis: str,
) -> dict[str, Any]:
    """Report-only evidence for who owns a post-exit free-memory drop (audit #102).

    The five-point recovery rule is unchanged. ``dropExceedsChildPeak`` says the
    host lost more free memory than the child's own peak could explain, the
    signature of a concurrent allocator rather than the child's unreleased or
    compressed pages.
    """
    physical = after.physical_memory_bytes or before.physical_memory_bytes
    drop = (
        round(before.free_percent - after.free_percent, 3)
        if before.free_percent is not None and after.free_percent is not None else None
    )
    share = (
        round(100.0 * child_peak_bytes / physical, 3)
        if child_peak_bytes and physical else None
    )
    if drop is None:
        status = "unattributed"
    elif drop <= RECOVERY_TOLERANCE_PERCENT_POINTS:
        status = "recovered"
    elif share is None:
        status = "unattributed"
    elif drop > share:
        status = "drop-exceeds-child-peak"
    else:
        status = "drop-within-child-peak"
    return {
        "freePercentDropPoints": drop,
        "physicalMemoryBytes": physical,
        "childPeakBytes": child_peak_bytes,
        "childPeakBasis": child_peak_basis,
        "childPeakPercentOfPhysicalMemory": share,
        "kernelPressureLevelBefore": before.kernel_pressure_level,
        "kernelPressureLevelAfter": after.kernel_pressure_level,
        "status": status,
        "ruleChanged": False,
    }


CANDIDATE_RECOVERY_RULE = "attributed-post-exit-recovery-v2"
# The kernel pressure level the timing lanes accept (`require_quiet_host`).
MAXIMUM_NORMAL_KERNEL_PRESSURE_LEVEL = 1


def candidate_recovery_verdict(
    before: HostSnapshot, after: HostSnapshot, attribution: dict[str, Any],
    *, exit_confirmed: bool,
) -> dict[str, Any]:
    """The recovery rule the audit recommends proposing after M6 evidence (#102).

    Report only: it never enters ``qualified``. Pressure is the kernel level
    the timing lanes judge (normal is 1) when both snapshots read it, else the
    binding free-percent warning. A post-exit drop beyond the five-point
    tolerance fails only when attribution leaves it to the child
    (``drop-within-child-peak``) or cannot attribute it; a drop larger than the
    child's own peak (``drop-exceeds-child-peak``) is another allocator's.
    """
    failures: list[str] = []
    if not exit_confirmed:
        failures.append("process-exit-unconfirmed")
    levels = (before.kernel_pressure_level, after.kernel_pressure_level)
    if all(isinstance(level, int) for level in levels):
        if any(level > MAXIMUM_NORMAL_KERNEL_PRESSURE_LEVEL for level in levels):
            failures.append("kernel-pressure-not-normal")
    elif before.pressure_warning is not False or after.pressure_warning is not False:
        failures.append("host-pressure-not-clean")
    status = attribution.get("status")
    if status == "drop-within-child-peak":
        failures.append("post-exit-recovery-attributed-to-child")
    elif status == "unattributed":
        failures.append("post-exit-recovery-unattributed")
    return {
        "algorithm": CANDIDATE_RECOVERY_RULE,
        "binding": False,
        "attribution": status,
        "qualified": not failures,
        "failures": failures,
    }


def recovery_report(envelopes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Binding against candidate recovery verdicts over saved envelopes (audit #102).

    Counts each envelope's binding recovery outcome (the five-point rule and the
    free-percent pressure warning), the candidate's, and the attribution, so a
    proposed rule change cites how many results it would flip and why.
    """
    rows = []
    for envelope in envelopes:
        failures = set(envelope.get("qualificationFailures") or [])
        binding_recovery = not failures & {
            "post-exit-memory-recovery-unqualified", "host-pressure-not-clean",
        }
        candidate = envelope.get("candidateRecoveryRule") or {}
        attribution = (envelope.get("recoveryAttribution") or {}).get("status")
        rows.append({
            "bindingRecoveryQualified": binding_recovery,
            "candidateQualified": candidate.get("qualified"),
            "attribution": attribution,
        })
    judged = [row for row in rows if row["candidateQualified"] is not None]
    by_attribution: dict[str, int] = {}
    for row in rows:
        key = str(row["attribution"])
        by_attribution[key] = by_attribution.get(key, 0) + 1
    return {
        "candidateRule": CANDIDATE_RECOVERY_RULE,
        "envelopes": len(rows),
        "withCandidateVerdict": len(judged),
        "bindingRecoveryFailures": sum(not row["bindingRecoveryQualified"] for row in rows),
        "candidateFailures": sum(row["candidateQualified"] is False for row in judged),
        "candidateWouldQualifyBindingFailure": sum(
            1 for row in judged if row["candidateQualified"] and not row["bindingRecoveryQualified"]
        ),
        "candidateWouldFailBindingPass": sum(
            1 for row in judged if not row["candidateQualified"] and row["bindingRecoveryQualified"]
        ),
        "attribution": dict(sorted(by_attribution.items())),
    }


def envelopes_in(value: Any) -> list[dict[str, Any]]:
    """Every resource envelope nested anywhere in a saved JSON document."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if value.get("kind") == "delivery-analyzer-resource-envelope":
            found.append(value)
        for item in value.values():
            found.extend(envelopes_in(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(envelopes_in(item))
    return found


def run_supervised(
    command: Sequence[str], *, lock_root: Path,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    maximum_rss_bytes: int = PROVISIONAL_MAXIMUM_RSS_BYTES,
    environment: dict[str, str] | None = None,
    snapshotter: Callable[[], HostSnapshot] = host_snapshot,
    rss_sampler: Callable[[int], int] | None = None,
    recovery_timeout_seconds: float = DEFAULT_RECOVERY_TIMEOUT_SECONDS,
    physical_footprint_sampler: Callable[[int], Any] | None = None,
    maximum_physical_footprint_bytes: int = PROVISIONAL_MAXIMUM_RSS_BYTES,
    measure_physical_footprint: bool = False,
    process_sampler: Callable[[int], ProcessSample] = owned_process_sample,
) -> SupervisedResult:
    """Run one governed child and qualify its resource envelope.

    Resident memory comes from ``process_sampler`` (in-process) unless an
    ``rss_sampler`` is injected. Physical footprint is measured when a
    ``physical_footprint_sampler`` is given or ``measure_physical_footprint`` is
    set (MLX callers, whose Metal memory RSS cannot see); the in-process probe then
    also supplies the kernel's lifetime peak.
    """
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
    footprint_requested = physical_footprint_sampler is not None or bool(measure_physical_footprint)
    footprint_from_process_probe = footprint_requested and physical_footprint_sampler is None
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
        sampled_peak_footprint = 0
        lifetime_peak_footprint = 0
        footprint_samples = 0
        resource_samples = 0
        maximum_sample_gap: float | None = None
        last_sample_at: float | None = None
        resource_limit_terminated = False
        resource_probe_failed = False
        probe_failures: list[dict[str, str]] = []
        terminal_probe_count = 0
        terminal_lifetime_read = False
        wait_usage: Any | None = None
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                list(command), stdout=stdout_file, stderr=stderr_file,
                env=environment, start_new_session=True,
                # Preserve exclusion if shutdown cannot reap the child or the
                # supervisor itself exits. Do not unlock this shared description
                # explicitly: the inherited descriptor lasts until child exit.
                pass_fds=(lock.fileno(),),
            )
            try:
                while True:
                    state = _exited_unreaped(process)
                    if state is None and process.poll() is not None:
                        break
                    if state:
                        # The exited child's lifetime peak is still readable until
                        # it is reaped: the exact high-water mark through exit.
                        if footprint_from_process_probe:
                            try:
                                _current, lifetime = _footprint_values(process_sampler(process.pid))
                                if lifetime is not None:
                                    lifetime_peak_footprint = max(lifetime_peak_footprint, lifetime)
                                    terminal_lifetime_read = True
                            except Exception:  # noqa: BLE001 - best effort after exit
                                pass
                        wait_usage = _reap_exited(process)
                        break
                    probe_stage = "rss"
                    try:
                        sample: ProcessSample | None = None
                        if rss_sampler is not None:
                            resident = rss_sampler(process.pid)
                        else:
                            probe_stage = "process"
                            sample = process_sampler(process.pid)
                            resident = sample.resident_bytes
                        if type(resident) is not int or resident < 0:
                            raise ResourceSupervisorError("invalid resident measurement")
                        peak_rss = max(peak_rss, resident)
                        if footprint_requested:
                            probe_stage = "physical-footprint"
                            if physical_footprint_sampler is not None:
                                observed = physical_footprint_sampler(process.pid)
                            else:
                                observed = sample if sample is not None else process_sampler(process.pid)
                            footprint, lifetime = _footprint_values(observed)
                            if lifetime is not None:
                                lifetime_peak_footprint = max(lifetime_peak_footprint, lifetime)
                            if footprint is None or footprint is _MALFORMED:
                                # A process may exit between the liveness check and
                                # the probe. Only absence, never malformed values,
                                # can be explained by independently observed exit.
                                resource_probe_failed = footprint is _MALFORMED or _still_running(process)
                                if resource_probe_failed:
                                    probe_failures.append({"stage": probe_stage, "reason": "missing-live-measurement"})
                            else:
                                footprint_samples += 1
                                sampled_peak_footprint = max(sampled_peak_footprint, footprint)
                        resource_samples += 1
                        now = time.monotonic()
                        if last_sample_at is not None:
                            gap = now - last_sample_at
                            maximum_sample_gap = gap if maximum_sample_gap is None else max(maximum_sample_gap, gap)
                        last_sample_at = now
                    except ProcessLookupError:
                        # The kernel may lose the task before waitpid observes
                        # exit. Only this typed observation permits a bounded
                        # reap before shutdown, never a retry of the workload.
                        try:
                            wait_usage = _wait_owned(process, PROBE_EXIT_WAIT_SECONDS) or wait_usage
                            terminal_probe_count += 1
                        except subprocess.TimeoutExpired:
                            resource_probe_failed = True
                            probe_failures.append({"stage": probe_stage, "reason": "target-exit-unconfirmed"})
                        except OSError:
                            resource_probe_failed = True
                            probe_failures.append({"stage": probe_stage, "reason": "target-exit-observation-failed"})
                    except PermissionError:
                        resource_probe_failed = True
                        probe_failures.append({"stage": probe_stage, "reason": "permission-denied"})
                    except Exception:
                        resource_probe_failed = True
                        probe_failures.append({"stage": probe_stage, "reason": "probe-exception"})
                    peak_footprint = max(sampled_peak_footprint, lifetime_peak_footprint)
                    resource_limit_terminated = (
                        peak_rss > maximum_rss_bytes
                        or peak_footprint > maximum_physical_footprint_bytes
                    )
                    timed_out = time.monotonic() - started > timeout_seconds
                    if timed_out or resource_limit_terminated or resource_probe_failed:
                        break
                    time.sleep(SAMPLE_INTERVAL_SECONDS)
            finally:
                shutdown_failures, shutdown_usage = _terminate_owned_process(process)
                wait_usage = shutdown_usage or wait_usage
            return_code = process.poll()
            exit_confirmed = return_code is not None
            stdout_file.seek(0)
            stderr_file.seek(0)
            stdout = stdout_file.read()
            stderr = stderr_file.read()
        wall_seconds = time.monotonic() - started
        # Snapshot only after the child has exited: a next layer may not start
        # while its predecessor still owns resident model pages.
        recovery_started = time.monotonic()
        after = snapshotter() if exit_confirmed else HostSnapshot(None, None, None)
        recovery_snapshot_count = int(exit_confirmed)
        while (
            before.free_percent is not None
            and after.free_percent is not None
            and after.free_percent < before.free_percent - RECOVERY_TOLERANCE_PERCENT_POINTS
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
            and after.free_percent >= before.free_percent - RECOVERY_TOLERANCE_PERCENT_POINTS
        )
        # Host probe failures are typed apart from the property they block, so a
        # locale or probe fault never reads as real pressure, swap or recovery.
        taken = (before, after) if exit_confirmed else (before,)
        host_failures = {failure for snapshot in taken for failure in snapshot.probe_failures}
        free_probe_failed = any(failure.startswith("free-percent-") for failure in host_failures)
        swap_probe_failed = any(failure.startswith("swap-usage-") for failure in host_failures)
        peak_footprint = max(sampled_peak_footprint, lifetime_peak_footprint)
        footprint_measured = footprint_samples > 0 or lifetime_peak_footprint > 0
        wait_max_rss = _max_rss_bytes(wait_usage)
        failures: list[str] = list(shutdown_failures)
        if timed_out:
            failures.append("timeout")
        if return_code is not None and return_code != 0:
            failures.append("nonzero-exit")
        if peak_rss <= 0:
            failures.append("peak-rss-unavailable")
        elif peak_rss > maximum_rss_bytes:
            failures.append("provisional-rss-ceiling-exceeded")
        if footprint_requested and footprint_samples == 0:
            failures.append("physical-footprint-unavailable")
        if peak_footprint > maximum_physical_footprint_bytes:
            failures.append("provisional-physical-footprint-ceiling-exceeded")
        if resource_probe_failed:
            failures.append("resource-probe-failed")
        if resource_limit_terminated:
            failures.append("resource-limit-termination")
        if before.pressure_warning is True or after.pressure_warning is True:
            failures.append("host-pressure-not-clean")
        elif not pressure_clean:
            failures.append("host-memory-probe-failed" if free_probe_failed else "host-pressure-not-clean")
        if swap_delta is not None and not swap_clean:
            failures.append("swap-recovery-unqualified")
        elif swap_delta is None:
            failures.append("host-swap-probe-failed" if swap_probe_failed else "swap-recovery-unqualified")
        if not memory_recovered:
            if before.free_percent is not None and after.free_percent is not None:
                failures.append("post-exit-memory-recovery-unqualified")
            elif free_probe_failed:
                failures.append("host-memory-probe-failed")
            else:
                failures.append("post-exit-memory-recovery-unqualified")
        failures = list(dict.fromkeys(failures))
        if footprint_measured:
            child_peak, child_basis = peak_footprint, "physical-footprint"
        else:
            child_peak = max(peak_rss, wait_max_rss or 0) or None
            child_basis = "resident"
        attribution = recovery_attribution(
            before, after, child_peak_bytes=child_peak, child_peak_basis=child_basis,
        )
        report = {
            "schemaVersion": SCHEMA_VERSION,
            "probeAlgorithmVersion": PROBE_ALGORITHM_VERSION,
            "kind": "delivery-analyzer-resource-envelope",
            "provisionalPolicy": True,
            "promotionAuthority": False,
            "timeoutSeconds": timeout_seconds,
            "timedOut": timed_out,
            "returnCode": return_code,
            "cleanExit": return_code == 0 and not (timed_out or resource_limit_terminated or resource_probe_failed or shutdown_failures),
            "processExitConfirmed": exit_confirmed,
            "outputCaptureComplete": exit_confirmed,
            "shutdownFailures": shutdown_failures,
            "probeFailures": probe_failures,
            "probeFailureCount": len(probe_failures),
            "terminalProbeCount": terminal_probe_count,
            "processProbe": "injected" if rss_sampler is not None else process_probe_identity(process_sampler),
            "sampleIntervalSeconds": SAMPLE_INTERVAL_SECONDS,
            "resourceSampleCount": resource_samples,
            "maximumSampleGapSeconds": maximum_sample_gap,
            "wallSeconds": wall_seconds,
            "peakRSSBytes": peak_rss,
            "waitMaxRSSBytes": wait_max_rss,
            "maximumAllowedRSSBytes": maximum_rss_bytes,
            "physicalFootprintMeasurementRequested": footprint_requested,
            "peakPhysicalFootprintBytes": peak_footprint if footprint_measured else None,
            "sampledPeakPhysicalFootprintBytes": sampled_peak_footprint if footprint_samples else None,
            "lifetimeMaxPhysicalFootprintBytes": lifetime_peak_footprint or None,
            "terminalLifetimePeakRead": terminal_lifetime_read,
            "physicalFootprintSampleCount": footprint_samples,
            "maximumAllowedPhysicalFootprintBytes": maximum_physical_footprint_bytes,
            "physicalFootprintCeilingEvaluated": footprint_measured,
            "resourceLimitTerminated": resource_limit_terminated,
            "hostBefore": before.report(),
            "hostAfter": after.report(),
            "swapDeltaBytes": swap_delta,
            "postExitMemoryRecovered": memory_recovered,
            "recoveryAttribution": attribution,
            "candidateRecoveryRule": candidate_recovery_verdict(
                before, after, attribution, exit_confirmed=exit_confirmed,
            ),
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


def main(argv: Sequence[str] | None = None) -> int:
    """``recovery-report FILE...``: binding against candidate recovery verdicts."""
    import argparse

    parser = argparse.ArgumentParser(description="Delivery analyzer resource supervisor tools")
    commands = parser.add_subparsers(dest="command", required=True)
    report_parser = commands.add_parser(
        "recovery-report",
        help="tabulate the binding and candidate post-exit recovery verdicts of saved envelopes",
    )
    report_parser.add_argument("paths", nargs="+", type=Path,
                               help="JSON evidence holding resource envelopes (e.g. independent-asr.json)")
    arguments = parser.parse_args(argv)
    envelopes: list[dict[str, Any]] = []
    for path in arguments.paths:
        try:
            envelopes.extend(envelopes_in(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, json.JSONDecodeError) as error:
            print(f"recovery-report: {path.name} is unreadable: {error}", file=sys.stderr)
            return 1
    print(json.dumps(recovery_report(envelopes), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
