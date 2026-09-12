#!/usr/bin/env python3
"""The host-quiet preflight refuses loaded or memory-pressured hosts before a lane starts."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "scripts/lib/host_preflight.sh"


def run_preflight(*, load: str, cores: str, level: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Run `require_quiet_host` against a fake `sysctl` that answers with the given values."""
    with tempfile.TemporaryDirectory() as temporary:
        shim = Path(temporary) / "sysctl"
        shim.write_text(
            "#!/bin/sh\n"
            "case \"$2\" in\n"
            f"  vm.loadavg) echo '{{ {load} 1.00 1.00 }}' ;;\n"
            f"  hw.ncpu) echo '{cores}' ;;\n"
            f"  kern.memorystatus_vm_pressure_level) echo '{level}' ;;\n"
            "  *) exit 1 ;;\n"
            "esac\n"
        )
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        environment = dict(os.environ)
        environment["PATH"] = f"{temporary}:{environment['PATH']}"
        environment.pop("QVOICE_ALLOW_BUSY_HOST", None)
        environment.update(env or {})
        return subprocess.run(
            ["bash", "-c", f". '{LIB}'; require_quiet_host fixture-lane"],
            capture_output=True, text=True, env=environment, check=False,
        )


class HostPreflightTests(unittest.TestCase):
    def test_quiet_host_passes_and_prints_its_numbers(self) -> None:
        result = run_preflight(load="3.20", cores="8", level="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("load1m=3.20", result.stderr)
        self.assertIn("memoryPressureLevel=1", result.stderr)

    def test_load_above_twice_the_cores_refuses(self) -> None:
        result = run_preflight(load="16.50", cores="8", level="1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("needs a quiet host", result.stderr)
        self.assertIn("limit 16", result.stderr)
        at_limit = run_preflight(load="16.00", cores="8", level="1")
        self.assertEqual(at_limit.returncode, 0, at_limit.stderr)

    def test_memory_pressure_warning_refuses_even_when_idle(self) -> None:
        result = run_preflight(load="0.50", cores="8", level="2")
        self.assertEqual(result.returncode, 1)
        self.assertIn("memoryPressureLevel=2", result.stderr)

    def test_explicit_override_continues_and_says_so(self) -> None:
        result = run_preflight(load="20.00", cores="8", level="4", env={"QVOICE_ALLOW_BUSY_HOST": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("busy host by request", result.stderr)

    def test_lane_identifier_is_required(self) -> None:
        result = subprocess.run(
            ["bash", "-c", f". '{LIB}'; require_quiet_host"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
