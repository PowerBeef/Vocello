"""Per-take decode-loop interval statistics of a profile trace (audit #12, #96, V-2)."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from lib import trace_intervals as intervals  # noqa: E402

MS = 1_000_000.0


def loop_intervals(start_ns: float, steps: int, *, drop: int = 0) -> list[intervals.Interval]:
    """`steps` decode steps of the 36 loop intervals plus a Token Read each,
    1 ms apart, minus the last `drop` loop intervals."""
    produced: list[intervals.Interval] = []
    cursor = start_ns
    for _ in range(steps):
        for name, multiplicity in intervals.LOOP_STEP_INTERVALS.items():
            for _ in range(multiplicity):
                produced.append(intervals.Interval(name, cursor, 0.4 * MS))
                cursor += MS
        produced.append(intervals.Interval("Token Read", cursor, 2 * MS))
        cursor += 3 * MS
    if drop:
        loop = [item for item in produced if item.name in intervals.LOOP_STEP_INTERVALS]
        dropped = set(id(item) for item in loop[-drop:])
        produced = [item for item in produced if id(item) not in dropped]
    return produced


class TraceIntervalTests(unittest.TestCase):
    def test_every_step_emits_thirty_six_loop_intervals(self) -> None:
        self.assertEqual(intervals.LOOP_INTERVALS_PER_STEP, 36)
        self.assertNotIn("Token Read", intervals.LOOP_STEP_INTERVALS)
        self.assertIn("Token Read", intervals.INTERVAL_KEYS)

    def test_intervals_are_assigned_by_containment_and_orphans_counted(self) -> None:
        take_one = ("gen-1", 1, "custom/speed/medium/cold#0")
        take_two = ("gen-2", 2, "custom/speed/medium/warm#0")
        correlated = {
            take_one: [
                ("Native Prepare Generation", intervals.Interval("Native Prepare Generation", 0, 50 * MS)),
                ("Native Generation Stream", intervals.Interval("Native Generation Stream", 100 * MS, 400 * MS)),
            ],
            take_two: [
                ("Native Generation Stream", intervals.Interval("Native Generation Stream", 1_000 * MS, 400 * MS)),
            ],
        }
        windows = intervals.take_windows(correlated)
        # From the prepare end to the stream end: the engine opens the loop in
        # between, so a first step just before the stream interval is the
        # take's, and prewarm inside the prepare interval is not.
        self.assertEqual(windows[take_one], (50 * MS, 500 * MS))
        self.assertEqual(windows[take_two], (1_000 * MS, 1_400 * MS))
        engine = [
            intervals.Interval("Talker Forward", 10 * MS, MS),       # prewarm: orphan
            intervals.Interval("Talker Forward", 99 * MS, 2 * MS),   # opened before the stream
            intervals.Interval("Talker Forward", 120 * MS, MS),      # take one
            intervals.Interval("Talker Forward", 499.5 * MS, MS),    # straddles the end: orphan
            intervals.Interval("Talker Forward", 1_100 * MS, MS),    # take two
        ]
        assigned, orphans = intervals.assign_intervals(engine, windows)
        self.assertEqual(orphans, 2)
        self.assertEqual([item.start_ns for item in assigned[take_one]], [99 * MS, 120 * MS])
        self.assertEqual([item.start_ns for item in assigned[take_two]], [1_100 * MS])

    def test_a_take_is_complete_only_with_thirty_six_intervals_per_step(self) -> None:
        tokens = 4
        complete = intervals.take_statistics(
            take_index=1, window=(0, 10_000 * MS),
            intervals=loop_intervals(0, tokens + 1), generated_tokens=tokens, timings_ms=None,
        )
        self.assertEqual(complete["loopSteps"], 5)
        self.assertEqual(complete["expectedLoopIntervalCount"], 180)
        self.assertEqual(complete["loopIntervalCount"], 180)
        self.assertTrue(complete["complete"])
        self.assertEqual(complete["intervals"]["tokenRead"]["count"], 5)
        self.assertEqual(complete["intervals"]["codePredictorStep"]["count"], 75)
        # Fifteen 0.4 ms spans per step sum exactly (audit #61): no rounding per span.
        self.assertEqual(complete["intervals"]["codePredictorStep"]["totalMS"], 30.0)

        short = intervals.take_statistics(
            take_index=1, window=(0, 10_000 * MS),
            intervals=loop_intervals(0, tokens + 1, drop=1), generated_tokens=tokens, timings_ms=None,
        )
        self.assertEqual(short["loopIntervalCount"], 179)
        self.assertFalse(short["complete"])

    def test_the_witness_counts_spans_that_drift_from_the_jsonl_totals(self) -> None:
        tokens = 1
        spans = loop_intervals(0, tokens + 1)
        timings = {
            "qwen_talker_forward_total": 1,      # 2 x 0.4 ms = 0.8 ms: within 5 ms
            "qwen_stream_step_token_read_total": 40,  # 2 x 2 ms = 4 ms: drifts 36 ms
            "qwen_stream_decoder_total": 9,      # no Audio Decoder interval: not compared
        }
        statistics = intervals.take_statistics(
            take_index=1, window=(0, 10_000 * MS), intervals=spans,
            generated_tokens=tokens, timings_ms=timings,
        )
        self.assertEqual(statistics["witness"]["comparedCount"], 2)
        self.assertEqual(statistics["witness"]["outsideToleranceCount"], 1)
        self.assertEqual(statistics["witness"]["maximumDriftMS"], 36.0)

    def test_the_published_block_validates_and_rejects_drift(self) -> None:
        correlation = ("gen-1", 1, "custom/speed/medium/cold#0")
        takes, orphans = intervals.interval_statistics(
            correlated={
                correlation: [(
                    "Native Generation Stream",
                    intervals.Interval("Native Generation Stream", 0, 10_000 * MS),
                )],
            },
            engine_intervals=loop_intervals(MS, 3),
            expectations={correlation: {"generatedTokens": 2, "timingsMS": {}}},
        )
        self.assertEqual(orphans, 0)
        summary = {
            "signpostSummaryVersion": 1,
            "signpostIntervalCount": 120,
            "signpostBeginCount": 0,
            "signpostEndCount": 0,
            "signpostPointCount": 3,
            "orphanIntervalCount": orphans,
            "recordedDurationSeconds": 12.5,
            "intervalStatistics": {"version": 1, "takes": takes},
        }
        intervals.validate_signpost_summary(summary, take_indices=[1], require_complete=True)

        def mutated(change) -> dict:
            candidate = copy.deepcopy(summary)
            change(candidate)
            return candidate

        take = lambda value: value["intervalStatistics"]["takes"][0]  # noqa: E731
        for change in (
            lambda value: value.__setitem__("signpostSummaryVersion", 2),
            lambda value: value.__setitem__("orphanIntervalCount", -1),
            lambda value: value.__setitem__("recordedDurationSeconds", 0),
            lambda value: value["intervalStatistics"].__setitem__("takes", []),
            lambda value: take(value).__setitem__("complete", False),
            lambda value: take(value).__setitem__("loopSteps", 9),
            lambda value: take(value).__setitem__("extra", 1),
            lambda value: take(value)["intervals"].__setitem__("unknownInterval", {}),
            lambda value: take(value)["intervals"]["talkerForward"].__setitem__("medianMS", 99.0),
            lambda value: take(value)["witness"].__setitem__("outsideToleranceCount", 99),
        ):
            with self.assertRaises(ValueError):
                intervals.validate_signpost_summary(
                    mutated(change), take_indices=[1], require_complete=True,
                )

        incomplete = mutated(lambda value: take(value).update(
            loopIntervalCount=take(value)["expectedLoopIntervalCount"] - 1, complete=False,
        ))
        with self.assertRaisesRegex(ValueError, "lost loop intervals"):
            intervals.validate_signpost_summary(incomplete, take_indices=[1], require_complete=True)
        # An iPhone profile records the shortfall instead of being refused.
        intervals.validate_signpost_summary(incomplete, take_indices=[1], require_complete=False)

    def test_only_owned_loop_intervals_are_engine_intervals(self) -> None:
        self.assertTrue(intervals.is_engine_interval("Talker Forward", intervals.QWEN3_SIGNPOST_SUBSYSTEM))
        self.assertTrue(intervals.is_engine_interval("Token Read", ""))
        self.assertFalse(intervals.is_engine_interval("Talker Forward", "com.qwenvoice.engine"))
        self.assertFalse(intervals.is_engine_interval("Native Generation Stream", ""))


if __name__ == "__main__":
    unittest.main()
