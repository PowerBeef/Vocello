#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "evidence_impact", REPO_ROOT / "scripts/evidence_impact.py"
)
assert SPEC and SPEC.loader
IMPACT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = IMPACT
SPEC.loader.exec_module(IMPACT)


class EvidenceImpactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = IMPACT.load_contract(REPO_ROOT)

    def test_repository_contract_is_valid_and_digest_is_stable(self) -> None:
        self.assertEqual(IMPACT.validate_contract(self.contract), [])
        first = IMPACT.contract_digest(self.contract)
        round_tripped = json.loads(json.dumps(self.contract))
        self.assertEqual(first, IMPACT.contract_digest(round_tripped))
        self.assertEqual(IMPACT.validate_repository_coverage(self.contract, REPO_ROOT), [])

    def test_model_delivery_change_has_deterministic_blockers_and_nonblocking_live_proofs(self) -> None:
        result = IMPACT.classify(
            self.contract,
            ["Sources/QwenVoiceCore/HuggingFaceDownloader.swift"],
        )
        self.assertIn("model-catalog-and-delivery", result["classes"])
        self.assertIn("engine-runtime", result["classes"])
        self.assertIn("model-catalog-contract", result["mergeRequiredEvidence"])
        self.assertIn("ios-model-download-lifecycle", result["qualityEvidence"])
        self.assertIn("ios-model-download-lifecycle", result["promotionRequiredEvidence"])
        self.assertNotIn("ios-model-download-lifecycle", result["mergeRequiredEvidence"])
        self.assertNotIn("ios-model-download-lifecycle", result["releaseRequiredEvidence"])
        self.assertFalse(result["qualityEvidenceBlocksOrdinaryPublication"])
        self.assertTrue(result["promotionEvidenceBlocksPublicPromotion"])

    def test_every_catalog_routing_surface_requires_complete_catalog_and_live_quality_proofs(self) -> None:
        paths = [
            "Sources/QwenVoiceCore/ProductionModelCatalog.swift",
            "Sources/Models/TTSContract.swift",
            "Sources/Models/TTSModel.swift",
            "Sources/ViewModels/ModelManagerViewModel.swift",
            "Sources/VocelloCLI/CLIRuntime.swift",
            "Sources/VocelloCLI/ModelsCommand.swift",
        ]
        for path in paths:
            with self.subTest(path=path):
                result = IMPACT.classify(self.contract, [path])
                self.assertIn("model-catalog-and-delivery", result["classes"])
                self.assertIn("model-catalog-complete", result["mergeRequiredEvidence"])
                self.assertIn("model-catalog-complete", result["releaseRequiredEvidence"])
                self.assertIn("macos-model-download-lifecycle", result["qualityEvidence"])
                self.assertIn("ios-model-download-lifecycle", result["qualityEvidence"])
                self.assertIn("macos-model-download-lifecycle", result["promotionRequiredEvidence"])
                self.assertIn("ios-model-download-lifecycle", result["promotionRequiredEvidence"])
                self.assertFalse(result["qualityEvidenceBlocksOrdinaryPublication"])

    def test_unknown_path_uses_deterministic_fallback(self) -> None:
        result = IMPACT.classify(self.contract, ["misc/new-file.txt"])
        self.assertEqual(result["classes"], ["repository-other"])
        self.assertEqual(result["mergeRequiredEvidence"], ["project-inputs"])
        self.assertEqual(result["qualityEvidence"], [])
        self.assertEqual(result["promotionRequiredEvidence"], [])

    def test_unknown_critical_path_is_rejected_instead_of_falling_back(self) -> None:
        broken = copy.deepcopy(self.contract)
        for item in broken["pathClasses"]:
            item["include"] = [
                pattern for pattern in item["include"] if pattern not in {"Sources/**", "scripts/**"}
            ]
        with self.assertRaisesRegex(IMPACT.EvidenceImpactError, "critical paths use"):
            IMPACT.classify(broken, ["Sources/NewProductionAuthority.swift"])
        with self.assertRaisesRegex(IMPACT.EvidenceImpactError, "critical paths use"):
            IMPACT.classify(broken, ["scripts/new_quality_analyzer.py"])

    def test_quality_and_promotion_authorities_request_detecting_evidence(self) -> None:
        cases = {
            "Sources/Services/AudioQualityGate.swift": "audio-quality-and-evaluation",
            "Sources/iOS/Settings/VoiceModelsScreen.swift": "platform-ui",
            "Sources/VocelloCLI/BenchCommand.swift": "repository-product-source",
            "scripts/analyze_prosody.py": "audio-quality-and-evaluation",
            "scripts/quality_promotion.py": "benchmark-and-promotion-authority",
            "config/quality-promotion-contract.json": "benchmark-and-promotion-authority",
        }
        for path, expected_class in cases.items():
            with self.subTest(path=path):
                result = IMPACT.classify(self.contract, [path])
                self.assertIn(expected_class, result["classes"])
                self.assertNotIn("repository-other", result["classes"])
                if expected_class != "repository-product-source":
                    self.assertTrue(result["promotionRequiredEvidence"])

    def test_capability_sensitive_paths_expose_promotion_dimensions(self) -> None:
        cases = {
            "Sources/Resources/qwenvoice_production_model_catalog.json": {
                "speed-generation", "quality-generation", "model-lifecycle",
            },
            "scripts/analyze_prosody.py": {"delivery-evaluation", "multilingual-output"},
            "scripts/quality_promotion.py": {
                "speed-generation", "quality-generation", "studio-modes",
                "multilingual-output", "delivery-evaluation", "model-lifecycle",
            },
        }
        for path, required in cases.items():
            with self.subTest(path=path):
                result = IMPACT.classify(self.contract, [path])
                self.assertTrue(required <= set(result["promotionCapabilities"]))

    def test_malformed_capability_list_is_rejected(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["pathClasses"][0]["promotionCapabilities"] = ["speed-generation", "speed-generation"]
        self.assertTrue(any("promotionCapabilities" in error for error in IMPACT.validate_contract(broken)))

    def test_memory_and_ui_changes_route_to_domain_specific_promotion_evidence(self) -> None:
        memory = IMPACT.classify(self.contract, ["Sources/QwenVoiceCore/WiredMemoryCoordinator.swift"])
        self.assertIn("memory-runtime", memory["classes"])
        self.assertIn("macos-retained-memory", memory["promotionRequiredEvidence"])
        self.assertIn("ios-retained-memory", memory["promotionRequiredEvidence"])

        ui = IMPACT.classify(self.contract, ["Sources/iOS/IOSStudioCanvas.swift"])
        self.assertIn("platform-ui", ui["classes"])
        self.assertIn("ios-ui-performance", ui["promotionRequiredEvidence"])

    def test_dot_prefixed_repository_paths_keep_their_identity(self) -> None:
        result = IMPACT.classify(self.contract, [".github/workflows/ci.yml"])
        self.assertIn("release-and-ci", result["classes"])
        self.assertNotIn("repository-other", result["classes"])

    def test_codex_session_storage_surfaces_require_hermetic_policy_fixtures(self) -> None:
        paths = (
            "config/codex-session-storage-policy.json",
            "docs/reference/codex-session-storage.md",
            "scripts/codex_session_storage.py",
            "scripts/tests/test_codex_session_storage.py",
        )
        for path in paths:
            with self.subTest(path=path):
                result = IMPACT.classify(self.contract, [path])
                self.assertIn("codex-session-storage-governance", result["classes"])
                self.assertIn("project-inputs", result["mergeRequiredEvidence"])
                self.assertIn("documentation-contract", result["mergeRequiredEvidence"])
                self.assertIn("project-inputs", result["releaseRequiredEvidence"])
                self.assertIn("documentation-contract", result["releaseRequiredEvidence"])
                self.assertEqual(result["qualityEvidence"], [])
                self.assertEqual(result["promotionRequiredEvidence"], [])
                if path.startswith("docs/"):
                    self.assertIn("documentation-and-governance", result["classes"])

    def test_device_or_model_evidence_cannot_become_publication_blocking(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["pathClasses"][0]["mergeRequiredEvidence"].append("ios-model-download-lifecycle")
        errors = IMPACT.validate_contract(broken)
        self.assertTrue(any("non-deterministic" in error for error in errors))

    def test_promotion_evidence_must_remain_non_deterministic(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["pathClasses"][0]["promotionRequiredEvidence"].append("project-inputs")
        errors = IMPACT.validate_contract(broken)
        self.assertTrue(any("promotionRequiredEvidence" in error for error in errors))

    def test_unknown_evidence_reference_and_missing_fallback_fail(self) -> None:
        broken = copy.deepcopy(self.contract)
        broken["pathClasses"][0]["releaseRequiredEvidence"].append("missing")
        broken.pop("fallbackClass")
        errors = IMPACT.validate_contract(broken)
        self.assertTrue(any("unknown evidence" in error for error in errors))
        self.assertTrue(any("fallbackClass" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
