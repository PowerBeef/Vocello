#!/usr/bin/env python3
"""The Stage 0 observational measures and engine introspection mirror (AQ-04)."""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import audio_qc, audio_qc_observations as observations  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "audio_qc_stage0_observations.json"
RATE = 24_000
# One rounding step of the reported reals: Swift and this mirror sum in different
# orders, so a value can land on either side of a four-decimal boundary.
REAL_TOLERANCE = 1.5e-4
INTEGER_FIELDS = {
    "algorithmVersion", "spectralFluxEventCount", "seamCount", "seamDiscontinuityMaxZStartMS",
    "repetitionStripeLongestMS", "repetitionStripeLagMS", "repetitionStripeCount",
}


def load_fixtures() -> dict:
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


class RecordTests(unittest.TestCase):
    """Swift owns the constants; both sides are pinned to one record."""

    def test_mirror_constants_are_the_record(self) -> None:
        record = observations.load_record()
        self.assertEqual(record["algorithmVersion"], observations.OBSERVATIONS_ALGORITHM_VERSION)
        self.assertEqual(record["introspectionAlgorithmVersion"], observations.INTROSPECTION_ALGORITHM_VERSION)
        self.assertEqual(record["fastQCAlgorithmVersion"], audio_qc.FASTQC_V8_ALGORITHM_VERSION)
        self.assertEqual(record["status"], "observational")
        self.assertEqual(record["constants"], observations.STAGE0_OBSERVATIONS)
        self.assertEqual(record["introspection"], observations.INTROSPECTION)

    def test_the_wada_table_is_the_quadrature_of_the_paper_model(self) -> None:
        table = observations.load_record()["wadaGammaTable"]
        self.assertEqual(table["snrDB"], list(range(-20, 101)))
        derived = observations.wada_gamma_table(table["snrDB"], alpha=table["alpha"])
        self.assertLess(max(abs(a - b) for a, b in zip(derived, table["g"])), 1e-8)
        self.assertTrue(all(b > a for a, b in zip(table["g"], table["g"][1:])), "G(SNR) rises monotonically")
        # Pure Gamma limit: log(alpha) - psi(alpha) = 1.6451 for alpha 0.4, approached from below.
        self.assertLess(table["g"][-1], 1.6451)

    def test_k_weighting_at_48khz_is_the_bs1770_filter(self) -> None:
        shelf, high_pass = observations.k_weighting_sections(48_000)
        published = ((1.53512485958697, -2.69169618940638, 1.19839281085285, -1.69065929318241, 0.73248077421585),
                     (1.0, -2.0, 1.0, -1.99004745483398, 0.99007225036621))
        for mine, reference in zip((shelf, high_pass), published):
            for value, expected in zip(mine, reference):
                self.assertAlmostEqual(value, expected, places=12)

    def test_the_true_peak_interpolator_passes_samples_through_on_phase_zero(self) -> None:
        phases = observations.true_peak_phases()
        self.assertEqual([len(phase) for phase in phases], [13, 13, 13, 13])
        self.assertEqual(phases[0], [0.0] * 6 + [1.0] + [0.0] * 6)
        # Odd phases mirror each other about the filter's centre (tap j pairs with 48 - j).
        for left, right in zip(phases[1][:12], reversed(phases[3][:12])):
            self.assertAlmostEqual(left, right, places=14)
        self.assertEqual((phases[1][12], phases[3][12]), (0.0, 0.0))


class SharedFixtureTests(unittest.TestCase):
    """Every field on every shared fixture; AudioQCSignalObservationTests scores the same file."""

    def assert_matches(self, actual: dict, expected: dict, where: str) -> None:
        self.assertEqual(set(actual), set(expected), where)
        for key, value in expected.items():
            with self.subTest(fixture=where, key=key):
                if value is None or key in INTEGER_FIELDS:
                    self.assertEqual(actual[key], value)
                else:
                    self.assertIsNotNone(actual[key])
                    self.assertLessEqual(abs(actual[key] - value), REAL_TOLERANCE)

    def test_signal_fixtures(self) -> None:
        fixtures = load_fixtures()
        self.assertEqual(fixtures["algorithmVersion"], observations.OBSERVATIONS_ALGORITHM_VERSION)
        for fixture in fixtures["signalFixtures"]:
            pcm = observations.synthesize_fixture(fixture["segments"], fixtures["sampleRate"])
            self.assertEqual(len(pcm), fixture["sampleCount"], fixture["id"])
            actual = observations.signal_observations(pcm, sample_rate=fixtures["sampleRate"],
                                                      seam_offsets=fixture.get("seams", ()))
            self.assert_matches(actual, fixture["expected"], fixture["id"])

    def test_introspection_fixtures(self) -> None:
        fixtures = load_fixtures()
        self.assertEqual(fixtures["introspectionAlgorithmVersion"], observations.INTROSPECTION_ALGORITHM_VERSION)
        for fixture in fixtures["introspectionFixtures"]:
            actual = observations.introspection_summary(
                fixture["tokens"], entropies=fixture.get("entropies", ()),
                eos_probabilities=fixture.get("eosProbabilities", ()),
                stopped_at_eos=fixture.get("stoppedAtEOS", False), seam_frames=fixture.get("seamFrames", ()))
            self.assertEqual(actual, fixture["expected"], fixture["id"])


class KnownReferenceTests(unittest.TestCase):
    """Values fixed by the definitions, not by the mirror's own output."""

    @staticmethod
    def measure(segments: list[dict], seams: tuple[int, ...] = ()) -> dict:
        pcm = observations.synthesize_fixture(segments, RATE)
        return observations.signal_observations(pcm, sample_rate=RATE, seam_offsets=seams)

    def test_a_minus_20_dbfs_997_hz_tone_reads_minus_23_lufs(self) -> None:
        # BS.1770's -0.691 offset cancels the K-weighting gain at 997 Hz: a mono sine of
        # amplitude A reads 20 log10(A) - 3.01 LUFS (at 48 kHz; the 24 kHz filter is 0.03 LU off).
        result = self.measure([{"kind": "sine", "samples": 96_000, "frequencyHz": 997.0, "amplitude": 0.1}])
        self.assertAlmostEqual(result["integratedLoudnessLUFS"], -23.0103, delta=0.05)
        self.assertEqual(result["loudnessRangeLU"], 0.0)
        self.assertAlmostEqual(result["truePeakDBTP"], -20.0, delta=0.01)
        self.assertAlmostEqual(result["noiseFloorDBFS"], -23.0103, delta=0.02)
        self.assertEqual(result["codecFrameModulationIndex"], 0.0)
        self.assertEqual((result["repetitionStripeLongestMS"], result["repetitionStripeCount"]), (0, 0),
                         "a steady tone repeats no content")
        # A pure tone's amplitude distribution is nothing like speech: WADA floors it.
        self.assertEqual(result["wadaSNRDB"], -20.0)

    def test_true_peak_finds_the_peak_between_samples(self) -> None:
        # fs/4 at 45 degrees: every sample sits at A / sqrt(2), 3.01 dB under the waveform.
        result = self.measure([{"kind": "sine", "samples": 24_000, "frequencyHz": 6_000.0, "amplitude": 0.5,
                                "phase": math.pi / 4}])
        sample_peak_db = 20 * math.log10(0.5 / math.sqrt(2))
        self.assertAlmostEqual(result["truePeakDBTP"], 20 * math.log10(0.5), delta=0.15)
        self.assertGreater(result["truePeakDBTP"] - sample_peak_db, 2.9)

    def test_bandwidth_of_a_bin_centred_tone_ends_one_bin_above_it(self) -> None:
        result = self.measure([{"kind": "sine", "samples": 48_000, "frequencyHz": 750.0, "amplitude": 0.25}])
        self.assertEqual(result["effectiveBandwidthHz"], 17 * RATE / 512)
        noise = self.measure([{"kind": "noise", "samples": 48_000, "amplitude": 0.3, "seed": 1}])
        self.assertEqual(noise["effectiveBandwidthHz"], RATE / 2)

    def test_each_click_is_one_flux_event(self) -> None:
        clicks = [{"kind": "silence", "samples": 48_000},
                  {"kind": "impulses", "amplitude": 0.5, "positions": [3_000 + 6_000 * k for k in range(8)]}]
        result = self.measure(clicks)
        self.assertEqual((result["spectralFluxEventCount"], result["spectralFluxEventsPerSecond"]), (8, 4.0))
        silence = self.measure([{"kind": "silence", "samples": 48_000}])
        self.assertEqual((silence["spectralFluxEventCount"], silence["noiseFloorDBFS"]), (0, -120.0))
        self.assertIsNone(silence["integratedLoudnessLUFS"])
        self.assertIsNone(silence["wadaSNRDB"])

    def test_a_repeated_segment_is_a_stripe_at_its_own_lag(self) -> None:
        result = self.measure([{"kind": "silence", "samples": 4_800},
                               {"kind": "noise", "samples": 19_200, "amplitude": 0.3, "seed": 12_345},
                               {"kind": "copy", "start": 4_800, "samples": 19_200},
                               {"kind": "silence", "samples": 4_800}])
        self.assertEqual(result["repetitionStripeLagMS"], 800)
        self.assertGreaterEqual(result["repetitionStripeLongestMS"], 600)
        self.assertEqual(result["repetitionStripeCount"], 1)
        fresh = self.measure([{"kind": "silence", "samples": 4_800},
                              {"kind": "noise", "samples": 38_400, "amplitude": 0.3, "seed": 12_345},
                              {"kind": "silence", "samples": 4_800}])
        self.assertEqual(fresh["repetitionStripeCount"], 0)
        self.assertLess(fresh["repetitionStripeLongestMS"], 600)

    def test_modulation_at_the_codec_frame_rate(self) -> None:
        # Depth 0.5 at 12.5 Hz, seen through 10 ms RMS frames: sinc(0.125) = 0.9745 of it.
        result = self.measure([{"kind": "am", "samples": 61_440, "frequencyHz": 1_000.0, "amplitude": 0.4,
                                "modulationHz": 12.5, "depth": 0.5}])
        self.assertAlmostEqual(result["codecFrameModulationIndex"], 0.5 * 0.9745, delta=0.01)
        slower = self.measure([{"kind": "am", "samples": 61_440, "frequencyHz": 1_000.0, "amplitude": 0.4,
                                "modulationHz": 5.0, "depth": 0.5}])
        self.assertLess(slower["codecFrameModulationIndex"], 0.05)

    def test_a_seam_step_stands_out_and_a_smooth_seam_does_not(self) -> None:
        segments = [{"kind": "sine", "samples": 24_000, "frequencyHz": 440.0, "amplitude": 0.3},
                    {"kind": "sine", "samples": 24_000, "frequencyHz": 440.0, "amplitude": 0.3,
                     "phase": math.pi / 2}]
        stepped = self.measure(segments, seams=(24_000, 36_000))
        self.assertEqual(stepped["seamCount"], 2)
        self.assertGreater(stepped["seamDiscontinuityMaxZ"], 10.0)
        self.assertEqual(stepped["seamDiscontinuityMaxZStartMS"], 1_000)
        smooth = self.measure(segments, seams=(36_000,))
        self.assertLess(smooth["seamDiscontinuityMaxZ"], 3.0)
        self.assertEqual(self.measure(segments)["seamCount"], 0)

    def test_wada_reads_added_noise(self) -> None:
        bursts = [segment for k in range(8) for segment in (
            {"kind": "silence", "samples": 4_800},
            {"kind": "sine", "samples": 7_200, "frequencyHz": 997.0, "amplitude": 0.3})]
        noisy = [segment for k in range(8) for segment in (
            {"kind": "noise", "samples": 4_800, "amplitude": 0.02, "seed": 7 + k},
            {"kind": "sine", "samples": 7_200, "frequencyHz": 997.0, "amplitude": 0.3})]
        quiet_floor = self.measure(bursts)["noiseFloorDBFS"]
        noisy_result = self.measure(noisy)
        self.assertEqual(quiet_floor, -120.0)
        self.assertAlmostEqual(noisy_result["noiseFloorDBFS"], 20 * math.log10(0.02 / math.sqrt(3)), delta=0.5)


class InjectorTests(unittest.TestCase):
    """AQ-03's T1 injectors move the measures they name, and their shams move nothing."""

    @classmethod
    def setUpClass(cls) -> None:
        from lib.qc_qualification import fixtures, injectors, pcm

        cls.injectors = injectors
        cls.pcm = pcm
        cls.source = fixtures.clean_fixture(0)

    def signal(self, samples) -> dict:
        return observations.signal_observations(self.pcm.to_pcm16(samples), sample_rate=RATE)

    def inject(self, injector: str, variant: str) -> dict:
        return self.signal(self.injectors.inject(injector, variant, self.source, seed=11).samples)

    def test_a_level_drop_moves_loudness_and_true_peak_by_its_gain(self) -> None:
        clean = self.inject("SIG-LEVEL", "sham")
        quieter = self.inject("SIG-LEVEL", "moderate")
        self.assertEqual(clean, self.signal(self.source.samples))
        self.assertAlmostEqual(quieter["integratedLoudnessLUFS"] - clean["integratedLoudnessLUFS"], -30.0, delta=0.1)
        self.assertAlmostEqual(quieter["truePeakDBTP"] - clean["truePeakDBTP"], -30.0, delta=0.1)

    def test_clicks_add_flux_events(self) -> None:
        # Clicks within 50 ms of an onset or of each other join its event, so the
        # count rises with the click rate without matching it.
        events = [self.inject("SIG-CLICK", variant)["spectralFluxEventCount"]
                  for variant in ("sham", "mild", "moderate", "severe")]
        self.assertEqual(events, sorted(set(events)), "every click level adds events")
        self.assertGreaterEqual(events[2] - events[0], 5, "16 moderate clicks in 3.1 s")
        self.assertGreater(self.inject("SIG-CLICK", "moderate")["truePeakDBTP"],
                           self.inject("SIG-CLICK", "sham")["truePeakDBTP"])

    def test_noise_lowers_wada_snr_and_raises_the_floor(self) -> None:
        sham = self.inject("SIG-NOISE", "sham")
        noisy = self.inject("SIG-NOISE", "severe")
        self.assertLess(noisy["wadaSNRDB"], sham["wadaSNRDB"])
        self.assertGreater(noisy["noiseFloorDBFS"], sham["noiseFloorDBFS"] + 10.0)

    def test_a_repeated_phrase_forms_a_stripe(self) -> None:
        sham = self.inject("CNT-REP", "sham")
        looped = self.inject("CNT-REP", "severe")
        self.assertEqual(sham["repetitionStripeCount"], 0)
        self.assertGreaterEqual(looped["repetitionStripeCount"], 1)
        self.assertGreaterEqual(looped["repetitionStripeLongestMS"], 600)


class FastQCMirrorTests(unittest.TestCase):
    def test_the_mirror_report_carries_the_signal_block_and_its_metrics(self) -> None:
        import numpy as np

        tone = 0.3 * np.sin(2 * np.pi * 440.0 * np.arange(2 * RATE) / RATE)
        report = audio_qc.fast_qc_v8(tone, seam_offsets=(RATE,))
        self.assertEqual(report["algorithmVersion"], 8, "the observations leave the Fast QC version")
        self.assertEqual(report["signal"]["seamCount"], 1)
        self.assertEqual(audio_qc.fast_qc_v8(tone, signal=False).keys() | {"signal"}, report.keys())
        without = audio_qc.fast_qc_v8(tone, signal=False)
        self.assertEqual({key: report[key] for key in without}, without, "no flag or verdict moves")
        metrics = audio_qc.qc_metrics(report)
        for _, target in audio_qc.QC_SIGNAL_METRIC_MAP:
            if report["signal"][target] is not None:
                self.assertEqual(metrics[target], float(report["signal"][target]))
        self.assertNotIn("repetitionStripeLagMS", metrics)

    def test_published_metrics_are_history_allowlisted(self) -> None:
        import importlib.util

        spec = importlib.util.spec_from_file_location("benchmark_history", ROOT / "scripts" / "benchmark_history.py")
        assert spec and spec.loader
        history = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(history)
        targets = {target for _, target in (*audio_qc.QC_METRIC_MAP, *audio_qc.QC_SIGNAL_METRIC_MAP)}
        self.assertLessEqual(targets, history.METRIC_KEYS)


class IntrospectionTests(unittest.TestCase):
    def test_a_stuck_token_is_a_run_not_a_cycle(self) -> None:
        summary = observations.introspection_summary([7] * 40)
        self.assertEqual(summary["longestRepeatedTokenRunFrames"], 40)
        self.assertIsNone(summary["tokenCyclePeriod"])

    def test_the_shortest_period_names_a_loop(self) -> None:
        loop = list(range(100, 108))
        summary = observations.introspection_summary(loop * 4)
        self.assertEqual((summary["tokenCyclePeriod"], summary["tokenCycleRepeats"],
                          summary["tokenCycleSpanFrames"], summary["tokenCycleStartFrame"]), (8, 4, 32, 0))
        # Periods above 32 frames are out of the window.
        self.assertIsNone(observations.introspection_summary(list(range(40)) * 2)["tokenCyclePeriod"])

    def test_eos_steps_and_seams(self) -> None:
        summary = observations.introspection_summary(
            [1, 2, 3], entropies=[0.5, 0.5, 0.5, 0.25], eos_probabilities=[0.1, 0.6, 0.2, 0.9],
            stopped_at_eos=True, seam_frames=[2, 2, 3, 0])
        self.assertEqual((summary["eosFirstLikelyStep"], summary["eosLikelyStepsWithoutStop"]), (1, 1))
        self.assertEqual((summary["eosProbabilityMax"], summary["eosProbabilityMaxStep"]), (0.9, 3))
        self.assertEqual(summary["seamCodecFrames"], [2])
        self.assertEqual(summary["entropyP95Nats"], 0.53125)


if __name__ == "__main__":
    unittest.main()
