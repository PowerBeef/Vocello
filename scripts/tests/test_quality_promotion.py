#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("quality_promotion", SCRIPTS / "quality_promotion.py")
assert SPEC and SPEC.loader
PROMOTION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROMOTION
SPEC.loader.exec_module(PROMOTION)


CANONICAL_RECORD = (
    REPO_ROOT
    / "benchmarks/runs/ui-generation/macos-xcui-benchmark-20260801-182943-b0b5a448.json"
)


class QualityPromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir()
        for name in ("quality-promotion-contract.json", "evidence-impact.json"):
            shutil.copy2(REPO_ROOT / "config" / name, self.root / "config" / name)
        self.git("init", "-q")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "Fixture")
        (self.root / "README.md").write_text("base\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-qm", "base")
        self.base = self.git("rev-parse", "HEAD")
        (self.root / "README.md").write_text("candidate\n", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-qm", "candidate")
        self.commit = self.git("rev-parse", "HEAD")
        self.git("tag", "v2.4.0")
        self.release_path = self.root / "release-evidence.json"
        self.release = {
            "schemaVersion": 2,
            "release": {
                "tag": "v2.4.0",
                "commitSHA": self.commit,
                "marketingVersion": "2.4.0",
                "buildNumber": "23",
                "platform": "macos",
            },
            "sourceIdentity": {
                "gitCommit": self.commit,
                "treeDirty": False,
                "identityDigest": "a" * 64,
            },
        }
        self.write_json(self.release_path, self.release)
        self.record_path = self.root / "record.json"
        self.record = json.loads(CANONICAL_RECORD.read_text(encoding="utf-8"))
        self.rebind_record()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def git(self, *arguments: str) -> str:
        completed = subprocess.run(
            ["git", *arguments], cwd=self.root, text=True, capture_output=True, check=True
        )
        return completed.stdout.strip()

    @staticmethod
    def write_json(path: Path, value: dict) -> None:
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def rebind_record(self, *, age: timedelta = timedelta(minutes=1)) -> None:
        finished = datetime.now(timezone.utc).replace(microsecond=0) - age
        duration = float(self.record["run"]["durationSeconds"])
        self.record["run"]["finishedAt"] = finished.isoformat().replace("+00:00", "Z")
        self.record["run"]["startedAt"] = (finished - timedelta(seconds=duration)).isoformat().replace("+00:00", "Z")
        self.record["source"].update({
            "commit": self.commit,
            "dirty": False,
            "changedPaths": [],
            "fingerprintsMatch": True,
        })
        self.record["toolchain"]["appVersion"] = "2.4.0"
        self.record["toolchain"]["appBuild"] = "23"
        self.record["digest"] = PROMOTION.benchmark_history.record_digest(self.record)
        self.write_json(self.record_path, self.record)

    def create_args(self, **overrides: object) -> argparse.Namespace:
        values: dict[str, object] = {
            "root": self.root,
            "platform": "macos",
            "tag": "v2.4.0",
            "base": self.base,
            "release_evidence": self.release_path,
            "record": [f"macos-ui-benchmark={self.record_path}"],
            "receipt": [],
            "accept_warning": ["memory.pressure.soft_trim"],
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def validation_args(self, manifest: Path) -> argparse.Namespace:
        return argparse.Namespace(
            root=self.root,
            platform="macos",
            tag="v2.4.0",
            release_evidence=self.release_path,
            manifest=manifest,
        )

    def test_exact_source_manifest_round_trip(self) -> None:
        manifest = PROMOTION.create(self.create_args())
        path = self.root / "quality-promotion.json"
        self.write_json(path, manifest)
        validated = PROMOTION.validate_manifest(self.validation_args(path))
        self.assertEqual(validated["sourceCommit"], self.commit)
        self.assertEqual(validated["requiredEvidence"], ["macos-ui-benchmark"])
        self.assertEqual(
            validated["lanes"]["macos-ui-benchmark"]["hardwareProfileID"],
            "mac-mini-m2-8gb",
        )

    def test_missing_required_lane_is_rejected(self) -> None:
        with self.assertRaisesRegex(PROMOTION.PromotionError, "missing=.*macos-ui-benchmark"):
            PROMOTION.create(self.create_args(record=[]))

    def test_invalid_tag_is_rejected_before_git_resolution(self) -> None:
        with self.assertRaisesRegex(PROMOTION.PromotionError, "tag is invalid"):
            PROMOTION.create(self.create_args(tag="latest"))

    def test_cross_source_record_is_rejected(self) -> None:
        self.record["source"]["commit"] = "b" * 40
        self.record["digest"] = PROMOTION.benchmark_history.record_digest(self.record)
        self.write_json(self.record_path, self.record)
        with self.assertRaisesRegex(PROMOTION.PromotionError, "cross-source"):
            PROMOTION.create(self.create_args())

    def test_dirty_record_is_rejected(self) -> None:
        self.record["source"]["dirty"] = True
        self.record["source"]["changedPaths"] = ["Sources/Example.swift"]
        self.record["run"]["classification"] = "exploratory"
        self.record["digest"] = PROMOTION.benchmark_history.record_digest(self.record)
        self.write_json(self.record_path, self.record)
        with self.assertRaises(PROMOTION.PromotionError):
            PROMOTION.create(self.create_args())

    def test_unaccepted_warning_is_rejected(self) -> None:
        with self.assertRaisesRegex(PROMOTION.PromotionError, "not explicitly accepted"):
            PROMOTION.create(self.create_args(accept_warning=[]))

    def test_stale_record_is_rejected(self) -> None:
        self.rebind_record(age=timedelta(days=8))
        with self.assertRaisesRegex(PROMOTION.PromotionError, "freshness window"):
            PROMOTION.create(self.create_args())

    def test_manifest_is_bound_to_release_evidence_bytes(self) -> None:
        manifest = PROMOTION.create(self.create_args())
        path = self.root / "quality-promotion.json"
        self.write_json(path, manifest)
        changed = copy.deepcopy(self.release)
        changed["extra"] = "different bytes"
        self.write_json(self.release_path, changed)
        with self.assertRaisesRegex(PROMOTION.PromotionError, "differs from release evidence"):
            PROMOTION.validate_manifest(self.validation_args(path))

    def test_private_device_identity_is_rejected(self) -> None:
        manifest = PROMOTION.create(self.create_args())
        manifest["deviceName"] = "Personal iPhone"
        manifest["digest"] = PROMOTION.digest_value({key: value for key, value in manifest.items() if key != "digest"})
        path = self.root / "quality-promotion.json"
        self.write_json(path, manifest)
        with self.assertRaises(PROMOTION.PromotionError):
            PROMOTION.validate_manifest(self.validation_args(path))

    def test_managed_command_receipt_digest_is_fail_closed(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        definition = contract["evidence"]["macos-model-download-lifecycle"]
        receipt = {
            "schemaVersion": 1,
            "evidenceID": "macos-model-download-lifecycle",
            "platform": "macos",
            "sourceCommit": self.commit,
            "sourceDirty": False,
            "command": definition["command"],
            "commandDigest": PROMOTION.digest_value(definition["command"]),
            "startedAt": "2026-08-19T12:00:00Z",
            "finishedAt": "2026-08-19T12:01:00Z",
            "exitCode": 0,
            "outputDigest": "c" * 64,
            "contractDigest": PROMOTION.digest_value(contract),
        }
        receipt["digest"] = PROMOTION.digest_value(receipt)
        validated = PROMOTION.validate_receipt(
            "macos-model-download-lifecycle", receipt, definition, self.commit,
            PROMOTION.digest_value(contract), contract["maxEvidenceAgeSeconds"],
            datetime(2026, 8, 19, 12, 2, tzinfo=timezone.utc),
        )
        self.assertEqual(validated["receiptDigest"], receipt["digest"])
        receipt["outputDigest"] = "d" * 64
        with self.assertRaisesRegex(PROMOTION.PromotionError, "digest is invalid"):
            PROMOTION.validate_receipt(
                "macos-model-download-lifecycle", receipt, definition, self.commit,
                PROMOTION.digest_value(contract), contract["maxEvidenceAgeSeconds"],
                datetime(2026, 8, 19, 12, 2, tzinfo=timezone.utc),
            )

    def test_stale_managed_command_receipt_is_rejected(self) -> None:
        contract = PROMOTION.load_contract(self.root)
        definition = contract["evidence"]["macos-model-download-lifecycle"]
        receipt = {
            "schemaVersion": 1,
            "evidenceID": "macos-model-download-lifecycle",
            "platform": "macos",
            "sourceCommit": self.commit,
            "sourceDirty": False,
            "command": definition["command"],
            "commandDigest": PROMOTION.digest_value(definition["command"]),
            "startedAt": "2026-08-01T12:00:00Z",
            "finishedAt": "2026-08-01T12:01:00Z",
            "exitCode": 0,
            "outputDigest": "c" * 64,
            "contractDigest": PROMOTION.digest_value(contract),
        }
        receipt["digest"] = PROMOTION.digest_value(receipt)
        with self.assertRaisesRegex(PROMOTION.PromotionError, "freshness window"):
            PROMOTION.validate_receipt(
                "macos-model-download-lifecycle", receipt, definition, self.commit,
                PROMOTION.digest_value(contract), contract["maxEvidenceAgeSeconds"],
                datetime(2026, 8, 19, 12, 2, tzinfo=timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
