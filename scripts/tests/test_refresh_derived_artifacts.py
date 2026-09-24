"""Derived-artifact registry (scripts/refresh_derived_artifacts.py): what it registers is refreshed and validated."""

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



# The function each generator compares its committed artifact against. Replacing it
# makes that artifact stale without touching the tree, so its real check prints the
# real stale message. A new registration needs an entry here.
STALE_BUILDERS = {
    "vendor-current-inventory": ("make_current_inventory", {"stale": True}),
    "vendor-facade-api-baseline": ("make_facade_api_baseline", {"stale": True}),
    "model-catalog": ("build_catalog", {"stale": True}),
    "readme-charts": ("render_all", {"stale-chart.svg": "stale"}),
    "third-party-attributions": ("build", {"stale": True}),
    "roadmap-render": ("render", "stale\n"),
}


def load_generator(script: str):
    path = ROOT / script
    spec = importlib.util.spec_from_file_location(f"refresh_marker_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class StaleMarkerTests(unittest.TestCase):
    def test_each_generator_s_real_stale_message_carries_its_marker(self) -> None:
        # PA-06: the catalog marker named text its check never prints, so a stale
        # catalog read as an error and `dev.sh regen` refused to rebuild it.
        self.assertEqual(set(STALE_BUILDERS), {a.artifact_id for a in MODULE.ARTIFACTS})
        for artifact in MODULE.ARTIFACTS:
            with self.subTest(artifact=artifact.artifact_id):
                interpreter, script, *arguments = artifact.check
                self.assertEqual(interpreter, "python3")
                # The registered check runs in-process against the repository; it must be read-only.
                self.assertTrue({"--check", "validate"} & set(arguments), artifact.check)
                generator = load_generator(script)
                name, stale_value = STALE_BUILDERS[artifact.artifact_id]
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.object(generator, name, return_value=stale_value), \
                        mock.patch.object(sys, "argv", [script, *arguments]), \
                        redirect_stdout(stdout), redirect_stderr(stderr):
                    code = generator.main()
                result = subprocess.CompletedProcess(list(artifact.check), code, stdout.getvalue(), stderr.getvalue())
                self.assertNotEqual(code, 0)
                self.assertEqual(MODULE.classify(artifact, result), ("stale", "needs rebuild"), stderr.getvalue())


class FakeTree:
    """Artifact freshness driven through the registry's own commands."""

    def __init__(self, stale: set[str], dependents: dict[str, set[str]] | None = None) -> None:
        self.stale = set(stale)
        self.dependents = dependents or {}
        self.rebuilt: list[str] = []

    def run(self, command: tuple[str, ...], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        rebuilt = [a for a in MODULE.ARTIFACTS if a.rebuild == command]
        if rebuilt:
            for artifact in rebuilt:
                self.rebuilt.append(artifact.artifact_id)
                self.stale.discard(artifact.artifact_id)
                self.stale.update(self.dependents.get(artifact.artifact_id, set()))
            return subprocess.CompletedProcess(list(command), 0, stdout="", stderr="")
        messages = [
            f"error: {artifact.stale_markers[0]}"
            for artifact in MODULE.ARTIFACTS
            if artifact.check == command and artifact.artifact_id in self.stale
        ]
        return subprocess.CompletedProcess(list(command), 1 if messages else 0, stdout="", stderr="\n".join(messages))

    def main(self, *argv: str) -> int:
        with mock.patch.object(MODULE, "run_command", side_effect=self.run), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return MODULE.main(list(argv))


class RefreshTests(unittest.TestCase):
    def test_an_upstream_rebuild_that_stales_a_later_artifact_finishes_in_one_refresh(self) -> None:
        # PA-06: the attributions read the model catalog, so rebuilding a stale
        # catalog stales them; a status taken before any rebuild missed that and
        # the closing validate failed until a second refresh.
        tree = FakeTree({"model-catalog"}, {"model-catalog": {"third-party-attributions"}})
        self.assertEqual(tree.main("refresh"), 0)
        self.assertEqual(tree.rebuilt, ["model-catalog", "third-party-attributions"])
        self.assertEqual(tree.stale, set())

    def test_a_stale_facade_alone_is_refreshed_through_the_shared_vendor_check(self) -> None:
        # The inventory shares the facade's validate; the facade's stale line is not an inventory error.
        tree = FakeTree({"vendor-facade-api-baseline"})
        with mock.patch.object(MODULE, "run_command", side_effect=tree.run):
            rows = {artifact.artifact_id: state for artifact, state, _ in MODULE.check_status(ROOT)}
        self.assertEqual(rows["vendor-current-inventory"], "ok")
        self.assertEqual(rows["vendor-facade-api-baseline"], "stale")
        self.assertEqual(tree.main("refresh"), 0)
        self.assertEqual(tree.rebuilt, ["vendor-facade-api-baseline"])

    def test_an_unexplained_check_failure_stops_before_any_later_rebuild(self) -> None:
        tree = FakeTree({"roadmap-render"})
        catalog = next(a for a in MODULE.ARTIFACTS if a.artifact_id == "model-catalog")
        original = tree.run

        def run(command: tuple[str, ...], *, cwd: Path) -> subprocess.CompletedProcess[str]:
            if command == catalog.check:
                return subprocess.CompletedProcess(list(command), 1, stdout="", stderr="error: receipts are invalid")
            return original(command, cwd=cwd)

        tree.run = run  # type: ignore[method-assign]
        self.assertEqual(tree.main("refresh"), 1)
        self.assertEqual(tree.rebuilt, [])


if __name__ == "__main__":
    unittest.main()
