from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "swift_dependency_updates.py"
SPEC = importlib.util.spec_from_file_location("swift_dependency_updates", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def pin(identity: str, repository: str, version: str, revision: str) -> dict[str, object]:
    return {
        "identity": identity,
        "kind": "remoteSourceControl",
        "location": f"https://github.com/{repository}.git",
        "state": {"revision": revision * 40, "version": version},
    }


class SwiftDependencyUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / ".github/workflows").mkdir(parents=True)
        (self.root / ".github/workflows/swift-dependency-watch.yml").write_text("name: fixture\n")
        (self.root / "config").mkdir()
        (self.root / "config/toolchain.json").write_text("{}\n")
        (self.root / "config/evidence-impact.json").write_text("{}\n")
        (self.root / "docs/reference").mkdir(parents=True)
        (self.root / "docs/reference/mlx-guide.md").write_text("fixture\n")
        (self.root / "Packages/VocelloQwen3Core").mkdir(parents=True)
        (self.root / "project.yml").write_text(
            """name: Fixture
packages:
  GRDB:
    url: https://github.com/groue/GRDB.swift
    exactVersion: "7.10.0"
  MLX:
    url: https://github.com/ml-explore/mlx-swift.git
    exactVersion: "0.31.6"
targets: {}
"""
        )
        (self.root / "Packages/VocelloQwen3Core/Package.swift").write_text(
            """import PackageDescription
let package = Package(name: "Fixture", dependencies: [
  .package(url: "https://github.com/ml-explore/mlx-swift.git", exact: "0.31.6"),
  .package(url: "https://github.com/ml-explore/mlx-swift-lm.git", exact: "3.31.4")
])
"""
        )
        self.root_lock = self.root / module.Path(
            "QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
        )
        self.core_lock = self.root / "Packages/VocelloQwen3Core/Package.resolved"
        self.root_lock.parent.mkdir(parents=True)
        pins = [
            pin("grdb.swift", "groue/GRDB.swift", "7.10.0", "a"),
            pin("mlx-swift", "ml-explore/mlx-swift", "0.31.6", "b"),
            pin("mlx-swift-lm", "ml-explore/mlx-swift-lm", "3.31.4", "c"),
        ]
        for path in (self.root_lock, self.core_lock):
            path.write_text(json.dumps({"version": 3, "pins": pins}))
        (self.root / "Packages/VocelloQwen3Core/COMPATIBILITY.json").write_text(json.dumps({
            "package": {"directDependencies": {
                "mlx-swift": "0.31.6",
                "mlx-swift-lm": "3.31.4",
            }}
        }))
        self.policy = {
            "schemaVersion": 1,
            "policy": "fixture",
            "workflow": ".github/workflows/swift-dependency-watch.yml",
            "governanceSurfaces": [
                "config/toolchain.json",
                "config/evidence-impact.json",
                "docs/reference/mlx-guide.md",
            ],
            "packages": [
                {
                    "identity": "grdb.swift",
                    "repository": "groue/GRDB.swift",
                    "group": "root-app",
                    "declarations": ["project.yml"],
                    "locks": [self.root_lock.relative_to(self.root).as_posix()],
                    "compatibility": [],
                    "requiredEvidence": ["gate"],
                },
                {
                    "identity": "mlx-swift",
                    "repository": "ml-explore/mlx-swift",
                    "group": "mlx-lockstep",
                    "declarations": ["project.yml", "Packages/VocelloQwen3Core/Package.swift"],
                    "locks": [
                        self.root_lock.relative_to(self.root).as_posix(),
                        "Packages/VocelloQwen3Core/Package.resolved",
                    ],
                    "compatibility": ["Packages/VocelloQwen3Core/COMPATIBILITY.json"],
                    "requiredEvidence": ["gate", "bench"],
                },
                {
                    "identity": "mlx-swift-lm",
                    "repository": "ml-explore/mlx-swift-lm",
                    "group": "mlx-lockstep",
                    "declarations": ["Packages/VocelloQwen3Core/Package.swift"],
                    "locks": [
                        self.root_lock.relative_to(self.root).as_posix(),
                        "Packages/VocelloQwen3Core/Package.resolved",
                    ],
                    "compatibility": ["Packages/VocelloQwen3Core/COMPATIBILITY.json"],
                    "requiredEvidence": ["gate", "bench"],
                },
            ],
        }
        self.policy_path = self.root / "config/swift-dependency-update-policy.json"
        self.policy_path.write_bytes(module.canonical_bytes(self.policy))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def loaded(self) -> tuple[dict[str, object], bytes, dict[str, str]]:
        policy, raw = module.load_policy(self.root)
        return policy, raw, module.validate_pins(self.root, policy)

    def feeds(self) -> dict[str, object]:
        return {
            "groue/GRDB.swift": [{"tag_name": "v7.10.0"}],
            "ml-explore/mlx-swift": [{"tag_name": "0.32.0"}],
            "ml-explore/mlx-swift-lm": [
                {"tag_name": "v3.32.0", "prerelease": True},
                {"tag_name": "3.31.4"},
            ],
        }

    def test_exact_pins_validate_across_all_declared_surfaces(self) -> None:
        _, _, current = self.loaded()
        self.assertEqual(current, {
            "grdb.swift": "7.10.0",
            "mlx-swift": "0.31.6",
            "mlx-swift-lm": "3.31.4",
        })

    def test_pin_drift_fails_closed(self) -> None:
        compatibility = json.loads(
            (self.root / "Packages/VocelloQwen3Core/COMPATIBILITY.json").read_text()
        )
        compatibility["package"]["directDependencies"]["mlx-swift"] = "0.31.5"
        (self.root / "Packages/VocelloQwen3Core/COMPATIBILITY.json").write_text(
            json.dumps(compatibility)
        )
        policy, _ = module.load_policy(self.root)
        with self.assertRaisesRegex(module.PolicyError, "exact pins disagree"):
            module.validate_pins(self.root, policy)

    def test_update_proposes_whole_lockstep_group_without_inferring_compatibility(self) -> None:
        policy, raw, current = self.loaded()
        report = module.build_report(
            policy,
            raw,
            current,
            self.feeds(),
            [],
            generated_at="2026-08-26T15:00:00-04:00",
        )
        self.assertFalse(report["compatibilityInferred"])
        self.assertEqual(report["summary"]["updateCount"], 1)
        self.assertEqual(len(report["proposals"]), 1)
        proposal = report["proposals"][0]
        self.assertEqual(proposal["members"], ["mlx-swift", "mlx-swift-lm"])
        self.assertIn("project.yml", proposal["reviewSurfaces"])
        self.assertIn("Packages/VocelloQwen3Core/Package.resolved", proposal["reviewSurfaces"])
        self.assertIn("Packages/VocelloQwen3Core/COMPATIBILITY.json", proposal["reviewSurfaces"])
        self.assertEqual(report["generatedAt"], "2026-08-26T19:00:00Z")

    def test_open_advisory_proposes_review_even_without_new_release(self) -> None:
        policy, raw, current = self.loaded()
        feeds = self.feeds()
        feeds["ml-explore/mlx-swift"] = [{"tag_name": "0.31.6"}]
        report = module.build_report(
            policy,
            raw,
            current,
            feeds,
            [{
                "state": "open",
                "dependency": {"package": {"name": "grdb.swift"}},
                "security_advisory": {"ghsa_id": "GHSA-abcd-1234-5678", "severity": "high"},
            }],
            generated_at="2026-08-26T19:00:00Z",
        )
        self.assertEqual(report["summary"]["advisoryCount"], 1)
        self.assertEqual(report["proposals"][0]["group"], "root-app")

    def test_prerelease_does_not_create_a_false_update(self) -> None:
        policy, raw, current = self.loaded()
        feeds = self.feeds()
        feeds["ml-explore/mlx-swift"] = [
            {"tag_name": "0.32.0-beta.1", "prerelease": True},
            {"tag_name": "0.31.6"},
        ]
        report = module.build_report(
            policy, raw, current, feeds, [], generated_at="2026-08-26T19:00:00Z"
        )
        self.assertEqual(report["summary"]["updateCount"], 0)
        self.assertEqual(report["proposals"], [])

    def test_missing_release_feed_fails_closed(self) -> None:
        policy, raw, current = self.loaded()
        feeds = self.feeds()
        del feeds["groue/GRDB.swift"]
        with self.assertRaisesRegex(module.PolicyError, "missing repository"):
            module.build_report(
                policy, raw, current, feeds, [], generated_at="2026-08-26T19:00:00Z"
            )

    def test_markdown_is_path_safe_and_states_read_only_boundary(self) -> None:
        policy, raw, current = self.loaded()
        report = module.build_report(
            policy, raw, current, self.feeds(), [], generated_at="2026-08-26T19:00:00Z"
        )
        rendered = module.render_markdown(report)
        self.assertIn("Read-only signal", rendered)
        self.assertIn("maintainer", rendered.lower())
        self.assertNotIn(str(self.root), rendered)


if __name__ == "__main__":
    unittest.main()
