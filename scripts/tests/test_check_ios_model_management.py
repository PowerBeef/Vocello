import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check_ios_model_management.py"
SPEC = importlib.util.spec_from_file_location("check_ios_model_management", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def event(sequence=1, **overrides):
    value = {
        "schemaVersion": 1,
        "runID": "run-1",
        "processInstanceID": "process-1",
        "sequence": sequence,
        "capturedAtUTC": f"2026-08-21T12:00:{sequence:02d}Z",
        "uptimeSeconds": float(sequence),
        "layer": "coordinator",
        "event": "heartbeat",
        "modelID": "pro_custom",
        "logicalRequestID": "request-1",
        "durableBytes": 50,
        "totalBytes": 100,
        "expectedFileCount": 2,
        "verifiedFileCount": 1,
        "ledgerStatus": "downloading",
    }
    value.update(overrides)
    return value


def observation(**overrides):
    value = {
        "schemaVersion": 1,
        "capturedAtUTC": "2026-08-21T12:00:01Z",
        "modelID": "pro_custom",
        "milestone": "transfer-50",
        "rawBytes": 50,
        "totalBytes": 100,
        "expectedFraction": 0.5,
        "accessibilityFraction": 0.5,
        "visibleText": "50% · 50 B of 100 B",
        "status": "Downloading",
        "phase": "transfer",
        "actions": ["Cancel"],
    }
    value.update(overrides)
    return value


class ModelManagementDiagnosisTests(unittest.TestCase):
    def test_rejects_missing_trace(self):
        findings = MODULE.diagnose([], [observation()])
        self.assertEqual([finding.code for finding in findings], ["missing-trace"])

    def test_rejects_missing_ui_observations(self):
        findings = MODULE.diagnose([event()], [])
        self.assertIn("missing-ui-observations", {finding.code for finding in findings})

    def test_classifies_verified_files_that_never_finalize(self):
        events = [
            event(1, event="file-verified", verifiedFileCount=2),
            event(2, verifiedFileCount=2),
        ]
        findings = MODULE.diagnose(events, [observation()])
        self.assertIn("verified-files-not-finalized", {finding.code for finding in findings})

    def test_rejects_progress_and_accessibility_disagreement(self):
        findings = MODULE.diagnose([event()], [observation(accessibilityFraction=0.75)])
        self.assertIn("accessibility-progress-disagrees", {finding.code for finding in findings})

    def test_does_not_compare_progress_across_logical_requests(self):
        findings = MODULE.diagnose(
            [
                event(1, event="progress", logicalRequestID="cancelled", durableBytes=90),
                event(2, event="progress", logicalRequestID="restarted", durableBytes=10),
                event(3, event="progress", logicalRequestID="restarted", durableBytes=20),
            ],
            [observation()],
        )
        self.assertNotIn("progress-regressed", {finding.code for finding in findings})

    def test_rejects_bytes_beyond_total_and_downloader_regression(self):
        findings = MODULE.diagnose(
            [
                event(1, event="progress", durableBytes=90),
                event(2, event="progress", durableBytes=80),
                event(3, event="progress", durableBytes=101),
            ],
            [observation()],
        )
        codes = {finding.code for finding in findings}
        self.assertIn("progress-regressed", codes)
        self.assertIn("bytes-exceed-total", codes)

    def test_rejects_premature_full_progress(self):
        findings = MODULE.diagnose(
            [event()],
            [observation(rawBytes=99, totalBytes=100, expectedFraction=0.99, accessibilityFraction=1.0)],
        )
        codes = {finding.code for finding in findings}
        self.assertIn("premature-full-bar", codes)

    def test_rejects_trace_sequence_gap(self):
        findings = MODULE.diagnose([event(1), event(3)], [observation()])
        self.assertIn("trace-sequence-gap", {finding.code for finding in findings})

    def test_rejects_false_delete_success(self):
        findings = MODULE.diagnose(
            [event(event="delete-completed", targetAvailable=True, stagingFileCount=1, ledgerStatus="downloading")],
            [],
        )
        self.assertIn("false-delete-success", {finding.code for finding in findings})

    def test_classifies_publication_without_installed_ledger(self):
        findings = MODULE.diagnose(
            [
                event(1, event="atomic-publication-completed", ledgerStatus="installing"),
                event(2, ledgerStatus="installing"),
            ],
            [observation()],
        )
        self.assertIn("publication-without-installed-ledger", {finding.code for finding in findings})

    def test_classifies_installed_ledger_without_ready_ui(self):
        findings = MODULE.diagnose(
            [event(event="write", ledgerStatus="installed")],
            [observation(status="Installing", actions=[])],
        )
        self.assertIn("installed-not-ready-in-ui", {finding.code for finding in findings})

    def test_does_not_treat_delete_request_as_a_new_install_transition(self):
        findings = MODULE.diagnose(
            [
                event(1, event="write", ledgerStatus="installed"),
                event(2, event="delete-requested", ledgerStatus="installed"),
                event(3, event="delete-completed", ledgerStatus="deleted"),
            ],
            [
                observation(capturedAtUTC="2026-08-21T12:00:02Z", status="Ready", actions=["Delete"]),
                observation(capturedAtUTC="2026-08-21T12:00:03Z", status="Not Installed", actions=["Download"]),
            ],
        )
        self.assertNotIn("installed-not-ready-in-ui", {finding.code for finding in findings})

    def test_does_not_infer_ui_failure_without_any_ui_observation(self):
        findings = MODULE.diagnose(
            [event(event="write", ledgerStatus="installed")],
            [],
        )
        codes = {finding.code for finding in findings}
        self.assertIn("missing-ui-observations", codes)
        self.assertNotIn("installed-not-ready-in-ui", codes)

    def test_classifies_queued_ledger_and_snapshot_byte_mismatch(self):
        findings = MODULE.diagnose(
            [
                event(1, event="request-queued", durableBytes=0, ledgerStatus="queued"),
                event(2, event="snapshot-published", phase="queued", durableBytes=100),
            ],
            [observation()],
        )
        self.assertIn("queued-ledger-progress-mismatch", {finding.code for finding in findings})

    def test_rejects_ui_regression_freeze_and_motion_without_bytes(self):
        findings = MODULE.diagnose(
            [event()],
            [
                observation(rawBytes=20, expectedFraction=0.2, accessibilityFraction=0.2),
                observation(rawBytes=40, expectedFraction=0.2, accessibilityFraction=0.2),
                observation(rawBytes=40, expectedFraction=0.3, accessibilityFraction=0.3),
                observation(rawBytes=30, expectedFraction=0.15, accessibilityFraction=0.15),
            ],
        )
        codes = {finding.code for finding in findings}
        self.assertIn("ui-frozen-while-bytes-advance", codes)
        self.assertIn("ui-moved-without-bytes", codes)
        self.assertIn("ui-progress-regressed", codes)

    def test_classifies_successful_urlsession_completion_without_staging(self):
        findings = MODULE.diagnose(
            [event(event="task-completed", layer="url-session", taskID=8)],
            [observation()],
        )
        self.assertIn("urlsession-completion-not-staged", {finding.code for finding in findings})

    def test_classifies_claimed_completion_without_downstream_resume(self):
        findings = MODULE.diagnose(
            [
                event(1, event="parked-completion-claimed", layer="url-session", taskID=8),
                event(2, event="heartbeat"),
            ],
            [observation()],
        )
        self.assertIn("claimed-completion-not-resumed", {finding.code for finding in findings})

    def test_trace_reader_rejects_cross_run_contamination(self):
        with tempfile.TemporaryDirectory() as temporary:
            trace = pathlib.Path(temporary) / "trace"
            trace.mkdir()
            (trace / "event-one.json").write_text(json.dumps(event(runID="other")), encoding="utf-8")
            with self.assertRaises(SystemExit):
                MODULE.read_trace(pathlib.Path(temporary), "run-1")

    def test_partitions_retained_prior_run_trace_without_weakening_active_reader(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            trace = root / "trace"
            trace.mkdir()
            (trace / "event-current.json").write_text(
                json.dumps(event(runID="run-1")), encoding="utf-8"
            )
            (trace / "event-prior.json").write_text(
                json.dumps(event(runID="prior-run")), encoding="utf-8"
            )

            result = MODULE.partition_prior_trace_events(root, "run-1")

            self.assertEqual(result, {"currentEventCount": 1, "priorEventCount": 1})
            self.assertTrue((trace / "event-current.json").is_file())
            self.assertFalse((trace / "event-prior.json").exists())
            self.assertTrue(
                (root / "prior-traces" / "prior-run" / "event-prior.json").is_file()
            )
            self.assertEqual(len(MODULE.read_trace(root, "run-1")), 1)

    def test_requires_all_progress_milestones_for_diagnose_and_acceptance(self):
        observations = [
            observation(modelID="pro_custom", milestone=milestone)
            for milestone in ["transfer-1", "transfer-25", "transfer-50", "transfer-75"]
        ]

        self.assertEqual(
            MODULE.missing_progress_milestones(observations, "diagnose"),
            ["transfer-95"],
        )
        self.assertEqual(
            MODULE.missing_progress_milestones(observations, "acceptance"),
            ["transfer-95"],
        )
        self.assertEqual(MODULE.missing_progress_milestones(observations, "queue"), [])

        observations.append(observation(
            modelID="pro_custom",
            milestone="transfer-95",
            expectedFraction=0.9406,
        ))
        self.assertEqual(MODULE.missing_progress_milestones(observations, "diagnose"), [])
        self.assertEqual(MODULE.invalid_progress_milestone_ranges(observations, "diagnose"), [])

    def test_rejects_95_percent_checkpoint_outside_real_byte_band(self):
        too_early = [observation(milestone="transfer-95", expectedFraction=0.89)]
        complete = [observation(milestone="transfer-95", expectedFraction=1.0)]

        self.assertEqual(
            MODULE.invalid_progress_milestone_ranges(too_early, "diagnose"),
            ["transfer-95"],
        )
        self.assertEqual(
            MODULE.invalid_progress_milestone_ranges(complete, "acceptance"),
            ["transfer-95"],
        )
        self.assertEqual(MODULE.invalid_progress_milestone_ranges(too_early, "queue"), [])

    def test_attachment_reader_accepts_xcresulttool_array_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "image.png").write_bytes(b"png")
            (root / "manifest.json").write_text(json.dumps([
                {"attachments": [{
                    "suggestedHumanReadableName": "milestone",
                    "exportedFileName": "image.png",
                }]}
            ]), encoding="utf-8")
            self.assertEqual(MODULE.attachment_map(root)["milestone"], root / "image.png")

    def test_attachment_reader_normalizes_xcode_name_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            (root / "image.png").write_bytes(b"png")
            decorated = "milestone_0_31791849-9749-422E-84F2-FA464BAD5EC3.png"
            (root / "manifest.json").write_text(json.dumps([
                {"attachments": [{
                    "suggestedHumanReadableName": decorated,
                    "exportedFileName": "image.png",
                }]}
            ]), encoding="utf-8")
            attachments = MODULE.attachment_map(root)
            self.assertEqual(attachments[decorated], root / "image.png")
            self.assertEqual(attachments["milestone"], root / "image.png")

    def test_visual_analyzer_accepts_leading_exact_high_contrast_fill(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "bar.png"
            width, height = 100, 8
            pixels = []
            for _ in range(height):
                pixels.extend([(210, 170, 255)] * 50 + [(45, 45, 55)] * 50)
            MODULE.write_png(path, width, height, pixels)
            result = MODULE.analyze_bar(path, 0.5)
            self.assertTrue(result["leadingEdgeAnchored"])
            self.assertTrue(result["passesFractionTolerance"])
            self.assertTrue(result["passesContrast"])

    def test_visual_analyzer_ignores_rounded_cap_background(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "rounded-bar.png"
            width, height = 100, 10
            fill = (210, 170, 255)
            track = (45, 45, 55)
            background = (20, 21, 29)
            pixels = []
            for row in range(height):
                cap = abs(row - height // 2)
                leading_background = min(4, cap)
                pixels.extend(
                    [background] * leading_background
                    + [fill] * (50 - leading_background)
                    + [track] * 50
                )
            MODULE.write_png(path, width, height, pixels)
            result = MODULE.analyze_bar(path, 0.5)
            self.assertTrue(result["leadingEdgeAnchored"])
            self.assertTrue(result["passesFractionTolerance"])

    def test_visual_analyzer_samples_narrow_track_at_ninety_nine_percent(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "near-complete-bar.png"
            width, height = 300, 6
            fill = (226, 194, 130)
            track = (26, 27, 35)
            pixels = []
            for _ in range(height):
                pixels.extend([fill] * 297 + [track] * 3)
            MODULE.write_png(path, width, height, pixels)

            result = MODULE.analyze_bar(path, 0.99)

            self.assertAlmostEqual(result["measuredFillFraction"], 0.99, places=2)
            self.assertTrue(result["leadingEdgeAnchored"])
            self.assertTrue(result["passesFractionTolerance"])
            self.assertTrue(result["passesContrast"])

    def test_visual_analyzer_rejects_full_pixels_for_incomplete_fraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "premature-full-bar.png"
            width, height = 300, 6
            pixels = [(226, 194, 130)] * width * height
            MODULE.write_png(path, width, height, pixels)

            result = MODULE.analyze_bar(path, 0.9995)

            self.assertGreaterEqual(result["measuredFillFraction"], 0.995)
            self.assertFalse(result["leadingEdgeAnchored"])
            self.assertFalse(result["passesContrast"])

    def test_visual_analyzer_rejects_wrong_or_reversed_fill(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "bar.png"
            width, height = 100, 8
            pixels = []
            for _ in range(height):
                pixels.extend([(45, 45, 55)] * 50 + [(210, 170, 255)] * 50)
            MODULE.write_png(path, width, height, pixels)
            result = MODULE.analyze_bar(path, 0.5)
            self.assertFalse(result["passesFractionTolerance"])

    def test_visual_analyzer_rejects_low_contrast(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = pathlib.Path(temporary) / "bar.png"
            width, height = 100, 8
            pixels = []
            for _ in range(height):
                pixels.extend([(90, 90, 94)] * 50 + [(80, 80, 84)] * 50)
            MODULE.write_png(path, width, height, pixels)
            result = MODULE.analyze_bar(path, 0.5)
            self.assertFalse(result["passesContrast"])


if __name__ == "__main__":
    unittest.main()
