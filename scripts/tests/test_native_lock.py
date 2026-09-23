#!/usr/bin/env python3
"""The host-wide native lock serializes Xcode/SwiftPM work across checkouts."""
from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD_CACHE = ROOT / "scripts" / "lib" / "build_cache.sh"


class NativeLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.lock = self.base / "host cache" / "native-build.lock"
        self.holders: list[subprocess.Popen[str]] = []

    def tearDown(self) -> None:
        for holder in self.holders:
            holder.kill()
            holder.wait()

    def environment(self, **extra: str) -> dict[str, str]:
        environment = os.environ.copy()
        # Pre-set build paths so sourcing build_cache.sh never loads the real
        # policy or touches the repository build tree.
        environment.update({
            "QVOICE_BUILD_ROOT": str(self.base / "build"),
            "QVOICE_XCODE_SOURCE_PACKAGES": str(self.base / "build" / "source-packages"),
            "QVOICE_NATIVE_LOCK": str(self.lock),
            "QVOICE_NATIVE_LOCK_WAIT_SECONDS": "2",
        })
        environment.update(extra)
        return environment

    def bash(self, body: str, checkout: Path | None = None, **extra: str) -> subprocess.CompletedProcess[str]:
        script = f"ROOT_DIR={shlex.quote(str(checkout or ROOT))}\n. {shlex.quote(str(BUILD_CACHE))}\n{body}"
        return subprocess.run(
            ["bash", "-c", script], text=True, capture_output=True,
            env=self.environment(**extra), timeout=30, check=False,
        )

    def hold_lock(self, **extra: str) -> subprocess.Popen[str]:
        script = (
            f"ROOT_DIR={shlex.quote(str(self.base / 'other-worktree'))}\n"
            f". {shlex.quote(str(BUILD_CACHE))}\n"
            "acquire_native_lock holder-test || exit 1\necho ready\nsleep 30\n"
        )
        holder = subprocess.Popen(
            ["bash", "-c", script], text=True, stdout=subprocess.PIPE,
            env=self.environment(**extra),
        )
        self.holders.append(holder)
        assert holder.stdout is not None
        self.assertEqual(holder.stdout.readline().strip(), "ready")
        return holder

    def test_acquire_records_owner_and_release_removes_the_lock(self) -> None:
        result = self.bash(
            "acquire_native_lock test-label || exit 1\n"
            'cat "$QVOICE_NATIVE_LOCK/pid" "$QVOICE_NATIVE_LOCK/label" "$QVOICE_NATIVE_LOCK/checkout"\n'
            'test -s "$QVOICE_NATIVE_LOCK/started" || exit 3\n'
            "release_native_lock\n"
            'test ! -e "$QVOICE_NATIVE_LOCK" || exit 4\n'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        pid, label, checkout = result.stdout.split("\n")[:3]
        self.assertRegex(pid, r"^[1-9][0-9]*$")
        self.assertEqual(label, "test-label")
        self.assertEqual(checkout, str(ROOT))

    def test_a_live_holder_in_another_checkout_blocks_until_timeout(self) -> None:
        holder = self.hold_lock()
        started = time.monotonic()
        result = self.bash("acquire_native_lock waiter")
        self.assertEqual(result.returncode, 1)
        self.assertGreaterEqual(time.monotonic() - started, 1.5)
        self.assertIn(f"held by pid {holder.pid} (holder-test, other-worktree)", result.stderr)
        self.assertIn("timed out", result.stderr)
        # The holder's lock is untouched.
        self.assertEqual((self.lock / "pid").read_text().strip(), str(holder.pid))

    def test_lock_path_does_not_depend_on_the_checkout(self) -> None:
        self.hold_lock()
        result = self.bash("acquire_native_lock waiter", checkout=self.base / "third-clone")
        self.assertEqual(result.returncode, 1)
        self.assertIn("held by pid", result.stderr)

    def test_a_dead_owner_is_reclaimed(self) -> None:
        dead = subprocess.Popen(["true"])
        dead.wait()
        self.lock.mkdir(parents=True)
        (self.lock / "pid").write_text(f"{dead.pid}\n")
        result = self.bash("acquire_native_lock reclaim && cat \"$QVOICE_NATIVE_LOCK/label\"")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "reclaim")

    def test_a_recycled_pid_with_a_different_start_time_is_reclaimed(self) -> None:
        self.lock.mkdir(parents=True)
        (self.lock / "pid").write_text(f"{os.getpid()}\n")
        (self.lock / "started").write_text("Mon Jan  1 00:00:00 2001\n")
        result = self.bash("acquire_native_lock recycled && cat \"$QVOICE_NATIVE_LOCK/label\"")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "recycled")

    def test_liveness_does_not_depend_on_the_waiters_locale_or_time_zone(self) -> None:
        holder = self.hold_lock(LANG="fr_CA.UTF-8", LC_ALL="fr_CA.UTF-8", TZ="Asia/Tokyo")
        result = self.bash("acquire_native_lock waiter", LC_ALL="C", TZ="UTC")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual((self.lock / "pid").read_text().strip(), str(holder.pid))

    def test_an_uncreatable_lock_fails_fast_instead_of_spinning(self) -> None:
        blocker = self.base / "not-a-directory"
        blocker.write_text("file")
        started = time.monotonic()
        result = self.bash("acquire_native_lock blocked", QVOICE_NATIVE_LOCK=str(blocker / "native.lock"),
                           QVOICE_NATIVE_LOCK_WAIT_SECONDS="30")
        self.assertEqual(result.returncode, 1)
        self.assertLess(time.monotonic() - started, 10)
        self.assertIn("cannot create", result.stderr)

    def test_an_ownerless_lock_is_reclaimed_only_once_it_is_old(self) -> None:
        self.lock.mkdir(parents=True)
        young = self.bash("acquire_native_lock waiter")
        self.assertEqual(young.returncode, 1, "a lock being created must not be stolen")
        old = time.time() - 120
        os.utime(self.lock, (old, old))
        result = self.bash("acquire_native_lock reclaim && cat \"$QVOICE_NATIVE_LOCK/label\"")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "reclaim")

    def test_nested_acquire_is_refused(self) -> None:
        result = self.bash("acquire_native_lock outer || exit 9\nacquire_native_lock inner")
        self.assertEqual(result.returncode, 1)
        self.assertIn("nested native lock", result.stderr)


if __name__ == "__main__":
    unittest.main()
