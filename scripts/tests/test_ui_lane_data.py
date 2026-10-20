#!/usr/bin/env python3
"""Tests for scripts/lib/ui_lane_data.py, the data steps of scripts/ui_test.sh."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import ui_lane_data as lane  # noqa: E402


def metadata_values(**overrides: str) -> dict[str, str]:
    values = dict.fromkeys(lane.RUN_METADATA_FIELDS, "")
    values.update(platform="macos", lane="benchmark", run_id="run-1", modes="custom,design",
                  lengths="short,long", warm="3", label="label-1", started_at="2026-10-19T00:00:00Z",
                  status="running")
    values.update(overrides)
    return values


class LaneDataCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def run_main(self, *arguments: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = lane.main(list(arguments))
        return status, out.getvalue(), err.getvalue()


class ArgumentCheckTests(LaneDataCase):
    def test_a_startup_parity_script_is_1_to_2000_non_nul_utf8_characters(self) -> None:
        for data in (b"hello", "é".encode() * 2000):
            lane.check_script_file(data)
        for data, message in ((b"\xff\xfe", "must be UTF-8"), (b"", "1...2000"), (b"  \n", "1...2000"),
                              (b"a\x00b", "1...2000"), (b"x" * 2001, "1...2000")):
            with self.subTest(data=data[:8]), self.assertRaisesRegex(lane.Refusal, message):
                lane.check_script_file(data)

    def test_the_matrix_takes_unique_known_modes_and_lengths_and_a_positive_warm_count(self) -> None:
        lane.check_matrix(" custom , design ", "short,medium,long", "1")
        for modes, lengths, warm, message in (
            ("custom,custom", "short", "1", "--modes"), ("custom,voice", "short", "1", "--modes"),
            ("", "short", "1", "--modes"), ("custom", "short,short", "1", "--lengths"),
            ("custom", "", "1", "--lengths"), ("custom", "short", "0", "at least 1"),
            ("custom", "short", "-x", "must be an integer"),
        ):
            with self.subTest(modes=modes, lengths=lengths, warm=warm), self.assertRaisesRegex(lane.Refusal, message):
                lane.check_matrix(modes, lengths, warm)

    def test_a_refusal_prints_the_runners_error_and_exits_1(self) -> None:
        status, stdout, stderr = self.run_main("matrix", "custom", "short", "-1")
        self.assertEqual((status, stdout, stderr), (1, "", "error: --warm must be at least 1\n"))
        script = self.directory / "script.txt"
        script.write_bytes(b"\xff")
        self.assertEqual(self.run_main("script-file", str(script))[2], "error: --script-file must be UTF-8\n")

    def test_a_wrong_argument_count_is_a_usage_error(self) -> None:
        self.assertEqual(self.run_main("matrix", "custom", "short")[0], 2)
        self.assertEqual(self.run_main("no-such-command")[0], 2)
        self.assertEqual(self.run_main()[0], 2)


class RunMetadataTests(LaneDataCase):
    def test_a_plain_run_records_its_matrix(self) -> None:
        payload = lane.run_metadata(metadata_values(), self.directory)
        self.assertEqual(payload, {
            "platform": "macos", "lane": "benchmark", "runID": "run-1", "modes": ["custom", "design"],
            "lengths": ["short", "long"], "warm": 3, "label": "label-1", "status": "running",
            "startedAt": "2026-10-19T00:00:00Z", "finishedAt": None, "exitCode": None, "schemaVersion": 2,
        })
        finished = lane.run_metadata(metadata_values(status="failed", finished_at="later", exit_code="65"),
                                     self.directory)
        self.assertEqual((finished["finishedAt"], finished["exitCode"]), ("later", 65))

    def test_focused_smoke_scenarios_narrow_the_matrix(self) -> None:
        cases: list[tuple[str, str, str, list[str]]] = [
            ("macos", "design-enrollment", "focused-smoke", ["design"]),
            ("macos", "clone-reference", "focused-smoke", ["clone"]),
            ("macos", "line-batch", "focused-smoke", ["custom"]),
            ("macos", "saved-voices-states", "focused-smoke", []),
            ("ios", "background-warmup", "focused-smoke", ["clone", "custom"]),
            ("ios", "long-form", "focused-smoke", ["custom"]),
            ("ios", "record-then-play", "focused-smoke", []),
            ("ios", "update-models", "device-maintenance", []),
        ]
        for platform, scenario, evidence, modes in cases:
            with self.subTest(platform=platform, scenario=scenario):
                payload = lane.run_metadata(metadata_values(platform=platform, lane="smoke", scenario=scenario),
                                            self.directory)
                self.assertEqual((payload["scenario"], payload["evidenceClass"], payload["modes"],
                                  payload["lengths"], payload["warm"]), (scenario, evidence, modes, [], 0))

    def test_a_scenario_only_tags_the_runs_that_define_it(self) -> None:
        exit_run = lane.run_metadata(metadata_values(platform="ios", lane="smoke", scenario="foreground-exit"),
                                     self.directory)
        self.assertEqual((exit_run["scenario"], exit_run["evidenceClass"], exit_run["warm"]),
                         ("foreground-exit", "focused-smoke", 3))
        other = lane.run_metadata(metadata_values(platform="macos", lane="smoke", scenario="anything"),
                                  self.directory)
        self.assertEqual((other["scenario"], other["modes"]), ("anything", ["custom", "design"]))
        benchmark = lane.run_metadata(metadata_values(platform="ios", scenario="long-form"), self.directory)
        self.assertNotIn("scenario", benchmark)

    def test_marketing_and_history_runs_carry_their_evidence_class(self) -> None:
        marketing = lane.run_metadata(metadata_values(lane="marketing", scenario="hero"), self.directory)
        self.assertEqual((marketing["evidenceClass"], marketing["scenario"], marketing["warm"],
                          marketing["lengths"], marketing["modes"]),
                         ("marketing-assets", "hero", 0, [], ["custom", "design"]))
        history = lane.run_metadata(metadata_values(scenario="history-transcript"), self.directory)
        self.assertEqual((history["evidenceClass"], history["modes"]), ("read-only-history-observation", []))

    def test_control_audit_and_resume_fields(self) -> None:
        payload = lane.run_metadata(metadata_values(
            audit_source_id="fp", control_scenario="all", control_resume_take_start="12",
            control_take_limit="40", control_resume="prior-run", control_resume_run_ids="r1,r2"), self.directory)
        self.assertEqual({key: payload[key] for key in (
            "treeFingerprint", "controlAuditScenario", "controlObservationSchemaVersion", "controlEvidenceVersion",
            "controlTakeStart", "controlTakeLimit", "resumedFrom", "resumeRunIDs")},
            {"treeFingerprint": "fp", "controlAuditScenario": "all", "controlObservationSchemaVersion": 2,
             "controlEvidenceVersion": 2, "controlTakeStart": 12, "controlTakeLimit": 40,
             "resumedFrom": "prior-run", "resumeRunIDs": ["r1", "r2"]})

    def test_a_candidate_run_reads_the_identity_beside_run_json(self) -> None:
        values = metadata_values(platform="ios", lane="smoke", candidate_evidence="candidate.json")
        without = lane.run_metadata(values, self.directory)
        self.assertEqual((without["lane"], without["evidenceClass"], without["modes"]),
                         ("candidate-smoke", "preinstalled-candidate-black-box", []))
        self.assertNotIn("candidateIdentity", without)
        (self.directory / "candidate-identity.json").write_text(json.dumps({"build": "3.0 (12)"}))
        self.assertEqual(lane.run_metadata(values, self.directory)["candidateIdentity"], {"build": "3.0 (12)"})

    def test_the_command_writes_sorted_json_atomically(self) -> None:
        path = self.directory / "nested" / "run.json"
        values = metadata_values(label="-starts-with-a-dash")
        status, _, _ = self.run_main("run-metadata", str(path), *values.values())
        self.assertEqual(status, 0)
        text = path.read_text()
        self.assertEqual(json.loads(text)["label"], "-starts-with-a-dash")
        self.assertTrue(text.endswith("}\n"))
        self.assertEqual(text, json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n")
        self.assertEqual([entry.name for entry in path.parent.iterdir()], ["run.json"])


class LongFormSummaryTests(LaneDataCase):
    def support(self, segments: list[float], rows: list[dict[str, Any]]) -> Path:
        support = self.directory / "support"
        (support / "outputs/CustomVoice").mkdir(parents=True)
        (support / "diagnostics/engine").mkdir(parents=True)
        (support / "outputs/CustomVoice/long_form_manifest_one.json").write_text(json.dumps({
            "assembly": {"outputFrameCount": int(24_000 * sum(segments)), "sampleRate": 24_000},
            "execution": {"segments": [{"audioDurationSeconds": seconds} for seconds in segments]},
        }))
        lines = [json.dumps(row) for row in rows] + ["not json", ""]
        (support / "diagnostics/engine/generations.jsonl").write_text("\n".join(lines))
        (support / "diagnostics/generations-merged.jsonl").write_text("{}\n")
        return support

    def test_the_segment_trend_matches_engine_rows_by_audio_duration(self) -> None:
        support = self.support([10, 12], [
            {"timing": {"audioSeconds": 3}},
            {"timing": {"audioSeconds": 10.2}, "memory": {"physFootprintStartMB": 90, "physFootprintEndMB": 100}},
            {"timing": {"audioSeconds": 11.9}, "memory": {"physFootprintEndMB": 110, "physFootprintPeakMB": 130}},
        ])
        run = self.directory / "run"
        lines = lane.long_form_summary(44.0, str(run), str(support))
        assert lines is not None
        self.assertEqual(lines[0], "long-form project: 2 segments, audio 22.0s, "
                                   "wall 44.0s (plan+stream+QC+assembly), project RTF 2.00")
        self.assertIn("segment  0: audio=  10.2s cumulative=   10.2s start=   90.0 end=  100.0 peak=    nan",
                      lines[2])
        self.assertEqual(lines[-1], "  end-footprint growth first→last: +10.0 MB (+10.00% of first segment end)")
        self.assertEqual(sorted(path.name for path in (run / "diagnostics").iterdir()),
                         ["engine-generations.jsonl", "generations-merged.jsonl"])

    def test_rows_that_do_not_fit_the_durations_are_not_this_runs_segments(self) -> None:
        support = self.support([10, 12], [{"timing": {"audioSeconds": 40}}, {"timing": {"audioSeconds": 50}}])
        lines = lane.long_form_summary(10.0, str(self.directory / "run"), str(support))
        assert lines is not None
        self.assertIn("no contiguous engine-row window matched", lines[-1])

    def test_without_a_manifest_nothing_is_written(self) -> None:
        run = self.directory / "run"
        self.assertIsNone(lane.long_form_summary(1.0, str(run), str(self.directory / "empty")))
        self.assertFalse(run.exists())

    def test_the_command_writes_the_summary_and_echoes_each_line(self) -> None:
        support = self.support([8], [])
        out = self.directory / "summary.txt"
        status, stdout, _ = self.run_main("long-form-summary", "4", str(out), str(self.directory / "run"),
                                          str(support))
        self.assertEqual(status, 0)
        self.assertEqual(out.read_text(), "long-form project: 1 segments, audio 8.0s, "
                                          "wall 4.0s (plan+stream+QC+assembly), project RTF 0.50\n")
        self.assertEqual(stdout, "==> " + out.read_text())


class VirtualMicTests(LaneDataCase):
    def test_the_fixture_is_12_seconds_of_mono_16_bit_24khz_speech_like_audio(self) -> None:
        path = self.directory / "mic.wav"
        self.assertEqual(self.run_main("virtual-mic", str(path))[0], 0)
        with wave.open(str(path), "rb") as stream:
            self.assertEqual((stream.getnchannels(), stream.getsampwidth(), stream.getframerate(),
                              stream.getnframes()), (1, 2, 24_000, 288_000))
            frames = stream.readframes(stream.getnframes())
        self.assertEqual(frames, lane.virtual_mic_frames())
        self.assertGreater(len(set(frames)), 200)


if __name__ == "__main__":
    unittest.main()
