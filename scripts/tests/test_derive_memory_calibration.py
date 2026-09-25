"""The offline derivation of the provisional memory bounds (scripts/derive_memory_calibration.py)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
import benchmark_memory  # noqa: E402
import derive_memory_calibration as calibration  # noqa: E402
import publish_benchmark_history as publisher  # noqa: E402

POLICY = json.loads((ROOT / "config" / "memory-qualification-policy.json").read_text(encoding="utf-8"))


NATIVE_TIER = {"macos": "mid_16gb_mac", "ios": "iphone_pro"}
ABSENT = object()


def record(*, platform: str = "macos", gaps: dict[int, float] | None = None,
           ends: dict[str, list[float]] | None = None, contract: int = 2,
           classification: str = "canonical", runtime_policy: object = None) -> dict:
    """A memory-qualification record; the runtime policy defaults to the
    platform's unforced canonical tier, and ABSENT leaves it out."""
    ends = ends or {"custom": [100.0, 101.0, 100.5], "design": [120.0, 120.0, 120.0],
                    "clone": [140.0, 146.0, 141.0]}
    takes = []
    index = 0
    for mode in ("custom", "design"):
        index += 1
        takes.append({"takeIndex": index, "mode": mode, "cell": f"{mode}/speed/medium/cold#0",
                      "metrics": {"samplerMaximumUnobservedGapMS": 260.0,
                                  "samplerTargetIntervalMS": 250.0}})
    for mode in ("custom", "design", "clone"):
        for repetition, end in enumerate(ends[mode]):
            index += 1
            takes.append({
                "takeIndex": index, "mode": mode,
                "cell": f"{mode}/speed/medium/retained#{repetition}",
                "metrics": {
                    "samplerMaximumUnobservedGapMS": (gaps or {}).get(index, 270.0),
                    "samplerTargetIntervalMS": 250.0,
                    "mlxEndActiveMB": end,
                },
            })
    run = {"kind": "memory-qualification", "platform": platform,
           "id": f"{platform}-memory-qualification-fixture", "classification": classification}
    if runtime_policy is None:
        runtime_policy = {"deviceClass": NATIVE_TIER[platform], "deviceClassForced": False}
    if runtime_policy is not ABSENT:
        run["runtimePolicy"] = runtime_policy
    return {
        "run": run,
        "evidence": {"memoryContractVersion": contract},
        "takes": takes,
    }


class DeriveMemoryCalibrationTests(unittest.TestCase):
    def test_quiet_gaps_keep_twice_the_cadence_and_the_floor(self) -> None:
        report = calibration.derive(record(), POLICY)
        gap = report["unobservedGap"]
        # 270 ms x 1.25 stays under the 500 ms floor: nothing needs more.
        self.assertEqual(gap["proposed"], {"targetIntervalMultiple": 2.0, "floorMS": 500.0})
        self.assertEqual(gap["maximumGapMS"], 270.0)
        self.assertAlmostEqual(gap["maximumGapToCadence"], 1.08)

    def test_a_long_gap_raises_the_multiple_to_cover_it(self) -> None:
        # 610 ms x 1.25 = 762.5 ms at a 250 ms cadence needs 3.05x: 3.25.
        report = calibration.derive(record(gaps={5: 610.0}), POLICY)
        self.assertEqual(report["unobservedGap"]["proposed"]["targetIntervalMultiple"], 3.25)

    def test_retained_bounds_follow_the_growth_and_the_noise(self) -> None:
        bounds = calibration.derive(record(), POLICY)["retainedMemoryV2"]
        # custom: growth 1.0, spread 1.0 -> 1 + 3 = 4 -> 8 -> floor 16.
        self.assertEqual(bounds["custom"]["growthMB"], 1.0)
        self.assertEqual(bounds["custom"]["proposedGrowthLimitMB"], 16.0)
        # design: identical ends still get the 1 MB noise floor.
        self.assertEqual(bounds["design"]["proposedGrowthLimitMB"], 16.0)
        # clone: growth 6, spread 6 -> 6 + 18 = 24.
        self.assertEqual(bounds["clone"]["proposedGrowthLimitMB"], 24.0)

    def test_write_records_a_calibration_the_loaders_accept(self) -> None:
        report = calibration.derive(record(gaps={5: 610.0}), POLICY)
        updated = calibration.apply_to_policy(POLICY, report)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(updated), encoding="utf-8")
            bound = benchmark_memory.load_unobserved_gap_bound(path)
        self.assertEqual((bound.target_interval_multiple, bound.floor_ms), (3.25, 500.0))
        self.assertEqual(updated["unobservedGapBound"]["calibrationRunID"], report["runID"])
        limits = publisher.retained_memory_v2_limits(
            updated["retainedMemoryV2"], list(POLICY["modes"]), "macos",
        )
        self.assertEqual(limits, {"custom": 16.0, "design": 16.0, "clone": 24.0})
        # The iOS entry and the source policy stay as they were.
        self.assertEqual(updated["retainedMemoryV2"]["calibration"]["ios"]["status"], "uncalibrated")
        self.assertEqual(POLICY["unobservedGapBound"]["status"], "provisional")

    def test_an_iphone_record_calibrates_the_floor_tiers_and_its_own_retained_bounds(self) -> None:
        # A 900 ms gap x 1.25 = 1,125 ms: the floor tiers' floor becomes 1,150 ms.
        report = calibration.derive(record(platform="ios", gaps={5: 900.0}), POLICY)
        self.assertEqual(report["unobservedGap"]["tier"], "floorTiers")
        self.assertEqual(report["unobservedGap"]["proposed"], {"floorMS": 1_150.0})
        updated = calibration.apply_to_policy(POLICY, report)
        general = {key: value for key, value in updated["unobservedGapBound"].items() if key != "floorTiers"}
        self.assertEqual(
            general,
            {key: value for key, value in POLICY["unobservedGapBound"].items() if key != "floorTiers"},
        )
        tiers = updated["unobservedGapBound"]["floorTiers"]
        self.assertEqual(
            (tiers["floorMS"], tiers["status"], tiers["calibrationRunID"]),
            (1_150.0, "calibrated", report["runID"]),
        )
        self.assertEqual(updated["retainedMemoryV2"]["calibration"]["ios"]["status"], "calibrated")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_text(json.dumps(updated), encoding="utf-8")
            bound = benchmark_memory.load_unobserved_gap_bound(path)
        self.assertEqual(bound.limit_ms(250.0, floor_tier=True), 1_150.0)
        self.assertEqual(bound.limit_ms(250.0), 500.0)
        # Quiet iPhone gaps bring the tier down to the general floor.
        quiet = calibration.derive(record(platform="ios"), POLICY)
        self.assertEqual(quiet["unobservedGap"]["proposed"], {"floorMS": 500.0})

    def test_an_8gb_mac_record_calibrates_the_floor_tiers_not_the_general_bound(self) -> None:
        report = calibration.derive(
            record(gaps={5: 610.0},
                   runtime_policy={"deviceClass": "floor_8gb_mac", "deviceClassForced": False}),
            POLICY,
        )
        self.assertEqual(report["unobservedGap"]["tier"], "floorTiers")
        # 610 ms x 1.25 = 762.5 ms, rounded up to 800 ms.
        self.assertEqual(report["unobservedGap"]["proposed"], {"floorMS": 800.0})
        updated = calibration.apply_to_policy(POLICY, report)
        self.assertEqual(updated["unobservedGapBound"]["status"], "provisional")
        self.assertEqual(updated["unobservedGapBound"]["floorTiers"]["floorMS"], 800.0)

    def test_a_forced_or_unstamped_tier_calibrates_no_gap_bound(self) -> None:
        for label, runtime_policy in (
            ("forced floor on a larger Mac", {"deviceClass": "floor_8gb_mac", "deviceClassForced": True}),
            ("no runtime policy", ABSENT),
        ):
            with self.subTest(label=label):
                report = calibration.derive(record(runtime_policy=runtime_policy), POLICY)
                self.assertIsNone(report["unobservedGap"]["tier"])
                self.assertIsNone(report["unobservedGap"]["proposed"])
                updated = calibration.apply_to_policy(POLICY, report)
                self.assertEqual(updated["unobservedGapBound"], POLICY["unobservedGapBound"])

    def test_it_refuses_records_that_cannot_calibrate(self) -> None:
        with self.assertRaises(calibration.CalibrationError):
            calibration.derive(record(contract=1), POLICY)
        with self.assertRaises(calibration.CalibrationError):
            calibration.derive(record(ends={"custom": [1.0, 2.0], "design": [1.0, 1.0, 1.0],
                                             "clone": [1.0, 1.0, 1.0]}), POLICY)
        exploratory = calibration.derive(record(classification="exploratory"), POLICY)
        with self.assertRaises(calibration.CalibrationError):
            calibration.apply_to_policy(POLICY, exploratory)

    def test_the_command_reports_without_writing_unless_asked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            record_path = Path(directory) / "record.json"
            policy_path = Path(directory) / "policy.json"
            record_path.write_text(json.dumps(record()), encoding="utf-8")
            policy_path.write_text(json.dumps(POLICY), encoding="utf-8")
            before = policy_path.read_bytes()
            self.assertEqual(calibration.main([str(record_path), "--policy", str(policy_path)]), 0)
            self.assertEqual(policy_path.read_bytes(), before)
            self.assertEqual(
                calibration.main([str(record_path), "--policy", str(policy_path), "--write"]), 0,
            )
            written = json.loads(policy_path.read_text(encoding="utf-8"))
            self.assertEqual(written["unobservedGapBound"]["status"], "calibrated")


if __name__ == "__main__":
    unittest.main()
