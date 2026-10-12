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
import subprocess
import sys
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
        # Evidence must resolve against the real tree; only the data is
        # synthetic. Inject it through the loader rather than rewriting the
        # tracked config/roadmap.json: parallel test workers read that file
        # concurrently (ProgressTests), and an interrupted worker would leave
        # the repository dirty.
        with mock.patch.object(roadmap, "load", return_value=data):
            return roadmap.validate(REPO_ROOT, today=TODAY)

    def errors_from(self, mutate):
        return " | ".join(self.check(mutate)["errors"])

    ARCHIVE_RULE = "done items belong in"

    def errors_except_archive_rule(self, mutate):
        """A done item written into the synthetic open ledger trips the
        archive rule by design; these tests are about the other obligations."""
        return [e for e in self.check(mutate)["errors"] if self.ARCHIVE_RULE not in e]


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
        self.assertEqual(self.errors_except_archive_rule(self._done_with(["commit:c14651c"])), [])

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
        self.assertEqual(self.errors_except_archive_rule(self._done_with(
            ["doc:docs/reference/qwen3-tts-guide.md#5-generation-modes"])), [])

    def test_an_unknown_evidence_kind_is_rejected(self):
        self.assertIn("unknown evidence kind",
                      self.errors_from(self._done_with(["vibes:it-feels-done"])))

    def test_evidence_must_be_kind_prefixed(self):
        self.assertIn("evidence must be", self.errors_from(self._done_with(["c14651c"])))

    def test_a_lane_run_id_is_known_evidence(self):
        self.assertEqual(self.errors_except_archive_rule(self._done_with(
            ["run:macos-xcui-smoke-20260915-040350-f374335f", "commit:c14651c"])), [])


class ArchiveTests(Harness):
    """Moving a done item to the archive must not end its evidence checks."""

    def archived(self, **item):
        entry = {"id": "A-7", "plan": "p1", "title": "finished", "status": "done", "updated": "2026-08-01"}
        entry.update(item)
        with mock.patch.object(roadmap, "load_archive", return_value={"items": [entry]}):
            return " | ".join(self.check()["errors"])

    def test_an_archived_done_item_must_cite_evidence(self):
        self.assertIn("archived item A-7: done requires evidence", self.archived())
        self.assertIn("archived item A-7: done requires evidence", self.archived(evidence=[]))

    def test_archived_commits_and_benchmarks_resolve(self):
        self.assertIn("commit does not exist", self.archived(evidence=["commit:deadbee"]))
        self.assertIn("benchmark record not found", self.archived(evidence=["benchmark:not-a-real-run"]))
        self.assertEqual(self.archived(evidence=["commit:c14651c"]), "")

    def test_archived_files_and_docs_are_checked_for_shape_only(self):
        # Files and anchors move after an item closes; the claim stays what it was.
        self.assertEqual(self.archived(evidence=["file:Sources/Retired.swift", "doc:docs/gone.md#x",
                                                 "run:ios-xcui-smoke-1", "commit:c14651c"]), "")
        self.assertIn("known kind", self.archived(evidence=["vibes:it-feels-done"]))
        self.assertIn("known kind", self.archived(evidence=["c14651c"]))

    def test_declined_and_superseded_archive_items_need_no_evidence(self):
        self.assertEqual(self.archived(status="declined", reason="not needed"), "")

    def test_the_real_archive_passes(self):
        self.assertEqual(roadmap.validate_archive(REPO_ROOT), [])


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

    def test_a_done_item_may_not_remain_in_the_open_ledger(self):
        self.assertIn("done items belong in config/roadmap-archive.json",
                      self.errors_from(lambda d: d["items"][0].update(
                          status="done", evidence=["commit:c14651c"])))

    def test_a_missing_source_of_truth_path_is_caught(self):
        self.assertIn("sourceOfTruth not found: scripts/nope.py",
                      self.errors_from(lambda d: d["items"][0].update(
                          sourceOfTruth=["scripts/nope.py"])))

    def test_a_source_of_truth_directory_is_accepted(self):
        self.assertTrue(self.check(lambda d: d["items"][0].update(
            sourceOfTruth=["Sources/QwenVoiceCore", "scripts/roadmap.py"]))["ok"])

    def test_notes_over_the_cap_are_rejected(self):
        self.assertIn("notes exceed 1200 characters",
                      self.errors_from(lambda d: d["items"][0].update(notes="x" * 1201)))

    def test_notes_at_the_cap_pass(self):
        self.assertTrue(self.check(lambda d: d["items"][0].update(notes="x" * 1200))["ok"])

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
        self.assertEqual(self.errors_except_archive_rule(mutate), [])

    def test_a_done_blocker_in_the_archive_satisfies_its_dependent(self):
        def mutate(data):
            data["items"][0].update(id="A-2", status="in-flight", blockedBy=["A-1"])
        archive = {"items": [{"id": "A-1", "plan": "p1", "title": "finished", "status": "done",
                              "updated": "2026-08-01", "evidence": ["commit:c14651c"]}]}
        with mock.patch.object(roadmap, "load_archive", return_value=archive):
            report = self.check(mutate)
        self.assertTrue(report["ok"], "; ".join(report["errors"]))

    def test_a_planned_item_behind_a_parked_blocker_is_surfaced(self):
        def mutate(data):
            self._two_items(data)
            data["items"][0].update(status="parked", unparkWhen="a phone")
            data["items"][1].update(blockedBy=["A-1"])
        report = self.check(mutate)
        self.assertTrue(report["ok"])
        self.assertTrue(any("effectively parked behind A-1" in w for w in report["warnings"]))

    def test_a_parked_item_behind_a_parked_blocker_is_quiet(self):
        def mutate(data):
            self._two_items(data)
            data["items"][0].update(status="parked", unparkWhen="a phone")
            data["items"][1].update(status="parked", unparkWhen="A-1 unparks", blockedBy=["A-1"])
        self.assertEqual(self.check(mutate)["warnings"], [])

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

    def test_fourteen_days_is_the_in_flight_limit(self):
        fifteen = self.check(lambda d: d["items"][0].update(
            status="in-flight", updated=str(TODAY - datetime.timedelta(days=15))))
        self.assertTrue(any("untouched for 15 days" in w for w in fifteen["warnings"]))
        thirteen = self.check(lambda d: d["items"][0].update(
            status="in-flight", updated=str(TODAY - datetime.timedelta(days=13))))
        self.assertEqual(thirteen["warnings"], [])

    def test_a_done_item_whose_source_moved_afterwards_is_surfaced(self):
        report = self.check(lambda d: d["items"][0].update(
            status="done", evidence=["commit:c14651c"], updated="2026-01-01",
            sourceOfTruth=["Sources/QwenVoiceCore/EmotionPreset.swift"]))
        self.assertTrue(any("confirm the completion still holds" in w
                            for w in report["warnings"]))


class FocusTests(Harness):
    """The focus lock is what stops the primary plan from being handed to the
    newest problem: live work elsewhere, a silent primary-plan move, too much in
    flight and an unnamed commit after the freeze each fail validation."""

    LOCK = {"plan": "p1", "decided": "2026-08-02", "decision": "ship p1 first", "maxInFlight": 1}
    HASH_A, HASH_B = "a" * 40, "b" * 40

    def _focused(self, extra=None):
        def mutate(data):
            data["primaryPlan"] = "p1"
            data["focusLock"] = copy.deepcopy(self.LOCK)
            data["plans"].append(dict(data["plans"][0], id="p2", title="Plan two"))
            data["items"].append({"id": "B-1", "plan": "p2", "title": "elsewhere", "status": "parked",
                                  "unparkWhen": "after p1", "updated": "2026-08-02"})
            if extra:
                extra(data)
        return mutate

    def test_a_focused_roadmap_with_parked_work_elsewhere_passes(self):
        self.assertTrue(self.check(self._focused())["ok"])

    def test_live_work_outside_the_focus_plan_is_rejected(self):
        for status in ("planned", "in-flight"):
            with self.subTest(status=status):
                errors = self.errors_from(self._focused(lambda d, s=status: d["items"][1].update(status=s)))
                self.assertIn("B-1 is " + status + " outside the focus plan p1", errors)

    def test_moving_the_primary_plan_requires_rewriting_the_lock(self):
        errors = self.errors_from(self._focused(lambda d: d.update(primaryPlan="p2")))
        self.assertIn("focusLock.plan must equal primaryPlan", errors)

    def test_the_lock_records_a_dated_decision_and_a_cap(self):
        errors = self.errors_from(self._focused(
            lambda d: d["focusLock"].update(decided="soon", decision=" ", maxInFlight=0)))
        for text in ("focusLock.decided must be an ISO date", "must record the maintainer's decision",
                     "maxInFlight must be a positive integer"):
            self.assertIn(text, errors)

    def test_in_flight_work_in_the_focus_plan_is_capped(self):
        def two_in_flight(data):
            data["items"][0].update(status="in-flight")
            data["items"].append({"id": "A-2", "plan": "p1", "title": "second", "status": "in-flight",
                                  "updated": "2026-08-02"})
        self.assertIn("the focus lock allows 1", self.errors_from(self._focused(two_in_flight)))

    def _frozen(self, log, returncode=0, freeze=None, extra_item=None):
        def extra(data):
            data["focusLock"]["freeze"] = freeze or {"commit": "abc1234"}
            if extra_item:
                data["items"].append(extra_item)
        data = copy.deepcopy(MINIMAL)
        self._focused(extra)(data)
        result = subprocess.CompletedProcess([], returncode, stdout=log, stderr="")
        with mock.patch.object(roadmap, "load", return_value=data), \
                mock.patch.object(roadmap, "load_archive", return_value={"items": []}), \
                mock.patch.object(roadmap, "_git", return_value=result) as git:
            report = roadmap.validate(REPO_ROOT, today=TODAY)
        report["git_calls"] = git.call_args_list
        return report

    def test_after_the_freeze_every_commit_names_a_focus_item(self):
        log = (f"{self.HASH_A}\x00fix(engine): settle A-1 before submission\x1e\n"
               f"{self.HASH_B}\x00docs: tidy the README\x1e\n")
        report = self._frozen(log)
        self.assertEqual(len(report["errors"]), 1, report["errors"])
        self.assertIn("commit bbbbbbbbbb after the freeze names no item of the focus plan in its subject: "
                      "docs: tidy the README", report["errors"][0])

    def test_only_the_subject_is_read(self):
        """An id mentioned in passing in a body does not make a commit release work."""
        report = self._frozen("")
        self.assertIn(mock.call(REPO_ROOT, "log", "--format=%H%x00%s%x1e", "abc1234..HEAD"),
                      report["git_calls"])

    def test_an_item_id_inside_a_longer_id_does_not_count(self):
        report = self._frozen(f"{self.HASH_A}\x00fix: settle A-10 instead\x1e\n")
        self.assertIn("names no item of the focus plan", " | ".join(report["errors"]))

    def test_a_legacy_id_of_a_focus_item_counts(self):
        renamed = {"id": "A-3", "plan": "p1", "title": "renamed", "status": "planned", "updated": "2026-08-02",
                   "legacyIds": ["OLD-7"]}
        report = self._frozen(f"{self.HASH_A}\x00fix: finish OLD-7\x1e\n", extra_item=renamed)
        self.assertTrue(report["ok"], report["errors"])

    def test_a_recorded_exception_accepts_a_commit_that_slipped_through(self):
        freeze = {"commit": "abc1234", "exceptions": {"bbbbbbb": "README typo accepted during the freeze"}}
        report = self._frozen(f"{self.HASH_B}\x00docs: tidy the README\x1e\n", freeze=freeze)
        self.assertTrue(report["ok"], report["errors"])

    def test_an_exception_needs_a_full_sha_and_a_reason_and_the_scan_still_runs(self):
        for key, reason in (("bbbbbbb", " "), ("b", "too short to bind one commit"), ("", "empty")):
            with self.subTest(key=key):
                freeze = {"commit": "abc1234", "exceptions": {key: reason}}
                report = self._frozen(f"{self.HASH_B}\x00docs: tidy the README\x1e\n", freeze=freeze)
                errors = " | ".join(report["errors"])
                self.assertIn("must map a 7-40 character commit sha to the reason", errors)
                self.assertIn("commit bbbbbbbbbb after the freeze names no item", errors)

    def test_a_freeze_commit_outside_local_history_is_surfaced_not_failed(self):
        report = self._frozen("", returncode=128)
        self.assertTrue(report["ok"], report["errors"])
        self.assertTrue(any("not in local history" in w for w in report["warnings"]))

    def test_the_freeze_names_a_commit(self):
        report = self._frozen("", freeze={"commit": "not-a-sha"})
        self.assertIn("freeze.commit must name the freeze commit's sha", " | ".join(report["errors"]))


class DueTests(Harness):
    def test_a_passed_due_date_on_open_work_is_surfaced(self):
        report = self.check(lambda d: d["items"][0].update(due="2026-08-01"))
        self.assertTrue(report["ok"], report["errors"])
        self.assertTrue(any("due 2026-08-01 has passed" in w for w in report["warnings"]))

    def test_a_future_due_date_is_quiet(self):
        report = self.check(lambda d: d["items"][0].update(due="2026-08-09"))
        self.assertFalse([w for w in report["warnings"] if "due" in w])

    def test_a_malformed_due_date_is_rejected(self):
        self.assertIn("due must be an ISO date",
                      self.errors_from(lambda d: d["items"][0].update(due="next week")))


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

    def test_the_focus_lock_and_due_dates_render_with_the_primary_plan(self):
        data = copy.deepcopy(MINIMAL)
        data["primaryPlan"] = "p1"
        data["focusLock"] = {"plan": "p1", "decided": "2026-08-02", "decision": "Ship p1 first.",
                             "maxInFlight": 2}
        data["items"][0].update(due="2026-08-09", gate="finish it")
        with mock.patch.object(roadmap, "load", return_value=data):
            rendered = roadmap.render(REPO_ROOT)
        self.assertIn("**Focus lock** (decided 2026-08-02): Ship p1 first.", rendered)
        self.assertIn("at most 2 items in flight", rendered)
        self.assertIn("- **`A-1`** (planned, due 2026-08-09) — an item.", rendered)

    def test_a_parked_item_renders_gate_and_unpark_condition(self):
        data = copy.deepcopy(MINIMAL)
        data["items"][0].update(status="parked", gate="do the thing", unparkWhen="the phone returns")
        with mock.patch.object(roadmap, "load", return_value=data):
            rendered = roadmap.render(REPO_ROOT)
        self.assertIn("  gate: do the thing\n  unparkWhen: the phone returns", rendered)

    def test_archived_items_count_toward_a_live_plan(self):
        data = copy.deepcopy(MINIMAL)
        archive = {"items": [{"id": "A-0", "plan": "p1", "title": "finished", "status": "done",
                              "updated": "2026-08-01", "evidence": ["commit:c14651c"]}]}
        with mock.patch.object(roadmap, "load", return_value=data), \
                mock.patch.object(roadmap, "load_archive", return_value=archive):
            plan = roadmap.progress(REPO_ROOT)["plans"][0]
        self.assertEqual((plan["items"], plan["finished"], plan["percent"]), (2, 1, 50))

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
