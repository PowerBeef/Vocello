#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/lib/ios_platform_preflight.py"
SPEC = importlib.util.spec_from_file_location("ios_platform_preflight", HELPER)
assert SPEC is not None and SPEC.loader is not None
preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = preflight
SPEC.loader.exec_module(preflight)


def sdk(*, build: str | None = "23F81a", version: str = "26.5") -> list[dict[str, object]]:
    item: dict[str, object] = {
        "canonicalName": "iphoneos26.5",
        "displayName": "iOS 26.5",
        "isBaseSdk": True,
        "platform": "iphoneos",
        "platformVersion": version,
    }
    if build is not None:
        item["productBuildVersion"] = build
    return [item]


def runtime(
    *,
    build: str | None = "23F81a",
    version: str = "26.5.1",
    available: bool = True,
    identifier: str = "com.apple.CoreSimulator.SimRuntime.iOS-26-5",
) -> dict[str, list[dict[str, object]]]:
    item: dict[str, object] = {
        "identifier": identifier,
        "version": version,
        "isAvailable": available,
    }
    if build is not None:
        item["buildversion"] = build
    return {"runtimes": [item]}


class IOSPlatformPreflightTests(unittest.TestCase):
    def run_fixture(
        self,
        sdk_payload: object,
        runtime_payload: object,
        *,
        json_output: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sdk_path = root / "sdks.json"
            runtime_path = root / "runtimes.json"
            sdk_path.write_text(json.dumps(sdk_payload), encoding="utf-8")
            runtime_path.write_text(json.dumps(runtime_payload), encoding="utf-8")
            command = [
                "python3",
                str(HELPER),
                "check",
                "--sdk-json",
                str(sdk_path),
                "--runtime-json",
                str(runtime_path),
            ]
            if json_output:
                command.append("--json")
            return subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )

    def test_exact_sdk_runtime_build_passes(self) -> None:
        result = self.run_fixture(sdk(), runtime(), json_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ready")
        self.assertEqual(payload["sdk"]["build"], "23F81a")
        self.assertFalse(payload["simulatorExecutionAuthorized"])

    def test_empty_runtime_inventory_fails_with_attended_repair(self) -> None:
        result = self.run_fixture(sdk(), {"runtimes": []})
        self.assertEqual(result.returncode, 1)
        self.assertIn("no matching available runtime is installed", result.stderr)
        self.assertIn("Xcode > Settings > Components", result.stderr)
        self.assertIn("installs nothing", result.stderr)
        self.assertIn("does not authorize Simulator", result.stderr)

    def test_xcode_supported_patch_build_pair_passes_when_version_matches(self) -> None:
        result = self.run_fixture(sdk(build="23F81a"), runtime(build="23F77", version="26.5"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_runtime_version_fails_even_when_build_differs(self) -> None:
        result = self.run_fixture(sdk(), runtime(build="23E99", version="26.4"))
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "blocked",
            json.loads(
                self.run_fixture(
                    sdk(),
                    runtime(build="23E99", version="26.4"),
                    json_output=True,
                ).stdout
            )["status"],
        )

    def test_runtime_version_is_authoritative_when_build_matches(self) -> None:
        result = self.run_fixture(sdk(build="23F81a"), runtime(build="23F81a", version="26.4"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("no matching available runtime is installed", result.stderr)

    def test_matching_unavailable_runtime_fails(self) -> None:
        result = self.run_fixture(sdk(), runtime(available=False))
        self.assertEqual(result.returncode, 1)
        self.assertIn("matching runtime is installed but unavailable", result.stderr)

    def test_unavailable_patch_build_pair_is_classified_as_matching(self) -> None:
        result = self.run_fixture(
            sdk(build="23F81a"),
            runtime(build="23F77", version="26.5", available=False),
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("matching runtime is installed but unavailable", result.stderr)

    def test_patch_versions_match_when_build_identity_is_absent(self) -> None:
        result = self.run_fixture(sdk(build=None, version="26.5"), runtime(build=None, version="26.5.1"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_runtime_version_uses_exact_build_fallback(self) -> None:
        result = self.run_fixture(sdk(build="23F81a"), runtime(build="23F81a", version=""))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_runtime_version_rejects_different_build(self) -> None:
        result = self.run_fixture(sdk(build="23F81a"), runtime(build="23F77", version=""))
        self.assertEqual(result.returncode, 1)
        self.assertIn("no matching available runtime is installed", result.stderr)

    def test_one_valid_runtime_among_multiple_passes(self) -> None:
        payload = {
            "runtimes": [
                runtime(build="23A1", version="26.0")["runtimes"][0],
                runtime()["runtimes"][0],
            ]
        }
        result = self.run_fixture(sdk(), payload)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_base_iphoneos_sdk_has_separate_diagnosis(self) -> None:
        result = self.run_fixture(
            [{"canonicalName": "iphonesimulator26.5", "platform": "iphonesimulator", "isBaseSdk": True}],
            runtime(),
            json_output=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["code"], "missingIOSSDK")

    def test_malformed_inventory_fails_closed(self) -> None:
        result = self.run_fixture(sdk(), {"unexpected": []}, json_output=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["code"], "inspectionFailed")

    def test_invalid_json_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sdk_path = root / "sdks.json"
            runtime_path = root / "runtimes.json"
            sdk_path.write_text("{", encoding="utf-8")
            runtime_path.write_text(json.dumps(runtime()), encoding="utf-8")
            result = subprocess.run(
                [
                    "python3",
                    str(HELPER),
                    "check",
                    "--sdk-json",
                    str(sdk_path),
                    "--runtime-json",
                    str(runtime_path),
                    "--json",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["code"], "inspectionFailed")

    def test_live_inspection_uses_only_read_only_public_commands(self) -> None:
        responses = [
            subprocess.CompletedProcess(preflight.SDK_COMMAND, 0, json.dumps(sdk()), ""),
            subprocess.CompletedProcess(preflight.RUNTIME_COMMAND, 0, json.dumps(runtime()), ""),
        ]
        with mock.patch.object(preflight.subprocess, "run", side_effect=responses) as runner:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(preflight.main(["check", "--json"]), 0)
        self.assertEqual(
            [call.args[0] for call in runner.call_args_list],
            [list(preflight.SDK_COMMAND), list(preflight.RUNTIME_COMMAND)],
        )
        inspected = " ".join(preflight.SDK_COMMAND + preflight.RUNTIME_COMMAND)
        for forbidden in ("download", "import", "delete", "boot", "create", "runFirstLaunch"):
            self.assertNotIn(forbidden, inspected)

    def test_nonzero_inventory_command_never_passes(self) -> None:
        response = subprocess.CompletedProcess(preflight.SDK_COMMAND, 72, "", "failure")
        with mock.patch.object(preflight.subprocess, "run", return_value=response):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(preflight.main(["check", "--json"]), 1)

    def test_unavailable_runtime_registry_is_distinct_from_missing_component(self) -> None:
        responses = [
            subprocess.CompletedProcess(preflight.SDK_COMMAND, 0, json.dumps(sdk()), ""),
            subprocess.CompletedProcess(preflight.RUNTIME_COMMAND, 72, "", "failure"),
        ]
        output = io.StringIO()
        with mock.patch.object(preflight.subprocess, "run", side_effect=responses):
            with redirect_stdout(output):
                self.assertEqual(preflight.main(["check", "--json"]), 1)
        self.assertEqual(json.loads(output.getvalue())["code"], "runtimeRegistryUnavailable")


if __name__ == "__main__":
    unittest.main()
