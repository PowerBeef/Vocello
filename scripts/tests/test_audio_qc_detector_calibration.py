#!/usr/bin/env python3
"""AQ-07 warn-level detector qualification: registry, cohort-split plans, derive and confirm-once."""

from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_calibration_set  # noqa: E402
import audio_qc_detector_calibration as calibration  # noqa: E402
from lib import language_metrics  # noqa: E402
from lib.qc_qualification import detectors, thresholds  # noqa: E402
from lib.qc_qualification.pcm import SeededStream, json_digest  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
LANGUAGES = ("english", "french", "german")
OTHERS = tuple(language for language in language_metrics.PRODUCT_LANGUAGES if language not in LANGUAGES)
WHISPER, PARAKEET = "asr.whisper-large-v3@1", "asr.parakeet-tdt-0.6b-v3@1"
IDENTITY = {WHISPER: "a" * 64, PARAKEET: "b" * 64}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(*argv: str) -> tuple[int, str, str]:
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = calibration.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def git(root: Path, *argv: str) -> None:
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", *argv], check=True, stdout=subprocess.DEVNULL)


def scope(languages=LANGUAGES) -> dict:
    return {"languages": list(languages),
            "exclusions": [{"language": language, "reason": "not-in-fixture"}
                           for language in language_metrics.PRODUCT_LANGUAGES if language not in languages]}


def consensus_entry(detector: str = "test.consensus-error@1", *, source: str = "panel",
                    what: str = "errorRate", injector: str = "CNT-DEL", klass: str = "B") -> dict:
    key = "metric" if source == "panel" else "measure"
    return {
        "id": detector, "class": klass, "stage": 2, "measures": "The smaller of two families' scores.",
        "score": {"combination": "consensus-min", "unit": "error-rate", "groups": [
            {"languages": list(LANGUAGES), "components": [{"source": source, "judge": WHISPER, key: what},
                                                          {"source": source, "judge": PARAKEET, key: what}]}]},
        "direction": "above", "strata": {"by": "language", "reason": "Recognizers differ by language."},
        "scope": scope(), "targets": [{"injectorID": injector, "severities": ["severe"],
                                       "mechanism": "T1-pcm-construction"}],
        "shams": [{"injectorID": injector, "mechanism": "T1-pcm-construction"}],
        "populations": "fleurs-n2", "limitations": ["fleurs-no-speaker-ids"], "risks": ["test-risk"],
    }


def level_entry() -> dict:
    return {
        "id": "test.level@1", "class": "A", "stage": 0, "measures": "RMS level.",
        "score": {"combination": "single", "unit": "dbfs", "groups": [
            {"languages": list(LANGUAGES), "components": [{"source": "fastqc", "field": "rmsDBFS"}]}]},
        "direction": "below", "strata": None, "scope": scope(),
        "targets": [{"injectorID": "SIG-LEVEL", "severities": ["severe"], "mechanism": "T1-pcm-construction"}],
        "shams": [{"injectorID": "SIG-LEVEL", "mechanism": "T1-pcm-construction"}],
        "populations": "fleurs-n2", "limitations": ["fleurs-no-speaker-ids"], "risks": [],
    }


def fixture_registry() -> dict:
    real = json.loads((REPO / calibration.REGISTRY).read_text(encoding="utf-8"))
    return {
        "schemaVersion": 1, "kind": detectors.REGISTRY_KIND, "authority": "test", "note": "test",
        "operatingPoint": "warn", "roleSets": real["roleSets"],
        "limitations": {"fleurs-no-speaker-ids": real["limitations"]["fleurs-no-speaker-ids"]},
        "exclusionReasons": {"not-in-fixture": "The fixture covers three languages."},
        "risks": {"test-risk": "A declared risk."},
        "detectors": [consensus_entry(), level_entry(),
                      consensus_entry("test.truncation@1", source="transcript-tail",
                                      what="trailingUnmatchedFraction", injector="BND-TRUNC", klass="C")],
    }


class Fixture:
    """A temporary repository and two synthetic FLEURS-like N2 cohorts with bundles and measurements."""

    def __init__(self, root: Path, *, per_language: int = 30, positives_per_language: int = 25) -> None:
        self.root = root
        self.repo = root / "repo"
        (self.repo / "config").mkdir(parents=True)
        for name in (calibration.JUDGES, calibration.POLICY):
            shutil.copy(REPO / name, self.repo / name)
        (self.repo / calibration.REGISTRY).write_text(json.dumps(fixture_registry(), indent=2), encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        git(self.repo, "add", "config")
        git(self.repo, "commit", "-q", "--no-verify", "-m", "config")
        self.per_language = per_language
        self.positives_per_language = positives_per_language
        self.calibration = self.cohort("calibration", "c")
        self.confirmation = self.cohort("confirmation", "t")

    # -- cohorts ---------------------------------------------------------------
    def cohort(self, name: str, tag: str) -> Path:
        directory = self.root / name
        directory.mkdir()
        takes = []
        for language in LANGUAGES:
            for index in range(self.per_language):
                takes.append({"takeID": f"{tag}-{language[:2]}-{index:03d}--n2", "family": f"{tag}-{language}-{index}",
                              "language": language, "scriptID": f"flores-{tag}{index % 12}", "eligible": True,
                              "population": "N2"})
        manifest = {"kind": "audio-qc-n2-cohort", "schemaVersion": 1, "manifestDigest": sha(f"{name}-manifest"),
                    "runID": f"run-{name}", "takes": takes}
        path = directory / "n2-manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def takes(self, cohort: Path) -> list[dict]:
        return json.loads(cohort.read_text(encoding="utf-8"))["takes"]

    @staticmethod
    def clean_error(index: int) -> float:
        return round(index / 100.0, 4)

    # -- panel bundles -----------------------------------------------------------
    def bundle(self, directory: Path, rows: list[tuple[str, str, dict, dict | None]]) -> Path:
        """rows: (takeID, language, {judge: metrics or None (out of scope)}, private or None)."""
        (directory / "evidence").mkdir(parents=True)
        (directory / "private").mkdir()
        entries = []
        for number, (take_id, language, metrics, private) in enumerate(rows, 1):
            measurements = [{"judge": judge, "status": "out-of-scope" if values is None else "complete",
                             "metrics": values or {}, "outputIdentity": IDENTITY[judge]}
                            for judge, values in metrics.items()]
            evidence = {"schema": "vocello.audioqc.take-evidence/1", "take": {"takeID": take_id, "language": language},
                        "measurements": measurements}
            evidence_text = json.dumps(evidence)
            private_text = json.dumps(private or {"referenceText": "", "transcripts": {}})
            (directory / "evidence" / f"{number:04d}.json").write_text(evidence_text, encoding="utf-8")
            (directory / "private" / f"{number:04d}.json").write_text(private_text, encoding="utf-8")
            entries.append({"takeID": take_id, "evidence": f"evidence/{number:04d}.json",
                            "evidenceSHA256": sha(evidence_text), "private": f"private/{number:04d}.json",
                            "privateSHA256": sha(private_text)})
        manifest = {"schema": calibration.BUNDLE_SCHEMA, "bundleDigest": sha(str(directory)),
                    "runID": directory.name, "manifestSHA256": sha("panel"), "takes": entries}
        (directory / "bundle.json").write_text(json.dumps(manifest), encoding="utf-8")
        return directory

    def negative_bundle(self, cohort: Path, name: str) -> Path:
        rows = []
        for take in self.takes(cohort):
            index = int(take["takeID"].split("-")[2])
            error = self.clean_error(index)
            rows.append((take["takeID"], take["language"],
                         {WHISPER: {"errorRate": error}, PARAKEET: {"errorRate": round(error + 0.05, 4)}}, None))
        return self.bundle(self.root / name, rows)

    def injection_set(self, injector: str) -> Path:
        entries = []
        for take in self.takes(self.confirmation):
            index = int(take["takeID"].split("-")[2])
            if index >= self.positives_per_language:
                continue
            for severity, population in (("severe", "P1"), ("sham", "S")):
                entries.append({"takeID": f"{take['takeID']}--{injector.lower()}-{severity}",
                                "sourceTakeID": take["takeID"], "family": take["family"],
                                "language": take["language"], "textSHA256": sha("x"),
                                "injection": {"injectorID": injector, "injector": f"{injector}@1", "variant": severity,
                                              "severity": severity, "classes": ["B"],
                                              "mechanism": "T1-pcm-construction", "population": population}})
        path = self.root / f"injection-{injector}.json"
        path.write_text(json.dumps({"kind": calibration.INJECTION_SET_KIND, "schemaVersion": 1,
                                    "sourceManifest": {"sha256": sha("confirmation-manifest")},
                                    "entries": entries}), encoding="utf-8")
        return path

    def positive_bundle(self, injection_set: Path, *, detected: float = 0.5) -> Path:
        rows = []
        for entry in json.loads(injection_set.read_text(encoding="utf-8"))["entries"]:
            value = detected if entry["injection"]["population"] == "P1" else 0.0
            rows.append((entry["takeID"], entry["language"],
                         {WHISPER: {"errorRate": value}, PARAKEET: {"errorRate": value}}, None))
        return self.bundle(self.root / "positive-bundle", rows)

    # -- measurements (class A) --------------------------------------------------
    def measurements(self, cohort: Path, name: str, *, with_positives: bool = False) -> Path:
        clips = []
        # Confirmation levels are spread half as wide, so no clean take reaches the calibration tail.
        spread = 10.0 if cohort == self.calibration else 20.0
        for take in self.takes(cohort):
            index = int(take["takeID"].split("-")[2])
            clips.append({"clipID": take["takeID"], "population": "N2", "family": take["family"],
                          "sourceTakeID": take["takeID"], "language": take["language"], "injection": None,
                          "fastQC": {"rmsDBFS": round(-20.0 - index / spread, 4)}, "observations": {}})
            if with_positives and index < self.positives_per_language:
                for severity, population, level in (("severe", "P1", -70.0), ("sham", "S", -20.0)):
                    clips.append({"clipID": f"{take['takeID']}--level-{severity}", "population": population,
                                  "family": take["family"], "sourceTakeID": take["takeID"],
                                  "language": take["language"],
                                  "injection": {"injector": "SIG-LEVEL@1", "injectorID": "SIG-LEVEL",
                                                "variant": severity, "severity": severity, "classes": ["A"],
                                                "outputPCMSHA256": sha(take["takeID"] + severity)},
                                  "fastQC": {"rmsDBFS": level}, "observations": {}})
        path = self.root / f"{name}.json"
        path.write_text(json.dumps({"kind": calibration.MEASUREMENTS_KIND, "schemaVersion": 1,
                                    "subject": {"detector": "fastqc@8", "mirror": "fastqc-v8-numpy/1"},
                                    "clipsSHA256": sha(name), "clips": clips}), encoding="utf-8")
        return path

    def commit_plans(self) -> None:
        git(self.repo, "add", "config/audio-qc-preregistrations")
        git(self.repo, "commit", "-q", "--no-verify", "-m", "plans")


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.judges = json.loads((REPO / calibration.JUDGES).read_text(encoding="utf-8"))
        self.registry = json.loads((REPO / calibration.REGISTRY).read_text(encoding="utf-8"))

    def errors(self, registry: dict) -> list[str]:
        return detectors.registry_errors(registry, self.judges)

    def test_the_committed_registry_validates(self) -> None:
        self.assertEqual(self.errors(self.registry), [])
        self.assertEqual(self.errors(fixture_registry()), [])
        ids = [entry["id"] for entry in self.registry["detectors"]]
        self.assertEqual(sorted({detectors.detector_entry(self.registry, detector)["class"] for detector in ids}),
                         ["A", "B", "C", "D"])

    def test_fastqc_fields_match_the_measurement_writer(self) -> None:
        self.assertLessEqual(detectors.FASTQC_SCORE_FIELDS, set(audio_qc_calibration_set.FASTQC_FIELDS))

    def mutate(self, detector: str, change) -> list[str]:
        registry = copy.deepcopy(self.registry)
        change(next(entry for entry in registry["detectors"] if entry["id"] == detector), registry)
        return self.errors(registry)

    def test_consensus_refuses_same_lab_same_family_and_non_voting_judges(self) -> None:
        def qwen(entry, _):
            entry["score"]["groups"][0]["components"][1]["judge"] = "asr.qwen3-asr-1.7b@1"
        self.assertTrue(any("A6" in error for error in self.mutate("content.consensus-error@1", qwen)))

        def same_family(entry, _):
            entry["score"]["groups"][0]["components"][1]["judge"] = "asr.whisper-small@1"
        self.assertTrue(any("two recognizer families" in error
                            for error in self.mutate("content.consensus-error@1", same_family)))

        def wrong_direction(entry, _):
            entry["direction"] = "below"
        self.assertTrue(any("direction is above" in error
                            for error in self.mutate("content.consensus-error@1", wrong_direction)))

    def test_a_timing_instrument_needs_two_completed_content_voters(self) -> None:
        def drop_gate(entry, _):
            for group in entry["score"]["groups"]:
                group.pop("requiresComplete")
        self.assertTrue(any("content voters" in error for error in self.mutate("boundary.run-on@1", drop_gate)))

    def test_scope_shams_strata_and_fields(self) -> None:
        def no_exclusion(entry, _):
            entry["scope"]["exclusions"] = []
        self.assertTrue(any("partition" in error for error in self.mutate("boundary.run-on@1", no_exclusion)))

        def no_sham(entry, _):
            entry["shams"] = []
        self.assertTrue(any("matched sham" in error for error in self.mutate("signal.clicks@1", no_sham)))

        def bad_field(entry, _):
            entry["score"]["groups"][0]["components"][0]["field"] = "loudness"
        self.assertTrue(any("Fast QC v8 field" in error for error in self.mutate("signal.clicks@1", bad_field)))

        def undeclared_stratum(entry, _):
            entry["strata"] = {"by": "language", "reason": " "}
        self.assertTrue(any("strata" in error for error in self.mutate("signal.clicks@1", undeclared_stratum)))

        def unused_code(_, registry):
            registry["risks"]["never-used"] = "A risk no detector cites."
        self.assertTrue(any("never-used" in error for error in self.mutate("signal.clicks@1", unused_code)))

        def not_severe(entry, _):
            entry["targets"][0]["severities"] = ["moderate"]
        self.assertTrue(any("severe" in error for error in self.mutate("signal.clicks@1", not_severe)))


class ScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.entry = consensus_entry()

    @staticmethod
    def measurement(value: float | None) -> dict:
        if value is None:
            return {"status": "out-of-scope", "metrics": {}}
        return {"status": "complete", "metrics": {"errorRate": value}}

    def test_consensus_is_the_smaller_score_and_abstains_on_a_missing_family(self) -> None:
        both = detectors.score_take(self.entry, "english", measurements={WHISPER: self.measurement(0.3),
                                                                          PARAKEET: self.measurement(0.1)})
        self.assertEqual((both["score"], both["abstain"], both["inScope"]), (0.1, None, True))
        self.assertEqual(sorted(both["components"].values()), [0.1, 0.3])
        missing = detectors.score_take(self.entry, "english", measurements={WHISPER: self.measurement(0.3)})
        self.assertEqual((missing["score"], missing["abstain"]), (None, "not-measured"))
        outside = detectors.score_take(self.entry, "english", measurements={
            WHISPER: self.measurement(0.3), PARAKEET: self.measurement(None)})
        self.assertEqual(outside["abstain"], "judge-out-of-scope")
        excluded = detectors.score_take(self.entry, "korean", measurements={})
        self.assertEqual((excluded["inScope"], excluded["abstain"]), (False, "out-of-scope"))

    def test_consensus_max_difference_gate_and_transform(self) -> None:
        entry = copy.deepcopy(self.entry)
        entry["score"]["combination"], entry["direction"] = "consensus-max", "below"
        scored = detectors.score_take(entry, "french", measurements={WHISPER: self.measurement(0.2),
                                                                      PARAKEET: self.measurement(0.9)})
        self.assertEqual(scored["score"], 0.9)
        entry["score"]["combination"] = "difference"
        entry["score"]["groups"][0]["requiresComplete"] = [WHISPER, PARAKEET]
        self.assertAlmostEqual(detectors.score_take(entry, "french", measurements={
            WHISPER: self.measurement(0.2), PARAKEET: self.measurement(0.9)})["score"], -0.7)
        gated = detectors.score_take(entry, "french", measurements={WHISPER: self.measurement(0.2)})
        self.assertEqual(gated["abstain"], "content-voters-incomplete")
        tail = {"source": "transcript-tail", "judge": PARAKEET, "measure": "trailingUnmatchedFraction"}
        private = {"referenceText": "one two three", "transcripts": {}}
        empty = {PARAKEET: {"status": "complete", "metrics": {"transcriptEmpty": True}}}
        self.assertEqual(detectors.component_value(tail, language="english", measurements=empty, private=private),
                         (1.0, None))
        lost = {PARAKEET: {"status": "complete", "metrics": {"transcriptEmpty": False}}}
        self.assertEqual(detectors.component_value(tail, language="english", measurements=lost, private=private),
                         (None, "no-transcript"))
        component = {"source": "fastqc", "field": "dcOffset", "transform": "absolute"}
        self.assertEqual(detectors.component_value(component, language="german",
                                                   clip={"fastQC": {"dcOffset": -0.25}}), (0.25, None))
        self.assertEqual(detectors.component_value(component, language="german",
                                                   clip={"fastQC": {"dcOffset": float("nan")}}), (None, "no-value"))


class TrailingDeletionTests(unittest.TestCase):
    def tail(self, reference: str, hypothesis: str, language: str = "english") -> dict:
        return detectors.transcript_tail(reference, hypothesis, language)

    def test_hand_made_transcripts(self) -> None:
        cut = self.tail("The cat sat on the mat.", "the cat sat on")
        self.assertEqual((cut["trailingUnmatched"], cut["trailingDeletions"], cut["referenceUnits"]), (2, 2, 6))
        self.assertAlmostEqual(cut["trailingUnmatchedFraction"], 2 / 6)
        self.assertEqual(self.tail("The cat sat on the mat.", "the cat sat on the mat thank you")
                         ["trailingUnmatched"], 0)
        garbled = self.tail("The cat sat on the mat.", "the cat sat on the hat")
        self.assertEqual((garbled["trailingUnmatched"], garbled["trailingDeletions"]), (1, 0))
        self.assertEqual(self.tail("The cat, sat.", "the cat sat")["trailingUnmatched"], 0)
        chinese = self.tail("今天天气很好。", "今天天气", "chinese")
        self.assertEqual((chinese["trailingUnmatched"], chinese["referenceUnits"]), (2, 6))
        self.assertEqual(self.tail("Hello there.", "", "english")["trailingUnmatchedFraction"], 1.0)
        self.assertIsNone(self.tail("", "anything")["trailingUnmatchedFraction"])

    def test_the_path_is_edit_metrics_alignment(self) -> None:
        stream = SeededStream(7, "trailing-parity")
        for trial in range(200):
            reference = [int(value) for value in stream.integers(4, 1 + trial % 9)]
            hypothesis = [int(value) for value in stream.integers(4, trial % 7)]
            ours = detectors.trailing_unmatched(reference, hypothesis)
            theirs = language_metrics.edit_metrics(reference, hypothesis)
            self.assertEqual((ours["substitutions"], ours["insertions"], ours["deletions"]),
                             (theirs["substitutions"], theirs["insertions"], theirs["deletions"]), trial)


class CohortPlanTests(unittest.TestCase):
    def split(self, **overrides) -> thresholds.CohortSplit:
        base = dict(calibration=thresholds.CohortReference("audio-qc-n2-cohort", "1" * 64, "fleurs-dev"),
                    confirmation=thresholds.CohortReference("audio-qc-n2-cohort", "2" * 64, "fleurs-test"),
                    disjoint_by=("family", "script"), speaker_unit="language:fleurs-unidentified",
                    speaker_claim="lower-bound", limitations=(("fleurs-no-speaker-ids", "No speaker ids."),))
        base.update(overrides)
        return thresholds.CohortSplit(**base)

    def plan(self, **overrides) -> thresholds.PreRegistration:
        base = dict(detector="test.consensus-error@1", rule="split-conformal", alpha=0.05, direction="above",
                    strata=(("language", "Recognizers differ by language."),), cohorts=self.split(),
                    bindings=(("operatingPoint", "warn"), ("detectorDefinitionSHA256", "3" * 64)))
        base.update(overrides)
        return thresholds.PreRegistration(**base)

    def test_hash_split_digests_are_unchanged(self) -> None:
        clicks = thresholds.PreRegistration(detector="fastqc.clicks@8", rule="split-conformal", alpha=0.01,
                                            direction="above", split_salt="salt-1",
                                            strata=(("cjk", "CER languages score differently"),))
        self.assertEqual(clicks.digest(), "42605b336566299791326ba7ec11d7fa06e2586f497305deaaa7f7e954ace086")
        grid = thresholds.PreRegistration(detector="signal.level@1", rule="learn-then-test", alpha=0.05,
                                          direction="below", split_salt="s", grid=(1.0, 2.0),
                                          calibration_fraction=0.4)
        self.assertEqual(grid.digest(), "5569bc38722ae1df65a9918f172eb7f80fe958d358aa1bae9ad9cadb7c5ec8ba")
        self.assertNotIn("bindings", clicks.as_dict())
        self.assertEqual(thresholds.PreRegistration.from_dict(clicks.as_dict()), clicks)

    def test_cohort_plans_are_canonical_and_bound(self) -> None:
        plan = self.plan()
        self.assertEqual(plan.digest(), "6996a8a416a46702c76ad5981fdfc11ff0ae9c6e86b945d5e1b81d0bfde089da")
        self.assertEqual(plan.as_dict()["split"]["method"], "declared-cohorts")
        self.assertEqual(thresholds.PreRegistration.from_dict(json.loads(json.dumps(plan.as_dict()))), plan)
        reordered = self.plan(bindings=tuple(reversed(plan.bindings)))
        self.assertEqual(reordered.digest(), self.plan(bindings=tuple(sorted(plan.bindings))).digest())
        other = self.plan(cohorts=self.split(
            confirmation=thresholds.CohortReference("audio-qc-n2-cohort", "4" * 64, "fleurs-test")))
        self.assertNotEqual(other.digest(), plan.digest())
        self.assertNotEqual(self.plan(bindings=()).digest(), plan.digest())
        with self.assertRaises(thresholds.PreRegistrationError):
            thresholds.split_families([("f", "s", "x")], plan)

    def test_cohort_plans_refuse_undeclared_choices(self) -> None:
        for overrides in ({"split_salt": "salt"}, {"bindings": (("x y", "z"),)},
                          {"bindings": (("a", "1"), ("a", "2"))}):
            with self.assertRaises(thresholds.PreRegistrationError, msg=str(overrides)):
                self.plan(**overrides)
        for overrides in ({"limitations": ()}, {"disjoint_by": ("script",)},
                          {"confirmation": thresholds.CohortReference("audio-qc-n2-cohort", "1" * 64)},
                          {"speaker_claim": "guessed"}):
            with self.assertRaises(thresholds.PreRegistrationError, msg=str(overrides)):
                self.split(**overrides)
        with self.assertRaises(thresholds.PreRegistrationError):
            thresholds.CohortReference("audio-qc-n2-cohort", "not-a-digest")

    def test_the_declared_split_is_checked_on_the_units(self) -> None:
        plan = self.plan()
        calibration_units = [("f1", "english:x", "s1"), ("f2", "french:x", "s2")]
        report = thresholds.check_cohort_disjointness(plan, calibration_units, [("f3", "english:x", "s3")])
        self.assertEqual(report["counts"]["speaker"], {"calibration": 2, "confirmation": 1})
        with self.assertRaises(thresholds.PreRegistrationError):
            thresholds.check_cohort_disjointness(plan, calibration_units, [("f3", "english:x", "s1")])
        with self.assertRaises(thresholds.PreRegistrationError):
            thresholds.check_cohort_disjointness(plan, calibration_units, [("f1", "english:x", "s9")])

    def test_the_detector_store_holds_one_plan_per_detector(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = thresholds.PreRegistrationStore(Path(directory), naming="detector")
            plan = self.plan()
            path = store.commit(plan)
            self.assertEqual(path.name, "test.consensus-error@1.json")
            self.assertEqual(store.load(plan.detector), plan)
            self.assertEqual(store.commit(plan), path)
            with self.assertRaises(thresholds.PreRegistrationError):
                store.commit(self.plan(alpha=0.04))
            self.assertIsNone(store.load("test.other@1"))


class FlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self.directory.name))
        self.out = self.fixture.root / "out"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def cli(self, *argv: str, expect: int = 0) -> str:
        code, out, err = run("--repo-root", str(self.fixture.repo), *argv)
        self.assertEqual(code, expect, f"{argv[0]}: {err}")
        return out + err

    def calibration_scores(self, detector: str = "test.consensus-error@1", **sources: Path) -> Path:
        output = self.out / f"{detector}-calibration.json"
        arguments = ["scores", "--detector", detector, "--role", "calibration", "--cohort",
                     str(self.fixture.calibration), "--output", str(output)]
        for key, value in sources.items():
            arguments += [f"--{key.replace('_', '-')}", str(value)]
        self.cli(*arguments)
        return output

    def plan(self, detector: str, scores: Path, *, expect: int = 0) -> str:
        return self.cli("plan", "--detector", detector, "--calibration-cohort", str(self.fixture.calibration),
                        "--confirmation-cohort", str(self.fixture.confirmation), "--calibration-scores", str(scores),
                        "--alpha", "0.05", expect=expect)

    def confirmation_scores(self, detector: str = "test.consensus-error@1", **sources: Path) -> Path:
        output = self.out / f"{detector}-confirmation.json"
        arguments = ["scores", "--detector", detector, "--role", "confirmation", "--cohort",
                     str(self.fixture.confirmation), "--output", str(output)]
        for key, value in sources.items():
            arguments += [f"--{key.replace('_', '-')}", str(value)]
        self.cli(*arguments)
        return output

    def test_derivation_refuses_an_uncommitted_plan(self) -> None:
        bundle = self.fixture.negative_bundle(self.fixture.calibration, "calibration/panel-bundle-v2")
        scores = self.calibration_scores(bundle=bundle)
        self.cli("derive", "--detector", "test.consensus-error@1", "--calibration-scores", str(scores), expect=2)
        self.plan("test.consensus-error@1", scores)
        self.assertIn("not committed", self.cli("derive", "--detector", "test.consensus-error@1",
                                                "--calibration-scores", str(scores), expect=2))
        self.fixture.commit_plans()
        derived = json.loads(self.cli("derive", "--detector", "test.consensus-error@1", "--calibration-scores",
                                      str(scores)))
        self.assertEqual((derived["status"], derived["strata"]), ("derived", "language"))
        # 30 families per language at alpha 0.05: the 30th order statistic, the largest clean error.
        self.assertEqual(derived["thresholds"], {language: 0.29 for language in LANGUAGES})
        plan_file = self.fixture.repo / "config/audio-qc-preregistrations/test.consensus-error@1.json"
        plan_file.write_text(plan_file.read_text(encoding="utf-8").replace("0.05", "0.06"), encoding="utf-8")
        self.cli("derive", "--detector", "test.consensus-error@1", "--calibration-scores", str(scores), expect=2)

    def test_plans_refuse_a_scored_confirmation_cohort_and_scores_refuse_before_the_plan(self) -> None:
        bundle = self.fixture.negative_bundle(self.fixture.calibration, "calibration/panel-bundle-v2")
        scores = self.calibration_scores(bundle=bundle)
        early = self.out / "early.json"
        self.cli("scores", "--detector", "test.consensus-error@1", "--role", "confirmation", "--cohort",
                 str(self.fixture.confirmation), "--bundle", str(bundle), "--output", str(early), expect=2)
        self.fixture.negative_bundle(self.fixture.confirmation, "confirmation/panel-bundle-v2")
        self.assertIn("already holds", self.plan("test.consensus-error@1", scores, expect=2))
        self.assertFalse((self.fixture.repo / "config/audio-qc-preregistrations").exists())

    def test_confirmation_runs_once_and_writes_a_valid_private_record(self) -> None:
        fixture = self.fixture
        scores = self.calibration_scores(bundle=fixture.negative_bundle(fixture.calibration, "cal-bundle"))
        self.plan("test.consensus-error@1", scores)
        # Once the plan exists, the confirmation cohort is never scored under another role.
        self.cli("scores", "--detector", "test.consensus-error@1", "--role", "informational", "--cohort",
                 str(fixture.confirmation), "--bundle", str(fixture.root / "cal-bundle"),
                 "--output", str(self.out / "x.json"), expect=2)
        fixture.commit_plans()
        injection = fixture.injection_set("CNT-DEL")
        confirmation = self.confirmation_scores(
            bundle=fixture.negative_bundle(fixture.confirmation, "confirmation/panel-bundle-v2"),
            injection_set=injection, positive_bundle=fixture.positive_bundle(injection))
        arguments = ("confirm", "--detector", "test.consensus-error@1", "--calibration-scores", str(scores),
                     "--confirmation-scores", str(confirmation))
        result = json.loads(self.cli(*arguments))
        self.assertEqual((result["verdict"], result["reasons"]), ("qualified", []))
        record_file = fixture.repo / result["record"]
        record = json.loads(record_file.read_text(encoding="utf-8"))
        self.assertEqual(calibration.record_errors(record), [])
        self.assertEqual((record["level"], record["speakers"]["count"]), ("warn", 3))
        self.assertEqual(record["threshold"]["values"], {language: 0.29 for language in LANGUAGES})
        self.assertEqual(record["rates"]["farPooled"]["events"], 0)
        self.assertEqual(record["rates"]["mechanisms"]["T1-pcm-construction"]["cells"]["CNT-DEL/severe"]["units"], 75)
        self.assertEqual([audit["judges"] for audit in record["phiAudit"]], [[WHISPER, PARAKEET]])
        self.assertEqual(record["split"]["counts"]["families"], {"calibration": 90, "confirmation": 90})
        self.assertIn("fleurs-no-speaker-ids", record["limitations"])
        ledger = fixture.repo / result["ledger"]
        self.assertEqual(json_digest(json.loads(ledger.read_text(encoding="utf-8"))), record["ledgerOutcomeSHA256"])
        # Confirmation runs once: a second attempt is refused and leaves both files as they were.
        before = (record_file.read_bytes(), ledger.read_bytes())
        self.assertIn("once", self.cli(*arguments, expect=2))
        self.assertEqual((record_file.read_bytes(), ledger.read_bytes()), before)
        # The contract gate validates the committed state and catches a tampered record.
        self.cli("validate")
        record["threshold"]["values"]["english"] = 0.5
        record_file.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.assertIn("ledger entry", self.cli("validate", expect=1))
        report = self.cli("report")
        self.assertIn("test.consensus-error@1", report)
        self.assertIn("qualified", report)

    def test_confirmation_does_not_start_without_enough_positives(self) -> None:
        fixture = self.fixture
        fixture.positives_per_language = 10
        scores = self.calibration_scores(bundle=fixture.negative_bundle(fixture.calibration, "cal-bundle"))
        self.plan("test.consensus-error@1", scores)
        fixture.commit_plans()
        injection = fixture.injection_set("CNT-DEL")
        confirmation = self.confirmation_scores(
            bundle=fixture.negative_bundle(fixture.confirmation, "confirmation/panel-bundle-v2"),
            injection_set=injection, positive_bundle=fixture.positive_bundle(injection))
        message = self.cli("confirm", "--detector", "test.consensus-error@1", "--calibration-scores", str(scores),
                           "--confirmation-scores", str(confirmation), expect=2)
        self.assertIn("30 positive families", message)
        self.assertEqual(list((fixture.repo / "config/audio-qc-preregistrations").glob("confirmation-*")), [])

    def test_a_pooled_signal_detector_reads_measurements(self) -> None:
        fixture = self.fixture
        scores = self.calibration_scores("test.level@1",
                                         measurements=fixture.measurements(fixture.calibration, "cal-measurements"))
        self.plan("test.level@1", scores)
        fixture.commit_plans()
        measured = fixture.measurements(fixture.confirmation, "confirmation/measurements", with_positives=True)
        confirmation = self.confirmation_scores("test.level@1", measurements=measured, positive_measurements=measured)
        result = json.loads(self.cli("confirm", "--detector", "test.level@1", "--calibration-scores", str(scores),
                                     "--confirmation-scores", str(confirmation)))
        record = json.loads((fixture.repo / result["record"]).read_text(encoding="utf-8"))
        self.assertEqual(result["verdict"], "qualified")
        self.assertEqual(record["threshold"]["strata"], "pooled")
        # Below: the 87th of 90 levels from the top (ceil(91 x 0.95)); the three at -22.9 alarm.
        self.assertEqual(record["threshold"]["values"], {"pooled": -22.8})
        self.assertEqual(record["threshold"]["ranks"], {"pooled": 87})
        self.assertEqual(record["phiAudit"], [])
        self.assertEqual(record["judges"][0]["judge"], "fastqc@8")

    def test_truncation_scores_come_from_private_transcripts(self) -> None:
        fixture = self.fixture
        rows = []
        for take in fixture.takes(fixture.calibration):
            reference = "one two three four five six seven eight nine ten"
            spoken = reference if int(take["takeID"].split("-")[2]) % 2 else "one two three four five six"
            rows.append((take["takeID"], take["language"],
                         {WHISPER: {"errorRate": 0.0}, PARAKEET: {"errorRate": 0.0}},
                         {"referenceText": reference, "transcripts": {WHISPER: spoken, PARAKEET: reference}}))
        bundle = fixture.bundle(fixture.root / "tail-bundle", rows)
        scores = json.loads(self.calibration_scores("test.truncation@1", bundle=bundle).read_text(encoding="utf-8"))
        self.assertEqual({unit["score"] for unit in scores["units"]}, {0.0})
        halves = [unit for unit in scores["units"] if unit["components"][f"{WHISPER}:transcript-tail:"
                                                                        "trailingUnmatchedFraction"] == 0.4]
        self.assertEqual(len(halves), 45)
        text = json.dumps(scores)
        self.assertNotIn("seven", text)
        self.assertNotIn(str(fixture.root), text)


class RecordPrivacyTests(unittest.TestCase):
    def record(self) -> dict:
        rate = {"events": 0, "units": 90, "rate": 0.0, "upper": 0.03, "lower": 0.0, "confidence": 0.95,
                "method": "clopper-pearson-one-sided"}
        return {
            "schema": calibration.RECORD_SCHEMA, "kind": calibration.RECORD_KIND, "detector": "test.level@1",
            "class": "A", "stage": 0, "direction": "below", "combination": "single",
            "judges": [{"judge": "fastqc@8", "outputIdentities": ["c" * 64]}], "operatingPoint": "warn",
            "verdict": "qualified", "level": "warn", "reasons": [], "planSHA256": "d" * 64,
            "detectorDefinitionSHA256": "e" * 64, "registries": {"policySHA256": "f" * 64},
            "cohorts": {"calibration": {"kind": "audio-qc-n2-cohort", "manifestDigest": "1" * 64,
                                        "scoresSHA256": "2" * 64},
                        "confirmation": {"kind": "audio-qc-n2-cohort", "manifestDigest": "3" * 64,
                                         "scoresSHA256": "4" * 64}},
            "split": {"method": "declared-cohorts", "disjointBy": ["family", "script"], "counts": {}},
            "speakers": {"unit": "language:fleurs-unidentified", "claim": "lower-bound", "count": 3},
            "threshold": {"strata": "pooled", "values": {"pooled": -22.9}, "ranks": {"pooled": 86},
                          "calibrationUnits": {"pooled": 90}, "alpha": 0.05, "rule": "split-conformal",
                          "unit": "source-family"},
            "counts": {}, "rates": {"farPooled": rate, "mechanisms": {}}, "phiAudit": [],
            "scope": scope(), "limitations": ["fleurs-no-speaker-ids"], "risks": [], "informational": None,
            "ledgerOutcomeSHA256": "5" * 64,
        }

    def test_a_record_carries_no_text_or_path(self) -> None:
        self.assertEqual(calibration.record_errors(self.record()), [])
        for mutation in (lambda record: record.update(informational={"note": "a spoken sentence here"}),
                         lambda record: record["counts"].update(text="hello"),
                         lambda record: record["counts"].update(transcript="x"),
                         lambda record: record.update(informational={"file": "/Users/example/take.wav"}),
                         lambda record: record["split"]["counts"].update(script=3)):
            record = self.record()
            mutation(record)
            self.assertTrue(calibration.record_errors(record), mutation)

    def test_a_record_is_consistent(self) -> None:
        for mutation in (lambda record: record.update(reasons=["far-pooled-not-met"]),
                         lambda record: record.update(verdict="refused"),
                         lambda record: record.update(planSHA256="short"),
                         lambda record: record["threshold"].update(values={"english": 1.0}),
                         lambda record: record["threshold"].update(values={"pooled": float("inf")}),
                         lambda record: record.update(combination="consensus-min"),
                         lambda record: record.pop("risks")):
            record = self.record()
            mutation(record)
            self.assertTrue(calibration.record_errors(record), mutation)


if __name__ == "__main__":
    unittest.main()
