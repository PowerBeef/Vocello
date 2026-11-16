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
    "config/licenses/Unicode-3.0.txt",
    "config/language-normalization/hant-hans-v1.json",
    "config/language-normalization/hant-hans-v1.txt",
    "config/notices/sparkle.txt",
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
            # Compiled-in Unicode-3.0 data must be the bytes its manifest attributes.
            "data": lambda root: (root / "config/language-normalization/hant-hans-v1.txt").write_text(
                "6C23 6C14\n", encoding="utf-8"),
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

    def test_every_model_names_each_base_it_was_built_from(self) -> None:
        """A hybrid takes tensors from two conversions; the manifest names both, pinned (RF-61)."""
        manifest = json.loads((ROOT / "Sources/Resources/third_party_attributions.json").read_text())
        self.assertEqual(len(manifest["modelArtifacts"]), 3)
        for model in manifest["modelArtifacts"]:
            with self.subTest(model=model["repo"]):
                bases = [(model["baseRepo"], model["baseRevision"])] + [
                    (row["baseRepo"], row["baseRevision"]) for row in model["additionalBases"]]
                self.assertEqual(sorted(repo.rsplit("-", 1)[1] for repo, _ in bases), ["4bit", "8bit"])
                self.assertTrue(all(len(revision) == 40 for _, revision in bases))
                self.assertTrue(all(row["contribution"] for row in model["additionalBases"]))
                self.assertEqual(len(model["builtFrom"]), 2)
                self.assertTrue(model["redistributionDecision"])

    def test_rejects_an_unpinned_duplicate_or_undecided_model_lineage(self) -> None:
        def short_revision(card: dict) -> None:
            card["additionalBases"][0]["baseRevision"] = card["additionalBases"][0]["baseRevision"][:8]

        def duplicate_base(card: dict) -> None:
            card["additionalBases"][0]["baseRepo"] = card["baseRepo"]

        def no_contribution(card: dict) -> None:
            card["additionalBases"][0]["contribution"] = " "

        def no_base(card: dict) -> None:
            del card["baseRepo"]

        def self_parent(card: dict) -> None:
            card["builtFrom"][0]["repo"] = card["repo"]

        def no_decision(card: dict) -> None:
            del card["redistributionDecision"]

        mutations = {
            "exact baseRevision": short_revision, "twice": duplicate_base, "contributed": no_contribution,
            "names no baseRepo": no_base, "other than itself": self_parent,
            "carries no redistributionDecision": no_decision,
        }
        for expected, mutate in mutations.items():
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.fixture(root)
                path = root / "config/third-party-attribution-policy.json"
                value = json.loads(path.read_text())
                mutate(value["modelCards"][0])
                path.write_text(json.dumps(value), encoding="utf-8")
                result = self.run_checker(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(expected, result.stderr)

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
