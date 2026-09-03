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

    def test_v2_preparation_evidence_requires_operation_and_reservation_state(self):
        evidence = {
            "stage": "after_mlx_cache_clear", "sequence": 2,
            "capturedAtUptimeSeconds": 42.0, "mlxActiveMB": 100.0,
            "mlxCacheMB": 0.0, "mlxPeakMB": 500.0, "metalAllocatedMB": 120.0,
            "physicalFootprintMB": 1_200.0, "availableHeadroomMB": 2_000.0,
            "hasActiveGeneration": False, "memoryActionInFlight": False,
            "modelOperationInFlight": False, "generationReservationInFlight": False,
            "loadedModelID": None, "engineLifecycle": "idle", "violations": [],
        }
        MODULE.validate_preparation_evidence(evidence, "take.preparationEvidence[0]")
        for missing in ("modelOperationInFlight", "generationReservationInFlight"):
            incomplete = dict(evidence)
            incomplete.pop(missing)
            with self.assertRaisesRegex(MODULE.ContractError, "schema v2"):
                MODULE.validate_preparation_evidence(
                    incomplete, "take.preparationEvidence[0]"
                )

    def test_v2_qc_and_generation_scoped_artifacts_fail_closed(self):
        generation = "00000000-0000-0000-0000-000000000001"
        evidence = self.root / "artifacts" / "run-1" / "evidence" / generation
        evidence.mkdir(parents=True)
        codec = b"VQCT" + (1).to_bytes(4, "little") + (1).to_bytes(4, "little") + (0).to_bytes(4, "little")
        codec += (2).to_bytes(2, "little") + (4).to_bytes(4, "little", signed=True) + (5).to_bytes(4, "little", signed=True)
        (evidence / "codec-trace-v1.bin").write_bytes(codec)
        rejected = b"RIFFfixture"
        (evidence / "rejected.wav").write_bytes(rejected)
        artifacts = [
            {"schemaVersion": 1, "kind": "codec_trace", "sha256": hashlib.sha256(codec).hexdigest(),
             "byteCount": len(codec), "codecFrameCount": 1,
             "codeGroupRange": {"minimum": 2, "maximum": 2},
             "codecChunkRanges": [{"start": 0, "endExclusive": 1}], "complete": True},
            {"schemaVersion": 1, "kind": "rejected_audio", "sha256": hashlib.sha256(rejected).hexdigest(),
             "byteCount": len(rejected), "durationSeconds": 3.5},
        ]
        MODULE.validate_diagnostic_artifacts(
            artifacts, "take.diagnosticArtifacts", artifact_dir=self.root / "artifacts",
            generation_id=generation,
        )
        qc = {
            "algorithmVersion": 4, "instabilityVerdict": "pass",
            "writtenOutputVerdict": "fail", "verdict": "fail",
            "flags": ["dropout:2725ms"], "rmsDBFS": -20.0, "dcOffset": 0.0,
            "peak": 0.8, "clippedSamples": 0, "hotSamples": 0,
            "nonFiniteSamples": 0, "clickEvents": 0, "longestSilenceMS": 2725,
            "longestSilenceStartMS": 1400, "durationSeconds": 8.0, "chunkQC": [],
        }
        MODULE.validate_audio_qc(qc, "take.audioQC")
        (evidence / "codec-trace-v1.bin").write_bytes(codec + b"corrupt")
        with self.assertRaisesRegex(MODULE.ContractError, "do not match"):
            MODULE.validate_diagnostic_artifacts(
                artifacts, "take.diagnosticArtifacts", artifact_dir=self.root / "artifacts",
                generation_id=generation,
            )

    def test_v2_codec_replay_binds_trace_ranges_audio_and_qc(self):
        trace_digest = "a" * 64
        ranges = [{"start": 0, "endExclusive": 2}]
        codec = {
            "schemaVersion": 1, "kind": "codec_trace", "sha256": trace_digest,
            "byteCount": 32, "codecFrameCount": 2,
            "codeGroupRange": {"minimum": 2, "maximum": 2},
            "codecChunkRanges": ranges, "complete": True,
        }
        incremental = {
            "schemaVersion": 1, "kind": "incremental_replay_audio",
            "sha256": "b" * 64, "byteCount": 100, "durationSeconds": 1.0,
        }
        full = {
            "schemaVersion": 1, "kind": "full_replay_audio",
            "sha256": "c" * 64, "byteCount": 100, "durationSeconds": 1.0,
        }
        chunk = {
            "chunkIndex": 0, "frameOffset": 0, "frameCount": 24_000,
            "verdict": "pass", "flags": [], "rmsDBFS": -20.0, "peak": 0.7,
            "clippedSamples": 0, "hotSamples": 0, "nonFiniteSamples": 0,
            "clickEvents": 0, "longestSilenceMS": 0, "durationSeconds": 1.0,
        }
        qc = {
            "algorithmVersion": 4, "instabilityVerdict": "pass",
            "writtenOutputVerdict": "pass", "verdict": "pass", "flags": [],
            "rmsDBFS": -20.0, "dcOffset": 0.0, "peak": 0.7,
            "clippedSamples": 0, "hotSamples": 0, "nonFiniteSamples": 0,
            "clickEvents": 0, "longestSilenceMS": 0, "durationSeconds": 1.0,
            "chunkQC": [chunk],
        }
        replay = {
            "status": "complete", "traceSHA256": trace_digest, "ranges": ranges,
            "incrementalArtifact": incremental, "incrementalAudioQC": qc,
            "fullArtifact": full, "fullAudioQC": qc,
        }
        MODULE.validate_codec_replay(replay, "take.codecReplay", [codec, incremental, full])

        drifted = json.loads(json.dumps(replay))
        drifted["ranges"] = [{"start": 0, "endExclusive": 1}]
        with self.assertRaisesRegex(MODULE.ContractError, "not bound"):
            MODULE.validate_codec_replay(
                drifted, "take.codecReplay", [codec, incremental, full]
            )

        incomplete_chunk = json.loads(json.dumps(qc))
        incomplete_chunk["chunkQC"][0].pop("peak")
        replay["incrementalAudioQC"] = incomplete_chunk
        with self.assertRaisesRegex(MODULE.ContractError, "incomplete"):
            MODULE.validate_codec_replay(replay, "take.codecReplay", [codec, incremental, full])

    def test_audio_qc_accepts_v6_terminal_silence_and_cadence(self):
        qc = {
            "algorithmVersion": 6, "instabilityVerdict": "pass",
            "writtenOutputVerdict": "fail", "verdict": "fail",
            "flags": ["terminal_silence:11096ms"], "rmsDBFS": -20.0,
            "dcOffset": 0.0, "peak": 0.7, "clippedSamples": 0,
            "hotSamples": 0, "nonFiniteSamples": 0, "clickEvents": 0,
            "longestSilenceMS": 1851, "longestSilenceStartMS": 12351,
            "trailingSilenceMS": 11096, "trailingSilenceStartMS": 18743,
            "durationSeconds": 29.84,
            "cadence": {
                "classification": "severe",
                "reasons": ["single_suspicious_pause", "egregious_terminal_silence"],
                "expectedPauseCount": 1, "cadencePauseThresholdMS": 350,
                "suspiciousPauseThresholdMS": 1200, "observedCadencePauseCount": 2,
                "excessCadencePauseCount": 1, "suspiciousPauseCount": 1,
                "recordedInteriorPausesMS": [1851, 564],
                "totalInteriorSilenceMS": 2415, "totalCadenceSilenceMS": 2415,
                "medianCadencePauseMS": 564, "p90CadencePauseMS": 1851,
                "cadenceSilenceRatio": 0.08093,
            },
            "chunkQC": [],
        }
        MODULE.validate_audio_qc(qc, "take.audioQC")

        malformed = json.loads(json.dumps(qc))
        malformed["cadence"]["cadenceSilenceRatio"] = 1.01
        with self.assertRaisesRegex(MODULE.ContractError, "cadenceSilenceRatio"):
            MODULE.validate_audio_qc(malformed, "take.audioQC")

        malformed = json.loads(json.dumps(qc))
        malformed["trailingSilenceMS"] = -1
        with self.assertRaisesRegex(MODULE.ContractError, "trailingSilenceMS"):
            MODULE.validate_audio_qc(malformed, "take.audioQC")

        for key, invalid in (
            ("classification", {}), ("reasons", [{}]),
            ("reasons", ["single_suspicious_pause"] * 2),
            ("expectedPauseCount", True), ("recordedInteriorPausesMS", [False]),
            ("medianCadencePauseMS", True), ("cadenceSilenceRatio", float("nan")),
        ):
            with self.subTest(key=key, invalid=invalid):
                malformed = json.loads(json.dumps(qc))
                malformed["cadence"][key] = invalid
                with self.assertRaises(MODULE.ContractError):
                    MODULE.validate_audio_qc(malformed, "take.audioQC")

        for key in ("trailingSilenceMS", "trailingSilenceStartMS"):
            with self.subTest(key=key):
                malformed = json.loads(json.dumps(qc))
                malformed[key] = True
                with self.assertRaises(MODULE.ContractError):
                    MODULE.validate_audio_qc(malformed, "take.audioQC")

    def test_v2_failed_codec_replay_is_typed_and_carries_no_partial_success(self):
        codec = {
            "schemaVersion": 1, "kind": "codec_trace", "sha256": "a" * 64,
            "byteCount": 32, "codecFrameCount": 2,
            "codeGroupRange": {"minimum": 2, "maximum": 2},
            "codecChunkRanges": [{"start": 0, "endExclusive": 2}], "complete": True,
        }
        failed = {
            "status": "failed", "traceSHA256": codec["sha256"],
            "ranges": codec["codecChunkRanges"], "failureCode": "decoder_replay_failed",
        }
        MODULE.validate_codec_replay(failed, "take.codecReplay", [codec])
        failed["fullArtifact"] = {"kind": "full_replay_audio"}
        with self.assertRaisesRegex(MODULE.ContractError, "completed evidence"):
            MODULE.validate_codec_replay(failed, "take.codecReplay", [codec])

    def test_process_exit_composition_represents_every_planned_take(self):
        artifacts = self.root / "exit"; artifacts.mkdir()
        partial = {
            "takeIndex": 1, "takeID": "cold-1", "generationID": "00000000-0000-0000-0000-000000000001",
            "classification": "success",
        }
        (artifacts / "startup-reliability-take-001.json").write_text(json.dumps(partial))
        output = self.root / "forensics.json"
        result = MODULE.compose_process_exit(self.plan_path, artifacts, "run-1", output)
        self.assertEqual(result["rows"][0]["status"], "represented")
        self.assertEqual(result["rows"][1]["status"], "process_terminated")
        self.assertNotIn("generationID", result["rows"][1])

    def test_system_crash_sanitization_classifies_only_allowlisted_process(self):
        crashes = self.root / "crashes"; crashes.mkdir()
        report = {
            "procName": "Vocello", "timestamp": "2026-08-24T00:00:00Z",
            "termination": {"reason": "jetsam per-process-limit"},
            "physFootprint": 5 * 1024 * 1024 * 1024,
            "path": "/private/forbidden",
        }
        (crashes / "one.ips").write_text(json.dumps(report))
        (crashes / "other.ips").write_text(json.dumps({"procName": "Other", "reason": "jetsam"}))
        output = self.root / "crash-summary.json"
        result = MODULE.sanitize_system_crashes(crashes, output, {"Vocello"})
        self.assertEqual(len(result["reports"]), 1)
        self.assertEqual(result["reports"][0]["classification"], "jetsam")
        self.assertNotIn("path", output.read_text())

    def test_xcui_bootstrap_classifier_requires_zero_launched_tests(self):
        log = self.root / "xcui.log"
        log.write_text("Timed out while enabling automation mode\n", encoding="utf-8")
        summary = self.root / "summary.json"
        summary.write_text(json.dumps({"totalTestCount": 0}), encoding="utf-8")
        output = self.root / "bootstrap.json"
        result = MODULE.classify_xcui_bootstrap(log, summary, "run-1", output)
        self.assertEqual(result["status"], "infrastructure_bootstrap_failure")
        summary.write_text(json.dumps({"totalTestCount": 1}), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ContractError, "zero launched"):
            MODULE.classify_xcui_bootstrap(log, summary, "run-1", output)
        summary.write_text(json.dumps({"totalTestCount": 0}), encoding="utf-8")
        log.write_text("Timed out while enabling automation mode\nTest Case '-[Suite test]' failed\n")
        with self.assertRaisesRegex(MODULE.ContractError, "forbids"):
            MODULE.classify_xcui_bootstrap(log, summary, "run-1", output)

    def test_xcui_bootstrap_classifier_accepts_xcresult_runner_failure_count(self):
        log = self.root / "xcui-runner.log"
        log.write_text(
            "Failed to initialize for UI testing: Timed out while enabling automation mode.\n",
            encoding="utf-8",
        )
        summary = self.root / "runner-summary.json"
        summary.write_text(json.dumps({
            "result": "Failed",
            "totalTestCount": 1,
            "passedTests": 0,
            "failedTests": 1,
            "skippedTests": 0,
            "testFailures": [{
                "failureText": (
                    "The test runner failed to initialize for UI testing. "
                    "(Underlying Error: Timed out while enabling automation mode.)"
                ),
                "targetName": "VocelloiOSUITests",
                "testIdentifier": 1,
                "testIdentifierString": (
                    "VocelloiOSUITests-Runner (61727) encountered an error"
                ),
                "testName": "VocelloiOSUITests-Runner (61727) encountered an error",
            }],
        }), encoding="utf-8")
        output = self.root / "runner-bootstrap.json"
        result = MODULE.classify_xcui_bootstrap(log, summary, "run-1", output)
        self.assertEqual(result["testCaseCount"], 0)
        self.assertEqual(result["xcresultReportedTestCount"], 1)
        self.assertEqual(result["runnerFailureCount"], 1)

        actual_test_summary = json.loads(summary.read_text(encoding="utf-8"))
        actual_test_summary["testFailures"][0].update({
            "testName": "testVisibleJourney()",
            "testIdentifierString": "Suite/testVisibleJourney()",
            "testIdentifierURL": "test://example/Suite/testVisibleJourney",
        })
        summary.write_text(json.dumps(actual_test_summary), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ContractError, "zero launched"):
            MODULE.classify_xcui_bootstrap(log, summary, "run-1", output)

    def test_xcui_external_notification_classifier_is_narrow_and_source_bound(self):
        log = self.root / "xcui-notification.log"
        log.write_text(
            "Find: identifier == NotificationShortLookView\n"
            "Failed to construct element query matching interruption. "
            "Interrupting element BannerNotification, foreground application "
            "Application 'com.apple.springboard'\n",
            encoding="utf-8",
        )
        summary = self.root / "notification-summary.json"
        summary.write_text(json.dumps({
            "totalTestCount": 1,
            "testFailures": [{
                "failureText": "failed - Timed out after 15.0s waiting for Studio mode",
                "testIdentifierURL": "test://example/Suite/testJourney",
            }],
        }), encoding="utf-8")
        output = self.root / "notification-classification.json"
        result = MODULE.classify_xcui_external_interruption(
            log, summary, "run-1", output
        )
        self.assertEqual(result["status"], "infrastructure_external_interruption")
        self.assertEqual(result["testCaseCount"], 1)
        self.assertEqual(result["notificationKind"], "springboard_banner")

        log.write_text(log.read_text() + "generation failed\n", encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ContractError, "product or crash"):
            MODULE.classify_xcui_external_interruption(log, summary, "run-1", output)

        mixed_summary = json.loads(summary.read_text(encoding="utf-8"))
        mixed_summary.update({"totalTestCount": 2, "passedTests": 1})
        summary.write_text(json.dumps(mixed_summary), encoding="utf-8")
        with self.assertRaisesRegex(MODULE.ContractError, "zero launched"):
            MODULE.classify_xcui_bootstrap(log, summary, "run-1", output)

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
            "cleanup_startup_reliability_device_evidence() {",
            "startup_reliability_process_is_alive() {",
            "wait_startup_reliability_result() {",
            "snapshot_startup_reliability_crashes() {",
            "snapshot_startup_reliability_system_crashes() {",
            "collect_startup_reliability_system_crash_delta() {",
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

        shared_pull = source[
            source.index("pull_device_diagnostics_run() {"):
            source.index("pull_startup_reliability_run() {")
        ]
        scoped_pull = source[
            source.index("pull_startup_reliability_run() {"):
            source.index("wait_startup_reliability_result() {")
        ]
        self.assertIn('diagnostics/$run_id', shared_pull)
        self.assertIn("--timeout 60", shared_pull)
        self.assertIn('pull_device_diagnostics_run "$@"', scoped_pull)
        wait_body = source[
            source.index("wait_startup_reliability_result() {"):
            source.index("snapshot_startup_reliability_crashes() {")
        ]
        self.assertIn('pull_startup_reliability_run "$run_id" "$dest"', wait_body)
        self.assertIn('startup_reliability_process_is_alive "$dev" "$target_pid"', wait_body)
        self.assertIn("return 27", wait_body)
        self.assertNotIn('cmd_pull "$dest"', wait_body)

        cleanup_body = source[
            source.index("cleanup_startup_reliability_device_evidence() {"):
            source.index("wait_startup_reliability_result() {")
        ]
        self.assertIn('marker="$cleanup_pull/${run_id}.json"', cleanup_body)
        self.assertIn('--destination "$marker"', cleanup_body)
        self.assertNotIn('--destination "$cleanup_pull"', cleanup_body)

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
        self.assertIn("systemCrashLogs", crash_body)
        self.assertIn("compose-process-exit", command_body)

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
        model_download_pull = ui_source[
            ui_source.index("pull_ios_model_download_diagnostics() {"):
            ui_source.index("# Combine the smoke journey")
        ]
        self.assertIn('model-downloads/$journal/$run_id', model_download_pull)
        self.assertIn('for journal in trace attempts', model_download_pull)
        self.assertIn("--timeout 60", model_download_pull)
        self.assertIn("--timeout 30", model_download_pull)
        self.assertIn("local validation_status=0", model_download_pull)
        self.assertIn("|| validation_status=$?", model_download_pull)
        self.assertIn('return "$validation_status"', model_download_pull)
        self.assertIn('success.get("reusedBytes"', model_download_pull)
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
        self.assertIn("classify-xcui-bootstrap", ui_source)
        self.assertIn("exact-manual-rerun-command.txt", ui_source)


if __name__ == "__main__":
    unittest.main()
