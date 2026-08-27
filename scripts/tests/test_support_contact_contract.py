#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/support_contact_contract.py"


class SupportContactContractTests(unittest.TestCase):
    def fixture(self, root: Path) -> None:
        for relative in (
            "config/support-contact.json",
            "website/public/support/index.html",
            "website/public/privacy/index.html",
            "website/src/sections/Footer.jsx",
            "Sources/iOS/Settings/SettingsScreen.swift",
        ):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)

    def run_checker(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), "validate", "--root", str(root)],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_accepts_complete_support_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            result = self.run_checker(root)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_placeholder_contact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            path = root / "config/support-contact.json"
            value = json.loads(path.read_text())
            value["supportEmail"] = "support@example.com"
            path.write_text(json.dumps(value), encoding="utf-8")
            result = self.run_checker(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("placeholder", result.stderr)

    def test_rejects_surface_drift_and_sla(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            support = root / "website/public/support/index.html"
            text = support.read_text().replace("Vocello maintainer", "Support team")
            support.write_text(text + "<p>We respond within 2 days.</p>", encoding="utf-8")
            result = self.run_checker(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("response owner", result.stderr)
        self.assertIn("response SLA", result.stderr)

    def test_rejects_insecure_url_and_missing_app_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            path = root / "config/support-contact.json"
            value = json.loads(path.read_text())
            value["supportURL"] = "http://vocello.invalid/support/"
            path.write_text(json.dumps(value), encoding="utf-8")
            settings = root / "Sources/iOS/Settings/SettingsScreen.swift"
            settings.write_text(settings.read_text().replace("iosSettings_supportRow", "removed"), encoding="utf-8")
            result = self.run_checker(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("public HTTPS URL", result.stderr)


if __name__ == "__main__":
    unittest.main()
