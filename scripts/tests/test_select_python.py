"""Installed Python discovery and child propagation do not change host settings."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from shell_stubs import LaneShell, ui_lane_sandbox

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

    def test_relative_override_and_relative_path_survive_child_directory_change(self):
        executable = self.root.resolve() / "bin/python3"
        executable.parent.mkdir()
        executable.symlink_to(sys.executable)
        for override in ("bin/python3", "python3"):
            with self.subTest(override=override):
                environment = {**os.environ, "VOCELLO_PYTHON": override,
                               "PATH": "bin" + os.pathsep + os.environ["PATH"]}
                selected = subprocess.run([sys.executable, str(ROOT / "scripts/select_python.py")],
                                          cwd=self.root, env=environment, text=True, capture_output=True, check=True)
                self.assertEqual(selected.stdout.strip(), str(executable))
                environment.update(VOCELLO_PYTHON=selected.stdout.strip(),
                                   PATH=str(ROOT / "scripts/lib/python-bin") + os.pathsep + os.environ["PATH"])
                completed = subprocess.run(["bash", "-c", "python3 -c 'import sys; print(sys.executable)'"],
                                           cwd=ROOT, env=environment, text=True, capture_output=True, check=True)
                self.assertEqual(Path(completed.stdout.strip()).resolve(), executable.resolve())

    def test_nested_shim_rejects_self_reference_without_recursion(self):
        environment = {**os.environ, "VOCELLO_PYTHON": "python3",
                       "PATH": str(ROOT / "scripts/lib/python-bin") + os.pathsep + os.environ["PATH"]}
        result = subprocess.run([str(ROOT / "scripts/lib/python-bin/python3"), "--version"],
                                env=environment, text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertIn("repository shim", result.stderr)


class SharedShellSelectionTests(unittest.TestCase):
    """scripts/lib/python.sh puts a shell and its children on the selected interpreter."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="vocello shell python ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.log = self.root / "interpreter.log"
        # The stand-in for an installed interpreter with the test packages: it records every
        # call on one line, answers `-m pytest` itself and hands everything else to the real Python.
        self.selected = self.root / "selected python3"
        self.selected.write_text(
            "#!/bin/sh\n"
            f"printf '%s\\n' \"$(printf '%s' \"$*\" | tr '\\n' ' ')\" >> {shlex.quote(str(self.log))}\n"
            "if [ \"$1\" = \"-m\" ]; then exit 0; fi\n"
            f"exec {shlex.quote(sys.executable)} \"$@\"\n")
        self.selected.chmod(0o755)
        self.environment = {name: value for name, value in os.environ.items()
                            if name not in {"CI", "GITHUB_ACTIONS", "QVOICE_GATES", "VOCELLO_PYTHON"}}
        # The shell's own python3 is the test's interpreter, never the shim of an outer dev.sh.
        ambient = self.root / "ambient"
        ambient.mkdir()
        (ambient / "python3").symlink_to(sys.executable)
        shim = str(ROOT / "scripts/lib/python-bin")
        self.environment["PATH"] = os.pathsep.join(
            [str(ambient)] + [part for part in os.environ["PATH"].split(os.pathsep) if part != shim])

    def calls(self):
        return [line for line in self.log.read_text().splitlines() if not line.startswith("-c import ")]

    def source(self, body, **environment):
        script = f". {shlex.quote(str(ROOT / 'scripts/lib/python.sh'))}\n{body}"
        return subprocess.run(["bash", "-euo", "pipefail", "-c", script], text=True, capture_output=True,
                              env={**self.environment, **environment}, timeout=30)

    def test_selects_exports_and_puts_the_shim_first_once(self):
        result = self.source(
            f"vocello_use_selected_python {shlex.quote(str(ROOT))}\n"
            f"vocello_use_selected_python {shlex.quote(str(ROOT))}\n"
            "printf '%s\\n' \"$VOCELLO_PYTHON\" \"$(command -v python3)\" \"$PATH\"\n"
            "python3 -c 'print(40 + 2)'\n",
            VOCELLO_PYTHON=str(self.selected))
        self.assertEqual(result.returncode, 0, result.stderr)
        selected, resolved, path, answer = result.stdout.splitlines()
        shim = str(ROOT / "scripts/lib/python-bin")
        self.assertEqual(selected, str(self.selected))
        self.assertEqual(resolved, shim + "/python3")
        self.assertEqual(path.split(os.pathsep).count(shim), 1)
        self.assertEqual(answer, "42")
        # The second selection already runs through the shim, on the selected interpreter.
        self.assertEqual(self.calls(), [f"{ROOT}/scripts/select_python.py", "-c print(40 + 2)"])

    def test_a_refused_selection_stops_the_caller(self):
        result = self.source(
            f"vocello_use_selected_python {shlex.quote(str(ROOT))}\necho reached\n",
            VOCELLO_PYTHON=str(self.root / "missing python3"))
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("reached", result.stdout)
        self.assertIn("VOCELLO_PYTHON", result.stderr)

    def test_the_library_refuses_to_be_executed(self):
        result = subprocess.run(["bash", str(ROOT / "scripts/lib/python.sh")], text=True, capture_output=True,
                                env=self.environment, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be sourced", result.stderr)

    def gate_sandbox(self):
        """The shipped gate beside stand-ins for the validators and the workflow."""
        sandbox = self.root / "repository"
        for relative in ("scripts/check_project_inputs.sh", "scripts/select_python.py", "scripts/lib/python.sh",
                         "scripts/lib/python-bin/python3", "config/toolchain.json"):
            target = sandbox / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(ROOT / relative)
        for relative in ("scripts/lib/contract_gate.py", "scripts/development_workflow.py"):
            (sandbox / relative).write_text("")
        return sandbox

    def test_the_gate_runs_validators_and_the_suite_on_the_selected_interpreter(self):
        # B3: the release preflight calls the gate without scripts/dev.sh, from a shell whose
        # bare python3 has no pytest.
        sandbox = self.gate_sandbox()
        gate = str(sandbox / "scripts/check_project_inputs.sh")
        for arguments, expected in (
                ([], [f"{sandbox}/scripts/lib/contract_gate.py", "-m pytest -n auto"]),
                (["--local"], [f"{sandbox}/scripts/lib/contract_gate.py --local",
                               f"{sandbox}/scripts/development_workflow.py py"]),
                (["--python", "none"], [f"{sandbox}/scripts/lib/contract_gate.py"])):
            with self.subTest(arguments=arguments):
                self.log.write_text("")
                result = subprocess.run(["bash", gate, *arguments], text=True, capture_output=True, timeout=60,
                                        env={**self.environment, "VOCELLO_PYTHON": str(self.selected)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.calls(), expected)

    def test_the_gate_stops_before_any_validator_when_no_interpreter_is_selected(self):
        sandbox = self.gate_sandbox()
        result = subprocess.run(["bash", str(sandbox / "scripts/check_project_inputs.sh")], text=True,
                                capture_output=True, timeout=60,
                                env={**self.environment, "VOCELLO_PYTHON": str(self.root / "missing python3")})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Validating", result.stdout)
        self.assertIn("VOCELLO_PYTHON", result.stderr)

    def test_dev_qc_runs_on_the_selected_interpreter(self):
        result = subprocess.run([str(ROOT / "scripts/dev.sh"), "qc", "--help"], text=True,
                                capture_output=True, timeout=60,
                                env={**self.environment, "VOCELLO_PYTHON": str(self.selected)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(call.endswith("/scripts/qc.py --help") for call in self.calls()), self.calls())

    def test_native_lanes_select_python_and_accept_lead_only(self):
        for script, subcommand, stub in (
                ("macos_test.sh", "preflight", "cmd_preflight"),
                ("ios_device.sh", "preflight", "cmd_preflight"),
        ):
            with self.subTest(script=script):
                shell = LaneShell(self, script)
                result = shell.run(
                    f"qv_stub vocello_use_selected_python\n"
                    f"qv_stub {stub}\n"
                    f"main --lead-only {subcommand}\n"
                    'printf "QVOICE_LEAD_ONLY=%s\\n" "${QVOICE_LEAD_ONLY:-}"\n'
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("QVOICE_LEAD_ONLY=1", result.stdout)
                self.assertTrue(shell.calls_to("vocello_use_selected_python"), shell.calls())
                self.assertTrue(shell.calls_to(stub), shell.calls())

        sandbox = ui_lane_sandbox(self)
        completed = sandbox.run_script("--lead-only", "macos", "smoke")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("QwenVoice.xcodeproj", completed.stderr)
        self.assertTrue(sandbox.calls_to("vocello_use_selected_python"), sandbox.calls())
