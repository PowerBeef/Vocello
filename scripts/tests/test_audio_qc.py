#!/usr/bin/env python3
"""The one audio-QC take mapping the publisher and both UI gates share."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib import audio_qc  # noqa: E402


def row(**overrides) -> dict:
    base = {
        "finishReason": "eos",
        "outputMetrics": {"readableWAV": True, "atomicallyPublished": True, "durationSeconds": 2.5},
        "audioQC": {
            "algorithmVersion": 6, "verdict": "pass", "instabilityVerdict": "pass",
            "writtenOutputVerdict": "pass", "flags": [], "clickEvents": 0, "clippedSamples": 1,
            "nonFiniteSamples": 0, "longestSilenceMS": 40, "dcOffset": -0.0001,
        },
        "notes": {"quality_registry_outcome": "pass",
                  "quality_registry_required_gates": "terminal,token_cap,persisted_wav"},
    }
    base.update(overrides)
    return base


class AudioQCTests(unittest.TestCase):
    def test_metric_rename_drops_non_finite_and_boolean_values(self) -> None:
        metrics = audio_qc.qc_metrics({
            "clickEvents": 2, "clippedSamples": True, "nonFiniteSamples": float("nan"),
            "longestSilenceMS": 12, "dcOffset": 0.5, "peak": 0.9,
        })
        self.assertEqual(metrics, {"discontinuityCount": 2.0, "longestSilenceMS": 12.0, "dcOffset": 0.5})

    def test_record_takes_the_worst_verdict_and_names_warning_sources(self) -> None:
        warned = row()
        warned["audioQC"].update({"writtenOutputVerdict": "warn", "flags": ["dropout:900ms"]})
        record = audio_qc.qc_record(warned)
        self.assertEqual(record["verdict"], "warn")
        self.assertEqual(record["warningCodes"], ["dropout:900ms", "written-output-warn"])
        self.assertEqual(record["metrics"]["clipCount"], 1.0)
        passed = audio_qc.qc_record(row())
        self.assertEqual(passed["warningCodes"], [])
        failed = row()
        failed["audioQC"]["instabilityVerdict"] = "fail"
        self.assertEqual(audio_qc.qc_record(failed)["verdict"], "fail")

    def test_failure_predicates_cover_finish_output_and_verdict(self) -> None:
        self.assertIsNone(audio_qc.output_failure(row()))
        self.assertIsNone(audio_qc.audio_qc_failure(row()))
        cancelled = row(finishReason="cancelled")
        self.assertIn("finishReason", audio_qc.output_failure(cancelled))
        unreadable = row(outputMetrics={"readableWAV": False, "atomicallyPublished": True, "durationSeconds": 1.0})
        self.assertIn("readableWAV", audio_qc.output_failure(unreadable))
        failed = row()
        failed["audioQC"].update({"verdict": "fail", "flags": ["clipping"]})
        self.assertEqual(audio_qc.audio_qc_failure(failed), "failed: ['clipping']")
        self.assertEqual(audio_qc.output_failure(failed), "audioQC failed: ['clipping']")
        missing = row(audioQC={})
        self.assertIn("missing or invalid", audio_qc.audio_qc_failure(missing))
        nested = row(audioQC=None)
        nested["outputMetrics"]["audioQC"] = {"verdict": "warn"}
        self.assertIsNone(audio_qc.audio_qc_failure(nested))
        self.assertTrue(audio_qc.finish_succeeded("MAX_TOKENS"))
        self.assertFalse(audio_qc.finish_succeeded("failed"))

    def test_quality_identity_and_schema_version_refuse_a_mixed_run(self) -> None:
        identity = audio_qc.quality_identity_fields(row())
        self.assertEqual(identity["qualityRegistryOutcome"], "pass")
        self.assertEqual(identity["qualityRegistryRequiredGates"], ["persisted_wav", "terminal", "token_cap"])
        self.assertEqual(audio_qc.quality_identity_fields(row(notes={})), {})
        self.assertEqual(audio_qc.history_record_schema_version([identity, identity]), 3)
        self.assertEqual(audio_qc.history_record_schema_version([{}, {}]), 2)
        with self.assertRaisesRegex(audio_qc.AudioQCError, "partial schema-v3"):
            audio_qc.history_record_schema_version([identity, {}])
        self.assertEqual(audio_qc.qc_algorithm_version([row(), row(audioQC={"algorithmVersion": 4})]), 6)


if __name__ == "__main__":
    unittest.main()


class StepBurstMetricTests(unittest.TestCase):
    def test_qc_metrics_carry_the_step_burst_when_present_and_tolerate_its_absence(self) -> None:
        new = {"clickEvents": 0, "clippedSamples": 0, "nonFiniteSamples": 0, "longestSilenceMS": 0,
               "dcOffset": 0.0, "stepBurstPeakCount": 31, "stepBurstPeakStartMS": 166}
        metrics = audio_qc.qc_metrics(new)
        self.assertEqual((metrics["stepBurstPeakCount"], metrics["stepBurstPeakStartMS"]), (31, 166))
        legacy = {k: v for k, v in new.items() if not k.startswith("stepBurst")}
        self.assertNotIn("stepBurstPeakCount", audio_qc.qc_metrics(legacy))

    def test_qc_v8_speaking_rate_is_published_only_when_the_engine_measured_it(self) -> None:
        # audit #10: the run-on measure reaches the tracked take; the unit count
        # stays in raw telemetry (duration ÷ rate recovers it).
        row = {"clickEvents": 0, "clippedSamples": 0, "nonFiniteSamples": 0, "longestSilenceMS": 0,
               "dcOffset": 0.0, "speakingRateTextUnits": 91, "secondsPerTextUnit": 0.1644}
        metrics = audio_qc.qc_metrics(row)
        self.assertEqual(metrics["secondsPerTextUnit"], 0.1644)
        self.assertNotIn("speakingRateTextUnits", metrics)
        self.assertNotIn("secondsPerTextUnit", audio_qc.qc_metrics({"clickEvents": 0}))

    def test_click_events_are_published_per_second_beside_the_sample_count(self) -> None:
        # audit #85: clustered events and their per-second rate reach the take;
        # the per-sample count keeps its legacy name.
        row = {"clickEvents": 12, "clippedSamples": 0, "nonFiniteSamples": 0, "longestSilenceMS": 0,
               "dcOffset": 0.0, "clickEventCount": 3, "lowEnergyClickEventCount": 1,
               "clickEventsPerSecond": 0.5}
        metrics = audio_qc.qc_metrics(row)
        self.assertEqual(metrics["discontinuityCount"], 12.0)
        self.assertEqual(
            (metrics["clickEventCount"], metrics["lowEnergyClickEventCount"], metrics["clickEventsPerSecond"]),
            (3.0, 1.0, 0.5),
        )
        self.assertNotIn("clickEventsPerSecond", audio_qc.qc_metrics({"clickEvents": 0}))


class FastQCV8MirrorTests(unittest.TestCase):
    """The NumPy mirror of Fast QC v8 (AQ-03 M1) on procedural signals with exact counts."""

    RATE = 24_000

    def tone(self, seconds: float, amplitude: float = 0.3, frequency: float = 200.0):
        import numpy as np

        time = np.arange(int(seconds * self.RATE)) / self.RATE
        return amplitude * np.cos(2 * np.pi * frequency * time)

    def test_replay_constants_are_the_swift_values(self) -> None:
        # Swift owns these (PCM16StreamLimiter, makeAudioQCReport, AudioSpeakingRateQC);
        # docs/reference/audio-qc-engineering.md lists them. A qualified change edits all three.
        constants = audio_qc.FASTQC_V8
        self.assertEqual(
            (constants["ceiling"], constants["maxSingleSampleStep"], constants["releaseStepPerSample"],
             constants["stepBurstStepThreshold"], constants["stepBurstWindowSamples"],
             constants["clickEventGapSamples"], constants["lowEnergyClickEnvelope"], constants["silenceFloor"],
             constants["interiorRunRecordFloorSamples"], constants["interiorRunRecordCap"]),
            (0.965, 0.42, 0.002, 0.25, 480, 240, 0.02, 0.001, 2_400, 256))
        self.assertEqual(constants["clickEnvelopeCoefficient"], 1.0 / 240.0)
        self.assertEqual(
            (constants["silentFailDBFS"], constants["lowLevelWarnDBFS"], constants["clipFailFraction"],
             constants["clickFailFraction"], constants["clickWarnFraction"], constants["hotWarnFraction"],
             constants["dcOffsetWarn"], constants["dcOffsetFail"], constants["onsetStepBurstMinSteps"],
             constants["onsetStepBurstWindowMS"], constants["longContentSeconds"]),
            (-60.0, -45.0, 0.001, 0.005, 0.0005, 0.02, 0.05, 0.20, 3, 50.0, 45.0))
        self.assertEqual(constants["cadencePauseMS"], {"short": 350, "long": 600})
        self.assertEqual(constants["egregiousMS"], {"noDeclaredPause": 1_200, "declaredPauseOrLong": 2_000})
        self.assertEqual(constants["suspiciousSingleMS"],
                         {"noDeclaredPause": 900, "declaredPause": 1_200, "long": 1_500})
        self.assertEqual({name: (band["slowSecondsPerUnit"], band["minimumJudgedUnits"])
                          for name, band in constants["speakingRateBands"].items()},
                         {"alphabetic": (0.145, 20), "chinese": (0.45, 8), "japanese": (0.40, 8),
                          "korean": (0.40, 8)})

    def test_text_measures(self) -> None:
        self.assertEqual(audio_qc.expected_pause_count("Hello there, world. Bye!"), 2)
        self.assertEqual(audio_qc.expected_pause_count("Wait... what?!"), 1)
        self.assertEqual(audio_qc.expected_pause_count("no punctuation"), 0)
        self.assertEqual(audio_qc.expected_pause_count("你好，世界。"), 1)
        self.assertEqual(audio_qc.speaking_rate_measure("Hello, world 42."), (12, "alphabetic"))
        self.assertEqual(audio_qc.speaking_rate_measure("你好世界"), (4, "chinese"))
        self.assertEqual(audio_qc.speaking_rate_measure("こんにちは世界"), (7, "japanese"))
        self.assertEqual(audio_qc.speaking_rate_measure("안녕하세요"), (5, "korean"))
        self.assertIsNone(audio_qc.speaking_rate_measure("... !"))

    def test_silence_nonfinite_level_and_dc(self) -> None:
        import numpy as np

        silent = audio_qc.fast_qc_v8(np.zeros(self.RATE))
        self.assertEqual((silent["verdict"], silent["flags"]), ("fail", ["silent"]))
        tone = audio_qc.fast_qc_v8(self.tone(1.0, amplitude=0.5))
        self.assertEqual((tone["verdict"], tone["flags"]), ("pass", []))
        self.assertAlmostEqual(tone["rmsDBFS"], 20 * np.log10(0.5 / np.sqrt(2)), places=3)
        broken = self.tone(1.0)
        broken[100] = np.nan
        report = audio_qc.fast_qc_v8(broken)
        self.assertEqual((report["verdict"], report["flags"], report["nonFiniteSamples"]),
                         ("fail", ["nonfinite"], 1))
        quiet = audio_qc.fast_qc_v8(self.tone(1.0, amplitude=0.005))
        self.assertEqual((quiet["verdict"], quiet["flags"]), ("warn", ["low_level"]))
        self.assertEqual(audio_qc.fast_qc_v8(self.tone(1.0) + 0.1)["flagLevels"], {"dc_offset": "warn"})
        self.assertEqual(audio_qc.fast_qc_v8(self.tone(1.0) + 0.3)["flagLevels"], {"dc_offset": "fail"})

    def test_click_counter_events_and_onset_burst(self) -> None:
        import numpy as np

        samples = np.zeros(self.RATE)
        for position in (1_000, 1_100, 5_000, 9_000):
            samples[position] = 0.9
        report = audio_qc.fast_qc_v8(samples)
        # One clamp per impulse on a zero background: the return step is exactly the clamp.
        self.assertEqual((report["clickEvents"], report["clickEventCount"], report["lowEnergyClickEventCount"]),
                         (4, 3, 3))
        self.assertEqual((report["stepBurstPeakCount"], report["stepBurstPeakStartMS"]), (4, 41))
        self.assertIn("onset_step_burst", report["flags"])
        self.assertNotIn("clicks", report["flagLevels"])
        warn = self.tone(1.0, amplitude=0.05)
        warn[2_000:2_000 + 20 * 300:300] += 0.9
        self.assertEqual(audio_qc.fast_qc_v8(warn)["flagLevels"].get("clicks"), "warn")
        fail = self.tone(1.0, amplitude=0.05)
        fail[500:500 + 130 * 150:150] += 0.9
        self.assertEqual(audio_qc.fast_qc_v8(fail)["flagLevels"].get("clicks"), "fail")

    def test_dropout_and_terminal_silence_follow_the_pause_budget(self) -> None:
        import numpy as np

        take = np.concatenate([self.tone(1.0), np.zeros(int(1.3 * self.RATE)), self.tone(1.0)])
        bare = audio_qc.fast_qc_v8(take)
        self.assertEqual((bare["longestSilenceMS"], bare["flags"], bare["verdict"]),
                         (1300, ["dropout:1300ms"], "fail"))
        declared = audio_qc.fast_qc_v8(take, text="Hello there, world.")
        self.assertEqual((declared["expectedPauseCount"], declared["flags"], declared["verdict"]),
                         (1, ["dropout:1300ms"], "warn"))
        cadence = audio_qc.fast_qc_v8(np.concatenate([self.tone(1.0), np.zeros(int(0.5 * self.RATE)),
                                                      self.tone(1.0)]))
        self.assertEqual(cadence["flags"], ["cadence:excess1(1/0)"])
        trailing = audio_qc.fast_qc_v8(np.concatenate([self.tone(1.0), np.zeros(int(2.1 * self.RATE))]))
        self.assertEqual((trailing["trailingSilenceMS"], trailing["flags"]), (2100, ["terminal_silence:2100ms"]))
        leading = audio_qc.fast_qc_v8(np.concatenate([np.zeros(int(2.1 * self.RATE)), self.tone(1.0)]))
        self.assertEqual(leading["flags"], [])

    def test_clipping_hot_and_speaking_rate(self) -> None:
        tone = self.tone(1.0, amplitude=0.5)
        tone[1_000:1_030] = 1.5
        self.assertEqual(audio_qc.fast_qc_v8(tone)["flagLevels"].get("clipping"), "fail")
        tone = self.tone(1.0, amplitude=0.5)
        tone[1_000:1_010] = 1.5
        report = audio_qc.fast_qc_v8(tone)
        self.assertEqual((report["flagLevels"].get("clipping"), report["clippedSamples"]), ("warn", 10))
        self.assertEqual(audio_qc.fast_qc_v8(self.tone(1.0, amplitude=0.99))["flagLevels"].get("hot"), "warn")
        slow = audio_qc.fast_qc_v8(self.tone(4.0), text="abcdefghij klmnopqrst.")
        self.assertEqual((slow["speakingRateTextUnits"], slow["secondsPerTextUnit"], slow["flags"]),
                         (20, 0.2, ["speaking_rate_slow"]))
        unjudged = audio_qc.fast_qc_v8(self.tone(4.0), text="abcdefghij klmnopqrs.")
        self.assertEqual(unjudged["flags"], [])

    def test_the_mirror_report_folds_into_the_tracked_take(self) -> None:
        samples = self.tone(1.0, amplitude=0.05)
        samples[2_000:2_000 + 20 * 300:300] += 0.9
        record = audio_qc.qc_record({"audioQC": audio_qc.fast_qc_v8(samples)})
        self.assertEqual((record["algorithmVersion"], record["verdict"]), (8, "warn"))
        self.assertIn("clicks", record["warningCodes"])
        self.assertEqual(record["metrics"]["clickEventCount"], 20.0)
        self.assertEqual(audio_qc.flag_family("dropout:1300ms"), "dropout")
