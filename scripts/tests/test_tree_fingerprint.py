#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest


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

    def test_reediting_already_modified_file_changes_digest(self) -> None:
        (self.root / "tracked.txt").write_text("first edit\n", encoding="utf-8")
        first = self.fingerprint()
        (self.root / "tracked.txt").write_text("second edit\n", encoding="utf-8")
        self.assertNotEqual(first, self.fingerprint())

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


class BuildInputsFingerprintTests(TreeFingerprintTests):
    """audit #75: the UI build skip keys on build inputs, not the whole tree."""

    def commit(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        subprocess.run(["git", "-C", self.root, "add", relative], check=True)
        subprocess.run(["git", "-C", self.root, "commit", "-qm", relative], check=True)

    def build_inputs(self) -> str:
        return MODULE.build_inputs_fingerprint(self.root)

    def test_a_publication_or_roadmap_commit_keeps_the_identity(self) -> None:
        before = self.build_inputs()
        whole_tree = self.fingerprint()
        self.commit("benchmarks/runs/ui-generation/run.json", "{}\n")
        self.commit("benchmarks/HISTORY.md", "index\n")
        self.commit("docs/charts/chart.svg", "<svg/>\n")
        self.commit("website/src/page.jsx", "page\n")
        self.commit("config/roadmap.json", "{}\n")
        (self.root / "docs" / "notes.md").write_text("draft\n", encoding="utf-8")
        self.assertEqual(before, self.build_inputs())
        self.assertNotEqual(whole_tree, self.fingerprint())

    def test_any_build_input_change_moves_the_identity(self) -> None:
        before = self.build_inputs()
        (self.root / "tracked.txt").write_text("edited\n", encoding="utf-8")
        edited = self.build_inputs()
        self.assertNotEqual(before, edited)
        subprocess.run(["git", "-C", self.root, "commit", "-qam", "edit"], check=True)
        # Committing the same content keeps the identity: it binds content, not the commit.
        self.assertEqual(edited, self.build_inputs())
        (self.root / "Sources").mkdir()
        (self.root / "Sources" / "New.swift").write_text("let x = 1\n", encoding="utf-8")
        self.assertNotEqual(edited, self.build_inputs())
        self.commit("config/other-contract.json", "{}\n")
        self.assertNotEqual(edited, self.build_inputs())


if __name__ == "__main__":
    unittest.main()
