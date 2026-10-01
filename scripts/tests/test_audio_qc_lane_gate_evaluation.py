#!/usr/bin/env python3
"""AQ-07 lane gate enforcement: a lane run's takes scored against each gating detector's qualified record.

Runs on a copy of the docs generator's fixture repository (`fixtures/audio_qc_docs/repo`), whose language bench
is gated at warn by `content.consensus-error@1` (thresholds 0.0931 en, 0.0812 fr, 0.1175 de), extended with a
run-on-shaped detector (a PCM measure minus the aligner's end, gated on both content voters) on the language bench
and a CAM++ similarity detector on the clone lane, each behind a qualified record. Panel bundles and Stage 0
measurements are fixtures bound by the digests the scoring code checks; no model runs.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
from io import StringIO
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_calibration_set  # noqa: E402
import audio_qc_detector_calibration as calibration  # noqa: E402
import audio_qc_lane_gates as gates  # noqa: E402
import audio_qc_orchestrator as orchestrator  # noqa: E402
import language_bench_evidence  # noqa: E402
from lib.jsonio import sha256_json  # noqa: E402
from lib.language_metrics import text_sha256  # noqa: E402
from lib.qc_pipeline.evidence import privacy_errors  # noqa: E402
from lib.qc_qualification import detectors as registry_lib  # noqa: E402
from lib.qc_qualification.pcm import json_digest  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "audio_qc_docs" / "repo"
CONTENT, RUNON, SIMILARITY = "content.consensus-error@1", "boundary.lane-run-on@1", "identity.lane-similarity@1"
WHISPER, PARAKEET = "asr.whisper-large-v3@1", "asr.parakeet-tdt-0.6b-v3@1"
ALIGNER, CAMPP = "align.qwen3-forcedaligner-0.6b@1", "speaker.campplus-voxceleb@1"
IDENTITY = {WHISPER: "a" * 64, PARAKEET: "b" * 64, ALIGNER: "e" * 64, CAMPP: "d" * 64}
LANGUAGES = ("english", "french", "german")
ORCHESTRATOR_SHA = "c" * 64
TEXT = {"english": "one two three four five six seven eight nine ten",
        "french": "un deux trois quatre cinq six sept huit neuf dix",
        "german": "eins zwei drei vier fuenf sechs sieben acht neun zehn",
        "spanish": "uno dos tres cuatro cinco seis siete ocho nueve diez"}
STAGE0_SUBJECT = {"detector": "fastqc@8", "mirror": "fastqc-v8-numpy/1"}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def judge_metrics(judge: str) -> dict:
    return {"definition": f"fixture-metrics:{judge}", "sourcesSHA256": sha(judge)}


def run_on_entry() -> dict:
    return {
        "id": RUNON, "class": "C", "stage": 2, "measures": "Active audio after the aligner's script end.",
        "score": {"combination": "difference", "unit": "seconds", "groups": [
            {"languages": list(LANGUAGES), "components": [{"source": "pcm", "field": "lastActiveSeconds"},
                                                          {"source": "panel", "judge": ALIGNER,
                                                           "metric": "spanEndSeconds"}],
             "requiresComplete": [WHISPER, PARAKEET]}]},
        "direction": "above", "strata": {"by": "language", "reason": "The aligner's end differs by language."},
        "scope": {"languages": list(LANGUAGES), "exclusions": []},
        "targets": [], "shams": [], "populations": "fleurs-n2", "limitations": [], "risks": [],
    }


def similarity_entry() -> dict:
    return {
        "id": SIMILARITY, "class": "E", "stage": 2, "measures": "CAM++ cosine of the take to its reference clip.",
        "score": {"combination": "single", "unit": "cosine", "groups": [
            {"languages": ["english"], "components": [{"source": "panel", "judge": CAMPP, "metric": "cosine"}]}]},
        "direction": "below", "strata": {"by": "language", "reason": "Speaker scores shift with language."},
        "scope": {"languages": ["english"], "exclusions": []},
        "targets": [], "shams": [], "populations": "fleurs-n2", "limitations": [], "risks": [],
    }


def write_json(path: Path, value) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


class GateFixture(unittest.TestCase):
    """A fixture repository whose language bench gates on CONTENT and RUNON and whose clone lane on SIMILARITY,
    each behind a qualified warn record whose evidence identity is what the fixture panels record."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.root = self.base / "repo"
        shutil.copytree(FIXTURE, self.root)
        self.run_dir = self.base / "build" / "run"
        self.run_dir.mkdir(parents=True)
        registry_path = self.root / calibration.REGISTRY
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        registry["detectors"] += [run_on_entry(), similarity_entry()]
        write_json(registry_path, registry)
        content = next((self.root / calibration.RECORDS / CONTENT).glob("record-*.json"))
        self.records = {CONTENT: content.relative_to(self.root).as_posix()}
        # The fixture's own record, re-stamped with the evidence identity its lane panels carry.
        self.edit(self.records[CONTENT], lambda record: record["evidence"].update(
            scoringCodeSHA256=registry_lib.scoring_code_sha256(), orchestratorSHA256=[ORCHESTRATOR_SHA],
            judgeMetrics={judge: [judge_metrics(judge)] for judge in (WHISPER, PARAKEET)}))
        template = json.loads(content.read_text(encoding="utf-8"))
        self.records[RUNON] = self.forge(template, run_on_entry(), {"english": 0.5, "french": 0.3, "german": 0.8},
                                         (WHISPER, PARAKEET, ALIGNER, registry_lib.STAGE0_JUDGE))
        self.records[SIMILARITY] = self.forge(template, similarity_entry(), {"english": 0.5}, (CAMPP,))

        def lanes(config: dict) -> None:
            config["lanes"]["language-bench"]["gates"] = [{"detector": CONTENT, "level": "warn"},
                                                          {"detector": RUNON, "level": "warn"}]
            config["lanes"]["clone-lane"]["gates"] = [{"detector": SIMILARITY, "level": "warn"}]
        self.edit(gates.GATES, lanes)
        self.assertEqual(gates.lane_gate_errors(self.root), [])

    def tearDown(self) -> None:
        self.temporary.cleanup()

    # -- the repository ----------------------------------------------------------
    def edit(self, relative: str, change) -> None:
        path = self.root / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        change(value)
        write_json(path, value)

    def forge(self, template: dict, entry: dict, values: dict, judges: tuple[str, ...]) -> str:
        """A qualified warn record of `entry` (the fixture record's rates and cohorts), with its own thresholds."""
        record = copy.deepcopy(template)
        stage0_identity = json_digest(STAGE0_SUBJECT)
        record.update({
            "detector": entry["id"], "class": entry["class"], "stage": entry["stage"],
            "direction": entry["direction"], "combination": entry["score"]["combination"],
            "detectorDefinitionSHA256": registry_lib.definition_digest(entry), "planSHA256": sha(entry["id"]),
            "judges": [{"judge": judge, "outputIdentities": [IDENTITY.get(judge, stage0_identity)]}
                       for judge in sorted(judges)],
            "phiAudit": [], "scope": {"languages": list(values), "exclusions": []}})
        record["threshold"].update(values=dict(values), calibrationUnits={key: 120 for key in values},
                                   ranks={key: 114 for key in values})
        record["evidence"].update(scoringCodeSHA256=registry_lib.scoring_code_sha256(),
                                  orchestratorSHA256=[ORCHESTRATOR_SHA],
                                  judgeMetrics={judge: [judge_metrics(judge)] for judge in judges if judge in IDENTITY})
        path = self.root / calibration.RECORDS / entry["id"] / f"record-{record['planSHA256'][:16]}.json"
        write_json(path, record)
        return path.relative_to(self.root).as_posix()

    # -- a lane run ----------------------------------------------------------------
    def wav(self, take_id: str, directory: Path | None = None) -> Path:
        path = (directory or self.run_dir / "wav") / f"{take_id}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"RIFF fixture audio of {take_id}".encode("utf-8"))
        return path

    def takes(self, *specs: tuple, lane: str = "language-bench", **extra) -> Path:
        """specs: (takeID, language, mode) or (takeID, language, mode, {take fields}); writes the lane takes."""
        takes = []
        for spec in specs:
            take_id, language, mode = spec[:3]
            fields = spec[3] if len(spec) > 3 else {}
            takes.append({"takeID": take_id, "wav": self.wav(take_id), "language": language, "mode": mode,
                          "text": TEXT[language], **fields})
        return gates.write_lane_takes(lane, takes, run_id="lane-run-1", directory=self.run_dir, root=self.root,
                                      **extra)

    def bundle(self, takes_path: Path, metrics: dict, *, name: str = "panel-bundle",
               privates: dict | None = None, identity: dict | None = None) -> Path:
        """metrics: takeID -> {judge: metrics dict, None (out of scope) or 'unavailable'}; a take not named has no
        evidence. Each evidence record binds the take's audio, text and language as the orchestrator writes it."""
        directory = self.base / "build" / name
        (directory / "evidence").mkdir(parents=True)
        (directory / "private").mkdir()
        manifest = json.loads(takes_path.read_text(encoding="utf-8"))
        entries, judges = [], set()
        for number, take in enumerate(manifest["takes"], 1):
            if take["takeID"] not in metrics:
                continue
            measurements = []
            for judge, values in metrics[take["takeID"]].items():
                judges.add(judge)
                status = "out-of-scope" if values is None else "unavailable" if values == "unavailable" else "complete"
                measurements.append({"judge": judge, "status": status,
                                     "metrics": values if status == "complete" else {},
                                     "outputIdentity": (identity or IDENTITY)[judge]})
            evidence = {"schema": "vocello.audioqc.take-evidence/1",
                        "take": {"takeID": take["takeID"], "language": take["language"],
                                 "audioSHA256": take["wavSHA256"], "textSHA256": take["textSHA256"]},
                        "measurements": measurements}
            private = {"takeID": take["takeID"], "referenceText": take["text"], "transcripts": {}}
            if take.get("reference"):
                private["referenceAudioSHA256"] = take["reference"]["wavSHA256"]
            private.update((privates or {}).get(take["takeID"], {}))
            texts = {}
            for kind, value in (("evidence", evidence), ("private", private)):
                texts[kind] = json.dumps(value)
                (directory / kind / f"{number:04d}.json").write_text(texts[kind], encoding="utf-8")
            entries.append({"takeID": take["takeID"], "evidence": f"evidence/{number:04d}.json",
                            "evidenceSHA256": sha(texts["evidence"]), "private": f"private/{number:04d}.json",
                            "privateSHA256": sha(texts["private"])})
        body = {"schema": calibration.BUNDLE_SCHEMA, "runID": "lane-run-1", "manifestSHA256": sha("panel"),
                "orchestratorSHA256": ORCHESTRATOR_SHA,
                "judgeMetrics": {judge: judge_metrics(judge) for judge in sorted(judges)},
                "startedAt": "2026-10-01T00:00:00.000000Z", "cacheRootEmptyAtStart": True, "takes": entries}
        write_json(directory / "bundle.json", {**body, "bundleDigest": sha256_json(body, ascii=False,
                                                                                   allow_nan=False)})
        return directory

    def measurements(self, takes_path: Path, last_active: dict, *, name: str = "measurements.json") -> Path:
        """Stage 0 over the lane takes: each named take's last active second (a take not named was not measured)."""
        manifest = json.loads(takes_path.read_text(encoding="utf-8"))
        clips = [{"clipID": take["takeID"], "population": "N3", "family": take["family"],
                  "sourceTakeID": take["takeID"], "language": take["language"], "injection": None,
                  "wavSHA256": take["wavSHA256"], "fastQC": {}, "observations": {},
                  "pcmMeasures": {"sourceSHA256": registry_lib.pcm_measures_sha256(),
                                  "lastActiveSeconds": last_active[take["takeID"]]}}
                 for take in manifest["takes"] if take["takeID"] in last_active]
        return write_json(self.base / "build" / name, {
            "kind": calibration.MEASUREMENTS_KIND, "schemaVersion": 1, "startedAt": "2026-10-01T00:00:00.000000Z",
            "subject": STAGE0_SUBJECT, "takesManifestSHA256": calibration.file_sha256(takes_path),
            "entriesSHA256": None, "clipsSHA256": json_digest(clips), "clips": clips})

    @staticmethod
    def asr(error_rate: float) -> dict:
        return {"errorRate": error_rate}

    def panel(self, takes_path: Path, scores: dict, **options) -> Path:
        """scores: takeID -> (whisper error, parakeet error, aligner end); every judge complete."""
        return self.bundle(takes_path, {take_id: {WHISPER: self.asr(whisper), PARAKEET: self.asr(parakeet),
                                                  ALIGNER: {"spanEndSeconds": end}}
                                        for take_id, (whisper, parakeet, end) in scores.items()}, **options)

    def evaluate(self, takes_path: Path, *, lane: str = "language-bench", **inputs) -> dict:
        return gates.evaluate(lane, takes_path, root=self.root, **inputs)

    @staticmethod
    def gate(result: dict, take_id: str, detector: str) -> dict:
        row = next(row for row in result["takes"] if row["take"] == take_id)
        return next(outcome for outcome in row["gates"] if outcome["detector"] == detector)


class LaneGateEvaluationTests(GateFixture):
    def test_a_take_above_its_threshold_flags_and_one_below_passes(self) -> None:
        takes = self.takes(("en-bad", "english", "custom"), ("en-good", "english", "design"))
        result = self.evaluate(takes, bundle=self.panel(takes, {"en-bad": (0.2, 0.25, 2.0),
                                                                "en-good": (0.05, 0.3, 2.0)}),
                               measurements=self.measurements(takes, {"en-bad": 2.1, "en-good": 2.1}))
        bad, good = self.gate(result, "en-bad", CONTENT), self.gate(result, "en-good", CONTENT)
        # consensus-min: both families must be high; the record's english threshold is 0.0931.
        self.assertEqual((bad["score"], bad["threshold"], bad["flagged"], bad["abstain"]), (0.2, 0.0931, True, None))
        self.assertEqual((good["score"], good["flagged"]), (0.05, False))
        self.assertEqual(bad["components"], {f"{WHISPER}:panel:errorRate": 0.2, f"{PARAKEET}:panel:errorRate": 0.25})
        runon = self.gate(result, "en-good", RUNON)
        self.assertEqual((round(runon["score"], 6), runon["threshold"], runon["flagged"]), (0.1, 0.5, False))
        self.assertEqual([row["verdict"] for row in result["takes"]], ["warn", "pass"])
        self.assertEqual(result["verdict"], "warn")
        detector = next(item for item in result["detectors"] if item["detector"] == CONTENT)
        self.assertEqual(detector["counts"], {"scored": 2, "flagged": 1, "abstained": {}})
        self.assertEqual(detector["evidenceMatchesRecord"], {"judgeIdentities": True, "judgeMetrics": True,
                                                             "scoringCode": True, "orchestrator": True})

    def test_each_language_reads_the_threshold_its_record_pre_registered(self) -> None:
        takes = self.takes(("fr", "french", "custom"), ("de", "german", "custom"))
        evidence = {"bundle": self.panel(takes, {"fr": (0.09, 0.09, 1.0), "de": (0.09, 0.09, 1.0)}),
                    "measurements": self.measurements(takes, {"fr": 1.5, "de": 1.5})}
        result = self.evaluate(takes, **evidence)
        # The same score flags against french's 0.0812 and passes german's 0.1175.
        self.assertEqual((self.gate(result, "fr", CONTENT)["threshold"], self.gate(result, "fr", CONTENT)["flagged"]),
                         (0.0812, True))
        self.assertEqual((self.gate(result, "de", CONTENT)["threshold"], self.gate(result, "de", CONTENT)["flagged"]),
                         (0.1175, False))
        # Run-on: 0.5 s past the end flags french (0.3) and not german (0.8).
        self.assertEqual([self.gate(result, take, RUNON)["flagged"] for take in ("fr", "de")], [True, False])
        # The gate reads the record's value, never one derived here.
        self.edit(self.records[CONTENT], lambda record: record["threshold"]["values"].update(german=0.05))
        self.assertTrue(self.gate(self.evaluate(takes, **evidence), "de", CONTENT)["flagged"])

    def test_takes_outside_the_lane_or_without_evidence_abstain_with_a_reason(self) -> None:
        takes = self.takes(
            ("ok", "english", "custom"), ("gone", "english", "custom"), ("failed", "french", "custom"),
            ("halfway", "german", "custom"), ("unmeasured", "german", "design"),
            ("control", "french", "custom", {"control": True}), ("es", "spanish", "custom"),
            ("cloned", "english", "clone"), ("silent", "english", "custom", {"exclude": "no-output"}))
        bundle = self.bundle(takes, {
            "ok": {WHISPER: self.asr(0.01), PARAKEET: self.asr(0.02), ALIGNER: {"spanEndSeconds": 1.0}},
            "failed": {WHISPER: "unavailable", PARAKEET: self.asr(0.5), ALIGNER: {"spanEndSeconds": 1.0}},
            "halfway": {WHISPER: self.asr(0.01), PARAKEET: self.asr(0.01), ALIGNER: None},
            "unmeasured": {WHISPER: self.asr(0.01), PARAKEET: self.asr(0.01), ALIGNER: {"spanEndSeconds": 1.0}}})
        result = self.evaluate(takes, bundle=bundle, measurements=self.measurements(
            takes, {"ok": 1.0, "gone": 1.0, "failed": 1.0, "halfway": 1.0}))
        abstained = {row["take"]: {outcome["detector"]: outcome["abstain"] for outcome in row["gates"]}
                     for row in result["takes"]}
        self.assertEqual(abstained["ok"], {CONTENT: None, RUNON: None})
        self.assertEqual(abstained["gone"], {CONTENT: "no-evidence", RUNON: "no-evidence"})
        self.assertEqual(abstained["failed"], {CONTENT: "judge-unavailable", RUNON: "judge-unavailable"})
        self.assertEqual(abstained["halfway"], {CONTENT: None, RUNON: "judge-out-of-scope"})
        self.assertEqual(abstained["unmeasured"], {CONTENT: None, RUNON: "no-evidence"})
        for take_id, reason in (("control", "negative-control"), ("es", "language-outside-lane"),
                                ("cloned", "mode-outside-lane"), ("silent", "no-output")):
            row = next(row for row in result["takes"] if row["take"] == take_id)
            self.assertEqual((row["excluded"], row["verdict"], set(abstained[take_id].values())),
                             (reason, None, {reason}))
        self.assertEqual(result["verdict"], "pass")
        self.assertEqual(result["counts"]["excluded"], 4)
        self.assertEqual(result["counts"]["unscored"], 2)  # "gone" and "failed": no gate could score them
        # Excluded takes never reach the panel: the manifest's takes are the gated ones only.
        manifest = json.loads(takes.read_text(encoding="utf-8"))
        self.assertEqual([take["takeID"] for take in manifest["takes"]],
                         ["ok", "gone", "failed", "halfway", "unmeasured"])

    def test_a_take_outside_the_record_s_scope_abstains(self) -> None:
        lane, found = gates.lane_gates(self.root, "language-bench")
        content = next(gate for gate in found if gate.detector == CONTENT)
        unit = {"score": 0.5, "abstain": None, "components": {}}
        narrowed = gates.LaneGate(content.detector, content.level, content.entry,
                                  {**content.record, "scope": {"languages": ["english"], "modes": ["custom"]}},
                                  content.record_file)
        self.assertEqual(gates.gate_result(narrowed, {"language": "french", "mode": "custom"}, unit, lane)["abstain"],
                         "language-outside-record")
        self.assertEqual(gates.gate_result(narrowed, {"language": "english", "mode": "design"}, unit, lane)["abstain"],
                         "mode-outside-record")
        self.assertTrue(gates.gate_result(narrowed, {"language": "english", "mode": "custom"}, unit, lane)["flagged"])
        missing = gates.LaneGate(content.detector, content.level, content.entry,
                                 {**content.record, "threshold": {**content.record["threshold"],
                                                                  "values": {"english": 0.1}}}, content.record_file)
        self.assertEqual(gates.gate_result(missing, {"language": "german", "mode": "custom"}, unit, lane)["abstain"],
                         "no-threshold")

    def test_a_detector_without_a_qualifying_record_is_refused(self) -> None:
        takes = self.takes(("ok", "english", "custom"))
        evidence = {"bundle": self.panel(takes, {"ok": (0.01, 0.01, 1.0)}),
                    "measurements": self.measurements(takes, {"ok": 1.0})}
        shutil.rmtree(self.root / calibration.RECORDS / RUNON)
        with self.assertRaisesRegex(gates.GateError, f"{RUNON} gates language-bench at warn without a committed"):
            self.evaluate(takes, **evidence)
        self.forge(json.loads((self.root / self.records[CONTENT]).read_text(encoding="utf-8")), run_on_entry(),
                   {"english": 0.5, "french": 0.3, "german": 0.8}, (WHISPER, PARAKEET, ALIGNER))
        self.edit(self.records[RUNON], lambda record: record.update(verdict="refused", level=None,
                                                                    reasons=["far-pooled-not-met"]))
        with self.assertRaisesRegex(gates.GateError, r"refused \(far-pooled-not-met\)"):
            self.evaluate(takes, **evidence)
        # The CLI reports the refusal; at warn gates it is an error that never fails the lane.
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gates.main(["--repo-root", str(self.root), "evaluate", "--lane", "language-bench",
                               "--takes", str(takes), "--bundle", str(evidence["bundle"]),
                               "--measurements", str(evidence["measurements"]),
                               "--output", str(self.base / "build" / "gates.json")])
        self.assertEqual(code, gates.EXIT_ERROR)
        self.assertIn("ERROR · not computed", err.getvalue())

    def test_a_panel_that_did_not_embed_the_clone_reference_is_refused(self) -> None:
        reference = self.wav("reference", self.base / "voices")
        takes = self.takes(("clone_take_00", "english", "clone", {"reference": reference}),
                           ("clone_take_01", "english", "clone", {"reference": reference}),
                           ("control_vivian_00", "english", "custom", {"control": True}), lane="clone-lane")
        manifest = json.loads(takes.read_text(encoding="utf-8"))
        self.assertEqual(manifest["takes"][0]["reference"],
                         {"wavPath": str(reference.resolve()), "wavSHA256": calibration.file_sha256(reference)})
        cosines = {"clone_take_00": {CAMPP: {"cosine": 0.3}}, "clone_take_01": {CAMPP: {"cosine": 0.8}}}
        result = self.evaluate(takes, lane="clone-lane", bundle=self.bundle(takes, cosines))
        self.assertEqual([self.gate(result, take, SIMILARITY)["flagged"] for take in ("clone_take_00", "clone_take_01")],
                         [True, False])
        self.assertEqual(self.gate(result, "control_vivian_00", SIMILARITY)["abstain"], "negative-control")
        self.assertEqual(result["verdict"], "warn")
        unembedded = self.bundle(takes, cosines, name="unembedded",
                                 privates={"clone_take_00": {"referenceAudioSHA256": None}})
        with self.assertRaisesRegex(gates.GateError, "declares a reference clip the panel did not embed"):
            self.evaluate(takes, lane="clone-lane", bundle=unembedded)

    def test_the_lane_verdict_is_its_worst_take_and_a_fail_gate_fails_only_on_its_record_s_evidence(self) -> None:
        takes = self.takes(("en", "english", "custom"), ("fr", "french", "custom"))
        quiet = {"bundle": self.panel(takes, {"en": (0.01, 0.01, 1.0), "fr": (0.01, 0.01, 1.0)}),
                 "measurements": self.measurements(takes, {"en": 1.0, "fr": 1.0})}
        self.assertEqual(self.evaluate(takes, **quiet)["verdict"], "pass")
        flagged = {"bundle": self.panel(takes, {"en": (0.01, 0.01, 1.0), "fr": (0.3, 0.3, 1.0)}, name="flagged"),
                   "measurements": quiet["measurements"]}
        result = self.evaluate(takes, **flagged)
        self.assertEqual(([row["verdict"] for row in result["takes"]], result["verdict"]), (["pass", "warn"], "warn"))
        self.assertEqual(result["counts"]["byVerdict"], {"pass": 1, "warn": 1, "fail": 0})

        def fail_record(record: dict) -> None:
            record.update(operatingPoint="fail", level="fail")
            record["cohorts"]["n3"] = {"kind": calibration.N3_KIND, "manifestDigest": "7" * 64,
                                       "scoresSHA256": "8" * 64}
            record["rates"]["n3"] = {"events": 0, "units": 180, "rate": 0.0, "lower": 0.0, "upper": 0.0165,
                                     "confidence": 0.95, "method": "clopper-pearson-one-sided", "limit": 0.05,
                                     "minimumUnits": None, "meets": True}
        self.edit(self.records[CONTENT], fail_record)
        self.edit(gates.GATES, lambda config: config["lanes"]["language-bench"]["gates"][0].update(level="fail"))
        result = self.evaluate(takes, **flagged)
        self.assertEqual((result["verdict"], self.gate(result, "fr", CONTENT)["level"]), ("fail", "fail"))
        # Panel evidence from another Whisper than the record qualified flags at warn only.
        drifted = self.panel(takes, {"en": (0.01, 0.01, 1.0), "fr": (0.3, 0.3, 1.0)}, name="drifted",
                             identity={**IDENTITY, WHISPER: "f" * 64})
        result = self.evaluate(takes, bundle=drifted, measurements=quiet["measurements"])
        detector = next(item for item in result["detectors"] if item["detector"] == CONTENT)
        self.assertEqual((detector["level"], detector["effectiveLevel"], detector["evidenceMatchesRecord"]
                          ["judgeIdentities"]), ("fail", "warn", False))
        self.assertEqual(result["verdict"], "warn")
        lines = gates.summary_lines(result)
        self.assertTrue(any("flags at warn" in line and "judgeIdentities" in line for line in lines), lines)
        self.assertEqual(gates.EXIT_CODES, {"pass": 0, "warn": 3, "fail": 1})

    def test_gates_json_holds_ids_numbers_and_reason_codes_only(self) -> None:
        reference = self.wav("reference", self.base / "voices")
        takes = self.takes(("en", "english", "custom"), ("fr", "french", "custom"),
                           ("control", "french", "custom", {"control": True}))
        evidence = {"bundle": self.panel(takes, {"en": (0.3, 0.3, 1.0), "fr": (0.01, 0.01, 1.0)},
                                         privates={"en": {"transcripts": {WHISPER: "a private transcript"}}}),
                    "measurements": self.measurements(takes, {"en": 1.0, "fr": 1.0})}
        output = self.base / "build" / "out" / "gates.json"
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gates.main(["--repo-root", str(self.root), "evaluate", "--lane", "language-bench",
                               "--takes", str(takes), "--bundle", str(evidence["bundle"]),
                               "--measurements", str(evidence["measurements"]), "--output", str(output)])
        self.assertEqual(code, gates.EXIT_CODES["warn"], err.getvalue())
        self.assertIn("audio-qc gates · language-bench: WARN", out.getvalue())
        text = output.read_text(encoding="utf-8")
        result = json.loads(text)
        self.assertEqual(privacy_errors(result), [])
        self.assertEqual(gates.result_errors(result), [])
        for private in (*TEXT.values(), "a private transcript", str(self.run_dir), str(self.base), "wav/",
                        reference.name):
            self.assertNotIn(private, text)

        def keys(value) -> set[str]:
            if isinstance(value, dict):
                return set(value) | {key for child in value.values() for key in keys(child)}
            return {key for child in value for key in keys(child)} if isinstance(value, list) else set()
        self.assertFalse({key.lower() for key in keys(result)} & {"text", "transcript", "transcripts", "path",
                                                                  "wavpath", "audiopath", "referencetext"})
        self.assertTrue(gates.result_errors({**result, "takes": [{**result["takes"][0], "text": TEXT["english"]}]}))
        # A result is lane evidence: never written into the tree outside build/.
        with self.assertRaisesRegex(gates.GateError, "inside the repository"):
            gates.write_result(result, self.root / "gates.json", self.root)

    def test_the_lane_takes_manifest_is_bound_to_its_digest_lane_and_audio(self) -> None:
        takes = self.takes(("en", "english", "custom"))
        manifest = json.loads(takes.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(gates.GateError, "holds the takes of 'language-bench', not 'clone-lane'"):
            gates.load_lane_takes(takes, "clone-lane")
        manifest["takes"][0]["text"] = TEXT["french"]
        write_json(takes, manifest)
        with self.assertRaisesRegex(gates.GateError, "does not match its manifestDigest"):
            gates.load_lane_takes(takes, "language-bench")
        with self.assertRaisesRegex(gates.GateError, "bytes differ"):
            self.takes(("en", "english", "custom", {"wavSHA256": "0" * 64}))
        outside = self.wav("outside", self.base / "elsewhere")
        with self.assertRaisesRegex(gates.GateError, "outside the lane's run directory"):
            gates.write_lane_takes("language-bench", [{"takeID": "outside", "wav": outside, "language": "english",
                                                       "mode": "custom", "text": TEXT["english"]}],
                                   run_id="r", directory=self.run_dir, root=self.root)


class LaneGateDriverTests(GateFixture):
    """`run` over a language bench run directory: its takes from the run plan and independent-ASR manifest, the
    gates' judges on the run's own cache root, Stage 0, then the evaluation. The orchestrator's manifest step runs
    for real (no model); its `run` and Stage 0 are replaced by fixture writers."""

    def language_run(self) -> str:
        plan = language_bench_evidence.build_plan(
            run_id="mac-lang-bench-20261001-000000-fixture", matrix_path=REPO / "config/language-bench-matrix.json",
            corpus_path=REPO / "config/language-bench-corpus.json", subset="quick", cohort_path=None)
        write_json(self.run_dir / gates.LANGUAGE_PLAN, plan)
        corpus = json.loads((REPO / "config/language-bench-corpus.json").read_text(encoding="utf-8"))
        scripts = {entry["id"]: entry["script"] for entry in corpus["languages"]}
        rows = []
        for take in plan["takes"]:
            wav = self.wav(take["cellID"])
            script = scripts[take["scriptLang"]]
            rows.append({"id": take["cellID"], "generationID": f"generation-{take['takeIndex']}",
                         "audioPath": str(wav), "audioSHA256": calibration.file_sha256(wav),
                         "expectedLanguage": take["expectedHint"], "referenceText": script,
                         "scriptSHA256": text_sha256(script), "expectedOutcome": take["expectedOutcome"]})
        write_json(self.run_dir / gates.LANGUAGE_ASR_MANIFEST, {
            "schemaVersion": 1, "kind": "independent-asr-manifest", "runID": plan["runID"], "platform": "macos",
            "generationProcessExited": True, "rows": rows})
        return plan["runID"]

    def runner(self, calls: list):
        def run(argv, stdout=None, stderr=None, check=False):
            calls.append(list(argv))
            command = argv[2]
            value = lambda flag: Path(argv[argv.index(flag) + 1])  # noqa: E731
            code = 0
            if command == "manifest":
                code = orchestrator.main(argv[2:])
            elif command == "run":
                takes = self.run_dir / gates.TAKES_FILE
                manifest = json.loads(takes.read_text(encoding="utf-8"))
                scores = {take["takeID"]: (0.3 if take["takeID"] == "custom-fr-auto" else 0.01, 0.3, 1.0)
                          for take in manifest["takes"]}
                built = self.panel(takes, scores, name="built-bundle")
                shutil.copytree(built, value("--bundle"))
            elif command == "score":
                takes = value("--takes")
                manifest = json.loads(takes.read_text(encoding="utf-8"))
                written = self.measurements(takes, {take["takeID"]: 1.0 for take in manifest["takes"]})
                value("--output").mkdir(parents=True)
                shutil.copy(written, value("--output") / "measurements.json")
            return subprocess.CompletedProcess(argv, code)
        return run

    def test_the_driver_runs_the_gates_judges_on_the_run_s_own_cache_root_then_evaluates(self) -> None:
        run_id = self.language_run()
        calls: list = []
        cache = self.base / "analysis-cache"
        with mock.patch.dict(os.environ, {"QVOICE_DELIVERY_ANALYSIS_CACHE": str(cache)}), \
                redirect_stdout(StringIO()):
            result, path = gates.run_gates("language-bench", self.run_dir, root=self.root, runner=self.runner(calls),
                                           python="python3")
        self.assertEqual([call[2] for call in calls], ["manifest", "run", "score"])
        run = calls[1]
        judges = [run[index + 1] for index, item in enumerate(run) if item == "--judge"]
        # Exactly the judges the two gates read: the content voters and the aligner, nothing else of the panel.
        self.assertEqual(judges, [ALIGNER, PARAKEET, WHISPER])
        self.assertEqual(Path(run[run.index("--cache-root") + 1]),
                         cache / "confirmation" / f"lane-language-bench-{run_id}")
        self.assertEqual(path, (self.run_dir / "audio-qc" / "gates.json").resolve())
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), result)
        # The quick subset's seven cells: six gated, the French-text English-hint control excluded.
        self.assertEqual(result["counts"]["gated"], 6)
        self.assertEqual([row["take"] for row in result["takes"] if row["excluded"]], ["custom-fr-text-en-pinned"])
        self.assertEqual([row["take"] for row in result["takes"] if row["verdict"] == "warn"], ["custom-fr-auto"])
        self.assertEqual(result["verdict"], "warn")
        # The orchestrator took the lane takes manifest as is: every gated take with its text and audio.
        panel = json.loads((self.run_dir / "audio-qc" / "panel-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual((panel["lane"], len(panel["takes"]), panel["generationProcessExited"]),
                         ("language-bench", 6, True))
        # The gates ran on this run: a second run refuses before any tool starts.
        with self.assertRaisesRegex(gates.GateError, "already exists"):
            gates.run_gates("language-bench", self.run_dir, root=self.root, runner=self.runner(calls))
        self.assertEqual(len(calls), 3)

    def test_the_driver_refuses_an_uncovered_gate_before_any_judge_runs(self) -> None:
        self.language_run()
        shutil.rmtree(self.root / calibration.RECORDS / RUNON)
        calls: list = []
        with self.assertRaisesRegex(gates.GateError, "without a committed calibration record"):
            gates.run_gates("language-bench", self.run_dir, root=self.root, runner=self.runner(calls))
        self.assertEqual(calls, [])
        self.assertFalse((self.run_dir / "audio-qc").exists())
        err = StringIO()
        with redirect_stdout(StringIO()), redirect_stderr(err):
            code = gates.main(["--repo-root", str(self.root), "run", "--lane", "language-bench",
                               "--run-dir", str(self.run_dir)])
        self.assertEqual(code, gates.EXIT_ERROR)
        # A lane with a fail gate fails instead when its gates cannot be computed.
        self.edit(gates.GATES, lambda config: config["lanes"]["language-bench"]["gates"][0].update(level="fail"))
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            code = gates.main(["--repo-root", str(self.root), "run", "--lane", "language-bench",
                               "--run-dir", str(self.run_dir)])
        self.assertEqual(code, gates.EXIT_CODES["fail"])

    def test_stage0_measures_the_lane_takes_manifest_the_run_on_gate_reads(self) -> None:
        """The real Stage 0 scorer over the lane takes manifest, read back by the run-on gate."""
        rate = 24_000
        takes = []
        for take_id, language, tail in (("en", "english", 0.0), ("fr", "french", 0.6)):
            path = self.run_dir / "wav" / f"{take_id}.wav"
            path.parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as writer:
                writer.setnchannels(1)
                writer.setsampwidth(2)
                writer.setframerate(rate)
                frames = bytearray()
                for index in range(int(rate * (1.0 + tail))):
                    sample = int(9000 * math.sin(2 * math.pi * 220 * index / rate))
                    frames += sample.to_bytes(2, "little", signed=True)
                frames += bytes(2 * int(rate * 0.3))
                writer.writeframes(bytes(frames))
            takes.append({"takeID": take_id, "wav": path, "language": language, "mode": "custom",
                          "text": TEXT[language]})
        manifest = gates.write_lane_takes("language-bench", takes, run_id="stage0-run", directory=self.run_dir,
                                          root=self.root)
        audio_qc_calibration_set.run_score(manifest, None, self.base / "build" / "stage0", jobs=1)
        measurements = self.base / "build" / "stage0" / "measurements.json"
        result = self.evaluate(manifest, bundle=self.panel(manifest, {"en": (0.01, 0.01, 1.0),
                                                                      "fr": (0.01, 0.01, 1.0)}),
                               measurements=measurements)
        ends = {take_id: self.gate(result, take_id, RUNON) for take_id in ("en", "fr")}
        self.assertTrue(all(outcome["score"] is not None for outcome in ends.values()), ends)
        self.assertGreater(ends["fr"]["score"], ends["en"]["score"] + 0.4)
        self.assertEqual((ends["en"]["flagged"], ends["fr"]["flagged"]), (False, True))


if __name__ == "__main__":
    unittest.main()
