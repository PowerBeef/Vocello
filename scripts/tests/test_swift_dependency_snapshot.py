from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "swift_dependency_snapshot.py"
SPEC = importlib.util.spec_from_file_location("swift_dependency_snapshot", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def pin(identity: str, location: str, version: str, revision_character: str) -> dict[str, object]:
    return {
        "identity": identity,
        "kind": "remoteSourceControl",
        "location": location,
        "state": {"revision": revision_character * 40, "version": version},
    }


class SwiftDependencySnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root_lock = self.root / module.ROOT_LOCK
        self.core_lock = self.root / module.OWNED_CORE_LOCK
        self.root_lock.parent.mkdir(parents=True)
        self.core_lock.parent.mkdir(parents=True)
        (self.root / "project.yml").write_text(
            """name: Fixture
packages:
  GRDB:
    url: https://github.com/groue/GRDB.swift
    exactVersion: 7.10.0
  OwnedCore:
    path: Packages/VocelloQwen3Core
  MLXSwift:
    url: https://github.com/ml-explore/mlx-swift.git
    exactVersion: 0.30.6
schemes: {}
""",
            encoding="utf-8",
        )
        (self.root / "Packages/VocelloQwen3Core/Package.swift").write_text(
            """import PackageDescription
let package = Package(
  name: "Fixture",
  dependencies: [
    .package(url: "https://github.com/ml-explore/mlx-swift.git", exact: "0.30.6"),
    .package(
      url: "https://github.com/ml-explore/mlx-swift-lm.git",
      exact: "2.30.6"
    ),
  ]
)
""",
            encoding="utf-8",
        )
        self._write_lock(self.root_lock, [
            pin("grdb.swift", "https://github.com/groue/GRDB.swift", "7.10.0", "a"),
            pin("mlx-swift", "https://github.com/ml-explore/mlx-swift.git", "0.30.6", "b"),
            pin("swift-nio", "https://github.com/apple/swift-nio.git", "2.100.0", "c"),
        ])
        self._write_lock(self.core_lock, [
            pin("mlx-swift", "https://github.com/ml-explore/mlx-swift.git", "0.30.6", "b"),
            pin("mlx-swift-lm", "https://github.com/ml-explore/mlx-swift-lm.git", "2.30.6", "d"),
            pin("swift-nio", "https://github.com/apple/swift-nio.git", "2.100.0", "c"),
        ])

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def _write_lock(path: Path, pins: list[dict[str, object]]) -> None:
        path.write_text(json.dumps({"originHash": "0" * 64, "pins": pins, "version": 3}), encoding="utf-8")

    def snapshot(self) -> dict[str, object]:
        return module.build_snapshot(
            self.root,
            sha="e" * 40,
            ref="refs/heads/main",
            job_id="12345-1",
            scanned="2026-07-16T20:00:00-04:00",
            job_url="https://github.com/PowerBeef/Vocello/actions/runs/12345",
        )

    def test_snapshot_is_deterministic_and_keeps_manifests_independent(self) -> None:
        first = self.snapshot()
        second = self.snapshot()
        self.assertEqual(module.canonical_bytes(first), module.canonical_bytes(second))
        self.assertEqual(first["job"]["correlator"], module.JOB_CORRELATOR)
        self.assertEqual(
            set(first["manifests"]),
            {"qwenvoice-root-xcode-workspace-v1", "qwenvoice-owned-qwen3-core-v1"},
        )
        self.assertEqual(first["scanned"], "2026-07-17T00:00:00Z")

    def test_detector_uses_only_api_permitted_properties(self) -> None:
        snapshot = self.snapshot()
        self.assertEqual(
            set(snapshot),
            {"version", "sha", "ref", "job", "detector", "metadata", "scanned", "manifests"},
        )
        self.assertEqual(
            snapshot["detector"],
            {
                "name": module.DETECTOR_NAME,
                "version": module.DETECTOR_VERSION,
                "url": module.DETECTOR_URL,
            },
        )
        self.assertEqual(
            snapshot["metadata"],
            {"format": "swift-package-resolved-v3", "manifest_count": 2},
        )
        root = snapshot["manifests"]["qwenvoice-root-xcode-workspace-v1"]
        self.assertEqual(root["metadata"]["lockfile_version"], 3)
        self.assertEqual(root["resolved"]["swift-nio"]["metadata"], {"revision": "c" * 40})

    def test_direct_relationships_are_derived_from_each_declaration(self) -> None:
        manifests = self.snapshot()["manifests"]
        root = manifests["qwenvoice-root-xcode-workspace-v1"]["resolved"]
        core = manifests["qwenvoice-owned-qwen3-core-v1"]["resolved"]
        self.assertEqual(root["grdb.swift"]["relationship"], "direct")
        self.assertEqual(root["mlx-swift"]["relationship"], "direct")
        self.assertEqual(root["swift-nio"]["relationship"], "indirect")
        self.assertNotIn("grdb.swift", core)
        self.assertEqual(core["mlx-swift-lm"]["relationship"], "direct")
        self.assertEqual(core["swift-nio"]["relationship"], "indirect")

    def test_purls_are_namespaced_and_payload_uses_only_tracked_paths(self) -> None:
        snapshot = self.snapshot()
        root = snapshot["manifests"]["qwenvoice-root-xcode-workspace-v1"]
        self.assertEqual(
            root["resolved"]["grdb.swift"]["package_url"],
            "pkg:swift/github.com/groue/GRDB.swift@7.10.0",
        )
        serialized = module.canonical_bytes(snapshot).decode("utf-8")
        self.assertNotIn(str(self.root), serialized)
        self.assertNotIn("https://github.com/groue/GRDB.swift", serialized)
        self.assertEqual(root["file"]["source_location"], module.ROOT_LOCK.as_posix())

    def test_private_or_ambiguous_package_urls_fail_closed(self) -> None:
        lock = json.loads(self.root_lock.read_text(encoding="utf-8"))
        lock["pins"][0]["location"] = "https://token@github.com/groue/GRDB.swift"
        self.root_lock.write_text(json.dumps(lock), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "private URL components"):
            self.snapshot()

    def test_private_or_ambiguous_job_url_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "job-url"):
            module.build_snapshot(
                self.root,
                sha="e" * 40,
                ref="refs/heads/main",
                job_id="12345-1",
                scanned="2026-07-17T00:00:00Z",
                job_url="https://github.com/PowerBeef/Vocello/actions/runs/12345?token=secret",
            )

    def test_duplicate_package_identity_fails_closed(self) -> None:
        lock = json.loads(self.core_lock.read_text(encoding="utf-8"))
        lock["pins"].append(lock["pins"][0])
        self.core_lock.write_text(json.dumps(lock), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate package identity"):
            self.snapshot()

    def test_cli_prints_a_gh_api_compatible_json_document(self) -> None:
        output = subprocess.check_output([
            sys.executable,
            str(SCRIPT),
            "--root", str(self.root),
            "--sha", "e" * 40,
            "--ref", "refs/heads/main",
            "--job-id", "12345-1",
            "--scanned", "2026-07-17T00:00:00Z",
        ], text=True)
        payload = json.loads(output)
        self.assertEqual(payload["version"], 0)
        self.assertEqual(payload["sha"], "e" * 40)
        self.assertEqual(len(payload["manifests"]), 2)
        self.assertNotIn("metadata", payload["detector"])


if __name__ == "__main__":
    unittest.main()
