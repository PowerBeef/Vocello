from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import prosody_holdout_validation as module
from prosody_profile import builtin_profile


def policy() -> dict[str, object]:
    value = copy.deepcopy(module.validate_policy())
    value.update({
        "minimumCalibrationClips": 2,
        "minimumHoldoutGoodClips": 2,
        "minimumHoldoutBadClips": 2,
        "minimumHoldoutSpeakerGroups": 2,
        "minimumHoldoutScriptGroups": 2,
        "minimumHoldoutLanguages": 2,
    })
    return value


class ProsodyHoldoutValidationTests(unittest.TestCase):
    def test_empty_preparation_reports_missing_data_not_pass(self):
        result = module.prepare_calibration([], module.validate_policy())
        self.assertEqual(result['additionalAudioMinimum'], {'calibration': 60, 'holdout': 60})
        self.assertEqual(result['status'], 'NEEDS_INDEPENDENT_LABELS')
        self.assertFalse(result['promotionAuthority'])

    def test_blind_preparation_identity_and_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            cal, hold = self._manifests(Path(directory))
            items = [{**{k: v for k, v in row.items() if k not in ('label', 'defectSeverity')}, 'split': split}
                     for split, rows in (('calibration', cal), ('holdout', hold)) for row in rows]
            result = module.prepare_calibration(items, policy())
            self.assertNotIn(directory, json.dumps(result))
            self.assertTrue(all(row['label'] is None for row in result['items']))
            items[0]['requestedLabel'] = 'happy'
            with self.assertRaisesRegex(ValueError, 'labels'):
                module.prepare_calibration(items, policy())
            del items[0]['requestedLabel']
            items[-1]['speakerGroup'] = items[0]['speakerGroup']
            with self.assertRaisesRegex(ValueError, 'leaks speakerGroup'):
                module.prepare_calibration(items, policy())

    def test_calibration_and_holdout_reject_invalid_measurements(self):
        from unittest.mock import patch
        baseline = {metric: 1.0 for metric, _ in module.prosody_calibration.THRESHOLD_MAP.values()}
        key = next(iter(baseline))
        for value in (None, True, '1.0', float('nan'), float('inf')):
            bad = {**baseline, key: value}
            with self.assertRaises(ValueError):
                module._metrics([{'path': 'fixture', 'label': 'good'}], lambda _: bad)
            with patch.object(module.prosody_calibration, 'analyze', return_value=bad):
                good, _, errors = module.prosody_calibration.analyze_corpus([{'path': 'fixture', 'label': 'good'}])
                self.assertEqual(len(errors), 1)
                self.assertTrue(all(not values for values in good.values()))

    def _row(self, root: Path, name: str, label: str, prefix: str, index: int) -> dict[str, object]:
        path = root / f"{name}.wav"
        path.write_bytes(name.encode())
        return {
            "path": str(path),
            "label": label,
            "speakerGroup": f"{prefix}-speaker-{index % 2}",
            "scriptGroup": f"{prefix}-script-{index % 2}",
            "translationGroup": f"{prefix}-translation-{index}",
            "lengthClass": ("short", "medium", "long")[index % 3],
            "language": ("English", "French")[index % 2],
            "defectSeverity": ("none", "mild", "moderate", "severe")[index % 4],
        }

    def _manifests(self, root: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        calibration = [self._row(root, f"cal-{i}", "good" if i % 2 == 0 else "bad", "cal", i) for i in range(4)]
        holdout = [self._row(root, f"hold-{i}", "good" if i < 4 else "bad", "hold", i) for i in range(8)]
        return calibration, holdout

    def test_live_policy_is_frozen_for_independent_coverage(self) -> None:
        live = module.validate_policy()
        self.assertEqual(live["groupIsolation"], ["speakerGroup", "scriptGroup", "translationGroup"])
        self.assertGreaterEqual(live["minimumHoldoutGoodClips"], 30)

    def test_complete_manifests_pass_without_exposing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calibration, holdout = self._manifests(Path(directory))
            summary = module.validate_manifests(calibration, holdout, policy())
            self.assertEqual(summary["holdoutGoodClipCount"], 4)
            self.assertNotIn(directory, json.dumps(summary))

    def test_audio_and_group_leakage_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calibration, holdout = self._manifests(Path(directory))
            holdout[0]["path"] = calibration[0]["path"]
            with self.assertRaisesRegex(module.HoldoutError, "reuse audio"):
                module.validate_manifests(calibration, holdout, policy())
            calibration, holdout = self._manifests(Path(directory))
            holdout[0]["speakerGroup"] = calibration[0]["speakerGroup"]
            with self.assertRaisesRegex(module.HoldoutError, "speakerGroup"):
                module.validate_manifests(calibration, holdout, policy())

    def test_wilson_bounds_are_uncertainty_aware(self) -> None:
        perfect = module._wilson(60, 60)
        none = module._wilson(0, 60)
        self.assertLess(perfect["lower"], 1.0)
        self.assertGreater(none["upper"], 0.0)
        self.assertLess(none["upper"], 0.1)

    def test_profile_binding_rejects_threshold_leakage_and_analyzer_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            calibration, _holdout = self._manifests(Path(directory))
            profile = {
                "calibration_corpus_digest": module.prosody_calibration.corpus_digest(calibration),
                "analyzer_algorithm_version": module.prosody_calibration.analyzer_algorithm_version(),
            }
            module.validate_profile_binding(profile, calibration)
            changed = copy.deepcopy(calibration)
            changed[0]["label"] = "bad"
            with self.assertRaisesRegex(module.HoldoutError, "not bound"):
                module.validate_profile_binding(profile, changed)
            profile["analyzer_algorithm_version"] = "drifted"
            with self.assertRaisesRegex(module.HoldoutError, "analyzer version"):
                module.validate_profile_binding(profile, calibration)

    def test_evaluate_emits_privacy_safe_uncertainty_and_promotion_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calibration, holdout = self._manifests(root)
            calibration_path = root / "calibration.jsonl"
            holdout_path = root / "holdout.jsonl"
            calibration_path.write_text(
                "".join(json.dumps(row) + "\n" for row in calibration),
                encoding="utf-8",
            )
            holdout_path.write_text(
                "".join(json.dumps(row) + "\n" for row in holdout),
                encoding="utf-8",
            )
            profile = copy.deepcopy(builtin_profile())
            profile["calibration_corpus_digest"] = module.prosody_calibration.corpus_digest(calibration)
            profile["analyzer_algorithm_version"] = module.prosody_calibration.analyzer_algorithm_version()
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile), encoding="utf-8")
            config = root / "config"
            config.mkdir()
            (config / "prosody-holdout-policy.json").write_text(
                json.dumps(policy()),
                encoding="utf-8",
            )

            def analyzer(path: str) -> dict[str, float]:
                is_bad = Path(path).stem.startswith("hold-") and int(Path(path).stem.split("-")[1]) >= 4
                return {
                    "f0_std_hz": 1.0 if is_bad else 20.0,
                    "f0_turning_points_per_sec": 1.0 if is_bad else 10.0,
                    "rate_syllable_rate_hz": 4.0,
                    "pauses_pause_speech_ratio": 0.1,
                    "energy_envelope_roughness": 0.2,
                    "rate_local_rate_cv": 0.2,
                    "pauses_max_pause_seconds": 0.2,
                }

            result = module.evaluate(
                calibration_path,
                holdout_path,
                profile_path,
                root=root,
                analyzer=analyzer,
            )
            self.assertIn("falsePositiveRate95CI", result)
            self.assertIn("truePositiveRate95CI", result)
            self.assertNotIn(directory, json.dumps(result))
            self.assertFalse(result["promotionAuthority"])


if __name__ == "__main__":
    unittest.main()
