#!/usr/bin/env python3
"""Unit tests for scripts/delivery_listening_session.py.

The build must be blind (no cell information reaches the session manifest),
deterministic for a fixed session seed, tolerant of missing generation arms,
and the scorer must evaluate the pre-registered decision rules from the trial
counts that actually survived.
"""
from __future__ import annotations

import json
from pathlib import Path
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from delivery_listening_session import (
    IDENTIFY_PRESETS,
    REPEAT_COUNT,
    build_session,
    score_session,
)

NORMAL_PRESETS = ["angry", "happy", "surprised", "fearful", "sad", "calm"]


class SessionBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archive_root = self.root / "bench-archive"
        self.clone_dir = self.root / "clone"
        self.clone_dir.mkdir(parents=True)

    def write_archive(
        self, run_id: str, label: str, seed: int, cells: list[tuple[str, str]]
    ) -> None:
        run_dir = self.archive_root / run_id
        run_dir.mkdir(parents=True)
        takes = []
        for index, (preset, tier) in enumerate(cells, start=1):
            name = f"take-{preset}-{tier}.wav"
            (run_dir / name).write_bytes(b"RIFFfake")
            takes.append(
                {
                    "takeIndex": index,
                    "generationID": f"{run_id}-{index}",
                    "outputFileName": name,
                    "delivery": f"{preset}.{tier}",
                }
            )
        (run_dir / "bench-results.json").write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "runID": run_id,
                    "label": label,
                    "seed": seed,
                    "startedAt": f"2026-08-04T0{seed % 10}:00:00Z",
                    "takes": takes,
                }
            ),
            encoding="utf-8",
        )

    def populate(self, strong_seeds: int = 3, normal_seeds: int = 2) -> None:
        for seed in range(1, strong_seeds + 1):
            self.write_archive(
                f"run-a-{seed}", f"calib-a-s{seed}", seed,
                [(preset, "strong") for preset in IDENTIFY_PRESETS],
            )
        for seed in range(1, normal_seeds + 1):
            self.write_archive(
                f"run-n-{seed}", f"calib-n-s{seed}", 100 + seed,
                [(preset, "normal") for preset in NORMAL_PRESETS],
            )
        for stem in ("happy_s1", "sad_s1"):
            (self.clone_dir / f"{stem}.wav").write_bytes(b"RIFFfake")

    def build(self, out_name: str = "session") -> tuple[Path, dict]:
        out = self.root / out_name
        summary = build_session(out, self.archive_root, self.clone_dir)
        return out, summary

    def test_build_is_blind_complete_and_deterministic(self) -> None:
        self.populate()
        out, summary = self.build()

        identify_expected = len(IDENTIFY_PRESETS) * 3 + REPEAT_COUNT + 2
        self.assertEqual(summary["identifyTrials"], identify_expected)
        self.assertEqual(summary["cloneTrials"], 2)
        self.assertEqual(summary["discriminationTrials"], 40)
        self.assertEqual(summary["skippedDesignRows"], [])

        manifest_text = (out / "session-manifest.json").read_text(encoding="utf-8")
        manifest = json.loads(manifest_text)
        # Blindness: the manifest names no cells, tiers, archives, or source
        # filenames — only opaque trial clips and the shared option list.
        for token in ('"cell"', "calib-", "take-", ".strong", ".normal", ".clone"):
            self.assertNotIn(token, manifest_text)
        for trial in manifest["trials"]:
            for clip in trial["audio"]:
                self.assertTrue((out / clip).is_file(), clip)

        keys = {
            stem: json.loads((out / f"key-{stem}.json").read_text(encoding="utf-8"))
            for stem in ("identification", "clone", "2afc")
        }
        key_ids = {entry["id"] for key in keys.values() for entry in key}
        trial_ids = {trial["id"] for trial in manifest["trials"]}
        self.assertEqual(key_ids, trial_ids)
        self.assertEqual(
            sum(len(key) for key in keys.values()),
            len(manifest["trials"]),
        )

        # Determinism: an identical build produces identical artifacts.
        out_again, _ = self.build("session-again")
        self.assertEqual(
            manifest_text,
            (out_again / "session-manifest.json").read_text(encoding="utf-8"),
        )
        for stem in ("identification", "clone", "2afc"):
            self.assertEqual(
                (out / f"key-{stem}.json").read_text(encoding="utf-8"),
                (out_again / f"key-{stem}.json").read_text(encoding="utf-8"),
            )

    def test_missing_normal_arm_degrades_loudly_not_fatally(self) -> None:
        self.populate(normal_seeds=0)
        _, summary = self.build()
        self.assertTrue(summary["skippedDesignRows"])
        for row in summary["skippedDesignRows"]:
            self.assertIn("@normal", row)
        # Strong-tier rows survive.
        self.assertGreater(summary["discriminationTrials"], 0)

    def test_missing_strong_archives_refuse(self) -> None:
        with self.assertRaisesRegex(ValueError, "no strong-tier archives"):
            build_session(self.root / "empty", self.archive_root, None)

    def test_score_applies_the_preregistered_rules(self) -> None:
        self.populate()
        out, _ = self.build()
        # A perfect listener: answer every trial from the sealed keys.
        for stem, transform in (
            ("identification", lambda entry: entry["cell"].split(".")[0].capitalize()),
            ("clone", lambda entry: entry["cell"].split(".")[0].capitalize()),
            ("2afc", lambda entry: entry["correctSide"]),
        ):
            key = json.loads((out / f"key-{stem}.json").read_text(encoding="utf-8"))
            answers = {entry["id"]: transform(entry) for entry in key}
            (out / f"answers-{stem}.json").write_text(
                json.dumps(answers), encoding="utf-8"
            )

        reports = score_session(out)
        decisions = reports["decisions"]
        pooled = decisions["identificationPooled"]
        self.assertTrue(pooled["aboveChance"])
        self.assertEqual(pooled["correct"], pooled["trials"])
        self.assertEqual(pooled["chance"], round(1 / len(IDENTIFY_PRESETS), 4))
        for preset, rule in decisions["identificationPerPreset"].items():
            self.assertTrue(rule["aboveChance"], preset)
        comparison = decisions["cloneVersusInstruct"]
        self.assertEqual(comparison["cloneRecall"]["rate"], 1.0)
        self.assertEqual(decisions["discriminationVerdict"], "no_measured_strong_tier_collapse")
        self.assertTrue(decisions["sessionEngaged"])
        self.assertTrue((out / "session-report.json").is_file())
        # Repeats feed self-agreement, not the confusion matrix.
        agreement = reports["identification"]["selfAgreement"]
        self.assertEqual(agreement["n"], REPEAT_COUNT)
        self.assertEqual(agreement["agreement"], 1.0)


if __name__ == "__main__":
    unittest.main()
