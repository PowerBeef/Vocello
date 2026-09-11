#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "tree_fingerprint", ROOT / "scripts/tree_fingerprint.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TreeFingerprintTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", self.root], check=True)
        subprocess.run(
            ["git", "-C", self.root, "config", "user.email", "fixture@example.invalid"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", self.root, "config", "user.name", "Fixture"], check=True
        )
        (self.root / "tracked.txt").write_text("baseline\n", encoding="utf-8")
        subprocess.run(["git", "-C", self.root, "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "fixture"], check=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def fingerprint(self) -> str:
        return MODULE.worktree_fingerprint(self.root)

    def test_identical_tree_is_stable(self) -> None:
        self.assertEqual(self.fingerprint(), self.fingerprint())

    def test_local_receipt_binds_tools_environment_and_tree_without_changing_release_digest(self):
        tree = self.fingerprint()
        with mock.patch.object(MODULE.shutil, "which", return_value=None):
            initial = MODULE.checkpoint_fingerprint(self.root)
            self.assertTrue(initial.startswith("local-v3:"))
            with mock.patch.dict(MODULE.os.environ, {"QWENVOICE_ENABLE_TSAN": "1"}):
                self.assertNotEqual(initial, MODULE.checkpoint_fingerprint(self.root))
            (self.root / "tracked.txt").write_text("changed\n")
            self.assertNotEqual(initial, MODULE.checkpoint_fingerprint(self.root))
        self.assertNotEqual(tree, self.fingerprint())

    def test_reediting_already_modified_file_changes_digest(self) -> None:
        (self.root / "tracked.txt").write_text("first edit\n", encoding="utf-8")
        first = self.fingerprint()
        (self.root / "tracked.txt").write_text("second edit\n", encoding="utf-8")
        self.assertNotEqual(first, self.fingerprint())

    def test_local_receipt_binds_resolved_tools_not_path_membership_or_order(self):
        first_tool = self.root / "tool-a"
        second_tool = self.root / "tool-b"
        first_tool.write_text("first executable\n")
        second_tool.write_text("second executable\n")
        with mock.patch.object(MODULE, "worktree_fingerprint", return_value="unchanged"), \
                mock.patch.object(MODULE, "_git_command_output", return_value="fixed toolchain"), \
                mock.patch.object(MODULE.shutil, "which", return_value=str(first_tool)) as which:
            with mock.patch.dict(MODULE.os.environ, {"PATH": "/fixture/a:/fixture/b"}):
                initial = MODULE.checkpoint_fingerprint(self.root)
            with mock.patch.dict(MODULE.os.environ, {"PATH": "/fixture/b:/fixture/a"}):
                self.assertEqual(initial, MODULE.checkpoint_fingerprint(self.root))
                which.return_value = str(second_tool)
                self.assertNotEqual(initial, MODULE.checkpoint_fingerprint(self.root))
                which.return_value = str(first_tool)
            # A hook or login shell that sees extra PATH directories but resolves the
            # same tools must reuse the receipt; a different resolved tool must not.
            with mock.patch.dict(MODULE.os.environ, {"PATH": "/fixture/a:/fixture/b:/fixture/c"}):
                self.assertEqual(initial, MODULE.checkpoint_fingerprint(self.root))
                which.return_value = str(second_tool)
                self.assertNotEqual(initial, MODULE.checkpoint_fingerprint(self.root))

    def test_staging_does_not_change_content_identity(self) -> None:
        (self.root / "tracked.txt").write_text("edit\n", encoding="utf-8")
        unstaged = self.fingerprint()
        subprocess.run(["git", "-C", self.root, "add", "tracked.txt"], check=True)
        self.assertEqual(unstaged, self.fingerprint())

    def test_untracked_path_and_bytes_are_bound(self) -> None:
        candidate = self.root / "new.txt"
        candidate.write_text("one\n", encoding="utf-8")
        first = self.fingerprint()
        candidate.write_text("two\n", encoding="utf-8")
        second = self.fingerprint()
        candidate.rename(self.root / "renamed.txt")
        third = self.fingerprint()
        self.assertNotEqual(first, second)
        self.assertNotEqual(second, third)

    def test_ignored_files_do_not_change_digest(self) -> None:
        (self.root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        subprocess.run(["git", "-C", self.root, "add", ".gitignore"], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", "ignore"], check=True)
        before = self.fingerprint()
        (self.root / "ignored.txt").write_text("local cache\n", encoding="utf-8")
        self.assertEqual(before, self.fingerprint())


if __name__ == "__main__":
    unittest.main()
