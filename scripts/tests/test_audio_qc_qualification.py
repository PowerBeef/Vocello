#!/usr/bin/env python3
"""The M1 "measure the present" report of the audio-QC qualification engine."""

from __future__ import annotations

import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_qualification as m1  # noqa: E402
from lib.qc_qualification import injectors  # noqa: E402


def take(index: int, *, version: int, verdict: str = "pass", codes: list[str] | None = None,
         seed: int | None = None, discontinuity: float = 0.0, duration: float = 4.0,
         digest: str | None = None) -> dict:
    entry = {
        "cell": "custom/medium", "takeIndex": index, "generationID": f"G{index}",
        "output": {"durationSeconds": duration, **({"fileDigest": digest} if digest else {})},
        "audioQC": {"algorithmVersion": version, "verdict": verdict, "warningCodes": codes or [],
                    "metrics": {"discontinuityCount": discontinuity, "clipCount": 0.0, "dcOffset": 0.001,
                                "longestSilenceMS": 300.0, "nonFiniteCount": 0.0}},
    }
    if seed is not None:
        entry.update(seed=seed, modelRevision="r1", modelQuantization="4-bit")
    return entry


def write_records(root: Path) -> None:
    (root / "engine-generation").mkdir(parents=True)
    first = {"run": {"id": "run-a", "kind": "engine-generation"}, "takes": [
        take(1, version=8), take(2, version=8, verdict="warn", codes=["dropout:1300ms", "written-output-warn"]),
        take(3, version=8, discontinuity=100.0), take(4, version=3),
    ]}
    second = {"historyRecord": {"run": {"id": "run-b"}, "takes": [
        take(5, version=8, seed=11), take(6, version=8, seed=11), {"cell": "no-qc"},
        # The same published WAV in two records is one family, whatever its take ids.
        take(7, version=8, digest="d" * 64, discontinuity=100.0), take(8, version=8, digest="d" * 64),
    ]}}
    (root / "engine-generation" / "a.json").write_text(json.dumps(first), encoding="utf-8")
    (root / "engine-generation" / "b.json").write_text(json.dumps(second), encoding="utf-8")


class MetaEvaluationTests(unittest.TestCase):
    report: dict
    records: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        cls.records = tempfile.TemporaryDirectory()
        write_records(Path(cls.records.name))
        cls.report = m1.meta_evaluation(sources=3, stratum_sources=2, seed=7, records=Path(cls.records.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.records.cleanup()

    def test_the_report_covers_every_injector_variant_and_stratum(self) -> None:
        procedural = self.report["procedural"]
        self.assertEqual(self.report["schema"], "vocello.audioqc.meta-evaluation/1")
        self.assertTrue(self.report["reportOnly"])
        self.assertEqual(self.report["subject"]["calibration"], "legacy-unqualified")
        self.assertEqual(set(procedural["clean"]), {"modal", "quiet", "breathy", "long-pause", "high-f0"})
        self.assertEqual(procedural["clean"]["modal"]["units"], 3)
        self.assertEqual(procedural["clean"]["quiet"]["units"], 2)
        rows = {(row["injector"], row["variant"]) for row in procedural["detection"] + procedural["shams"]}
        self.assertEqual(rows, {(injector.key, variant.name) for injector in injectors.CATALOG.values()
                                for variant in injector.variants})
        self.assertEqual(set(m1.TARGETS), set(injectors.CATALOG))
        self.assertEqual(len(procedural["abstention"]), 12)

    def test_measured_facts_about_fast_qc_v8(self) -> None:
        rows = {(row["injector"], row["variant"]): row for row in self.report["procedural"]["detection"]}
        # A 2 s zeroed span fails; clicks at full scale and 50/s fail; a 10 s tail fails.
        self.assertEqual(rows[("SIG-DROP@2", "severe")]["fail"]["events"], 3)
        # Flattening below full scale is invisible to v8, which counts samples beyond it.
        self.assertEqual(rows[("SIG-CLIP@2", "severe")]["alarm"]["events"], 0)
        self.assertEqual(rows[("SIG-CLIP@2", "over-range-moderate")]["target"]["events"], 3)
        self.assertEqual(rows[("SIG-CLICK@1", "severe")]["target"]["events"], 3)
        self.assertEqual(rows[("SIG-SIL@1", "severe")]["target"]["events"], 3)
        # Amplitude-only: truncation, deletions and identity swaps are invisible to v8.
        for key in ("BND-TRUNC@1", "CNT-DEL@1", "IDN-SWAP@1", "PRS-OCT@1"):
            self.assertEqual(rows[(key, "severe")]["alarm"]["events"], 0, key)
            self.assertIsNone(rows[(key, "severe")]["target"])
        shams = {(row["injector"], row["variant"]): row for row in self.report["procedural"]["shams"]}
        self.assertEqual(shams[("SIG-CLICK@1", "sham")]["alarm"]["events"], 0)
        self.assertTrue(shams[("SIG-CLICK@1", "sham")]["a4"]["overlaps"])
        abstention = {entry["fixture"]: entry for entry in self.report["procedural"]["abstention"]}
        self.assertEqual(abstention["digital-silence"]["verdict"], "fail")
        self.assertEqual(abstention["nan-bearing"]["flags"], ["nonfinite"])

    def test_a4_compares_target_flags_on_the_same_sources(self) -> None:
        shams = {(row["injector"], row["variant"]): row for row in self.report["procedural"]["shams"]}
        # The clipping sham is the identity; peak normalization is a labeled control.
        self.assertEqual(shams[("SIG-CLIP@2", "sham")]["alarm"]["events"], 0)
        control = shams[("SIG-CLIP@2", "control-peak-normalized")]
        self.assertEqual((control["severity"], control["a4"]["basis"]), ("control", "target-flags"))
        self.assertEqual(control["target"]["events"], 0)
        clamped = control.get("clickClampedSamples")
        if clamped:
            self.assertLessEqual(clamped["insideFricativeBursts"], clamped["clamped"])
        # Source 0 declares no pause, so the natural-pause control runs on the other two only.
        pause = shams[("SIG-DROP@2", "control-natural-pause")]
        self.assertEqual((pause["units"], pause["notApplicable"]), (2, 1))
        self.assertEqual(pause["a4"]["cleanTarget"]["units"], 2)
        self.assertEqual(shams[("BND-TRUNC@1", "sham")]["a4"]["basis"], "not-applicable")
        self.assertIsNone(shams[("BND-TRUNC@1", "sham")]["a4"]["overlaps"])
        self.assertEqual(self.report["procedural"]["shamsPooled"]["basis"], "target-flags")

    def test_committed_evidence_is_replayed_read_only(self) -> None:
        committed = self.report["committed"]
        self.assertEqual((committed["records"], committed["takes"]), (2, 8))
        v8 = committed["byAlgorithmVersion"]["8"]
        # Two seeded takes of one cell, seed and model are one family; two takes of
        # one published WAV digest merge into one.
        self.assertEqual((v8["takes"], v8["declaredFamilies"], v8["families"]), (7, 6, 5))
        self.assertEqual((v8["takesWithDigest"], v8["distinctDigests"]), (2, 1))
        self.assertEqual(v8["publishedVerdicts"], {"pass": 6, "warn": 1})
        self.assertEqual((v8["flags"]["dropout"]["events"], v8["flags"]["dropout"]["units"]), (1, 5))
        self.assertNotIn("written-output-warn", v8["flags"])
        self.assertEqual((v8["warn"]["familyLevel"]["events"], v8["warn"]["familyLevel"]["units"]), (1, 5))
        # 100 clamped samples in 4 s is a 0.1% fraction: above the warn bound, under the fail bound.
        # Take 3 and the merged digest family each carry one: two families of five.
        clicks = v8["v8BoundReplay"]["clicks"]
        self.assertEqual((clicks["takes"], clicks["warnOrWorse"]["events"], clicks["warnOrWorse"]["units"],
                          clicks["fail"]["events"]), (7, 2, 5, 0))
        self.assertEqual(committed["byAlgorithmVersion"]["3"]["takes"], 1)

    def test_the_report_is_deterministic_and_renders(self) -> None:
        again = m1.meta_evaluation(sources=3, stratum_sources=2, seed=7, records=Path(self.records.name))
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(self.report, sort_keys=True))
        text = m1.markdown(self.report)
        self.assertTrue(text.startswith("<!-- Generated by scripts/audio_qc_qualification.py"))
        self.assertIn("| SIG-CLICK@1 | severe | severe | clicks | 3/3 |", text)
        self.assertEqual(len(self.report["headline"]), len(m1.headline(self.report)))

    def test_the_command_writes_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "m1"
            with redirect_stdout(StringIO()) as output:
                code = m1.main(["meta-evaluation", "--sources", "1", "--stratum-sources", "1", "--no-records",
                                "--out", str(out)])
            self.assertEqual(code, 0)
            written = json.loads((out / "meta-evaluation.json").read_text(encoding="utf-8"))
            self.assertIsNone(written["committed"])
            self.assertTrue((out / "meta-evaluation.md").read_text(encoding="utf-8").strip())
            self.assertIn("wrote", output.getvalue())
            with redirect_stdout(StringIO()) as catalog:
                self.assertEqual(m1.main(["catalog"]), 0)
            self.assertEqual(len(json.loads(catalog.getvalue())["injectors"]), len(injectors.CATALOG))
            with redirect_stdout(StringIO()) as table:
                self.assertEqual(m1.main(["sample-sizes"]), 0)
            self.assertEqual(json.loads(table.getvalue())[-1]["clopperPearson"]["0"], 299)


if __name__ == "__main__":
    unittest.main()
