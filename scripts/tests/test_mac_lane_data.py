#!/usr/bin/env python3
"""Tests for scripts/lib/mac_lane_data.py, the data steps of scripts/macos_test.sh."""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import mac_lane_data as lane  # noqa: E402

ROOT = "/repo"


def coverage_file(name: str, covered: int, count: int) -> dict[str, Any]:
    return {"filename": name, "summary": {"lines": {"covered": covered, "count": count}}}


class LaneDataCase(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)

    def write(self, name: str, payload: Any) -> str:
        path = self.directory / name
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8")
        return str(path)

    def run_main(self, *arguments: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = lane.main(list(arguments))
        return status, out.getvalue(), err.getvalue()


class CoverageSummaryTests(LaneDataCase):
    DATA = {"data": [{"files": [
        coverage_file(f"{ROOT}/Sources/QwenVoiceCore/A.swift", 30, 40),
        coverage_file(f"{ROOT}/Sources/QwenVoiceCore/Sub/B.swift", 10, 10),
        coverage_file(f"{ROOT}/Sources/iOS/C.swift", 0, 50),
        coverage_file(f"{ROOT}/Packages/VocelloQwen3Core/Sources/D.swift", 5, 10),
        coverage_file(f"{ROOT}/Tools/E.swift", 1, 2),
        coverage_file(f"{ROOT}/build/cache/swiftpm/checkouts/mlx/F.swift", 100, 100),
        coverage_file("/elsewhere/G.swift", 7, 7),
    ]}]}

    def test_sources_and_packages_group_by_two_components_and_the_rest_by_one(self) -> None:
        lines, percent, covered, count = lane.coverage_lines(self.DATA, ROOT)
        tops = [line.split()[-1] for line in lines[:-1]]
        self.assertEqual(tops, ["Packages/VocelloQwen3Core", "Sources/QwenVoiceCore", "Sources/iOS", "Tools"])
        self.assertEqual(lines[1], "  80.0%       40/50       Sources/QwenVoiceCore")
        self.assertEqual((covered, count), (46, 112))
        self.assertAlmostEqual(percent, 100.0 * 46 / 112)
        self.assertTrue(lines[-1].endswith("TOTAL (lines, repository sources)"))

    def test_the_build_tree_and_files_outside_the_root_are_not_repository_sources(self) -> None:
        lines = lane.coverage_lines(self.DATA, ROOT + "/")[0]
        self.assertFalse(any("build" in line or "elsewhere" in line for line in lines))

    def test_no_lines_reports_zero_percent(self) -> None:
        lines, percent, covered, count = lane.coverage_lines({"data": []}, ROOT)
        self.assertEqual((percent, covered, count), (0.0, 0, 0))
        self.assertEqual(len(lines), 1)

    def test_the_command_writes_the_summary_and_prints_the_total(self) -> None:
        out = self.directory / "summary.txt"
        status, stdout, _ = self.run_main("coverage-summary", self.write("c.json", self.DATA), str(out), ROOT)
        self.assertEqual(status, 0)
        self.assertEqual(stdout, "coverage=41.1% lines (46/112)\n")
        self.assertEqual(len(out.read_text(encoding="utf-8").splitlines()), 5)


class LanguageBenchTests(LaneDataCase):
    MATRIX = {"cells": [
        {"mode": "custom", "quick": True},
        {"mode": "design", "variant": "quality"},
        {"mode": "custom", "variant": "speed", "quick": True},
    ]}
    CORPUS = {"languages": [{"id": "en", "script": "Hello there."}, {"id": "fr", "script": "Bonjour."}]}

    def take(self, **fields: Any) -> dict[str, Any]:
        base = {"cellID": "en-custom", "mode": "custom", "seed": 7, "scriptLang": "en",
                "customSpeakerID": "ryan"}
        base.update(fields)
        return base

    def test_the_quick_subset_needs_only_its_cells_models(self) -> None:
        self.assertEqual(lane.language_models(self.MATRIX, "quick"), ["pro_custom_speed"])
        self.assertEqual(lane.language_models(self.MATRIX, "full"), ["pro_custom_speed", "pro_design_quality"])

    def test_each_take_is_one_unit_separated_line_with_defaults(self) -> None:
        plan = {"takes": [
            self.take(),
            self.take(cellID="fr-design", mode="design", variant="quality", uiHint="fr", scriptLang="fr",
                      customSpeakerID=None, designInstruction="A calm narrator."),
        ]}
        lines = lane.language_take_lines(plan, self.CORPUS)
        self.assertEqual([line.split("\x1f") for line in lines], [
            ["en-custom", "custom", "speed", "auto", "7", "ryan", "", "Hello there."],
            ["fr-design", "design", "quality", "fr", "7", "", "A calm narrator.", "Bonjour."],
        ])

    def test_a_field_holding_a_separator_or_newline_refuses(self) -> None:
        for brief in ("two\nlines", "unit\x1fseparator"):
            with self.subTest(brief=brief), self.assertRaisesRegex(ValueError, "en-custom"):
                lane.language_take_lines({"takes": [self.take(designInstruction=brief)]}, self.CORPUS)

    def test_the_takes_command_exits_1_with_the_refusal(self) -> None:
        plan = self.write("plan.json", {"takes": [self.take(customSpeakerID="a\nb")]})
        status, stdout, stderr = self.run_main("language-takes", plan, self.write("corpus.json", self.CORPUS))
        self.assertEqual((status, stdout), (1, ""))
        self.assertIn("a planned field contains a separator", stderr)

    def test_the_models_command_prints_one_id_per_line(self) -> None:
        status, stdout, _ = self.run_main("language-models", self.write("m.json", self.MATRIX), "full")
        self.assertEqual((status, stdout), (0, "pro_custom_speed\npro_design_quality\n"))


class FieldTests(LaneDataCase):
    def test_a_scalar_prints_as_python_would(self) -> None:
        path = self.write("plan.json", {"takeCount": 12, "batchCount": 3})
        self.assertEqual(self.run_main("field", path, "takeCount")[1], "12\n")
        self.assertEqual(self.run_main("field", path, "batchCount")[1], "3\n")

    def test_a_list_joins_with_the_separator(self) -> None:
        path = self.write("policy.json", {"defaultCells": ["custom", "design", "clone"]})
        self.assertEqual(self.run_main("field", path, "defaultCells", "--join", ",")[1], "custom,design,clone\n")

    def test_a_missing_key_fails(self) -> None:
        with self.assertRaises(KeyError):
            lane.field_text({}, "takeCount")


class TakesCountsTests(LaneDataCase):
    def test_counts_introspection_and_generation_limit_failures(self) -> None:
        manifest = {
            "counts": {"generated": 8, "rejected": 1, "failed": 2, "missing": 0},
            "introspection": {"bound": 7, "unbound": 1},
            "takes": [
                {"status": "generated"},
                {"status": "failed", "failure": {"errorCode": "generation.incomplete"}},
                {"status": "failed", "failure": {"errorCode": "engine.crash"}},
                {"status": "failed", "failure": None},
            ],
        }
        self.assertEqual(lane.takes_counts(manifest), ["8", "1", "2", "0", "7/8", "1"])
        status, stdout, _ = self.run_main("takes-counts", self.write("manifest.json", manifest))
        self.assertEqual((status, stdout), (0, "8 1 2 0 7/8 1\n"))

    def test_absent_introspection_reads_as_unknown(self) -> None:
        manifest = {"counts": {"generated": 0, "rejected": 0, "failed": 0, "missing": 0}, "takes": []}
        self.assertEqual(lane.takes_counts(manifest)[4], "?/0")


class AudioQCTests(LaneDataCase):
    def test_only_fail_verdicts_are_failures(self) -> None:
        rows = [
            json.dumps({"generationID": "a", "audioQC": {"verdict": "pass"}}),
            "",
            json.dumps({"generationID": "b", "audioQC": {"verdict": "fail"}}),
            json.dumps({"generationID": "c", "audioQC": {"verdict": "warn"}}),
            json.dumps({"generationID": "d"}),
            json.dumps({"audioQC": {"verdict": "fail"}}),
        ]
        self.assertEqual(lane.audio_qc_failures(rows), ["b", "?"])

    def test_the_command_passes_clean_rows_and_fails_with_the_ids(self) -> None:
        clean = self.write("clean.jsonl", json.dumps({"generationID": "a", "audioQC": {"verdict": "pass"}}) + "\n")
        self.assertEqual(self.run_main("audio-qc", clean), (0, "gate bench: audioQC pass on all rows\n", ""))
        failing = self.write("fail.jsonl", "\n".join(
            json.dumps({"generationID": name, "audioQC": {"verdict": "fail"}}) for name in ("x", "y")))
        status, stdout, stderr = self.run_main("audio-qc", failing)
        self.assertEqual((status, stdout), (1, ""))
        self.assertEqual(stderr, "gate bench: audioQC fail on 2 row(s): x, y\n")


if __name__ == "__main__":
    unittest.main()
