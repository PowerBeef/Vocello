#!/usr/bin/env python3
"""Unit tests for scripts/delivery_matrix_report.py."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delivery_matrix_report import (
    build_report,
    emit_expectations,
    expectation_candidates,
    intensity_ladder,
    load_matrix,
    per_preset_statistics,
)
from prosody_profile import _validate_delivery_expectations, builtin_profile


def records(cell_features, seeds=12):
    """Synthetic sweep: each cell's feature moves by a fixed amount per seed."""
    built = []
    for (preset, intensity), features in cell_features.items():
        for seed in range(seeds):
            wobble = 0.05 * ((seed % 5) - 2)
            built.append({
                "preset": preset,
                "intensity": intensity,
                "seed": f"seed-{seed}",
                "features": {name: value + wobble for name, value in features.items()},
            })
    return built


class MatrixReportTests(unittest.TestCase):
    def test_a_consistently_moved_feature_becomes_an_expectation_candidate(self):
        data = records({
            ("alpha", "normal"): {"pitch_shift_semitones": 2.4, "rate_delta_hz": 0.02},
            ("beta", "normal"): {"pitch_shift_semitones": -2.1, "rate_delta_hz": 0.01},
        })
        statistics = per_preset_statistics(data)
        candidates = expectation_candidates(statistics)
        alpha = {item["feature"]: item for item in candidates["alpha.normal"]}
        self.assertIn("pitch_shift_semitones", alpha)
        self.assertEqual(alpha["pitch_shift_semitones"]["direction"], 1)
        beta = {item["feature"]: item for item in candidates["beta.normal"]}
        self.assertEqual(beta["pitch_shift_semitones"]["direction"], -1)

    def test_a_feature_that_barely_moves_is_not_promoted(self):
        # rate_delta_hz sits at ~0.02 with 0.05 wobble: it is consistent in sign
        # for some seeds but carries no effect worth asserting.
        data = records({("alpha", "normal"): {"pitch_shift_semitones": 2.4,
                                              "rate_delta_hz": 0.02}})
        candidates = expectation_candidates(per_preset_statistics(data))
        promoted = {item["feature"] for item in candidates["alpha.normal"]}
        self.assertNotIn("rate_delta_hz", promoted)

    def test_composite_scores_are_never_promoted_as_expectations(self):
        # Binding a composite hides which acoustic property actually moved --
        # the exact reason the old profile could not explain whisper.
        data = records({("alpha", "normal"): {"arousal_score": 3.0,
                                              "voice_tension_score": 3.0,
                                              "voice_breathiness_score": 3.0}})
        candidates = expectation_candidates(per_preset_statistics(data))
        self.assertEqual(candidates["alpha.normal"], [])

    def test_statistics_carry_correction_effect_size_and_interval(self):
        data = records({("alpha", "normal"): {"pitch_shift_semitones": 2.4}})
        rows = per_preset_statistics(data)["alpha.normal"]
        row = rows[0]
        for key in ("adjustedP", "significant", "cohensDz", "ciLower", "ciUpper", "winRate"):
            self.assertIn(key, row)
        self.assertTrue(row["significant"])

    def test_features_with_too_few_observations_are_skipped(self):
        sparse = [
            {"preset": "alpha", "intensity": "normal", "seed": "s1",
             "features": {"only_once": 1.0, "always": 2.0}},
            {"preset": "alpha", "intensity": "normal", "seed": "s2", "features": {"always": 2.1}},
            {"preset": "alpha", "intensity": "normal", "seed": "s3", "features": {"always": 2.2}},
        ]
        names = {row["feature"] for row in per_preset_statistics(sparse)["alpha.normal"]}
        self.assertIn("always", names)
        self.assertNotIn("only_once", names)

    def test_load_matrix_preserves_engine_seed_across_speakers(self):
        with tempfile.TemporaryDirectory() as directory:
            for name, speaker in (("aiden.json", "aiden"), ("vivian.json", "vivian")):
                rows = [{
                    "delivery": "angry.strong",
                    "generationID": f"gen-{name}",
                    "seed": 20261001,
                    "speakerID": speaker,
                    "deliveryGate": {
                        "preset": "angry", "intensity": "strong",
                        "metrics": {"pitch_shift_semitones": 1.0},
                    },
                }]
                Path(directory, name).write_text(json.dumps(rows))
            loaded = load_matrix([
                os.path.join(directory, "aiden.json"),
                os.path.join(directory, "vivian.json"),
            ])
        self.assertEqual(len(loaded), 2)
        self.assertEqual({record["seed"] for record in loaded}, {20261001})
        self.assertEqual({record["speakerID"] for record in loaded}, {"aiden", "vivian"})

    def test_load_matrix_uses_filename_only_for_legacy_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "legacy-seed.json")
            path.write_text(json.dumps([{
                "delivery": "calm.strong",
                "deliveryGate": {
                    "preset": "calm", "intensity": "strong",
                    "metrics": {"rate_delta_hz": -0.5},
                },
            }]))
            loaded = load_matrix([str(path)])
        self.assertEqual(loaded[0]["seed"], "legacy-seed")

    def test_derived_expectations_validate_against_the_profile_schema(self):
        data = records({
            ("alpha", "normal"): {"pitch_shift_semitones": 2.4, "hnr_delta_db": -3.0},
            ("alpha", "strong"): {"pitch_shift_semitones": 3.6, "hnr_delta_db": -4.5},
        })
        derived = emit_expectations(expectation_candidates(per_preset_statistics(data)))
        self.assertIn("alpha", derived)
        block = dict(builtin_profile()["delivery_expectations"])
        block["presets"] = derived
        _validate_delivery_expectations(block)

    def test_required_tier_needs_the_strong_cell_to_agree_in_direction(self):
        # A feature the strong tier pushes the *other* way is not a stable
        # description of the preset, whatever the normal tier measured.
        data = records({
            ("alpha", "normal"): {"pitch_shift_semitones": 2.4},
            ("alpha", "strong"): {"pitch_shift_semitones": -2.4},
        })
        derived = emit_expectations(expectation_candidates(per_preset_statistics(data)))
        self.assertEqual(derived["alpha"]["pitch_shift_semitones"]["tier"], "supporting")
        self.assertEqual(derived["alpha"]["pitch_shift_semitones"]["min_effect_normal"], 0.0)

    def test_required_magnitude_is_half_the_measured_normal_median(self):
        data = records({
            ("alpha", "normal"): {"pitch_shift_semitones": 2.0},
            ("alpha", "strong"): {"pitch_shift_semitones": 3.0},
        }, seeds=12)
        derived = emit_expectations(expectation_candidates(per_preset_statistics(data)))
        entry = derived["alpha"]["pitch_shift_semitones"]
        self.assertEqual(entry["tier"], "required")
        # Magnitudes come from the normal cell because the profile scales by
        # intensity; binding the strong median would double-count the tier.
        self.assertAlmostEqual(entry["min_effect_normal"], 1.0, delta=0.05)

    def test_intensity_ladder_separates_amplified_from_saturated(self):
        data = records({
            ("grows", "normal"): {"pitch_shift_semitones": 2.0},
            ("grows", "strong"): {"pitch_shift_semitones": 3.4},
            ("flat", "normal"): {"pitch_shift_semitones": 2.0},
            ("flat", "strong"): {"pitch_shift_semitones": 1.2},
        })
        ladder = intensity_ladder(per_preset_statistics(data))
        self.assertEqual(ladder["grows"]["amplified"], ["pitch_shift_semitones"])
        self.assertGreater(ladder["grows"]["medianStrongToNormalRatio"], 1.0)
        # Saturation: strong moves the same axis less than normal does, so the
        # 1.15x-scaled expectation is a bar it was never going to clear.
        self.assertEqual(ladder["flat"]["saturated"], ["pitch_shift_semitones"])
        self.assertLess(ladder["flat"]["medianStrongToNormalRatio"], 1.0)

    def test_intensity_ladder_reports_a_reversed_feature(self):
        data = records({
            ("backwards", "normal"): {"pitch_shift_semitones": 2.0},
            ("backwards", "strong"): {"pitch_shift_semitones": -1.5},
        })
        ladder = intensity_ladder(per_preset_statistics(data))
        self.assertEqual(ladder["backwards"]["reversed"], ["pitch_shift_semitones"])

    def test_report_bundles_both_separability_label_modes(self):
        data = records({
            ("alpha", "normal"): {"pitch_shift_semitones": 2.4, "rate_delta_hz": 1.0},
            ("alpha", "strong"): {"pitch_shift_semitones": 3.4, "rate_delta_hz": 2.0},
            ("beta", "normal"): {"pitch_shift_semitones": -2.4, "rate_delta_hz": -1.0},
            ("beta", "strong"): {"pitch_shift_semitones": -3.4, "rate_delta_hz": -2.0},
        })
        report = build_report(data)
        self.assertIn("separabilityByCell", report)
        self.assertIn("separabilityByPreset", report)
        self.assertEqual(report["seedCount"], 12)
        self.assertEqual(report["cellCount"], 4)

    def test_report_exposes_speaker_balanced_and_held_out_speaker_results(self):
        data = []
        for speaker_index, speaker in enumerate(("aiden", "vivian", "ryan")):
            for seed in range(4):
                for preset, base in (("happy", 2.0), ("sad", -2.0)):
                    data.append({
                        "preset": preset,
                        "intensity": "strong",
                        "seed": f"seed-{seed}",
                        "speakerID": speaker,
                        "features": {
                            "pitch_shift_semitones": base + speaker_index * 0.1,
                            "rate_delta_hz": base / 2 + seed * 0.01,
                        },
                    })
        report = build_report(data)
        self.assertEqual(report["speakerCount"], 3)
        self.assertEqual(report["speakers"], ["aiden", "ryan", "vivian"])
        self.assertEqual(set(report["perSpeaker"]), {"aiden", "ryan", "vivian"})
        self.assertIsNotNone(report["separabilityHeldOutSpeaker"])
        self.assertTrue(report["speakerBalancedStatistics"])


if __name__ == "__main__":
    unittest.main()
