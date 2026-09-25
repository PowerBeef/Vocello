#!/usr/bin/env python3
"""The offline audio-QC bound screen replays evidence and never qualifies a bound."""

from __future__ import annotations

from array import array
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import derive_audio_qc_bounds as bounds  # noqa: E402

def record(run_id: str, finished: str, takes: list[dict], *, kind: str = "ui-generation",
           platform: str = "macos") -> dict:
    return {"run": {"id": run_id, "kind": kind, "platform": platform, "finishedAt": finished},
            "inputs": {}, "takes": takes}


def take(length: str, seconds: float, *, cell: str = "custom/medium/warm#0", verdict: str = "pass",
         clamps: int | None = None) -> dict:
    value = {"cell": cell, "length": length, "output": {"durationSeconds": seconds},
             "metrics": {}, "audioQC": {"instabilityVerdict": verdict, "metrics": {}}}
    if clamps is not None:
        value["metrics"]["discontinuityCount"] = float(clamps)
    return value


class MirroredConstantsTests(unittest.TestCase):
    def test_the_mirror_holds_the_documented_values(self) -> None:
        """The tool never reads Swift source (release rule): it mirrors the values
        docs/reference/audio-qc-engineering.md documents under "Replay constants",
        and a qualified Swift change updates both with this pin."""
        self.assertEqual(bounds.SPEAKING_RATE_BANDS, {
            "alphabetic": {"slowSecondsPerUnit": 0.145, "minimumJudgedUnits": 20},
            "chinese": {"slowSecondsPerUnit": 0.45, "minimumJudgedUnits": 8},
            "japanese": {"slowSecondsPerUnit": 0.40, "minimumJudgedUnits": 8},
            "korean": {"slowSecondsPerUnit": 0.40, "minimumJudgedUnits": 8},
        })
        self.assertEqual(bounds.BENCHMARK_TEXT_UNITS,
                         {"short": 28, "medium": 91, "long": 278, "ios-ui-long": 126})
        self.assertEqual(
            (bounds.ENGINE_SAMPLE_RATE, bounds.SLEW_CLAMP, bounds.CLICK_EVENT_GAP_SAMPLES,
             bounds.CLICK_ENVELOPE_COEFFICIENT, bounds.LOW_ENERGY_CLICK_ENVELOPE),
            (24_000, 0.42, 240, 1.0 / 240.0, 0.02),
        )
        self.assertEqual(bounds.CLICK_FRACTION_BOUNDS, {"warnFraction": 0.0005, "failFraction": 0.005})


class SpeakingRateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bands = bounds.SPEAKING_RATE_BANDS

    def report(self, records: list[tuple[str, dict]]) -> dict:
        rows, skipped = bounds.speaking_rate_rows(
            records, text_units_by_length=bounds.BENCHMARK_TEXT_UNITS,
            language_matrix={"cells": []}, language_corpus={"languages": []},
            corpus_digest="0" * 64, cut="2026-09-25T08:35:53Z",
        )
        return bounds.speaking_rate_report(rows, self.bands, skipped, "2026-09-25T08:35:53Z")

    def test_a_run_on_warns_and_the_untouched_split_stays_apart(self) -> None:
        seeded = record("seeded", "2026-09-14T05:18:14Z", [
            take("medium", 6.5), take("medium", 6.6), take("medium", 14.96),  # 0.164 s per unit
            take("short", 2.0, cell="custom/short/warm#0"),  # 28 units, well under the band
        ])
        later = record("later", "2026-09-25T20:05:52Z", [take("medium", 6.4)])
        overhead = record("overhead", "2026-07-01T00:00:00Z", [take("medium", 30.0)], kind="telemetry-overhead")
        report = self.report([("seeded.json", seeded), ("later.json", later), ("overhead.json", overhead)])
        self.assertEqual(report["takes"], 5)
        self.assertEqual(report["skipped"], {"kind-telemetry-overhead": 1})
        self.assertEqual([row["record"] for row in report["warned"]], ["seeded.json"])
        self.assertAlmostEqual(report["warned"][0]["secondsPerUnit"], round(14.96 / 91, 4))
        alphabetic = report["classes"]["alphabetic"]
        self.assertEqual((alphabetic["calibration"]["count"], alphabetic["untouched"]["count"]), (4, 1))
        self.assertEqual(alphabetic["warned"], {"calibration": 1, "untouched": 0})
        first = alphabetic["candidates"][0]
        self.assertEqual(first["failSecondsPerUnit"], round(0.145 * 1.25, 4))
        # The run-on at 0.164 s per unit is under every candidate fail bound.
        self.assertEqual(first["warnedTakesItWouldFail"], 0)

    def test_the_screen_never_qualifies_a_bound(self) -> None:
        report = self.report([("later.json", record("later", "2026-10-01T00:00:00Z", [take("medium", 6.5)] * 70))])
        qualification = report["qualification"]
        self.assertFalse(qualification["qualified"])
        self.assertTrue(qualification["automaticMetricsMayScreenOnly"])
        self.assertEqual(qualification["untouchedConfirmationCohort"]["negatives"], 70)
        self.assertFalse(qualification["untouchedConfirmationCohort"]["met"])
        self.assertFalse(qualification["independentReferenceEvidence"]["met"])


class ClickMirrorTests(unittest.TestCase):
    @staticmethod
    def tone(seconds: float, *, seams: list[int], quiet: bool = False) -> list[float]:
        import math
        samples = [0.0 if quiet else 0.3 * math.sin(2 * math.pi * 220 * index / 24_000)
                   for index in range(int(seconds * 24_000))]
        for seam in seams:
            # What the limiter publishes for a 0.95 spike: one clamp up, one back.
            samples[seam] = samples[seam - 1] + bounds.SLEW_CLAMP
            samples[seam + 1] = samples[seam] - bounds.SLEW_CLAMP
        return samples

    def test_clamped_samples_cluster_into_events_whatever_the_length(self) -> None:
        short = bounds.click_events(self.tone(2, seams=[2_400, 7_200]))
        long = bounds.click_events(self.tone(20, seams=[2_400, 7_200]))
        self.assertEqual(short, long)
        self.assertEqual(short["clampedSamples"], 4)
        self.assertEqual(short["clickEventCount"], 2)
        self.assertEqual(short["lowEnergyClickEventCount"], 0)
        near = bounds.click_events(self.tone(1, seams=[2_400, 2_520, 2_640]))
        self.assertEqual(near["clickEventCount"], 1)
        quiet = bounds.click_events(self.tone(1, seams=[2_400], quiet=True))
        self.assertEqual((quiet["clickEventCount"], quiet["lowEnergyClickEventCount"]), (1, 1))
        self.assertEqual(bounds.click_events(self.tone(1, seams=[]))["clickEventCount"], 0)

    def test_wav_takes_and_labels_screen_per_second_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, seams in (("clean.wav", []), ("seam.wav", [2_400, 7_200, 12_000])):
                with wave.open(str(root / name), "wb") as stream:
                    stream.setnchannels(1)
                    stream.setsampwidth(2)
                    stream.setframerate(24_000)
                    stream.writeframes(array("h", (
                        int(round(value * 32767)) for value in self.tone(1, seams=seams)
                    )).tobytes())
            labels = root / "labels.json"
            labels.write_text(json.dumps({
                "clean.wav": {"label": "good", "split": "confirmation"},
                "seam.wav": {"label": "bad", "split": "confirmation"},
            }))
            records = root / "runs"
            (records / "ui-generation").mkdir(parents=True)
            (records / "ui-generation" / "r.json").write_text(json.dumps(record(
                "r", "2026-09-01T00:00:00Z", [take("medium", 10.0, clamps=5), take("medium", 5.0, clamps=0)])))
            output = root / "report.json"
            self.assertEqual(bounds.main([
                "clicks", "--records", str(records), "--wav", str(root / "clean.wav"), str(root / "seam.wav"),
                "--labels", str(labels), "--output", str(output),
            ]), 0)
            report = json.loads(output.read_text())
        self.assertEqual(report["committedTakes"]["withAnyClamp"], 1)
        self.assertEqual(report["committedTakes"]["clampedPerSecond"]["median"], 0.5)
        self.assertEqual(report["currentBoundAsClampedSamplesPerSecond"], {"warn": 12.0, "fail": 120.0})
        by_name = {row["wav"]: row for row in report["wavTakes"]["rows"]}
        self.assertEqual(by_name["seam.wav"]["clickEventCount"], 3)
        self.assertEqual(by_name["clean.wav"]["clickEventCount"], 0)
        first = report["candidates"][0]
        self.assertEqual(first["failEventsPerSecond"], 0.5)
        self.assertEqual((first["confirmationBadFailed"], first["confirmationGoodFailed"]), ("1/1", "0/1"))
        self.assertFalse(report["qualification"]["qualified"])
        self.assertRegex(report["qualification"]["independentReferenceEvidence"]["digest"], r"^[0-9a-f]{64}$")

    def test_malformed_labels_and_inputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            labels = Path(directory) / "labels.json"
            labels.write_text(json.dumps({"a.wav": {"label": "maybe", "split": "confirmation"}}))
            with self.assertRaises(bounds.BoundsError):
                bounds.load_labels(labels)
            with self.assertRaises(bounds.BoundsError):
                bounds.wav_paths([Path(directory) / "missing.wav"])


if __name__ == "__main__":
    unittest.main()
