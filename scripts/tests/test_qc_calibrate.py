"""QC v2 calibration on human controls, human-reference scoring and levels, and chat confirmations."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from qc import calibrate, confirm, detectors, fit, label, lanes, store  # noqa: E402
from qc.features import feature  # noqa: E402
from qc.store import Layout  # noqa: E402

RUNNER = "a" * 64
MODELS = {"asrA": {"id": "asr.x", "runnerSHA256": RUNNER, "available": True}}


def by_id(name: str) -> dict:
    config = json.loads((ROOT / "config/qc/detectors.json").read_text())
    return next(item for item in config["detectors"] if item["id"] == name)


def new_layout(root: Path) -> Layout:
    layout = Layout(root)
    layout.config.mkdir(parents=True)
    for name in ("detectors.json", "protocol.json"):
        shutil.copyfile(ROOT / "config/qc" / name, layout.config / name)
    return layout


def write_run(layout: Layout, run_id: str, lane: str, entries: list[tuple[dict, dict]], *,
              scoring: str | None = None, runner: str = RUNNER) -> Path:
    """A run directory: takes.json and features.json from (take, features) pairs."""

    directory = layout.runs / run_id
    directory.mkdir(parents=True, exist_ok=True)
    takes = [take for take, _ in entries]
    store.write_json_atomic(directory / "takes.json", {"schema": store.TAKES_SCHEMA, "source": run_id, "takes": takes})
    store.write_json_atomic(directory / "features.json", {
        "schema": "vocello.qc.features/1", "run": run_id, "lane": lane,
        "scoringSHA256": scoring or detectors.scoring_identity(layout)["sha256"],
        "models": {"asrA": dict(MODELS["asrA"], runnerSHA256=runner)},
        "takes": [{"token": take["token"], "takeID": take["takeID"], "language": take["language"], "features": values}
                  for take, values in entries]})
    return directory


def human(language: str, index: int, values: dict, *, source: str = "mls") -> tuple[dict, dict]:
    family = f"human:{source}:{language}-spk{index // 3}"
    take = {"takeID": f"human-{source}-{language}-{index}", "token": store.take_token("controls", f"{language}-{index}"),
            "audio": f"/corpora/{language}/{index}.wav", "language": language, "text": "Une phrase lue.",
            "mode": "human", "voice": family, "cell": "control", "reference": None, "family": family,
            "control": True}
    return take, values


def human_values(rng: random.Random, *, excerpt: bool = False) -> dict:
    return {
        "asr.phonetic_error_min": feature(rng.uniform(0.0, 0.2)),
        "pause.longest_gap_seconds": feature(max(0.0, rng.gauss(0.3, 0.1)), 1.0, 1.3),
        "pause.nonspeech_level_db": feature(rng.gauss(-30, 4)),
        "pause.voiced_blips": feature(1.0 if rng.random() < 0.05 else 0.0),
        "pause.excerpt_phones": feature(0.0 if excerpt else None),
        "signal.dropout_seconds": feature(0.0),
        "signal.clipping_fraction": feature(0.0),
        "phones.last_word_coverage": feature(rng.uniform(0.85, 1.0)),
        "signal.abrupt_offset_db": feature(rng.gauss(20, 5)),
        "engine.finish_not_eos": feature(None),
    }


def controls_entries(seed: int = 7) -> list[tuple[dict, dict]]:
    rng = random.Random(seed)
    entries = [human("french", index, human_values(rng, excerpt=index % 25 == 0)) for index in range(1000)]
    entries += [human("english", index, human_values(rng), source="libritts-r") for index in range(200)]
    entries += [human("japanese", index, human_values(rng), source="other") for index in range(80)]
    return entries


def generated(take_id: str, language: str, values: dict, *, mode: str = "custom", audio: str | None = None,
              reference: str | None = None, control: bool = False) -> tuple[dict, dict]:
    take = {"takeID": take_id, "token": store.take_token("pool", take_id), "audio": audio or f"/pool/{take_id}.wav",
            "language": language, "text": f"Script {take_id}.", "mode": mode, "voice": "v", "cell": "standard",
            "reference": reference, "family": take_id.split("--")[0], "finishReason": "eos"}
    if control:
        take["control"] = True
    return take, values


class CalibrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = new_layout(self.root)
        self.entries = controls_entries()
        write_run(self.layout, "controls-1", "controls", self.entries)

    def tearDown(self):
        self.directory.cleanup()

    def test_cuts_sit_at_the_quantile_and_the_check_half_measures_false_alarms(self):
        path, document = calibrate.calibrate(self.layout, controls=["controls-1"])
        self.assertEqual(path.name, "thresholds-v1.json")
        self.assertEqual(store.read_json(path), document)  # the compact writer is plain JSON
        self.assertEqual((document["schema"], document["method"]), (fit.THRESHOLDS_SCHEMA, "human-reference"))
        self.assertEqual(document["scoringSHA256"], detectors.scoring_identity(self.layout)["sha256"])
        self.assertEqual(document["models"], {"asrA": {"id": "asr.x", "runnerSHA256": RUNNER}})
        self.assertEqual(len(document["quantileGrid"]), 219)
        french = document["controls"]["languages"]["french"]
        self.assertEqual((french["takes"], french["speakers"], french["sources"]), (1000, 334, {"mls": 1000}))
        self.assertEqual(french["calibration"] + french["check"], 1000)
        self.assertEqual(document["controls"]["languages"]["english"]["sources"], {"libritts-r": 200})

        asr = document["detectors"]["content.asr"]
        self.assertEqual(asr["unreferenced"], ["asr.edit_rate_min"])  # no control measures it
        reference = asr["languages"]["french"]
        self.assertEqual(set(reference["features"]), {"asr.phonetic_error_min"})
        self.assertEqual(len(reference["features"]["asr.phonetic_error_min"]), 219)
        self.assertAlmostEqual(reference["cut"], 0.99, delta=0.01)
        self.assertLessEqual(reference["calibration"]["rate"], 0.01)
        check = reference["check"]
        self.assertEqual(check["n"], french["check"])
        self.assertLessEqual(check["rate"], 0.03)
        self.assertLess(check["lower"], check["rate"] + 1e-9)
        self.assertGreater(check["upper"], check["rate"])
        # The cut moves with the quantile.
        _, lower = calibrate.calibrate(self.layout, controls=["controls-1"], quantile=0.95)
        self.assertAlmostEqual(lower["detectors"]["content.asr"]["languages"]["french"]["cut"], 0.95, delta=0.015)

        # The split is by speaker: no family on both sides.
        halves = {}
        for take, _ in self.entries:
            halves.setdefault(take["family"], set()).add(calibrate.half_for_family(take["family"]))
        self.assertTrue(all(len(sides) == 1 for sides in halves.values()))

        # Features most people hold at zero cannot flag at zero: the cut sits above every human.
        artifacts = document["detectors"]["signal.artifacts"]["languages"]["french"]
        self.assertEqual(artifacts["cut"], 1.0)
        self.assertEqual(artifacts["check"]["rate"], 0.0)
        pause = document["detectors"]["pause.anomalous"]["languages"]["french"]
        self.assertEqual(pause["unreferenced"], ["pause.excerpt_phones"])  # measured on too few recordings
        self.assertLess(pause["measured"]["pause.excerpt_phones"], calibrate.MIN_FEATURE_VALUES)
        self.assertIn("engine.finish_not_eos", document["detectors"]["boundary.cutoff"]["unreferenced"])

    def test_report_only_where_controls_cannot_reference_a_detector(self):
        _, document = calibrate.calibrate(self.layout, controls=["controls-1"])
        asr = document["detectors"]["content.asr"]
        self.assertEqual(set(asr["languages"]), {"french", "english"})
        self.assertIn("80 human controls measure its features, under 150", asr["reportOnlyLanguages"]["japanese"])
        self.assertEqual(asr["reportOnlyLanguages"]["russian"], "no human controls")
        self.assertFalse(asr["reportOnly"])
        for clone_only in ("prosody.pitch", "identity.drift"):
            entry = document["detectors"][clone_only]
            self.assertTrue(entry["reportOnly"])
            self.assertIn("clone", entry["reason"])
        self.assertTrue(document["detectors"]["level.loudness"]["advisory"])
        phoneme = document["detectors"]["content.phoneme"]
        self.assertEqual((phoneme["reportOnly"], phoneme["reason"]), (True, "no control measures its features"))
        # A lower floor gives Japanese its reference.
        _, small = calibrate.calibrate(self.layout, controls=["controls-1"], min_controls=60)
        self.assertIn("japanese", small["detectors"]["content.asr"]["languages"])

    def test_aggregates_only_and_the_generated_share(self):
        rng = random.Random(3)
        write_run(self.layout, "pool-1", "pool", [
            generated(f"fr-{index:04d}--a", "french", dict(human_values(rng), **{
                "asr.phonetic_error_min": feature(0.6 if index < 10 else 0.05)})) for index in range(40)]
            + [generated("fr-9999--c", "french", human_values(rng), control=True)])
        path, document = calibrate.calibrate(self.layout, controls=["controls-1"], runs=["pool-1"])
        share = document["detectors"]["content.asr"]["languages"]["french"]["generated"]
        self.assertEqual(share["n"], 40)  # the control take is left out
        self.assertEqual(share["rate"], 0.25)
        self.assertEqual(document["generated"], {"runs": ["pool-1"], "takes": 40})
        text = path.read_text()
        for take, _ in self.entries[:50]:
            self.assertNotIn(take["token"], text)
            self.assertNotIn(take["takeID"], text)
            self.assertNotIn(take["audio"], text)
        self.assertNotIn("Une phrase", text)
        self.assertNotIn("spk", text)
        self.assertLess(len(text.splitlines()), 2000)  # the quantile tables stay on one line each

    def test_scoring_identity_and_input_refusals(self):
        write_run(self.layout, "controls-old", "controls", self.entries[:10], scoring="0" * 64)
        with self.assertRaisesRegex(calibrate.CalibrationError, "different scoring code"):
            calibrate.calibrate(self.layout, controls=["controls-1", "controls-old"])
        with self.assertRaisesRegex(calibrate.CalibrationError, "other scoring code .* than the current"):
            calibrate.calibrate(self.layout, controls=["controls-old"])
        write_run(self.layout, "pool-1", "pool", [generated("fr-0001--a", "french", {})])
        with self.assertRaisesRegex(calibrate.CalibrationError, "not a controls run"):
            calibrate.calibrate(self.layout, controls=["pool-1"])
        write_run(self.layout, "pool-old", "pool", [generated("fr-0001--a", "french", {})], scoring="1" * 64)
        with self.assertRaisesRegex(calibrate.CalibrationError, "generated runs were scored with other"):
            calibrate.calibrate(self.layout, controls=["controls-1"], runs=["pool-old"])
        write_run(self.layout, "pool-other", "pool", [generated("fr-0001--a", "french", {})], runner="b" * 64)
        with self.assertRaisesRegex(calibrate.CalibrationError, "another asrA model identity"):
            calibrate.calibrate(self.layout, controls=["controls-1"], runs=["pool-other"])
        with self.assertRaisesRegex(calibrate.CalibrationError, "name it with --controls"):
            calibrate.calibrate(self.layout, controls=["controls-1"], runs=["controls-1"])
        mixed = self.entries[:5] + [generated("fr-0001--a", "french", {})]
        write_run(self.layout, "controls-mixed", "controls", mixed)
        with self.assertRaisesRegex(calibrate.CalibrationError, "not a human control"):
            calibrate.calibrate(self.layout, controls=["controls-mixed"])
        with self.assertRaisesRegex(calibrate.CalibrationError, "no features.json"):
            calibrate.calibrate(self.layout, controls=["controls-missing"])
        with self.assertRaisesRegex(calibrate.CalibrationError, "quantile"):
            calibrate.calibrate(self.layout, controls=["controls-1"], quantile=1.0)
        self.assertFalse(list(self.layout.config.glob("thresholds-v*.json")))


class HumanReferenceScoringTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = new_layout(self.root)
        write_run(self.layout, "controls-1", "controls", controls_entries())
        self.path, self.document = calibrate.calibrate(self.layout, controls=["controls-1"])

    def tearDown(self):
        self.directory.cleanup()

    def test_human_rank_on_a_quantile_table(self):
        grid = detectors.QUANTILE_GRID
        table = calibrate.quantile_table(range(101))  # 0..100: the table is the percentile itself
        self.assertEqual(detectors.human_rank(50.0, table), 0.5)
        self.assertAlmostEqual(detectors.human_rank(99.5, table), 0.995)
        self.assertEqual(detectors.human_rank(100.5, table), 1.0)  # beyond the human maximum
        self.assertEqual(detectors.human_rank(-3.0, table), 0.0)
        zeros = calibrate.quantile_table([0.0] * 90 + [1.0] * 10)
        self.assertEqual(detectors.human_rank(0.0, zeros), 0.0)  # a tie ranks at the bottom of its run
        self.assertAlmostEqual(detectors.human_rank(1.0, zeros), 0.9, delta=0.015)
        self.assertEqual(detectors.human_rank(1.5, zeros), 1.0)
        with self.assertRaises(ValueError):
            detectors.human_rank(1.0, [0.0, 1.0], grid)
        self.assertEqual(calibrate.choose_cut([0.0] * 50, 0.99), 1.0)
        self.assertEqual(calibrate.choose_cut([index / 100 for index in range(100)], 0.95), 0.95)

    def test_flag_beyond_the_humans_pass_within_and_ignore_missing_features(self):
        asr = by_id("content.asr")
        entry = self.document["detectors"]["content.asr"]
        beyond = detectors.score(asr, {"asr.phonetic_error_min": feature(0.6, 1.2, 1.5)}, "french", entry, {})
        self.assertEqual((beyond["score"], beyond["scope"]), (1.0, "human-reference"))
        self.assertGreaterEqual(beyond["score"], beyond["cut"])
        self.assertEqual(beyond["evidence"], [{"feature": "asr.phonetic_error_min", "value": 0.6,
                                               "humanPercentile": 100.0, "start": 1.2, "end": 1.5}])
        within = detectors.score(asr, {"asr.phonetic_error_min": feature(0.1)}, "french", entry, {})
        self.assertAlmostEqual(within["score"], 0.5, delta=0.06)
        self.assertLess(within["score"], within["cut"])
        # asr.edit_rate_min has no reference: alone, it leaves nothing to score.
        missing = detectors.score(asr, {"asr.edit_rate_min": feature(0.9), "asr.phonetic_error_min": feature(None)},
                                  "french", entry, {})
        self.assertEqual((missing["score"], missing["scope"]), (None, "human-reference"))
        ignored = detectors.score(asr, {"asr.edit_rate_min": feature(0.9), "asr.phonetic_error_min": feature(0.1)},
                                  "french", entry, {})
        self.assertEqual(ignored["score"], within["score"])
        # The largest percentile among the measured features wins, with its evidence.
        pause = by_id("pause.anomalous")
        long_gap = detectors.score(pause, {"pause.longest_gap_seconds": feature(3.0, 2.0, 5.0),
                                           "pause.nonspeech_level_db": feature(-30.0)},
                                   "french", self.document["detectors"]["pause.anomalous"], {})
        self.assertEqual(long_gap["evidence"][0]["feature"], "pause.longest_gap_seconds")
        self.assertEqual(long_gap["score"], 1.0)

    def test_a_language_without_reference_keeps_the_provisional_rule_report_only(self):
        pause = by_id("pause.anomalous")
        entry = self.document["detectors"]["pause.anomalous"]
        values = {"pause.longest_gap_seconds": feature(2.0, 1.0, 3.0), "pause.excerpt_phones": feature(0.0)}
        outcome = detectors.score(pause, values, "japanese", entry, {})
        self.assertEqual((outcome["score"], outcome["cut"], outcome["scope"]), (1.0, 1.0, "provisional"))
        asr = detectors.score(by_id("content.asr"), {"asr.phonetic_error_min": feature(0.9)}, "russian",
                              self.document["detectors"]["content.asr"], {"russian": {}})
        self.assertIsNone(asr["cut"])  # no rule: uncalibrated, never flags

        # Through a run's scoring: levels from the evaluation, report-only without a reference.
        evaluation = {"version": 1, "thresholdsSHA256": store.sha256_file(self.path), "detectors": {
            "content.asr": {"languages": {"french": {"level": "warn"}}},
            "pause.anomalous": {"languages": {"french": {"level": "warn"}, "japanese": {"level": "warn"}}}}}
        store.write_json_atomic(self.root / "benchmarks/qc/eval-v1.json", evaluation)
        rows = [{"token": "t-fr", "language": "french", "features": {"asr.phonetic_error_min": feature(0.6)}},
                {"token": "t-ja", "language": "japanese", "features": values}]
        config = detectors.load_config(self.layout)
        flags = lanes.score_run(self.layout, config, rows, MODELS, lane="qc-takes")
        self.assertTrue(flags["thresholdsApplied"])
        self.assertEqual(flags["thresholdsMethod"], "human-reference")
        by_token = {take["token"]: {flag["detector"]: flag for flag in take["flags"]} for take in flags["takes"]}
        french = by_token["t-fr"]["content.asr"]
        self.assertEqual((french["level"], french["scope"]), ("warn", "human-reference"))
        self.assertEqual(french["evidence"][0]["humanPercentile"], 100.0)
        japanese = by_token["t-ja"]["pause.anomalous"]
        self.assertEqual((japanese["level"], japanese["scope"]), ("report-only", "provisional"))
        self.assertEqual((flags["summary"]["warn"], flags["summary"]["report-only"]), (1, 1))
        # Another model identity leaves the run report-only, as for fitted thresholds.
        other = lanes.score_run(self.layout, config, rows, {"asrA": dict(MODELS["asrA"], runnerSHA256="b" * 64)},
                                lane="qc-takes")
        self.assertFalse(other["thresholdsApplied"])
        self.assertIn("another asrA model identity", other["thresholdsReason"])


class HumanReferenceEvalTests(unittest.TestCase):
    """Levels from the human false alarms, and fail only with enough precise confirmations."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = new_layout(self.root)
        write_run(self.layout, "controls-1", "controls", controls_entries())
        audio = self.root / "audio"
        audio.mkdir()
        rng = random.Random(11)
        entries = []
        for index in range(30):
            path = audio / f"fr-{index:04d}.wav"
            path.write_bytes(b"RIFF" + bytes([index]))
            values = dict(human_values(rng), **{"asr.phonetic_error_min": feature(0.7)})  # beyond every human
            entries.append(generated(f"fr-{index:04d}--a", "french", values, audio=str(path)))
        self.pool = write_run(self.layout, "pool-1", "pool", entries)
        self.path, _ = calibrate.calibrate(self.layout, controls=["controls-1"])

    def tearDown(self):
        self.directory.cleanup()

    def git(self, *arguments):
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=qc", "-c", "user.email=qc@example.com",
                        *arguments], check=True, capture_output=True)

    def commit(self, path):
        if not (self.root / ".git").is_dir():
            self.git("init", "-q")
        self.git("add", str(path.relative_to(self.root)))
        self.git("commit", "-q", "-m", path.name)

    def flag_pool(self):
        features = store.read_json(self.pool / "features.json")
        flags = lanes.score_run(self.layout, detectors.load_config(self.layout), features["takes"],
                                features["models"], lane="pool")
        flags.update(run="pool-1", lane="pool")
        store.write_json_atomic(self.pool / "flags.json", flags)

    def confirm(self, n, answers):
        result = confirm.next_batch(self.layout, "pool-1", n=n)
        confirm.record(self.layout, result["batch"], answers)
        return result

    def evaluate(self):
        return store.read_json(fit.evaluate(self.layout))

    def test_warn_from_human_false_alarms_and_fail_from_seventeen_confirmations(self):
        with self.assertRaisesRegex(fit.FitError, "not committed"):
            fit.evaluate(self.layout)
        self.commit(self.path)
        evaluation = self.evaluate()
        self.assertEqual(evaluation["method"]["name"], "human-reference")
        asr = evaluation["detectors"]["content.asr"]
        alarms = asr["languages"]["french"]["humanFalseAlarms"]
        self.assertLessEqual((alarms["rate"], alarms["upper"]), (0.02, 0.06))
        self.assertEqual(asr["languages"]["french"]["level"], "warn")
        self.assertEqual(asr["confirmations"]["flagged"], 0)
        self.assertEqual(evaluation["detectors"]["signal.artifacts"]["languages"]["french"]["level"], "warn")
        self.assertEqual(evaluation["detectors"]["prosody.pitch"]["languages"], {})
        self.assertEqual(fit.levels_for(self.layout, self.path)["content.asr"]["french"], "warn")
        with self.assertRaisesRegex(fit.FitError, "already scored this label set"):
            fit.evaluate(self.layout)

        # Sixteen unusable confirmations are not enough; the seventeenth makes a fail.
        self.flag_pool()
        self.confirm(16, ",".join(f"{k}=x" for k in range(1, 17)))
        evaluation = self.evaluate()
        asr = evaluation["detectors"]["content.asr"]
        self.assertEqual((asr["confirmations"]["flagged"], asr["confirmations"]["precision"]["rate"]), (16, 1.0))
        self.assertEqual(asr["languages"]["french"]["level"], "warn")
        self.assertIn("replaces", evaluation)  # the same version, evaluated on a new label set
        self.confirm(1, "1=x")
        evaluation = self.evaluate()
        asr = evaluation["detectors"]["content.asr"]
        self.assertEqual(asr["confirmations"]["precision"]["n"], 17)
        self.assertGreaterEqual(asr["confirmations"]["precision"]["lower"], 0.8)
        self.assertEqual(asr["languages"]["french"]["level"], "fail")
        # English has no confirmed take, but the precision is pooled: fail wherever the humans allow warn.
        english = asr["languages"]["english"]
        self.assertEqual(english["level"], "fail" if english["humanFalseAlarms"]["upper"] <= 0.06
                         and english["humanFalseAlarms"]["rate"] <= 0.02 else "report-only")
        self.assertEqual(evaluation["labelSet"]["takes"], 17)
        self.assertNotIn(store.take_token("pool", "fr-0000--a"), (self.root / "benchmarks/qc/eval-v1.json").read_text())
        # Usable answers lower the precision: back to warn. Unsure answers count on neither side.
        self.confirm(4, "1=u,2=u,3=u,4=?")
        asr = self.evaluate()["detectors"]["content.asr"]
        self.assertEqual((asr["confirmations"]["flagged"], asr["confirmations"]["uncertain"]), (21, 1))
        self.assertEqual(asr["confirmations"]["precision"]["rate"], round(17 / 20, 4))
        self.assertEqual(asr["languages"]["french"]["level"], "warn")
        self.assertEqual(len(store.read_jsonl(self.layout.private / "eval-ledger.jsonl")), 4)

    def test_eval_reports_precision_by_how_many_detectors_flagged(self):
        self.commit(self.path)
        self.evaluate()
        # The first ten pool takes also lose two seconds of audio: content.asr and signal.artifacts both flag.
        features = store.read_json(self.pool / "features.json")
        for row in features["takes"][:10]:
            row["features"]["signal.dropout_seconds"] = feature(2.0)
        store.write_json_atomic(self.pool / "features.json", features)
        self.flag_pool()
        result = confirm.next_batch(self.layout, "pool-1", n=6, mix_agreement=True)
        items = label.load_batch(self.layout, result["batch"])["items"]
        self.assertEqual(sorted(len(item["reasons"]) for item in items), [1, 1, 1, 2, 2, 2])
        # Agreeing flags unusable, lone flags usable, one lone flag unsure (counted on neither side).
        lone = [k for k, item in enumerate(items, 1) if len(item["reasons"]) == 1]
        confirm.record(self.layout, result["batch"], ",".join(
            f"{k}={'u' if len(item['reasons']) == 1 else 'x'}" if k != lone[0] else f"{k}=?"
            for k, item in enumerate(items, 1)))
        agreement = self.evaluate()["agreement"]["detectorsFlagging"]
        self.assertEqual((agreement["2+"]["n"], agreement["2+"]["rate"]), (3, 1.0))
        self.assertEqual((agreement["1"]["n"], agreement["1"]["rate"]), (2, 0.0))

    def test_eval_refuses_other_scoring_or_controls(self):
        self.commit(self.path)
        rows = store.read_json(self.layout.runs / "controls-1/features.json")
        store.write_json_atomic(self.layout.runs / "controls-1/features.json",
                                dict(rows, takes=rows["takes"][1:]))
        with self.assertRaisesRegex(fit.FitError, "controls runs differ"):
            fit.evaluate(self.layout)
        store.write_json_atomic(self.layout.runs / "controls-1/features.json", rows)
        config = self.layout.config / "detectors.json"
        config.write_text(config.read_text().replace('"failMinConfirmed": 17', '"failMinConfirmed": 18'))
        with self.assertRaisesRegex(fit.FitError, "calibrated with other scoring code"):
            fit.evaluate(self.layout)

    def test_a_declared_reuse_scores_the_same_label_set_again(self):
        self.commit(self.path)
        self.evaluate()
        with self.assertRaisesRegex(fit.FitError, "reason"):
            calibrate.calibrate(self.layout, controls=["controls-1"], reuse_reason=" ")
        second, _ = calibrate.calibrate(self.layout, controls=["controls-1"], quantile=0.995,
                                        reuse_reason="a stricter quantile on the same controls")
        self.commit(second)
        evaluation = store.read_json(fit.evaluate(self.layout))
        self.assertEqual(evaluation["version"], 2)
        self.assertEqual(evaluation["reuse"]["reason"], "a stricter quantile on the same controls")


class ConfirmTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.layout = new_layout(self.root)
        audio = self.root / "audio"
        audio.mkdir()

        def take(take_id, language, flags, **kwargs):
            path = audio / f"{take_id}.wav"
            path.write_bytes(b"RIFF-" + take_id.encode())
            item, _ = generated(take_id, language, {}, audio=str(path), **kwargs)
            item["text"] = f"Texte numéro {take_id[3:7]}."
            return item, [{"detector": detector, "class": cls, "score": score, "level": "report-only"}
                          for detector, cls, score in flags]

        self.take = take
        asr, pause, loud = ("content.asr", "stutter"), ("pause.anomalous", "pause"), ("level.loudness", None)
        self.takes = dict((item["takeID"], (item, flags)) for item, flags in [
            take("fr-0001--a", "french", [pause + (0.999,)]),
            take("fr-0002--b", "french", [asr + (1.0,)]),
            take("fr-0003--c", "french", [asr + (1.0,)], mode="clone", reference=str(audio / "ref.wav")),
            take("fr-0004--d", "french", [asr + (1.0,)], control=True),
            take("en-0005--e", "english", [pause + (0.995,)]),
            take("fr-0006--f", "french", [loud + (1.0,)]),
            take("fr-0007--g", "french", [asr + (0.98,)]),
            take("fr-0008--h", "french", []),
            take("zh-0009--i", "chinese", [asr + (1.0,)]),
            take("fr-0010--j", "french", [asr + (0.97,)]),
        ])
        self.write_flags("pool-1", "qc-takes")

    def tearDown(self):
        self.directory.cleanup()

    def write_flags(self, run_id, lane):
        directory = self.layout.runs / run_id
        directory.mkdir(parents=True, exist_ok=True)
        store.write_json_atomic(directory / "takes.json", {"schema": store.TAKES_SCHEMA, "source": run_id,
                                                           "takes": [item for item, _ in self.takes.values()]})
        store.write_json_atomic(directory / "flags.json", {"lane": lane, "takes": [
            dict({"token": item["token"], "language": item["language"], "flags": flags},
                 **({"control": True} if item.get("control") else {}))
            for item, flags in self.takes.values()]})

    def token(self, take_id):
        return self.takes[take_id][0]["token"]

    def test_next_sends_flagged_takes_blind_never_clones_controls_or_takes_sent_before(self):
        # fr-0007 was answered in an earlier confirm batch.
        earlier = confirm.next_batch(self.layout, "pool-1", n=1, languages=["french"], name="earlier")
        self.assertEqual([item["takeToken"] for item in label.load_batch(self.layout, "earlier")["items"]],
                         [self.token("fr-0002--b")])
        confirm.record(self.layout, earlier["batch"], "1=x")
        batch_items = label.load_batch(self.layout, "earlier")["items"]
        self.assertEqual(batch_items[0]["reasons"], ["content.asr"])

        result = confirm.next_batch(self.layout, "pool-1", n=4)
        self.assertEqual(result["batch"], "confirm-001")
        batch = label.load_batch(self.layout, "confirm-001")
        self.assertEqual(batch["kind"], "confirm")
        chosen = [item["takeToken"] for item in batch["items"]]
        # Round-robin by detector, highest score first, French and English before the rest.
        self.assertEqual(chosen, [self.token("fr-0007--g"), self.token("fr-0001--a"), self.token("fr-0010--j"),
                                  self.token("en-0005--e")])
        for excluded in ("fr-0002--b", "fr-0003--c", "fr-0004--d", "fr-0006--f", "fr-0008--h"):
            self.assertNotIn(self.token(excluded), chosen)
        for item in batch["items"]:
            self.assertIsNone(item["repeatOf"])
            self.assertIsNone(item["inclusionProbability"])
            self.assertIn(item["split"], ("train", "heldout"))
        self.assertEqual([item["order"] for item in batch["items"]], [0, 1, 2, 3])
        folder = self.layout.private / "confirm/confirm-001"
        self.assertEqual(sorted(path.name for path in folder.iterdir()), ["1.wav", "2.wav", "3.wav", "4.wav"])
        self.assertEqual((folder / "2.wav").read_bytes(), b"RIFF-fr-0001--a")
        lines = "\n".join(confirm.next_lines(result))
        for hidden in ("content.asr", "pause.anomalous", "stutter", "fr-0001", "en-0005--e", "score", "0.999",
                       self.token("fr-0001--a")):
            self.assertNotIn(hidden, lines)
        self.assertIn(str(folder / "1.wav"), lines)
        self.assertIn("english: Texte numéro 0005.", lines)
        # With more room, the other languages follow; clones and controls never, nor a take confirm-001
        # sent and nobody answered yet (it stays answerable there).
        more = confirm.next_batch(self.layout, "pool-1", n=10)
        self.assertEqual([item["takeToken"] for item in label.load_batch(self.layout, more["batch"])["items"]],
                         [self.token("zh-0009--i")])
        self.assertEqual(more["batch"], "confirm-002")
        with self.assertRaisesRegex(FileExistsError, "exists"):
            confirm.next_batch(self.layout, "pool-1", name="confirm-002")

    def test_mix_agreement_sends_agreeing_and_lone_flags_half_and_half_in_a_seeded_order(self):
        def candidate(token, language, *names):
            return {"token": token, "language": language,
                    "flags": [{"detector": name, "class": "c", "score": 1.0} for name in names]}

        several = [candidate("a", "french", "content.asr", "pause.anomalous"),
                   candidate("b", "english", "content.phoneme", "content.asr", "prosody.rate"),
                   candidate("f", "chinese", "content.asr", "language.wrong")]
        lone = [candidate("c", "french", "content.asr"), candidate("d", "french", "pause.anomalous"),
                candidate("e", "english", "prosody.rate")]
        self.assertEqual([confirm.agreement(item) for item in several + lone], [2, 3, 2, 1, 1, 1])
        chosen = confirm.pick(several + lone, 4, ["french", "english"], mix_agreement=True, seed="s")
        self.assertEqual(sorted(item["token"] for item in chosen), ["a", "b", "c", "d"])
        orders = {tuple(item["token"] for item in confirm.pick(several + lone, 4, ["french", "english"],
                                                               mix_agreement=True, seed=f"s{k}"))
                  for k in range(8)}
        self.assertGreater(len(orders), 1)  # shuffled, so position says nothing about agreement
        self.assertEqual([item["token"] for item in chosen],
                         [item["token"] for item in confirm.pick(several + lone, 4, ["french", "english"],
                                                                 mix_agreement=True, seed="s")])
        # Either half fills in when the other runs short; without the flag, nothing changes.
        short_several = confirm.pick(several[:1] + lone, 4, ["french"], mix_agreement=True, seed="s")
        self.assertEqual(sorted(item["token"] for item in short_several), ["a", "c", "d", "e"])
        short_lone = confirm.pick(several + lone[:1], 4, ["french", "english"], mix_agreement=True, seed="s")
        self.assertEqual(sorted(item["token"] for item in short_lone), ["a", "b", "c", "f"])
        self.assertEqual([item["token"] for item in confirm.pick(several + lone, 4, ["french", "english"])],
                         ["a", "b", "d", "e"])

        # In a batch: the advisory loudness flag adds no agreement, clones stay out, the params record the mix.
        asr, pause, loud = ("content.asr", "stutter"), ("pause.anomalous", "pause"), ("level.loudness", None)
        for item, flags in (self.take("fr-0011--k", "french", [asr + (0.99,), pause + (0.996,)]),
                            self.take("fr-0012--l", "french", [asr + (0.99,), loud + (1.0,)]),
                            self.take("fr-0013--m", "french", [asr + (1.0,), pause + (1.0,)], mode="clone")):
            self.takes[item["takeID"]] = (item, flags)
        self.write_flags("pool-1", "qc-takes")
        result = confirm.next_batch(self.layout, "pool-1", n=2, name="mix-1", mix_agreement=True)
        batch = label.load_batch(self.layout, "mix-1")
        self.assertTrue(batch["params"]["mixAgreement"])
        self.assertEqual(len(result["takes"]), 2)
        tokens = [item["takeToken"] for item in batch["items"]]
        self.assertIn(self.token("fr-0011--k"), tokens)
        self.assertNotIn(self.token("fr-0013--m"), tokens)
        self.assertEqual(sorted(len(item["reasons"]) for item in batch["items"]), [1, 2])
        self.assertFalse(label.load_batch(self.layout, confirm.next_batch(self.layout, "pool-1", n=1)["batch"])
                         ["params"]["mixAgreement"])

    def test_controls_runs_and_runs_without_sendable_takes_are_refused(self):
        self.write_flags("controls-1", "controls")
        with self.assertRaisesRegex(confirm.ConfirmError, "never sent"):
            confirm.next_batch(self.layout, "controls-1")
        for take_id in ("fr-0001--a", "fr-0002--b", "en-0005--e", "fr-0007--g", "zh-0009--i", "fr-0010--j"):
            Path(self.takes[take_id][0]["audio"]).unlink()
        with self.assertRaisesRegex(confirm.ConfirmError, "flagged no take"):
            confirm.next_batch(self.layout, "pool-1")
        with self.assertRaisesRegex(confirm.ConfirmError, "no flags.json"):
            confirm.next_batch(self.layout, "missing")

    def test_record_maps_answers_to_labels_and_refuses_bad_input(self):
        confirm.next_batch(self.layout, "pool-1", n=3, name="c1")
        summary = confirm.record(self.layout, "c1", "1=x, 2=U; 3=?", classes="1=devoiced:severe,pause:moderate")
        self.assertEqual(summary, {"batch": "c1", "recorded": 3, "takes": 3, "unanswered": 0,
                                   "verdicts": {"objectionable": 1, "acceptable": 1, "uncertain": 1}})
        protocol = label.load_protocol(self.layout)
        rows = store.read_jsonl(self.layout.labels / "c1.jsonl")
        self.assertEqual([row["verdict"] for row in rows], ["objectionable", "acceptable", "uncertain"])
        for row in rows:
            self.assertEqual((row["rater"], row["playedFraction"], row["acousticOnly"], row["batch"]),
                             ("maintainer", 1.0, False, "c1"))
            self.assertEqual(row["protocolSHA256"], label.protocol_digest(protocol))
        self.assertEqual(rows[0]["classes"], {"devoiced": {"severity": "severe", "start": None, "end": None},
                                              "pause": {"severity": "moderate", "start": None, "end": None}})
        self.assertEqual(rows[1]["classes"], {})
        for answers, classes, message in (
                ("9=x", None, "unknown take '9'"), ("1=maybe", None, "answer x"), ("1=x,1=u", None, "twice"),
                ("", None, "no answers"), ("1x", None, "<take>="), ("1=x", "2=pause:moderate", "no answer"),
                ("1=x", "1=nope:severe", "unknown class"), ("1=x", "1=pause:huge", "severity"),
                ("1=x", "pause:mild", "start with their take")):
            with self.subTest(answers=answers, classes=classes):
                with self.assertRaisesRegex(confirm.ConfirmError, message):
                    confirm.record(self.layout, "c1", answers, classes=classes)
        self.assertEqual(len(store.read_jsonl(self.layout.labels / "c1.jsonl")), 3)  # nothing half-written
        label.write_batch(self.layout, {"schema": label.BATCH_SCHEMA, "batch": "s1", "kind": "sample", "createdAt": "x",
                                        "params": {}, "items": [], "takes": {}})
        with self.assertRaisesRegex(confirm.ConfirmError, "not a confirm batch"):
            confirm.record(self.layout, "s1", "1=x")

    def test_confirmations_enter_the_fit_like_queue_labels(self):
        confirm.next_batch(self.layout, "pool-1", n=2, name="c1")
        confirm.record(self.layout, "c1", "1=x,2=u")
        rows = fit.label_rows(self.layout, ["c1"])
        self.assertTrue(all(not row["probabilitySample"] and row["weight"] == 1.0 for row in rows))
        unusable, usable = sorted(rows, key=lambda row: row["label"]["verdict"], reverse=True)
        self.assertEqual(unusable["label"]["verdict"], "objectionable")
        # An unusable take of unknown class says nothing about any one class; a usable one is clean.
        self.assertFalse(fit.usable(unusable, "pause"))
        self.assertTrue(fit.usable(usable, "pause"))
        self.assertTrue(fit.is_clean(usable))


class CommandLineTests(unittest.TestCase):
    def test_calibrate_and_confirm_commands(self):
        spec = importlib.util.spec_from_file_location("qc_cli_calibrate", SCRIPTS / "qc.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        with tempfile.TemporaryDirectory() as directory:
            layout = new_layout(Path(directory))
            write_run(layout, "controls-1", "controls", controls_entries())
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(cli.main(["calibrate", "--controls", "controls-1"], layout=layout), 0)
            self.assertIn("content.asr", output.getvalue())
            self.assertIn("wrote config/qc/thresholds-v1.json", output.getvalue())
            with contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(cli.main(["confirm", "next", "--run", "nope"], layout=layout), 2)
                self.assertEqual(cli.main(["calibrate", "--controls", "nope"], layout=layout), 2)
            self.assertIn("no flags.json", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
