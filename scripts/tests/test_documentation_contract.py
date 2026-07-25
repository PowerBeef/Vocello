#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "scripts/documentation_contract.py"
SPEC = importlib.util.spec_from_file_location("documentation_contract", HELPER)
assert SPEC and SPEC.loader
DOCUMENTATION = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DOCUMENTATION
SPEC.loader.exec_module(DOCUMENTATION)


class DocumentationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir(parents=True)
        (self.root / "config/build-output-policy.json").write_text(
            json.dumps(
                {
                    "entries": [
                        {"path": "build/cache/xcode/macos"},
                        {"path": "build/artifacts/macos"},
                        {"path": "build/dist/macos"},
                    ],
                    "publicLinks": [
                        {"path": "build/Vocello.app"},
                        {"path": "build/vocello"},
                    ],
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, relative: str, text: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_active_inventory_includes_nested_guidance_and_excludes_history(self) -> None:
        active = self.write("website/CLAUDE.md", "# Current\n")
        release = self.write("docs/releases/v2.0.0.md", "retired harness instructions\n")
        legacy = self.write("benchmarks/LEGACY_HISTORY.md", "retired harness instructions\n")
        paths = DOCUMENTATION.active_markdown_paths(self.root)
        self.assertIn(active, paths)
        self.assertNotIn(release, paths)
        self.assertNotIn(legacy, paths)

    def test_missing_link_and_script_are_rejected(self) -> None:
        source = self.write(
            "README.md",
            "[missing](docs/missing.md) and `scripts/missing_tool.sh`\n",
        )
        self.assertTrue(DOCUMENTATION.validate_relative_links(self.root, [source]))
        self.assertTrue(DOCUMENTATION.validate_script_references(self.root, [source]))
        self.write("docs/missing.md", "# Found\n")
        self.write("scripts/missing_tool.sh", "#!/bin/sh\n")
        self.assertEqual(DOCUMENTATION.validate_relative_links(self.root, [source]), [])
        self.assertEqual(DOCUMENTATION.validate_script_references(self.root, [source]), [])

    def test_stale_inline_repository_path_is_rejected(self) -> None:
        source = self.write("README.md", "Use `config/missing-contract.json`.\n")
        self.assertTrue(DOCUMENTATION.validate_repository_paths(self.root, [source]))
        self.write("config/missing-contract.json", "{}\n")
        self.assertEqual(DOCUMENTATION.validate_repository_paths(self.root, [source]), [])

    def test_declared_generated_repository_path_need_not_exist_in_clean_checkout(self) -> None:
        (self.root / "config/documentation-contract.json").write_text(
            json.dumps(
                {
                    "generatedRepositoryPaths": [
                        {
                            "path": "website/dist",
                            "owner": "website",
                            "producer": "npm --prefix website run build",
                            "requiredInCheckout": False,
                        }
                    ],
                    "groups": [],
                }
            ),
            encoding="utf-8",
        )
        source = self.write(
            "README.md",
            "Generated output is `website/dist/` and may contain `website/dist/assets/app.js`.\n",
        )
        self.assertFalse((self.root / "website/dist").exists())
        self.assertEqual(DOCUMENTATION.validate_repository_paths(self.root, [source]), [])
        source.write_text("Unknown generated output is `website/unowned-dist/`.\n", encoding="utf-8")
        self.assertTrue(DOCUMENTATION.validate_repository_paths(self.root, [source]))

    def test_only_manifest_owned_build_paths_are_documented(self) -> None:
        source = self.write(
            "README.md",
            "Valid `build/artifacts/macos/run` and `build/Vocello.app`; "
            "invalid `build/random-derived-data/run`.\n",
        )
        errors = DOCUMENTATION.validate_build_references(self.root, [source])
        self.assertEqual(len(errors), 1)
        self.assertIn("build/random-derived-data/run", errors[0])

    def test_transient_plugin_installation_cannot_be_claimed(self) -> None:
        source = self.write(
            "CLAUDE.md",
            "Use the installed GitHub integration. OpenAI Build iOS Apps supplies the server.\n",
        )
        errors = DOCUMENTATION.validate_optional_capabilities(self.root, [source])
        self.assertEqual(len(errors), 2)
        source.write_text(
            "Use GitHub when callable, otherwise gh. Use one shared server when available.\n",
            encoding="utf-8",
        )
        self.assertEqual(DOCUMENTATION.validate_optional_capabilities(self.root, [source]), [])

    def test_stale_generation_lifecycle_guidance_is_rejected(self) -> None:
        source = self.write(
            "docs/reference/runtime.md",
            "macOS uses `.unbounded`; iOS uses `.bufferingNewest(64)`. "
            "iOS cancel is cooperative only and does not conform to `ActiveGenerationCancellable`. "
            "The streaming chunk's `previewAudio` PCM is emitted.\n",
        )
        errors = DOCUMENTATION.validate_current_runtime_guidance(self.root, [source])
        self.assertEqual(len(errors), 5)
        source.write_text(
            "Both streams are bounded and measured. Cancellation awaits the owned task before unload.\n",
            encoding="utf-8",
        )
        self.assertEqual(DOCUMENTATION.validate_current_runtime_guidance(self.root, [source]), [])

    def test_retired_dropping_event_capacity_is_rejected(self) -> None:
        source = self.write(
            "docs/reference/runtime.md",
            "macOS uses bufferingNewest(256) and iOS uses bufferingNewest(96).\n",
        )
        errors = DOCUMENTATION.validate_current_runtime_guidance(self.root, [source])
        self.assertEqual(len(errors), 1)
        self.assertIn("bounded suspending router", errors[0])

    def test_complete_catalog_rejects_staged_prose_and_live_enumeration(self) -> None:
        self.write(
            "Sources/Resources/qwenvoice_production_model_catalog.json",
            json.dumps({"activationState": "complete", "missingArtifactIdentities": []}),
        )
        for relative in (
            "CLAUDE.md",
            ".claude/rules/backend-mlx.md",
            ".claude/rules/release-qa.md",
            "docs/ARCHITECTURE.md",
            "docs/development-progress.md",
            "docs/reference/model-delivery.md",
            "docs/project-map.html",
        ):
            self.write(relative, "The production model catalog is complete.\n")
        self.write(
            "Sources/ViewModels/ModelManagerViewModel.swift",
            "ProductionModelCatalog.shared.downloadFiles()\n",
        )
        cli = self.write(
            "Sources/VocelloCLI/ModelsCommand.swift",
            "ProductionModelCatalog.shared.downloadFiles()\n",
        )
        self.assertEqual(DOCUMENTATION.validate_model_catalog_guidance(self.root), [])
        cli.write_text(
            "The catalog is staged and Quality remains pending.\n"
            "ProductionModelCatalog.shared.downloadRepo()\n",
            encoding="utf-8",
        )
        (self.root / "CLAUDE.md").write_text(
            "The production model catalog is staged and Quality remains pending.\n",
            encoding="utf-8",
        )
        errors = DOCUMENTATION.validate_model_catalog_guidance(self.root)
        self.assertTrue(any("staged or Quality-pending" in error for error in errors))
        self.assertTrue(any("missing downloadFiles" in error for error in errors))
        self.assertTrue(any("live repository enumeration" in error for error in errors))

    def test_local_markdown_heading_anchor_is_validated(self) -> None:
        target = self.write("docs/guide.md", "# Guide\n\n## Exact heading\n")
        source = self.write("README.md", "[good](docs/guide.md#exact-heading)\n")
        self.assertEqual(DOCUMENTATION.validate_relative_links(self.root, [source]), [])
        source.write_text("[bad](docs/guide.md#missing-heading)\n", encoding="utf-8")
        self.assertTrue(DOCUMENTATION.validate_relative_links(self.root, [source]))
        self.assertIn("exact-heading", DOCUMENTATION.headings(target))

    def test_project_inventory_parser_counts_only_top_level_entries(self) -> None:
        project = "targets:\n  One:\n    type: app\n  Two:\n    type: framework\nschemes:\n  Main:\n    build:\n"
        self.assertEqual(DOCUMENTATION._top_level_names(project, "targets"), ["One", "Two"])
        self.assertEqual(DOCUMENTATION._top_level_names(project, "schemes"), ["Main"])

    def test_clean_canonical_status_is_derived_from_history(self) -> None:
        self.write(
            "benchmarks/runs/ui-generation/mac.json",
            json.dumps(
                {
                    "schemaVersion": 2,
                    "run": {"platform": "macos", "classification": "canonical", "status": "passedWithWarnings"},
                    "source": {"dirty": False},
                }
            ),
        )
        self.assertTrue(DOCUMENTATION.benchmark_baseline_status(self.root, "macos"))
        self.assertFalse(DOCUMENTATION.benchmark_baseline_status(self.root, "ios"))

    def test_visible_website_copy_rejects_universal_performance_and_em_dash(self) -> None:
        source = self.write("website/src/Hero.jsx", 'const copy = "Faster than realtime — everywhere";\n')
        errors = DOCUMENTATION.validate_website_copy(self.root)
        self.assertEqual(len(errors), 2)
        source.write_text('const copy = "Responsive native generation";\n', encoding="utf-8")
        self.assertEqual(DOCUMENTATION.validate_website_copy(self.root), [])

    def test_readme_public_contract_rejects_claim_and_asset_drift(self) -> None:
        self.write(
            "config/public-product-facts.json",
            json.dumps(
                {
                    "stableMacRelease": {"version": "2.1.0", "tag": "v2.1.0"},
                }
            ),
        )
        stale = self.write(
            "README.md",
            "Every generation records its sampling seed.\n\n"
            "The iPhone works exactly like the Mac app.\n\n"
            "![Screen](https://vocello.vercel.app/assets/screens/custom-voice.png)\n",
        )
        errors = DOCUMENTATION.validate_readme_public_contract(self.root)
        self.assertGreaterEqual(len(errors), 8)
        self.assertTrue(any("seed-replayable" in error for error in errors))
        self.assertTrue(any("repository-versioned" in error for error in errors))

        for relative in (
            "docs/readme_banner_vocello.png",
            "docs/screenshots/voice-design.png",
            "docs/screenshots/voice-cloning.png",
            "docs/screenshots/models.png",
            "docs/screenshots/history.png",
        ):
            self.write(relative, "fixture")
        stale.write_text(
            "[Download](https://github.com/PowerBeef/Vocello/releases/download/v2.1.0/Vocello-macos26.dmg)\n\n"
            "| Platform | Support | Model variants | Status |\n"
            "| --- | --- | --- | --- |\n"
            "| Mac | supported | Speed (4-bit) and Quality (8-bit) | available |\n"
            "| iPhone | supported | Speed (4-bit) | pending |\n\n"
            "Voice Cloning follows its reference and does not expose delivery controls.\n\n"
            "[mlx-audio-swift](https://github.com/Blaizzy/mlx-audio-swift)\n\n"
            "![Banner](docs/readme_banner_vocello.png)\n"
            "![Design](docs/screenshots/voice-design.png)\n"
            "![Clone](docs/screenshots/voice-cloning.png)\n"
            "![Models](docs/screenshots/models.png)\n"
            "![History](docs/screenshots/history.png)\n",
            encoding="utf-8",
        )
        self.assertEqual(DOCUMENTATION.validate_readme_public_contract(self.root), [])

    def test_historical_snapshot_paths_are_excluded_from_active_inventory(self) -> None:
        active = self.write(
            "README.md",
            "Do not resurrect Mirroir, Peekaboo, mobile-mcp, or computer-use drivers.\n",
        )
        report = self.write(
            "docs/reference/backend-optimization-research-report.md",
            "# Report\n\n> **Historical snapshot.**\n\nComputer Use and an old harness.\n",
        )
        paths = DOCUMENTATION.active_markdown_paths(self.root)
        self.assertIn(active, paths)
        self.assertNotIn(report, paths)
        self.assertEqual(DOCUMENTATION.validate_historical_banners(self.root), [])


if __name__ == "__main__":
    unittest.main()
