#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "model_catalog_contract", REPO_ROOT / "scripts/model_catalog_contract.py"
)
assert SPEC and SPEC.loader
CATALOG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CATALOG
SPEC.loader.exec_module(CATALOG)


class ModelCatalogContractTests(unittest.TestCase):
    component_files = [
        {
            "relativePath": "speech_tokenizer/config.json",
            "sizeBytes": 1,
            "sha256": "1" * 64,
        },
        {
            "relativePath": "speech_tokenizer/configuration.json",
            "sizeBytes": 1,
            "sha256": "2" * 64,
        },
        {
            "relativePath": "speech_tokenizer/model.safetensors",
            "sizeBytes": 2,
            "sha256": "3" * 64,
        },
        {
            "relativePath": "speech_tokenizer/preprocessor_config.json",
            "sizeBytes": 1,
            "sha256": "4" * 64,
        },
    ]

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "Sources/Resources").mkdir(parents=True)
        (self.root / "config").mkdir(parents=True)
        (self.root / CATALOG.SCHEMA_PATH).write_bytes((REPO_ROOT / CATALOG.SCHEMA_PATH).read_bytes())
        (self.root / CATALOG.RECEIPTS_PATH).write_text(
            json.dumps({"schemaVersion": 1, "artifacts": []}), encoding="utf-8"
        )
        self.contract = {
            "models": [{
                "id": "model",
                "variants": [
                    {
                        "id": "speed",
                        "platforms": ["iOS", "macOS"],
                        "folder": "Model-4bit",
                        "huggingFaceRepo": "org/model-4bit",
                        "huggingFaceRevision": "a" * 40,
                        "artifactVersion": "v1",
                        "iosDownloadEligible": True,
                        "estimatedDownloadBytes": 8,
                        "requiredRelativePaths": [
                            "config.json",
                            *[item["relativePath"] for item in self.component_files],
                        ],
                    },
                    {
                        "id": "quality",
                        "platforms": ["macOS"],
                        "folder": "Model-8bit",
                        "huggingFaceRepo": "org/model-8bit",
                        "huggingFaceRevision": "b" * 40,
                        "artifactVersion": "v1",
                        "iosDownloadEligible": False,
                        "estimatedDownloadBytes": 10,
                        "requiredRelativePaths": [
                            "config.json",
                            *[item["relativePath"] for item in self.component_files],
                        ],
                    },
                ],
            }]
        }
        self.ios_catalog = {
            "models": [{
                "modelID": "model",
                "artifactVersion": "v1",
                "totalBytes": 8,
                "baseURL": f"https://huggingface.co/org/model-4bit/resolve/{'a' * 40}",
                "files": [{
                    "relativePath": "config.json",
                    "sizeBytes": 3,
                    "sha256": "c" * 64,
                }, *self.component_files],
            }]
        }
        self.write_sources()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_sources(self) -> None:
        (self.root / CATALOG.CONTRACT_PATH).write_text(json.dumps(self.contract), encoding="utf-8")
        (self.root / CATALOG.IOS_CATALOG_PATH).write_text(json.dumps(self.ios_catalog), encoding="utf-8")

    def write_generated(self) -> None:
        (self.root / CATALOG.PRODUCTION_CATALOG_PATH).write_bytes(
            CATALOG.pretty_bytes(CATALOG.build_catalog(self.root))
        )

    def test_real_catalog_is_reproducible_and_complete(self) -> None:
        result = CATALOG.validate_catalog(REPO_ROOT)
        self.assertTrue(result["ok"], result["errors"])
        self.assertTrue(result["complete"])
        self.assertEqual(result["coveredArtifacts"], 6)
        self.assertEqual(result["missingArtifactIdentities"], [])
        catalog = result["catalog"]
        self.assertEqual(catalog, "Sources/Resources/qwenvoice_production_model_catalog.json")
        document = CATALOG.load_json(REPO_ROOT / CATALOG.PRODUCTION_CATALOG_PATH)
        totals = {
            f"{artifact['modelID']}:{artifact['variantID']}": artifact["totalBytes"]
            for artifact in document["artifacts"]
        }
        # Exact 2026.08.06.1 totals (Article 50 marking rollout: the
        # 2026.08.01.1 totals plus the 29,360,042-byte AudioSeal generator
        # added to every artifact).
        self.assertEqual(totals["pro_custom:quality"], 2_476_666_107)
        self.assertEqual(totals["pro_design:quality"], 2_476_665_614)
        self.assertEqual(totals["pro_clone:quality"], 2_500_683_247)
        self.assertEqual(document["schemaVersion"], 2)
        self.assertEqual(len(document["sharedComponents"]), 1)
        component = document["sharedComponents"][0]
        self.assertEqual(
            [item["relativePath"] for item in component["contentIdentity"]["files"]],
            list(CATALOG.SHARED_COMPONENT_PATHS),
        )
        self.assertEqual(
            component["sourceArtifactIdentities"],
            list(CATALOG.SHARED_COMPONENT_SOURCE_ORDER),
        )
        self.assertEqual(
            sorted(
                f"{artifact['modelID']}:{artifact['variantID']}"
                for artifact in document["artifacts"]
                if "iOS" in artifact["platforms"]
            ),
            ["pro_clone:speed", "pro_custom:speed", "pro_design:speed"],
        )
        self.assertTrue(all(
            artifact["sharedComponentIDs"] == [CATALOG.SHARED_COMPONENT_ID]
            for artifact in document["artifacts"]
        ))

    def test_staged_catalog_validates_but_complete_gate_fails_closed(self) -> None:
        self.write_generated()
        self.assertTrue(CATALOG.validate_catalog(self.root)["ok"])
        strict = CATALOG.validate_catalog(self.root, require_complete=True)
        self.assertFalse(strict["ok"])
        self.assertIn("model:quality", " ".join(strict["errors"]))

    def test_exact_additional_receipt_can_complete_the_catalog(self) -> None:
        receipt = {
            "modelID": "model",
            "artifactVersion": "v1",
            "totalBytes": 10,
            "baseURL": f"https://huggingface.co/org/model-8bit/resolve/{'b' * 40}",
            "files": [{
                "relativePath": "config.json",
                "sizeBytes": 5,
                "sha256": "d" * 64,
            }, *self.component_files],
        }
        (self.root / CATALOG.RECEIPTS_PATH).write_text(
            json.dumps({"schemaVersion": 1, "artifacts": [receipt]}), encoding="utf-8"
        )
        generated = CATALOG.build_catalog(self.root)
        self.assertEqual(generated["activationState"], "complete")
        self.assertEqual(generated["missingArtifactIdentities"], [])
        (self.root / CATALOG.PRODUCTION_CATALOG_PATH).write_bytes(CATALOG.pretty_bytes(generated))
        self.assertTrue(CATALOG.validate_catalog(self.root, require_complete=True)["ok"])

    def test_missing_sha_and_unsafe_path_are_rejected(self) -> None:
        for mutation in ("sha", "path"):
            with self.subTest(mutation=mutation):
                original = copy.deepcopy(self.ios_catalog)
                if mutation == "sha":
                    self.ios_catalog["models"][0]["files"][0].pop("sha256")
                else:
                    self.ios_catalog["models"][0]["files"][0]["relativePath"] = "../config.json"
                self.write_sources()
                with self.assertRaises(CATALOG.CatalogContractError):
                    CATALOG.build_catalog(self.root)
                self.ios_catalog = original

    def test_contract_disagreement_and_untrusted_host_are_rejected(self) -> None:
        original = copy.deepcopy(self.ios_catalog)
        self.ios_catalog["models"][0]["artifactVersion"] = "wrong"
        self.write_sources()
        with self.assertRaisesRegex(CATALOG.CatalogContractError, "matches 0"):
            CATALOG.build_catalog(self.root)

        self.ios_catalog = copy.deepcopy(original)
        self.ios_catalog["models"][0]["baseURL"] = (
            f"https://attacker.invalid/org/model-4bit/resolve/{'a' * 40}"
        )
        self.write_sources()
        with self.assertRaisesRegex(CATALOG.CatalogContractError, "host policy"):
            CATALOG.build_catalog(self.root)

        self.ios_catalog = copy.deepcopy(original)
        self.ios_catalog["models"][0]["files"][0]["url"] = (
            f"https://huggingface.co/org/model-4bit/resolve/{'a' * 40}/other.json"
        )
        self.write_sources()
        with self.assertRaisesRegex(CATALOG.CatalogContractError, "identity mismatch"):
            CATALOG.build_catalog(self.root)

    def test_generated_source_digest_detects_independent_mutation(self) -> None:
        self.write_generated()
        generated = json.loads((self.root / CATALOG.PRODUCTION_CATALOG_PATH).read_text())
        generated["sourceDigests"][str(CATALOG.CONTRACT_PATH)] = "0" * 64
        (self.root / CATALOG.PRODUCTION_CATALOG_PATH).write_text(json.dumps(generated), encoding="utf-8")
        result = CATALOG.validate_catalog(self.root)
        self.assertFalse(result["ok"])
        self.assertIn("stale", result["errors"][0])


if __name__ == "__main__":
    unittest.main()
