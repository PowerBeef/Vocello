#!/usr/bin/env python3
"""PCM shape measures (flat tops, digital silence, the last active span) and the `pcm` detector source."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.qc_qualification import detectors, pcm_measures  # noqa: E402
from lib.qc_qualification.pcm import SeededStream  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
RATE = 24_000


def tone(seconds: float, amplitude: float, frequency: float = 180.0) -> np.ndarray:
    time = np.arange(int(seconds * RATE)) / RATE
    return amplitude * np.sin(2.0 * math.pi * frequency * time)


def noise(seconds: float, amplitude: float, label: str) -> np.ndarray:
    return amplitude * SeededStream(7, label).normal(int(seconds * RATE))


class FlatTopTests(unittest.TestCase):
    def test_symmetric_clipping_below_full_scale_holds_both_polarities(self) -> None:
        clean = tone(1.0, 0.5) + noise(1.0, 0.01, "clean")
        clipped = np.clip(clean, -0.3, 0.3)
        values = pcm_measures.pcm16_values(clipped)
        tops = pcm_measures.flat_tops(values)
        self.assertEqual(tops["peakPCM16"], int(np.max(np.abs(values))))
        self.assertGreater(tops["flatTopPositive"], 0)
        self.assertGreater(tops["flatTopNegative"], 0)
        self.assertAlmostEqual(tops["symmetricFlatTopFraction"],
                               min(tops["flatTopPositive"], tops["flatTopNegative"]) / values.size)
        # The waveform itself never repeats a sample at its peak.
        self.assertEqual(pcm_measures.flat_tops(pcm_measures.pcm16_values(clean))["symmetricFlatTopFraction"], 0.0)

    def test_a_one_sided_plateau_is_not_symmetric_clipping(self) -> None:
        # Positive half-cycles reach 0.6 and negative ones 0.4: clamped at 0.45, the positive side holds the peak.
        wave = tone(1.0, 0.5)
        clean = np.where(wave > 0, 1.2 * wave, 0.8 * wave) + noise(1.0, 0.005, "one-sided")
        tops = pcm_measures.flat_tops(pcm_measures.pcm16_values(np.minimum(clean, 0.45)))
        self.assertGreater(tops["flatTopPositive"], 0)
        self.assertEqual(tops["flatTopNegative"], 0)
        self.assertEqual(tops["symmetricFlatTopFraction"], 0.0)

    def test_the_score_is_relative_to_the_takes_own_peak(self) -> None:
        clipped = np.clip(tone(1.0, 0.5) + noise(1.0, 0.01, "gain"), -0.3, 0.3)
        # Halving the PCM16 integers keeps every run equal and the peak relative level.
        values = pcm_measures.pcm16_values(clipped)
        halved = values // 2
        self.assertEqual(pcm_measures.flat_tops(values)["symmetricFlatTopFraction"],
                         pcm_measures.flat_tops(halved)["symmetricFlatTopFraction"])

    def test_silence_has_no_peak_and_no_score(self) -> None:
        self.assertEqual(pcm_measures.flat_tops(np.zeros(100, dtype=np.int64)),
                         {"peakPCM16": 0, "flatTopPositive": None, "flatTopNegative": None,
                          "symmetricFlatTopFraction": None})


class DigitalSilenceTests(unittest.TestCase):
    def test_interior_trailing_and_leading_zero_runs(self) -> None:
        values = np.concatenate([np.zeros(24, dtype=np.int64), np.full(100, 5), np.zeros(240, dtype=np.int64),
                                 np.full(100, -3), np.zeros(10, dtype=np.int64), np.full(1, 2),
                                 np.zeros(48, dtype=np.int64)])
        self.assertEqual(pcm_measures.digital_silence(values, RATE),
                         {"longestInteriorDigitalSilenceMS": 10.0, "trailingDigitalSilenceMS": 2.0,
                          "leadingDigitalSilenceMS": 1.0})

    def test_quiet_room_tone_is_not_digital_silence(self) -> None:
        # Room tone at -70 dBFS sits below Fast QC's 0.001 floor but is never exactly zero for long.
        room = pcm_measures.pcm16_values(noise(2.0, 10 ** (-70 / 20), "room"))
        self.assertLess(pcm_measures.digital_silence(room, RATE)["longestInteriorDigitalSilenceMS"], 5.0)

    def test_a_silent_take_is_digital_silence_throughout(self) -> None:
        whole = pcm_measures.digital_silence(np.zeros(2400, dtype=np.int64), RATE)
        self.assertEqual(set(whole.values()), {100.0})


class LastActiveTests(unittest.TestCase):
    def test_the_last_span_ends_where_speech_level_audio_ends(self) -> None:
        floor = noise(3.0, 10 ** (-70 / 20), "floor")
        speech = floor.copy()
        start, end = int(0.5 * RATE), int(1.5 * RATE)
        speech[start:end] += noise(1.0, 10 ** (-20 / 20), "speech")
        # A 30 ms dip inside the span does not split it.
        speech[int(1.0 * RATE):int(1.03 * RATE)] = floor[int(1.0 * RATE):int(1.03 * RATE)]
        # A 5 ms click after it is shorter than any counted span.
        speech[int(2.0 * RATE):int(2.005 * RATE)] += 0.5
        values = pcm_measures.pcm16_values(speech)
        self.assertAlmostEqual(pcm_measures.last_active_seconds(values, RATE), 1.5, places=6)
        # A run-on of speech-level audio after the take moves the end with it.
        extended = np.concatenate([speech, noise(1.2, 10 ** (-20 / 20), "run-on")])
        self.assertAlmostEqual(pcm_measures.last_active_seconds(pcm_measures.pcm16_values(extended), RATE),
                               4.2, places=6)

    def test_no_counted_span_is_none(self) -> None:
        self.assertIsNone(pcm_measures.last_active_seconds(np.zeros(RATE, dtype=np.int64), RATE))
        self.assertIsNone(pcm_measures.last_active_seconds(np.zeros(10, dtype=np.int64), RATE))


class BlockTests(unittest.TestCase):
    def test_measure_writes_every_field_its_version_and_its_digest(self) -> None:
        block = pcm_measures.measure(tone(0.5, 0.2), RATE)
        self.assertEqual(set(block), {"version", "sourceSHA256", "sampleRate", "samples", *pcm_measures.FIELDS})
        self.assertEqual(block["version"], pcm_measures.PCM_MEASURES_VERSION)
        self.assertEqual(block["sourceSHA256"], pcm_measures.source_sha256())
        self.assertEqual(block["sourceSHA256"], detectors.pcm_measures_sha256())
        self.assertEqual((block["sampleRate"], block["samples"]), (RATE, RATE // 2))
        json.dumps(block, allow_nan=False)

    def test_the_registry_reads_exactly_the_measured_fields(self) -> None:
        self.assertEqual(detectors.PCM_SCORE_FIELDS, set(pcm_measures.FIELDS))
        self.assertIn(detectors.PCM_MEASURES_SOURCE, detectors.scoring_sources())
        self.assertEqual(detectors.PCM_MEASURES_SOURCE, Path(pcm_measures.__file__).resolve())


class PcmSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.component = {"source": "pcm", "field": "trailingDigitalSilenceMS"}
        self.block = pcm_measures.measure(np.concatenate([tone(0.5, 0.2), np.zeros(RATE // 10)]), RATE)

    def test_a_current_block_scores(self) -> None:
        value, why = detectors.component_value(self.component, language="french",
                                               clip={"clipID": "a", "pcmMeasures": self.block})
        self.assertEqual((value, why), (100.0, None))

    def test_a_clip_without_the_block_is_an_evidence_gap(self) -> None:
        self.assertEqual(detectors.component_value(self.component, language="french", clip={"clipID": "a"}),
                         (None, "not-measured"))
        self.assertIn("not-measured", ("no-evidence", "not-measured", "no-raw-output"))

    def test_a_block_measured_by_other_code_is_refused(self) -> None:
        stale = {**self.block, "sourceSHA256": "0" * 64}
        with self.assertRaises(detectors.DetectorError):
            detectors.component_value(self.component, language="french",
                                      clip={"clipID": "a", "pcmMeasures": stale})

    def test_the_registry_accepts_only_measured_fields(self) -> None:
        registry = json.loads((REPO / "config/audio-qc-detectors.json").read_text(encoding="utf-8"))
        judges = json.loads((REPO / "config/audio-qc-judges.json").read_text(encoding="utf-8"))
        self.assertEqual(detectors.registry_errors(registry, judges), [])
        mutated = copy.deepcopy(registry)
        entry = next(item for item in mutated["detectors"] if item["id"] == "signal.dropout@2")
        entry["score"]["groups"][0]["components"][0]["field"] = "longestSilenceMS"
        self.assertTrue(any("PCM measures" in error for error in detectors.registry_errors(mutated, judges)))


class SignalV2RegistryTests(unittest.TestCase):
    """The v2 signal detectors: one pooled threshold, and digital silence where v1 read Fast QC's floor."""

    def setUp(self) -> None:
        self.registry = json.loads((REPO / "config/audio-qc-detectors.json").read_text(encoding="utf-8"))

    def entry(self, detector: str) -> dict:
        return detectors.detector_entry(self.registry, detector)

    def test_pooled_strata_and_sources(self) -> None:
        expected = {"signal.dc-offset@2": ("fastqc", "dcOffset", "SIG-DC"),
                    "signal.dropout@2": ("pcm", "longestInteriorDigitalSilenceMS", "SIG-DROP"),
                    "signal.terminal-silence@2": ("pcm", "trailingDigitalSilenceMS", "SIG-SIL")}
        for detector, (source, field, injector) in expected.items():
            entry = self.entry(detector)
            self.assertIsNone(detectors.strata_by(entry), detector)
            self.assertEqual(detectors.stratum(detectors.strata_by(entry), "portuguese"), detectors.POOLED)
            (component,) = detectors.components_of(entry)
            self.assertEqual((component["source"], component["field"]), (source, field))
            self.assertEqual(detectors.judges_of(entry), [detectors.STAGE0_JUDGE])
            self.assertTrue(detectors.needs_measurements(entry))
            self.assertFalse(detectors.needs_panel(entry))
            self.assertEqual(detectors.declared_cells(entry),
                             {"T1-pcm-construction": {f"{injector}/moderate", f"{injector}/severe"}})
            self.assertEqual(len(entry["scope"]["languages"]), 10)
        # v1 keeps its per-language definition (A7: a new version, never an edit).
        for detector in ("signal.dc-offset@1", "signal.dropout@1", "signal.terminal-silence@1"):
            self.assertEqual(detectors.strata_by(self.entry(detector)), "language")

    def test_scores_read_the_block(self) -> None:
        samples = np.concatenate([tone(0.4, 0.2), np.zeros(RATE // 4), tone(0.4, 0.2), np.zeros(RATE // 20)])
        clip = {"clipID": "c", "pcmMeasures": pcm_measures.measure(samples, RATE),
                "fastQC": {"dcOffset": -0.004}}
        scores = {detector: detectors.score_take(self.entry(detector), "korean", clip=clip)["score"]
                  for detector in ("signal.dropout@2", "signal.terminal-silence@2", "signal.dc-offset@2")}
        self.assertGreaterEqual(scores["signal.dropout@2"], 250.0)
        self.assertEqual(scores["signal.terminal-silence@2"], 50.0)
        self.assertEqual(scores["signal.dc-offset@2"], 0.004)


if __name__ == "__main__":
    unittest.main()
