"""The draft promotion-manifest uploader refuses before uploading anything; never touches the network."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import upload_promotion_manifest as uploader  # noqa: E402


class FakeCommands:
    def __init__(self, *, manifest_size: int, **overrides: str | Exception) -> None:
        self.calls: list[list[str]] = []
        self.uploaded = False
        self.manifest_size = manifest_size
        self.answers: dict[str, str | Exception] = {
            "git remote get-url origin": "https://github.com/PowerBeef/Vocello.git\n",
            "gh release upload": "",
            "validate": "Quality promotion: PASS\n",
        }
        self.answers.update(overrides)

    def __call__(self, argv: list[str]) -> str:
        self.calls.append(argv)
        command = " ".join(argv)
        if "quality_promotion.py validate" in command:
            answer = self.answers["validate"]
            if isinstance(answer, Exception):
                raise answer
            return answer
        if "repos/PowerBeef/Vocello/releases?per_page=100" in command:
            if "releases" in self.answers:
                answer = self.answers["releases"]
                if isinstance(answer, Exception):
                    raise answer
                return answer
            assets = [{"name": "quality-promotion.json", "size": self.manifest_size}] if self.uploaded else []
            return json.dumps([[{"tag_name": "v3.2.0", "draft": True, "assets": assets}]])
        if command.startswith("gh release upload"):
            answer = self.answers["gh release upload"]
            if isinstance(answer, Exception):
                raise answer
            self.uploaded = True
            return answer
        for key in sorted(self.answers, key=len, reverse=True):
            if command.startswith(key):
                answer = self.answers[key]
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise AssertionError(f"unexpected command: {command}")

    def uploads(self) -> list[list[str]]:
        return [c for c in self.calls if c[:3] == ["gh", "release", "upload"]]


class UploadPromotionManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.manifest = base / "quality-promotion.json"
        self.evidence = base / "release-evidence.json"
        self.payload = b'{"schemaVersion":2}\n'
        self.manifest.write_bytes(self.payload)
        self.evidence.write_text("{}\n", encoding="utf-8")

    def run_with(self, fake: FakeCommands, *extra: str, manifest: Path | None = None, tag: str = "v3.2.0") -> int:
        argv = [
            "--tag", tag,
            "--manifest", str(manifest or self.manifest),
            "--release-evidence", str(self.evidence),
            *extra,
        ]
        with patch.object(uploader, "run", fake):
            return uploader.main(argv)

    def test_valid_manifest_uploads_to_draft_and_verifies_size(self) -> None:
        fake = FakeCommands(manifest_size=len(self.payload))
        self.assertEqual(self.run_with(fake), 0)
        self.assertEqual(
            fake.uploads(),
            [["gh", "release", "upload", "v3.2.0", str(self.manifest), "--clobber", "--repo", "PowerBeef/Vocello"]],
        )
        self.assertEqual(len(self.payload), 20)
        self.assertEqual(len(hashlib.sha256(self.payload).hexdigest()), 64)

    def test_dry_run_checks_everything_and_uploads_nothing(self) -> None:
        fake = FakeCommands(manifest_size=len(self.payload))
        self.assertEqual(self.run_with(fake, "--dry-run"), 0)
        self.assertEqual(fake.uploads(), [])

    def test_preconditions_refuse_before_uploading(self) -> None:
        wrong_name = Path(self.tmp.name) / "Vocello.dmg"
        wrong_name.write_bytes(b"dmg")
        for label, tag, manifest, overrides in (
            ("ios candidate tag", "v3.2.0-ios.1", None, {}),
            ("bad tag", "3.2.0", None, {}),
            ("wrong filename", "v3.2.0", wrong_name, {}),
            ("missing manifest", "v3.2.0", Path(self.tmp.name) / "missing/quality-promotion.json", {}),
            ("validation failure", "v3.2.0", None, {"validate": uploader.Refusal("invalid")}),
            ("published release", "v3.2.0", None, {"releases": json.dumps([[{"tag_name": "v3.2.0", "draft": False, "assets": []}]])}),
            ("missing draft release", "v3.2.0", None, {"releases": json.dumps([[{"tag_name": "v3.1.0", "draft": False, "assets": []}]])}),
            ("releases api error", "v3.2.0", None, {"releases": uploader.Refusal("HTTP 500")}),
            ("non-github origin", "v3.2.0", None, {"git remote get-url origin": "https://gitlab.com/PowerBeef/Vocello.git\n"}),
        ):
            with self.subTest(label):
                fake = FakeCommands(manifest_size=len(self.payload), **overrides)
                self.assertEqual(self.run_with(fake, manifest=manifest, tag=tag), 1)
                self.assertEqual(fake.uploads(), [])

    def test_post_upload_size_mismatch_fails(self) -> None:
        fake = FakeCommands(manifest_size=len(self.payload) + 1)
        self.assertEqual(self.run_with(fake), 1)
        self.assertEqual(len(fake.uploads()), 1)


if __name__ == "__main__":
    unittest.main()
