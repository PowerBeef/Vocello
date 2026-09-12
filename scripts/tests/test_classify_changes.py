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


if __name__ == "__main__":
    unittest.main()
