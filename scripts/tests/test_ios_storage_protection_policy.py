from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ios_storage_protection_policy",
    SCRIPTS / "ios_storage_protection_policy.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class IOSStorageProtectionPolicyTests(unittest.TestCase):
    def fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        for relative in [
            "config/ios-storage-protection-policy.json",
            "Sources/iOSSupport/Services/IOSStorageProtectionPolicy.swift",
            "Sources/iOS/IOSAppBootstrap.swift",
            "project.yml",
        ]:
            source = module.ROOT / relative
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        return temporary, root

    def test_live_policy_passes(self) -> None:
        result = module.validate()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["pathCount"], 11)

    def test_missing_data_class_fails_closed(self) -> None:
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        path = root / "config/ios-storage-protection-policy.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["paths"] = [row for row in payload["paths"] if row["id"] != "voices"]
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(module.PolicyError, "every governed"):
            module.validate(root)

    def test_user_voice_backup_exclusion_is_rejected(self) -> None:
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        path = root / "config/ios-storage-protection-policy.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        next(row for row in payload["paths"] if row["id"] == "voices")["backup"] = "excluded"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(module.PolicyError, "backup-eligible"):
            module.validate(root)

    def test_unsafe_path_and_source_drift_are_rejected(self) -> None:
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        path = root / "config/ios-storage-protection-policy.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        next(row for row in payload["paths"] if row["id"] == "cache")["relativePath"] = "../cache"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(module.PolicyError, "app-support root"):
            module.validate(root)

        shutil.copy2(module.POLICY, path)
        source = root / "Sources/iOSSupport/Services/IOSStorageProtectionPolicy.swift"
        source.write_text(source.read_text(encoding="utf-8").replace('id: "models"', 'id: "modelz"'), encoding="utf-8")
        with self.assertRaisesRegex(module.PolicyError, "Swift policy entries"):
            module.validate(root)

    def test_missing_bootstrap_and_project_ownership_are_rejected(self) -> None:
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        bootstrap = root / "Sources/iOS/IOSAppBootstrap.swift"
        bootstrap.write_text(bootstrap.read_text(encoding="utf-8").replace("IOSStorageProtectionPolicy.apply", "Removed.apply"), encoding="utf-8")
        with self.assertRaisesRegex(module.PolicyError, "bootstrap"):
            module.validate(root)

        shutil.copy2(module.BOOTSTRAP, bootstrap)
        project = root / "project.yml"
        project.write_text(project.read_text(encoding="utf-8").replace("Sources/iOSSupport/Services/IOSStorageProtectionPolicy.swift", "removed.swift", 1), encoding="utf-8")
        with self.assertRaisesRegex(module.PolicyError, "both host and generic-iOS"):
            module.validate(root)


if __name__ == "__main__":
    unittest.main()
