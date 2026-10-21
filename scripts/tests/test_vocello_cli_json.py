#!/usr/bin/env python3
"""The vocello stdout reader: today's bare per-command JSON and the v1 envelope read alike.

The bare shapes are the ones `Sources/VocelloCLI/*.swift` emits under `--json` (GenerateJSON,
BatchJSON, the schemaVersion 2 FailedBatchJSON, LongFormBatchJSON, the list commands' arrays); the
envelopes are the contract's (`config/cli-contract/v1/`). The shell check runs the shipped
`scripts/lib/test_models.sh` functions over a stand-in `vocello`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from typing import Any
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import vocello_cli_json as cli  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "config" / "cli-contract" / "v1" / "examples"

GENERATE = {"generationID": "3b0e6f1c-5d2a-4c8e-9f17-2a6b8c4d0e93", "audioPath": "/tmp/take.wav",
            "durationSeconds": 4.5, "finishReason": "eos", "mode": "custom", "variant": "speed",
            "modelID": "pro_custom_speed"}
SPEAKERS = [{"id": "ryan", "group": "English", "displayName": "Ryan", "language": "english",
             "description": None, "isDefault": False}]
BATCH = {"count": 1, "items": [{"index": 0, "text": "One.", "audioPath": "/tmp/0.wav", "durationSeconds": 1.0,
                                "finishReason": "eos"}],
         "mode": "custom", "modelID": "pro_custom_speed", "variant": "speed", "wallSeconds": 2.0}


def envelope(*, ok: bool = True, command: str = "generate", result: Any = None,
             error: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"schemaVersion": 1, "ok": ok, "command": command, "requestID": "req-1", "result": result,
            "error": error, "warnings": [],
            "meta": {"vocelloVersion": "3.0.0", "build": "24", "contractRevision": 1, "durationMs": 5,
                     "replayed": False}}


def error(code: str, category: str, exit_code: int, *, retryable: bool = False,
          detail: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "category": category, "exitCode": exit_code, "message": f"{code} happened",
            "retryable": retryable, "retryAfterMs": None, "hint": None, "detail": detail}


def failed_batch(stop_status: str, stop_code: str) -> dict[str, Any]:
    return {"schemaVersion": 2, "mode": "custom", "variant": "speed", "modelID": "pro_custom_speed",
            "plannedCount": 3, "completedCount": 1, "wallSeconds": 3.0,
            "items": [{"index": 0, "generationID": "A", "status": "completed", "audioPath": "/tmp/0.wav",
                       "durationSeconds": 1.0, "finishReason": "eos"},
                      {"index": 1, "generationID": "B", "status": stop_status, "errorCode": stop_code},
                      {"index": 2, "generationID": "C", "status": "not_attempted"}]}


def dumps(value: Any) -> str:
    # emitJSON prints compact sorted-key JSON on one line.
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


class ResultTests(unittest.TestCase):
    def test_bare_and_enveloped_results_read_the_same(self) -> None:
        self.assertEqual(cli.read_result(dumps(GENERATE)), GENERATE)
        self.assertEqual(cli.read_result(dumps(envelope(result=GENERATE))), GENERATE)

    def test_list_rows_come_from_a_bare_array_or_the_wrapped_result(self) -> None:
        self.assertEqual(cli.rows(cli.read_result(dumps(SPEAKERS)), "speakers"), SPEAKERS)
        wrapped = envelope(command="speakers.list", result={"speakers": SPEAKERS})
        self.assertEqual(cli.rows(cli.read_result(dumps(wrapped)), "speakers"), SPEAKERS)
        with self.assertRaises(cli.VocelloCLIOutputError):
            cli.rows({"voices": []}, "speakers")

    def test_a_failed_envelope_raises_its_typed_error(self) -> None:
        failed = envelope(ok=False, error=error("model_not_installed", "precondition", 69,
                                                detail={"modelID": "pro_clone_quality"}))
        with self.assertRaises(cli.VocelloCLIError) as raised:
            cli.read_result(dumps(failed))
        failure = raised.exception
        self.assertEqual((failure.code, failure.exit_code, failure.category, failure.retryable),
                         ("model_not_installed", 69, "precondition", False))
        self.assertEqual(failure.message, "model_not_installed happened")
        self.assertEqual(failure.detail, {"modelID": "pro_clone_quality"})
        self.assertEqual((failure.command, failure.request_id, failure.result), ("generate", "req-1", None))

    def test_the_committed_example_envelopes_read(self) -> None:
        self.assertEqual(cli.read_result((EXAMPLES / "generate-success.json").read_text())["mode"], "custom")
        speakers = cli.rows(cli.read_result((EXAMPLES / "speakers-list.json").read_text()), "speakers")
        self.assertEqual([row["id"] for row in speakers], ["ryan", "vivian"])
        with self.assertRaises(cli.VocelloCLIError) as raised:
            cli.read_result((EXAMPLES / "invalid-mode.json").read_text())
        self.assertEqual((raised.exception.code, raised.exception.exit_code), ("invalid_input", 2))
        with self.assertRaises(cli.VocelloCLIError) as raised:
            cli.read_result((EXAMPLES / "cancelled-sigterm.json").read_text())
        self.assertEqual((raised.exception.exit_code, raised.exception.detail), (143, {"signal": "SIGTERM"}))

    def test_notes_before_the_json_line_are_skipped(self) -> None:
        self.assertEqual(cli.read_result("loading model…\n" + dumps(GENERATE)), GENERATE)
        self.assertEqual(cli.read_result("{broken\n" + dumps(SPEAKERS)), SPEAKERS)

    def test_empty_or_non_json_stdout_is_an_output_error(self) -> None:
        for text in ("", "   \n", "/tmp/take.wav\n", "{not json"):
            with self.subTest(text=text), self.assertRaises(cli.VocelloCLIOutputError):
                cli.read_result(text)

    def test_a_failed_envelope_without_an_error_is_unreadable(self) -> None:
        with self.assertRaises(cli.VocelloCLIOutputError):
            cli.read_result(dumps(envelope(ok=False)))

    def test_every_legacy_alias_names_a_v1_error_code(self) -> None:
        for old, new in cli.ERROR_CODE_ALIASES.items():
            self.assertNotIn(old, cli.error_table())
            self.assertIn(new, cli.error_table())


class BatchTests(unittest.TestCase):
    def test_a_complete_batch_reads_alike_bare_or_enveloped(self) -> None:
        for text in (dumps(BATCH), dumps(envelope(command="batch", result=BATCH))):
            output = cli.read_batch(text)
            self.assertTrue(output.complete)
            self.assertEqual(output.payload, BATCH)

    def test_a_stopped_bare_batch_keeps_its_rows_with_v1_codes(self) -> None:
        output = cli.read_batch(dumps(failed_batch("failed", "published_output_missing")))
        self.assertFalse(output.complete)
        self.assertEqual(output.payload["items"][1]["errorCode"], "output_missing")
        self.assertEqual(output.payload["plannedCount"], 3)
        assert output.error is not None
        self.assertEqual((output.error.code, output.error.exit_code, output.error.retryable),
                         ("batch_incomplete", 1, False))
        assert output.error.detail is not None
        self.assertEqual(output.error.detail["stoppedAt"],
                         {"index": 1, "status": "failed", "errorCode": "output_missing"})

    def test_a_stopped_bare_batch_reports_the_stop_the_contract_names(self) -> None:
        pressure = cli.read_batch(dumps(failed_batch("failed", "memory_pressure")), exit_code=75).error
        assert pressure is not None
        self.assertEqual((pressure.code, pressure.exit_code, pressure.category, pressure.retryable),
                         ("memory_pressure", 75, "transient", True))
        cancelled = cli.read_batch(dumps(failed_batch("cancelled", "cancelled"))).error
        assert cancelled is not None
        self.assertEqual((cancelled.code, cancelled.exit_code), ("cancelled", 130))
        generation = cli.read_batch(dumps(failed_batch("failed", "generation_failed"))).error
        assert generation is not None
        self.assertEqual(generation.code, "batch_incomplete")

    def test_a_stopped_enveloped_batch_keeps_its_rows(self) -> None:
        stopped = envelope(ok=False, command="batch", result=failed_batch("failed", "published_output_missing"),
                           error=error("batch_incomplete", "failure", 1))
        output = cli.read_batch(dumps(stopped))
        self.assertFalse(output.complete)
        self.assertEqual(output.payload["schemaVersion"], 2)
        self.assertEqual(output.payload["items"][1]["errorCode"], "output_missing")
        assert output.error is not None
        self.assertEqual(output.error.code, "batch_incomplete")

    def test_read_result_raises_for_a_stopped_batch_with_its_rows(self) -> None:
        with self.assertRaises(cli.VocelloCLIError) as raised:
            cli.read_result(dumps(failed_batch("failed", "generation_failed")))
        self.assertEqual(raised.exception.result["completedCount"], 1)

    def test_the_committed_stopped_batch_example_reads(self) -> None:
        output = cli.read_batch((EXAMPLES / "batch-memory-pressure.json").read_text())
        assert output.error is not None
        self.assertEqual((output.error.code, output.error.exit_code), ("memory_pressure", 75))
        self.assertEqual([row["status"] for row in output.payload["items"]],
                         ["completed", "failed", "not_attempted"])

    def test_a_failure_without_rows_or_a_non_object_is_not_a_batch(self) -> None:
        with self.assertRaises(cli.VocelloCLIError):
            cli.read_batch(dumps(envelope(ok=False, command="batch",
                                          error=error("model_not_installed", "precondition", 69))))
        with self.assertRaises(cli.VocelloCLIOutputError):
            cli.read_batch(dumps(SPEAKERS))

    def test_a_long_form_batch_reads_unchanged(self) -> None:
        long_form = {**BATCH, "longForm": True}
        self.assertEqual(cli.read_batch(dumps(envelope(command="batch", result=long_form))).payload, long_form)


class StreamTests(unittest.TestCase):
    def stream(self) -> str:
        return (EXAMPLES / "generate-stream.jsonl").read_text(encoding="utf-8")

    def test_the_records_and_the_final_envelope(self) -> None:
        events, final = cli.read_ndjson(self.stream())
        self.assertEqual(events[0]["type"], "started")
        self.assertEqual(len(events), 12)
        assert final is not None
        self.assertTrue(final["ok"])
        self.assertEqual(cli.unwrap(final)["mode"], "design")

    def test_read_result_accepts_a_stream(self) -> None:
        self.assertEqual(cli.read_result(self.stream())["modelID"], "pro_design_speed")

    def test_unknown_record_types_are_kept(self) -> None:
        lines = self.stream().splitlines()
        lines.insert(2, json.dumps({"schemaVersion": 1, "seq": 2, "t": 0.003, "requestID": "agent-run-42",
                                    "type": "heartbeat_v9", "data": {}}))
        events, final = cli.read_ndjson("\n".join(lines))
        self.assertIn("heartbeat_v9", [event["type"] for event in events])
        self.assertIsNotNone(final)

    def test_a_cut_stream_has_no_final_envelope(self) -> None:
        events, final = cli.read_ndjson("\n".join(self.stream().splitlines()[:-1]))
        self.assertEqual(len(events), 12)
        self.assertIsNone(final)

    def test_malformed_streams_are_refused(self) -> None:
        lines = self.stream().splitlines()
        for text in ("\n".join([*lines, lines[1]]),            # a record after the result
                     "not json\n" + lines[-1],                  # a line that is not JSON
                     "[1, 2]\n" + lines[-1],                    # a line that is not a record
                     json.dumps({"type": "result", "data": {}})):  # a result without an envelope
            with self.subTest(text=text[:40]), self.assertRaises(cli.VocelloCLIOutputError):
                cli.read_ndjson(text)


class TestModelsShellTests(unittest.TestCase):
    """scripts/lib/test_models.sh reads `models status` and `voices list` through the reader."""

    def run_shell(self, stdout: str, function: str, *arguments: str) -> int:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "build").mkdir()
            output = root / "stdout.json"
            output.write_text(stdout, encoding="utf-8")
            stub = root / "build" / "vocello"
            stub.write_text(f"#!/bin/sh\ncat {shlex.quote(str(output))}\n", encoding="utf-8")
            stub.chmod(0o755)
            script = (f". {shlex.quote(str(ROOT / 'scripts/lib/test_models.sh'))}\n"
                      f"test_models_init {shlex.quote(str(root))}\n"
                      f"{function} {' '.join(shlex.quote(argument) for argument in arguments)}\n")
            completed = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False,
                                       env={**os.environ, "HOME": temporary})
            return completed.returncode

    def test_model_install_state_reads_alike(self) -> None:
        rows = [{"id": "pro_custom_speed", "installed": True}, {"id": "pro_clone_speed", "installed": False}]
        for stdout in (dumps(rows), dumps(envelope(command="models.status", result={"models": rows}))):
            self.assertEqual(self.run_shell(stdout, "vocello_model_installed", "pro_custom_speed"), 0)
            self.assertEqual(self.run_shell(stdout, "vocello_model_installed", "pro_clone_speed"), 1)
        failed = envelope(ok=False, command="models.status", error=error("model_unknown", "not_found", 66))
        self.assertEqual(self.run_shell(dumps(failed), "vocello_model_installed", "pro_custom_speed"), 1)
        self.assertEqual(self.run_shell("", "vocello_model_installed", "pro_custom_speed"), 1)

    def test_the_clone_voice_check_reads_alike(self) -> None:
        voices = [{"id": "A_warm_elderly_woman", "name": "A_warm_elderly_woman", "audioPath": "/tmp/v.wav",
                   "hasTranscript": True, "qualityWarnings": []}]
        for stdout in (dumps(voices), dumps(envelope(command="voices.list", result={"voices": voices}))):
            self.assertEqual(self.run_shell(stdout, "vocello_clone_voice_present"), 0)
        self.assertEqual(self.run_shell(dumps(envelope(command="voices.list", result={"voices": []})),
                                        "vocello_clone_voice_present"), 1)
        self.assertEqual(self.run_shell("not json", "vocello_clone_voice_present"), 1)


if __name__ == "__main__":
    unittest.main()
