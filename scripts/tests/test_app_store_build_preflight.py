from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "app_store_build_preflight", SCRIPTS / "app_store_build_preflight.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class AppStoreBuildPreflightTests(unittest.TestCase):
    def test_live_project_identity_is_exact(self) -> None:
        identity = module.project_identity()
        self.assertEqual(identity["bundleIdentifier"], "com.patricedery.vocello")
        self.assertRegex(identity["marketingVersion"], r"^\d+\.\d+\.\d+$")
        self.assertRegex(identity["buildNumber"], r"^\d+$")

    def test_unused_identity_passes_with_complete_pagination(self) -> None:
        calls: list[list[str]] = []

        def runner(arguments: list[str], profile: str) -> dict[str, object]:
            calls.append(arguments)
            self.assertEqual(profile, "primary")
            if arguments[:2] == ["apps", "list"]:
                return {"data": [{"id": "private-app-id", "attributes": {"bundleId": "com.patricedery.vocello"}}]}
            return {"data": []}

        result = module.check(runner=runner)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["matchedBuildCount"], 0)
        self.assertNotIn("private-app-id", str(result))
        self.assertIn("--paginate", calls[0])
        self.assertIn("--paginate", calls[1])
        self.assertIn("--processing-state", calls[1])

    def test_existing_build_is_a_hard_collision(self) -> None:
        def runner(arguments: list[str], _profile: str) -> dict[str, object]:
            if arguments[:2] == ["apps", "list"]:
                return {"data": [{"id": "app", "attributes": {"bundleId": "com.patricedery.vocello"}}]}
            return {"data": [{"id": "build", "attributes": {"version": "23"}}]}

        with self.assertRaisesRegex(module.PreflightError, "already contains"):
            module.check(runner=runner)

    def test_ambiguous_app_and_malformed_pagination_fail_closed(self) -> None:
        with self.assertRaisesRegex(module.PreflightError, "exactly one"):
            module.check(runner=lambda _arguments, _profile: {"data": []})

        def malformed(arguments: list[str], _profile: str) -> dict[str, object]:
            if arguments[:2] == ["apps", "list"]:
                return {"data": [{"id": "app", "attributes": {"bundleId": "com.patricedery.vocello"}}]}
            return {"results": []}

        with self.assertRaisesRegex(module.PreflightError, "paginated"):
            module.check(runner=malformed)


if __name__ == "__main__":
    unittest.main()
