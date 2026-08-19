#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "scripts" / "project_health.py"
ARTIFACT_ROOT = ROOT / "build" / "artifacts" / "project-health"


class ProjectHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # Routine cleanup may remove the disposable project-health artifact root.
        # Tests must be runnable from a fresh checkout and recreate their own
        # generated-output parent before asking tempfile to allocate beneath it.
        ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)

    def run_tool(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(TOOL), *arguments], text=True,
            capture_output=True, check=False,
        )

    def test_contract_and_report_are_privacy_safe_and_complete(self) -> None:
        validation = self.run_tool("validate")
        self.assertEqual(validation.returncode, 0, validation.stdout + validation.stderr)
        with tempfile.TemporaryDirectory(dir=ARTIFACT_ROOT) as directory:
            result = self.run_tool("report", "--output", directory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads((Path(directory) / "project-health.json").read_text(encoding="utf-8"))
            self.assertEqual(payload["requiredStepAssurance"]["forcedFailureCoverage"], "all-declared-steps")
            self.assertGreaterEqual(len(payload["criticalDomains"]), 8)
            self.assertGreater(payload["testInventory"]["swiftCases"], 0)
            self.assertGreater(payload["testInventory"]["pythonCases"], 0)
            self.assertTrue(payload["unsafeConcurrency"]["fullyRegistered"])
            self.assertEqual(
                payload["unsafeConcurrency"]["count"],
                payload["unsafeConcurrency"]["registeredCount"],
            )
            serialized = json.dumps(payload)
            self.assertNotIn(str(Path.home()), serialized)
            self.assertNotIn(str(ROOT), serialized)

    def test_hardware_freshness_is_derived_for_both_platforms(self) -> None:
        with tempfile.TemporaryDirectory(dir=ARTIFACT_ROOT) as directory:
            result = self.run_tool("report", "--output", directory)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads((Path(directory) / "project-health.json").read_text(encoding="utf-8"))
            catalog = payload["hardwareEvidenceCatalog"]
            self.assertEqual(catalog["macos-ui-generation"]["status"], "available")
            self.assertEqual(catalog["ios-ui-generation"]["status"], "available")
            self.assertEqual(catalog["macos-ui-performance"]["kind"], "ui-perf")
            self.assertEqual(catalog["ios-ui-performance"]["kind"], "ui-perf")
            self.assertTrue(catalog["ios-ui-performance"]["runID"])

    def test_domains_select_evidence_that_matches_their_risk(self) -> None:
        contract = json.loads(
            (ROOT / "config/project-health-contract.json").read_text(encoding="utf-8")
        )
        domains = {item["id"]: item for item in contract["criticalDomains"]}
        self.assertEqual(
            {item["kind"] for item in domains["memory-policy"]["hardwareEvidence"]},
            {"memory-qualification"},
        )
        self.assertEqual(
            {item["kind"] for item in domains["ui-performance"]["hardwareEvidence"]},
            {"ui-perf"},
        )
        self.assertEqual(domains["release-supply-chain"]["hardwareEvidence"], [])

    def test_tracked_summary_omits_self_referential_source_state(self) -> None:
        source = __import__("importlib.util").util.spec_from_file_location("project_health", TOOL)
        self.assertIsNotNone(source)
        module = __import__("importlib.util").util.module_from_spec(source)
        assert source.loader is not None
        source.loader.exec_module(module)
        report = module.build_report(module.validate_contract(module.DEFAULT_CONTRACT))
        rendered = module.markdown(report)
        self.assertNotIn(report["source"]["commit"], rendered)
        self.assertNotIn("dirty working tree", rendered)
        self.assertNotIn("Commit distance", rendered)

    def test_output_cannot_escape_governed_artifact_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_tool("report", "--output", directory)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must stay below", result.stderr)

    def test_model_delivery_domain_covers_catalog_and_runtime_routing(self) -> None:
        contract = json.loads(
            (ROOT / "config/project-health-contract.json").read_text(encoding="utf-8")
        )
        domain = next(item for item in contract["criticalDomains"] if item["id"] == "model-delivery")
        expected = {
            "Sources/QwenVoiceCore/ProductionModelCatalog.swift",
            "Sources/Models/TTSContract.swift",
            "Sources/ViewModels/ModelManagerViewModel.swift",
            "Sources/VocelloCLI/CLIRuntime.swift",
            "Sources/VocelloCLI/ModelsCommand.swift",
        }
        self.assertTrue(expected.issubset(set(domain["productionGlobs"])))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
