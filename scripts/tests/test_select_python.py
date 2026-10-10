"""Installed Python discovery and child propagation do not change host settings."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("select_python", ROOT / "scripts/select_python.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PythonSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vocello python selection ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir()
        self.pins = {"pytest": "9.1.1", "pytest-xdist": "3.8.0", "numpy": "2.4.6"}
        (self.root / "config/toolchain.json").write_text(json.dumps({"native": {name: {"version": pin} for name, pin in self.pins.items()}}))

    def test_prefers_pinned_installed_environment_to_incomplete_ambient(self):
        reports = {"/system/python3": None, "/ordinary/python3": {"packages": {}}, "/installed/python3": {"packages": self.pins}}
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(MODULE, "installed_candidates", return_value=iter(reports)), \
                mock.patch.object(MODULE, "inspect_python", side_effect=reports.get):
            self.assertEqual(MODULE.select_python(self.root), "/installed/python3")

    def test_no_packages_still_allows_readonly_workflow(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(MODULE, "installed_candidates", return_value=iter(["/ci/python3"])), \
                mock.patch.object(MODULE, "inspect_python", return_value={"packages": {}}):
            self.assertEqual(MODULE.select_python(self.root), "/ci/python3")

    def test_explicit_override_never_falls_back(self):
        for override in ("", "/missing/python3"):
            with self.subTest(override=override), mock.patch.dict(os.environ, {"VOCELLO_PYTHON": override}), \
                    mock.patch.object(MODULE.shutil, "which", return_value=None), \
                    mock.patch.object(MODULE, "installed_candidates", side_effect=AssertionError("must not fall back")):
                with self.assertRaisesRegex(ValueError, "no fallback"):
                    MODULE.select_python(self.root)

    def test_probe_rejects_old_malformed_and_failed_interpreters(self):
        for code, output in ((0, '{"version":[3,9],"packages":{}}'), (0, "not json"), (0, '[]'), (0, '{"version":["3","14"],"packages":{}}'), (1, "")):
            with self.subTest(code=code, output=output), mock.patch.object(MODULE.subprocess, "run", return_value=subprocess.CompletedProcess([], code, output)):
                self.assertIsNone(MODULE.inspect_python("fake"))

    def test_path_candidate_can_be_probed_without_importing_test_packages(self):
        fake = self.root / "bin/python3"
        fake.parent.mkdir()
        fake.write_text("#!/bin/sh\nprintf '%s\\n' '" + json.dumps({"version": [3, 14], "packages": self.pins}) + "'\n")
        fake.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": str(fake.parent)}, clear=True):
            self.assertEqual(MODULE.select_python(self.root), str(fake))

    def test_versioned_override_with_spaces_propagates_to_shell_python3(self):
        override = self.root / "custom python3.14"
        override.symlink_to(sys.executable)
        environment = {**os.environ, "VOCELLO_PYTHON": str(override), "PATH": str(ROOT / "scripts/lib/python-bin") + os.pathsep + os.environ["PATH"]}
        selected = subprocess.run([sys.executable, str(ROOT / "scripts/select_python.py")], env=environment, text=True, capture_output=True, check=True)
        self.assertEqual(selected.stdout.strip(), str(override))
        completed = subprocess.run(["bash", "-c", "python3 -c 'import sys; print(sys.executable)'"], env=environment, text=True, capture_output=True, check=True)
        self.assertEqual(Path(completed.stdout.strip()).resolve(), Path(sys.executable).resolve())

    def test_dev_doctor_uses_override_and_rejects_invalid_override(self):
        environment = {**os.environ, "VOCELLO_PYTHON": sys.executable}
        result = subprocess.run([str(ROOT / "scripts/dev.sh"), "doctor", "--json"], env=environment, text=True, capture_output=True, check=True)
        self.assertEqual(Path(json.loads(result.stdout)["pythonSelection"]["executable"]).resolve(), Path(sys.executable).resolve())
        result = subprocess.run([str(ROOT / "scripts/dev.sh"), "doctor", "--json"], env={**environment, "VOCELLO_PYTHON": "/missing/python3"}, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("VOCELLO_PYTHON", result.stderr)
