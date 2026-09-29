#!/usr/bin/env python3
"""AQ-07 warn-level detector qualification: registry, cohort-split plans, derive and confirm-once."""

from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_calibration_set  # noqa: E402
import audio_qc_detector_calibration as calibration  # noqa: E402
from lib import language_metrics  # noqa: E402
from lib.jsonio import sha256_json  # noqa: E402
from lib.qc_pipeline import panel_metrics  # noqa: E402
from lib.qc_pipeline.evidence import PRIVATE_SCHEMA, TAKE_EVIDENCE_SCHEMA, write_private_bundle  # noqa: E402
from lib.qc_pipeline.layered_cache import metric_sources_digest  # noqa: E402
from lib.qc_pipeline.panel_jobs import profile  # noqa: E402
from lib.qc_pipeline.verdicts import channel_detectors, compose_take, stage0_detector  # noqa: E402
from lib.qc_qualification import detectors, injectors, thresholds  # noqa: E402
from lib.qc_qualification.pcm import SeededStream, json_digest  # noqa: E402
from lib.qc_qualification.stats import DEFAULT_CONFIDENCE  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
LANGUAGES = ("english", "french", "german")
OTHERS = tuple(language for language in language_metrics.PRODUCT_LANGUAGES if language not in LANGUAGES)
WHISPER, PARAKEET = "asr.whisper-large-v3@1", "asr.parakeet-tdt-0.6b-v3@1"
IDENTITY = {WHISPER: "a" * 64, PARAKEET: "b" * 64}
REFERENCE = "one two three four five six seven eight nine ten"
METRIC_VERSION = "normalization-v3-edit-rate-v4"
# Plans are committed at a fixed time; a confirmation panel starts after it unless a test says otherwise.
PLAN_DATE = "2026-09-01T00:00:00+0000"
FRESH = "2026-09-02T00:00:00.000000Z"
STALE = "2026-08-31T00:00:00.000000Z"
INJECTION_FLAGS = ("--injection-catalog-seed", "7", "--injection-sample-seed", "1",
                   "--injection-sample-per-cell", "150", "--injection-classes", "A,B,C,D,F")


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(*argv: str) -> tuple[int, str, str]:
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = calibration.main(list(argv))
    return code, out.getvalue(), err.getvalue()


def git(root: Path, *argv: str, date: str | None = None) -> None:
    environment = dict(os.environ)
    if date is not None:
        environment.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", *argv], check=True, stdout=subprocess.DEVNULL, env=environment)


def write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def scope(languages=LANGUAGES) -> dict:
    return {"languages": list(languages),
            "exclusions": [{"language": language, "reason": "not-in-fixture"}
                           for language in language_metrics.PRODUCT_LANGUAGES if language not in languages]}


def consensus_entry(detector: str = "test.consensus-error@1", *, source: str = "panel",
                    what: str = "errorRate", injectors_: tuple[str, ...] = ("CNT-DEL",), klass: str = "B") -> dict:
    key = "metric" if source == "panel" else "measure"
    return {
        "id": detector, "class": klass, "stage": 2, "measures": "The smaller of two families' scores.",
        "score": {"combination": "consensus-min", "unit": "error-rate", "groups": [
            {"languages": list(LANGUAGES), "components": [{"source": source, "judge": WHISPER, key: what},
                                                          {"source": source, "judge": PARAKEET, key: what}]}]},
        "direction": "above", "strata": {"by": "language", "reason": "Recognizers differ by language."},
        "scope": scope(),
        "targets": [{"injectorID": injector, "severities": ["severe"], "mechanism": "T1-pcm-construction"}
                    for injector in injectors_],
        "shams": [{"injectorID": injector, "mechanism": "T1-pcm-construction"} for injector in injectors_],
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
                                      what="trailingUnmatchedFraction", injectors_=("BND-TRUNC",), klass="C"),
                      consensus_entry("test.two-injectors@1", injectors_=("CNT-DEL", "CNT-INS"))],
    }


def signed(manifest: dict) -> dict:
    manifest["manifestDigest"] = sha256_json(manifest, ascii=False)
    return manifest


# What a panel run by the current code records: its orchestrator source and each judge's metric reduction.
ORCHESTRATOR = calibration.file_sha256(REPO / "scripts/audio_qc_orchestrator.py")


def judge_metrics(*judges: str) -> dict:
    return {judge: {"definition": panel_metrics.metric_definition(profile(judge).category),
                    "sourcesSHA256": metric_sources_digest(panel_metrics.metric_sources(profile(judge).category))}
            for judge in judges}


class Fixture:
    """A temporary repository and two synthetic FLEURS-like N2 cohorts (dev and test) with their N1 sources,
    panel bundles, injection sets and measurements, every one bound by the digests the driver checks."""

    def __init__(self, root: Path, *, per_language: int = 60, positives_per_language: int = 25) -> None:
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
        self.n1 = {"calibration": self.n1_manifest("calibration", "dev"),
                   "confirmation": self.n1_manifest("confirmation", "test")}
        self.calibration = self.cohort("calibration", "c")
        self.confirmation = self.cohort("confirmation", "t")

    # -- cohorts ---------------------------------------------------------------
    def n1_manifest(self, name: str, split: str) -> Path:
        return write_json(self.root / f"n1-{name}.json", signed({
            "kind": "audio-qc-n1-cohort", "schemaVersion": 1, "population": "N1", "split": name,
            "fleursSplit": split, "takes": []}))

    def cohort(self, name: str, tag: str) -> Path:
        takes = []
        for language in LANGUAGES:
            for index in range(self.per_language):
                take_id = f"{tag}-{language[:2]}-{index:03d}--n2"
                takes.append({"takeID": take_id, "family": f"{tag}-{language}-{index}", "language": language,
                              "scriptID": f"flores-{tag}{index % 12}", "eligible": True, "population": "N2",
                              "wavSHA256": sha(f"wav:{take_id}"), "textSHA256": sha(REFERENCE)})
        manifest = signed({"kind": "audio-qc-n2-cohort", "schemaVersion": 1, "runID": f"run-{name}",
                           "n1ManifestSHA256": calibration.file_sha256(self.n1[name]), "takes": takes})
        return write_json(self.root / name / "n2-manifest.json", manifest)

    @staticmethod
    def takes(cohort: Path) -> list[dict]:
        return json.loads(cohort.read_text(encoding="utf-8"))["takes"]

    @staticmethod
    def index(take_id: str) -> int:
        return int(take_id.split("-")[2])

    # -- panel bundles -----------------------------------------------------------
    def bundle(self, directory: Path, rows: list[tuple], **header) -> Path:
        """rows: (takeID, language, audio SHA-256, text SHA-256, {judge: metrics, None (out of scope) or
        'unavailable'}, private or None)."""
        (directory / "evidence").mkdir(parents=True)
        (directory / "private").mkdir()
        entries = []
        for number, (take_id, language, audio, text, metrics, private) in enumerate(rows, 1):
            measurements = []
            for judge, values in metrics.items():
                status = "out-of-scope" if values is None else "unavailable" if values == "unavailable" else "complete"
                measurements.append({"judge": judge, "status": status,
                                     "metrics": values if status == "complete" else {},
                                     "outputIdentity": IDENTITY[judge]})
            evidence = {"schema": "vocello.audioqc.take-evidence/1",
                        "take": {"takeID": take_id, "language": language, "audioSHA256": audio, "textSHA256": text},
                        "measurements": measurements}
            evidence_text = json.dumps(evidence)
            private_text = json.dumps({"takeID": take_id, **(private or {"referenceText": REFERENCE,
                                                                        "transcripts": {}})})
            (directory / "evidence" / f"{number:04d}.json").write_text(evidence_text, encoding="utf-8")
            (directory / "private" / f"{number:04d}.json").write_text(private_text, encoding="utf-8")
            entries.append({"takeID": take_id, "evidence": f"evidence/{number:04d}.json",
                            "evidenceSHA256": sha(evidence_text), "private": f"private/{number:04d}.json",
                            "privateSHA256": sha(private_text)})
        body = {"schema": calibration.BUNDLE_SCHEMA, "runID": directory.name, "manifestSHA256": sha("panel"),
                "orchestratorSHA256": ORCHESTRATOR, "judgeMetrics": judge_metrics(WHISPER, PARAKEET),
                "startedAt": FRESH, "cacheRootEmptyAtStart": True,
                "cache": {"L0": {"hits": 0, "misses": len(rows), "adopted": 0},
                          "L1": {"hits": 0, "misses": len(rows), "adopted": 0},
                          "L2": {"hits": 0, "misses": len(rows), "adopted": 0}},
                "takes": entries}
        body.update(header)
        write_json(directory / "bundle.json", {**body, "bundleDigest": sha256_json(body, ascii=False, allow_nan=False)})
        return directory

    @staticmethod
    def asr(value: float, version: str = METRIC_VERSION) -> dict:
        return {"errorRate": value, "accuracyMetricVersion": version}

    def negative_bundle(self, cohort: Path, name: str, *, scale: float = 100.0, drop: int = 0,
                        failed: int = 0, version: str = METRIC_VERSION, **header) -> Path:
        """Clean takes (the first `drop` missing, Whisper's rows of the next `failed` unavailable)."""
        rows = []
        for position, take in enumerate(self.takes(cohort)[drop:]):
            error = round(self.index(take["takeID"]) / scale, 4)
            whisper = "unavailable" if position < failed else self.asr(error, version)
            rows.append((take["takeID"], take["language"], take["wavSHA256"], take["textSHA256"],
                         {WHISPER: whisper, PARAKEET: self.asr(round(error + 0.05, 4), version)}, None))
        return self.bundle(self.root / name, rows, **header)

    def injection_set(self, injectors_: tuple[str, ...] = ("CNT-DEL",), *, name: str = "injection",
                      catalog_seed: int = 7, clean_shams: bool = False, shams_per_language: int | None = None,
                      sham_injectors: tuple[str, ...] | None = None, mechanism: str = "T1-pcm-construction",
                      entry_catalog_version: int = injectors.CATALOG_VERSION) -> Path:
        shams_per_language = self.positives_per_language if shams_per_language is None else shams_per_language
        sham_injectors = injectors_ if sham_injectors is None else sham_injectors
        entries = []
        for injector in injectors_:
            for take in self.takes(self.confirmation):
                index = self.index(take["takeID"])
                for severity, population in (("severe", "P1"), ("sham", "S")):
                    if population == "P1" and index >= self.positives_per_language:
                        continue
                    if population == "S" and (index >= shams_per_language or injector not in sham_injectors):
                        continue
                    clip = f"{take['takeID']}__{injector}__{severity}"
                    clean = population == "S" and clean_shams
                    source_pcm = sha(f"pcm:{take['takeID']}")
                    entries.append({
                        "takeID": clip, "sourceTakeID": take["takeID"], "family": take["family"],
                        "language": take["language"], "textSHA256": take["textSHA256"],
                        "wavSHA256": take["wavSHA256"] if clean else sha(f"wav:{clip}"),
                        "injection": {"injectorID": injector, "injector": f"{injector}@1", "variant": severity,
                                      "catalogVersion": entry_catalog_version,
                                      "severity": severity, "classes": ["B"], "mechanism": mechanism,
                                      "population": population, "sourcePCMSHA256": source_pcm,
                                      "outputPCMSHA256": source_pcm if clean else sha(f"pcm:{clip}")}})
        return write_json(self.root / name / "injection-set.json", {
            "kind": calibration.INJECTION_SET_KIND, "schemaVersion": 1,
            "sourceManifest": {"sha256": calibration.file_sha256(self.confirmation), "kind": "audio-qc-n2-cohort"},
            "catalogVersion": injectors.CATALOG_VERSION, "catalogSeed": catalog_seed,
            "classes": ["A", "B", "C", "D", "F"], "sampling": {"perCell": 150, "seed": 1},
            "entries": entries, "entriesSHA256": json_digest(entries)})

    @staticmethod
    def entries(injection_set: Path) -> list[dict]:
        return json.loads(injection_set.read_text(encoding="utf-8"))["entries"]

    def positive_bundle(self, injection_set: Path, *, detected: float = 0.9, parakeet: object = True,
                        name: str = "positive-bundle", **header) -> Path:
        rows = []
        for entry in self.entries(injection_set):
            positive = entry["injection"]["population"] == "P1"
            value = detected if positive else 0.0
            second = self.asr(value) if (parakeet is True or not positive) else parakeet
            rows.append((entry["takeID"], entry["language"], entry["wavSHA256"], entry["textSHA256"],
                         {WHISPER: self.asr(value), PARAKEET: second}, None))
        return self.bundle(self.root / name, rows, **header)

    # -- measurements (class A) --------------------------------------------------
    def measurements(self, cohort: Path, name: str, *, injection_set: Path | None = None) -> Path:
        clips = []
        # Confirmation levels are spread half as wide, so no clean take reaches the calibration tail.
        spread = 10.0 if cohort == self.calibration else 20.0
        for take in self.takes(cohort):
            index = self.index(take["takeID"])
            clips.append({"clipID": take["takeID"], "population": "N2", "family": take["family"],
                          "sourceTakeID": take["takeID"], "language": take["language"], "injection": None,
                          "wavSHA256": take["wavSHA256"],
                          "fastQC": {"rmsDBFS": round(-20.0 - index / spread, 4)}, "observations": {}})
        entries = self.entries(injection_set) if injection_set is not None else []
        for entry in entries:
            injection = entry["injection"]
            clips.append({"clipID": entry["takeID"], "population": injection["population"], "family": entry["family"],
                          "sourceTakeID": entry["sourceTakeID"], "language": entry["language"],
                          "wavSHA256": entry["wavSHA256"],
                          "injection": {key: injection[key] for key in ("injector", "injectorID", "variant",
                                                                         "severity", "classes", "outputPCMSHA256")},
                          "fastQC": {"rmsDBFS": -70.0 if injection["population"] == "P1" else -20.0},
                          "observations": {}})
        return write_json(self.root / f"{name}.json", {
            "kind": calibration.MEASUREMENTS_KIND, "schemaVersion": 1,
            "subject": {"detector": "fastqc@8", "mirror": "fastqc-v8-numpy/1"},
            "takesManifestSHA256": calibration.file_sha256(cohort),
            "entriesSHA256": json_digest(entries) if injection_set is not None else None,
            "clipsSHA256": json_digest(clips), "clips": clips})

    def commit_plans(self) -> None:
        git(self.repo, "add", "config/audio-qc-preregistrations")
        git(self.repo, "commit", "-q", "--no-verify", "-m", "plans", date=PLAN_DATE)


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

    def test_the_scoring_code_digest_covers_detectors_and_language_metrics(self) -> None:
        names = {path.name for path in detectors.scoring_sources()}
        self.assertLessEqual({"detectors.py", "language_metrics.py"}, names)
        self.assertEqual(detectors.scoring_code_sha256(), detectors.scoring_code_sha256())


def brute_force_tail(reference: list, hypothesis: list) -> tuple[int, int]:
    """(trailing unmatched, trailing deletions) by enumerating every alignment: the earliest last match of a
    minimum-cost alignment, and the most deletions after it."""
    ends: list[tuple[int, int, int]] = []

    def walk(row: int, column: int, cost: int, last: int, deleted: int) -> None:
        if row == len(reference) and column == len(hypothesis):
            ends.append((cost, last, deleted))
            return
        if row < len(reference) and column < len(hypothesis):
            if reference[row] == hypothesis[column]:
                walk(row + 1, column + 1, cost, row + 1, 0)
            else:
                walk(row + 1, column + 1, cost + 1, last, deleted)
        if row < len(reference):
            walk(row + 1, column, cost + 1, last, deleted + 1)
        if column < len(hypothesis):
            walk(row, column + 1, cost + 1, last, deleted)

    walk(0, 0, 0, 0, 0)
    best = min(cost for cost, _, _ in ends)
    anchors = [last for cost, last, _ in ends if cost == best and last > 0]
    anchor = min(anchors) if anchors else 0
    return len(reference) - anchor, max(deleted for cost, last, deleted in ends if cost == best and last == anchor)


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

    def test_a_truncation_whose_last_word_recurs_later_is_not_pinned_to_it(self) -> None:
        # Four words were cut; "the" recurs after the cut, where a match-first backtrace anchored it (1/9).
        english = self.tail("the cat sat on the mat by the door", "the cat sat on the")
        self.assertEqual((english["trailingUnmatched"], english["trailingDeletions"]), (4, 4))
        self.assertAlmostEqual(english["trailingUnmatchedFraction"], 4 / 9)
        # Eleven characters were cut; 去 recurs at the 14th, where the backtrace anchored it (2/16).
        chinese = self.tail("我们今天去公园散步明天还要去看戏", "我们今天去", "chinese")
        self.assertEqual((chinese["referenceUnits"], chinese["trailingUnmatched"]), (16, 11))
        self.assertAlmostEqual(chinese["trailingUnmatchedFraction"], 11 / 16)
        # One word heard: the take stopped after it, not at its later occurrence.
        self.assertEqual(self.tail("the cat sat on the", "the")["trailingUnmatched"], 4)

    def test_a_complete_take_scores_zero_even_when_its_last_word_recurs(self) -> None:
        complete = (("the cat sat on the mat by the door", "the cat sat on the mat by the door"),
                    ("the cat sat on the mat by the", "the cat sat on the mat by the"),
                    ("the cat sat on the mat by the", "the cat sat on mat by the"),
                    ("the cat sat on the mat by the", "a cat sat in the mat by the"),
                    ("我们今天去公园散步明天还要去", "我们今天去公园散步明天还要去"))
        for reference, hypothesis in complete:
            language = "chinese" if reference.startswith("我") else "english"
            scored = self.tail(reference, hypothesis, language)
            self.assertEqual((scored["trailingUnmatched"], scored["trailingUnmatchedFraction"]), (0, 0.0), hypothesis)

    def test_the_anchor_is_the_earliest_of_every_optimal_alignment(self) -> None:
        # An optimal alignment without a match has no last match: where one ties with a matching one, the
        # match anchors (the transcript reached the reference's last unit).
        self.assertEqual(detectors.trailing_unmatched(["a", "b"], ["b", "c"])["trailingUnmatched"], 0)
        # Tie-order independent: equal to enumerating every alignment, on small alphabets where ties abound.
        generator = random.Random(20260929)
        for trial in range(1500):
            reference = [generator.randrange(3) for _ in range(generator.randrange(0, 7))]
            hypothesis = [generator.randrange(3) for _ in range(generator.randrange(0, 6))]
            scored = detectors.trailing_unmatched(reference, hypothesis)
            self.assertEqual((scored["trailingUnmatched"], scored["trailingDeletions"]),
                             brute_force_tail(reference, hypothesis), (trial, reference, hypothesis))

    def test_the_totals_are_edit_metrics_alignment(self) -> None:
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

    def test_each_sham_cell_is_tested_alone_with_a_minimum(self) -> None:
        plan = self.plan()
        warn = json.loads((REPO / calibration.POLICY).read_text(encoding="utf-8"))["operatingPoints"]["warn"]

        def units(prefix: str, count: int, *, alarm: bool = False) -> list:
            return [thresholds.ScoredUnit(f"{prefix}{index}", LANGUAGES[index % 3], f"{LANGUAGES[index % 3]}:x",
                                          f"s{index % 5}", alarm) for index in range(count)]
        cohort = dict(operating_point=warn, confidence=DEFAULT_CONFIDENCE, n2_negatives=units("n", 90),
                      positives={"T1-pcm-construction": {"CNT-DEL/severe": units("d", 70, alarm=True),
                                                         "CNT-INS/severe": units("i", 70, alarm=True)}})
        # Per mechanism (the default), one injector's sham covered the other's.
        self.assertEqual(thresholds.evaluate_confirmation(
            plan, 0.5, shams={"T1-pcm-construction": units("s", 70)}, **cohort)["status"], "qualified")
        per_injector = thresholds.evaluate_confirmation(
            plan, 0.5, shams={"CNT-DEL": units("s", 70)}, sham_cells=["CNT-DEL", "CNT-INS"], sham_minimum=60,
            sham_informative={"CNT-DEL": True, "CNT-INS": True}, **cohort)
        self.assertIn("sham-missing:CNT-INS", per_injector["reasons"])
        few = thresholds.evaluate_confirmation(
            plan, 0.5, shams={"CNT-DEL": units("s", 70), "CNT-INS": units("t", 20)},
            sham_cells=["CNT-DEL", "CNT-INS"], sham_minimum=60, **cohort)
        self.assertEqual(few["reasons"], ["sham-too-few:CNT-INS"])
        marked = thresholds.evaluate_confirmation(
            plan, 0.5, shams={"CNT-DEL": units("s", 70), "CNT-INS": units("t", 70)},
            sham_cells=["CNT-DEL", "CNT-INS"], sham_minimum=60,
            sham_informative={"CNT-DEL": False, "CNT-INS": True}, **cohort)
        self.assertEqual((marked["status"], marked["shams"]["CNT-DEL"]["informative"],
                          marked["shams"]["CNT-INS"]["minimumUnits"]), ("qualified", False, 60))


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

    def scores(self, detector: str, role: str, cohort: Path, *, n1: Path | None, name: str | None = None,
               expect: int = 0, **sources: Path) -> Path | str:
        output = self.out / f"{name or detector}-{role}.json"
        arguments = ["scores", "--detector", detector, "--role", role, "--cohort", str(cohort), "--output", str(output)]
        if n1 is not None:
            arguments += ["--n1-manifest", str(n1)]
        for key, value in sources.items():
            arguments += [f"--{key.replace('_', '-')}", str(value)]
        text = self.cli(*arguments, expect=expect)
        return output if expect == 0 else text

    def calibration_scores(self, detector: str = "test.consensus-error@1", **sources: Path) -> Path:
        return self.scores(detector, "calibration", self.fixture.calibration, n1=self.fixture.n1["calibration"],
                           **sources)

    def confirmation_scores(self, detector: str = "test.consensus-error@1", *, expect: int = 0,
                            **sources: Path) -> Path | str:
        return self.scores(detector, "confirmation", self.fixture.confirmation,
                           n1=self.fixture.n1["confirmation"], expect=expect, **sources)

    def plan(self, detector: str, scores: Path, *, expect: int = 0, flags: tuple[str, ...] = INJECTION_FLAGS) -> str:
        return self.cli("plan", "--detector", detector, "--calibration-cohort", str(self.fixture.calibration),
                        "--confirmation-cohort", str(self.fixture.confirmation),
                        "--confirmation-n1-manifest", str(self.fixture.n1["confirmation"]),
                        "--calibration-scores", str(scores), "--alpha", "0.05", *flags, expect=expect)

    def confirm(self, detector: str, calibration_scores: Path, confirmation_scores: Path, *extra: str,
                expect: int = 0) -> str:
        return self.cli("confirm", "--detector", detector, "--calibration-scores", str(calibration_scores),
                        "--confirmation-scores", str(confirmation_scores), *extra, expect=expect)

    def planned(self, detector: str = "test.consensus-error@1") -> Path:
        """Calibration scores and a committed plan for a consensus detector."""
        scores = self.calibration_scores(detector, bundle=self.fixture.negative_bundle(self.fixture.calibration,
                                                                                      f"cal-bundle-{detector}"))
        self.plan(detector, scores)
        self.fixture.commit_plans()
        return scores

    def no_ledger(self) -> None:
        directory = self.fixture.repo / "config/audio-qc-preregistrations"
        self.assertEqual(list(directory.glob("confirmation-*")), [])
        self.assertFalse((self.fixture.repo / calibration.RECORDS).exists())

    def document(self, detector: str, *, bundle: Path, injection: Path, positives: Path) -> Path:
        """Confirmation scores built directly (bypassing the scores command's own checks), for confirm to judge."""
        repository = calibration.Repository(self.fixture.repo)
        _, entry = repository.entry(detector)
        cohort = calibration.load_cohort(self.fixture.confirmation)
        document = calibration.build_scores(
            entry, cohort, role="confirmation", split="test", bundle=calibration.Bundle(bundle),
            injection_set=calibration.load_injection_set(injection), positive_bundle=calibration.Bundle(positives))
        return write_json(self.out / f"direct-{detector}.json", document)

    # -- the whole flow ------------------------------------------------------------
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
        self.assertEqual((derived["status"], derived["strata"], derived["calibrationFloor"]),
                         ("derived", "language", 60))
        # 60 families per language at alpha 0.05: the 58th order statistic (ceil(61 x 0.95)).
        self.assertEqual(derived["thresholds"], {language: 0.57 for language in LANGUAGES})
        plan_file = self.fixture.repo / "config/audio-qc-preregistrations/test.consensus-error@1.json"
        plan_file.write_text(plan_file.read_text(encoding="utf-8").replace("0.05", "0.06"), encoding="utf-8")
        self.cli("derive", "--detector", "test.consensus-error@1", "--calibration-scores", str(scores), expect=2)

    def test_plans_refuse_a_scored_confirmation_cohort_and_scores_refuse_before_the_plan(self) -> None:
        bundle = self.fixture.negative_bundle(self.fixture.calibration, "calibration/panel-bundle-v2")
        scores = self.calibration_scores(bundle=bundle)
        self.confirmation_scores(bundle=bundle, expect=2)
        self.fixture.negative_bundle(self.fixture.confirmation, "confirmation/panel-bundle-v2")
        self.assertIn("already holds", self.plan("test.consensus-error@1", scores, expect=2))
        self.assertFalse((self.fixture.repo / "config/audio-qc-preregistrations").exists())

    def test_confirmation_runs_once_and_writes_a_valid_private_record(self) -> None:
        fixture = self.fixture
        scores = self.calibration_scores(bundle=fixture.negative_bundle(fixture.calibration, "cal-bundle"))
        self.plan("test.consensus-error@1", scores)
        plan_file = fixture.repo / "config/audio-qc-preregistrations/test.consensus-error@1.json"
        bindings = json.loads(plan_file.read_text(encoding="utf-8"))["bindings"]
        self.assertEqual({key: bindings[key] for key in calibration.INJECTION_BINDINGS.values()},
                         {"injectorCatalogVersion": str(injectors.CATALOG_VERSION), "injectionCatalogSeed": "7",
                          "injectionSampleSeed": "1", "injectionSamplePerCell": "150",
                          "injectionClasses": "A,B,C,D,F"})
        self.assertEqual(bindings["scoringCodeSHA256"], detectors.scoring_code_sha256())
        fixture.commit_plans()
        injection = fixture.injection_set()
        confirmation = self.confirmation_scores(
            bundle=fixture.negative_bundle(fixture.confirmation, "confirmation/panel-bundle-v2", scale=200.0),
            injection_set=injection, positive_bundle=fixture.positive_bundle(injection))
        arguments = ("test.consensus-error@1", scores, confirmation)
        result = json.loads(self.confirm(*arguments))
        self.assertEqual((result["verdict"], result["reasons"]), ("qualified", []))
        record_file = fixture.repo / result["record"]
        record = json.loads(record_file.read_text(encoding="utf-8"))
        self.assertEqual(calibration.record_errors(record), [])
        self.assertEqual((record["level"], record["speakers"]["count"]), ("warn", 3))
        self.assertEqual(record["threshold"]["values"], {language: 0.57 for language in LANGUAGES})
        self.assertEqual(record["rates"]["farPooled"]["events"], 0)
        self.assertEqual(record["rates"]["mechanisms"]["T1-pcm-construction"]["cells"]["CNT-DEL/severe"]["units"], 75)
        sham = record["rates"]["shams"]["CNT-DEL"]
        self.assertEqual((sham["units"], sham["informative"]), (75, True))
        self.assertEqual(record["a4"], {"unit": "injector", "cells": ["CNT-DEL"], "uninformative": {}})
        self.assertEqual(record["evidence"]["metricVersions"], {judge: {"accuracyMetricVersion": [METRIC_VERSION]}
                                                                for judge in (PARAKEET, WHISPER)})
        self.assertEqual(record["evidence"]["planCommittedAt"], "2026-09-01T00:00:00Z")
        self.assertEqual([panel["startedAt"] for panel in record["evidence"]["confirmationPanels"]], [FRESH, FRESH])
        self.assertEqual([audit["judges"] for audit in record["phiAudit"]], [[WHISPER, PARAKEET]])
        self.assertEqual(record["split"]["counts"]["families"], {"calibration": 180, "confirmation": 180})
        self.assertIn("fleurs-no-speaker-ids", record["limitations"])
        ledger = fixture.repo / result["ledger"]
        self.assertEqual(json_digest(json.loads(ledger.read_text(encoding="utf-8"))), record["ledgerOutcomeSHA256"])
        # Confirmation runs once: a second attempt is refused and leaves both files as they were.
        before = (record_file.read_bytes(), ledger.read_bytes())
        self.assertIn("once", self.confirm(*arguments, expect=2))
        self.assertEqual((record_file.read_bytes(), ledger.read_bytes()), before)
        # The contract gate validates the committed state and catches a tampered record.
        self.cli("validate")
        tampered = copy.deepcopy(record)
        tampered["threshold"]["values"]["english"] = 0.5
        record_file.write_text(json.dumps(tampered, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self.assertIn("ledger entry", self.cli("validate", expect=1))
        record_file.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report = self.cli("report")
        self.assertIn("test.consensus-error@1", report)
        self.assertIn("qualified", report)
        # An in-place registry edit after the record (no version bump) fails the gate, for the plan and the record.
        registry = json.loads((fixture.repo / calibration.REGISTRY).read_text(encoding="utf-8"))
        registry["detectors"][0]["measures"] = "The smaller of two families' error rates."
        (fixture.repo / calibration.REGISTRY).write_text(json.dumps(registry, indent=2), encoding="utf-8")
        edited = self.cli("validate", expect=1)
        self.assertIn("changed after it was confirmed", edited)
        self.assertIn("changed after its plan", edited)

    def test_a_pooled_signal_detector_reads_measurements(self) -> None:
        fixture = self.fixture
        scores = self.calibration_scores("test.level@1",
                                         measurements=fixture.measurements(fixture.calibration, "cal-measurements"))
        self.plan("test.level@1", scores)
        fixture.commit_plans()
        injection = fixture.injection_set(("SIG-LEVEL",))
        measured = fixture.measurements(fixture.confirmation, "confirmation/measurements", injection_set=injection)
        confirmation = self.confirmation_scores("test.level@1", measurements=measured, injection_set=injection,
                                                positive_measurements=measured)
        result = json.loads(self.confirm("test.level@1", scores, confirmation))
        record = json.loads((fixture.repo / result["record"]).read_text(encoding="utf-8"))
        self.assertEqual(result["verdict"], "qualified")
        self.assertEqual(record["threshold"]["strata"], "pooled")
        # Below: the 172nd of 180 levels from the top (ceil(181 x 0.95)), three levels per step of 0.1 dB.
        self.assertEqual(record["threshold"]["values"], {"pooled": -25.7})
        self.assertEqual(record["threshold"]["ranks"], {"pooled": 172})
        self.assertEqual(record["phiAudit"], [])
        self.assertEqual(record["judges"][0]["judge"], "fastqc@8")
        self.assertEqual(record["evidence"]["confirmationPanels"], [])

    def test_truncation_scores_come_from_private_transcripts(self) -> None:
        fixture = self.fixture
        rows = []
        for take in fixture.takes(fixture.calibration):
            spoken = REFERENCE if fixture.index(take["takeID"]) % 2 else "one two three four five six"
            rows.append((take["takeID"], take["language"], take["wavSHA256"], take["textSHA256"],
                         {WHISPER: fixture.asr(0.0), PARAKEET: fixture.asr(0.0)},
                         {"referenceText": REFERENCE, "transcripts": {WHISPER: spoken, PARAKEET: REFERENCE}}))
        bundle = fixture.bundle(fixture.root / "tail-bundle", rows)
        scores = json.loads(self.calibration_scores("test.truncation@1", bundle=bundle).read_text(encoding="utf-8"))
        self.assertEqual({unit["score"] for unit in scores["units"]}, {0.0})
        halves = [unit for unit in scores["units"] if unit["components"][f"{WHISPER}:transcript-tail:"
                                                                        "trailingUnmatchedFraction"] == 0.4]
        self.assertEqual(len(halves), 90)
        text = json.dumps(scores)
        self.assertNotIn("seven", text)
        self.assertNotIn(str(fixture.root), text)
        # A private reference text that is not the manifest's is refused.
        rows[0] = (*rows[0][:5], {"referenceText": "another text", "transcripts": {}})
        wrong = fixture.bundle(fixture.root / "tail-bundle-wrong", rows)
        self.assertIn("private reference text", self.scores("test.truncation@1", "calibration", fixture.calibration,
                                                            n1=fixture.n1["calibration"], bundle=wrong, expect=2))

    # -- defect 2: evidence bound to the cohort and the injection set ---------------------
    def test_scores_refuse_evidence_not_bound_to_the_cohort(self) -> None:
        fixture = self.fixture

        def refused(**sources: Path) -> str:
            return self.scores("test.consensus-error@1", "calibration", fixture.calibration,
                               n1=fixture.n1["calibration"], expect=2, **sources)
        bundle = fixture.negative_bundle(fixture.calibration, "bound-bundle")
        manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
        manifest["runID"] = "edited"
        (bundle / "bundle.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.assertIn("bundleDigest", refused(bundle=bundle))
        # Evidence measured on other audio (a bundle of the confirmation cohort's takes under these ids).
        rows = [(take["takeID"], take["language"], sha("other audio"), take["textSHA256"],
                 {WHISPER: fixture.asr(0.1), PARAKEET: fixture.asr(0.1)}, None)
                for take in fixture.takes(fixture.calibration)]
        self.assertIn("other audio", refused(bundle=fixture.bundle(fixture.root / "other-audio", rows)))
        # A manifest edited after it was written.
        edited = json.loads(fixture.calibration.read_text(encoding="utf-8"))
        edited["takes"][0]["wavSHA256"] = sha("swapped")
        copied = write_json(fixture.root / "edited" / "n2-manifest.json", edited)
        self.assertIn("manifestDigest", self.scores("test.consensus-error@1", "calibration", copied,
                                                    n1=fixture.n1["calibration"], expect=2,
                                                    bundle=fixture.negative_bundle(fixture.calibration, "b2")))

    def test_measurements_are_bound_to_their_takes_manifest_injection_set_and_clips(self) -> None:
        fixture = self.fixture

        def refused(measurements: Path) -> str:
            return self.scores("test.level@1", "calibration", fixture.calibration, n1=fixture.n1["calibration"],
                               expect=2, measurements=measurements)
        other = fixture.measurements(fixture.confirmation, "other-cohort")
        self.assertIn("another takes manifest", refused(other))
        good = fixture.measurements(fixture.calibration, "calibration-measurements")
        data = json.loads(good.read_text(encoding="utf-8"))
        data["clips"][0]["fastQC"]["rmsDBFS"] = -99.0
        self.assertIn("clipsSHA256", refused(write_json(fixture.root / "edited-clips.json", data)))
        data = json.loads(good.read_text(encoding="utf-8"))
        data["clips"][0]["wavSHA256"] = sha("other")
        data["clipsSHA256"] = json_digest(data["clips"])
        self.assertIn("other audio", refused(write_json(fixture.root / "other-audio.json", data)))

    def test_injection_sets_are_bound_to_their_entries_and_the_cohort(self) -> None:
        fixture = self.fixture
        scores = self.calibration_scores("test.level@1",
                                         measurements=fixture.measurements(fixture.calibration, "cal-measurements"))
        self.plan("test.level@1", scores)
        fixture.commit_plans()
        injection = fixture.injection_set(("SIG-LEVEL",))
        measured = fixture.measurements(fixture.confirmation, "confirmation/measurements", injection_set=injection)

        def refused(injection_set: Path, positive: Path = measured) -> str:
            return self.confirmation_scores("test.level@1", expect=2, measurements=measured,
                                            injection_set=injection_set, positive_measurements=positive)
        data = json.loads(injection.read_text(encoding="utf-8"))
        data["entries"] = data["entries"][:-1]
        self.assertIn("entriesSHA256", refused(write_json(fixture.root / "trimmed/injection-set.json", data)))
        data = json.loads(injection.read_text(encoding="utf-8"))
        data.pop("sourceManifest")
        self.assertIn("no source manifest", refused(write_json(fixture.root / "unsourced/injection-set.json", data)))
        data = json.loads(injection.read_text(encoding="utf-8"))
        data["sourceManifest"]["sha256"] = calibration.file_sha256(fixture.calibration)
        self.assertIn("another cohort manifest", refused(write_json(fixture.root / "moved/injection-set.json", data)))
        # Positive measurements of another injection set, and positives without any set.
        other = fixture.injection_set(("SIG-LEVEL",), name="other-set", shams_per_language=24)
        other_measured = fixture.measurements(fixture.confirmation, "other-measured", injection_set=other)
        self.assertIn("did not score this injection set", refused(injection, other_measured))
        self.assertIn("pass --injection-set", self.confirmation_scores("test.level@1", expect=2, measurements=measured,
                                                                        positive_measurements=measured))

    def test_confirm_refuses_units_without_evidence_and_nearly_all_abstaining_detectors(self) -> None:
        fixture = self.fixture
        scores = self.planned()
        injection = fixture.injection_set()
        # Five cohort takes missing from the confirmation panel: those units have no evidence.
        missing = self.confirmation_scores(
            bundle=fixture.negative_bundle(fixture.confirmation, "confirmation/panel-bundle-v2", scale=200.0, drop=5),
            injection_set=injection, positive_bundle=fixture.positive_bundle(injection))
        self.assertIn("have no evidence", self.confirm("test.consensus-error@1", scores, missing, expect=2))
        self.no_ledger()
        # Parakeet's rows failed on every positive: the run failed, so confirmation never starts.
        abstaining = self.scores(
            "test.consensus-error@1", "confirmation", fixture.confirmation, n1=fixture.n1["confirmation"],
            name="abstaining",
            bundle=fixture.negative_bundle(fixture.confirmation, "confirmation-2/panel-bundle", scale=200.0),
            injection_set=injection, positive_bundle=fixture.positive_bundle(injection, parakeet="unavailable",
                                                                             name="abstaining-positives"))
        message = self.confirm("test.consensus-error@1", scores, abstaining, expect=2)
        self.assertIn("75 in-scope units have a failed judge row", message)
        self.assertIn("0 scored positive families", message)
        # Five failed rows among the negatives (an admission timeout): the floors still hold, but the run
        # failed, and its units would count as clean abstentions in a permanent refusal.
        failed = self.scores(
            "test.consensus-error@1", "confirmation", fixture.confirmation, n1=fixture.n1["confirmation"],
            name="failed", injection_set=injection, positive_bundle=fixture.positive_bundle(injection, name="p3"),
            bundle=fixture.negative_bundle(fixture.confirmation, "confirmation-3/panel-bundle", scale=200.0, failed=5))
        message = self.confirm("test.consensus-error@1", scores, failed, expect=2)
        self.assertIn("5 in-scope units have a failed judge row", message)
        self.assertNotIn("floor", message)
        self.no_ledger()

    # -- plans bind calibration evidence a confirmation panel can still match -------------
    def test_plans_refuse_calibration_evidence_the_current_code_would_not_produce(self) -> None:
        fixture = self.fixture
        stale = judge_metrics(WHISPER, PARAKEET)
        stale[PARAKEET] = {**stale[PARAKEET], "sourcesSHA256": sha("older panel_metrics.py")}
        for name, header, version, expected in (
                ("orchestrator", {"orchestratorSHA256": sha("older orchestrator")}, METRIC_VERSION,
                 "another orchestrator"),
                ("reduction", {"judgeMetrics": stale}, METRIC_VERSION, f"{PARAKEET}: the calibration panel reduced"),
                ("version", {}, "normalization-v2-edit-rate-v3", "accuracyMetricVersion")):
            scores = self.scores("test.consensus-error@1", "calibration", fixture.calibration,
                                 n1=fixture.n1["calibration"], name=name,
                                 bundle=fixture.negative_bundle(fixture.calibration, f"cal-{name}", version=version,
                                                                **header))
            self.assertIn(expected, self.plan("test.consensus-error@1", scores, expect=2), name)
        self.assertFalse((fixture.repo / "config/audio-qc-preregistrations").exists())

    def test_confirmation_does_not_start_without_enough_positives(self) -> None:
        fixture = self.fixture
        scores = self.planned()
        fixture.positives_per_language = 10
        injection = fixture.injection_set()
        confirmation = self.confirmation_scores(
            bundle=fixture.negative_bundle(fixture.confirmation, "confirmation/panel-bundle-v2", scale=200.0),
            injection_set=injection, positive_bundle=fixture.positive_bundle(injection))
        message = self.confirm("test.consensus-error@1", scores, confirmation, expect=2)
        self.assertIn("30 scored positive families", message)
        self.no_ledger()

    # -- defect 3: A7 beyond the judges' output identities --------------------------------
    def test_confirm_refuses_other_evidence_or_scoring_code_than_the_plan(self) -> None:
        fixture = self.fixture
        scores = self.planned()
        injection = fixture.injection_set()
        reduced = judge_metrics(WHISPER, PARAKEET)
        reduced[WHISPER] = {**reduced[WHISPER], "sourcesSHA256": sha("edited panel_metrics.py")}
        for name, header, version in (("orchestrator", {"orchestratorSHA256": sha("orchestrator-v2")}, METRIC_VERSION),
                                      ("reduction", {"judgeMetrics": reduced}, METRIC_VERSION),
                                      ("metric", {}, "normalization-v2-edit-rate-v3")):
            confirmation = self.scores(
                "test.consensus-error@1", "confirmation", fixture.confirmation, n1=fixture.n1["confirmation"],
                name=name, injection_set=injection,
                bundle=fixture.negative_bundle(fixture.confirmation, f"{name}/panel-bundle", scale=200.0,
                                               version=version, **header),
                positive_bundle=fixture.positive_bundle(injection, name=f"{name}-positives", **header))
            self.assertIn("A7", self.confirm("test.consensus-error@1", scores, confirmation, expect=2), name)
        confirmation = self.confirmation_scores(
            bundle=fixture.negative_bundle(fixture.confirmation, "confirmation/panel-bundle-v2", scale=200.0),
            injection_set=injection, positive_bundle=fixture.positive_bundle(injection))
        with mock.patch.object(calibration.registry_lib, "scoring_code_sha256", return_value="f" * 64):
            self.assertIn("scoring code", self.confirm("test.consensus-error@1", scores, confirmation, expect=2))
        self.no_ledger()

    # -- defect 4: a sham cell per injector, with a floor ---------------------------------
    def test_every_injector_needs_its_own_sham_cell_with_enough_families(self) -> None:
        fixture = self.fixture
        scores = self.planned("test.two-injectors@1")
        negatives = fixture.negative_bundle(fixture.confirmation, "confirmation/panel-bundle-v2", scale=200.0)
        # CNT-INS has positives but no shams; before, CNT-DEL's shams stood in for the whole mechanism.
        injection = fixture.injection_set(("CNT-DEL", "CNT-INS"), sham_injectors=("CNT-DEL",))
        confirmation = self.confirmation_scores("test.two-injectors@1", bundle=negatives, injection_set=injection,
                                                positive_bundle=fixture.positive_bundle(injection))
        self.assertIn("CNT-INS: 0 scored sham families",
                      self.confirm("test.two-injectors@1", scores, confirmation, expect=2))
        # Shams present for both, but 30 families each: below the positive floor.
        injection = fixture.injection_set(("CNT-DEL", "CNT-INS"), name="few-shams", shams_per_language=10)
        confirmation = self.scores("test.two-injectors@1", "confirmation", fixture.confirmation,
                                   n1=fixture.n1["confirmation"], name="few", bundle=negatives,
                                   injection_set=injection,
                                   positive_bundle=fixture.positive_bundle(injection, name="few-positives"))
        message = self.confirm("test.two-injectors@1", scores, confirmation, expect=2)
        self.assertIn("CNT-DEL: 30 scored sham families", message)
        self.assertIn("CNT-INS: 30 scored sham families", message)
        self.no_ledger()

    def test_a_sham_of_clean_cohort_audio_is_recorded_as_uninformative(self) -> None:
        fixture = self.fixture
        scores = self.planned()
        injection = fixture.injection_set(clean_shams=True)
        confirmation = self.confirmation_scores(
            bundle=fixture.negative_bundle(fixture.confirmation, "confirmation/panel-bundle-v2", scale=200.0),
            injection_set=injection, positive_bundle=fixture.positive_bundle(injection))
        result = json.loads(self.confirm("test.consensus-error@1", scores, confirmation))
        record = json.loads((fixture.repo / result["record"]).read_text(encoding="utf-8"))
        self.assertEqual(record["a4"]["uninformative"], {"CNT-DEL": calibration.UNINFORMATIVE_SHAM})
        self.assertIs(record["rates"]["shams"]["CNT-DEL"]["informative"], False)
        self.assertIn("(uninformative)", self.cli("report"))

    # -- defect 5: A5 enforced --------------------------------------------------------------
    def test_the_confirmation_corpus_is_never_scored_for_calibration_or_information(self) -> None:
        fixture = self.fixture
        bundle = fixture.negative_bundle(fixture.confirmation, "confirmation-bundle")
        for role in ("calibration", "informational"):
            self.assertIn("FLEURS test", self.scores("test.consensus-error@1", role, fixture.confirmation,
                                                     n1=fixture.n1["confirmation"], bundle=bundle, expect=2))
        self.assertIn("pass the N1 manifest", self.scores("test.consensus-error@1", "informational",
                                                          fixture.confirmation, n1=None, bundle=bundle, expect=2))
        self.assertIn("is not the N1 manifest", self.scores("test.consensus-error@1", "informational",
                                                            fixture.confirmation, n1=fixture.n1["calibration"],
                                                            bundle=bundle, expect=2))
        # Any cohort a committed plan names as confirmation, whatever its corpus.
        repository = calibration.Repository(fixture.repo)
        cohort = calibration.load_cohort(fixture.calibration)
        other = thresholds.PreRegistration(
            detector="test.level@1", rule="split-conformal", alpha=0.05, direction="below",
            cohorts=thresholds.CohortSplit(
                calibration=thresholds.CohortReference("audio-qc-n2-cohort", "1" * 64, "fleurs-dev"),
                confirmation=thresholds.CohortReference("audio-qc-n2-cohort", cohort["manifestDigest"], "x"),
                disjoint_by=("family", "script"), speaker_unit="u", speaker_claim="lower-bound",
                limitations=(("l", "A limitation."),)))
        repository.store.commit(other)
        message = self.scores("test.consensus-error@1", "calibration", fixture.calibration,
                              n1=fixture.n1["calibration"],
                              bundle=fixture.negative_bundle(fixture.calibration, "cal-bundle"), expect=2)
        self.assertIn("the plan of test.level@1 names this cohort as its confirmation cohort", message)

    def test_confirm_refuses_an_injection_set_built_otherwise_than_planned(self) -> None:
        fixture = self.fixture
        scores = self.planned()
        injection = fixture.injection_set(catalog_seed=8)
        negatives = fixture.negative_bundle(fixture.confirmation, "confirmation/panel-bundle-v2", scale=200.0)
        positives = fixture.positive_bundle(injection)
        self.assertIn("catalogSeed is 8, the plan declares 7",
                      self.confirmation_scores(bundle=negatives, injection_set=injection, positive_bundle=positives,
                                               expect=2))
        direct = self.document("test.consensus-error@1", bundle=negatives, injection=injection, positives=positives)
        self.assertIn("catalogSeed is 8", self.confirm("test.consensus-error@1", scores, direct, expect=2))
        # A header that names the planned catalog over entries built with another one.
        older = fixture.injection_set(name="older-catalog", entry_catalog_version=injectors.CATALOG_VERSION - 1)
        self.assertIn("entries carry catalog versions", self.confirmation_scores(
            bundle=negatives, injection_set=older, expect=2,
            positive_bundle=fixture.positive_bundle(older, name="older-positives")))
        self.no_ledger()

    def test_confirmation_panels_are_computed_from_scratch_after_the_plan(self) -> None:
        fixture = self.fixture
        scores = self.planned()
        injection = fixture.injection_set()
        for name, header, expected in (
                ("stale", {"startedAt": STALE}, "started before its plan was committed"),
                ("unstamped", {"startedAt": None}, "records no start time"),
                ("shared", {"cacheRootEmptyAtStart": False}, "empty cache root"),
                ("reused", {"cache": {"L1": {"hits": 3, "misses": 0, "adopted": 0},
                                      "L2": {"hits": 0, "misses": 0, "adopted": 0}}}, "reused 3 L1 entries"),
                ("adopted", {"cache": {"L1": {"hits": 0, "misses": 0, "adopted": 2}}}, "adopted 2 entries")):
            negatives = fixture.negative_bundle(fixture.confirmation, f"{name}/panel-bundle", scale=200.0, **header)
            positives = fixture.positive_bundle(injection, name=f"{name}-positives")
            self.assertIn(expected, self.confirmation_scores(bundle=negatives, injection_set=injection,
                                                             positive_bundle=positives, expect=2), name)
            direct = self.document("test.consensus-error@1", bundle=negatives, injection=injection,
                                   positives=positives)
            self.assertIn(expected, self.confirm("test.consensus-error@1", scores, direct, expect=2), name)
        self.no_ledger()

    # -- defect 6: --n3-scores checked --------------------------------------------------------
    def test_n3_scores_must_be_this_detectors_informational_scores(self) -> None:
        fixture = self.fixture
        scores = self.planned()
        injection = fixture.injection_set()
        confirmation = self.confirmation_scores(
            bundle=fixture.negative_bundle(fixture.confirmation, "confirmation/panel-bundle-v2", scale=200.0),
            injection_set=injection, positive_bundle=fixture.positive_bundle(injection))
        message = self.confirm("test.consensus-error@1", scores, confirmation, "--n3-scores", str(scores), expect=2)
        self.assertIn("informational scores", message)
        self.assertIn("not N3", message)
        self.no_ledger()

    # -- defect 8 and the write-once store ------------------------------------------------------
    def test_validate_catches_rewritten_plans_and_orphan_ledger_entries(self) -> None:
        fixture = self.fixture
        self.planned()
        self.cli("validate")
        plan_file = fixture.repo / "config/audio-qc-preregistrations/test.consensus-error@1.json"
        # A ledger entry whose record was never written: the plan is spent, and the gate says so.
        orphan = write_json(plan_file.with_name(f"confirmation-{'0' * 64}.json"),
                            {"schema": thresholds.CONFIRMATION_SCHEMA, "plan": "0" * 64, "status": "refused"})
        self.assertIn("a ledger entry without its record", self.cli("validate", expect=1))
        orphan.unlink()
        # Deleting a committed plan (to plan the same confirmation cohort again) stays in the history.
        git(fixture.repo, "rm", "-q", "config/audio-qc-preregistrations/test.consensus-error@1.json")
        git(fixture.repo, "commit", "-q", "--no-verify", "-m", "drop the plan")
        self.assertIn("config/audio-qc-preregistrations/test.consensus-error@1.json: a committed plan, ledger "
                      "entry or record was later deleted", self.cli("validate", expect=1))

    # -- defect 7: the calibration floor ------------------------------------------------------
    def test_the_calibration_floor_holds_per_stratum(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.fixture = Fixture(Path(directory.name), per_language=30)
        scores = self.calibration_scores(bundle=self.fixture.negative_bundle(self.fixture.calibration, "cal"))
        message = self.plan("test.consensus-error@1", scores, expect=2)
        self.assertIn("english: 30 scored calibration families, the floor is 60", message)

    def test_derivation_withholds_a_threshold_below_the_floor(self) -> None:
        scores = self.planned()
        repository = calibration.Repository(self.fixture.repo)
        _, entry = repository.entry("test.consensus-error@1")
        plan = calibration.committed_plan(repository, entry)
        document = calibration.load_scores(scores)
        self.assertEqual(calibration.derivation(repository, entry, plan, document, 60)["status"], "derived")
        short = calibration.derivation(repository, entry, plan, document, 61)
        self.assertEqual((short["status"], short["thresholds"]["english"],
                          short["byStratum"]["english"]["minimumNegatives"]), ("insufficient-negatives", None, 61))


def evidence_record(take: dict) -> dict:
    """A take-evidence record as the orchestrator writes it (it passes validate_take_evidence)."""
    composed = compose_take("language-bench", [
        stage0_detector({"algorithmVersion": 8, "verdict": "pass", "instabilityVerdict": "pass",
                         "writtenOutputVerdict": "pass"}),
        *channel_detectors({"whisper": [{"language": True, "accuracy": True}]}, unqualified=[], unavailable={})])
    measurements = [{"judge": judge, "outputIdentity": IDENTITY[judge], "status": "complete",
                     "metrics": {"errorRate": 0.1, "accuracyMetricVersion": METRIC_VERSION},
                     "metricsSHA256": "a" * 64, "transcriptSHA256": "a" * 64, "wallSeconds": 0.2, "reasons": [],
                     "cache": {"l1": "miss", "l2": "miss"}} for judge in (PARAKEET, WHISPER)]
    return {
        "schema": TAKE_EVIDENCE_SCHEMA,
        "take": {"takeID": take["takeID"], "audioSHA256": take["wavSHA256"], "canonicalPCMSHA256": "b" * 64,
                 "canonicalSampleRateHz": 16000, "durationSeconds": 2.0, "textSHA256": take["textSHA256"],
                 "language": take["language"], "role": None, "expectedOutcome": "pass"},
        "registries": {"judges": "d" * 64, "detectors": None, "policy": "e" * 64},
        "stage0": {"audioQC": {"algorithmVersion": 8, "verdict": "pass", "flags": []}},
        "measurements": measurements, "verdicts": composed["verdicts"],
        "takeVerdict": {key: composed[key] for key in ("lane", "status", "composition", "decidedBy", "reasons")},
        "legacyVerdicts": {"languageWitness": {"status": "one-witness", "expectationMet": True,
                                               "families": ["whisper"], "reasons": []}},
    }


class WriterRoundTripTests(unittest.TestCase):
    """The driver reads what the real writers write: the private-bundle writer and the streamed JSON writer of
    measurements.json and injection sets (the fixtures above only copy their shapes)."""

    def test_the_driver_reads_the_writers_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory), per_language=2, positives_per_language=1)
            cohort = calibration.load_cohort(fixture.confirmation)
            takes = fixture.takes(fixture.confirmation)
            privates = [{"schema": PRIVATE_SCHEMA, "takeID": take["takeID"], "manifestTakeID": take["takeID"],
                         "audioPath": "take.wav", "referenceText": REFERENCE, "transcripts": {}} for take in takes]
            header = {"runID": "run-1", "lane": "language-bench", "manifestSHA256": "1" * 64,
                      "registries": {"judges": "d" * 64, "detectors": "9" * 64, "policy": "e" * 64},
                      "orchestratorSHA256": ORCHESTRATOR, "workerHostSHA256": "3" * 64,
                      "judgeMetrics": judge_metrics(WHISPER, PARAKEET), "admission": {},
                      "cache": {"L1": {"hits": 0, "misses": 6, "adopted": 0}}, "scorer": {}, "workers": [],
                      "run": {}, "startedAt": FRESH, "cacheRootEmptyAtStart": True}
            written = fixture.root / "written-bundle"
            write_private_bundle(written, header=header, takes=zip(map(evidence_record, takes), privates),
                                 repository=REPO)
            panel = calibration.build_scores(consensus_entry(), cohort, role="informational", split="test",
                                             bundle=calibration.Bundle(written))
            self.assertEqual({unit["abstain"] for unit in panel["units"]}, {None})
            self.assertEqual((panel["sources"]["bundle"]["startedAt"], panel["evidenceIdentity"]["judgeMetrics"]),
                             (FRESH, {judge: [value] for judge, value in judge_metrics(PARAKEET, WHISPER).items()}))

            def streamed(path: Path, key: str, digest_key: str) -> Path:
                data = json.loads(path.read_text(encoding="utf-8"))
                items = data.pop(key)
                data.pop(digest_key)
                target = path.with_name(f"streamed-{path.name}")
                audio_qc_calibration_set._write_streamed(target, data, key, iter(items),
                                                         lambda digest: {digest_key: digest})
                return target
            injection = streamed(fixture.injection_set(("SIG-LEVEL",)), "entries", "entriesSHA256")
            measured = streamed(fixture.measurements(fixture.confirmation, "measured", injection_set=injection),
                                "clips", "clipsSHA256")
            level = calibration.build_scores(
                level_entry(), cohort, role="informational", split="test",
                measurements=calibration.load_measurements(measured),
                injection_set=calibration.load_injection_set(injection),
                positive_measurements=calibration.load_measurements(measured))
            self.assertEqual(level["counts"]["byPopulation"], {"N2": 6, "P1": 3, "S": 3})
            self.assertEqual(level["counts"]["abstained"], {})


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
            "evidence": {"scoringCodeSHA256": "6" * 64, "evidenceIdentitySHA256": "7" * 64,
                         "orchestratorSHA256": [], "metricVersions": {},
                         "injectionSet": {"entriesSHA256": "8" * 64,
                                          "construction": {"catalogVersion": 2, "catalogSeed": 7,
                                                           "classes": ["A", "B"], "samplePerCell": 150,
                                                           "sampleSeed": 1}},
                         "planCommittedAt": "2026-09-01T00:00:00Z", "confirmationPanels": []},
            "split": {"method": "declared-cohorts", "disjointBy": ["family", "script"], "counts": {}},
            "speakers": {"unit": "language:fleurs-unidentified", "claim": "lower-bound", "count": 3},
            "threshold": {"strata": "pooled", "values": {"pooled": -22.9}, "ranks": {"pooled": 86},
                          "calibrationUnits": {"pooled": 90}, "alpha": 0.05, "rule": "split-conformal",
                          "unit": "source-family"},
            "counts": {}, "rates": {"farPooled": rate, "mechanisms": {},
                                    "shams": {"SIG-LEVEL": {**rate, "present": True, "overlaps": True,
                                                            "informative": False}}},
            "a4": {"unit": "injector", "cells": ["SIG-LEVEL"],
                   "uninformative": {"SIG-LEVEL": calibration.UNINFORMATIVE_SHAM}},
            "phiAudit": [], "scope": scope(), "limitations": ["fleurs-no-speaker-ids"], "risks": [],
            "informational": None, "ledgerOutcomeSHA256": "5" * 64,
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
                         lambda record: record["evidence"].update(scoringCodeSHA256=None),
                         lambda record: record["a4"].update(cells=["SIG-LEVEL", "SIG-DC"]),
                         lambda record: record.pop("risks")):
            record = self.record()
            mutation(record)
            self.assertTrue(calibration.record_errors(record), mutation)


if __name__ == "__main__":
    unittest.main()
