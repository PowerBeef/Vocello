#!/usr/bin/env python3
"""AQ-07 warn-level detector qualification: registry, cohort-split plans, derive and confirm-once."""

from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
import math
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
from lib import audio_qc_observations, language_metrics  # noqa: E402
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
IDENTITY = {WHISPER: "a" * 64, PARAKEET: "b" * 64, "pitch.pyin@1": "c" * 64,
            "speaker.campplus-voxceleb@1": "d" * 64}
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
    # No background auto-maintenance: it writes and removes .git/objects/maintenance.lock after a commit,
    # which raced a fixture's shutil.copytree of a template repository on Linux CI.
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", "-c", "maintenance.auto=false", "-c", "gc.auto=0", *argv],
                   check=True, stdout=subprocess.DEVNULL, env=environment)


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


def mean_entry() -> dict:
    """Two families' error rates averaged (consensus-mean): each family's evidence counts at half weight."""
    entry = consensus_entry("test.consensus-mean@1")
    entry["score"]["combination"] = "consensus-mean"
    entry["measures"] = "The mean of two families' scores."
    return entry


ALIGNER = "align.qwen3-forcedaligner-0.6b@1"
IDENTITY[ALIGNER] = "e" * 64


def run_on_entry() -> dict:
    """A PCM measure minus a non-voting panel timing, gated on both content voters (boundary.run-on@2's shape)."""
    return {
        "id": "test.run-on@1", "class": "C", "stage": 2, "measures": "Active audio after the script's end.",
        "score": {"combination": "difference", "unit": "seconds", "groups": [
            {"languages": list(LANGUAGES), "components": [{"source": "pcm", "field": "lastActiveSeconds"},
                                                          {"source": "panel", "judge": ALIGNER,
                                                           "metric": "spanEndSeconds"}],
             "requiresComplete": [WHISPER, PARAKEET]}]},
        "direction": "above", "strata": {"by": "language", "reason": "The aligner's end differs by language."},
        "scope": scope(),
        "targets": [{"injectorID": "BND-RUNON", "severities": ["severe"], "mechanism": "T1-pcm-construction"}],
        "shams": [{"injectorID": "BND-RUNON", "mechanism": "T1-pcm-construction"}],
        "populations": "fleurs-n2", "limitations": ["fleurs-no-speaker-ids"], "risks": [],
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


def token_loop_entry(detector: str = "test.token-loop@1", populations: str = "n3-codec-trace") -> dict:
    """A Stage 0 introspection detector fitted and confirmed on N3 takes, with declared T2 positives."""
    return {
        "id": detector, "class": "I", "stage": 0, "measures": "The looped codec span.",
        "score": {"combination": "single", "unit": "codec-frames", "groups": [
            {"languages": list(LANGUAGES), "components": [{"source": "introspection",
                                                            "field": "tokenCycleSpanFrames"}]}]},
        "direction": "above", "strata": None, "scope": scope(),
        "targets": [{"injectorID": "COD-LOOP", "severities": ["severe"], "mechanism": "T2-codec-construction"}],
        "shams": [{"injectorID": "COD-LOOP", "mechanism": "T2-codec-construction"}],
        "populations": populations, "limitations": ["n3-no-labels"], "risks": [],
    }


def pitch_entry() -> dict:
    """A class F detector that reduces pYIN's raw frame track (a DSP instrument, so it may stand alone)."""
    return {
        "id": "test.pitch-break@1", "class": "F", "stage": 1, "measures": "The largest pitch step.",
        "score": {"combination": "single", "unit": "semitones", "groups": [
            {"languages": list(LANGUAGES), "components": [{"source": "raw-output", "judge": "pitch.pyin@1",
                                                            "measure": "maxPitchStepSemitones"}]}]},
        "direction": "above", "strata": None, "scope": scope(),
        "targets": [{"injectorID": "PRS-BRK", "severities": ["severe"], "mechanism": "T1-pcm-construction"}],
        "shams": [{"injectorID": "PRS-BRK", "mechanism": "T1-pcm-construction"}],
        "populations": "fleurs-n2", "limitations": ["fleurs-no-speaker-ids"], "risks": [],
    }


def fixture_registry() -> dict:
    real = json.loads((REPO / calibration.REGISTRY).read_text(encoding="utf-8"))
    roles = copy.deepcopy(real["roleSets"])
    # The fixture's speaker-labelled corpus has data; the long-form one stays pending.
    roles["speaker-labeled-n2"]["fit"]["corpus"] = "test-speakers-calibration"
    roles["speaker-labeled-n2"]["confirmNegatives"]["corpus"] = "test-speakers-confirmation"
    return {
        "schemaVersion": 1, "kind": detectors.REGISTRY_KIND, "authority": "test", "note": "test",
        "operatingPoint": "warn", "roleSets": roles,
        "limitations": {"fleurs-no-speaker-ids": real["limitations"]["fleurs-no-speaker-ids"],
                        "n3-no-labels": real["limitations"]["n3-no-labels"]},
        "exclusionReasons": {"not-in-fixture": "The fixture covers three languages."},
        "risks": {"test-risk": "A declared risk."},
        "detectors": [consensus_entry(), level_entry(),
                      consensus_entry("test.truncation@1", source="transcript-tail",
                                      what="trailingUnmatchedFraction", injectors_=("BND-TRUNC",), klass="C"),
                      consensus_entry("test.two-injectors@1", injectors_=("CNT-DEL", "CNT-INS")),
                      token_loop_entry(), token_loop_entry("test.long-loop@1", "n3-long-form"),
                      {**level_entry(), "id": "test.labeled-level@1", "populations": "speaker-labeled-n2"},
                      pitch_entry(), mean_entry(), run_on_entry()],
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
    def measurements(self, cohort: Path, name: str, *, injection_set: Path | None = None,
                     started_at: str | None = FRESH) -> Path:
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
            "kind": calibration.MEASUREMENTS_KIND, "schemaVersion": 1, "startedAt": started_at,
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
                         ["A", "B", "C", "D", "E", "F", "I", "J"])

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


def _fewest_indels(reference: list, hypothesis: list) -> tuple[int, int]:
    """Brute force: (minimum edit cost, fewest insertions plus deletions among the minimum-cost alignments)."""
    best: dict[tuple[int, int], tuple[int, int]] = {}

    def walk(row: int, column: int) -> tuple[int, int]:
        if (row, column) in best:
            return best[(row, column)]
        if row == len(reference) or column == len(hypothesis):
            rest = (len(reference) - row) + (len(hypothesis) - column)
            best[(row, column)] = (rest, rest)
            return best[(row, column)]
        cost, indels = walk(row + 1, column + 1)
        options = [(cost + (reference[row] != hypothesis[column]), indels)]
        for step in (walk(row + 1, column), walk(row, column + 1)):
            options.append((step[0] + 1, step[1] + 1))
        best[(row, column)] = min(options)
        return best[(row, column)]
    return walk(0, 0)


class InsertionDeletionTests(unittest.TestCase):
    """content.consensus-error@2's reduction and the two-family mean."""

    def test_repeats_and_insertions_count_and_a_misheard_word_does_not(self) -> None:
        repeated = detectors.insertion_deletion("a b c d".split(), "a b c b c d".split())
        self.assertEqual((repeated["insertions"], repeated["deletions"], repeated["insertionDeletionRate"]),
                         (2, 0, 0.5))
        dropped = detectors.insertion_deletion("a b c d".split(), "a d".split())
        self.assertEqual((dropped["insertions"], dropped["deletions"]), (0, 2))
        # [a, b] heard as [b, c]: two substitutions or a deletion and an insertion cost the same; the reading
        # with the fewest insertions and deletions wins, so a recognizer's misreading is no content defect.
        shifted = detectors.insertion_deletion(["a", "b"], ["b", "c"])
        self.assertEqual((shifted["editCost"], shifted["insertionDeletions"]), (2, 0))
        self.assertEqual(detectors.insertion_deletion(["a", "b"], [])["insertionDeletionRate"], 1.0)
        self.assertIsNone(detectors.insertion_deletion([], ["a"])["insertionDeletionRate"])

    def test_the_counts_are_the_fewest_over_every_minimum_cost_alignment(self) -> None:
        stream = SeededStream(11, "insertion-deletion")
        for _ in range(300):
            lengths = [int(value) for value in stream.integers(7, 2)]
            reference = [int(value) for value in stream.integers(3, lengths[0])] if lengths[0] else []
            hypothesis = [int(value) for value in stream.integers(3, lengths[1])] if lengths[1] else []
            result = detectors.insertion_deletion(reference, hypothesis)
            cost, indels = _fewest_indels(reference, hypothesis)
            self.assertEqual((result["editCost"], result["insertionDeletions"]), (cost, indels))
            self.assertEqual(result["insertions"] - result["deletions"], len(hypothesis) - len(reference))
            self.assertEqual(result["editCost"],
                             language_metrics.edit_metrics(reference, hypothesis)["substitutions"]
                             + language_metrics.edit_metrics(reference, hypothesis)["insertions"]
                             + language_metrics.edit_metrics(reference, hypothesis)["deletions"])

    def test_the_transcript_edit_source_reads_private_transcripts(self) -> None:
        component = {"source": "transcript-edit", "judge": PARAKEET, "measure": "insertionDeletionRate"}
        complete = {PARAKEET: {"status": "complete", "metrics": {"transcriptEmpty": False}}}
        private = {"referenceText": "one two three four", "transcripts": {PARAKEET: "one two three two three four"}}
        self.assertEqual(detectors.component_value(component, language="english", measurements=complete,
                                                   private=private), (0.5, None))
        empty = {PARAKEET: {"status": "complete", "metrics": {"transcriptEmpty": True}}}
        self.assertEqual(detectors.component_value(component, language="english", measurements=empty,
                                                   private={"referenceText": "one two", "transcripts": {}}),
                         (1.0, None))
        self.assertEqual(detectors.component_value(component, language="english", measurements=complete,
                                                   private={"referenceText": "one two", "transcripts": {}}),
                         (None, "no-transcript"))

    def test_consensus_mean_averages_two_families(self) -> None:
        entry = mean_entry()
        measurements = {WHISPER: {"status": "complete", "metrics": {"errorRate": 0.0}},
                        PARAKEET: {"status": "complete", "metrics": {"errorRate": 0.3}}}
        self.assertAlmostEqual(detectors.score_take(entry, "german", measurements=measurements)["score"], 0.15)
        self.assertEqual(detectors.combine("consensus-mean", [0.2, 0.9]), 0.55)
        self.assertIn("consensus-mean", detectors.CONSENSUS_COMBINATIONS)


class ContentV2RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.judges = json.loads((REPO / calibration.JUDGES).read_text(encoding="utf-8"))
        self.registry = json.loads((REPO / calibration.REGISTRY).read_text(encoding="utf-8"))
        self.entry = detectors.detector_entry(self.registry, "content.consensus-error@2")

    def mutate(self, change) -> list[str]:
        registry = copy.deepcopy(self.registry)
        change(next(entry for entry in registry["detectors"] if entry["id"] == "content.consensus-error@2"))
        return detectors.registry_errors(registry, self.judges)

    def test_definition(self) -> None:
        self.assertEqual(self.entry["score"]["combination"], "consensus-mean")
        self.assertTrue(detectors.needs_private(self.entry) and detectors.needs_panel(self.entry))
        self.assertEqual(sorted(detectors.judges_of(self.entry)),
                         sorted([WHISPER, PARAKEET, "asr.paraformer-zh@1"]))
        self.assertEqual({item["language"] for item in self.entry["scope"]["exclusions"]}, {"japanese", "korean"})
        self.assertEqual(detectors.target_injectors(self.entry), {"CNT-DEL", "CNT-INS", "CNT-REP"})
        self.assertEqual(detectors.strata_by(self.entry), "language")
        # v1 keeps its minimum of error rates.
        self.assertEqual(detectors.detector_entry(self.registry, "content.consensus-error@1")["score"]["combination"],
                         "consensus-min")

    def test_the_mean_keeps_the_two_family_rules(self) -> None:
        def same_family(entry):
            entry["score"]["groups"][0]["components"][1]["judge"] = "asr.whisper-small@1"
        self.assertTrue(any("two recognizer families" in error for error in self.mutate(same_family)))

        def same_lab(entry):
            entry["score"]["groups"][0]["components"][1]["judge"] = "asr.qwen3-asr-1.7b@1"
        self.assertTrue(any("A6" in error for error in self.mutate(same_lab)))

        def unknown_measure(entry):
            entry["score"]["groups"][0]["components"][0]["measure"] = "insertionRate"
        self.assertTrue(any("insertionDeletionRate" in error for error in self.mutate(unknown_measure)))

        def below(entry):
            entry["direction"] = "below"
        # The mean has no direction of its own: either is valid.
        self.assertEqual(self.mutate(below), [])


ALL_LANGUAGES = tuple(language_metrics.PRODUCT_LANGUAGES)
CAMPPLUS, RESNET, PYIN = "speaker.campplus-voxceleb@1", "speaker.resnet293-voxceleb@1", "pitch.pyin@1"


class NewClassRegistryTests(unittest.TestCase):
    """Classes E, F, I and J: role sets, language-free judges, targets and the voter rules they keep."""

    def setUp(self) -> None:
        self.judges = json.loads((REPO / calibration.JUDGES).read_text(encoding="utf-8"))
        self.registry = json.loads((REPO / calibration.REGISTRY).read_text(encoding="utf-8"))

    def entry(self, detector: str) -> dict:
        return detectors.detector_entry(self.registry, detector)

    def mutate(self, detector: str, change) -> list[str]:
        registry = copy.deepcopy(self.registry)
        change(next(entry for entry in registry["detectors"] if entry["id"] == detector), registry)
        return detectors.registry_errors(registry, self.judges)

    def test_language_free_panel_judges_cover_every_language(self) -> None:
        judges = self.judges["judges"]
        for judge in (CAMPPLUS, RESNET, PYIN):
            self.assertEqual(detectors._judge_languages(judges[judge]), set(ALL_LANGUAGES))
        self.assertEqual(detectors._judge_languages(judges["asr.parakeet-tdt-0.6b-v3@1"]),
                         {"english", "french", "german", "italian", "portuguese", "russian", "spanish"})
        # No panel entry: not a panel judge, so it covers no language.
        self.assertEqual(detectors._judge_languages(judges["asr.whisper-small@1"]), set())

    def test_identity_role_set_and_targets(self) -> None:
        for detector in ("identity.clone-similarity@1", "identity.window-drift@1", "identity.onset-drift@1"):
            entry = self.entry(detector)
            self.assertEqual((entry["class"], entry["stage"]), ("E", 2))
            roles = detectors.role_set(self.registry, entry)
            self.assertEqual((roles["fit"]["population"], roles["confirmNegatives"]["population"],
                              roles["positives"]["population"]), ("N2", "N2", "P1"))
            self.assertEqual(detectors.judges_of(entry), [CAMPPLUS])
            self.assertTrue(detectors.needs_panel(entry))
            self.assertFalse(detectors.needs_measurements(entry) or detectors.needs_private(entry))
            self.assertEqual(sorted(entry["scope"]["languages"]), sorted(ALL_LANGUAGES))
        similarity = self.entry("identity.clone-similarity@1")
        self.assertEqual(detectors.target_injectors(similarity), {"IDN-IMPOSTOR", "IDN-SHIFT"})
        self.assertEqual(detectors.target_mechanism(similarity, "IDN-IMPOSTOR"), "T1-parallel-corpus")
        self.assertEqual(detectors.target_cell(similarity, "IDN-SHIFT", "severe", "T1-pcm-construction"),
                         "IDN-SHIFT/severe")
        self.assertIsNone(detectors.target_cell(similarity, "IDN-SHIFT", "severe", "T1-parallel-corpus"))
        self.assertEqual(detectors.target_injectors(self.entry("identity.window-drift@1")), {"IDN-SWAP"})
        self.assertEqual(detectors.target_injectors(self.entry("identity.onset-drift@1")), {"IDN-ONSET"})
        self.assertTrue(detectors.sham_of(similarity, "IDN-IMPOSTOR", "T1-parallel-corpus"))

    def test_identity_detectors_keep_the_voter_rules(self) -> None:
        def resnet(entry, _):
            entry["score"]["groups"][0]["components"][0]["judge"] = RESNET
        self.assertTrue(any("does not vote" in error for error in self.mutate("identity.clone-similarity@1", resnet)))

        def unknown_metric(entry, _):
            entry["score"]["groups"][0]["components"][1]["metric"] = "window cosine"
        self.assertTrue(any("panel metric" in error
                            for error in self.mutate("identity.window-drift@1", unknown_metric)))

    def test_role_sets_are_validated(self) -> None:
        def confirm_on_calibration(_, registry):
            registry["roleSets"]["speaker-labeled-n2"]["confirmNegatives"]["cohort"] = "calibration"
        self.assertTrue(any("roleSets.speaker-labeled-n2" in error
                            for error in self.mutate("identity.clone-similarity@1", confirm_on_calibration)))

        def unknown_population(_, registry):
            registry["roleSets"]["speaker-labeled-n2"]["positives"]["population"] = "P9"
        self.assertTrue(any("roleSets.speaker-labeled-n2.positives" in error
                            for error in self.mutate("identity.clone-similarity@1", unknown_population)))

        def unnamed_role_set(entry, _):
            entry["populations"] = "speaker-corpus"
        self.assertTrue(any("must name a role set" in error
                            for error in self.mutate("identity.clone-similarity@1", unnamed_role_set)))

    def test_prosody_detectors_reduce_the_pitch_track(self) -> None:
        for detector, injector in (("prosody.pitch-break@1", "PRS-BRK"), ("prosody.octave-jump@1", "PRS-OCT")):
            entry = self.entry(detector)
            self.assertEqual((entry["class"], entry["stage"], entry["populations"]), ("F", 1, "fleurs-n2"))
            self.assertEqual(detectors.judges_of(entry), [PYIN])
            self.assertTrue(detectors.needs_panel(entry) and detectors.needs_raw(entry))
            self.assertFalse(detectors.needs_private(entry) or detectors.needs_measurements(entry))
            self.assertEqual(detectors.target_injectors(entry), {injector})
            self.assertEqual(detectors.target_cell(entry, injector, "severe", "T1-pcm-construction"),
                             f"{injector}/severe")
        self.assertFalse(detectors.needs_raw(self.entry("identity.clone-similarity@1")))
        # Erratic pitch is fitted on natural expressive takes (N3), with FLEURS read speech informational.
        instability = self.entry("prosody.pitch-instability@1")
        self.assertEqual((instability["class"], instability["populations"]), ("F", "n3-takes"))
        roles = detectors.role_set(self.registry, instability)
        self.assertEqual((roles["fit"]["population"], roles["confirmNegatives"]["population"],
                          roles["positives"]["population"], roles["informational"]), ("N3", "N3", "P1", ["N2"]))
        self.assertEqual(detectors.judges_of(instability), [PYIN])
        self.assertEqual(detectors.target_injectors(instability), {"PRS-ERRATIC"})
        self.assertEqual(detectors.declared_cells(instability), {"T1-pcm-construction": {"PRS-ERRATIC/severe"}})

    def test_a_dsp_instrument_scores_alone_only_through_its_raw_output(self) -> None:
        # pYIN does not vote: its L2 metric through a `panel` component would make it a family's vote.
        def panel_metric(entry, _):
            entry["score"]["groups"][0]["components"][0] = {"source": "panel", "judge": PYIN,
                                                            "metric": "f0RangeSemitones"}
        self.assertTrue(any("does not vote" in error for error in self.mutate("prosody.pitch-break@1", panel_metric)))

        def speaker_track(entry, _):
            entry["score"]["groups"][0]["components"][0]["judge"] = CAMPPLUS
        self.assertTrue(any("pyin-librosa" in error for error in self.mutate("prosody.pitch-break@1", speaker_track)))

        def unknown_measure(entry, _):
            entry["score"]["groups"][0]["components"][0]["measure"] = "jitter"
        self.assertTrue(any(".measure must be one of" in error
                            for error in self.mutate("prosody.octave-jump@1", unknown_measure)))

        for change, expected in ((lambda judge: judge.update(status="candidate"), "below shadow"),
                                 (lambda judge: judge["independence"].update(generatorLabCorrelated=True), "A6")):
            judges = copy.deepcopy(self.judges)
            change(judges["judges"][PYIN])
            self.assertTrue(any(expected in error for error in detectors.registry_errors(self.registry, judges)))
        # A neural judge is no instrument, whatever its kind of output.
        judges = copy.deepcopy(self.judges)
        judges["judges"][PYIN]["kind"] = "neural"
        self.assertTrue(any("does not vote" in error for error in detectors.registry_errors(self.registry, judges)))

    def test_introspection_fields_are_the_summarys_and_the_role_sets_name_n3(self) -> None:
        summary = audio_qc_observations.introspection_summary([1, 2, 1, 2, 1, 2], entropies=[1.0] * 6,
                                                              eos_probabilities=[0.1] * 6)
        self.assertLessEqual(detectors.INTROSPECTION_SCORE_FIELDS, set(summary))
        self.assertLessEqual(detectors.INTROSPECTION_ABSENT_AS_ZERO, detectors.INTROSPECTION_SCORE_FIELDS)
        expected = {"introspection.token-loop@1": ("n3-codec-trace", "P2", "COD-LOOP", "T2-codec-construction"),
                    "introspection.high-entropy@1": ("n3-controlled-generation", "P3", "GEN-NOEOS",
                                                     "T3-controlled-generation"),
                    "introspection.eos-overrun@1": ("n3-controlled-generation", "P3", "GEN-NOEOS",
                                                    "T3-controlled-generation")}
        for detector, (role_set, positives, injector, mechanism) in expected.items():
            entry = self.entry(detector)
            self.assertEqual((entry["class"], entry["stage"], entry["populations"]), ("I", 0, role_set))
            roles = detectors.role_set(self.registry, entry)
            self.assertEqual((roles["fit"]["population"], roles["confirmNegatives"]["population"],
                              roles["positives"]["population"], roles["informational"]), ("N3", "N3", positives, []))
            self.assertEqual(detectors.judges_of(entry), [detectors.STAGE0_JUDGE])
            self.assertTrue(detectors.needs_measurements(entry))
            self.assertFalse(detectors.needs_panel(entry) or detectors.needs_raw(entry))
            self.assertEqual(detectors.target_injectors(entry), {injector})
            self.assertEqual(detectors.target_mechanism(entry, injector), mechanism)
            self.assertEqual(detectors.declared_cells(entry), {mechanism: {f"{injector}/severe"}})

        def unknown_field(entry, _):
            entry["score"]["groups"][0]["components"][0]["field"] = "entropyMaxNats"
        self.assertTrue(any("introspection summary" in error
                            for error in self.mutate("introspection.high-entropy@1", unknown_field)))

        def fastqc_field(entry, _):
            entry["score"]["groups"][0]["components"][0] = {"source": "fastqc", "field": "tokenCycleSpanFrames"}
        self.assertTrue(any("Fast QC v8 field" in error
                            for error in self.mutate("introspection.token-loop@1", fastqc_field)))

        def panel_at_stage_zero(entry, _):
            entry["score"]["groups"][0]["components"][0] = {"source": "panel", "judge": CAMPPLUS, "metric": "cosine"}
        self.assertTrue(any("Stage 0 detector" in error
                            for error in self.mutate("introspection.eos-overrun@1", panel_at_stage_zero)))

    def test_long_form_role_set_sources_and_seam_measure(self) -> None:
        expected = {"long-form.seam-discontinuity@1": (0, "SEAM-DISC", [detectors.STAGE0_JUDGE]),
                    "long-form.seam-jump@1": (0, "SEAM-DISC", [detectors.STAGE0_JUDGE]),
                    "long-form.seam-identity@1": (2, "SEAM-VOICE", [CAMPPLUS])}
        for detector, (stage, injector, judges) in expected.items():
            entry = self.entry(detector)
            self.assertEqual((entry["class"], entry["stage"], entry["strata"]), ("J", stage, None))
            roles = detectors.role_set(self.registry, entry)
            self.assertEqual((entry["populations"], roles["fit"]["population"], roles["positives"]["population"],
                              roles["informational"]), ("n3-long-form", "N3", "P1", []))
            self.assertEqual(detectors.judges_of(entry), judges)
            self.assertEqual(detectors.target_injectors(entry), {injector})
            self.assertEqual(detectors.needs_seams(entry), detector == "long-form.seam-identity@1")
            self.assertEqual(detectors.needs_measurements(entry), stage == 0)
            self.assertEqual(detectors.stratum(detectors.strata_by(entry), "french"), detectors.POOLED)

        def unknown_long_form_field(entry, _):
            entry["score"]["groups"][0]["components"][0]["field"] = "segmentCount"
        self.assertTrue(any("maximumSegmentBoundaryJump" in error
                            for error in self.mutate("long-form.seam-jump@1", unknown_long_form_field)))

        def resnet(entry, _):
            entry["score"]["groups"][0]["components"][0]["judge"] = RESNET
        self.assertTrue(any("does not vote" in error for error in self.mutate("long-form.seam-identity@1", resnet)))

        def pitch_judge(entry, _):
            entry["score"]["groups"][0]["components"][0]["judge"] = PYIN
        self.assertTrue(any("wespeaker-onnx" in error
                            for error in self.mutate("long-form.seam-identity@1", pitch_judge)))
        judges = copy.deepcopy(self.judges)
        judges["judges"][CAMPPLUS]["preprocessing"]["windows"]["seconds"] = 1.5
        self.assertTrue(any("2 s windows" in error for error in detectors.registry_errors(self.registry, judges)))


class NewClassScoringTests(unittest.TestCase):
    """score_take on fixture evidence for classes E, F, I and J, and their abstentions."""

    def setUp(self) -> None:
        self.registry = json.loads((REPO / calibration.REGISTRY).read_text(encoding="utf-8"))

    def entry(self, detector: str) -> dict:
        return detectors.detector_entry(self.registry, detector)

    def test_identity_scores_and_abstentions(self) -> None:
        metrics = {"cosine": 0.82, "windowCount": 17, "windowCosineMinimum": 0.31, "windowCosineMean": 0.7,
                   "onsetWindowCosine": 0.74, "embeddingDimension": 512}
        evidence = {CAMPPLUS: {"status": "complete", "metrics": metrics}}
        expected = {"identity.clone-similarity@1": 0.82, "identity.window-drift@1": 0.51,
                    "identity.onset-drift@1": 0.08}
        for detector, score in expected.items():
            entry = self.entry(detector)
            scored = detectors.score_take(entry, "korean", measurements=evidence)
            self.assertEqual((scored["inScope"], scored["abstain"]), (True, None), detector)
            self.assertAlmostEqual(scored["score"], score, places=9)
            # No reference clip: CAM++ completes but reports no similarity, so the take abstains.
            unreferenced = {CAMPPLUS: {"status": "complete", "metrics": {}}}
            self.assertEqual(detectors.score_take(entry, "english", measurements=unreferenced)["abstain"], "no-value")
            # A take shorter than one window has no window cosine.
            short = {CAMPPLUS: {"status": "complete", "metrics": {**metrics, "windowCount": 0,
                                                                  "windowCosineMinimum": None,
                                                                  "onsetWindowCosine": None}}}
            self.assertEqual(detectors.score_take(entry, "english", measurements=short)["abstain"],
                             None if detector == "identity.clone-similarity@1" else "no-value")
            self.assertEqual(detectors.score_take(entry, "english", measurements={})["abstain"], "not-measured")
            self.assertEqual(detectors.score_take(entry, "english", measurements={
                CAMPPLUS: {"status": "out-of-scope", "metrics": {}}})["abstain"], "judge-out-of-scope")
            self.assertEqual(detectors.score_take(entry, "english", measurements={
                CAMPPLUS: {"status": "unavailable", "metrics": {}}})["abstain"], "judge-unavailable")
            outside = detectors.score_take(entry, "dutch", measurements=evidence)
            self.assertEqual((outside["inScope"], outside["abstain"], outside["score"]), (False, "out-of-scope", None))

    @staticmethod
    def track(*spans: tuple[float | None, int]) -> dict:
        """A pYIN frame track at a 10 ms hop: (F0 in Hz, or None for unvoiced frames, frame count) spans."""
        f0: list = []
        for hertz, count in spans:
            f0.extend([hertz] * count)
        return {"hopSeconds": 0.01, "f0Hz": f0, "voiced": [value is not None for value in f0],
                "voicedProbability": [0.9 if value is not None else 0.1 for value in f0]}

    def test_pitch_scores_and_abstentions(self) -> None:
        pitch = {PYIN: {"status": "complete", "metrics": {"voicedFraction": 0.8}}}
        step, octave = self.entry("prosody.pitch-break@1"), self.entry("prosody.octave-jump@1")
        up_seven = 200.0 * 2 ** (7 / 12)

        def score(entry: dict, track: dict | None, measurements: dict = pitch, language: str = "english") -> dict:
            return detectors.score_take(entry, language, measurements=measurements,
                                        raw=None if track is None else {PYIN: track})

        # A 7 semitone break reached over two frames (pYIN's transition cap) scores 7 semitones.
        broken = self.track((200.0, 50), (250.0, 1), (up_seven, 49))
        self.assertAlmostEqual(score(step, broken)["score"], 7.0, places=6)
        self.assertEqual(score(octave, broken)["score"], 0.0)
        # An octave held for 370 ms: a 12 semitone step and a 0.37 s displacement.
        jumped = self.track((200.0, 100), (400.0, 37), (200.0, 100))
        self.assertAlmostEqual(score(step, jumped)["score"], 12.0, places=6)
        self.assertAlmostEqual(score(octave, jumped)["score"], 0.37, places=9)
        self.assertAlmostEqual(score(octave, jumped, language="chinese")["score"], 0.37, places=9)
        # An unvoiced frame ends a displaced run.
        split = self.track((200.0, 100), (400.0, 10), (None, 1), (400.0, 20), (200.0, 100))
        self.assertAlmostEqual(score(octave, split)["score"], 0.2, places=9)
        # Voiced frames more than 50 ms apart are never compared.
        gapped = self.track((200.0, 10), (None, 6), (300.0, 10))
        self.assertEqual(score(step, gapped)["score"], 0.0)
        self.assertAlmostEqual(score(step, self.track((200.0, 10), (None, 4), (300.0, 10)))["score"],
                               12 * math.log2(1.5), places=9)
        steady = self.track((None, 20), (180.0, 200), (None, 20))
        self.assertEqual((score(step, steady)["score"], score(octave, steady)["score"]), (0.0, 0.0))
        # Silence (no voiced frame), a malformed track, no exported track, no or failed pYIN row: abstain.
        for entry in (step, octave):
            self.assertEqual(score(entry, self.track((None, 300)))["abstain"], "no-value")
            self.assertEqual(score(entry, {**steady, "voiced": steady["voiced"][:-1]})["abstain"], "no-value")
            self.assertEqual(score(entry, None)["abstain"], "no-raw-output")
            self.assertEqual(score(entry, steady, measurements={})["abstain"], "not-measured")
            self.assertEqual(score(entry, steady, measurements={PYIN: {"status": "unavailable"}})["abstain"],
                             "judge-unavailable")
            self.assertEqual(score(entry, steady, language="dutch")["abstain"], "out-of-scope")
        # The raw measures are pure functions of the track.
        self.assertIsNone(detectors.max_pitch_step(self.track((200.0, 1))))
        self.assertEqual(detectors.longest_octave_displacement(self.track((200.0, 1))), 0.0)
        with self.assertRaises(detectors.DetectorError):
            detectors.raw_measure("jitter", steady)

    def test_pitch_instability_counts_jumps_a_voice_cannot_make(self) -> None:
        pitch = {PYIN: {"status": "complete", "metrics": {"voicedFraction": 0.9}}}
        entry = self.entry("prosody.pitch-instability@1")

        def rate(track: dict, language: str = "english") -> dict:
            return detectors.score_take(entry, language, measurements=pitch, raw={PYIN: track})

        # Erratic: 15 spans of 200 ms alternating 4 semitones apart, one-frame jumps: 14 jumps over 3 s.
        low, high = 200.0, 200.0 * 2 ** (4 / 12)
        erratic = self.track(*[(high if index % 2 else low, 20) for index in range(15)])
        self.assertAlmostEqual(rate(erratic)["score"], 14 / 3.0, places=9)
        self.assertAlmostEqual(rate(erratic, "korean")["score"], 14 / 3.0, places=9)
        # Wide expressive intonation that glides (12 semitones in 300 ms, 40 semitones per second): no jump.
        glide = [200.0 * 2 ** (0.4 * frame / 12) for frame in range(30)]
        track = self.track((200.0, 100), (None, 0), (glide[-1], 100))
        track["f0Hz"][100:100] = glide
        track["voiced"][100:100] = [True] * 30
        self.assertEqual(rate(track)["score"], 0.0)
        # A jump spread over two frames by pYIN's transition cap is one jump.
        split = self.track((200.0, 100), (200.0 * 2 ** (1.6 / 12), 1), (200.0 * 2 ** (3.2 / 12), 99))
        self.assertAlmostEqual(rate(split)["score"], 1 / 2.0, places=9)
        # Across an unvoiced gap: 7 semitones over 40 ms counts, over 60 ms it is never compared.
        up = 200.0 * 2 ** (7 / 12)
        self.assertAlmostEqual(rate(self.track((200.0, 100), (None, 3), (up, 100)))["score"], 1 / 2.0, places=9)
        self.assertEqual(rate(self.track((200.0, 100), (None, 5), (up, 100)))["score"], 0.0)
        # Less than a second of voiced speech, or none: abstain.
        self.assertEqual(rate(self.track((None, 100), (200.0, 99), (None, 100)))["abstain"], "no-value")
        self.assertIsNotNone(rate(self.track((200.0, 100)))["score"])
        self.assertEqual(rate(self.track((None, 300)))["abstain"], "no-value")
        self.assertEqual(detectors.score_take(entry, "english", measurements=pitch)["abstain"], "no-raw-output")
        self.assertEqual(detectors.score_take(entry, "english", measurements={}, raw={PYIN: erratic})["abstain"],
                         "not-measured")
        self.assertEqual(rate(erratic, "dutch")["abstain"], "out-of-scope")

    def test_introspection_scores_and_abstentions(self) -> None:
        loop, entropy, eos = (self.entry(detector) for detector in (
            "introspection.token-loop@1", "introspection.high-entropy@1", "introspection.eos-overrun@1"))
        # An 8-token phrase looped four times, a 7-step high-entropy run and 3 likely-EOS steps that did not stop.
        tokens = list(range(100, 120)) + list(range(8)) * 4 + list(range(200, 210))
        steps = len(tokens) + 1
        entropies = [1.0] * 20 + [4.5] * 7 + [2.0] * (steps - 27)
        eos_probabilities = [0.01] * (steps - 5) + [0.6, 0.7, 0.2, 0.55, 0.9]
        summary = audio_qc_observations.introspection_summary(
            tokens, entropies=entropies, eos_probabilities=eos_probabilities, stopped_at_eos=True)
        self.assertEqual((summary["tokenCyclePeriod"], summary["tokenCycleSpanFrames"]), (8, 32))
        clip = {"fastQC": {}, "observations": {}, "introspection": summary}
        self.assertEqual(detectors.score_take(loop, "japanese", clip=clip)["score"], 32.0)
        self.assertEqual(detectors.score_take(entropy, "japanese", clip=clip)["score"], 7.0)
        self.assertEqual(detectors.score_take(eos, "japanese", clip=clip)["score"], 3.0)
        component = f"{detectors.STAGE0_JUDGE}:introspection:tokenCycleSpanFrames"
        self.assertEqual(detectors.score_take(loop, "japanese", clip=clip)["components"], {component: 32.0})
        # No exact cycle: the summary reports none, which scores 0 rather than abstaining.
        plain = audio_qc_observations.introspection_summary(list(range(60)), entropies=[1.0] * 60,
                                                            eos_probabilities=[0.0] * 60)
        self.assertIsNone(plain["tokenCycleSpanFrames"])
        scored = detectors.score_take(loop, "english", clip={"introspection": plain})
        self.assertEqual((scored["score"], scored["abstain"]), (0.0, None))
        # A clip without a summary (the scorer does not carry one yet), no clip, or a language out of scope.
        for entry in (loop, entropy, eos):
            self.assertEqual(detectors.score_take(entry, "english", clip={"fastQC": {}})["abstain"], "no-value")
            self.assertEqual(detectors.score_take(entry, "english", clip={"introspection": {}})["abstain"],
                             "no-value")
            self.assertEqual(detectors.score_take(entry, "english")["abstain"], "not-measured")
            self.assertEqual(detectors.score_take(entry, "dutch", clip=clip)["abstain"], "out-of-scope")
        # An empty generation has a summary but no observed step: its entropy has no p95 to read.
        empty = audio_qc_observations.introspection_summary([])
        self.assertEqual(detectors.score_take(loop, "english", clip={"introspection": empty})["score"], 0.0)
        self.assertIsNone(empty["entropyP95Nats"])

    def test_long_form_scores_and_abstentions(self) -> None:
        discontinuity, jump, identity = (self.entry(detector) for detector in (
            "long-form.seam-discontinuity@1", "long-form.seam-jump@1", "long-form.seam-identity@1"))
        clip = {"fastQC": {}, "observations": {"seamDiscontinuityMaxZ": 14.25},
                "longForm": {"maximumSegmentBoundaryJump": 5120}}
        self.assertEqual(detectors.score_take(discontinuity, "german", clip=clip)["score"], 14.25)
        self.assertEqual(detectors.score_take(jump, "german", clip=clip)["score"], 5120.0)
        for entry in (discontinuity, jump):
            # The offline scorer passes no seam and carries no longForm block yet: no value, never a pass.
            self.assertEqual(detectors.score_take(entry, "german", clip={"observations": {
                "seamDiscontinuityMaxZ": None}})["abstain"], "no-value")
            self.assertEqual(detectors.score_take(entry, "german")["abstain"], "not-measured")
            self.assertEqual(detectors.score_take(entry, "dutch", clip=clip)["abstain"], "out-of-scope")

        voice, other, mixed = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.6, 0.8, 0.0]

        def windows(change_at: float, after: list, length: float = 10.0) -> dict:
            items = []
            for index in range(int((length - 2.0) / 0.5) + 1):
                start = index * 0.5
                embedding = voice if start + 2.0 <= change_at else after if start >= change_at else mixed
                items.append({"startSeconds": start, "embedding": embedding})
            return {"embedding": voice, "dimension": 3, "windows": items}

        evidence = {CAMPPLUS: {"status": "complete", "metrics": {}}}

        def score(output: dict | None, seams: list | None, language: str = "italian") -> dict:
            return detectors.score_take(identity, language, measurements=evidence,
                                        raw=None if output is None else {CAMPPLUS: output}, seams=seams)

        # Another voice after the seam at 5 s: the windows either side are orthogonal.
        self.assertEqual(score(windows(5.0, other), [5.0])["score"], 0.0)
        self.assertEqual(score(windows(5.0, voice), [5.0])["score"], 1.0)
        # The lowest over the seams; a seam without a whole window on each side is not scored.
        self.assertEqual(score(windows(5.0, other), [7.0, 5.0, 1.0])["score"], 0.0)
        self.assertEqual(score(windows(5.0, other), [1.0, 9.5])["abstain"], "no-value")
        self.assertEqual(score(windows(5.0, voice), [])["abstain"], "no-seams")
        self.assertEqual(score(windows(5.0, voice), None)["abstain"], "no-seams")
        self.assertEqual(score(None, [5.0])["abstain"], "no-raw-output")
        self.assertEqual(detectors.score_take(identity, "italian", measurements={}, raw={CAMPPLUS: windows(5.0, voice)},
                                              seams=[5.0])["abstain"], "not-measured")
        self.assertEqual(score(windows(5.0, voice), [5.0], language="dutch")["abstain"], "out-of-scope")
        self.assertAlmostEqual(detectors.seam_window_cosine_minimum(windows(5.0, mixed), [5.0]), 0.6, places=12)
        self.assertIsNone(detectors.raw_measure("seamWindowCosineMinimum", windows(5.0, voice)))


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
            # A plan at another operating point is filed beside the warn plan of the same version.
            fail = self.plan(alpha=0.005, bindings=(("operatingPoint", "fail"), ("detectorDefinitionSHA256", "3" * 64)))
            self.assertEqual(store.commit(fail).name, "test.consensus-error@1.fail.json")
            self.assertEqual((store.load(plan.detector), store.load(plan.detector, "fail")), (plan, fail))
            self.assertIsNone(store.load(plan.detector, "evidenceLaneFail"))
            (Path(directory) / "test.consensus-error@1.evidenceLaneFail.json").write_text(
                (Path(directory) / "test.consensus-error@1.fail.json").read_text(encoding="utf-8"), encoding="utf-8")
            with self.assertRaisesRegex(thresholds.PreRegistrationError, "at operating point fail"):
                store.load(plan.detector, "evidenceLaneFail")

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
        # A FLEURS plan keeps the shape every committed warn plan has.
        split = json.loads(plan_file.read_text(encoding="utf-8"))["split"]
        self.assertEqual((split["disjointBy"], split["speakers"], sorted(bindings)),
                         (["family", "script"], {"unit": "language:fleurs-unidentified", "claim": "lower-bound"},
                          ["calibrationScoresSHA256", "detectorDefinitionSHA256", "evidenceIdentitySHA256",
                           "injectionCatalogSeed", "injectionClasses", "injectionSamplePerCell", "injectionSampleSeed",
                           "injectorCatalogVersion", "operatingPoint", "policySHA256", "scoringCodeSHA256"]))
        committed = json.loads((REPO / "config/audio-qc-preregistrations/signal.clicks@1.json").read_text(
            encoding="utf-8"))
        self.assertEqual((committed["split"]["disjointBy"], committed["split"]["speakers"], sorted(committed["bindings"])),
                         (split["disjointBy"], split["speakers"], sorted(bindings)))
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

    def test_a_consensus_mean_detector_confirms_with_its_phi_audit(self) -> None:
        fixture = self.fixture
        detector = "test.consensus-mean@1"
        scores = self.calibration_scores(detector, bundle=fixture.negative_bundle(fixture.calibration, "mean-cal"))
        self.plan(detector, scores)
        fixture.commit_plans()
        injection = fixture.injection_set()
        confirmation = self.confirmation_scores(
            detector, bundle=fixture.negative_bundle(fixture.confirmation, "confirmation/panel-bundle-v2", scale=200.0),
            injection_set=injection, positive_bundle=fixture.positive_bundle(injection))
        units = json.loads(confirmation.read_text(encoding="utf-8"))["units"]
        clean = next(unit for unit in units if unit["injectorID"] is None)
        self.assertAlmostEqual(clean["score"], sum(clean["components"].values()) / 2.0, places=9)
        result = json.loads(self.confirm(detector, scores, confirmation))
        self.assertEqual((result["verdict"], result["reasons"]), ("qualified", []))
        record = json.loads((fixture.repo / result["record"]).read_text(encoding="utf-8"))
        self.assertEqual(record["combination"], "consensus-mean")
        self.assertEqual([audit["judges"] for audit in record["phiAudit"]], [[WHISPER, PARAKEET]])
        self.assertEqual(calibration.record_errors(record), [])
        # A consensus-mean record without its phi audit is refused like any consensus rule's.
        self.assertIn("phi audit", " ".join(calibration.record_errors({**record, "phiAudit": []})))

    def test_a_pcm_measure_minus_a_panel_timing_reads_both_sources(self) -> None:
        fixture = self.fixture
        takes = fixture.takes(fixture.calibration)
        rows = [(take["takeID"], take["language"], take["wavSHA256"], take["textSHA256"],
                 {WHISPER: fixture.asr(0.0), PARAKEET: "unavailable" if position == 0 else fixture.asr(0.0),
                  ALIGNER: {"spanEndSeconds": 5.0}}, None)
                for position, take in enumerate(takes)]
        bundle = fixture.bundle(fixture.root / "run-on-bundle", rows)

        def measurements(name: str, digest: str) -> Path:
            clips = [{"clipID": take["takeID"], "population": "N2", "family": take["family"],
                      "sourceTakeID": take["takeID"], "language": take["language"], "injection": None,
                      "wavSHA256": take["wavSHA256"], "fastQC": {}, "observations": {},
                      "pcmMeasures": {"version": "pcm-measures/1", "sourceSHA256": digest,
                                      "lastActiveSeconds": 5.0 + fixture.index(take["takeID"]) / 100.0}}
                     for take in takes]
            return write_json(fixture.root / f"{name}.json", {
                "kind": calibration.MEASUREMENTS_KIND, "schemaVersion": 1, "startedAt": FRESH,
                "subject": {"detector": "fastqc@8"}, "takesManifestSHA256": calibration.file_sha256(fixture.calibration),
                "entriesSHA256": None, "clipsSHA256": json_digest(clips), "clips": clips})
        scores = self.calibration_scores("test.run-on@1", bundle=bundle,
                                         measurements=measurements("run-on-measurements",
                                                                   detectors.pcm_measures_sha256()))
        units = {unit["unitID"]: unit for unit in json.loads(scores.read_text(encoding="utf-8"))["units"]}
        first = takes[0]["takeID"]
        # The first take's Parakeet row failed: a content voter the timing needs did not complete.
        self.assertEqual(units[first]["abstain"], "judge-unavailable")
        second = units[takes[1]["takeID"]]
        self.assertAlmostEqual(second["score"], fixture.index(takes[1]["takeID"]) / 100.0, places=9)
        self.assertEqual(sorted(second["components"]), [f"{ALIGNER}:panel:spanEndSeconds",
                                                        "fastqc@8:pcm:lastActiveSeconds"])
        # A block measured by other pcm_measures code is refused, never scored.
        refused = self.scores("test.run-on@1", "calibration", fixture.calibration, n1=fixture.n1["calibration"],
                              name="stale", expect=2, bundle=bundle,
                              measurements=measurements("stale-measurements", "0" * 64))
        self.assertIn("pcm_measures.py", refused)

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

    def test_confirmation_measurements_postdate_the_plan(self) -> None:
        # Fast QC and Stage 0 measurements stamp startedAt (outside clipsSHA256); like a panel, a confirmation's
        # measurements must start after its plan's commit (A5).
        fixture = self.fixture
        scores = self.calibration_scores("test.level@1",
                                         measurements=fixture.measurements(fixture.calibration, "cal-measurements"))
        self.plan("test.level@1", scores)
        fixture.commit_plans()
        injection = fixture.injection_set(("SIG-LEVEL",))
        for name, started_at, expected in (("stale", STALE, "started before its plan was committed"),
                                           ("unstamped", None, "record no start time")):
            measured = fixture.measurements(fixture.confirmation, f"{name}/measurements", injection_set=injection,
                                            started_at=started_at)
            self.assertIn(expected, self.confirmation_scores("test.level@1", measurements=measured,
                                                             injection_set=injection, positive_measurements=measured,
                                                             expect=2), name)
        self.no_ledger()

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


T2_FLAGS = ("--injection-catalog-seed", "7", "--injection-sample-seed", "1", "--injection-sample-per-cell", "150",
            "--injection-classes", "I", "--injection-catalog-version", "1")
CALIBRATION_VOICES = ("aiden", "serena", "design-calm")
CONFIRMATION_VOICES = ("ryan", "vivian", "design-warm")


class TakesFixture:
    """Two N3 take-plan splits over the three fixture languages (25 families each), their Stage 0 measurements
    with engine introspection, and a declared T2 (P2) injection set over the confirmation split."""

    def __init__(self, fixture: Fixture, *, per_language: int = 25) -> None:
        self.fixture = fixture
        self.root = fixture.root / "n3"
        self.per_language = per_language
        self.calibration = self.manifest("calibration", "c", CALIBRATION_VOICES)
        self.confirmation = self.manifest("confirmation", "t", CONFIRMATION_VOICES)

    def manifest(self, split: str, tag: str, voices: tuple[str, ...], *, long_form: bool = False,
                 name: str | None = None) -> Path:
        takes = []
        for language in LANGUAGES:
            for index in range(self.per_language):
                voice = voices[index % len(voices)]
                block = {"kind": "design", "briefID": voice.removeprefix("design-"), "brief": "A calm voice."} \
                    if voice.startswith("design-") else {"kind": "builtin", "id": voice}
                script = f"{tag}{language[:2]}{index:03d}"
                take_id = f"{script}--{voice}"
                take = {"takeID": take_id, "family": f"{script}:{voice}:7", "scriptID": script,
                        "language": language, "voice": block, "seed": 7, "status": "generated",
                        "wavSHA256": sha(f"wav:{take_id}"), "textSHA256": sha(REFERENCE)}
                if long_form:
                    take["longForm"] = {"schemaVersion": 1, "algorithmVersion": 4, "sampleRate": 24_000,
                                        "segmentCount": 2, "outputFrameCount": 96_000,
                                        "maximumSegmentBoundaryJump": 12, "seamFrames": [48_000]}
                takes.append(take)
        manifest = signed({"schemaVersion": 1, "kind": calibration.N3_KIND, "runID": f"run-{split}",
                           "split": split, "takes": takes})
        return write_json(self.root / (name or split) / "takes-manifest.json", manifest)

    @staticmethod
    def span(take_id: str) -> int:
        return int(take_id.split("--")[0][-3:]) % 10

    def injection_set(self, *, population: str = "P2", provenance: bool = True, name: str = "t2-set") -> Path:
        entries = []
        for take in self.fixture.takes(self.confirmation):
            for severity, kind in (("severe", population), ("sham", "S")):
                clip = f"{take['takeID']}__COD-LOOP__{severity}"
                injection = {"injectorID": "COD-LOOP", "injector": "COD-LOOP@1", "variant": severity,
                             "severity": severity, "catalogVersion": 1, "classes": ["I"],
                             "mechanism": "T2-codec-construction", "population": kind,
                             "sourcePCMSHA256": sha(f"pcm:{take['takeID']}"), "outputPCMSHA256": sha(f"pcm:{clip}")}
                if provenance:
                    injection["provenance"] = {"tier": "T2", "traceSHA256": sha(f"trace:{take['takeID']}"),
                                               "recipeSHA256": sha(f"recipe:{clip}"), "decoderSHA256": sha("decoder")}
                entries.append({"takeID": clip, "sourceTakeID": take["takeID"], "family": take["family"],
                                "language": take["language"], "textSHA256": take["textSHA256"],
                                "wavSHA256": sha(f"wav:{clip}"), "injection": injection})
        return write_json(self.root / name / "injection-set.json", {
            "kind": calibration.INJECTION_SET_KIND, "schemaVersion": 1,
            "sourceManifest": {"sha256": calibration.file_sha256(self.confirmation), "kind": calibration.N3_KIND},
            "catalogVersion": 1, "catalogSeed": 7, "classes": ["I"], "sampling": {"perCell": 150, "seed": 1},
            "entries": entries, "entriesSHA256": json_digest(entries)})

    def measurements(self, cohort: Path, name: str, *, injection_set: Path | None = None) -> Path:
        clips = []
        for take in self.fixture.takes(cohort):
            # Clean confirmation takes loop half as long, so none reaches the calibration tail.
            span = self.span(take["takeID"]) // (2 if cohort == self.confirmation else 1)
            clips.append({"clipID": take["takeID"], "population": "N3", "family": take["family"],
                          "sourceTakeID": take["takeID"], "language": take["language"], "injection": None,
                          "wavSHA256": take["wavSHA256"], "fastQC": {}, "observations": {},
                          "introspection": {"codecFrameCount": 90, "tokenCycleSpanFrames": span or None}})
        entries = self.fixture.entries(injection_set) if injection_set is not None else []
        for entry in entries:
            injection = entry["injection"]
            looped = injection["severity"] == "severe"
            clips.append({"clipID": entry["takeID"], "population": injection["population"], "family": entry["family"],
                          "sourceTakeID": entry["sourceTakeID"], "language": entry["language"],
                          "wavSHA256": entry["wavSHA256"],
                          "injection": {key: injection[key] for key in ("injector", "injectorID", "variant", "severity",
                                                                         "classes", "outputPCMSHA256")},
                          "fastQC": {}, "observations": {},
                          "introspection": {"codecFrameCount": 90, "tokenCycleSpanFrames": 64 if looped else None}})
        return write_json(self.root / f"{name}.json", {
            "kind": calibration.MEASUREMENTS_KIND, "schemaVersion": 1, "startedAt": FRESH,
            "subject": {"detector": "fastqc@8", "mirror": "fastqc-v8-numpy/1"},
            "takesManifestSHA256": calibration.file_sha256(cohort),
            "entriesSHA256": json_digest(entries) if injection_set is not None else None,
            "clipsSHA256": json_digest(clips), "clips": clips})


def labelled_cohort(fixture: Fixture, name: str, tag: str, split: str, speakers: tuple[str, ...], *,
                    corpus: str = "test-speakers") -> tuple[Path, Path]:
    """A speaker-labelled N2 cohort and the N1 manifest it pins (its split, corpus and speaker labels)."""
    n1_takes, n2_takes = [], []
    for language in LANGUAGES:
        for index in range(fixture.per_language):
            n1_id, take_id = f"n1-{tag}-{language[:2]}-{index:03d}", f"{tag}-{language[:2]}-{index:03d}--n2"
            family, script = f"{tag}-{language}-{index}", f"corpus-{tag}{index % 12}"
            n1_takes.append({"takeID": n1_id, "family": family, "scriptID": script, "language": language,
                             "speaker": f"{language[:2]}-{speakers[index % len(speakers)]}", "eligible": True,
                             "wavSHA256": sha(f"n1:{n1_id}"), "textSHA256": sha(REFERENCE)})
            n2_takes.append({"takeID": take_id, "n1TakeID": n1_id, "family": family, "scriptID": script,
                             "language": language, "eligible": True, "population": "N2",
                             "wavSHA256": sha(f"wav:{take_id}"), "textSHA256": sha(REFERENCE)})
    n1 = write_json(fixture.root / f"{name}-n1.json", signed({
        "kind": calibration.N1_KIND, "schemaVersion": 1, "population": "N1", "split": split,
        "corpus": corpus, "takes": n1_takes}))
    n2 = write_json(fixture.root / name / "n2-manifest.json", signed({
        "kind": calibration.N2_KIND, "schemaVersion": 1, "runID": f"run-{name}",
        "n1ManifestSHA256": calibration.file_sha256(n1), "takes": n2_takes}))
    return n2, n1


class RoleSetCohortTests(unittest.TestCase):
    """Plans, scores and confirmations over the role sets beyond FLEURS: N3 take splits with declared P2
    positives, speaker-labelled N2 and pending long-form corpora."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.fixture = Fixture(Path(self.directory.name))
        self.takes = TakesFixture(self.fixture)
        self.out = self.fixture.root / "out"

    def tearDown(self) -> None:
        self.directory.cleanup()

    def cli(self, *argv: str, expect: int = 0) -> str:
        code, out, err = run("--repo-root", str(self.fixture.repo), *argv)
        self.assertEqual(code, expect, f"{argv[0]}: {err}")
        return out + err

    def scores(self, detector: str, role: str, cohort: Path, name: str, *extra: str, expect: int = 0) -> Path | str:
        output = self.out / f"{name}.json"
        text = self.cli("scores", "--detector", detector, "--role", role, "--cohort", str(cohort),
                        "--output", str(output), *extra, expect=expect)
        return output if expect == 0 else text

    def plan(self, detector: str, calibration_cohort: Path, confirmation_cohort: Path, scores: Path, *extra: str,
             flags: tuple[str, ...] = T2_FLAGS, expect: int = 0) -> str:
        return self.cli("plan", "--detector", detector, "--calibration-cohort", str(calibration_cohort),
                        "--confirmation-cohort", str(confirmation_cohort), "--calibration-scores", str(scores),
                        "--alpha", "0.05", *flags, *extra, expect=expect)

    def calibrated(self) -> Path:
        takes = self.takes
        return self.scores("test.token-loop@1", "calibration", takes.calibration, "loop-calibration",
                           "--measurements", str(takes.measurements(takes.calibration, "cal-measurements")))

    def test_n3_take_splits_plan_score_and_confirm_with_declared_p2_positives(self) -> None:
        takes = self.takes
        scores = self.calibrated()
        document = json.loads(scores.read_text(encoding="utf-8"))
        self.assertEqual((document["cohort"]["split"], document["cohort"]["fleursSplit"]), ("calibration", None))
        self.assertEqual({unit["speaker"] for unit in document["units"]},
                         {"voice:aiden", "voice:serena", "voice:design-calm"})
        # The confirmation split is never scored for calibration or information (A5), plan or no plan.
        confirmation_measurements = takes.measurements(takes.confirmation, "early-measurements")
        for role in ("calibration", "informational"):
            self.assertIn("the confirmation split is the confirmation corpus", self.scores(
                "test.token-loop@1", role, takes.confirmation, f"early-{role}", "--measurements",
                str(confirmation_measurements), expect=2))
        # A P2 construction names its catalog version: this repository has no T2 catalog.
        self.assertIn("--injection-catalog-version", self.plan(
            "test.token-loop@1", takes.calibration, takes.confirmation, scores, flags=INJECTION_FLAGS, expect=2))
        self.plan("test.token-loop@1", takes.calibration, takes.confirmation, scores)
        plan_file = self.fixture.repo / "config/audio-qc-preregistrations/test.token-loop@1.json"
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
        self.assertEqual(plan["split"]["disjointBy"], ["family", "script", "speaker"])
        self.assertEqual(plan["split"]["speakers"], {"unit": "vocello-voice", "claim": "identified"})
        self.assertEqual((plan["split"]["calibration"]["source"], plan["split"]["confirmation"]["kind"]),
                         ("vocello-takes-calibration", calibration.N3_KIND))
        self.assertEqual((plan["population"], plan["bindings"]["injectorCatalogVersion"],
                          plan["bindings"]["injectionClasses"]), ("N3", "1", "I"))
        self.fixture.commit_plans()
        injection = takes.injection_set()
        measured = takes.measurements(takes.confirmation, "t2-measurements", injection_set=injection)
        # An injection set of P1 is not this role set's, and a P2 names its provenance.
        p1 = takes.injection_set(population="P1", name="p1-set")
        self.assertIn("an injection is P2 or S, not 'P1'", self.scores(
            "test.token-loop@1", "confirmation", takes.confirmation, "p1", "--injection-set", str(p1),
            "--measurements", str(takes.measurements(takes.confirmation, "p1-measurements", injection_set=p1)),
            "--positive-measurements", str(takes.measurements(takes.confirmation, "p1-positive", injection_set=p1)),
            expect=2))
        bare = takes.injection_set(provenance=False, name="bare-set")
        bare_measured = takes.measurements(takes.confirmation, "bare-measurements", injection_set=bare)
        self.assertIn("names its traceSHA256", self.scores(
            "test.token-loop@1", "confirmation", takes.confirmation, "bare", "--injection-set", str(bare),
            "--measurements", str(bare_measured), "--positive-measurements", str(bare_measured), expect=2))
        confirmation = self.scores("test.token-loop@1", "confirmation", takes.confirmation, "loop-confirmation",
                                   "--injection-set", str(injection), "--measurements", str(measured),
                                   "--positive-measurements", str(measured))
        units = json.loads(confirmation.read_text(encoding="utf-8"))["units"]
        positive = next(unit for unit in units if unit["population"] == "P2")
        self.assertEqual((positive["cell"], positive["provenance"]["tier"], positive["score"]),
                         ("COD-LOOP/severe", "T2", 64.0))
        self.assertIn("reports no N3 informational rate", self.cli(
            "confirm", "--detector", "test.token-loop@1", "--calibration-scores", str(scores),
            "--confirmation-scores", str(confirmation), "--n3-scores", str(scores), expect=2))
        result = json.loads(self.cli("confirm", "--detector", "test.token-loop@1", "--calibration-scores",
                                     str(scores), "--confirmation-scores", str(confirmation)))
        self.assertEqual((result["verdict"], result["reasons"]), ("qualified", []))
        record = json.loads((self.fixture.repo / result["record"]).read_text(encoding="utf-8"))
        self.assertEqual(calibration.record_errors(record), [])
        self.assertEqual(sorted(record["counts"]["confirmation"]), ["N3", "P2", "S"])
        self.assertEqual(record["counts"]["confirmation"]["P2"]["families"], 75)
        self.assertEqual(record["speakers"], {"unit": "vocello-voice", "claim": "identified", "count": 3})
        self.assertEqual(record["split"]["counts"]["speakers"], {"calibration": 3, "confirmation": 3})
        self.assertEqual(list(record["rates"]["mechanisms"]), ["T2-codec-construction"])
        self.cli("validate")

    def test_any_confirmation_split_stays_untouched_by_other_role_sets(self) -> None:
        takes = self.takes
        measured = takes.measurements(takes.confirmation, "n3-confirmation-measurements")
        self.assertIn("the confirmation split is a confirmation split", self.scores(
            "test.level@1", "informational", takes.confirmation, "fleurs-on-n3", "--measurements", str(measured),
            expect=2))
        self.scores("test.level@1", "informational", takes.calibration, "fleurs-on-n3-calibration",
                    "--measurements", str(takes.measurements(takes.calibration, "n3-calibration-measurements")))
        fixture = self.fixture
        self.assertIn("FLEURS test is a confirmation split", self.scores(
            "test.token-loop@1", "informational", fixture.confirmation, "n3-on-fleurs", "--n1-manifest",
            str(fixture.n1["confirmation"]), "--measurements",
            str(fixture.measurements(fixture.confirmation, "fleurs-test-measurements")), expect=2))

    def test_n3_splits_must_be_disjoint_by_speaker(self) -> None:
        takes = self.takes
        scores = self.calibrated()
        shared = takes.manifest("confirmation", "u", ("aiden", "vivian", "design-warm"), name="shared-voice")
        self.assertIn("share 1 speaker value", self.plan("test.token-loop@1", takes.calibration, shared, scores,
                                                        expect=2))
        swapped = takes.manifest("calibration", "v", CONFIRMATION_VOICES, name="calibration-as-confirmation")
        self.assertIn("the calibration split; the role set confirms on the confirmation split",
                      self.plan("test.token-loop@1", takes.calibration, swapped, scores, expect=2))
        self.assertFalse((self.fixture.repo / "config/audio-qc-preregistrations").exists())

    def test_a_pending_corpus_or_a_flat_long_form_cohort_is_not_plannable(self) -> None:
        takes = self.takes
        long_calibration = takes.manifest("calibration", "lc", CALIBRATION_VOICES, long_form=True, name="lf-cal")
        long_confirmation = takes.manifest("confirmation", "lt", CONFIRMATION_VOICES, long_form=True, name="lf-conf")
        scores = self.scores("test.long-loop@1", "calibration", long_calibration, "long-calibration",
                             "--measurements", str(takes.measurements(long_calibration, "lf-measurements")))
        seams = {unit["unitID"]: unit for unit in json.loads(scores.read_text(encoding="utf-8"))["units"]}
        self.assertEqual(len(seams), 75)
        self.assertIn("names no corpus yet for fit (pending-vocello-long-form-calibration)",
                      self.plan("test.long-loop@1", long_calibration, long_confirmation, scores,
                                flags=(*INJECTION_FLAGS, "--tier-catalog-version", "T2=1"), expect=2))
        # Its T2 target is a second construction tier: the plan binds that tier's catalog too.
        self.assertIn("reads T2 second-tier constructions", self.plan(
            "test.long-loop@1", long_calibration, long_confirmation, scores, flags=INJECTION_FLAGS, expect=2))
        # A long-form role set's cohorts are assembled projects with seams.
        registry = calibration.Repository(self.fixture.repo).registry()
        entry = detectors.detector_entry(registry, "test.long-loop@1")
        rule = calibration.cohort_rule(entry)
        roles = detectors.role_set(registry, entry)
        self.assertEqual(calibration.cohort_rule_problems(calibration.load_cohort(long_confirmation), rule, roles), [])
        flat = calibration.cohort_rule_problems(calibration.load_cohort(takes.confirmation), rule, roles)
        self.assertIn("75 takes of takes-manifest.json carry no long-form seam", flat[0])
        self.assertEqual(calibration.load_cohort(long_confirmation)["takes"]["lten000--ryan"]["seams"], [2.0])

    def test_a_speaker_labelled_corpus_names_its_speakers_and_proves_speaker_disjointness(self) -> None:
        fixture = self.fixture
        cal, cal_n1 = labelled_cohort(fixture, "lab-cal", "lc", "calibration", ("s1", "s2", "s3"))
        conf, conf_n1 = labelled_cohort(fixture, "lab-conf", "lt", "confirmation", ("s4", "s5", "s6"))
        self.assertIn("pass the N1 manifest", self.scores("test.labeled-level@1", "calibration", cal, "no-n1",
                                                          expect=2))
        scores = self.scores("test.labeled-level@1", "calibration", cal, "labelled", "--n1-manifest", str(cal_n1),
                             "--measurements", str(fixture.measurements(cal, "lab-measurements")))
        units = json.loads(scores.read_text(encoding="utf-8"))["units"]
        self.assertEqual(len({unit["speaker"] for unit in units}), 9)
        self.assertTrue(all(unit["speaker"].startswith("speaker:") and "s1" not in unit["speaker"] for unit in units))
        self.assertIn("--calibration-n1-manifest", self.plan("test.labeled-level@1", cal, conf, scores,
                                                             "--confirmation-n1-manifest", str(conf_n1),
                                                             flags=INJECTION_FLAGS, expect=2))
        # One confirmation speaker label is a calibration speaker's.
        shared, shared_n1 = labelled_cohort(fixture, "lab-shared", "ls", "confirmation", ("s1", "s5", "s6"))
        self.assertIn("share 3 speaker value", self.plan(
            "test.labeled-level@1", cal, shared, scores, "--confirmation-n1-manifest", str(shared_n1),
            "--calibration-n1-manifest", str(cal_n1), flags=INJECTION_FLAGS, expect=2))
        # Speakers are digests of (corpus, label): cohorts of two corpora would compare nothing.
        other, other_n1 = labelled_cohort(fixture, "lab-other", "lo", "confirmation", ("s4", "s5", "s6"),
                                          corpus="another-corpus")
        self.assertIn("name one corpus", self.plan(
            "test.labeled-level@1", cal, other, scores, "--confirmation-n1-manifest", str(other_n1),
            "--calibration-n1-manifest", str(cal_n1), flags=INJECTION_FLAGS, expect=2))
        self.plan("test.labeled-level@1", cal, conf, scores, "--confirmation-n1-manifest", str(conf_n1),
                  "--calibration-n1-manifest", str(cal_n1), flags=INJECTION_FLAGS)
        plan = json.loads((fixture.repo / "config/audio-qc-preregistrations/test.labeled-level@1.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual((plan["split"]["disjointBy"], plan["split"]["speakers"]),
                         (["family", "script", "speaker"], {"unit": "corpus-speaker", "claim": "identified"}))
        self.assertEqual(plan["split"]["calibration"]["source"], "test-speakers-calibration")
        # A take without a label is refused.
        document = json.loads(cal_n1.read_text(encoding="utf-8"))
        document["takes"][0].pop("speaker")
        unlabelled_n1 = write_json(fixture.root / "unlabelled-n1.json", signed(
            {key: value for key, value in document.items() if key != "manifestDigest"}))
        cohort = calibration.load_cohort(cal)
        cohort["n1ManifestSHA256"] = calibration.file_sha256(unlabelled_n1)
        with self.assertRaisesRegex(calibration.CalibrationError, "names no speaker"):
            calibration.resolve_cohort(cohort, unlabelled_n1)


FAIL_DETECTOR = "test.fail-level@1"
FAIL_FLAGS = ("--injection-catalog-seed", "7", "--injection-sample-seed", "1", "--injection-sample-per-cell", "150",
              "--injection-classes", "A,B,C,D,F")


def fail_level_entry() -> dict:
    """A pooled Stage 0 detector over every product language whose targets span two construction tiers with
    severe and moderate cells: what a fail point measures (A3)."""
    return {**level_entry(), "id": FAIL_DETECTOR, "scope": scope(ALL_LANGUAGES),
            "score": {"combination": "single", "unit": "dbfs", "groups": [
                {"languages": list(ALL_LANGUAGES), "components": [{"source": "fastqc", "field": "rmsDBFS"}]}]},
            "targets": [{"injectorID": "SIG-LEVEL", "severities": ["moderate", "severe"],
                         "mechanism": "T1-pcm-construction"},
                        {"injectorID": "COD-GAIN", "severities": ["moderate", "severe"],
                         "mechanism": "T2-codec-construction"}],
            "shams": [{"injectorID": "SIG-LEVEL", "mechanism": "T1-pcm-construction"},
                      {"injectorID": "COD-GAIN", "mechanism": "T2-codec-construction"}]}


class FailFixture(Fixture):
    """FLEURS-like N2 dev and test cohorts over the ten product languages at the fail floors (124 families
    each), an N3 bound cohort (60 per language), and a two-tier injection set (60 families per cell)."""

    def __init__(self, root: Path) -> None:
        super().__init__(root, per_language=124, positives_per_language=6)
        registry = json.loads((self.repo / calibration.REGISTRY).read_text(encoding="utf-8"))
        registry["detectors"].append(fail_level_entry())
        (self.repo / calibration.REGISTRY).write_text(json.dumps(registry, indent=2), encoding="utf-8")
        git(self.repo, "add", "config")
        git(self.repo, "commit", "-q", "--no-verify", "-m", "fail detector")

    def cohort(self, name: str, tag: str) -> Path:
        takes = []
        for language in ALL_LANGUAGES:
            for index in range(self.per_language):
                take_id = f"{tag}-{language[:2]}-{index:03d}--n2"
                takes.append({"takeID": take_id, "family": f"{tag}-{language}-{index}", "language": language,
                              "scriptID": f"flores-{tag}{index % 12}", "eligible": True, "population": "N2",
                              "wavSHA256": sha(f"wav:{take_id}"), "textSHA256": sha(REFERENCE)})
        manifest = signed({"kind": "audio-qc-n2-cohort", "schemaVersion": 1, "runID": f"run-{name}",
                           "n1ManifestSHA256": calibration.file_sha256(self.n1[name]), "takes": takes})
        return write_json(self.root / name / "n2-manifest.json", manifest)

    def n3_cohort(self, per_language: int = 60, *, split: str = "confirmation", name: str = "n3-bound") -> Path:
        takes = []
        for language in ALL_LANGUAGES:
            for index in range(per_language):
                voice = ("ryan", "vivian", "eric")[index % 3]
                take_id = f"b{language[:2]}{index:03d}--{voice}"
                takes.append({"takeID": take_id, "family": f"b{language[:2]}{index:03d}:{voice}:7",
                              "scriptID": f"b{language[:2]}{index:03d}", "language": language,
                              "voice": {"kind": "builtin", "id": voice}, "status": "generated",
                              "wavSHA256": sha(f"wav:{take_id}"), "textSHA256": sha(REFERENCE)})
        return write_json(self.root / name / "takes-manifest.json", signed(
            {"schemaVersion": 1, "kind": calibration.N3_KIND, "runID": f"run-{name}", "split": split,
             "takes": takes}))

    def fail_injection_set(self) -> Path:
        entries = []
        for take in self.takes(self.confirmation):
            if self.index(take["takeID"]) >= self.positives_per_language:
                continue
            for injector, mechanism, population in (("SIG-LEVEL", "T1-pcm-construction", "P1"),
                                                    ("COD-GAIN", "T2-codec-construction", "P2")):
                for severity in ("moderate", "severe", "sham"):
                    clip = f"{take['takeID']}__{injector}__{severity}"
                    kind = "S" if severity == "sham" else population
                    version = injectors.CATALOG_VERSION if mechanism.startswith("T1") else 1
                    injection = {"injectorID": injector, "injector": f"{injector}@1", "variant": severity,
                                 "catalogVersion": version, "severity": severity, "classes": ["A"],
                                 "mechanism": mechanism, "population": kind,
                                 "sourcePCMSHA256": sha(f"pcm:{take['takeID']}"), "outputPCMSHA256": sha(f"pcm:{clip}")}
                    if mechanism.startswith("T2"):
                        injection["provenance"] = {"tier": "T2", "traceSHA256": sha(f"trace:{clip}"),
                                                   "recipeSHA256": sha(f"recipe:{clip}"),
                                                   "decoderSHA256": sha("decoder")}
                    entries.append({"takeID": clip, "sourceTakeID": take["takeID"], "family": take["family"],
                                    "language": take["language"], "textSHA256": take["textSHA256"],
                                    "wavSHA256": sha(f"wav:{clip}"), "injection": injection})
        return write_json(self.root / "fail-set" / "injection-set.json", {
            "kind": calibration.INJECTION_SET_KIND, "schemaVersion": 1,
            "sourceManifest": {"sha256": calibration.file_sha256(self.confirmation), "kind": "audio-qc-n2-cohort"},
            "catalogVersion": injectors.CATALOG_VERSION, "catalogSeed": 7, "classes": ["A", "B", "C", "D", "F"],
            "sampling": {"perCell": 150, "seed": 1}, "entries": entries, "entriesSHA256": json_digest(entries)})

    def measurements(self, cohort: Path, name: str, *, injection_set: Path | None = None,
                     started_at: str | None = FRESH) -> Path:
        path = super().measurements(cohort, name, injection_set=injection_set, started_at=started_at)
        data = json.loads(path.read_text(encoding="utf-8"))
        for clip in data["clips"]:
            if clip["population"] in ("P1", "P2"):
                clip["fastQC"]["rmsDBFS"] = -70.0
            elif clip["population"] == "N3":
                clip["fastQC"]["rmsDBFS"] = -20.0
        data["clipsSHA256"] = json_digest(data["clips"])
        return write_json(path, data)

    def n3_measurements(self, cohort: Path, name: str) -> Path:
        clips = [{"clipID": take["takeID"], "population": "N3", "family": take["family"],
                  "sourceTakeID": take["takeID"], "language": take["language"], "injection": None,
                  "wavSHA256": take["wavSHA256"], "fastQC": {"rmsDBFS": -20.0}, "observations": {}}
                 for take in self.takes(cohort)]
        return write_json(self.root / f"{name}.json", {
            "kind": calibration.MEASUREMENTS_KIND, "schemaVersion": 1, "startedAt": FRESH,
            "subject": {"detector": "fastqc@8", "mirror": "fastqc-v8-numpy/1"},
            "takesManifestSHA256": calibration.file_sha256(cohort), "entriesSHA256": None,
            "clipsSHA256": json_digest(clips), "clips": clips})


class FailLevelTests(unittest.TestCase):
    """The fail operating point (decision 5): a fail plan beside the warn plan of one detector version, its N3
    bound, its floors and a fail record the lane gates accept."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        cls.template = FailFixture(Path(cls.directory.name) / "template")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def setUp(self) -> None:
        self.work = tempfile.TemporaryDirectory()
        root = Path(self.work.name) / "fixture"
        shutil.copytree(self.template.root, root)
        self.fixture = copy.copy(self.template)
        self.fixture.root, self.fixture.repo = root, root / "repo"
        self.fixture.n1 = {key: root / path.name for key, path in self.template.n1.items()}
        self.fixture.calibration = root / "calibration" / "n2-manifest.json"
        self.fixture.confirmation = root / "confirmation" / "n2-manifest.json"
        self.out = root / "out"

    def tearDown(self) -> None:
        self.work.cleanup()

    def cli(self, *argv: str, expect: int = 0) -> str:
        code, out, err = run("--repo-root", str(self.fixture.repo), *argv)
        self.assertEqual(code, expect, f"{argv[0]}: {err}")
        return out + err

    def scores(self, role: str, cohort: Path, name: str, *extra: str, n1: Path | None = None,
               detector: str = FAIL_DETECTOR, expect: int = 0) -> Path | str:
        output = self.out / f"{name}.json"
        text = self.cli("scores", "--detector", detector, "--role", role, "--cohort", str(cohort),
                        *(("--n1-manifest", str(n1)) if n1 else ()), "--output", str(output), *extra, expect=expect)
        return output if expect == 0 else text

    def plan(self, scores: Path, *extra: str, detector: str = FAIL_DETECTOR, expect: int = 0) -> str:
        fixture = self.fixture
        # The fail detector's COD-GAIN target is a second (T2) construction tier, bound by its own catalog version.
        tier = ("--tier-catalog-version", "T2=1") if detector == FAIL_DETECTOR else ()
        return self.cli("plan", "--detector", detector, "--calibration-cohort", str(fixture.calibration),
                        "--confirmation-cohort", str(fixture.confirmation), "--confirmation-n1-manifest",
                        str(fixture.n1["confirmation"]), "--calibration-scores", str(scores), *FAIL_FLAGS, *tier,
                        *extra, expect=expect)

    def calibrated(self, detector: str = FAIL_DETECTOR) -> Path:
        fixture = self.fixture
        return self.scores("calibration", fixture.calibration, f"{detector}-calibration", "--measurements",
                           str(fixture.measurements(fixture.calibration, f"cal-{detector}")),
                           n1=fixture.n1["calibration"], detector=detector)

    def test_a_fail_plan_needs_n2_two_mechanisms_every_language_and_its_n3_cohort(self) -> None:
        fixture = self.fixture
        n3 = fixture.n3_cohort()
        level = self.calibrated("test.level@1")
        refused = self.plan(level, "--alpha", "0.005", "--operating-point", "fail", "--n3-cohort", str(n3),
                            detector="test.level@1", expect=2)
        self.assertIn("its scope holds 3 languages; a fail bound covers 10", refused)
        self.assertIn("0 construction mechanisms declare severe and moderate cells (none); fail measures detection "
                      "on 2 (A3)", refused)
        scores = self.calibrated()
        self.assertIn("alpha must lie below the fail FAR bound 0.01",
                      self.plan(scores, "--alpha", "0.05", "--operating-point", "fail", "--n3-cohort", str(n3),
                                expect=2))
        self.assertIn("names the N3 cohort its flag rate is bounded on",
                      self.plan(scores, "--alpha", "0.005", "--operating-point", "fail", expect=2))
        self.assertIn("bounds no N3 flag rate", self.plan(scores, "--alpha", "0.05", "--n3-cohort", str(n3),
                                                           expect=2))
        # The calibration floor at fail is the confirmation's N2 negative floor (1240 pooled families).
        registry = calibration.Repository(fixture.repo).registry()
        policy = json.loads((REPO / calibration.POLICY).read_text(encoding="utf-8"))
        self.assertEqual(calibration.calibration_floor_of(policy["operatingPoints"]["fail"], None), 1240)
        self.assertEqual(calibration.calibration_floor_of(policy["operatingPoints"]["fail"], "language"), 124)
        self.assertEqual(calibration.calibration_floor_of(policy["operatingPoints"]["evidenceLaneFail"], None), 510)
        self.assertEqual(calibration.calibration_floor_of(policy["operatingPoints"]["warn"], "language"), 60)
        # A detector confirmed on N3 cannot qualify at fail: its FAR is not confirmed on N2 (A2).
        loop = detectors.detector_entry(registry, "test.token-loop@1")
        problems = calibration.fail_plan_problems(loop, detectors.role_set(registry, loop),
                                                  policy["operatingPoints"]["fail"])
        self.assertIn("the fail FAR is confirmed on N2 (A2); role set n3-codec-trace confirms on N3", problems)

    def test_fail_and_warn_plans_of_one_version_confirm_separately(self) -> None:
        fixture = self.fixture
        n3 = fixture.n3_cohort()
        scores = self.calibrated()
        self.plan(scores, "--alpha", "0.05")
        self.plan(scores, "--alpha", "0.005", "--operating-point", "fail", "--n3-cohort", str(n3))
        directory = fixture.repo / "config/audio-qc-preregistrations"
        warn_plan = json.loads((directory / f"{FAIL_DETECTOR}.json").read_text(encoding="utf-8"))
        fail_plan = json.loads((directory / f"{FAIL_DETECTOR}.fail.json").read_text(encoding="utf-8"))
        self.assertEqual((warn_plan["bindings"]["operatingPoint"], fail_plan["bindings"]["operatingPoint"]),
                         ("warn", "fail"))
        self.assertNotIn("n3CohortDigest", warn_plan["bindings"])
        self.assertEqual(fail_plan["bindings"]["n3CohortDigest"], calibration.load_cohort(n3)["manifestDigest"])
        self.assertEqual((warn_plan["bindings"]["injectorCatalogVersionT2"],
                          fail_plan["bindings"]["injectorCatalogVersion"]), ("1", str(injectors.CATALOG_VERSION)))
        self.assertIn("another fail plan", self.plan(scores, "--alpha", "0.004", "--operating-point", "fail",
                                                     "--n3-cohort", str(n3), expect=2))
        fixture.commit_plans()
        self.cli("validate")
        derived = json.loads(self.cli("derive", "--detector", FAIL_DETECTOR, "--calibration-scores", str(scores),
                                      "--operating-point", "fail"))
        self.assertEqual((derived["status"], derived["calibrationFloor"], derived["byStratum"]["pooled"]["rank"]),
                         ("derived", 1240, 1235))
        # The N3 bound is scored only under the fail plan, after it, and never for information.
        n3_measured = fixture.n3_measurements(n3, "n3-bound/measurements")
        self.assertIn("scored only under --role bound", self.scores(
            "informational", n3, "n3-info", "--measurements", str(n3_measured), expect=2))
        self.assertIn("pass --operating-point fail", self.scores(
            "bound", n3, "n3-warn", "--measurements", str(n3_measured), expect=2))
        self.assertIn("scored only under the fail plan", self.scores(
            "bound", n3, "n3-lane", "--measurements", str(n3_measured), "--operating-point", "evidenceLaneFail",
            expect=2))
        bound = self.scores("bound", n3, "n3-bound", "--measurements", str(n3_measured), "--operating-point", "fail")
        injection = fixture.fail_injection_set()
        measured = fixture.measurements(fixture.confirmation, "confirmation/measurements", injection_set=injection)
        confirmation = self.scores("confirmation", fixture.confirmation, "fail-confirmation", "--measurements",
                                   str(measured), "--injection-set", str(injection), "--positive-measurements",
                                   str(measured), "--operating-point", "fail", n1=fixture.n1["confirmation"])
        document = json.loads(confirmation.read_text(encoding="utf-8"))
        self.assertEqual(document["counts"]["byPopulation"], {"N2": 1240, "P1": 120, "P2": 120, "S": 120})
        arguments = ("confirm", "--detector", FAIL_DETECTOR, "--calibration-scores", str(scores),
                     "--confirmation-scores", str(confirmation), "--operating-point", "fail")
        self.assertIn("pass --n3-scores", self.cli(*arguments, expect=2))
        self.assertIn("not this detector's N3 bound scores", self.cli(*arguments, "--n3-scores", str(scores), expect=2))
        result = json.loads(self.cli(*arguments, "--n3-scores", str(bound)))
        self.assertEqual((result["verdict"], result["reasons"]), ("qualified", []))
        record = json.loads((fixture.repo / result["record"]).read_text(encoding="utf-8"))
        self.assertEqual(calibration.record_errors(record), [])
        self.assertEqual((record["operatingPoint"], record["level"]), ("fail", "fail"))
        self.assertEqual((record["rates"]["n3"]["units"], record["rates"]["n3"]["meets"]), (600, True))
        self.assertEqual(record["cohorts"]["n3"]["scoresSHA256"], json.loads(bound.read_text())["scoresSHA256"])
        self.assertEqual(sorted(record["counts"]["confirmation"]), ["N2", "N3", "P1", "P2", "S"])
        self.assertEqual(record["rates"]["mechanismsMeeting"], ["T1-pcm-construction", "T2-codec-construction"])
        self.assertEqual([panel["cohort"] for panel in record["evidence"]["confirmationPanels"]], [])
        self.assertIn("once", self.cli(*arguments, "--n3-scores", str(bound), expect=2))
        # The warn plan confirms on its own, once, into its own record.
        warn = json.loads(self.cli("confirm", "--detector", FAIL_DETECTOR, "--calibration-scores", str(scores),
                                   "--confirmation-scores", str(confirmation)))
        warn_record = json.loads((fixture.repo / warn["record"]).read_text(encoding="utf-8"))
        self.assertEqual((warn_record["level"], "n3" in warn_record["rates"]), ("warn", False))
        self.assertNotEqual(warn["record"], result["record"])
        self.cli("validate")
        # Both plans confirmed: their confirmation and N3 cohorts are spent for any later plan (A5).
        self.assertIn("already scored as confirmation evidence", self.plan(
            scores, "--alpha", "0.004", "--operating-point", "evidenceLaneFail", "--n3-cohort", str(n3), expect=2))
        self.assertIn(f"{FAIL_DETECTOR} (fail)", self.cli("report"))
        # A fail record without its N3 bound, or a warn record with one, is refused.
        for mutation, fragment in ((lambda value: value["rates"].pop("n3"), "carries its N3 bound"),
                                   (lambda value: value.update(level="warn"), "level is fail")):
            broken = copy.deepcopy(record)
            mutation(broken)
            self.assertTrue(any(fragment in error for error in calibration.record_errors(broken)), fragment)
        broken = copy.deepcopy(warn_record)
        broken["rates"]["n3"] = record["rates"]["n3"]
        self.assertIn("a warn record carries no N3 bound", calibration.record_errors(broken))

    def test_a_warn_record_pins_its_informational_n3_cohort(self) -> None:
        fixture = self.fixture
        informational = fixture.n3_cohort(split="calibration", name="n3-informational")
        scores = self.calibrated()
        self.plan(scores, "--alpha", "0.05")
        fixture.commit_plans()
        n3_scores = self.scores("informational", informational, "n3-informational", "--measurements",
                                str(fixture.n3_measurements(informational, "n3-informational/measurements")))
        injection = fixture.fail_injection_set()
        measured = fixture.measurements(fixture.confirmation, "confirmation/measurements", injection_set=injection)
        confirmation = self.scores("confirmation", fixture.confirmation, "warn-confirmation", "--measurements",
                                   str(measured), "--injection-set", str(injection), "--positive-measurements",
                                   str(measured), n1=fixture.n1["confirmation"])
        result = json.loads(self.cli("confirm", "--detector", FAIL_DETECTOR, "--calibration-scores", str(scores),
                                     "--confirmation-scores", str(confirmation), "--n3-scores", str(n3_scores)))
        record = json.loads((fixture.repo / result["record"]).read_text(encoding="utf-8"))
        digest = calibration.load_cohort(informational)["manifestDigest"]
        self.assertEqual(record["informational"]["manifestDigest"], digest)
        self.assertEqual(calibration.record_errors(record), [])
        spent = calibration.declared_cohorts(calibration.Repository(fixture.repo))["spent"]
        self.assertEqual((spent[digest], spent[calibration.load_cohort(fixture.confirmation)["manifestDigest"]]),
                         ([FAIL_DETECTOR], [FAIL_DETECTOR]))

    def test_the_fail_floors_hold_before_the_confirmation_starts(self) -> None:
        fixture = self.fixture
        n3 = fixture.n3_cohort(per_language=59)
        scores = self.calibrated()
        self.plan(scores, "--alpha", "0.005", "--operating-point", "fail", "--n3-cohort", str(n3))
        fixture.commit_plans()
        bound = self.scores("bound", n3, "n3-bound", "--measurements",
                            str(fixture.n3_measurements(n3, "n3-bound/measurements")), "--operating-point", "fail")
        fixture.positives_per_language = 5
        injection = fixture.fail_injection_set()
        measured = fixture.measurements(fixture.confirmation, "confirmation/measurements", injection_set=injection)
        confirmation = self.scores("confirmation", fixture.confirmation, "short", "--measurements", str(measured),
                                   "--injection-set", str(injection), "--positive-measurements", str(measured),
                                   "--operating-point", "fail", n1=fixture.n1["confirmation"])
        message = self.cli("confirm", "--detector", FAIL_DETECTOR, "--calibration-scores", str(scores),
                           "--confirmation-scores", str(confirmation), "--operating-point", "fail", "--n3-scores",
                           str(bound), expect=2)
        self.assertIn("T1-pcm-construction SIG-LEVEL/moderate: 50 scored positive families, the fail floor is 60",
                      message)
        self.assertIn("COD-GAIN: 50 scored sham families, the fail floor is 60 (A4)", message)
        self.assertIn("english: 59 scored N3 families, the fail floor is 60 (A2)", message)
        self.assertFalse(list((fixture.repo / "config/audio-qc-preregistrations").glob("confirmation-*")))


class RawOutputAndReferenceTests(unittest.TestCase):
    """A `raw-output` detector reads exported raw outputs bound to its manifest, bundle and evidence; a speaker
    detector requires the panel to have embedded the reference clip each take declares."""

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

    def pitch_bundle(self, name: str, cohort: Path | None = None) -> Path:
        fixture = self.fixture
        rows = [(take["takeID"], take["language"], take["wavSHA256"], take["textSHA256"],
                 {PYIN: {"voicedFraction": 0.8}}, None) for take in fixture.takes(cohort or fixture.calibration)]
        return fixture.bundle(fixture.root / name, rows, judgeMetrics=judge_metrics(PYIN))

    def export(self, cohort: Path, bundle: Path, name: str, *, missing: tuple[str, ...] = (),
               identity: str = IDENTITY["pitch.pyin@1"]) -> Path:
        """What `audio_qc_calibration_set.py raw-outputs` writes: each take's pYIN track, a step of index % 7
        semitones between two held pitches."""
        takes = {}
        for take in self.fixture.takes(cohort):
            base = {"language": take["language"], "audioSHA256": take["wavSHA256"]}
            if take["takeID"] in missing:
                takes[take["takeID"]] = {**base, "status": "not-in-cache"}
                continue
            step = self.fixture.index(take["takeID"]) % 7
            f0 = [200.0] * 40 + [200.0 * 2 ** (step / 12)] * 40
            takes[take["takeID"]] = {**base, "status": "complete", "outputIdentity": identity,
                                     "output": {"hopSeconds": 0.01, "f0Hz": f0, "voiced": [True] * 80}}
        digest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))["bundleDigest"]
        return write_json(self.fixture.root / "raw" / name, {
            "schemaVersion": 1, "kind": calibration.RAW_OUTPUTS_KIND,
            "takesManifest": {"sha256": calibration.file_sha256(cohort)}, "bundle": {"bundleDigest": digest},
            "judge": {"judge": PYIN}, "takes": takes, "takesSHA256": json_digest(takes)})

    def scores(self, name: str, *extra: str, detector: str = "test.pitch-break@1", expect: int = 0) -> Path | str:
        output = self.out / f"{name}.json"
        text = self.cli("scores", "--detector", detector, "--role", "calibration", "--cohort",
                        str(self.fixture.calibration), "--n1-manifest", str(self.fixture.n1["calibration"]),
                        "--output", str(output), *extra, expect=expect)
        return output if expect == 0 else text

    def test_raw_output_scores_come_from_a_bound_export(self) -> None:
        fixture = self.fixture
        bundle = self.pitch_bundle("pitch-bundle")
        first = fixture.takes(fixture.calibration)[0]["takeID"]
        export = self.export(fixture.calibration, bundle, "raw.json", missing=(first,))
        scores = json.loads(self.scores("pitch", "--bundle", str(bundle), "--raw-outputs", str(export))
                            .read_text(encoding="utf-8"))
        units = {unit["unitID"]: unit for unit in scores["units"]}
        self.assertEqual(units[first]["abstain"], "no-raw-output")
        take = fixture.takes(fixture.calibration)[5]["takeID"]
        self.assertAlmostEqual(units[take]["score"], 5.0, places=6)
        self.assertEqual(scores["sources"]["rawOutputs"],
                         [{"judge": PYIN, "fileSHA256": calibration.file_sha256(export),
                           "takesSHA256": json.loads(export.read_text(encoding="utf-8"))["takesSHA256"],
                           "bundleDigest": json.loads((bundle / "bundle.json").read_text())["bundleDigest"]}])
        # A missing raw output is an evidence gap: the plan refuses scores that have one.
        self.assertIn("have no evidence ({'no-raw-output': 1})", self.cli(
            "plan", "--detector", "test.pitch-break@1", "--calibration-cohort", str(fixture.calibration),
            "--confirmation-cohort", str(fixture.confirmation), "--confirmation-n1-manifest",
            str(fixture.n1["confirmation"]), "--calibration-scores", str(self.out / "pitch.json"), "--alpha",
            "0.05", *INJECTION_FLAGS, expect=2))
        # The export is required, and bound to the manifest, the bundle and the evidence's output identity.
        self.assertIn("reduces the raw output of pitch.pyin@1", self.scores("none", "--bundle", str(bundle),
                                                                            expect=2))
        other_bundle = self.pitch_bundle("other-bundle")
        self.assertIn("another panel bundle", self.scores(
            "moved", "--bundle", str(other_bundle), "--raw-outputs", str(export), expect=2))
        foreign = self.export(fixture.confirmation, bundle, "foreign.json")
        self.assertIn("exported for another manifest", self.scores(
            "foreign", "--bundle", str(bundle), "--raw-outputs", str(foreign), expect=2))
        stranger = self.export(fixture.calibration, bundle, "stranger.json", identity="e" * 64)
        self.assertIn("of another identity than its evidence", self.scores(
            "stranger", "--bundle", str(bundle), "--raw-outputs", str(stranger), expect=2))
        self.assertIn("reduces no judge's raw output", self.scores(
            "level", "--measurements", str(fixture.measurements(fixture.calibration, "level-measurements")),
            "--raw-outputs", str(export), detector="test.level@1", expect=2))

    def test_a_speaker_detector_scores_only_against_the_declared_reference_clip(self) -> None:
        fixture = self.fixture
        entry = {**pitch_entry(), "id": "test.similarity@1", "class": "E", "stage": 2, "direction": "below",
                 "score": {"combination": "single", "unit": "cosine", "groups": [
                     {"languages": list(LANGUAGES), "components": [{"source": "panel", "judge": CAMPPLUS,
                                                                     "metric": "cosine"}]}]}}
        manifest = json.loads(fixture.calibration.read_text(encoding="utf-8"))
        manifest.pop("manifestDigest")
        for take in manifest["takes"]:
            take["reference"] = {"takeID": f"{take['takeID']}-ref", "wavPath": f"ref/{take['takeID']}.wav",
                                 "wavSHA256": sha(f"ref:{take['takeID']}")}
        referenced = write_json(fixture.root / "referenced" / "n2-manifest.json", signed(manifest))
        cohort = calibration.load_cohort(referenced)

        def bundle(name: str, reference) -> Path:
            rows = []
            for take in manifest["takes"]:
                private = {"referenceText": REFERENCE, "transcripts": {}}
                embedded = reference(take)
                if embedded is not None:
                    private["referenceAudioSHA256"] = embedded
                rows.append((take["takeID"], take["language"], take["wavSHA256"], take["textSHA256"],
                             {CAMPPLUS: {"cosine": 0.81}}, private))
            return fixture.bundle(fixture.root / name, rows)

        def score(directory: Path, source: dict = cohort) -> dict:
            return calibration.build_scores(entry, source, role="informational", split="dev",
                                            bundle=calibration.Bundle(directory))

        scored = score(bundle("embedded", lambda take: take["reference"]["wavSHA256"]))
        self.assertEqual({unit["score"] for unit in scored["units"]}, {0.81})
        for name, reference, fragment in (("absent", lambda take: None, "did not embed"),
                                          ("other", lambda take: sha("another clip"), "another reference clip")):
            with self.assertRaisesRegex(calibration.CalibrationError, fragment):
                score(bundle(name, reference))
        with self.assertRaisesRegex(calibration.CalibrationError, "does not declare"):
            score(bundle("undeclared", lambda take: sha("a clip")), calibration.load_cohort(fixture.calibration))
        manifest.pop("manifestDigest")
        manifest["takes"][0]["reference"]["wavSHA256"] = manifest["takes"][0]["wavSHA256"]
        with self.assertRaisesRegex(calibration.CalibrationError, "never its own reference"):
            calibration.load_cohort(write_json(fixture.root / "self" / "n2-manifest.json", signed(manifest)))


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
