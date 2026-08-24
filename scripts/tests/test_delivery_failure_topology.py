import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "delivery_failure_topology", ROOT / "scripts" / "delivery_failure_topology.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class DeliveryFailureTopologyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def write_json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def write_jsonl(self, name, rows):
        path = self.root / name
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        return path

    def test_matrix_qc_failure_is_post_generation_but_missing_audio_is_unknown(self):
        path = self.write_json("matrix.json", {
            "generationFailures": [
                {"generationID": "A", "takeIndex": 1, "cell": "custom-speed",
                 "reasonCode": "fast_qc_dropout", "rejectedOutputFileName": "secret.wav"},
                {"generationID": "B", "takeIndex": 2, "cell": "custom-speed",
                 "reasonCode": "process_failed"},
            ]
        })
        rows = MODULE.matrix_attempts(path)
        self.assertEqual(rows[0].classification, "post_generation_qc")
        self.assertEqual(rows[1].classification, "unmaterialized_unknown")
        report = MODULE.build_report(rows)
        encoded = json.dumps(report)
        self.assertNotIn("secret.wav", encoded)

    def test_typed_boundaries_distinguish_startup_and_post_audio(self):
        digest = "a" * 64
        telemetry = self.write_jsonl("telemetry.jsonl", [
            {"generationID": "G1", "finishReason": "failed", "stageMarks": [
                {"stage": "startup.request_validated"}, {"stage": "startup.engine_opened"}],
             "requestReceipt": {"requestIdentityDigest": digest, "retryAttempt": 0}},
            {"generationID": "G2", "finishReason": "failed", "stageMarks": [
                {"stage": "startup.first_decoded_audio_frame"}]},
        ])
        rows = MODULE.telemetry_attempts(telemetry, None)
        self.assertEqual(rows[0].classification, "pre_audio_startup")
        self.assertEqual(rows[1].classification, "post_generation_qc")

    def test_timeout_cancel_memory_and_journal_v2_v3(self):
        journal = self.write_jsonl("journal.jsonl", [
            {"schemaVersion": 2, "timestamp": "2026-08-23T00:00:00Z",
             "errorCode": "generation.cancelled", "classification": "cancelled",
             "stage": "stream_startup"},
            {"schemaVersion": 3, "timestamp": "2026-08-23T00:00:01Z",
             "errorCode": "memory.insufficient", "classification": "memory",
             "stage": "model_load", "requestIdentityDigest": "b" * 64,
             "retryAttempt": 1},
        ])
        rows = MODULE.journal_attempts(journal)
        self.assertEqual([row.classification for row in rows], ["cancelled", "memory_failure"])
        self.assertIsNone(rows[0].request_digest)
        self.assertEqual(rows[1].request_digest, "b" * 64)

    def test_explicit_timeout_and_crash_are_classified_without_audio_inference(self):
        telemetry = self.write_jsonl("terminal.jsonl", [
            {"generationID": "T", "finishReason": "startup_timeout", "stageMarks": []},
            {"generationID": "C", "finishReason": "process_crash", "stageMarks": []},
        ])
        rows = MODULE.telemetry_attempts(telemetry, None)
        self.assertEqual([row.classification for row in rows], ["timeout", "crash"])

    def test_experiment_nonzero_exit_without_audio_remains_unknown(self):
        state = self.write_json("execution-state.json", {
            "takes": {
                "cell-a": {"status": "failed", "returnCode": 1,
                           "stderrSHA256": "c" * 64},
                "cell-b": {"status": "complete", "generationID": "G",
                           "audioSHA256": "d" * 64},
            }
        })
        rows = MODULE.experiment_attempts(state)
        self.assertEqual(rows[0].classification, "unmaterialized_unknown")
        self.assertEqual(rows[1].classification, "success")

    def test_cross_run_telemetry_is_rejected(self):
        telemetry = self.write_jsonl("telemetry.jsonl", [
            {"generationID": "G", "finishReason": "failed", "stageMarks": [],
             "notes": {"benchRunID": "other"}},
        ])
        with self.assertRaisesRegex(ValueError, "different run"):
            MODULE.telemetry_attempts(telemetry, "expected")

    def test_cli_writes_privacy_safe_json_and_markdown(self):
        state = self.write_json("state.json", {"takes": {"cell": {"status": "failed"}}})
        out = self.root / "out"
        self.assertEqual(MODULE.main([
            "--experiment", str(state), "--output-dir", str(out)
        ]), 0)
        report = json.loads((out / "failure-topology.json").read_text())
        self.assertEqual(report["status"], "complete")
        self.assertFalse(report["policy"]["missingAudioAloneIsStartupFailure"])
        self.assertTrue((out / "failure-topology.md").is_file())


if __name__ == "__main__":
    unittest.main()
