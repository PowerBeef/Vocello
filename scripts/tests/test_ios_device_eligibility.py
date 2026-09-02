from __future__ import annotations

import importlib.util
import plistlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ios_device_eligibility",
    SCRIPTS / "ios_device_eligibility.py",
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class IOSDeviceEligibilityTests(unittest.TestCase):
    def fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        for relative in [
            module.INFO_PLIST,
            module.POLICY_SOURCE,
            module.BOOTSTRAP_SOURCE,
            module.PROJECT,
            module.RELEASE_VERIFIER,
        ]:
            source = module.ROOT / relative
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        return temporary, root

    def test_live_contract_passes(self) -> None:
        result = module.validate()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            result["requiredCapabilities"],
            ["arm64", "iphone-performance-gaming-tier"],
        )

    def test_missing_or_extra_capability_fails_closed(self) -> None:
        for capabilities in [
            ["arm64"],
            ["arm64", "gps", "iphone-performance-gaming-tier"],
        ]:
            temporary, root = self.fixture()
            self.addCleanup(temporary.cleanup)
            path = root / module.INFO_PLIST
            payload = plistlib.loads(path.read_bytes())
            payload["UIRequiredDeviceCapabilities"] = capabilities
            path.write_bytes(plistlib.dumps(payload))
            with self.assertRaisesRegex(module.EligibilityError, "require exactly"):
                module.validate(root)

    def test_runtime_policy_drift_fails_closed(self) -> None:
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        path = root / module.POLICY_SOURCE
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                '"iphone-performance-gaming-tier"', '"gps"'
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(module.EligibilityError, "omits"):
            module.validate(root)

    def test_bootstrap_project_and_archive_verifier_are_required(self) -> None:
        temporary, root = self.fixture()
        self.addCleanup(temporary.cleanup)
        bootstrap = root / module.BOOTSTRAP_SOURCE
        bootstrap.write_text(
            bootstrap.read_text(encoding="utf-8").replace(
                "IOSDeviceEligibilityPolicy.isSupportedMachineIdentifier", "Removed.check"
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(module.EligibilityError, "runtime hardware guard"):
            module.validate(root)

        shutil.copy2(module.ROOT / module.BOOTSTRAP_SOURCE, bootstrap)
        project = root / module.PROJECT
        project.write_text(
            project.read_text(encoding="utf-8").replace(
                module.POLICY_SOURCE.as_posix(), "removed.swift", 1
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(module.EligibilityError, "both host"):
            module.validate(root)

        shutil.copy2(module.ROOT / module.PROJECT, project)
        verifier = root / module.RELEASE_VERIFIER
        verifier.write_text(
            verifier.read_text(encoding="utf-8").replace(
                "UIRequiredDeviceCapabilities", "RemovedCapabilities"
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(module.EligibilityError, "release verifier"):
            module.validate(root)


if __name__ == "__main__":
    unittest.main()
