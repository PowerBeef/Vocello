"""The public release tag script refuses before writing or deleting anything; never touches Git or the network."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import release_source_authority  # noqa: E402
import release_tag as cut  # noqa: E402

COMMIT = "a" * 40
OLD_COMMIT = "1" * 40
OLD_TAG_OBJ = "2" * 40
VERIFIED = {"verified": True, "reason": "valid"}
VALID_NOTES = (
    "# Vocello 3.2.0\n\n"
    "## What's New\n\n"
    + ("Substantive release notes describing real changes across the Mac app, CLI, and iOS engine. " * 25)
    + "\n\n## Requirements\n\nApple Silicon macOS 26.\n\n"
    "## Install\n\nDownload from https://github.com/PowerBeef/Vocello/releases/tag/v3.2.0.\n\n"
    "## TestFlight What-to-Test\n\nVerify local synthesis across all three modes.\n"
)


def ci(conclusion: str = "success") -> dict[str, str]:
    """`gh api` responses for one push run on main whose `CI required` check ended with `conclusion`."""
    runs = [{"total_count": 1, "workflow_runs": [{
        "id": 7, "event": "push", "head_branch": "main", "head_sha": COMMIT,
        "path": release_source_authority.CI_WORKFLOW_PATH, "check_suite_id": 9}]}]
    checks = [{"total_count": 1, "check_runs": [{
        "id": 5, "name": "CI required", "head_sha": COMMIT, "status": "completed", "conclusion": conclusion,
        "completed_at": "2026-11-26T20:00:00Z", "app": {"slug": "github-actions"}, "check_suite": {"id": 9}}]}]
    return {"check-runs": json.dumps(checks), "actions/runs": json.dumps(runs)}


class FakeCommands:
    """Answers each command by its leading words; records every call."""

    def __init__(self, **overrides: str | Exception) -> None:
        self.calls: list[list[str]] = []
        self.answers: dict[str, str | Exception] = {
            "git symbolic-ref": "main\n",
            "git status": "",
            "git fetch": "",
            "git rev-parse HEAD": COMMIT + "\n",
            "git rev-parse refs/remotes/origin/main": COMMIT + "\n",
            "git remote get-url origin": "https://github.com/PowerBeef/Vocello.git\n",
            f"git show {COMMIT}:{cut.PROJECT_SPEC}": "project spec\n",
            f"git show {COMMIT}:docs/releases/v3.2.0.md": VALID_NOTES,
            "git config --get gpg.format": "ssh\n",
            "git config --get user.signingkey": __file__ + "\n",
            "git config --get gpg.ssh.allowedSignersFile": __file__ + "\n",
            "git tag --list": "",
            "git ls-remote": "",
            "git tag -d": "",
            "git tag -s": "",
            "git tag -v": "",
            "git cat-file": "tag\n",
            "git rev-parse refs/tags/v3.2.0^{commit}": COMMIT + "\n",
            "git push --no-follow-tags origin :refs/tags/v3.2.0": "",
            "git push --no-follow-tags origin refs/tags/v3.2.0:refs/tags/v3.2.0": "",
            "gh api --paginate --slurp -H Accept: application/vnd.github+json repos/PowerBeef/Vocello/releases":
                json.dumps([[{"tag_name": "v3.1.0", "draft": False}]]),
            "gh api repos/PowerBeef/Vocello/git/ref": json.dumps({"object": {"sha": "c" * 40}}),
            "gh api repos/PowerBeef/Vocello/git/tags": json.dumps({"verification": VERIFIED}),
            **ci(),
        }
        self.answers.update(overrides)

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        command = " ".join(argv)
        for key in sorted(self.answers, key=len, reverse=True):
            if command.startswith(key) or (key in ("check-runs", "actions/runs") and key in command):
                answer = self.answers[key]
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise AssertionError(f"unexpected command: {command}")

    def wrote(self) -> list[str]:
        return [
            " ".join(call[:3])
            for call in self.calls
            if call[:3] in (["git", "tag", "-s"], ["git", "tag", "-d"], ["git", "push", "--no-follow-tags"])
        ]


class ReleaseTagTests(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(patch.object(cut, "project_version_from_text", return_value=("3.2.0", "32")).start().stop)
        self.addCleanup(patch.object(cut, "check_build_number", return_value="v3.2.0 build 32 > 31").start().stop)

    def cut_with(self, fake: FakeCommands, *argv: str) -> int:
        with patch.object(cut, "run", fake), patch.object(cut.time, "sleep"), \
             patch.object(cut.subprocess, "run") as rollback:
            status = cut.main(list(argv))
        self.rollbacks = [call.args[0] for call in rollback.call_args_list]
        return status

    def test_fresh_tag_signs_verifies_and_pushes_exactly_one_ref(self) -> None:
        fake = FakeCommands()
        self.assertEqual(self.cut_with(fake), 0)
        sign_cmd = ["git", "tag", "-s", "-m", "Vocello 3.2.0 (build 32)", "v3.2.0", COMMIT]
        verify_cmd = ["git", "tag", "-v", "v3.2.0"]
        push_cmd = ["git", "push", "--no-follow-tags", "origin", "refs/tags/v3.2.0:refs/tags/v3.2.0"]
        self.assertIn(sign_cmd, fake.calls)
        self.assertIn(verify_cmd, fake.calls)
        pushes = [call for call in fake.calls if call[:2] == ["git", "push"]]
        self.assertEqual(pushes, [push_cmd])
        self.assertLess(fake.calls.index(sign_cmd), fake.calls.index(verify_cmd))
        self.assertLess(fake.calls.index(verify_cmd), fake.calls.index(push_cmd))

    def test_dry_run_checks_everything_and_writes_nothing(self) -> None:
        fake = FakeCommands(
            **{
                "git tag --list": OLD_TAG_OBJ + "\n",
                "git ls-remote": f"{OLD_TAG_OBJ}\trefs/tags/v3.2.0\n{OLD_COMMIT}\trefs/tags/v3.2.0^{{}}\n",
            }
        )
        self.assertEqual(self.cut_with(fake, "--dry-run", "--replace-unpublished"), 0)
        self.assertEqual(fake.wrote(), [])
        self.assertTrue(any("releases?per_page=100" in " ".join(c) for c in fake.calls))

    def test_replace_unpublished_verifies_local_tag_before_deleting_remote_and_pushing(self) -> None:
        fake = FakeCommands(
            **{
                "git tag --list": OLD_TAG_OBJ + "\n",
                "git ls-remote": f"{OLD_TAG_OBJ}\trefs/tags/v3.2.0\n{OLD_COMMIT}\trefs/tags/v3.2.0^{{}}\n",
            }
        )
        self.assertEqual(self.cut_with(fake, "--replace-unpublished"), 0)
        del_local = ["git", "tag", "-d", "v3.2.0"]
        sign_cmd = ["git", "tag", "-s", "-m", "Vocello 3.2.0 (build 32)", "v3.2.0", COMMIT]
        verify_cmd = ["git", "tag", "-v", "v3.2.0"]
        del_remote = ["git", "push", "--no-follow-tags", "origin", ":refs/tags/v3.2.0"]
        push_new = ["git", "push", "--no-follow-tags", "origin", "refs/tags/v3.2.0:refs/tags/v3.2.0"]
        self.assertEqual([c for c in fake.calls if c[:2] == ["git", "push"]], [del_remote, push_new])
        self.assertLess(fake.calls.index(del_local), fake.calls.index(sign_cmd))
        self.assertLess(fake.calls.index(sign_cmd), fake.calls.index(verify_cmd))
        self.assertLess(fake.calls.index(verify_cmd), fake.calls.index(del_remote))
        self.assertLess(fake.calls.index(del_remote), fake.calls.index(push_new))

    def test_every_precondition_refuses_before_anything_is_written(self) -> None:
        existing_remote = f"{OLD_TAG_OBJ}\trefs/tags/v3.2.0\n{OLD_COMMIT}\trefs/tags/v3.2.0^{{}}\n"
        for label, argv, overrides in (
            ("another branch", (), {"git symbolic-ref": "feature\n"}),
            ("dirty tree", (), {"git status": " M Sources/a.swift\n"}),
            ("unpushed commit", (), {"git rev-parse refs/remotes/origin/main": "d" * 40 + "\n"}),
            ("origin elsewhere", (), {"git remote get-url origin": "https://gitlab.com/PowerBeef/Vocello.git\n"}),
            ("failed CI", (), ci("failure")),
            ("no CI", (), {"check-runs": json.dumps([{"total_count": 0, "check_runs": []}])}),
            ("missing release notes", (), {f"git show {COMMIT}:docs/releases/v3.2.0.md": cut.Refusal("missing")}),
            ("invalid release notes", (), {f"git show {COMMIT}:docs/releases/v3.2.0.md": "# tiny TBD\n"}),
            ("gpg signing", (), {"git config --get gpg.format": "openpgp\n"}),
            ("missing signers", (), {"git config --get gpg.ssh.allowedSignersFile": "/nonexistent/signers\n"}),
            ("existing local tag without flag", (), {"git tag --list": OLD_TAG_OBJ + "\n"}),
            ("existing remote tag without flag", (), {"git ls-remote": existing_remote}),
            (
                "remote already at HEAD",
                ("--replace-unpublished",),
                {"git ls-remote": f"{OLD_TAG_OBJ}\trefs/tags/v3.2.0\n{COMMIT}\trefs/tags/v3.2.0^{{}}\n"},
            ),
            (
                "draft release exists",
                ("--replace-unpublished",),
                {
                    "git ls-remote": existing_remote,
                    "gh api --paginate --slurp -H Accept: application/vnd.github+json repos/PowerBeef/Vocello/releases":
                        json.dumps([[{"tag_name": "v3.2.0", "draft": True}]]),
                },
            ),
            (
                "published release exists",
                ("--replace-unpublished",),
                {
                    "git ls-remote": existing_remote,
                    "gh api --paginate --slurp -H Accept: application/vnd.github+json repos/PowerBeef/Vocello/releases":
                        json.dumps([[{"tag_name": "v3.2.0", "draft": False}]]),
                },
            ),
            (
                "releases API failed",
                ("--replace-unpublished",),
                {
                    "git ls-remote": existing_remote,
                    "gh api --paginate --slurp -H Accept: application/vnd.github+json repos/PowerBeef/Vocello/releases":
                        cut.Refusal("HTTP 500"),
                },
            ),
        ):
            with self.subTest(label):
                fake = FakeCommands(**overrides)
                self.assertEqual(self.cut_with(fake, *argv), 1)
                self.assertEqual(fake.wrote(), [])

    def test_build_number_failure_refuses_before_writing(self) -> None:
        with patch.object(cut, "check_build_number", side_effect=ValueError("build not greater")):
            fake = FakeCommands()
            self.assertEqual(self.cut_with(fake), 1)
            self.assertEqual(fake.wrote(), [])

    def test_failed_verify_restores_replaced_local_tag_without_touching_origin(self) -> None:
        fake = FakeCommands(
            **{
                "git tag --list": OLD_TAG_OBJ + "\n",
                "git ls-remote": f"{OLD_TAG_OBJ}\trefs/tags/v3.2.0\n{OLD_COMMIT}\trefs/tags/v3.2.0^{{}}\n",
                "git tag -v": cut.Refusal("bad signature"),
            }
        )
        self.assertEqual(self.cut_with(fake, "--replace-unpublished"), 1)
        self.assertEqual([c for c in fake.calls if c[:2] == ["git", "push"]], [])
        self.assertEqual(
            self.rollbacks,
            [["git", "tag", "-d", "v3.2.0"], ["git", "update-ref", "refs/tags/v3.2.0", OLD_TAG_OBJ]],
        )

    def test_failure_after_remote_delete_reports_partial_remote_mutation(self) -> None:
        fake = FakeCommands(
            **{
                "git tag --list": OLD_TAG_OBJ + "\n",
                "git ls-remote": f"{OLD_TAG_OBJ}\trefs/tags/v3.2.0\n{OLD_COMMIT}\trefs/tags/v3.2.0^{{}}\n",
                "git push --no-follow-tags origin refs/tags/v3.2.0:refs/tags/v3.2.0": cut.Refusal("network error"),
            }
        )
        with patch("sys.stderr") as stderr:
            self.assertEqual(self.cut_with(fake, "--replace-unpublished"), 1)
        err = "".join(call.args[0] for call in stderr.write.call_args_list)
        self.assertIn("partial remote mutation", err)
        self.assertNotIn("nothing pushed", err)

    def test_unverified_github_signature_reports_failure(self) -> None:
        fake = FakeCommands(
            **{
                "gh api repos/PowerBeef/Vocello/git/tags": json.dumps(
                    {"verification": {"verified": False, "reason": "unknown_key"}}
                )
            }
        )
        self.assertEqual(self.cut_with(fake), 1)
        self.assertIn("git push --no-follow-tags", fake.wrote())

    def test_non_release_tag_shapes_are_refused(self) -> None:
        for version in ("3.2", "3.2.0-ios.1", "3.2.0-rc.1"):
            with self.subTest(version=version), \
                 patch.object(cut, "project_version_from_text", return_value=(version, "32")):
                fake = FakeCommands()
                self.assertEqual(self.cut_with(fake), 1)
                self.assertEqual(fake.wrote(), [])
        with self.assertRaises(cut.Refusal):
            cut.create_and_push("v3.2.0-ios.1", COMMIT, "message")

    def test_tag_pattern_is_accepted_by_release_source_authority(self) -> None:
        self.assertIsNotNone(release_source_authority.TAG.fullmatch("v3.2.0"))
        self.assertIsNotNone(cut.RELEASE_TAG.fullmatch("v3.2.0"))
        self.assertIsNone(cut.RELEASE_TAG.fullmatch("v3.2.0-ios.1"))


if __name__ == "__main__":
    unittest.main()
