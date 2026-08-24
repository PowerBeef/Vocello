import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ios_startup_reliability", ROOT / "scripts" / "ios_startup_reliability.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class IOSStartupReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.script = "Exact private script."
        self.script_path = self.root / "script.txt"
        self.script_path.write_text(self.script, encoding="utf-8")
        digest = hashlib.sha256(self.script.encode()).hexdigest()
        self.plan = {
            "schemaVersion": 1, "scriptSHA256": digest, "scriptCharacters": len(self.script),
            "takes": [
                {"takeIndex": 1, "takeID": "cold-1", "speakerID": "vivian",
                 "deliveryID": "calm.strong", "language": "english", "seed": 38112001,
                 "variation": "balanced", "streaming": True, "preparation": "full_runtime_unload"},
                {"takeIndex": 2, "takeID": "warm-1", "speakerID": "vivian",
                 "deliveryID": "calm.strong", "language": "english", "seed": 38112001,
                 "variation": "balanced", "streaming": False, "preparation": "production",
                 "predecessorTakeID": "cold-1"},
            ],
        }
        self.plan_path = self.root / "plan.json"
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def pass_timeline(streaming):
        rows = []
        time_ms = 1
        for boundary in MODULE.BOUNDARY_ORDER[:-1]:
            if boundary in {"first_model_token", "first_audio_code_group"}:
                observed_ms = 11
            else:
                observed_ms = time_ms
                time_ms += 1
            rows.append({"boundary": boundary, "tMS": observed_ms})
        if streaming:
            rows.append({"boundary": "first_published_stream_chunk", "tMS": time_ms})
        return rows

    def test_prepare_validates_and_keeps_script_out_of_sanitized_plan(self):
        sanitized, launch = self.root / "sanitized.json", self.root / "launch.json"
        MODULE.prepare(self.plan_path, self.script_path, "run-1", sanitized, launch)
        self.assertNotIn(self.script, sanitized.read_text())
        self.assertIn(self.script, launch.read_text())
        self.assertEqual(json.loads(sanitized.read_text())["runID"], "run-1")

    def test_digest_mismatch_duplicate_and_predecessor_drift_fail_closed(self):
        bad = dict(self.plan)
        bad["scriptSHA256"] = "0" * 64
        path = self.root / "bad.json"
        path.write_text(json.dumps(bad))
        with self.assertRaisesRegex(MODULE.ContractError, "digest"):
            MODULE.validate_script(MODULE.load_plan(path), self.script_path)
        bad = json.loads(json.dumps(self.plan))
        bad["takes"][1]["takeID"] = "cold-1"
        path.write_text(json.dumps(bad))
        with self.assertRaisesRegex(MODULE.ContractError, "unique"):
            MODULE.load_plan(path)
        bad = json.loads(json.dumps(self.plan))
        bad["takes"][1]["predecessorTakeID"] = "wrong"
        path.write_text(json.dumps(bad))
        with self.assertRaisesRegex(MODULE.ContractError, "predecessor"):
            MODULE.load_plan(path)

    def test_bounds_invalid_ids_and_unknown_fields_fail(self):
        for mutation in (
            lambda p: p["takes"][0].update({"deliveryID": "calm"}),
            lambda p: p["takes"][0].update({"deliveryID": "dramatic.strong"}),
            lambda p: p["takes"][0].update({"speakerID": "unknown"}),
            lambda p: p["takes"][0].update({"extra": True}),
        ):
            bad = json.loads(json.dumps(self.plan)); mutation(bad)
            path = self.root / "bad.json"; path.write_text(json.dumps(bad))
            with self.assertRaises(MODULE.ContractError): MODULE.load_plan(path)
        bad = json.loads(json.dumps(self.plan)); bad["takes"] *= 65
        path.write_text(json.dumps(bad))
        with self.assertRaises(MODULE.ContractError): MODULE.load_plan(path)

    def test_result_validation_requires_parity_order_and_terminal_last(self):
        artifacts = self.root / "artifacts"; artifacts.mkdir()
        sessions = ["a" * 64, "b" * 64]
        takes = []
        for index, planned in enumerate(self.plan["takes"]):
            timeline = self.pass_timeline(planned["streaming"])
            receipt = {
                "schemaVersion": 1,
                "generationID": f"00000000-0000-0000-0000-00000000000{index}",
                "generationIdentityDigest": chr(ord("c") + index) * 64,
                "requestIdentityDigest": chr(ord("e") + index) * 64,
                "sessionIdentityDigest": sessions[index],
                "prewarmIdentityDigest": str(index + 1) * 64,
                "modelID": "pro_custom", "speakerID": planned["speakerID"],
                "deliveryID": planned["deliveryID"], "instructionDigest": "f" * 64,
                "instructionCharacters": 20, "language": planned["language"],
                "seed": planned["seed"], "seedSource": "requested",
                "variation": planned["variation"], "streaming": planned["streaming"],
                "warmState": "cold" if index == 0 else "warm",
                "predecessorIdentityDigest": None if index == 0 else sessions[index - 1],
                "retryAttempt": 0, "operationGeneration": index + 1,
            }
            takes.append({
                "takeIndex": planned["takeIndex"], "takeID": planned["takeID"], "status": "pass",
                "generationID": receipt["generationID"], "preparation": planned["preparation"],
                "requestReceipt": receipt,
                "attempts": [{"retryAttempt": 0, "finishReason": "eos", "requestReceipt": receipt,
                              "startupTimeline": timeline}],
                "startupTimeline": timeline,
                "classification": "success",
            })
        result = {
            "schemaVersion": 1, "status": "pass", "runID": "run-1",
            "scriptSHA256": self.plan["scriptSHA256"], "scriptCharacters": len(self.script),
            "plannedTakeCount": 2, "representedTakeCount": 2,
            "startedAt": "2026-08-23T00:00:00Z", "finishedAt": "2026-08-23T00:01:00Z",
            "startingDeviceState": {"lowPowerModeEnabled": False, "thermalState": "nominal", "modelInstalled": True},
            "finishingDeviceState": {"lowPowerModeEnabled": False, "thermalState": "fair", "modelInstalled": True, "loadedModelID": "pro_custom"},
            "takes": takes,
        }
        result_path = artifacts / "startup-reliability-result.json"
        result_path.write_text(json.dumps(result))
        summary = MODULE.validate_result(self.plan_path, artifacts, "run-1")
        self.assertEqual(summary["result"], "pass")
        result["takes"][1]["requestReceipt"]["seed"] = 9
        result_path.write_text(json.dumps(result))
        with self.assertRaisesRegex(MODULE.ContractError, "match"):
            MODULE.validate_result(self.plan_path, artifacts, "run-1")

    def test_retry_must_be_contiguous_and_identity_preserving(self):
        artifacts = self.root / "retry"; artifacts.mkdir()
        planned = self.plan["takes"][0]
        receipt = {
            "schemaVersion": 1, "generationID": "00000000-0000-0000-0000-000000000001",
            "generationIdentityDigest": "a" * 64, "requestIdentityDigest": "b" * 64,
            "sessionIdentityDigest": "c" * 64, "prewarmIdentityDigest": "d" * 64,
            "modelID": "pro_custom", "speakerID": planned["speakerID"],
            "deliveryID": planned["deliveryID"], "instructionDigest": "e" * 64,
            "instructionCharacters": 20, "language": planned["language"], "seed": planned["seed"],
            "seedSource": "requested", "variation": planned["variation"],
            "streaming": planned["streaming"], "warmState": "cold",
            "predecessorIdentityDigest": None, "retryAttempt": 0, "operationGeneration": 1,
        }
        retried = dict(receipt); retried["retryAttempt"] = 1
        timeline = self.pass_timeline(planned["streaming"])
        take = {
            "takeIndex": 1, "takeID": planned["takeID"], "status": "pass",
            "generationID": receipt["generationID"], "preparation": planned["preparation"],
            "requestReceipt": retried,
            "attempts": [
                {"retryAttempt": 0, "finishReason": "memory.insufficient", "requestReceipt": receipt, "startupTimeline": []},
                {"retryAttempt": 1, "finishReason": "eos", "requestReceipt": retried,
                 "startupTimeline": timeline},
            ],
            "startupTimeline": timeline,
            "classification": "success",
        }
        one_take_plan = dict(self.plan); one_take_plan["takes"] = [planned]
        plan_path = artifacts / "plan.json"; plan_path.write_text(json.dumps(one_take_plan))
        result = {
            "schemaVersion": 1, "status": "pass", "runID": "run-1",
            "scriptSHA256": self.plan["scriptSHA256"], "scriptCharacters": len(self.script),
            "plannedTakeCount": 1, "representedTakeCount": 1,
            "startedAt": "2026-08-23T00:00:00Z", "finishedAt": "2026-08-23T00:01:00Z",
            "startingDeviceState": {"lowPowerModeEnabled": False, "thermalState": "nominal", "modelInstalled": True},
            "finishingDeviceState": {"lowPowerModeEnabled": False, "thermalState": "nominal", "modelInstalled": True},
            "takes": [take],
        }
        result_path = artifacts / "startup-reliability-result.json"
        result_path.write_text(json.dumps(result))
        MODULE.validate_result(plan_path, artifacts, "run-1")
        take["attempts"][0]["requestReceipt"]["seed"] += 1
        result_path.write_text(json.dumps(result))
        with self.assertRaisesRegex(MODULE.ContractError, "changed request"):
            MODULE.validate_result(plan_path, artifacts, "run-1")

    def test_timeline_rejects_causal_reordering_and_incomplete_success(self):
        timeline = self.pass_timeline(True)
        reordered = json.loads(json.dumps(timeline))
        load_started = next(row for row in reordered if row["boundary"] == "model_load_started")
        loaded = next(row for row in reordered if row["boundary"] == "model_loaded")
        load_started["boundary"], loaded["boundary"] = loaded["boundary"], load_started["boundary"]
        with self.assertRaisesRegex(MODULE.ContractError, "causal"):
            MODULE.validate_timeline(reordered, "timeline")

        missing_code = [
            row for row in timeline if row["boundary"] != "first_audio_code_group"
        ]
        with self.assertRaisesRegex(MODULE.ContractError, "co-observe"):
            MODULE.validate_timeline(missing_code, "timeline")

    def test_private_fields_are_rejected(self):
        with self.assertRaisesRegex(MODULE.ContractError, "forbidden"):
            MODULE.recursively_reject_private_fields({"nested": {"error": "raw"}})

    def test_failed_take_can_preserve_unknown_boundary_without_fabricating_receipt(self):
        artifacts = self.root / "unknown"; artifacts.mkdir()
        observed = []
        for index, planned in enumerate(self.plan["takes"]):
            observed.append({
                "takeIndex": planned["takeIndex"], "takeID": planned["takeID"],
                "generationID": f"00000000-0000-0000-0000-00000000000{index}",
                "status": "failed", "failureCode": "request_receipt_unavailable",
                "preparation": planned["preparation"], "requestReceipt": None,
                "attempts": [], "startupTimeline": [], "classification": "unmaterialized_unknown",
            })
        result = {
            "schemaVersion": 1, "status": "diagnosed_failure", "runID": "run-1",
            "scriptSHA256": self.plan["scriptSHA256"], "scriptCharacters": len(self.script),
            "plannedTakeCount": 2, "representedTakeCount": 2,
            "startedAt": "2026-08-23T00:00:00Z", "finishedAt": "2026-08-23T00:01:00Z",
            "startingDeviceState": {"lowPowerModeEnabled": False, "thermalState": "nominal", "modelInstalled": True},
            "finishingDeviceState": {"lowPowerModeEnabled": False, "thermalState": "nominal", "modelInstalled": True},
            "takes": observed,
        }
        (artifacts / "startup-reliability-result.json").write_text(json.dumps(result))
        summary = MODULE.validate_result(self.plan_path, artifacts, "run-1")
        self.assertEqual(summary["failedTakeCount"], 2)

    def test_ui_manifest_correlates_with_engine_receipt(self):
        diagnostics = self.root / "ui" / "engine"; diagnostics.mkdir(parents=True)
        generation = "abcdefab-cdef-abcd-efab-cdefabcdefab"
        log = self.root / "xcodebuild.log"
        log.write_text(
            "VOCELLO-STARTUP-PARITY-UI-MANIFEST runID=run-1 "
            f"generationID={generation} speakerID=vivian deliveryID=calm.strong "
            "language=english variation=balanced streaming=true seedSource=generated\n"
        )
        encoded_generation = generation.upper()
        row = {
            "layer": "engine", "generationID": encoded_generation,
            "requestReceipt": {
                "generationID": encoded_generation, "speakerID": "vivian", "deliveryID": "calm.strong",
                "instructionDigest": "a" * 64, "instructionCharacters": 42,
                "language": "english", "seed": 99, "seedSource": "generated",
                "variation": "balanced", "streaming": True, "retryAttempt": 0,
            },
            "stageMarks": [{"stage": "startup.first_decoded_audio_frame", "tMS": 12}],
        }
        (diagnostics / "generations.jsonl").write_text(json.dumps(row) + "\n")
        output = self.root / "parity.json"
        result = MODULE.validate_ui_parity(log, self.root / "ui", "run-1", output)
        self.assertEqual(result["status"], "pass")
        row["requestReceipt"]["speakerID"] = "aiden"
        (diagnostics / "generations.jsonl").write_text(json.dumps(row) + "\n")
        with self.assertRaisesRegex(MODULE.ContractError, "diverged"):
            MODULE.validate_ui_parity(log, self.root / "ui", "run-1", output)

    def test_device_runner_helpers_are_shell_definitions_not_heredoc_payload(self):
        source = (ROOT / "scripts" / "ios_device.sh").read_text(encoding="utf-8")
        helpers = (
            "pull_startup_reliability_run() {",
            "startup_reliability_process_is_alive() {",
            "wait_startup_reliability_result() {",
            "snapshot_startup_reliability_crashes() {",
        )
        for helper in helpers:
            self.assertEqual(source.count(helper), 1)

        heredoc_bodies = []
        cursor = 0
        marker = "<<'PY'"
        while True:
            start = source.find(marker, cursor)
            if start == -1:
                break
            body_start = source.find("\n", start) + 1
            body_end = source.find("\nPY\n", body_start)
            self.assertNotEqual(body_end, -1)
            heredoc_bodies.append(source[body_start:body_end])
            cursor = body_end + 4
        for body in heredoc_bodies:
            for helper in helpers:
                self.assertNotIn(helper, body)

        command_index = source.index("cmd_delivery_reliability() {")
        for helper in helpers:
            self.assertLess(source.index(helper), command_index)

        scoped_pull = source[
            source.index("pull_startup_reliability_run() {"):
            source.index("wait_startup_reliability_result() {")
        ]
        self.assertIn('diagnostics/$run_id', scoped_pull)
        self.assertIn("--timeout 60", scoped_pull)
        wait_body = source[
            source.index("wait_startup_reliability_result() {"):
            source.index("snapshot_startup_reliability_crashes() {")
        ]
        self.assertIn('pull_startup_reliability_run "$run_id" "$dest"', wait_body)
        self.assertIn('startup_reliability_process_is_alive "$dev" "$target_pid"', wait_body)
        self.assertIn("return 27", wait_body)
        self.assertNotIn('cmd_pull "$dest"', wait_body)

        liveness_body = source[
            source.index("startup_reliability_process_is_alive() {"):
            source.index("wait_startup_reliability_result() {")
        ]
        self.assertIn("device info processes", liveness_body)
        self.assertIn('processIdentifier == $target_pid', liveness_body)
        self.assertIn('row.get("processIdentifier") == target', liveness_body)
        self.assertIn('rm -f "$inventory"', liveness_body)

        command_body = source[
            source.index("cmd_delivery_reliability() {"):
            source.index("# memory-field-report")
        ]
        self.assertIn(
            'wait_startup_reliability_result "$run_id" "$timeout" "$pulled" "$dev" "$target_pid"',
            command_body,
        )

        crash_body = source[
            source.index("snapshot_startup_reliability_crashes() {"):
            source.index("read_devicectl_launch_pid() {")
        ]
        self.assertIn("diagnostics/crashes", crash_body)
        self.assertIn("CoreDeviceError error 7000", crash_body)
        self.assertIn("--timeout 30", crash_body)

        ui_source = (ROOT / "scripts" / "ui_test.sh").read_text(encoding="utf-8")
        ui_crash_body = ui_source[
            ui_source.index("snapshot_ios_crashes() {"):
            ui_source.index("pull_ios_run_diagnostics() {")
        ]
        self.assertIn("diagnostics/crashes", ui_crash_body)
        self.assertIn("CoreDeviceError error 7000", ui_crash_body)
        self.assertIn("--timeout 30", ui_crash_body)
        ui_run_pull = ui_source[
            ui_source.index("pull_ios_run_diagnostics() {"):
            ui_source.index("pull_ios_model_download_diagnostics() {")
        ]
        self.assertIn('diagnostics/$target_run_id', ui_run_pull)
        self.assertIn("--timeout 60", ui_run_pull)
        startup_collection = ui_source[
            ui_source.index('if [[ "$lane" == "startup-parity" ]]; then', ui_source.index("startup_parity_status=0")):
            ui_source.index("crash_delta_status=0")
        ]
        self.assertIn("pull_ios_run_diagnostics", startup_collection)
        self.assertNotIn('ios_device.sh" pull', startup_collection)

        mirror_source = (
            ROOT / "Sources" / "iOSSupport" / "Services" /
            "IOSPullableDiagnosticsMirror.swift"
        ).read_text(encoding="utf-8")
        self.assertIn('environment["QVOICE_IOS_DEVICE_RUN_ID"]', mirror_source)
        self.assertIn(
            "pullableRoot.appendingPathComponent(runID, isDirectory: true)",
            mirror_source,
        )
        self.assertGreaterEqual(
            mirror_source.count("syncGenerationTelemetry("),
            3,
            "the UI mirror must preserve the global export and add a run-scoped export",
        )


if __name__ == "__main__":
    unittest.main()
