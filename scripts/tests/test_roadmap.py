#!/usr/bin/env python3
"""Unit tests for scripts/roadmap.py.

The accuracy tests matter most. A tracker where `status: done` is a
self-assertion is worse than no tracker, because it looks like evidence. Each
test below is one way an item could claim completion it has not earned.
"""
import copy
import datetime
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import roadmap  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

MINIMAL = {
    "schemaVersion": 1,
    "plans": [{
        "id": "p1", "title": "Plan one", "status": "active",
        "owner": "backend-mlx", "adopted": "2026-08-01", "goal": "do a thing",
    }],
    "items": [{
        "id": "A-1", "plan": "p1", "title": "an item", "status": "planned",
        "updated": "2026-08-02",
    }],
}
TODAY = datetime.date(2026, 8, 2)


class Harness(unittest.TestCase):
    """Validates a synthetic roadmap against the real repo, so evidence
    resolution runs against real commits, records, and docs."""

    def check(self, mutate=None):
        data = copy.deepcopy(MINIMAL)
        if mutate:
            mutate(data)
        directory = pathlib.Path(tempfile.mkdtemp())
        (directory / "config").mkdir()
        (directory / "config" / "roadmap.json").write_text(json.dumps(data))
        # Evidence must resolve against the real tree; only the data is synthetic.
        real = REPO_ROOT / "config" / "roadmap.json"
        backup = real.read_text(encoding="utf-8")
        real.write_text(json.dumps(data), encoding="utf-8")
        try:
            return roadmap.validate(REPO_ROOT, today=TODAY)
        finally:
            real.write_text(backup, encoding="utf-8")

    def errors_from(self, mutate):
        return " | ".join(self.check(mutate)["errors"])


class AccuracyTests(Harness):
    def _done_with(self, evidence):
        def mutate(data):
            data["items"][0].update(status="done", evidence=evidence)
            # A second live item, so the plan does not trip the separate
            # "active but every item is finished" contradiction and mask the
            # evidence result these tests are actually about.
            data["items"].append({"id": "A-9", "plan": "p1", "title": "still open",
                                  "status": "planned", "updated": "2026-08-02"})
        return mutate

    def test_a_baseline_roadmap_passes(self):
        self.assertTrue(self.check()["ok"])

    def test_done_cannot_be_a_bare_assertion(self):
        self.assertIn("done requires evidence", self.errors_from(self._done_with([])))

    def test_a_fabricated_commit_is_caught(self):
        self.assertIn("commit does not exist",
                      self.errors_from(self._done_with(["commit:deadbee"])))

    def test_a_real_commit_passes(self):
        # The commit that introduced this file's subject matter.
        self.assertTrue(self.check(self._done_with(["commit:c14651c"]))["ok"])

    def test_a_missing_benchmark_record_is_caught(self):
        self.assertIn("benchmark record not found",
                      self.errors_from(self._done_with(["benchmark:not-a-real-run"])))

    def test_a_missing_doc_is_caught(self):
        self.assertIn("doc not found",
                      self.errors_from(self._done_with(["doc:docs/nope.md"])))

    def test_a_missing_anchor_is_caught(self):
        self.assertIn("anchor #nope not found", self.errors_from(
            self._done_with(["doc:docs/reference/qwen3-tts-guide.md#nope"])))

    def test_a_real_anchor_passes(self):
        self.assertTrue(self.check(self._done_with(
            ["doc:docs/reference/qwen3-tts-guide.md#5-generation-modes"]))["ok"])

    def test_an_unknown_evidence_kind_is_rejected(self):
        self.assertIn("unknown evidence kind",
                      self.errors_from(self._done_with(["vibes:it-feels-done"])))

    def test_evidence_must_be_kind_prefixed(self):
        self.assertIn("evidence must be", self.errors_from(self._done_with(["c14651c"])))


class ObligationTests(Harness):
    def test_declined_requires_a_reason(self):
        self.assertIn("declined requires a reason",
                      self.errors_from(lambda d: d["items"][0].update(status="declined")))

    def test_parked_requires_unpark_conditions(self):
        self.assertIn("parked requires unparkWhen",
                      self.errors_from(lambda d: d["items"][0].update(status="parked")))

    def test_superseded_requires_a_pointer(self):
        self.assertIn("superseded requires supersededBy",
                      self.errors_from(lambda d: d["items"][0].update(status="superseded")))

    def test_an_unknown_status_is_rejected(self):
        self.assertIn("status must be one of",
                      self.errors_from(lambda d: d["items"][0].update(status="mostly-done")))


class IntegrityTests(Harness):
    def test_primary_plan_must_exist(self):
        self.assertIn("primaryPlan must reference an existing plan",
                      self.errors_from(lambda d: d.update(primaryPlan="missing")))

    def test_primary_plan_must_be_active(self):
        def mutate(data):
            data["primaryPlan"] = "p1"
            data["plans"][0]["status"] = "parked"
        self.assertIn("primaryPlan must reference an active plan", self.errors_from(mutate))

    def test_primary_plan_rejects_invalid_type(self):
        self.assertIn("primaryPlan must reference an existing plan",
                      self.errors_from(lambda d: d.update(primaryPlan=[])))

    def _two_items(self, data):
        data["items"].append({"id": "A-2", "plan": "p1", "title": "second",
                              "status": "planned", "updated": "2026-08-02"})

    def test_work_cannot_start_before_its_blocker_finishes(self):
        def mutate(data):
            self._two_items(data)
            data["items"][1].update(status="in-flight", blockedBy=["A-1"])
        self.assertIn("but its blocker A-1 is planned", self.errors_from(mutate))

    def test_work_may_start_once_its_blocker_is_done(self):
        def mutate(data):
            self._two_items(data)
            data["items"][0].update(status="done", evidence=["commit:c14651c"])
            data["items"][1].update(status="in-flight", blockedBy=["A-1"])
        self.assertTrue(self.check(mutate)["ok"])

    def test_an_unknown_blocker_is_caught(self):
        self.assertIn("blockedBy unknown item",
                      self.errors_from(lambda d: d["items"][0].update(blockedBy=["ghost"])))

    def test_a_dependency_cycle_is_caught(self):
        def mutate(data):
            self._two_items(data)
            data["items"][0]["blockedBy"] = ["A-2"]
            data["items"][1]["blockedBy"] = ["A-1"]
        self.assertIn("cycle", self.errors_from(mutate))

    def test_duplicate_ids_are_caught(self):
        def mutate(data):
            data["items"].append(dict(data["items"][0]))
        self.assertIn("duplicate item id", self.errors_from(mutate))

    def test_a_legacy_id_cannot_be_claimed_twice(self):
        def mutate(data):
            self._two_items(data)
            data["items"][0]["legacyIds"] = ["Stage 1"]
            data["items"][1]["legacyIds"] = ["Stage 1"]
        self.assertIn("already claimed", self.errors_from(mutate))

    def test_a_complete_plan_cannot_hold_live_work(self):
        self.assertIn("holds 1 unfinished item",
                      self.errors_from(lambda d: d["plans"][0].update(status="complete")))

    def test_an_active_plan_whose_work_is_finished_is_a_contradiction(self):
        def mutate(data):
            data["items"][0].update(status="done", evidence=["commit:c14651c"])
        self.assertIn("active but every item is finished", self.errors_from(mutate))


class StalenessTests(Harness):
    def test_a_long_untouched_in_flight_item_is_surfaced(self):
        report = self.check(lambda d: d["items"][0].update(
            status="in-flight", updated="2026-06-01"))
        self.assertTrue(any("untouched for" in w for w in report["warnings"]))
        self.assertTrue(report["ok"], "staleness surfaces, it does not block")

    def test_a_recently_touched_in_flight_item_is_quiet(self):
        report = self.check(lambda d: d["items"][0].update(
            status="in-flight", updated="2026-08-01"))
        self.assertEqual(report["warnings"], [])

    def test_a_done_item_whose_source_moved_afterwards_is_surfaced(self):
        report = self.check(lambda d: d["items"][0].update(
            status="done", evidence=["commit:c14651c"], updated="2026-01-01",
            sourceOfTruth=["Sources/QwenVoiceCore/EmotionPreset.swift"]))
        self.assertTrue(any("confirm the completion still holds" in w
                            for w in report["warnings"]))


class ProgressTests(unittest.TestCase):
    def test_primary_plan_is_first_in_status_and_render_without_hiding_other_plans(self):
        data = copy.deepcopy(MINIMAL)
        data["plans"].append(dict(data["plans"][0], id="z-primary", title="Primary programme"))
        data["items"].append(dict(data["items"][0], id="RF-01", plan="z-primary"))
        data["primaryPlan"] = "z-primary"
        with mock.patch.object(roadmap, "load", return_value=data):
            self.assertEqual([p["id"] for p in roadmap.progress(REPO_ROOT)["plans"]],
                             ["z-primary", "p1"])
            rendered = roadmap.render(REPO_ROOT)
        self.assertIn("Current execution plan: Primary programme", rendered)
        self.assertLess(rendered.index("## Primary programme"), rendered.index("## Plan one"))
        self.assertIn("`A-1`", rendered)
        self.assertIn("`RF-01`", rendered)

    def test_the_shipped_roadmap_is_valid_and_tracks_several_plans(self):
        report = roadmap.validate(REPO_ROOT)
        self.assertTrue(report["ok"], "; ".join(report["errors"]))
        summary = roadmap.progress(REPO_ROOT)
        self.assertGreaterEqual(len(summary["plans"]), 2,
                                "the system exists to track several plans")
        active = [p for p in summary["plans"] if p["status"] == "active"]
        self.assertGreaterEqual(len(active), 1,
                                "at least one plan should be in flight")
        for plan in summary["plans"]:
            if plan["items"]:
                self.assertIsNotNone(plan["percent"])

    def test_the_rendered_view_matches_the_source(self):
        text = (REPO_ROOT / "docs" / "ROADMAP.md").read_text(encoding="utf-8")
        self.assertEqual(text, roadmap.render(REPO_ROOT),
                         "docs/ROADMAP.md is stale; run: python3 scripts/roadmap.py render")


if __name__ == "__main__":
    unittest.main()
