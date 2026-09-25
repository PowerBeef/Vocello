"""Per-take CPU cycle plausibility of a profile (scripts/lib/trace_cpu.py, audit #97)."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from lib import trace_cpu  # noqa: E402
from lib.trace_intervals import Interval  # noqa: E402

TAKE_ONE = ("gen-1", 1, "custom/speed/medium/cold#0")
TAKE_TWO = ("gen-2", 2, "custom/speed/medium/warm#0")


def correlated() -> dict:
    return {
        TAKE_ONE: [
            ("Native Prepare Generation", Interval("Native Prepare Generation", 0.0, 100.0)),
            ("Native Generation Stream", Interval("Native Generation Stream", 200.0, 800.0)),
        ],
        TAKE_TWO: [
            ("Native Generation Stream", Interval("Native Generation Stream", 2_000.0, 1_000.0)),
        ],
    }


class CPUPlausibilityTests(unittest.TestCase):
    def test_cycles_are_summed_over_each_generation_window_and_judged_per_take(self) -> None:
        samples = [
            (50.0, 1e9),       # inside take 1's prepare interval: its window starts there
            (900.0, 1e9),      # inside take 1's stream
            (1_500.0, 9e9),    # between the takes: nobody's
            (2_500.0, 0.5e9),  # take 2
        ]
        block = trace_cpu.cpu_plausibility(
            samples=samples, unresolved_rows=3, correlated=correlated(),
            expectations={TAKE_ONE: {"cpuSeconds": 1.0}, TAKE_TWO: {"cpuSeconds": 1.0}},
        )
        self.assertEqual(block["unresolvedRowCount"], 3)
        self.assertEqual(block["band"], list(trace_cpu.PLAUSIBLE_GIGACYCLES_PER_CPU_SECOND))
        first, second = block["takes"]
        self.assertEqual((first["takeIndex"], first["cycleWeight"]), (1, 2e9))
        self.assertEqual(first["gigacyclesPerCPUSecond"], 2.0)
        self.assertIs(first["plausible"], True)
        # 0.5 GHz: the kind of reading the -O profile gave (0.651).
        self.assertEqual(second["gigacyclesPerCPUSecond"], 0.5)
        self.assertIs(second["plausible"], False)
        self.assertEqual(trace_cpu.implausible_take_indices(block), [2])
        trace_cpu.validate_cpu_plausibility(block, take_indices=[1, 2])

    def test_a_take_without_cpu_seconds_is_not_judged(self) -> None:
        block = trace_cpu.cpu_plausibility(
            samples=[(900.0, 1e9)], unresolved_rows=0, correlated=correlated(),
            expectations={TAKE_ONE: {"cpuSeconds": None}},
        )
        self.assertEqual(block["takes"][0]["gigacyclesPerCPUSecond"], None)
        self.assertIsNone(block["takes"][0]["plausible"])
        self.assertEqual(trace_cpu.implausible_take_indices(block), [])
        trace_cpu.validate_cpu_plausibility(block, take_indices=[1])

    def test_validation_refuses_a_block_that_does_not_add_up(self) -> None:
        block = trace_cpu.cpu_plausibility(
            samples=[(900.0, 2e9), (2_500.0, 3e9)], unresolved_rows=0, correlated=correlated(),
            expectations={TAKE_ONE: {"cpuSeconds": 1.0}, TAKE_TWO: {"cpuSeconds": 1.0}},
        )
        for name, mutate, indices in (
            ("ratio", lambda value: value["takes"][0].__setitem__("gigacyclesPerCPUSecond", 9.0), [1, 2]),
            ("verdict", lambda value: value["takes"][1].__setitem__("plausible", False), [1, 2]),
            ("takes", lambda value: value["takes"].pop(), [1, 2]),
            ("unresolved", lambda value: value.__setitem__("unresolvedRowCount", -1), [1, 2]),
            ("version", lambda value: value.__setitem__("version", 2), [1, 2]),
            ("band", lambda value: value.__setitem__("band", [5.0, 0.8]), [1, 2]),
            ("field", lambda value: value["takes"][0].pop("cpuSeconds"), [1, 2]),
        ):
            broken = copy.deepcopy(block)
            mutate(broken)
            with self.subTest(name=name), self.assertRaises(ValueError):
                trace_cpu.validate_cpu_plausibility(broken, take_indices=indices)


if __name__ == "__main__":
    unittest.main()
