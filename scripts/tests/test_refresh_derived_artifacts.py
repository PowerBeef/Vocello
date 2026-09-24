"""Derived-artifact registry (scripts/refresh_derived_artifacts.py): validate checks what it registers."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("refresh_derived_artifacts", ROOT / "scripts/refresh_derived_artifacts.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE  # the registry's dataclass resolves its module while loading
SPEC.loader.exec_module(MODULE)


class ValidateAllTests(unittest.TestCase):
    def validate(self, failing: tuple[str, ...] | None = None) -> tuple[int, list[tuple[str, ...]]]:
        calls: list[tuple[str, ...]] = []

        def fake_run(command: tuple[str, ...], *, cwd: Path) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            code = 1 if command == failing else 0
            return subprocess.CompletedProcess(list(command), code, stdout="", stderr="stale" if code else "")

        with mock.patch.object(MODULE, "run_command", side_effect=fake_run), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = MODULE.validate_all(ROOT)
        return code, calls

    def test_every_registered_artifact_is_validated_once(self) -> None:
        # PA-06: validate used to skip the README charts its registry lists.
        code, calls = self.validate()
        self.assertEqual(code, 0)
        registered = [artifact.check for artifact in MODULE.ARTIFACTS]
        self.assertEqual(set(calls), set(registered))
        self.assertEqual(len(calls), len(set(registered)), "a shared check runs once")
        ids = {artifact.artifact_id for artifact in MODULE.ARTIFACTS}
        self.assertTrue({"readme-charts", "third-party-attributions"} <= ids, ids)

    def test_the_first_stale_artifact_fails_closed(self) -> None:
        charts = next(a.check for a in MODULE.ARTIFACTS if a.artifact_id == "readme-charts")
        code, calls = self.validate(failing=charts)
        self.assertEqual(code, 1)
        self.assertEqual(calls[-1], charts)


if __name__ == "__main__":
    unittest.main()
