"""QC v2 fit and eval on synthetic features and labels."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from qc import fit, label, store  # noqa: E402
from qc.features import feature  # noqa: E402
from qc.store import Layout  # noqa: E402


class StatisticsTests(unittest.TestCase):
    def test_clopper_pearson(self):
        self.assertEqual(fit.clopper_pearson(0, 10), (0.0, 0.3085))
        self.assertEqual(fit.clopper_pearson(10, 10), (0.6915, 1.0))
        self.assertEqual(fit.clopper_pearson(5, 10), (0.1871, 0.8129))
        self.assertEqual(fit.clopper_pearson(0, 0), (None, None))
        lower, upper = fit.clopper_pearson(7.5, 12.3)  # effective counts
        self.assertTrue(0 < lower < 7.5 / 12.3 < upper < 1)

    def test_weighted_rate_uses_the_effective_sample_size(self):
        equal = fit.weighted_rate([True] * 8 + [False] * 2, [1.0] * 10)
        self.assertEqual((equal["rate"], equal["lower"]), (0.8, fit.clopper_pearson(8, 10)[0]))
        skewed = fit.weighted_rate([True] * 8 + [False] * 2, [10.0] + [1.0] * 9)
        self.assertGreater(skewed["upper"] - skewed["lower"], equal["upper"] - equal["lower"])

    def test_logistic_and_cut(self):
        rng = np.random.default_rng(0)
        x = rng.normal(size=(400, 2))
        y = (x[:, 0] + 0.2 * rng.normal(size=400) > 0.5).astype(float)
        intercept, weights = fit.fit_logistic(x, y, np.ones(400), l2=1.0)
        self.assertGreater(weights[0], 2.0)
        self.assertLess(abs(weights[1]), 0.5)
        self.assertEqual(fit.best_cut([0.1, 0.4, 0.6, 0.9], [0, 0, 1, 1], [1, 1, 1, 1]), 0.6)
        self.assertIsNone(fit.best_cut([0.1, 0.2], [0, 0], [1, 1]))

    def test_levels(self):
        rules = json.loads((ROOT / "config/qc/detectors.json").read_text())["levels"]

        def row(precision_lower, recall, clean_upper):
            return {"precision": {"lower": precision_lower}, "recall": {"rate": recall},
                    "cleanFalseAlarms": {"upper": clean_upper}}

        self.assertEqual(fit.level_for(row(0.85, 0.3, 0.04), rules, False), "fail")
        self.assertEqual(fit.level_for(row(0.85, 0.7, 0.2), rules, False), "warn")
        self.assertEqual(fit.level_for(row(0.65, 0.5, 0.01), rules, False), "report-only")
        self.assertEqual(fit.level_for(row(0.95, 0.9, 0.0), rules, True), "report-only")


class FitEvalTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = Layout(self.root)
        self.layout.config.mkdir(parents=True)
        for name in ("detectors.json", "protocol.json"):
            shutil.copyfile(ROOT / "config/qc" / name, self.layout.config / name)
        rng = random.Random(4)
        rows, items, takes, labels = [], [], {}, []
        for language in ("french", "english"):
            for index in range(200):
                token = store.take_token("pool", f"{language}-{index}")
                gap_defect = index % 10 < 3
                stutter = index % 10 == 9
                values = {
                    "pause.longest_gap_seconds": feature(rng.gauss(1.0, 0.15) if gap_defect else rng.gauss(0.25, 0.08)),
                    "pause.nonspeech_level_db": feature(rng.gauss(-5, 3) if gap_defect else rng.gauss(-30, 5)),
                    "pause.voiced_blips": feature(1 if gap_defect and rng.random() < 0.6 else 0),
                    "llm.stutter": feature(1.0 if stutter else 0.0),
                    "llm.cutoff": feature(float(rng.random() < 0.5)),
                }
                rows.append({"token": token, "takeID": f"{language}-{index}", "language": language, "features": values})
                split = "train" if (index // 10) % 5 < 3 else "heldout"
                item_token = label.label_token("b1", 0, token, 0)
                items.append({"token": item_token, "takeToken": token, "repeatOf": None, "split": split,
                              "inclusionProbability": 0.5, "stratum": language, "enriched": False, "reasons": [],
                              "order": len(items)})
                takes[token] = {"token": token, "takeID": f"{language}-{index}", "language": language}
                classes = {}
                if gap_defect:
                    classes["pause"] = {"severity": "moderate", "start": None, "end": None}
                if stutter:
                    classes["stutter"] = {"severity": "moderate", "start": None, "end": None}
                labels.append({"token": item_token, "batch": "b1", "rater": "maintainer", "classes": classes,
                               "verdict": "objectionable" if classes else "acceptable", "acousticOnly": False,
                               "labelledAt": "2026-10-01T21:00:00Z"})
        run = self.layout.runs / "pool-1"
        run.mkdir(parents=True)
        store.write_json_atomic(run / "features.json", {
            "schema": "vocello.qc.features/1", "run": "pool-1", "lane": "pool",
            "models": {"asrA": {"id": "asr.x", "runnerSHA256": "a" * 64, "available": True}}, "takes": rows})
        label.write_batch(self.layout, {"schema": label.BATCH_SCHEMA, "batch": "b1", "kind": "sample",
                                        "createdAt": "x", "params": {}, "items": items, "takes": takes})
        for row in labels:
            store.append_jsonl(self.layout.labels / "b1.jsonl", row)

    def tearDown(self):
        self.directory.cleanup()

    def git(self, *arguments):
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=qc", "-c", "user.email=qc@example.com",
                        *arguments], check=True, capture_output=True)

    def test_fit_then_eval_once_on_a_committed_thresholds_file(self):
        path = fit.fit(self.layout)
        self.assertEqual(path.name, "thresholds-v1.json")
        thresholds = store.read_json(path)
        pause = thresholds["detectors"]["pause.anomalous"]
        self.assertFalse(pause["reportOnly"])
        self.assertEqual(set(pause["models"]), {"french", "english", "*"})  # 120 train takes per language
        self.assertEqual(pause["train"]["positives"], 72)
        self.assertTrue(thresholds["detectors"]["content.phoneme"]["reportOnly"])  # its features never computed
        self.assertTrue(thresholds["detectors"]["level.loudness"]["advisory"])
        self.assertFalse(thresholds["detectors"]["judge.llm.stutter"]["reportOnly"])  # kappa 1.0
        self.assertTrue(thresholds["detectors"]["judge.llm.cutoff"]["reportOnly"])  # no cutoff labels
        self.assertEqual(thresholds["models"], {"asrA": {"id": "asr.x", "runnerSHA256": "a" * 64}})
        self.assertEqual(len(thresholds["labelSet"]["digest"]), 64)

        with self.assertRaisesRegex(fit.FitError, "not committed"):
            fit.evaluate(self.layout)
        self.git("init", "-q")
        self.git("add", "config/qc/thresholds-v1.json")
        self.git("commit", "-q", "-m", "thresholds v1")
        output = fit.evaluate(self.layout)
        self.assertEqual(output, self.root / "benchmarks/qc/eval-v1.json")
        evaluation = store.read_json(output)
        french = evaluation["detectors"]["pause.anomalous"]["languages"]["french"]
        self.assertEqual(french["n"], 80)
        self.assertGreaterEqual(french["recall"]["rate"], 0.9)
        self.assertGreaterEqual(french["precision"]["lower"], 0.8)
        # No clean false alarm, but 48 clean held-out takes bound the rate only below 7.4%:
        # above the 5% a fail needs, so the detector earns warn.
        self.assertEqual(french["cleanFalseAlarms"]["rate"], 0.0)
        self.assertAlmostEqual(french["cleanFalseAlarms"]["upper"], 0.074, delta=0.002)
        self.assertEqual(french["level"], "warn")
        self.assertEqual(evaluation["detectors"]["content.phoneme"]["languages"]["french"]["level"], "report-only")
        self.assertEqual(fit.levels_for(self.layout, self.layout.config / "thresholds-v1.json")["pause.anomalous"]
                         ["french"], "warn")
        with self.assertRaisesRegex(fit.FitError, "scored once"):
            fit.evaluate(self.layout)

        # A thresholds file changed after its commit is refused.
        output.unlink()
        path.write_text(path.read_text().replace('"version": 1', '"version": 1 '))
        with self.assertRaisesRegex(fit.FitError, "not committed"):
            fit.evaluate(self.layout)

    def test_next_fit_is_a_new_version_and_queue_labels_never_enter_eval(self):
        fit.fit(self.layout)
        self.assertEqual(fit.fit(self.layout).name, "thresholds-v2.json")
        rows = fit.label_rows(self.layout)
        self.assertTrue(all(row["probabilitySample"] and row["weight"] == 2.0 for row in rows))


if __name__ == "__main__":
    unittest.main()
