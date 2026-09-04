from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "app_store_connect_readiness", ROOT / "scripts/app_store_connect_readiness.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class AppStoreConnectReadinessTests(unittest.TestCase):
    def test_policy_is_read_only_and_complete(self) -> None:
        policy = module.validate_policy()
        self.assertGreaterEqual(len(policy["reads"]), 8)
        all_tokens = {token for read in policy["reads"] for token in read["arguments"]}
        self.assertNotIn("--confirm", all_tokens)
        self.assertTrue(policy["webOrOwnerOnlyChecks"])

    def test_inventory_redacts_account_and_personal_values(self) -> None:
        calls: list[list[str]] = []

        def runner(arguments: list[str], profile: str, timeout: int) -> dict[str, object]:
            calls.append(arguments)
            self.assertEqual(profile, "primary")
            self.assertLessEqual(timeout, 120)
            if arguments[:2] == ["apps", "list"]:
                return {
                    "data": [{
                        "id": "private-app-id",
                        "type": "apps",
                        "attributes": {
                            "bundleId": "com.patricedery.vocello",
                            "name": "Private Name",
                        },
                    }]
                }
            return {
                "data": [{
                    "id": "private-resource-id",
                    "type": "appStoreVersions",
                    "attributes": {
                        "appStoreState": "PREPARE_FOR_SUBMISSION",
                        "contactEmail": "private@example.invalid",
                    },
                }]
            }

        result = module.inventory(runner=runner)
        self.assertEqual(result["status"], "PASS")
        encoded = json.dumps(result)
        self.assertNotIn("private-app-id", encoded)
        self.assertNotIn("private-resource-id", encoded)
        self.assertNotIn("private@example", encoded)
        self.assertNotIn("Private Name", encoded)
        self.assertIn("appStoreState=PREPARE_FOR_SUBMISSION", encoded)
        self.assertTrue(all("--output" in call for call in calls))

    def test_safe_tokens_normalize_current_asc_snake_case_without_exposing_payload(self) -> None:
        summary = module._summary(
            "content-rights",
            {
                "content_rights_declaration": "USES_THIRD_PARTY_CONTENT",
                "review_state": "NOT_SUBMITTED",
                "contact_email": "private@example.invalid",
                "id": "private-resource-id",
            },
        )

        self.assertEqual(
            summary["safeStateTokens"],
            [
                "contentRightsDeclaration=USES_THIRD_PARTY_CONTENT",
                "reviewState=NOT_SUBMITTED",
            ],
        )
        encoded = json.dumps(summary)
        self.assertNotIn("private@example", encoded)
        self.assertNotIn("private-resource-id", encoded)

    def test_required_read_failure_is_incomplete_but_optional_is_retained(self) -> None:
        def runner(arguments: list[str], _profile: str, _timeout: int) -> dict[str, object]:
            if arguments[:2] == ["apps", "list"]:
                return {"data": [{"id": "app", "attributes": {"bundleId": "com.patricedery.vocello"}}]}
            if arguments[0] == "validate":
                raise module.ReadinessError("version does not exist")
            if arguments[:2] == ["apps", "view"]:
                raise module.ReadinessError("read failed")
            return {"data": []}

        result = module.inventory(runner=runner)
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual(result["requiredReadFailures"], 1)
        version = next(row for row in result["reads"] if row["id"] == "version-readiness")
        self.assertFalse(version["required"])

    def test_ambiguous_app_fails_closed(self) -> None:
        with self.assertRaisesRegex(module.ReadinessError, "exactly one"):
            module.inventory(runner=lambda _arguments, _profile, _timeout: {"data": []})


if __name__ == "__main__":
    unittest.main()
