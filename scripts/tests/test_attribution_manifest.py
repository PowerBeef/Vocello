#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/attribution_manifest.py"
FILES = (
    "config/third-party-attribution-policy.json",
    "config/licenses/Apache-2.0.txt",
    "config/licenses/MIT-terms.txt",
    "config/notices/swift-asn1.txt",
    "config/notices/swift-crypto.txt",
    "config/notices/swift-nio.txt",
    "QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved",
    "Packages/VocelloQwen3Core/Package.resolved",
    "Packages/VocelloQwen3Core/LICENSE",
    "Packages/VocelloQwen3Core/NOTICES.md",
    "Packages/VocelloQwen3Core/ORIGINS.md",
    "Sources/Resources/qwenvoice_production_model_catalog.json",
    "Sources/Resources/third_party_attributions.json",
    "project.yml",
    "LICENSE",
)


class AttributionManifestTests(unittest.TestCase):
    def fixture(self, root: Path) -> None:
        for relative in FILES:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)

    def run_checker(self, root: Path, command: str = "validate") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), command, "--root", str(root)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_accepts_exact_resolutions_and_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            result = self.run_checker(root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_missing_and_duplicate_package_policy(self) -> None:
        for mutation in ("missing", "duplicate"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root)
                path = root / "config/third-party-attribution-policy.json"
                value = json.loads(path.read_text())
                if mutation == "missing":
                    value["packages"].pop()
                else:
                    value["packages"].append(dict(value["packages"][0]))
                path.write_text(json.dumps(value), encoding="utf-8")
                result = self.run_checker(root)
            self.assertNotEqual(result.returncode, 0)

    def test_rejects_resolution_license_and_model_card_drift(self) -> None:
        mutations = {
            "resolution": lambda root: self.mutate_revision(root),
            "license": lambda root: (root / "config/licenses/Apache-2.0.txt").write_text("changed", encoding="utf-8"),
            "model card": lambda root: self.mutate_model_card(root),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root)
                mutate(root)
                result = self.run_checker(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue("stale" in result.stderr or "drifts" in result.stderr, result.stderr)

    def test_rebuild_is_deterministic_and_preserves_pending_rights(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            output = root / "Sources/Resources/third_party_attributions.json"
            output.unlink()
            first = self.run_checker(root, "rebuild")
            first_bytes = output.read_bytes()
            second = self.run_checker(root, "rebuild")
            second_bytes = output.read_bytes()
            value = json.loads(output.read_text())
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(first_bytes, second_bytes)
        self.assertEqual(value["summary"]["pendingContentRightsCount"], 4)

    @staticmethod
    def mutate_revision(root: Path) -> None:
        path = root / "QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
        value = json.loads(path.read_text())
        value["pins"][0]["state"]["revision"] = "0" * 40
        path.write_text(json.dumps(value), encoding="utf-8")

    @staticmethod
    def mutate_model_card(root: Path) -> None:
        path = root / "Sources/Resources/qwenvoice_production_model_catalog.json"
        value = json.loads(path.read_text())
        readme = next(row for row in value["artifacts"][0]["files"] if row["relativePath"] == "README.md")
        readme["sha256"] = "0" * 64
        path.write_text(json.dumps(value), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
