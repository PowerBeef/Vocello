#!/usr/bin/env python3
"""Tests for scripts/lib/farm_smoke.py over a fake product tree and an injected curl runner:
nothing here builds, uploads or reaches BrowserStack."""

from __future__ import annotations

import json
import os
import plistlib
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import farm_smoke  # noqa: E402

COMMIT = "0123456789abcdef0123456789abcdef01234567"
ACCOUNT = ("maintainer_ab12", "SECRETkey123")
ONLY_TESTING = [
    "VocelloiOSUITests/VocelloiOSFarmSmokeUITests/testFarmSmokeJourney",
    "VocelloiOSUITests/VocelloiOSFarmSmokeUITests/testFarmTakeMemoryPeak",
]
BUILD_RESPONSES: dict[str, Any] = {
    "/app": {"app_url": "bs://app"},
    "/test-suite": {"test_suite_url": "bs://suite"},
    "/build": {"message": "Success", "build_id": "build42"},
}


def make_products(root: Path, *, with_farm_test: bool = True) -> Path:
    products = root / "stage"
    app = products / farm_smoke.APP
    (app / "Frameworks").mkdir(parents=True)
    binary = app / "Vocello"
    binary.write_bytes(b"\xcf\xfa\xed\xfe app")
    binary.chmod(0o755)
    (app / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleExecutable": "Vocello", "CFBundleShortVersionString": "3.0.0", "CFBundleVersion": "27",
    }, fmt=plistlib.FMT_BINARY))
    os.symlink("../Info.plist", app / "Frameworks" / "link")
    test_binary = products / farm_smoke.RUNNER / farm_smoke.TEST_BINARY
    test_binary.parent.mkdir(parents=True)
    test_binary.write_bytes(b"prefix VocelloiOSFarmSmokeUITests suffix" if with_farm_test else b"other")
    return products


def make_package(temp: str) -> Path:
    return farm_smoke.package(make_products(Path(temp)), Path(temp) / "farm", commit=COMMIT, dirty=False,
                              xcode="Xcode 27.1", fingerprint="fp", now=lambda: 0)


def mode(info: zipfile.ZipInfo) -> int:
    return info.external_attr >> 16


class FakeCurl:
    """Answers each BrowserStack endpoint the module calls and records argv and stdin."""

    def __init__(self, responses: dict[str, Any], fail_on: str | None = None) -> None:
        self.calls: list[tuple[list[str], str | None]] = []
        self.responses = responses
        self.fail_on = fail_on

    def __call__(self, argv: list[str], *, input: str | None = None) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), input))
        url = argv[-1]
        if self.fail_on and url.endswith(self.fail_on):
            return subprocess.CompletedProcess(argv, 22, '{"error":"bad"}', "")
        for suffix, body in self.responses.items():
            if url.endswith(suffix):
                text = body if isinstance(body, str) else json.dumps(body)
                return subprocess.CompletedProcess(argv, 0, text, "")
        raise AssertionError(f"unexpected request: {url}")

    def assert_account_only_on_stdin(self, test: unittest.TestCase) -> None:
        test.assertTrue(self.calls)
        for argv, config in self.calls:
            test.assertNotIn(ACCOUNT[1], " ".join(argv))
            test.assertEqual(argv[:3], ["curl", "-q", "--config"])
            test.assertTrue(argv[-1].startswith("https://api-cloud.browserstack.com/"))
            test.assertEqual(config, f'user = "{ACCOUNT[0]}:{ACCOUNT[1]}"\n')


class PackageTests(unittest.TestCase):
    def test_package_writes_ipa_suite_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            directory = make_package(temp)
            self.assertEqual(directory.name, "19700101-000000-01234567")
            self.assertEqual(sorted(path.name for path in (Path(temp) / "farm").iterdir()), [directory.name])
            with zipfile.ZipFile(directory / farm_smoke.IPA) as ipa:
                self.assertEqual({name.split("/")[0] for name in ipa.namelist()}, {"Payload"})
                for folder in ("Payload/", "Payload/Vocello.app/", "Payload/Vocello.app/Frameworks/"):
                    info = ipa.getinfo(folder)
                    self.assertTrue(stat.S_ISDIR(mode(info)), folder)
                    self.assertEqual(stat.S_IMODE(mode(info)) & 0o755, 0o755, folder)
                    self.assertTrue(info.external_attr & 0x10, folder)
                binary = ipa.getinfo("Payload/Vocello.app/Vocello")
                self.assertTrue(stat.S_ISREG(mode(binary)))
                self.assertTrue(stat.S_IMODE(mode(binary)) & stat.S_IXUSR)
                link = ipa.getinfo("Payload/Vocello.app/Frameworks/link")
                self.assertTrue(stat.S_ISLNK(mode(link)))
                self.assertEqual(ipa.read(link), b"../Info.plist")
            with zipfile.ZipFile(directory / farm_smoke.SUITE) as suite:
                self.assertEqual({name.split("/")[0] for name in suite.namelist()}, {farm_smoke.RUNNER})
                self.assertIn(f"{farm_smoke.RUNNER}/{farm_smoke.TEST_BINARY.as_posix()}", suite.namelist())
            manifest = json.loads((directory / farm_smoke.MANIFEST).read_text())
            self.assertEqual(manifest["sourceCommit"], COMMIT)
            self.assertEqual((manifest["appVersion"], manifest["appBuild"]), ("3.0.0", "27"))
            self.assertEqual(manifest["buildInputsFingerprint"], "fp")
            self.assertEqual(manifest["files"][farm_smoke.IPA], farm_smoke.sha256(directory / farm_smoke.IPA))
            self.assertEqual(manifest["onlyTesting"], ONLY_TESTING)

    def test_package_refuses_a_runner_without_the_farm_test_and_leaves_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            products = make_products(Path(temp), with_farm_test=False)
            with self.assertRaisesRegex(farm_smoke.FarmError, "VocelloiOSFarmSmokeUITests"):
                farm_smoke.package(products, Path(temp) / "farm", commit=COMMIT, dirty=False, xcode="x",
                                   fingerprint="fp")
            self.assertFalse((Path(temp) / "farm").exists())

    def test_package_refuses_a_short_commit_and_an_existing_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            products = make_products(Path(temp))
            with self.assertRaisesRegex(farm_smoke.FarmError, "full git SHA"):
                farm_smoke.package(products, Path(temp) / "farm", commit="abc123", dirty=False, xcode="x",
                                   fingerprint="fp")
            for _ in range(2):
                try:
                    farm_smoke.package(products, Path(temp) / "farm", commit=COMMIT, dirty=False, xcode="x",
                                       fingerprint="fp", now=lambda: 0)
                except farm_smoke.FarmError as error:
                    self.assertIn("already exists", str(error))
                    break
            else:
                self.fail("a second package in the same second must be refused")


class AccountTests(unittest.TestCase):
    def test_environment_wins_over_prompts(self) -> None:
        def refuse(_: str) -> str:
            raise AssertionError("must not prompt")

        account = farm_smoke.credentials(
            {"BROWSERSTACK_USERNAME": ACCOUNT[0], "BROWSERSTACK_ACCESS_KEY": ACCOUNT[1]}, refuse, refuse)
        self.assertEqual(account, ACCOUNT)

    def test_prompts_when_unset_and_rejects_config_breaking_characters(self) -> None:
        self.assertEqual(farm_smoke.credentials({}, lambda _: ACCOUNT[0], lambda _: ACCOUNT[1]), ACCOUNT)
        for user, key in (('user"', "key"), ("user", ""), ("user", "a b"), ("us:er", "key")):
            with self.assertRaises(farm_smoke.FarmError):
                farm_smoke.credentials({}, lambda _, u=user: u, lambda _, k=key: k)

    def test_the_account_goes_only_to_the_api_host_over_https(self) -> None:
        self.assertEqual(farm_smoke.api_url("/app-automate/x"), "https://api-cloud.browserstack.com/app-automate/x")
        for url in ("http://api-cloud.browserstack.com/x", "https://evil.example/x",
                    "https://api-cloud.browserstack.com.evil.example/x", "https://api-cloud.browserstack.com@evil.example/x",
                    "https://user:pass@api-cloud.browserstack.com/x", "https://api-cloud.browserstack.com:8443/x",
                    ".evil.example/x", "@evil.example/x"):
            with self.assertRaises(farm_smoke.FarmError, msg=url):
                farm_smoke.api_url(url)

    def test_curl_runs_without_the_account_in_its_environment(self) -> None:
        completed = subprocess.CompletedProcess(["curl"], 0, "{}", "")
        with mock.patch.dict(os.environ, {"BROWSERSTACK_ACCESS_KEY": ACCOUNT[1], "KEEP": "1"}), \
                mock.patch.object(farm_smoke.subprocess, "run", return_value=completed) as run:
            farm_smoke.run_command(["curl"], input="config")
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("BROWSERSTACK_ACCESS_KEY", environment)
        self.assertEqual(environment["KEEP"], "1")


class UploadTests(unittest.TestCase):
    def test_upload_starts_one_build_with_the_pinned_tests_and_devices(self) -> None:
        curl = FakeCurl(BUILD_RESPONSES)
        with tempfile.TemporaryDirectory() as temp:
            directory = make_package(temp)
            record = farm_smoke.upload(directory, lambda: ACCOUNT, devices=list(farm_smoke.DEFAULT_DEVICES),
                                       confirm=lambda _: True, run=curl)
            assert record is not None
            self.assertEqual(record["buildId"], "build42")
            saved = (directory / "uploads" / "build42.json").read_text()
            self.assertEqual(saved, (directory / farm_smoke.LATEST_UPLOAD).read_text())
            self.assertNotIn(ACCOUNT[1], saved)
        self.assertEqual(len(curl.calls), 3)
        curl.assert_account_only_on_stdin(self)
        argv = curl.calls[2][0]
        body = json.loads(argv[argv.index("--data-raw") + 1])
        self.assertEqual(body["devices"], ["iPhone 15 Pro-27", "iPhone 15 Pro Max-26"])
        self.assertEqual(body["only-testing"], ONLY_TESTING)
        self.assertEqual((body["app"], body["testSuite"]), ("bs://app", "bs://suite"))
        self.assertTrue(body["deviceLogs"])
        self.assertEqual(body["singleRunnerInvocation"], "true")

    def test_a_declined_upload_asks_for_no_account_and_sends_nothing(self) -> None:
        curl = FakeCurl(BUILD_RESPONSES)

        def no_account() -> tuple[str, str]:
            raise AssertionError("must not ask for the account")

        with tempfile.TemporaryDirectory() as temp:
            directory = make_package(temp)
            self.assertIsNone(farm_smoke.upload(directory, no_account, devices=["iPhone 15 Pro-27"],
                                                confirm=lambda _: False, run=curl))
        self.assertEqual(curl.calls, [])

    def test_upload_refuses_a_second_upload_and_a_changed_package(self) -> None:
        curl = FakeCurl(BUILD_RESPONSES)
        with tempfile.TemporaryDirectory() as temp:
            directory = make_package(temp)
            farm_smoke.upload(directory, lambda: ACCOUNT, devices=["iPhone 15 Pro-27"], confirm=lambda _: True,
                              run=curl)
            with self.assertRaisesRegex(farm_smoke.FarmError, "already uploaded"):
                farm_smoke.upload(directory, lambda: ACCOUNT, devices=["iPhone 15 Pro-27"],
                                  confirm=lambda _: True, run=curl)
            (directory / farm_smoke.IPA).write_bytes(b"changed")
            with self.assertRaisesRegex(farm_smoke.FarmError, "no longer matches"):
                farm_smoke.upload(directory, lambda: ACCOUNT, devices=["iPhone 15 Pro-27"],
                                  confirm=lambda _: True, run=curl, force=True)

    def test_a_failed_request_reports_the_body_and_records_nothing(self) -> None:
        curl = FakeCurl({"/app": {"app_url": "a"}}, fail_on="/test-suite")
        with tempfile.TemporaryDirectory() as temp:
            directory = make_package(temp)
            with self.assertRaises(farm_smoke.FarmError) as raised:
                farm_smoke.upload(directory, lambda: ACCOUNT, devices=["iPhone 15 Pro-27"],
                                  confirm=lambda _: True, run=curl)
            self.assertIn("bad", str(raised.exception))
            self.assertNotIn(ACCOUNT[1], str(raised.exception))
            self.assertFalse((directory / farm_smoke.LATEST_UPLOAD).exists())


class ResultsTests(unittest.TestCase):
    LOG = "\n".join([
        "Test Case started",
        'VOCELLO_FARM_SMOKE {"takes":[]}',
        "Test Case measured [Memory Peak Physical, kB] average: 2500000.000",
        "noise",
    ])

    def responses(self, *, build_status: str = "done", case_status: str = "passed",
                  log_url: str = "/app-automate/xcuitest/v2/builds/build42/sessions/s1/tests/t1/instrumentationlogs"
                  ) -> dict[str, Any]:
        return {
            "/builds/build42": {"status": build_status, "devices": [{
                "device": "iPhone 15 Pro", "os_version": "27", "sessions": [{"id": "s1", "status": case_status}],
            }]},
            "/builds/build42/sessions/s1": {"testcases": {"data": [{
                "class": "VocelloiOSFarmSmokeUITests",
                "testcases": [{"name": "testFarmSmokeJourney", "status": case_status, "instrumentation_log": log_url}],
            }]}},
            "/instrumentationlogs": self.LOG,
        }

    def read(self, curl: FakeCurl, lines: list[str]) -> tuple[int, Path]:
        temp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(temp, ignore_errors=True))
        directory = Path(temp)
        (directory / farm_smoke.LATEST_UPLOAD).write_text(json.dumps({"buildId": "build42"}))
        return farm_smoke.results(directory, ACCOUNT, run=curl, emit=lines.append), directory

    def test_results_prints_statuses_and_marker_lines_and_saves_logs_per_build(self) -> None:
        curl, lines = FakeCurl(self.responses()), []
        code, directory = self.read(curl, lines)
        self.assertEqual(code, 0)
        saved = directory / "results" / "build42" / "iPhone-15-Pro-iOS-27" / \
            "VocelloiOSFarmSmokeUITests-testFarmSmokeJourney.log"
        self.assertEqual(saved.read_text(), self.LOG)
        output = "\n".join(lines)
        self.assertIn("VocelloiOSFarmSmokeUITests/testFarmSmokeJourney: passed", output)
        self.assertIn('VOCELLO_FARM_SMOKE {"takes":[]}', output)
        self.assertIn("measured [Memory Peak Physical, kB]", output)
        self.assertNotIn("noise", output)
        self.assertNotIn(ACCOUNT[1], output)
        curl.assert_account_only_on_stdin(self)

    def test_results_codes_follow_the_build_and_its_tests(self) -> None:
        self.assertEqual(self.read(FakeCurl(self.responses(case_status="failed")), [])[0], 1)
        self.assertEqual(self.read(FakeCurl(self.responses(build_status="running")), [])[0],
                         farm_smoke.STILL_RUNNING)

    def test_results_refuses_a_log_url_on_another_host(self) -> None:
        curl = FakeCurl(self.responses(log_url="https://evil.example/instrumentationlogs"))
        with self.assertRaisesRegex(farm_smoke.FarmError, "refusing"):
            self.read(curl, [])
        self.assertFalse(any("evil.example" in argv[-1] for argv, _ in curl.calls))


if __name__ == "__main__":
    unittest.main()
