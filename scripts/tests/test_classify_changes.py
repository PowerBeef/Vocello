"""CI lane routing (scripts/ci/classify_changes.py): per-lane green bases, not the previous push."""

from __future__ import annotations

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("classify_changes", ROOT / "scripts/ci/classify_changes.py")
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def git(cwd: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=cwd, capture_output=True, text=True, check=True,
        env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
             "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
             "HOME": str(cwd), "PATH": "/usr/bin:/bin"},
    ).stdout.strip()


class RoutingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repo = Path(self.temp.name)
        git(self.repo, "init", "-q", "-b", "main")
        self.shas = {}
        self.commit("c0", "README.md")
        self.commit("c1", "Sources/Services/Thing.swift")   # macOS-only Swift
        self.commit("c2", "scripts/tool.py")                 # Python and Swift lanes
        self.commit("c3", "docs/note.md")                    # docs only
        self.head = self.shas["c3"]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def commit(self, name: str, path: str) -> None:
        target = self.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(name + "\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", name)
        self.shas[name] = git(self.repo, "rev-parse", "HEAD")

    def history(self, **passed_at: str) -> list[dict]:
        """One completed run per named commit, with the given job conclusions."""
        runs = []
        for name, jobs in passed_at.items():
            runs.append({"headSha": self.shas[name], "conclusion": "success",
                         "jobs": {MODULE.LANE_JOBS[lane]: "success" for lane in jobs.split(",") if lane}})
        return runs

    def test_docs_only_push_still_runs_the_lanes_a_cancelled_run_owed(self) -> None:
        # Swift last passed at c0, Python at c2 (the c1/c2 push was cancelled for Swift).
        history = [
            {"headSha": self.shas["c2"], "conclusion": "cancelled",
             "jobs": {MODULE.LANE_JOBS["python"]: "success", MODULE.LANE_JOBS["swift"]: "cancelled"}},
            *self.history(c0="swift,ios,python,website"),
        ]
        lanes, reason = MODULE.route_push(self.head, self.shas["c2"], history, cwd=str(self.repo))
        self.assertTrue(lanes["swift"], reason)
        self.assertFalse(lanes["ios"], reason)        # Sources/Services is macOS-only
        self.assertFalse(lanes["python"], reason)     # nothing Python since c2
        self.assertFalse(lanes["website"], reason)
        self.assertFalse(lanes["workflows"], reason)

    def test_previous_push_routing_would_have_skipped_everything(self) -> None:
        lanes, _ = MODULE.route_push(self.head, self.shas["c2"], None, cwd=str(self.repo))
        self.assertFalse(any(lanes[lane] for lane in ("swift", "ios", "python", "website")))

    def test_a_lane_with_no_prior_green_run_always_runs(self) -> None:
        history = self.history(c2="python")
        lanes, reason = MODULE.route_push(self.head, self.shas["c2"], history, cwd=str(self.repo))
        self.assertTrue(lanes["swift"] and lanes["ios"] and lanes["website"], reason)
        self.assertFalse(lanes["python"], reason)

    def test_history_heads_that_are_not_ancestors_are_ignored(self) -> None:
        history = [{"headSha": "f" * 40, "conclusion": "success",
                    "jobs": {job: "success" for job in MODULE.LANE_JOBS.values()}}]
        lanes, _ = MODULE.route_push(self.head, "", history, cwd=str(self.repo))
        self.assertTrue(all(lanes[lane] for lane in ("swift", "ios", "python", "website")))

    def test_unknowable_diff_without_history_runs_everything(self) -> None:
        lanes, reason = MODULE.route_push(self.head, "0" * 40, None, cwd=str(self.repo))
        self.assertTrue(all(lanes.values()), reason)

    def test_workflow_changes_force_the_native_lanes(self) -> None:
        self.commit("c4", ".github/workflows/ci.yml")
        history = self.history(c3="swift,ios,python,website")
        lanes, _ = MODULE.route_push(self.shas["c4"], self.shas["c3"], history, cwd=str(self.repo))
        self.assertTrue(lanes["workflows"] and lanes["swift"] and lanes["ios"] and lanes["python"])

    def test_a_stale_website_base_never_forces_native_lanes(self) -> None:
        # The PR template changed at c4; every native lane passed there, but the
        # website lane last ran at c0. A docs push at c5 must not rerun the Mac lanes.
        self.commit("c4", ".github/pull_request_template.md")
        self.commit("c5", "docs/other.md")
        history = self.history(c4="swift,ios,python", c0="website")
        lanes, reason = MODULE.route_push(self.shas["c5"], self.shas["c4"], history, cwd=str(self.repo))
        for lane in ("swift", "ios", "python", "workflows", "website"):
            self.assertFalse(lanes[lane], f"{lane}: {reason}")

    def test_a_workflow_change_already_proven_by_a_lanes_green_base_does_not_rerun_it(self) -> None:
        self.commit("c4", ".github/workflows/ci.yml")
        self.commit("c5", "docs/other.md")
        history = self.history(c4="swift", c2="python,ios")
        lanes, reason = MODULE.route_push(self.shas["c5"], self.shas["c4"], history, cwd=str(self.repo))
        self.assertFalse(lanes["swift"], reason)
        self.assertTrue(lanes["python"] and lanes["ios"] and lanes["workflows"], reason)

    def test_a_lane_skipped_inside_a_green_run_advances_its_base(self) -> None:
        skipped_green = [{"headSha": self.shas["c2"], "conclusion": "success",
                          "jobs": {MODULE.LANE_JOBS["website"]: "skipped", MODULE.LANE_JOBS["python"]: "success"}}]
        bases = MODULE.lane_bases(skipped_green, self.head, cwd=str(self.repo))
        self.assertEqual(bases["website"], self.shas["c2"])
        skipped_cancelled = [{"headSha": self.shas["c2"], "conclusion": "cancelled",
                              "jobs": {MODULE.LANE_JOBS["website"]: "skipped"}}]
        self.assertIsNone(MODULE.lane_bases(skipped_cancelled, self.head, cwd=str(self.repo))["website"])


class ClassificationTests(unittest.TestCase):
    def lanes(self, path: str) -> set[str]:
        return {lane for lane, on in MODULE.classify([path]).items() if on}

    def test_only_push_ci_inputs_are_workflow_changes(self) -> None:
        for path in (".github/pull_request_template.md", ".github/dependabot.yml", ".github/CODEOWNERS",
                     ".github/workflows/nightly.yml", ".github/workflows/release.yml"):
            self.assertNotIn("workflows", self.lanes(path), path)
            self.assertFalse(self.lanes(path) & {"swift", "ios"}, path)
        for path in (".github/workflows/ci.yml", ".github/actions/native-toolchain/action.yml",
                     "scripts/ci/classify_changes.py"):
            self.assertEqual(self.lanes(path) & {"workflows", "swift", "ios", "python"},
                             {"workflows", "swift", "ios", "python"}, path)
        self.assertEqual(self.lanes(".github/workflows/nightly.yml"), {"python"})

    def test_inert_paths_route_nowhere(self) -> None:
        for path in ("Packages/VocelloQwen3Core/README.md", "Packages/VocelloQwen3Core/UPSTREAM.md",
                     "benchmarks/OPTIMIZATION.md", "benchmarks/baseline-2026-05-30-06166f0.md",
                     "benchmarks/README.md", "docs/reference/cli.md", "CONTRIBUTING.md", ".claude/settings.json"):
            self.assertEqual(self.lanes(path), set(), path)
        self.assertEqual(self.lanes("config/roadmap.json"), {"python"})
        self.assertEqual(self.lanes("scripts/tests/test_foo.py"), {"python"})
        self.assertEqual(self.lanes("scripts/hooks/policy_guard.sh"), {"python"})
        self.assertEqual(self.lanes("Sources/Resources/qwenvoice_production_model_catalog.json"), {"swift", "python"})

    def test_compile_and_contract_inputs_still_route(self) -> None:
        expected = {
            "Packages/VocelloQwen3Core/Sources/MLXAudioTTS/X.swift": {"swift", "ios"},
            "Packages/VocelloQwen3Core/Package.resolved": {"swift", "ios"},
            "Packages/VocelloQwen3Core/Package.swift": {"swift", "ios"},
            "Packages/VocelloQwen3Core/SEMANTIC_DELTAS.json": {"swift"},
            "Sources/Resources/Localizable.xcstrings": {"swift", "ios", "python"},
            "Sources/iOS/TTSEngineStore.swift": {"swift", "ios"},
            "Sources/Views/ContentView.swift": {"swift"},
            "scripts/lib/build_cache.sh": {"swift", "ios", "python"},
            "scripts/lib/jsonio.py": {"swift", "python"},
            "scripts/tests/test_benchmark_history.py": {"swift", "python"},
            "scripts/tests/conftest.py": {"swift", "python"},
            "benchmarks/runs/ui-generation/x.json": {"swift", "python"},
            "benchmarks/schema-v3.json": {"swift", "python"},
            "README.md": {"swift"},
            "website/PRODUCT.md": {"swift", "website"},
            "config/toolchain.json": {"swift", "ios", "python"},
            "config/quality-promotion-contract.json": {"swift", "python"},
            "project.yml": {"swift", "ios", "python"},
            "QwenVoice.xcodeproj/project.pbxproj": {"swift", "ios"},
            "scripts/build_foundation_targets.sh": {"swift", "ios", "python"},
            "scripts/delivery_experiment_runner.py": {"swift", "python", "research"},
        }
        for path, lanes in expected.items():
            self.assertEqual(self.lanes(path), lanes, path)


if __name__ == "__main__":
    unittest.main()
