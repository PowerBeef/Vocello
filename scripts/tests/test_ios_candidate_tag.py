"""The candidate tag script refuses before it writes anything; never touches Git or the network."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import ios_candidate_tag as cut  # noqa: E402
import release_source_authority  # noqa: E402

COMMIT = "a" * 40
VERIFIED = {"verified": True, "reason": "valid"}


def ci(conclusion: str = "success") -> dict[str, str]:
    """`gh api` responses for one push run on main whose `CI required` check ended with `conclusion`."""
    runs = [{"total_count": 1, "workflow_runs": [{
        "id": 7, "event": "push", "head_branch": "main", "head_sha": COMMIT,
        "path": release_source_authority.CI_WORKFLOW_PATH, "check_suite_id": 9}]}]
    checks = [{"total_count": 1, "check_runs": [{
        "id": 5, "name": "CI required", "head_sha": COMMIT, "status": "completed", "conclusion": conclusion,
        "completed_at": "2026-10-24T12:00:00Z", "app": {"slug": "github-actions"}, "check_suite": {"id": 9}}]}]
    return {"check-runs": json.dumps(checks), "actions/runs": json.dumps(runs)}


class FakeCommands:
    """Answers each command by its leading words; records every call."""

    def __init__(self, **overrides: str | Exception) -> None:
        self.calls: list[list[str]] = []
        self.answers: dict[str, str | Exception] = {
            "git symbolic-ref": "main\n", "git status": "", "git fetch": "",
            "git rev-parse HEAD": COMMIT + "\n", "git rev-parse refs/remotes/origin/main": COMMIT + "\n",
            "git remote get-url origin": "https://github.com/PowerBeef/Vocello.git\n",
            "git show": "the commit's project spec\n",
            "asc builds list": json.dumps({"data": []}),
            "git config --get gpg.format": "ssh\n",
            "git config --get user.signingkey": __file__ + "\n",
            "git config --get gpg.ssh.allowedSignersFile": __file__ + "\n",
            "git tag --list": f"v3.0.0-ios.1 {'1' * 40}\nv3.0.0-ios.2 {'2' * 40}\n",
            "git ls-remote": f"{'b' * 40}\trefs/tags/v3.0.0-ios.2\n{'2' * 40}\trefs/tags/v3.0.0-ios.2^{{}}\n",
            "git tag -s": "", "git tag -v": "", "git cat-file": "tag\n",
            "git rev-parse refs/tags/v3.0.0-ios.3^{commit}": COMMIT + "\n", "git push": "",
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
        return [" ".join(call[:3]) for call in self.calls
                if call[:3] in (["git", "tag", "-s"], ["git", "push", "--no-follow-tags"])]


class CandidateTagTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(cut, "project_version_from_text", return_value=("3.0.0", "24"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def cut_with(self, fake: FakeCommands, *argv: str) -> int:
        with patch.object(cut, "run", fake), patch.object(cut.time, "sleep"), \
             patch.object(cut.subprocess, "run") as delete:
            status = cut.main(list(argv))
        self.deleted = [call.args[0] for call in delete.call_args_list]
        return status

    def test_the_next_free_number_counts_local_and_remote_tags(self) -> None:
        self.assertEqual(cut.next_tag("3.0.0", []), "v3.0.0-ios.1")
        self.assertEqual(cut.next_tag("3.0.0", ["v3.0.0-ios.2", "v3.0.0-ios.10", "v3.0.0", "v3.0.1-ios.40",
                                                "v3.0.0-ios.07"]), "v3.0.0-ios.11")

    def test_a_cut_signs_verifies_and_pushes_exactly_one_tag_ref(self) -> None:
        fake = FakeCommands()
        self.assertEqual(self.cut_with(fake), 0)
        self.assertIn(["git", "tag", "-s", "-m", "Vocello 3.0.0 for iPhone (TestFlight candidate 3, build 24)",
                       "v3.0.0-ios.3", COMMIT], fake.calls)
        self.assertIn(["git", "tag", "-v", "v3.0.0-ios.3"], fake.calls)
        pushes = [call for call in fake.calls if call[:2] == ["git", "push"]]
        self.assertEqual(pushes, [["git", "push", "--no-follow-tags", "origin",
                                   "refs/tags/v3.0.0-ios.3:refs/tags/v3.0.0-ios.3"]])
        self.assertIn(["git", "show", f"{COMMIT}:{cut.PROJECT_SPEC}"], fake.calls)
        sign, verify, push = (fake.calls.index(call) for call in (
            ["git", "tag", "-s", "-m", "Vocello 3.0.0 for iPhone (TestFlight candidate 3, build 24)",
             "v3.0.0-ios.3", COMMIT], ["git", "tag", "-v", "v3.0.0-ios.3"], pushes[0]))
        self.assertLess(sign, verify)
        self.assertLess(verify, push)

    def test_a_dry_run_checks_everything_and_writes_nothing(self) -> None:
        fake = FakeCommands()
        self.assertEqual(self.cut_with(fake, "--dry-run"), 0)
        self.assertEqual(fake.wrote(), [])
        self.assertTrue(any(call[:2] == ["asc", "builds"] for call in fake.calls))

    def test_every_precondition_refuses_before_anything_is_written(self) -> None:
        for label, overrides in (
            ("another branch", {"git symbolic-ref": "feature\n"}),
            ("dirty tree", {"git status": " M Sources/a.swift\n"}),
            ("unpushed commit", {"git rev-parse refs/remotes/origin/main": "d" * 40 + "\n"}),
            ("origin elsewhere", {"git remote get-url origin": "https://gitlab.com/PowerBeef/Vocello.git\n"}),
            ("candidate already on this commit", {"git tag --list": f"v3.0.0-ios.2 {COMMIT}\n"}),
            ("candidate already on origin", {"git ls-remote": f"{'b' * 40}\trefs/tags/v3.0.0-ios.2\n"
                                                              f"{COMMIT}\trefs/tags/v3.0.0-ios.2^{{}}\n"}),
            ("failed CI", ci("failure")),
            ("no CI", {"check-runs": json.dumps([{"total_count": 0, "check_runs": []}])}),
            ("used build", {"asc builds list": json.dumps({"data": [{"id": "x"}]})}),
            ("asc unavailable", {"asc builds list": cut.Refusal("asc failed")}),
            ("gpg signing", {"git config --get gpg.format": "openpgp\n"}),
            ("missing signers", {"git config --get gpg.ssh.allowedSignersFile": "/nonexistent/signers\n"}),
        ):
            with self.subTest(label):
                fake = FakeCommands(**overrides)
                self.assertEqual(self.cut_with(fake), 1)
                self.assertEqual(fake.wrote(), [])

    def test_a_failed_verify_or_push_removes_the_unpushed_local_tag(self) -> None:
        for step in ("git tag -v", "git push"):
            with self.subTest(step):
                fake = FakeCommands(**{step: cut.Refusal(f"{step} failed")})
                self.assertEqual(self.cut_with(fake), 1)
                self.assertEqual(self.deleted, [["git", "tag", "-d", "v3.0.0-ios.3"]])

    def test_an_unverified_github_signature_is_reported_as_a_failure(self) -> None:
        fake = FakeCommands(**{"gh api repos/PowerBeef/Vocello/git/tags":
                               json.dumps({"verification": {"verified": False, "reason": "unknown_key"}})})
        self.assertEqual(self.cut_with(fake), 1)
        self.assertIn("git push --no-follow-tags", fake.wrote())

    def test_a_failure_after_the_push_reports_the_pushed_tag_not_a_refusal(self) -> None:
        for answer in ("not json", cut.Refusal("HTTP 404"), RuntimeError("network")):
            with self.subTest(answer=answer):
                fake = FakeCommands(**{"gh api repos/PowerBeef/Vocello/git/ref": answer})
                with patch("sys.stdout") as stdout, patch("sys.stderr"):
                    self.assertEqual(self.cut_with(fake), 1)
                printed = "".join(call.args[0] for call in stdout.write.call_args_list)
                self.assertIn("Pushed v3.0.0-ios.3", printed)
                self.assertNotIn("refused", printed)

    def test_a_tag_of_any_other_shape_is_never_signed(self) -> None:
        for version in ("3.0", "3.0.0-rc.1"):
            with self.subTest(version=version), \
                 patch.object(cut, "project_version_from_text", return_value=(version, "24")):
                fake = FakeCommands(**{"git tag --list": "", "git ls-remote": ""})
                self.assertEqual(self.cut_with(fake), 1)
                self.assertEqual(fake.wrote(), [])
        with self.assertRaises(cut.Refusal):
            cut.create_and_push("v3.0.0-iOS.1", COMMIT, "message")

    def test_origin_names_the_repository(self) -> None:
        for url in ("https://github.com/PowerBeef/Vocello.git", "https://github.com/PowerBeef/Vocello",
                    "git@github.com:PowerBeef/Vocello.git", "ssh://git@github.com/PowerBeef/Vocello.git"):
            with self.subTest(url=url), patch.object(cut, "run", return_value=url + "\n"):
                self.assertEqual(cut.origin_repository(), "PowerBeef/Vocello")

    def test_the_tag_shape_matches_the_release_trigger(self) -> None:
        trigger = (ROOT / "scripts/ci/release_trigger.py").read_text(encoding="utf-8")
        self.assertIn(f're.compile(r"{cut.IOS_CANDIDATE.pattern}")', trigger)


if __name__ == "__main__":
    unittest.main()
