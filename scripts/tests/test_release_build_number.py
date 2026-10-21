"""The release build-number check over real Git histories with v* tags.

Each test builds a throwaway repository whose commits change project.yml's
CURRENT_PROJECT_VERSION, tags some of them, and runs the shipped script against it.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "release_build_number.py"
SPEC = importlib.util.spec_from_file_location("release_build_number", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def project(version: str, build: str) -> str:
    return (
        "name: QwenVoice\nsettings:\n  base:\n"
        f'    MARKETING_VERSION: "{version}"\n    CURRENT_PROJECT_VERSION: "{build}"\n'
    )


class ReleaseBuildNumberTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.environment = {
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "HOME": str(self.repo), "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        }
        self.git("init", "-q", "-b", "main")

    def git(self, *arguments: str) -> str:
        return subprocess.run(["git", *arguments], cwd=self.repo, env=self.environment, capture_output=True,
                              text=True, check=True).stdout.strip()

    def release(self, version: str, build: str, *tags: str) -> None:
        (self.repo / "project.yml").write_text(project(version, build), encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", f"{version} ({build})")
        for tag in tags:
            self.git("tag", tag)

    def check(self, tag: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(SCRIPT), "check", "--tag", tag, "--root", str(self.repo)],
                              env=self.environment, capture_output=True, text=True, timeout=60, check=False)

    def test_a_greater_build_than_the_previous_tag_passes(self) -> None:
        self.release("2.3.0", "22", "v2.3.0")
        self.release("2.4.0", "23", "v2.4.0")
        self.release("3.0.0", "24")
        completed = self.check("v3.0.0")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("v3.0.0 build 24 is greater than v2.4.0's build 23", completed.stdout)

    def test_an_equal_or_lower_build_fails(self) -> None:
        self.release("2.4.0", "23", "v2.4.0")
        for build in ("23", "22", "9"):
            with self.subTest(build=build):
                self.release("3.0.0", build)
                completed = self.check("v3.0.0")
                self.assertEqual(completed.returncode, 1)
                self.assertIn(f"declares build {build}, which is not greater than v2.4.0's build 23", completed.stderr)

    def test_build_numbers_compare_as_numbers(self) -> None:
        self.release("2.4.0", "9", "v2.4.0")
        self.release("3.0.0", "10")
        self.assertEqual(self.check("v3.0.0").returncode, 0)
        self.git("tag", "v3.0.0")
        self.release("3.0.1", "10.0.1")
        self.assertEqual(self.check("v3.0.1").returncode, 0)
        self.release("3.0.1", "10.0")
        self.assertIn("not greater than v3.0.0's build 10", self.check("v3.0.1").stderr)

    def test_the_previous_tag_is_chosen_by_version_not_by_name_or_date(self) -> None:
        # Tagged out of order: the 2.0.0 prerelease after 2.0.0, a 1.x patch last.
        self.release("2.0.0", "16", "v2.0.0")
        self.release("2.0.0", "15", "v2.0.0-beta.1")
        self.release("1.2.3", "40", "v1.2.3")
        self.release("2.1.0", "17")
        completed = self.check("v2.1.0")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("than v2.0.0's build 16", completed.stdout)

    def test_a_release_follows_its_own_prerelease(self) -> None:
        self.release("3.0.0", "24", "v3.0.0-rc.1")
        self.release("3.0.0", "24")
        completed = self.check("v3.0.0")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("not greater than v3.0.0-rc.1's build 24", completed.stderr)

    def test_the_tag_being_built_is_not_its_own_predecessor(self) -> None:
        self.release("2.4.0", "23", "v2.4.0")
        self.release("3.0.0", "24", "v3.0.0")
        completed = self.check("v3.0.0")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("than v2.4.0's", completed.stdout)

    def test_the_first_release_has_nothing_to_compare(self) -> None:
        self.release("1.0.0", "1", "not-a-version", "release-1")
        completed = self.check("v1.0.0")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("no v* tag precedes v1.0.0", completed.stdout)

    def test_an_unreadable_previous_project_fails_closed(self) -> None:
        (self.repo / "README.md").write_text("before project.yml\n", encoding="utf-8")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "old")
        self.git("tag", "v0.9.0")
        self.release("1.0.0", "1")
        completed = self.check("v1.0.0")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("cannot read project.yml at the previous release tag v0.9.0", completed.stderr)

    def test_a_malformed_tag_or_build_fails(self) -> None:
        self.release("2.4.0", "23", "v2.4.0")
        self.release("3.0.0", "24b")
        self.assertIn("is not one to three period-separated integers", self.check("v3.0.0").stderr)
        self.release("3.0.0", "24")
        for malformed in ("3.0.0", "v3", "release-3.0.0"):
            with self.subTest(tag=malformed):
                completed = self.check(malformed)
                self.assertEqual(completed.returncode, 1)
                self.assertIn("is not a vMAJOR.MINOR[.PATCH][-PRERELEASE] tag", completed.stderr)

    def test_version_precedence(self) -> None:
        ordered = ["v1.0.0-alpha", "v1.0.0-alpha.1", "v1.0.0-alpha.beta", "v1.0.0-beta", "v1.0.0-beta.2",
                   "v1.0.0-beta.11", "v1.0.0-rc.1", "v1.0.0", "v1.2", "v1.2.1", "v1.10.0", "v2.0.0"]
        keys = [module.tag_key(tag) for tag in ordered]
        self.assertEqual(keys, sorted(keys))
        self.assertEqual(len(set(keys)), len(keys))
        self.assertEqual(module.tag_key("v1.2"), module.tag_key("v1.2.0+build.5"))
        self.assertIsNone(module.tag_key("v1"))
        self.assertEqual(module.previous_tag(ordered, "v1.2.0"), "v1.0.0")


if __name__ == "__main__":
    unittest.main()
