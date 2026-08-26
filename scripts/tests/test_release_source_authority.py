from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "release_source_authority.py"
SPEC = importlib.util.spec_from_file_location("release_source_authority", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class ReleaseSourceAuthorityTests(unittest.TestCase):
    tag = "v2.4.0"
    commit = "a" * 40
    tag_sha = "b" * 40

    def fixtures(self) -> tuple[dict, dict, dict]:
        tag_ref = {
            "ref": f"refs/tags/{self.tag}",
            "object": {"type": "tag", "sha": self.tag_sha},
        }
        tag_object = {
            "sha": self.tag_sha,
            "tag": self.tag,
            "object": {"type": "commit", "sha": self.commit},
            "verification": {
                "verified": True,
                "reason": "valid",
                "signature": "private-to-runner-signature-material",
                "payload": "private-to-runner-signed-payload",
                "verified_at": "2026-08-26T12:00:00Z",
            },
        }
        checks = {
            "total_count": 2,
            "check_runs": [
                self.check(1, "CI required"),
                self.check(2, "Security required"),
            ],
        }
        return tag_ref, tag_object, checks

    def check(
        self,
        identifier: int,
        name: str,
        *,
        status: str = "completed",
        conclusion: str | None = "success",
        commit: str | None = None,
    ) -> dict:
        return {
            "id": identifier,
            "name": name,
            "head_sha": commit or self.commit,
            "status": status,
            "conclusion": conclusion,
            "completed_at": f"2026-08-26T12:00:0{identifier}Z",
            "details_url": f"https://github.com/example/actions/runs/{identifier}",
            "app": {"slug": "github-actions"},
        }

    def test_valid_signed_tag_and_exact_sha_checks_pass(self) -> None:
        tag_ref, tag_object, checks = self.fixtures()
        result = module.validate(
            tag=self.tag,
            commit=self.commit,
            tag_ref=tag_ref,
            tag_object=tag_object,
            check_runs=checks,
        )
        self.assertEqual(result["status"], "passed")
        encoded = json.dumps(result)
        self.assertNotIn("private-to-runner", encoded)
        self.assertEqual(set(result["checks"]), {"CI required", "Security required"})

    def test_lightweight_tag_fails_closed(self) -> None:
        tag_ref, tag_object, checks = self.fixtures()
        tag_ref["object"]["type"] = "commit"
        with self.assertRaisesRegex(ValueError, "annotated signed tag"):
            module.validate(
                tag=self.tag, commit=self.commit, tag_ref=tag_ref,
                tag_object=tag_object, check_runs=checks,
            )

    def test_unsigned_or_invalid_tag_fails_closed(self) -> None:
        tag_ref, tag_object, checks = self.fixtures()
        tag_object["verification"].update(verified=False, reason="unsigned")
        with self.assertRaisesRegex(ValueError, "unsigned"):
            module.validate(
                tag=self.tag, commit=self.commit, tag_ref=tag_ref,
                tag_object=tag_object, check_runs=checks,
            )

    def test_signed_tag_must_target_exact_commit(self) -> None:
        tag_ref, tag_object, checks = self.fixtures()
        tag_object["object"]["sha"] = "c" * 40
        with self.assertRaisesRegex(ValueError, "does not target"):
            module.validate(
                tag=self.tag, commit=self.commit, tag_ref=tag_ref,
                tag_object=tag_object, check_runs=checks,
            )

    def test_missing_or_cross_sha_check_fails_closed(self) -> None:
        tag_ref, tag_object, checks = self.fixtures()
        checks["check_runs"][1]["head_sha"] = "d" * 40
        with self.assertRaisesRegex(ValueError, "Security required"):
            module.validate(
                tag=self.tag, commit=self.commit, tag_ref=tag_ref,
                tag_object=tag_object, check_runs=checks,
            )

    def test_latest_check_must_be_complete_and_successful(self) -> None:
        tag_ref, tag_object, checks = self.fixtures()
        checks["total_count"] = 3
        checks["check_runs"].append(
            self.check(3, "CI required", status="completed", conclusion="failure")
        )
        with self.assertRaisesRegex(ValueError, "failure"):
            module.validate(
                tag=self.tag, commit=self.commit, tag_ref=tag_ref,
                tag_object=tag_object, check_runs=checks,
            )

    def test_paginated_response_must_be_complete(self) -> None:
        tag_ref, tag_object, checks = self.fixtures()
        pages = [{"total_count": 3, "check_runs": checks["check_runs"]}]
        with self.assertRaisesRegex(ValueError, "incomplete"):
            module.validate(
                tag=self.tag, commit=self.commit, tag_ref=tag_ref,
                tag_object=tag_object, check_runs=pages,
            )

    def test_cli_output_is_privacy_safe(self) -> None:
        tag_ref, tag_object, checks = self.fixtures()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, value in (("ref", tag_ref), ("tag", tag_object), ("checks", checks)):
                (root / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable, str(SCRIPT), "--tag", self.tag, "--commit", self.commit,
                    "--tag-ref", str(root / "ref.json"),
                    "--tag-object", str(root / "tag.json"),
                    "--check-runs", str(root / "checks.json"),
                ],
                check=False,
                text=True,
                capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("private-to-runner", result.stdout)


if __name__ == "__main__":
    unittest.main()
