#!/usr/bin/env python3
"""Offline fixtures for the iOS Speech asset bootstrap checker."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "check_ios_speech_assets.py"
RUNNER = ROOT / "Sources" / "iOS" / "IOSDeviceDiagnosticsRunner.swift"
DEVICE_SCRIPT = ROOT / "scripts" / "ios_device.sh"
FIXTURES = ROOT / "scripts" / "tests" / "fixtures" / "speech_assets"
RUN_ID = "ios-speech-assets-fixture"


class IOSSpeechAssetCheckerTests(unittest.TestCase):
    def run_fixture(
        self,
        name: str,
        *,
        run_id: str = RUN_ID,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CHECKER),
                str(FIXTURES / name),
                "--run-id",
                run_id,
            ],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_installed_assets_and_legacy_recognizers_pass(self) -> None:
        completed = self.run_fixture("installed.json")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("es_419", completed.stdout)
        self.assertIn("es_ES", completed.stdout)
        self.assertIn("asset_inventory=PASS", completed.stdout)
        self.assertIn("vocello_legacy_gate=PASS", completed.stdout)

    def test_download_failure_reports_bounded_error(self) -> None:
        completed = self.run_fixture("download-failed.json")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("download_failed", completed.stderr)
        self.assertIn("SFSpeechErrorDomain", completed.stderr)
        self.assertNotIn("asset_inventory=PASS", completed.stdout)

    def test_partial_install_is_not_accepted(self) -> None:
        completed = self.run_fixture("partial-install.json")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("post_installation_verification_failed", completed.stderr)

    def test_legacy_block_is_distinct_from_asset_failure(self) -> None:
        completed = self.run_fixture("legacy-blocked.json")
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("legacy on-device recognizer gate is blocked", completed.stderr)
        self.assertNotIn("asset_inventory=PASS", completed.stdout)

    def test_run_identity_and_locale_order_are_strict(self) -> None:
        wrong_run = self.run_fixture("installed.json", run_id="different-run")
        self.assertNotEqual(wrong_run.returncode, 0)
        self.assertIn("run identity mismatch", wrong_run.stderr)

        payload = json.loads((FIXTURES / "installed.json").read_text(encoding="utf-8"))
        payload["locales"] = list(reversed(payload["locales"]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong-order.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(CHECKER), str(path), "--run-id", RUN_ID],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("locale ordering mismatch", completed.stderr)

    def test_malformed_or_incomplete_evidence_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text("{not-json", encoding="utf-8")
            malformed = subprocess.run(
                [sys.executable, str(CHECKER), str(path), "--run-id", RUN_ID],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(malformed.returncode, 0)
        self.assertIn("invalid JSON", malformed.stderr)

        payload = json.loads((FIXTURES / "installed.json").read_text(encoding="utf-8"))
        payload["locales"].pop()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "incomplete.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            incomplete = subprocess.run(
                [sys.executable, str(CHECKER), str(path), "--run-id", RUN_ID],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(incomplete.returncode, 0)
        self.assertIn("incomplete locale evidence", incomplete.stderr)

    def test_device_contract_uses_one_run_scoped_non_generation_checker(self) -> None:
        shell = DEVICE_SCRIPT.read_text(encoding="utf-8")
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn('local locales="de_DE,es_419,ja_JP,zh_CN"', shell)
        self.assertIn('check_ios_speech_assets.py" "$sentinel" --run-id "$run_id"', shell)
        self.assertIn("AssetInventory.assetInstallationRequest", runner)
        self.assertIn("try await installationRequest.downloadAndInstall()", runner)
        self.assertIn("await finalizeSpeechAssetBootstrapResult", runner)
        self.assertLess(
            runner.index("} catch let error as SpeechAssetBootstrapError"),
            runner.index("await finalizeSpeechAssetBootstrapResult"),
        )
        speech_command = shell[shell.index("cmd_speech_assets() {") : shell.index("\n}\n", shell.index("cmd_speech_assets() {"))]
        self.assertNotIn("QVOICE_IOS_DEVICE_DIAGNOSTICS_SPEC", speech_command)
        self.assertNotIn("publish_benchmark_history", speech_command)


if __name__ == "__main__":
    unittest.main()
