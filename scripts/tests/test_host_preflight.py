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


def run_preflight(
    *, load: str, cores: str, level: str, env: dict[str, str] | None = None,
    cwd: Path | None = None, command: str = "require_quiet_host fixture-lane",
) -> subprocess.CompletedProcess:
    """Run `require_quiet_host` (or `command`) against a fake `sysctl` answering the given values."""
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
        # Isolate from the real host lock and from this checkout's worktrees.
        environment.pop("QVOICE_NATIVE_LOCK", None)
        environment.pop("ROOT_DIR", None)
        environment.update(env or {})
        return subprocess.run(
            ["bash", "-c", f". '{LIB}'; {command}"],
            capture_output=True, text=True, env=environment, check=False,
            cwd=cwd or temporary,
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

    def test_a_live_native_lock_holder_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / "native-build.lock"
            lock.mkdir()
            holder = subprocess.Popen(["sleep", "30"])
            try:
                (lock / "pid").write_text(f"{holder.pid}\n")
                result = run_preflight(load="0.50", cores="8", level="1",
                                       env={"QVOICE_NATIVE_LOCK": str(lock)})
            finally:
                holder.kill()
                holder.wait()
            self.assertEqual(result.returncode, 1)
            self.assertIn(f"native-lock(pid {holder.pid})", result.stderr)
            # A dead holder's lock is stale and does not block.
            stale = run_preflight(load="0.50", cores="8", level="1",
                                  env={"QVOICE_NATIVE_LOCK": str(lock)})
            self.assertEqual(stale.returncode, 0, stale.stderr)

    def test_a_locked_agent_worktree_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
            subprocess.run([*git, "-C", str(repo), "commit", "-q", "--allow-empty", "-m", "i"], check=True)
            worktree = repo / ".claude" / "worktrees" / "agent"
            subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "-b", "worktree-agent",
                            str(worktree)], check=True)
            idle = run_preflight(load="0.50", cores="8", level="1", cwd=repo)
            self.assertEqual(idle.returncode, 0, idle.stderr)
            subprocess.run(["git", "-C", str(repo), "worktree", "lock", str(worktree)], check=True)
            busy = run_preflight(load="0.50", cores="8", level="1", cwd=repo)
            self.assertEqual(busy.returncode, 1)
            self.assertIn("active-agent-worktrees(1)", busy.stderr)
            allowed = run_preflight(load="0.50", cores="8", level="1", cwd=repo,
                                    env={"QVOICE_ALLOW_BUSY_HOST": "1"})
            self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_settle_hands_the_host_to_the_quiet_host_rule(self) -> None:
        """audit #28/V-8: after the lane's build, the bounded settle ends in the
        ordinary rule: within twice the core count continues, above it refuses."""
        for load, expected in (("3.20", 0), ("12.00", 0), ("17.00", 1)):
            with self.subTest(load=load):
                result = run_preflight(load=load, cores="8", level="1",
                                       command="settle_host_load fixture-lane 0")
                self.assertEqual(result.returncode, expected, result.stderr)
        pressured = run_preflight(load="0.50", cores="8", level="2",
                                  command="settle_host_load fixture-lane 0")
        self.assertEqual(pressured.returncode, 1)

    def test_lane_identifier_is_required(self) -> None:
        result = subprocess.run(
            ["bash", "-c", f". '{LIB}'; require_quiet_host"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
