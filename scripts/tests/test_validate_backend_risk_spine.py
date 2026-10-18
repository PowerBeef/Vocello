import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.validate_backend_risk_spine import summary, validate


class BackendRiskSpineValidatorTests(unittest.TestCase):
    def make_repository(self) -> tuple[tempfile.TemporaryDirectory, Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        (root / "Reports").mkdir()
        (root / "Reports/deferred.md").write_text("deferred\n", encoding="utf-8")
        (root / "Sources").mkdir()
        (root / "Sources/Engine.swift").write_text("struct Engine {}\n", encoding="utf-8")
        test_root = root / "Tests/VocelloCoreTests"
        test_root.mkdir(parents=True)
        (test_root / "EngineTests.swift").write_text(
            "final class EngineTests: XCTestCase { func testInvariant() {} }\n",
            encoding="utf-8",
        )
        scripts = root / "scripts"
        scripts.mkdir()
        (scripts / "macos_test.sh").write_text("  telemetry-overhead) run ;;\n", encoding="utf-8")
        config = root / "config.json"
        config.write_text(json.dumps({
            "schemaVersion": 3,
            "referenceFormat": "target/class/test",
            "evidence": {
                "reportDirectory": "Reports",
                "reportCommit": "0" * 40,
            },
            "items": [{
                "id": "ENGINE",
                "source": "Sources/Engine.swift",
                "tests": ["VocelloCoreTests/EngineTests/testInvariant"],
                "runtimeChecks": ["telemetry-overhead"],
                "status": "implemented",
                "remaining": [],
            }],
            "deferredMatrix": {"source": "Reports/deferred.md"},
        }), encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
        commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
        ).strip()
        data = json.loads(config.read_text(encoding="utf-8"))
        data["evidence"]["reportCommit"] = commit
        config.write_text(json.dumps(data), encoding="utf-8")
        return temporary, root, config

    def test_accepts_resolvable_contract(self):
        temporary, root, config = self.make_repository()
        self.addCleanup(temporary.cleanup)
        self.assertEqual(validate(root, config), [])

    def test_rejects_missing_test_method(self):
        temporary, root, config = self.make_repository()
        self.addCleanup(temporary.cleanup)
        data = json.loads(config.read_text(encoding="utf-8"))
        data["items"][0]["tests"] = ["VocelloCoreTests/EngineTests/testMissing"]
        config.write_text(json.dumps(data), encoding="utf-8")
        errors = validate(root, config)
        self.assertTrue(any("does not resolve" in error for error in errors), errors)

    def test_rejects_method_from_another_class(self):
        temporary, root, config = self.make_repository()
        self.addCleanup(temporary.cleanup)
        test_file = root / "Tests/VocelloCoreTests/EngineTests.swift"
        test_file.write_text(
            "final class EngineTests: XCTestCase {}\n"
            "final class OtherTests: XCTestCase { func testInvariant() {} }\n",
            encoding="utf-8",
        )
        errors = validate(root, config)
        self.assertTrue(any("does not resolve" in error for error in errors), errors)

    def test_rejects_unreachable_report_commit(self):
        temporary, root, config = self.make_repository()
        self.addCleanup(temporary.cleanup)
        data = json.loads(config.read_text(encoding="utf-8"))
        data["evidence"]["reportCommit"] = "f" * 40
        config.write_text(json.dumps(data), encoding="utf-8")
        errors = validate(root, config)
        self.assertTrue(any("not a reachable commit" in error for error in errors), errors)

    def test_rejects_nonempty_remaining_for_implemented_item(self):
        temporary, root, config = self.make_repository()
        self.addCleanup(temporary.cleanup)
        data = json.loads(config.read_text(encoding="utf-8"))
        data["items"][0]["remaining"] = ["missing proof"]
        config.write_text(json.dumps(data), encoding="utf-8")
        errors = validate(root, config)
        self.assertTrue(any("remaining must be empty" in error for error in errors), errors)

    def audit_items(self, root: Path, config: Path, *items: dict) -> list[str]:
        (root / "Reports/audit.md").write_text("findings\n", encoding="utf-8")
        data = json.loads(config.read_text(encoding="utf-8"))
        base = {"audit": "Reports/audit.md", "severity": "S2", "source": "Sources/Engine.swift"}
        data["items"].extend({**base, **item} for item in items)
        config.write_text(json.dumps(data), encoding="utf-8")
        return validate(root, config)

    def test_partial_and_uncovered_findings_are_accepted_and_reported(self):
        temporary, root, config = self.make_repository()
        self.addCleanup(temporary.cleanup)
        errors = self.audit_items(
            root, config,
            {"id": "F-1", "status": "partial", "tests": ["VocelloCoreTests/EngineTests/testInvariant"],
             "remaining": ["the coordinator wiring"]},
            {"id": "F-2", "status": "uncovered", "tests": [], "reason": "open finding"},
        )
        self.assertEqual(errors, [])
        lines = summary(config, report=True)
        self.assertEqual(lines[0], "1 implemented, 1 partial, 1 uncovered")
        self.assertIn("uncovered: F-2", lines)
        self.assertIn("- F-2 S2 uncovered: open finding", lines)
        self.assertIn("- F-1 S2 partial: the coordinator wiring", lines)

    def test_an_uncovered_finding_gives_a_reason_and_names_no_test(self):
        temporary, root, config = self.make_repository()
        self.addCleanup(temporary.cleanup)
        errors = self.audit_items(
            root, config,
            {"id": "F-1", "status": "uncovered", "tests": []},
            {"id": "F-2", "status": "uncovered", "reason": "open",
             "tests": ["VocelloCoreTests/EngineTests/testInvariant"]},
            {"id": "F-3", "status": "partial", "tests": ["VocelloCoreTests/EngineTests/testInvariant"]},
            {"id": "F-4", "status": "partial", "tests": [], "remaining": ["x"]},
            {"id": "F-5", "status": "open", "tests": []},
            {"id": "F-6", "status": "uncovered", "tests": [], "reason": "open", "severity": "S9",
             "audit": "Reports/missing.md"},
        )
        for expected in ("(F-1).reason must say why", "(F-2).tests must be empty", "(F-3).remaining must say",
                         "(F-4).tests must name", "(F-5).status must be one of", "(F-6).audit does not resolve",
                         "(F-6).severity must be one of"):
            self.assertTrue(any(expected in error for error in errors), (expected, errors))

    def test_suites_and_hosted_logic_tests_resolve_and_nested_helpers_do_not_end_a_class(self):
        temporary, root, config = self.make_repository()
        self.addCleanup(temporary.cleanup)
        (root / "Tests/VocelloCoreTests/EngineTests.swift").write_text(
            "@MainActor final class EngineTests: XCTestCase {\n"
            "    struct Fixture {}\n"
            "    class func setUpFixture() {}\n"
            "    func testInvariant() {}\n"
            "}\n"
            "private struct Helper {}\n"
            '@Suite("Frames")\n'
            "struct FramesTests {\n"
            "    @Test(arguments: 1...4) func framesRoundTrip(frames: Int) {}\n"
            "}\n",
            encoding="utf-8",
        )
        logic = root / "Tests/VocelloiOSLogicTests"
        logic.mkdir(parents=True)
        (logic / "PolicyTests.swift").write_text(
            "final class PolicyTests: XCTestCase { func testRule() {} }\n", encoding="utf-8"
        )
        data = json.loads(config.read_text(encoding="utf-8"))
        data["items"][0]["tests"] = ["VocelloCoreTests/EngineTests/testInvariant",
                                     "VocelloCoreTests/FramesTests/framesRoundTrip",
                                     "VocelloCoreTests/PolicyTests/testRule"]
        config.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(validate(root, config), [])
        data["items"][0]["tests"] = ["VocelloCoreTests/Helper/testInvariant",
                                     "VocelloCoreTests/EngineTests/framesRoundTrip"]
        config.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(len([e for e in validate(root, config) if "does not resolve" in e]), 2)


if __name__ == "__main__":
    unittest.main()
