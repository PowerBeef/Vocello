#!/usr/bin/env python3
"""The contract gate runner: grouped output in a fixed order, failure propagation, and local selection."""

from __future__ import annotations

import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import contract_gate as gate  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
ROADMAP_ONLY = ["config/roadmap.json", "docs/ROADMAP.md", "docs/development-progress.md"]


class FixtureValidators:
    """Small Python scripts in a temporary directory, run as validators."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def make(self, name: str, body: str, *, inputs: tuple[str, ...] | None = None,
             heavy: bool = False) -> gate.Validator:
        script = self.directory / f"{name}.py"
        script.write_text("import pathlib, sys, time\n" + textwrap.dedent(body), encoding="utf-8")
        return gate.Validator((gate.PYTHON, os.fspath(script)), inputs, "" if inputs is not None else "fixture",
                              heavy)


class RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.fixtures = FixtureValidators(self.directory)

    def run_gate(self, validators: list[gate.Validator], **options) -> tuple[int, str]:
        out = io.BytesIO()
        code = gate.run(validators, root=self.directory, out=out, **options)
        return code, out.getvalue().decode()

    def test_output_is_grouped_in_declaration_order_while_validators_run_concurrently(self) -> None:
        marker = self.directory / "second-started"
        first = self.fixtures.make("first", f"""
            deadline = time.monotonic() + 20
            while not pathlib.Path({os.fspath(marker)!r}).exists():
                if time.monotonic() > deadline:
                    print("first: the second validator never ran beside me")
                    sys.exit(1)
                time.sleep(0.01)
            print("first: one")
            print("first: two", file=sys.stderr)
            print("first: three")
            """)
        second = self.fixtures.make("second", f"""
            pathlib.Path({os.fspath(marker)!r}).touch()
            print("second: done")
            """)
        third = self.fixtures.make("third", 'print("third: done")\n')

        code, output = self.run_gate([first, second, third], jobs=3)

        self.assertEqual(code, 0, output)
        lines = [line for line in output.splitlines() if not line.startswith("==> ")]
        self.assertEqual(lines, ["first: one", "first: two", "first: three", "second: done", "third: done"])

    def test_heavy_validators_start_first_without_moving_their_output(self) -> None:
        log = self.directory / "start-order"
        light = self.fixtures.make("light", f"""
            with open({os.fspath(log)!r}, "a") as handle:
                handle.write("light ")
            print("light output")
            """)
        heavy = self.fixtures.make("heavy", f"""
            with open({os.fspath(log)!r}, "a") as handle:
                handle.write("heavy ")
            print("heavy output")
            """, heavy=True)

        code, output = self.run_gate([light, heavy], jobs=1)

        self.assertEqual(code, 0, output)
        self.assertEqual(log.read_text().split(), ["heavy", "light"])
        self.assertLess(output.index("light output"), output.index("heavy output"))

    def test_a_failure_fails_the_gate_after_every_validator_ran(self) -> None:
        failing = self.fixtures.make("failing", 'print("broken contract", file=sys.stderr)\nsys.exit(3)\n')
        passing = self.fixtures.make("passing", 'print("passing: PASS")\n')

        code, output = self.run_gate([failing, passing], jobs=2)

        self.assertEqual(code, 1)
        self.assertIn("broken contract", output)
        self.assertIn("==> FAILED (exit 3, ", output)
        self.assertIn("passing: PASS", output)
        self.assertLess(output.index("broken contract"), output.index("passing: PASS"))
        self.assertIn(f"failed: {failing.name}", output)
        self.assertIn("1 failed", output)

    def test_a_validator_that_cannot_start_is_a_failure(self) -> None:
        missing = gate.Validator(("scripts/no-such-validator.sh",), None, "fixture")
        passing = self.fixtures.make("passing", 'print("passing: PASS")\n')

        code, output = self.run_gate([missing, passing])

        self.assertEqual(code, 1)
        self.assertIn("cannot run scripts/no-such-validator.sh", output)
        self.assertIn("passing: PASS", output)

    def test_non_local_runs_never_skip(self) -> None:
        unrelated = self.fixtures.make("unrelated", 'print("unrelated ran")\n', inputs=("elsewhere/",))

        code, output = self.run_gate([unrelated], changed=["config/roadmap.json"], local=False)

        self.assertEqual(code, 0, output)
        self.assertIn("unrelated ran", output)
        self.assertNotIn("local contract selection", output)

    def test_local_runs_skip_untouched_validators_and_say_so_once(self) -> None:
        touched = self.fixtures.make("touched", 'print("touched ran")\n', inputs=("config/roadmap.json",))
        untouched = self.fixtures.make("untouched", 'print("untouched ran")\n', inputs=("Sources/",))
        always = self.fixtures.make("always", 'print("always ran")\n')

        code, output = self.run_gate([touched, untouched, always], changed=["config/roadmap.json"], local=True)

        self.assertEqual(code, 0, output)
        self.assertIn("touched ran", output)
        self.assertIn("always ran", output)
        self.assertNotIn("untouched ran", output)
        notes = [line for line in output.splitlines() if line.startswith("==> local contract selection")]
        self.assertEqual(len(notes), 1, output)
        self.assertIn("skipped 1 of 3", notes[0])


class SelectionTests(unittest.TestCase):
    def ran(self, changed: list[str] | None, *, local: bool = True) -> set[str]:
        runs, _note = gate.select(gate.VALIDATORS, changed, local=local)
        return {validator.name for validator, chosen in zip(gate.VALIDATORS, runs) if chosen}

    def test_a_roadmap_only_change_runs_the_roadmap_and_the_whole_tree_checks_only(self) -> None:
        always = {validator.name for validator in gate.VALIDATORS if validator.inputs is None}
        self.assertEqual(self.ran(ROADMAP_ONLY), always | {"scripts/roadmap.py render --check"})
        for product in ("scripts/localization_contract.py validate", "scripts/entitlement_contract.py validate",
                        "scripts/model_catalog_contract.py validate", "scripts/qwen3_core_contract.py validate",
                        "scripts/benchmark_history.py validate --all"):
            self.assertNotIn(product, self.ran(ROADMAP_ONLY))

    def test_a_product_source_change_runs_the_validators_that_read_it(self) -> None:
        ran = self.ran(["Sources/iOS/Settings/SettingsScreen.swift"])
        for expected in ("scripts/localization_contract.py validate", "scripts/support_contact_contract.py validate",
                         "scripts/ios_storage_protection_policy.py validate", "scripts/check_qwen3_backend_only.sh"):
            self.assertIn(expected, ran)
        self.assertNotIn("scripts/benchmark_history.py validate --all", ran)
        self.assertNotIn("scripts/roadmap.py render --check", ran)

    def test_a_shared_module_change_runs_its_importers(self) -> None:
        ran = self.ran(["scripts/lib/jsonio.py"])
        for importer in ("scripts/attribution_manifest.py validate", "scripts/qwen3_core_contract.py validate",
                         "scripts/benchmark_history.py rebuild-index --check",
                         "scripts/quality_promotion.py validate-contract"):
            self.assertIn(importer, ran)

    def test_validators_without_inputs_always_run(self) -> None:
        unknown = gate.Validator(("scripts/a.sh",), None, "reads everything")
        mapped = gate.Validator(("scripts/b.sh",), ("scripts/b.sh",))
        runs, _note = gate.select([unknown, mapped], ["website/src/App.jsx"], local=True)
        self.assertEqual(runs, [True, False])

    def test_no_changed_path_information_runs_everything(self) -> None:
        everything = {validator.name for validator in gate.VALIDATORS}
        self.assertEqual(self.ran(None), everything)
        self.assertEqual(self.ran([]), everything)

    def test_a_change_to_the_gate_itself_runs_everything(self) -> None:
        everything = {validator.name for validator in gate.VALIDATORS}
        self.assertEqual(self.ran(["scripts/lib/contract_gate.py", *ROADMAP_ONLY]), everything)
        self.assertEqual(self.ran(["scripts/check_project_inputs.sh"]), everything)

    def test_non_local_selection_never_skips(self) -> None:
        runs, note = gate.select(gate.VALIDATORS, ROADMAP_ONLY, local=False)
        self.assertTrue(all(runs))
        self.assertEqual(note, "")

    def test_paths_match_whole_components_and_directories_contain_inputs(self) -> None:
        self.assertTrue(gate.touches("Sources/iOS/A.swift", ("Sources/iOS/",)))
        self.assertFalse(gate.touches("Sources/iOSSupport/A.swift", ("Sources/iOS/",)))
        self.assertTrue(gate.touches("project.yml", ("project.yml",)))
        self.assertFalse(gate.touches("project.yml.bak", ("project.yml",)))
        self.assertTrue(gate.touches("Sources", ("Sources/iOS/",)))
        self.assertTrue(gate.touches("config/", ("config/toolchain.json",)))


class DeclaredInputsTests(unittest.TestCase):
    """The map stays reviewable: every validator names why it always runs or what it reads."""

    def test_every_validator_script_exists(self) -> None:
        for validator in gate.VALIDATORS:
            script = validator.command[1] if validator.command[0] == gate.PYTHON else validator.command[0]
            self.assertTrue((ROOT / script).is_file(), script)

    def test_every_mapped_validator_reads_its_own_script(self) -> None:
        for validator in gate.VALIDATORS:
            if validator.inputs is None:
                continue
            script = validator.command[1] if validator.command[0] == gate.PYTHON else validator.command[0]
            self.assertIn(script, validator.inputs, validator.name)

    def test_validators_without_inputs_say_why(self) -> None:
        for validator in gate.VALIDATORS:
            if validator.inputs is None:
                self.assertTrue(validator.always.strip(), validator.name)

    def test_every_declared_input_exists(self) -> None:
        for validator in gate.VALIDATORS:
            for entry in validator.inputs or ():
                path = ROOT / entry
                exists = path.is_dir() if entry.endswith("/") else path.is_file()
                self.assertTrue(exists, f"{validator.name}: declared input {entry} does not exist")


class ChangedPathsTests(unittest.TestCase):
    def git(self, root: Path, *args: str) -> None:
        subprocess.run(["git", "-C", os.fspath(root), "-c", "user.name=Gate Test", "-c",
                        "user.email=gate@example.invalid", "-c", "commit.gpgsign=false", "-c",
                        "core.hooksPath=/dev/null", *args],
                       check=True, capture_output=True)

    def test_an_explicit_list_overrides_git(self) -> None:
        paths = gate.changed_paths(Path("/nonexistent"), {gate.CHANGED_PATHS_ENV: "b/c.json\n./a.txt\n\n  \n"})
        self.assertEqual(paths, ["a.txt", "b/c.json"])

    def test_the_dirty_tree_and_committed_work_since_a_ref(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.git(root, "init", "-q")
            (root / "old.txt").write_text("old\n")
            (root / "keep.txt").write_text("keep\n")
            self.git(root, "add", "old.txt", "keep.txt")
            self.git(root, "commit", "-q", "-m", "base")
            self.git(root, "tag", "base")
            (root / "committed.txt").write_text("committed\n")
            self.git(root, "add", "committed.txt")
            self.git(root, "commit", "-q", "-m", "later")
            self.git(root, "mv", "old.txt", "new.txt")  # a staged rename lists both sides
            (root / "keep.txt").write_text("changed\n")
            (root / "untracked.txt").write_text("new\n")

            self.assertEqual(gate.changed_paths(root, {}), ["keep.txt", "new.txt", "old.txt", "untracked.txt"])
            self.assertEqual(gate.changed_paths(root, {gate.CHANGED_SINCE_ENV: "base"}),
                             ["committed.txt", "keep.txt", "new.txt", "old.txt", "untracked.txt"])

    def test_outside_a_repository_there_is_no_information(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, \
                mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": os.path.dirname(temporary)}):
            self.assertIsNone(gate.changed_paths(Path(temporary), {}))


class CommandLineTests(unittest.TestCase):
    def test_local_selection_is_refused_in_ci(self) -> None:
        with mock.patch.dict(os.environ, {"CI": "true"}), mock.patch.object(gate, "run") as run:
            self.assertEqual(gate.main(["--local"]), 2)
        run.assert_not_called()

    def test_without_local_every_validator_is_handed_to_the_runner(self) -> None:
        with mock.patch.dict(os.environ, {gate.CHANGED_PATHS_ENV: "config/roadmap.json"}), \
                mock.patch.object(gate, "run", return_value=0) as run:
            self.assertEqual(gate.main([]), 0)
        self.assertEqual(run.call_args.kwargs["local"], False)
        self.assertIsNone(run.call_args.kwargs["changed"])


if __name__ == "__main__":
    unittest.main()
