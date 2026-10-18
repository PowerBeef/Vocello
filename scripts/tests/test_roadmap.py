#!/usr/bin/env python3
"""Unit tests for scripts/roadmap.py.

The accuracy tests matter most. A tracker where `status: done` is a
self-assertion is worse than no tracker, because it looks like evidence. Each
test below is one way an item could claim completion it has not earned.
"""
import contextlib
import copy
import datetime
import difflib
import io
import json
import os
import pathlib
import subprocess
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


# --------------------------------------------------------------------------
# editing commands: set, note, close
# --------------------------------------------------------------------------

EDIT_ROADMAP = {
    "schemaVersion": 1,
    "primaryPlan": "p1",
    "focusLock": {"plan": "p1", "decided": "2026-08-01", "decision": "ship p1 first", "maxInFlight": 1},
    "description": "fixture",
    "plans": [
        {"id": "p1", "title": "Plan one", "status": "active", "owner": "backend-mlx",
         "adopted": "2026-08-01", "goal": "do a thing"},
        {"id": "p2", "title": "Plan two", "status": "parked", "owner": "release-qa",
         "adopted": "2026-08-01", "goal": "later"},
    ],
    "items": [
        {"id": "A-1", "plan": "p1", "title": "first", "status": "in-flight", "blockedBy": [],
         "gate": "ship it", "updated": "2026-08-01", "notes": "Started."},
        {"id": "A-2", "plan": "p1", "title": "second", "status": "planned", "gate": "then this",
         "updated": "2026-08-01", "notes": "Queued."},
        {"id": "A-3", "plan": "p1", "title": "third", "status": "parked", "blockedBy": ["A-2"],
         "gate": "maybe", "updated": "2026-08-01", "unparkWhen": "A-2 lands", "notes": "Waiting."},
        {"id": "B-1", "plan": "p2", "title": "elsewhere", "status": "parked", "gate": "later",
         "updated": "2026-08-01", "unparkWhen": "after p1", "notes": "Parked."},
    ],
}
EDIT_ARCHIVE = {
    "schemaVersion": 1,
    "description": "fixture archive",
    "plans": [],
    "items": [
        {"id": "A-0", "plan": "p1", "title": "zeroth", "status": "done", "gate": "done before",
         "updated": "2026-07-30", "notes": "Finished.", "evidence": ["run:fixture-run-0"]},
    ],
}
EDIT_DATE = "2026-08-05"
FILES = (roadmap.ROADMAP_PATH, roadmap.ARCHIVE_PATH, roadmap.RENDER_PATH)


class EditHarness(unittest.TestCase):
    """A small, valid roadmap in a temporary root; edits never touch the real config.

    The fixture cites no commits and sets no freeze, so validation never asks git
    about a directory that is not a repository.
    """

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        (self.root / "config").mkdir()
        (self.root / "docs").mkdir()
        self.write_json(roadmap.ROADMAP_PATH, EDIT_ROADMAP)
        self.write_json(roadmap.ARCHIVE_PATH, EDIT_ARCHIVE)
        (self.root / "evidence.txt").write_text("proof\n", encoding="utf-8")
        (self.root / roadmap.RENDER_PATH).write_text(roadmap.render(self.root), encoding="utf-8")
        self.assertConsistent()

    def write_json(self, relative, data):
        (self.root / relative).write_text(roadmap.dump_json(copy.deepcopy(data)), encoding="utf-8")

    def edit(self, *args):
        """Run one editing command against the fixture; returns (exit code, stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = roadmap.main([*args, "--root", str(self.root), "--date", EDIT_DATE])
        return code, out.getvalue(), err.getvalue()

    def snapshot(self):
        return {path: (self.root / path).read_bytes() for path in FILES}

    def data(self, relative=roadmap.ROADMAP_PATH):
        return json.loads((self.root / relative).read_text(encoding="utf-8"))

    def item(self, item_id):
        return next(item for item in self.data()["items"] if item["id"] == item_id)

    def archived(self):
        return self.data(roadmap.ARCHIVE_PATH)["items"]

    def assertRefused(self, args, message, code=1):
        before = self.snapshot()
        result, _, err = self.edit(*args)
        self.assertEqual(result, code, err)
        self.assertIn(message, err)
        self.assertEqual(self.snapshot(), before, "a refused edit wrote a file")

    def assertConsistent(self):
        """What one editing call promises: valid, rendered and in the files' own format."""
        report = roadmap.validate(self.root, today=datetime.date.fromisoformat(EDIT_DATE))
        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual((self.root / roadmap.RENDER_PATH).read_text(encoding="utf-8"),
                         roadmap.render(self.root))
        for relative in (roadmap.ROADMAP_PATH, roadmap.ARCHIVE_PATH):
            text = (self.root / relative).read_text(encoding="utf-8")
            self.assertEqual(roadmap.dump_json(json.loads(text)), text)


class SetTests(EditHarness):
    def test_set_due_inserts_one_line_after_status_and_keeps_updated(self):
        before = (self.root / roadmap.ROADMAP_PATH).read_text(encoding="utf-8").splitlines()
        code, out, err = self.edit("set", "A-2", "--due", "2026-08-20")
        self.assertEqual(code, 0, err)
        after = (self.root / roadmap.ROADMAP_PATH).read_text(encoding="utf-8").splitlines()
        changes = [line for line in difflib.ndiff(before, after) if line[:2] in ("+ ", "- ")]
        self.assertEqual(changes, ['+       "due": "2026-08-20",'])
        self.assertEqual(list(self.item("A-2"))[:5], ["id", "plan", "title", "status", "due"])
        self.assertEqual(self.item("A-2")["updated"], "2026-08-01", "a date change alone does not touch the item")
        self.assertIn("(planned, due 2026-08-20)", (self.root / roadmap.RENDER_PATH).read_text(encoding="utf-8"))
        self.assertIn("set A-2: due", out)
        self.assertConsistent()

    def test_a_status_change_moves_updated_to_the_date(self):
        code, _, err = self.edit("set", "A-3", "--status", "planned")
        self.assertEqual(code, 0, err)
        item = self.item("A-3")
        self.assertEqual((item["status"], item["updated"]), ("planned", EDIT_DATE))
        self.assertEqual(item["unparkWhen"], "A-2 lands", "unparking keeps the recorded condition")
        self.assertConsistent()

    def test_a_gate_change_moves_updated_and_touch_moves_it_for_anything(self):
        self.assertEqual(self.edit("set", "A-2", "--gate", "a sharper gate")[0], 0)
        self.assertEqual(self.item("A-2")["updated"], EDIT_DATE)
        self.assertEqual(self.edit("set", "B-1", "--title", "renamed", "--touch")[0], 0)
        self.assertEqual((self.item("B-1")["title"], self.item("B-1")["updated"]), ("renamed", EDIT_DATE))
        self.assertConsistent()

    def test_none_removes_optional_fields(self):
        self.assertEqual(self.edit("set", "A-2", "--due", "2026-08-20")[0], 0)
        self.assertEqual(self.edit("set", "A-2", "--due", "none")[0], 0)
        self.assertNotIn("due", self.item("A-2"))
        self.assertEqual(self.edit("set", "A-3", "--blocked-by", "none")[0], 0)
        self.assertEqual(self.item("A-3")["blockedBy"], [])
        self.assertEqual(self.edit("set", "A-3", "--status", "planned", "--unpark-when", "none")[0], 0)
        self.assertNotIn("unparkWhen", self.item("A-3"))
        self.assertConsistent()

    def test_blockers_may_be_open_or_archived_and_land_before_the_gate(self):
        self.assertEqual(self.edit("set", "A-2", "--blocked-by", "A-0,B-1")[0], 0)
        item = self.item("A-2")
        self.assertEqual(item["blockedBy"], ["A-0", "B-1"])
        self.assertEqual(list(item).index("blockedBy") + 1, list(item).index("gate"))
        self.assertConsistent()

    def test_an_unknown_or_archived_id_is_refused(self):
        self.assertRefused(("set", "Z-9", "--status", "planned"), "unknown item Z-9")
        self.assertRefused(("set", "A-0", "--status", "planned"), "A-0 is archived")

    def test_a_bad_date_is_refused(self):
        for value in ("2026-13-01", "next week", "20260820", "2026-8-1"):
            with self.subTest(value=value):
                self.assertRefused(("set", "A-2", "--due", value), "--due must be an ISO date")
        before = self.snapshot()
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = roadmap.main(["set", "A-2", "--due", "2026-08-20", "--root", str(self.root), "--date", "soon"])
        self.assertEqual(code, 1)
        self.assertIn("--date must be an ISO date", err.getvalue())
        self.assertEqual(self.snapshot(), before)

    def test_invalid_values_are_refused(self):
        self.assertRefused(("set", "A-2", "--status", "done"), "roadmap.py close A-2 --status done")
        self.assertRefused(("set", "A-2", "--status", "mostly-done"), "--status must be one of")
        self.assertRefused(("set", "A-2", "--blocked-by", "ghost"), "unknown item(s): ghost")
        self.assertRefused(("set", "A-2", "--blocked-by", "A-2"), "cannot block itself")
        self.assertRefused(("set", "A-2", "--blocked-by", "A-1,,A-3"), "distinct comma-separated")
        self.assertRefused(("set", "A-2", "--title", "  "), "--title cannot be empty")
        self.assertRefused(("set", "A-2"), "set needs at least one of")

    def test_an_edit_that_changes_nothing_writes_nothing(self):
        before = self.snapshot()
        code, out, _ = self.edit("set", "A-2", "--status", "planned")
        self.assertEqual(code, 0)
        self.assertIn("no change", out)
        self.assertEqual(self.snapshot(), before)


class NoteTests(EditHarness):
    def test_note_replaces_or_appends_without_touching_updated(self):
        self.assertEqual(self.edit("note", "A-2", "New position.")[0], 0)
        self.assertEqual(self.item("A-2")["notes"], "New position.")
        self.assertEqual(self.edit("note", "A-2", "--append", "More.")[0], 0)
        self.assertEqual(self.item("A-2")["notes"], "New position. More.")
        self.assertEqual(self.item("A-2")["updated"], "2026-08-01")
        self.assertEqual(self.edit("note", "A-2", "--append", "Measured.", "--touch")[0], 0)
        self.assertEqual(self.item("A-2")["updated"], EDIT_DATE)
        self.assertConsistent()

    def test_notes_stop_at_the_limit_and_are_never_truncated(self):
        self.assertEqual(self.edit("note", "A-2", "x" * roadmap.NOTES_MAX_CHARS)[0], 0)
        self.assertRefused(("note", "A-2", "--append", "y"), "notes would be 1202 characters, 2 over the "
                                                              "1200-character limit")
        self.assertRefused(("note", "A-2", "z" * 1201), "1201 characters")
        self.assertEqual(self.item("A-2")["notes"], "x" * 1200)
        self.assertConsistent()

    def test_note_takes_text_or_append(self):
        self.assertRefused(("note", "A-2"), "note takes TEXT")
        self.assertRefused(("note", "A-2", "both", "--append", "ways"), "note takes TEXT")
        self.assertRefused(("note", "A-2", " "), "TEXT cannot be empty")


class CloseTests(EditHarness):
    def test_close_moves_the_item_to_the_end_of_the_archive(self):
        keys = list(self.item("A-3"))
        code, out, err = self.edit("close", "A-3", "--evidence", "run:fixture-run-3",
                                   "--evidence", "file:evidence.txt", "--note", "Done 2026-08-05.")
        self.assertEqual(code, 0, err)
        self.assertNotIn("A-3", [item["id"] for item in self.data()["items"]])
        closed = self.archived()[-1]
        self.assertEqual([item["id"] for item in self.archived()], ["A-0", "A-3"])
        self.assertEqual((closed["status"], closed["updated"]), ("done", EDIT_DATE))
        self.assertEqual(closed["notes"], "Waiting. Done 2026-08-05.")
        self.assertEqual(closed["evidence"], ["run:fixture-run-3", "file:evidence.txt"])
        # Same fields in the same order; a closed item never wakes, and new evidence goes last.
        self.assertEqual(list(closed), [key for key in keys if key != "unparkWhen"] + ["evidence"])
        rendered = (self.root / roadmap.RENDER_PATH).read_text(encoding="utf-8")
        self.assertNotIn("`A-3`", rendered)
        self.assertIn("| `p1` | active | backend-mlx | 2/4 (50%) |", rendered)
        self.assertIn("close A-3: done", out)
        self.assertConsistent()

    def test_done_needs_evidence_that_resolves(self):
        self.assertRefused(("close", "A-2"), "done is never a bare assertion")
        self.assertRefused(("close", "A-2", "--evidence", "file:missing.txt"), "file not found: missing.txt")
        self.assertRefused(("close", "A-2", "--evidence", "vibes:it-feels-done"), "unknown evidence kind")

    def test_superseding_records_both_sides(self):
        code, _, err = self.edit("close", "A-3", "--status", "superseded", "--superseded-by", "A-2")
        self.assertEqual(code, 0, err)
        loser = self.archived()[-1]
        self.assertEqual((loser["id"], loser["status"]), ("A-3", "superseded"))
        self.assertEqual(list(loser)[-1], "supersededBy")
        self.assertEqual(loser["supersededBy"], "A-2")
        winner = self.item("A-2")
        self.assertEqual(winner["legacyIds"], ["A-3"])
        self.assertEqual(list(winner)[-1], "legacyIds")
        self.assertEqual(winner["updated"], "2026-08-01", "absorbing an id is not a status or gate change")
        self.assertConsistent()

    def test_a_winner_keeps_its_earlier_legacy_ids(self):
        data = copy.deepcopy(EDIT_ROADMAP)
        data["items"][1]["legacyIds"] = ["OLD-1"]
        self.write_json(roadmap.ROADMAP_PATH, data)
        (self.root / roadmap.RENDER_PATH).write_text(roadmap.render(self.root), encoding="utf-8")
        self.assertEqual(self.edit("close", "A-3", "--status", "superseded", "--superseded-by", "A-2")[0], 0)
        self.assertEqual(self.item("A-2")["legacyIds"], ["OLD-1", "A-3"])
        self.assertConsistent()

    def test_superseding_needs_an_open_winner(self):
        self.assertRefused(("close", "A-3", "--status", "superseded"), "needs --superseded-by")
        self.assertRefused(("close", "A-3", "--status", "superseded", "--superseded-by", "A-3"),
                           "cannot supersede itself")
        self.assertRefused(("close", "A-3", "--status", "superseded", "--superseded-by", "A-0"),
                           "A-0 is archived")
        self.assertRefused(("close", "A-3", "--status", "superseded", "--superseded-by", "Z-9"),
                           "Z-9 is not an item")
        self.assertRefused(("close", "A-3", "--superseded-by", "A-2", "--evidence", "run:x"),
                           "--superseded-by goes with --status superseded")

    def test_declining_needs_a_reason(self):
        self.assertRefused(("close", "B-1", "--status", "declined"), "needs --reason")
        code, _, err = self.edit("close", "B-1", "--status", "declined", "--reason", "not needed")
        self.assertEqual(code, 0, err)
        closed = self.archived()[-1]
        self.assertEqual((closed["status"], closed["reason"], list(closed)[-1]), ("declined", "not needed", "reason"))
        self.assertConsistent()

    def test_dependents_of_a_superseded_item_are_named(self):
        code, _, err = self.edit("close", "A-2", "--status", "superseded", "--superseded-by", "A-1")
        self.assertEqual(code, 0, err)
        self.assertIn("A-3 is blocked by A-2", err)
        self.assertIn("roadmap.py set ID --blocked-by A-1", err)
        self.assertConsistent()


class DryRunAndGateTests(EditHarness):
    def test_dry_run_prints_the_diff_and_writes_nothing(self):
        before = self.snapshot()
        code, out, err = self.edit("set", "A-2", "--status", "parked", "--unpark-when", "after A-1", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.snapshot(), before)
        for line in ("--- a/config/roadmap.json", '-      "status": "planned",', '+      "status": "parked",',
                     '+      "unparkWhen": "after A-1",', "+++ b/docs/ROADMAP.md", "dry run"):
            self.assertIn(line, out)

    def test_dry_run_of_a_close_shows_the_archive(self):
        before = self.snapshot()
        code, out, err = self.edit("close", "A-3", "--evidence", "run:fixture-run-3", "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.snapshot(), before)
        self.assertIn("+++ b/config/roadmap-archive.json", out)
        self.assertIn('+      "id": "A-3",', out)
        self.assertIn('-      "id": "A-3",', out)

    def test_a_result_that_fails_validation_writes_nothing(self):
        self.assertRefused(("set", "A-2", "--status", "in-flight"), "the focus lock allows 1")
        self.assertRefused(("set", "A-2", "--status", "parked"), "parked requires unparkWhen")
        self.assertRefused(("set", "B-1", "--status", "planned"), "outside the focus plan p1")
        self.assertRefused(("set", "A-2", "--status", "in-flight", "--dry-run"), "fails validation")

    def test_a_file_off_the_format_is_refused(self):
        path = self.root / roadmap.ROADMAP_PATH
        path.write_text(json.dumps(EDIT_ROADMAP, indent=4) + "\n", encoding="utf-8")
        self.assertRefused(("set", "A-2", "--due", "2026-08-20"), "not in the format roadmap.py writes", code=2)


class FormatAndCliTests(EditHarness):
    def test_the_real_files_round_trip_byte_identically(self):
        """Edits rewrite only their own lines because a load and dump changes nothing else."""
        for relative in (roadmap.ROADMAP_PATH, roadmap.ARCHIVE_PATH):
            with self.subTest(file=relative):
                text = (REPO_ROOT / relative).read_text(encoding="utf-8")
                self.assertEqual(roadmap.dump_json(json.loads(text)), text)

    def test_in_memory_validation_ignores_the_files(self):
        data = self.data()
        data["items"][1]["status"] = "in-flight"
        report = roadmap.validate(self.root, today=datetime.date.fromisoformat(EDIT_DATE), data=data,
                                  archive=self.data(roadmap.ARCHIVE_PATH))
        self.assertIn("the focus lock allows 1", " | ".join(report["errors"]))
        self.assertTrue(roadmap.validate(self.root)["ok"])

    def test_root_is_accepted_before_and_after_the_command(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(roadmap.main(["--root", str(self.root), "validate"]), 0)
            self.assertEqual(roadmap.main(["validate", "--root", str(self.root)]), 0)
            self.assertEqual(roadmap.main(["render", "--check", "--root", str(self.root)]), 0)
            self.assertEqual(roadmap.main(["--root", str(self.root), "status", "--json"]), 0)

    def test_help_documents_the_editing_commands(self):
        text = roadmap.build_parser().format_help()
        for fragment in ("set ID", "note ID", "close ID", "--dry-run", "--superseded-by", "--blocked-by"):
            self.assertIn(fragment, text)


if __name__ == "__main__":
    unittest.main()
