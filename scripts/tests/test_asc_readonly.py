from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("asc_readonly", SCRIPTS / "asc_readonly.py")
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


class FakeProcess:
    def __init__(self, *, stdout: str = "{}", returncode: int = 0, timeout: bool = False) -> None:
        self.pid = 1234
        self.returncode = returncode
        self.stdout = stdout
        self.timeout = timeout
        self.calls = 0

    def communicate(self, timeout: int | None = None) -> tuple[str, str]:
        self.calls += 1
        if self.timeout and self.calls == 1:
            raise subprocess.TimeoutExpired(["asc"], timeout)
        return self.stdout, "private diagnostic"


class ASCReadOnlyTests(unittest.TestCase):
    def _run(self, process: FakeProcess, terminated: list[int]) -> dict[str, object]:
        def popen(arguments: list[str], **kwargs: object) -> FakeProcess:
            self.assertEqual(arguments[:4], ["asc", "--profile", "primary", "--strict-auth"])
            self.assertTrue(kwargs["start_new_session"])
            self.assertEqual(kwargs["env"]["ASC_TELEMETRY_DISABLED"], "1")  # type: ignore[index]
            return process

        return module.run_json(
            ["apps", "list", "--output", "json"],
            "primary",
            30,
            popen=popen,
            terminate=lambda candidate: terminated.append(candidate.pid),
        )

    def test_valid_object_returns_without_termination(self) -> None:
        terminated: list[int] = []
        self.assertEqual(self._run(FakeProcess(stdout=json.dumps({"data": []})), terminated), {"data": []})
        self.assertEqual(terminated, [])

    def test_timeout_terminates_the_whole_process_group_and_redacts_details(self) -> None:
        terminated: list[int] = []
        with self.assertRaisesRegex(module.ASCReadError, "timed out") as context:
            self._run(FakeProcess(timeout=True), terminated)
        self.assertEqual(terminated, [1234])
        self.assertEqual(context.exception.args, ("App Store Connect read timed out",))

    def test_failure_and_invalid_json_are_sanitized(self) -> None:
        with self.assertRaisesRegex(module.ASCReadError, "read failed"):
            self._run(FakeProcess(returncode=2), [])
        with self.assertRaisesRegex(module.ASCReadError, "invalid JSON"):
            self._run(FakeProcess(stdout="private-token-or-error"), [])
        with self.assertRaisesRegex(module.ASCReadError, "root must be an object"):
            self._run(FakeProcess(stdout="[]"), [])

    def test_timeout_must_be_positive_before_launch(self) -> None:
        with self.assertRaisesRegex(module.ASCReadError, "positive"):
            module.run_json([], "primary", 0)


if __name__ == "__main__":
    unittest.main()
