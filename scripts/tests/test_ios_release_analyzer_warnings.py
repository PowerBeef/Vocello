from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "ios_release_analyzer_warnings",
    ROOT / "scripts/ios_release_analyzer_warnings.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class IOSReleaseAnalyzerWarningPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = module.load_policy()

    def test_checked_in_policy_is_valid(self) -> None:
        self.assertEqual(module.validate_policy(self.policy), [])

    def test_registered_warning_passes_without_leaking_absolute_path(self) -> None:
        log = (
            "/opt/work/QwenVoice/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Generation.swift:194:16: "
            "warning: stored property has non-Sendable type 'MLXArray'\n"
        )
        result = module.analyze_log(log, self.policy)
        self.assertEqual(result["status"], "PASS")
        self.assertNotIn("/opt/work", str(result))

    def test_unknown_application_warning_fails_closed(self) -> None:
        result = module.analyze_log(
            "/opt/work/QwenVoice/Sources/iOS/App.swift:4:2: warning: unsafe behavior\n",
            self.policy,
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["unexpected"][0]["source"], "Sources/iOS/App.swift")

    def test_app_intents_tool_warning_is_registered(self) -> None:
        result = module.analyze_log(
            "appintentsmetadataprocessor[12:34] warning: Metadata extraction skipped. "
            "No AppIntents.framework dependency found.\n",
            self.policy,
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["registeredCounts"]["no-app-intents-framework"], 1)

    def test_allowance_count_cannot_grow_silently(self) -> None:
        row = self.policy["allowedWarnings"][0]
        line = (
            "/opt/work/QwenVoice/Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Generation.swift:1:1: "
            "warning: non-Sendable type 'MLXArray'\n"
        )
        result = module.analyze_log(line * (row["maximumCount"] + 1), self.policy)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["exceeded"][0]["id"], row["id"])

    def test_duplicate_id_is_rejected(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["allowedWarnings"][1]["id"] = policy["allowedWarnings"][0]["id"]
        self.assertIn("duplicate warning id", "\n".join(module.validate_policy(policy)))


if __name__ == "__main__":
    unittest.main()
