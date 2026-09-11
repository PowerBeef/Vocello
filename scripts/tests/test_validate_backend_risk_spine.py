import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.validate_backend_risk_spine import validate


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
            "schemaVersion": 2,
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


if __name__ == "__main__":
    unittest.main()
