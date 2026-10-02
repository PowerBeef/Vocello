"""QC v2 fit and out-of-fold eval on synthetic features and labels."""

from __future__ import annotations

import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from qc import detectors, fit, label, store  # noqa: E402
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


class FoldTests(unittest.TestCase):
    def test_a_family_keeps_its_fold_in_every_batch(self):
        families = [f"fr-{index:04d}" for index in range(1000)]
        folds = [label.fold_for_family(family, 5) for family in families]
        self.assertEqual(folds, [label.fold_for_family(family, 5) for family in families])
        self.assertEqual(set(folds), set(range(5)))
        self.assertTrue(all(150 <= folds.count(fold) <= 250 for fold in range(5)))
        expected = int(store.sha256_text("vocello.qc.fold/1:fr-0101")[:8], 16) % 5
        self.assertEqual(label.fold_for_family("fr-0101"), expected)


def label_row(token, language, *, positive, weight=1.0):
    classes = {"pause": {"severity": "moderate", "start": None, "end": None}} if positive else {}
    return {"batch": "b", "token": token, "language": language, "split": "train", "family": token,
            "weight": weight, "probabilitySample": True, "rater": "maintainer", "minSeverity": "moderate",
            "label": {"verdict": "objectionable" if positive else "acceptable", "classes": classes}}


class PooledFloorTests(unittest.TestCase):
    def test_the_pooled_model_needs_the_positive_floor(self):
        config = json.loads((ROOT / "config/qc/detectors.json").read_text())
        detector = next(item for item in config["detectors"] if item["id"] == "pause.anomalous")
        settings = fit.fit_settings(config)
        self.assertEqual((settings["pooledMinPositive"], settings["crossValidationFolds"]), (10, 5))
        rng = random.Random(1)

        def fitted(positives):
            rows, features = [], {}
            for index in range(80):
                token = f"t{index:03d}"
                defect = index < positives
                rows.append(label_row(token, "french", positive=defect))
                features[token] = {"language": "french", "features": {
                    "pause.longest_gap_seconds": feature(rng.gauss(1.0, 0.1) if defect else rng.gauss(0.25, 0.05))}}
            norm = detectors.normalization(features.values(), ["pause.longest_gap_seconds"])
            return fit.fit_detector(detector, rows, features, norm, settings)

        below = fitted(9)
        self.assertTrue(below["reportOnly"])
        self.assertEqual(below["models"], {})
        self.assertIn("below the pooled floor of 10", below["reason"])
        at = fitted(10)
        self.assertFalse(at["reportOnly"])
        self.assertEqual(set(at["models"]), {"*"})
        with self.assertRaisesRegex(fit.FitError, "crossValidationFolds"):
            fit.fit_settings({"fit": {"crossValidationFolds": 1}})


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
                    "asr.phonetic_error_min": feature(1.0 if stutter else 0.0),
                    "signal.abrupt_offset_db": feature(float(rng.random() < 0.5)),
                }
                rows.append({"token": token, "takeID": f"{language}-{index}", "language": language, "features": values})
                item_token = label.label_token("b1", 0, token, 0)
                items.append({"token": item_token, "takeToken": token, "repeatOf": None, "split": "train",
                              "inclusionProbability": 0.5, "stratum": language, "enriched": False, "reasons": [],
                              "order": len(items)})
                # Script families of four takes (two per language), as the voices of one script.
                takes[token] = {"token": token, "takeID": f"{language}-{index}", "language": language,
                                "family": f"script-{index // 2:03d}"}
                classes = {}
                if gap_defect:
                    classes["pause"] = {"severity": "moderate", "start": None, "end": None}
                if stutter:
                    classes["stutter"] = {"severity": "moderate", "start": None, "end": None}
                labels.append({"token": item_token, "batch": "b1", "rater": "maintainer", "classes": classes,
                               "verdict": "objectionable" if classes else "acceptable", "acousticOnly": False,
                               "labelledAt": "2026-10-01T21:00:00Z"})
        self.rows = rows
        self.families = {token: take["family"] for token, take in takes.items()}
        self.write_features()
        label.write_batch(self.layout, {"schema": label.BATCH_SCHEMA, "batch": "b1", "kind": "sample",
                                        "createdAt": "x", "params": {}, "items": items, "takes": takes})
        for row in labels:
            store.append_jsonl(self.layout.labels / "b1.jsonl", row)

    def tearDown(self):
        self.directory.cleanup()

    def write_features(self, *, scoring=None, runner="a" * 64):
        run = self.layout.runs / "pool-1"
        run.mkdir(parents=True, exist_ok=True)
        store.write_json_atomic(run / "features.json", {
            "schema": "vocello.qc.features/1", "run": "pool-1", "lane": "pool",
            "scoringSHA256": scoring or detectors.scoring_identity(self.layout)["sha256"],
            "models": {"asrA": {"id": "asr.x", "runnerSHA256": runner, "available": True}}, "takes": self.rows})

    def git(self, *arguments):
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=qc", "-c", "user.email=qc@example.com",
                        *arguments], check=True, capture_output=True)

    def commit(self, path):
        if not (self.root / ".git").is_dir():
            self.git("init", "-q")
        self.git("add", str(path.relative_to(self.root)))
        self.git("commit", "-q", "-m", path.name)

    def test_fit_then_eval_once_on_a_committed_thresholds_file(self):
        path = fit.fit(self.layout)
        self.assertEqual(path.name, "thresholds-v1.json")
        thresholds = store.read_json(path)
        pause = thresholds["detectors"]["pause.anomalous"]
        self.assertFalse(pause["reportOnly"])
        self.assertEqual(set(pause["models"]), {"french", "english", "*"})
        self.assertEqual(pause["train"]["positives"], 120)  # the final models train on every label
        self.assertTrue(thresholds["detectors"]["content.phoneme"]["reportOnly"])  # its features never computed
        self.assertTrue(thresholds["detectors"]["level.loudness"]["advisory"])
        self.assertFalse(thresholds["detectors"]["content.asr"]["reportOnly"])  # a second class fits
        self.assertTrue(thresholds["detectors"]["boundary.cutoff"]["reportOnly"])  # no cutoff labels
        self.assertEqual(thresholds["models"], {"asrA": {"id": "asr.x", "runnerSHA256": "a" * 64}})
        self.assertEqual(thresholds["rater"], "maintainer")
        self.assertEqual(thresholds["scoringSHA256"], detectors.scoring_identity(self.layout)["sha256"])
        self.assertEqual(set(thresholds["scoring"]["files"]),
                         {"config/qc/detectors.json", "scripts/qc/features.py", "scripts/qc/detectors.py",
                          "scripts/qc/phones.py", "scripts/qc/pitch.py"})
        self.assertEqual((thresholds["labelSet"]["takes"], len(thresholds["labelSet"]["digest"])), (400, 64))
        validation = thresholds["crossValidation"]
        self.assertEqual((validation["k"], validation["salt"], len(validation["folds"])), (5, label.FOLD_SALT, 5))
        self.assertEqual(sum(400 - fold["takes"] for fold in validation["folds"]), 400)  # each take held out once
        self.assertNotIn("reuse", thresholds)

        with self.assertRaisesRegex(fit.FitError, "not committed"):
            fit.evaluate(self.layout)
        self.commit(path)
        output = fit.evaluate(self.layout)
        self.assertEqual(output, self.root / "benchmarks/qc/eval-v1.json")
        evaluation = store.read_json(output)
        self.assertEqual(evaluation["method"], {"name": "out-of-fold", "k": 5, "salt": label.FOLD_SALT,
                                                "groups": "script family"})
        self.assertEqual(evaluation["labelSet"], {"batches": ["b1"], "takes": 400})
        self.assertEqual(evaluation["detectors"]["pause.anomalous"]["scoredWith"], "out-of-fold")
        french = evaluation["detectors"]["pause.anomalous"]["languages"]["french"]
        self.assertEqual(french["n"], 200)  # every probability-sample take, not a held-out share
        self.assertGreaterEqual(french["recall"]["rate"], 0.9)
        self.assertGreaterEqual(french["precision"]["lower"], 0.8)
        # No clean false alarm among 120 clean takes bounds the rate below 3.1%: under the 5% a fail needs.
        self.assertEqual(french["cleanFalseAlarms"]["rate"], 0.0)
        self.assertAlmostEqual(french["cleanFalseAlarms"]["upper"], 0.0303, delta=0.001)
        self.assertEqual(french["level"], "fail")
        phoneme = evaluation["detectors"]["content.phoneme"]
        self.assertEqual((phoneme["scoredWith"], phoneme["languages"]["french"]["level"]),
                         ("provisional", "report-only"))
        self.assertEqual(fit.levels_for(self.layout, path)["pause.anomalous"]["french"], "fail")
        ledger = store.read_jsonl(self.layout.private / "eval-ledger.jsonl")
        self.assertEqual([(row["version"], row["labelSetDigest"]) for row in ledger],
                         [(1, evaluation["labelSetDigest"])])
        self.assertEqual(ledger[0]["tokens"], sorted(row["token"] for row in self.rows))
        self.assertNotIn(self.rows[0]["token"], output.read_text())  # the committed file holds aggregates only
        with self.assertRaisesRegex(fit.FitError, "evaluated once"):
            fit.evaluate(self.layout)

        # A thresholds file changed after its commit is refused.
        output.unlink()
        path.write_text(path.read_text().replace('"version": 1', '"version": 1 '))
        with self.assertRaisesRegex(fit.FitError, "not committed"):
            fit.evaluate(self.layout)

    def test_eval_scores_each_take_with_a_fold_that_never_trained_on_its_family(self):
        real_fit_detector, real_score = fit.fit_detector, detectors.score

        def fit_detector(detector, train, *args):
            entry = real_fit_detector(detector, train, *args)
            entry["trainedFamilies"] = sorted({row["family"] for row in train})
            return entry

        with mock.patch.object(fit, "fit_detector", fit_detector):
            path = fit.fit(self.layout)
        thresholds = store.read_json(path)
        for entry in thresholds["crossValidation"]["folds"]:
            trained = entry["detectors"]["pause.anomalous"]["trainedFamilies"]
            self.assertFalse([family for family in trained if label.fold_for_family(family, 5) == entry["fold"]])
        self.commit(path)

        by_features = {store.canonical_json(row["features"]): row["token"] for row in self.rows}
        calls = []

        def score(detector, features, language, fitted, norm, **kwargs):
            if detector["id"] == "pause.anomalous":
                calls.append((by_features[store.canonical_json(features)], fitted))
            return real_score(detector, features, language, fitted, norm, **kwargs)

        with mock.patch.object(detectors, "score", score):
            evaluation = store.read_json(fit.evaluate(self.layout))
        self.assertEqual(sorted(token for token, _ in calls), sorted(row["token"] for row in self.rows))
        for token, fitted in calls:
            family = self.families[token]
            self.assertNotIn(family, fitted["trainedFamilies"])  # never the final model, never its own fold
            self.assertTrue(fitted["trainedFamilies"])
        self.assertEqual(evaluation["detectors"]["pause.anomalous"]["unscored"], 0)

    def test_a_label_set_is_evaluated_once_unless_a_reuse_is_declared(self):
        first = fit.fit(self.layout)
        self.commit(first)
        evaluation = store.read_json(fit.evaluate(self.layout))
        second = fit.fit(self.layout)
        self.commit(second)
        with self.assertRaisesRegex(fit.FitError, "eval-v1.json already scored this label set"):
            fit.evaluate(self.layout)
        self.assertFalse((self.root / "benchmarks/qc/eval-v2.json").exists())
        # The private ledger remembers it even when the committed evaluation is gone.
        (self.root / "benchmarks/qc/eval-v1.json").unlink()
        with self.assertRaisesRegex(fit.FitError, "private ledger"):
            fit.evaluate(self.layout)
        with self.assertRaisesRegex(fit.FitError, "reason"):
            fit.fit(self.layout, reuse_reason="  ")
        third = fit.fit(self.layout, reuse_reason="detectors v4 rescored the same batch")
        self.assertEqual(store.read_json(third)["reuse"], {"reason": "detectors v4 rescored the same batch"})
        self.commit(third)
        reused = store.read_json(fit.evaluate(self.layout))
        self.assertEqual(reused["version"], 3)
        self.assertEqual(reused["labelSetDigest"], evaluation["labelSetDigest"])
        self.assertEqual(reused["reuse"]["reason"], "detectors v4 rescored the same batch")
        self.assertEqual(len(store.read_jsonl(self.layout.private / "eval-ledger.jsonl")), 2)

    def test_other_scoring_code_or_models_refuse_the_fit_and_the_evaluation(self):
        self.write_features(scoring="0" * 64)
        with self.assertRaisesRegex(fit.FitError, "other scoring code"):
            fit.fit(self.layout)
        self.write_features()
        path = fit.fit(self.layout)
        self.commit(path)
        # Features scored by other code, or by another model identity, are refused.
        self.write_features(scoring="0" * 64)
        with self.assertRaisesRegex(fit.FitError, "other scoring code"):
            fit.evaluate(self.layout)
        self.write_features(runner="b" * 64)
        with self.assertRaisesRegex(fit.FitError, r"other model identities .*\(asrA\)"):
            fit.evaluate(self.layout)
        # Editing the feature code after the fit refuses the evaluation of that fit.
        self.write_features()
        code = self.root / "scripts/qc/features.py"
        code.parent.mkdir(parents=True)
        code.write_text("# changed feature code\n")
        with self.assertRaisesRegex(fit.FitError, "thresholds-v1.json was fitted with other scoring code"):
            fit.evaluate(self.layout)
        # Labels added after the fit are refused too.
        code.unlink()
        store.append_jsonl(self.layout.labels / "b1.jsonl", dict(
            store.read_jsonl(self.layout.labels / "b1.jsonl")[0], verdict="uncertain"))
        with self.assertRaisesRegex(fit.FitError, "differ from those thresholds-v1.json was fitted on"):
            fit.evaluate(self.layout)
        # Two runs of different scoring identities cannot be mixed.
        other = self.layout.runs / "pool-2"
        other.mkdir()
        store.write_json_atomic(other / "features.json", {"scoringSHA256": "1" * 64, "models": {}, "takes": []})
        with self.assertRaisesRegex(fit.FitError, "runs were scored with different scoring code"):
            fit.feature_rows(self.layout)
        self.assertEqual(fit.feature_rows(self.layout, ["pool-2"])[2], "1" * 64)

    def test_another_rater_is_refused_by_the_evaluation(self):
        path = fit.fit(self.layout)
        self.commit(path)
        with self.assertRaisesRegex(fit.FitError, "rater maintainer, not guest"):
            fit.evaluate(self.layout, rater="guest")

    def test_next_fit_is_a_new_version_and_queue_labels_never_enter_eval(self):
        fit.fit(self.layout)
        self.assertEqual(fit.fit(self.layout).name, "thresholds-v2.json")
        rows = fit.label_rows(self.layout)
        self.assertTrue(all(row["probabilitySample"] and row["weight"] == 2.0 for row in rows))


if __name__ == "__main__":
    unittest.main()
