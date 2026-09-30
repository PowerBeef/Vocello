#!/usr/bin/env python3
"""Class E end to end on fixtures: the speaker cohort, its N2 resynthesis, the panel manifest's reference clips,
CAM++ evidence, the three identity detectors' scores and plans, and the confirmation injection set's donors.

Every clip is a procedural speech-like render (`lib/qc_qualification/fixtures.py`) written into synthetic
extractions of the four corpora the speaker cohort reads. The codec round trip is replaced by its resampled input,
the panels by bundles in the orchestrator's shape carrying CAM++ metrics, and the plans are written into a
temporary repository holding the committed detector registry and judges, with the policy's warn floors lowered
to the fixture's size. No model runs and no audio is committed.
"""

from __future__ import annotations

from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_calibration_set as m2  # noqa: E402
import audio_qc_corpora as corpora  # noqa: E402
import audio_qc_detector_calibration as calibration  # noqa: E402
import audio_qc_n2_resynthesis as n2  # noqa: E402
import audio_qc_orchestrator as orchestrator  # noqa: E402
from lib import corpus_clips as clips  # noqa: E402
from lib.jsonio import sha256_json  # noqa: E402
from lib.language_metrics import text_sha256  # noqa: E402
from lib.qc_pipeline import panel_metrics  # noqa: E402
from lib.qc_pipeline.layered_cache import metric_sources_digest  # noqa: E402
from lib.qc_pipeline.panel_jobs import profile  # noqa: E402
from lib.qc_qualification import fixtures, pcm, speaker_donors  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
CAMPPLUS = "speaker.campplus-voxceleb@1"
DETECTORS = ("identity.clone-similarity@1", "identity.window-drift@1", "identity.onset-drift@1")
IDENTITY_INJECTORS = ("IDN-IMPOSTOR", "IDN-ONSET", "IDN-SHIFT", "IDN-SWAP")
RATE = 24_000
SPEAKERS, READINGS, WORDS = 6, 5, 14  # 14 words render 5 s or more, above the cohort's 4 s floor
# Three speakers of five readings per language and split: 15 families, above the lowered floor and 1/alpha - 1.
FLOOR, ALPHA, PER_CELL = 12, "0.09", 4
INJECTION = ("--injection-catalog-seed", "7", "--injection-sample-seed", "1", "--injection-sample-per-cell",
             str(PER_CELL), "--injection-classes", "E")
PLAN_DATE = "2026-09-01T00:00:00+0000"
FRESH = "2026-09-02T00:00:00.000000Z"
REVISION = "47ab65f7eda0aad7e1c1a008d9c12d93a10ac475"


def quiet(function, *args, **kwargs):
    with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
        return function(*args, **kwargs)


def git(root: Path, *argv: str, date: str | None = None) -> None:
    environment = dict(os.environ)
    if date is not None:
        environment.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                    "-c", "commit.gpgsign=false", "-c", "maintenance.auto=false", "-c", "gc.auto=0", *argv],
                   check=True, stdout=subprocess.DEVNULL, env=environment)


def wav_bytes(samples) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setparams((1, 2, RATE, 0, "NONE", "not compressed"))
        writer.writeframes(pcm.to_pcm16(samples).tobytes())
    return buffer.getvalue()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def unit_fraction(text: str) -> float:
    return int(sha(text.encode("utf-8"))[:8], 16) / float(1 << 32)


def extract_corpora(registry: dict, root: Path) -> dict[str, list]:
    """Synthetic extractions of the speaker cohort's sources: per language six speakers of five readings, gendered
    where the corpus labels gender; returns each clip's word intervals (samples at 24 kHz)."""
    by_source: dict[str, list[str]] = {}
    for language, source in sorted(corpora.SPEAKER_SOURCES.items()):
        by_source.setdefault(source, []).append(language)
    words: dict[str, list] = {}
    seed = 900
    for source, languages in sorted(by_source.items()):
        rate = registry["sources"][source]["extract"]["outputRate"]
        gendered = source in ("mls", "aishell3-subset")
        directory = corpora.source_directory(registry, source, root) / corpora.EXTRACTED_DIRECTORY
        sink = clips.ClipSink(directory / "wav")
        for language in languages:
            for speaker in range(SPEAKERS):
                gender = ("female", "male")[speaker % 2]
                base = fixtures.VOICES["high" if gender == "female" else "low"]
                voice = replace(base, voice_id=f"{language}-{speaker}", f0_hz=base.f0_hz * (1.0 + 0.05 * speaker))
                for reading in range(READINGS):
                    seed += 1
                    script = fixtures.make_script(seed, word_count=WORDS)
                    data = wav_bytes(fixtures.render(script, voice))
                    clip, info = clips.clip_from_wav(data, output_rate=rate)
                    source_id = f"{language[:3]}{speaker}r{reading}"
                    clip_id = clips.clip_id(source, source_id)
                    labels = {"language": language, "split": "test", "sourceID": source_id,
                              "speaker": f"{language[:3]}-{speaker}", "gender": gender if gendered else None,
                              "text": f"{language} speaker {speaker} reading {reading}: {script.text}"}
                    sink.add(clip_id, clip, info, labels, origin=f"row#{source_id}", source_sha256=sha(data))
                    words[clip_id] = list(script.words)
        manifest = corpora.build_manifest(registry, source, sink.clips, sink.skipped, metadata={}, members={})
        (directory / corpora.MANIFEST_NAME).write_text(json.dumps(manifest), encoding="utf-8")
    return words


def resynthesize(n1_path: Path, directory: Path) -> Path:
    """The qc-n2 lane's three steps around a stand-in round trip whose output is its 24 kHz input."""
    plan = n2.build_plan(n1_manifest=n1_path, out_dir=directory, run_id=f"mac-qc-n2-{directory.name}")
    out = directory / "roundtrip"
    out.mkdir()
    items = []
    for item in plan["items"]:
        data = (directory / item["inputWAVPath"]).read_bytes()
        (out / f"{item['id']}.wav").write_bytes(data)
        codes = out / f"{item['id']}.codes.bin"
        codes.write_bytes(b"VQCT" + item["id"].encode())
        items.append({"id": item["id"], "inputSHA256": item["inputWAVSHA256"], "status": "complete",
                      "inputSampleCount": item["inputSampleCount"], "outputPath": f"{item['id']}.wav",
                      "outputSHA256": sha(data), "outputSampleCount": item["inputSampleCount"],
                      "clampedSampleCount": 0, "frameCount": 7, "codebookCount": 16,
                      "codesPath": f"{item['id']}.codes.bin", "codesSHA256": sha(codes.read_bytes())})
    result = {"schemaVersion": 1, "kind": n2.RESULT_KIND, "jobSHA256": plan["job"]["sha256"],
              "modelID": "pro_clone_speed", "modelRevision": REVISION, "tokenizerSHA256": "a" * 64,
              "encoderInput": n2.ENCODER_INPUT, "decodeSemantics": n2.DECODE_SEMANTICS,
              "outputFormat": n2.OUTPUT_FORMAT, "sampleRate": n2.CODEC_RATE, "status": "complete",
              "modelLoadCount": 1, "items": items}
    result_path = out / "codec-roundtrip-result.json"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    output = directory / "n2-manifest.json"
    n2.build_manifest(plan_path=directory / n2.PLAN_NAME, result_path=result_path, output=output)
    return output


def alignments_for(manifest_path: Path, words: dict[str, list], output: Path) -> Path:
    """The aligner's export for an N2 cohort: every take's script words, Korean left out as the aligner leaves it."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = {}
    for take in manifest["takes"]:
        if take["language"] == "korean":
            continue
        intervals = words[take["n1TakeID"].removeprefix("n1-")]
        records[take["takeID"]] = {"language": take["language"], "audioSHA256": take["wavSHA256"],
                                   "status": "complete",
                                   "intervals": [{"start": start / RATE, "end": end / RATE, "unitSHA256": "0" * 64}
                                                 for start, end in intervals]}
    output.write_text(json.dumps({"schemaVersion": 1, "kind": m2.ALIGNMENTS_KIND,
                                  "takesManifest": {"sha256": sha(manifest_path.read_bytes())},
                                  "takes": records, "takesSHA256": pcm.json_digest(records)}), encoding="utf-8")
    return output


def panel_manifest(source: Path) -> dict:
    """What `audio_qc_orchestrator.py manifest --from-calibration-takes` hands the panel."""
    return orchestrator.manifest_from_calibration_takes(json.loads(source.read_text(encoding="utf-8")),
                                                        source_sha256=sha(source.read_bytes()),
                                                        base_dir=source.parent)


def campplus_metrics(take: dict, injection: dict | None) -> dict:
    """CAM++'s whole-take and window cosines: a clean take near its reference, and each identity positive low
    where its construction puts another voice (the whole take, a span or the onset)."""
    whole = 0.72 + 0.12 * unit_fraction(take["id"])
    minimum, onset = whole - 0.08 - 0.05 * unit_fraction("min" + take["id"]), whole - 0.04
    positive = (injection or {}).get("population") == "P1" and (injection or {}).get("severity") == "severe"
    kind = (injection or {}).get("injectorID") if positive else None
    if kind in ("IDN-IMPOSTOR", "IDN-SHIFT"):
        whole, minimum, onset = 0.21, 0.12, 0.18
    elif kind == "IDN-SWAP":
        minimum = whole - 0.6
    elif kind == "IDN-ONSET":
        onset = whole - 0.6
    return {"cosine": round(whole, 6), "windowCount": 7, "windowCosineMinimum": round(minimum, 6),
            "windowCosineMean": round(whole - 0.03, 6), "onsetWindowCosine": round(onset, 6),
            "embeddingDimension": 512}


def write_bundle(directory: Path, panel: dict, injections: dict[str, dict] | None = None) -> Path:
    """A private panel bundle in the orchestrator's shape: CAM++'s metrics per take, and in each private record
    the reference clip the panel embedded (the manifest's)."""
    (directory / "evidence").mkdir(parents=True)
    (directory / "private").mkdir()
    entries = []
    for number, take in enumerate(panel["takes"], 1):
        evidence = {"schema": "vocello.audioqc.take-evidence/1",
                    "take": {"takeID": take["id"], "language": take["language"], "audioSHA256": take["audioSHA256"],
                             "textSHA256": text_sha256(take["referenceText"])},
                    "measurements": [{"judge": CAMPPLUS, "status": "complete", "outputIdentity": "d" * 64,
                                      "metrics": campplus_metrics(take, (injections or {}).get(take["id"]))}]}
        private = {"takeID": take["id"], "referenceText": take["referenceText"], "transcripts": {}}
        if "referenceAudioSHA256" in take:
            private["referenceAudioSHA256"] = take["referenceAudioSHA256"]
        texts = {"evidence": json.dumps(evidence), "private": json.dumps(private)}
        entry = {"takeID": take["id"]}
        for key, text in texts.items():
            (directory / key / f"{number:04d}.json").write_text(text, encoding="utf-8")
            entry.update({key: f"{key}/{number:04d}.json", f"{key}SHA256": sha(text.encode("utf-8"))})
        entries.append(entry)
    category = profile(CAMPPLUS).category
    sources = metric_sources_digest(panel_metrics.metric_sources(category))
    body = {"schema": calibration.BUNDLE_SCHEMA, "runID": directory.name, "manifestSHA256": "1" * 64,
            "orchestratorSHA256": calibration.file_sha256(calibration.ORCHESTRATOR_SOURCE),
            "judgeMetrics": {CAMPPLUS: {"definition": panel_metrics.metric_definition(category),
                                        "sourcesSHA256": sources}},
            "startedAt": FRESH, "cacheRootEmptyAtStart": True,
            "cache": {layer: {"hits": 0, "misses": len(entries), "adopted": 0} for layer in ("L0", "L1", "L2")},
            "takes": entries}
    (directory / "bundle.json").write_text(json.dumps({**body, "bundleDigest": sha256_json(body, ascii=False,
                                                                                          allow_nan=False)}),
                                           encoding="utf-8")
    return directory


class IdentityChainTests(unittest.TestCase):
    """One chain built once: extractions, both speaker cohorts, their N2 manifests, the confirmation cohort's
    word intervals and E injection set, and a repository holding the committed registry."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        root = cls.root = Path(cls.directory.name)
        cls.registry = corpora.load_registry()
        cls.words = extract_corpora(cls.registry, root / "cache")
        cls.n1: dict[str, Path] = {}
        cls.cohort: dict[str, Path] = {}
        for split in ("calibration", "confirmation"):
            corpora.speaker_cohort(cls.registry, split=split, root=root / "cache")
            cls.n1[split] = corpora.speaker_cohort_path(cls.registry, split=split, share=0.5, root=root / "cache")
            cls.cohort[split] = resynthesize(cls.n1[split], root / f"qc-n2-{split}")
        cls.alignments = alignments_for(cls.cohort["confirmation"], cls.words, root / "alignments.json")
        cls.set_dir = cls.cohort["confirmation"].parent / "injection-set"
        cls.summary = quiet(m2.run_inject, cls.cohort["confirmation"], cls.set_dir, catalog_seed=7, classes=("E",),
                            jobs=1, alignments_path=cls.alignments, sample_per_cell=PER_CELL, sample_seed=1)
        cls.set_path = cls.set_dir / "injection-set.json"
        repo = cls.repo = root / "repo"
        (repo / "config").mkdir(parents=True)
        for name in (calibration.REGISTRY, calibration.JUDGES):
            shutil.copy(REPO / name, repo / name)
        policy = json.loads((REPO / calibration.POLICY).read_text(encoding="utf-8"))
        policy["operatingPoints"]["warn"]["minimumUnits"]["calibration"] = FLOOR
        (repo / calibration.POLICY).write_text(json.dumps(policy, indent=2), encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        git(repo, "add", "config")
        git(repo, "commit", "-q", "--no-verify", "-m", "config")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def cli(self, *argv: str, expect: int = 0) -> str:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = calibration.main(["--repo-root", str(self.repo), *argv])
        self.assertEqual(code, expect, f"{argv[0]}: {err.getvalue()}")
        return out.getvalue() + err.getvalue()

    def manifest(self, split: str) -> dict:
        return json.loads(self.cohort[split].read_text(encoding="utf-8"))

    def entries(self, injector: str) -> list[dict]:
        return [entry for entry in self.summary["entries"] if entry["injection"]["injectorID"] == injector]

    def test_each_n2_take_keeps_its_speaker_and_names_its_references_resynthesis(self) -> None:
        speakers = {}
        for split in ("calibration", "confirmation"):
            manifest = self.manifest(split)
            self.assertEqual(n2.validate_manifest(manifest, manifest_dir=self.cohort[split].parent)["status"], "PASS")
            by_id = {take["takeID"]: take for take in manifest["takes"]}
            for take in manifest["takes"]:
                reference = by_id[take["reference"]["takeID"]]
                self.assertEqual((reference["speaker"], reference["wavSHA256"]),
                                 (take["speaker"], take["reference"]["wavSHA256"]))
                self.assertNotEqual(reference["scriptID"], take["scriptID"])
                self.assertEqual("gender" in take, take["language"] not in ("english", "korean"))
            speakers[split] = {take["speaker"] for take in manifest["takes"]}
            self.assertEqual(Counter(take["language"] for take in manifest["takes"]),
                             Counter({language: 3 * READINGS for language in corpora.SPEAKER_SOURCES}))
        self.assertFalse(speakers["calibration"] & speakers["confirmation"])

    def test_the_confirmation_set_draws_every_identity_construction_with_its_donors(self) -> None:
        takes = {take["takeID"]: take for take in self.manifest("confirmation")["takes"]}
        drawn = Counter((entry["injection"]["injectorID"], entry["injection"]["severity"])
                        for entry in self.summary["entries"])
        for injector in IDENTITY_INJECTORS:
            self.assertEqual((drawn[(injector, "severe")], drawn[(injector, "sham")]), (PER_CELL, PER_CELL), injector)
        for entry in self.entries("IDN-IMPOSTOR"):
            source, donor = takes[entry["sourceTakeID"]], takes[entry["injection"]["donorTakeID"]]
            self.assertEqual((donor["language"], donor["gender"]), (source["language"], source["gender"]))
            self.assertEqual(donor["speaker"] != source["speaker"], entry["injection"]["severity"] == "severe")
            self.assertEqual(entry["speaker"], source["speaker"])
        for injector in ("IDN-SWAP", "IDN-ONSET"):
            for entry in self.entries(injector):
                self.assertTrue(entry["injection"]["variant"].startswith("take-"))
                source, donor = takes[entry["sourceTakeID"]], takes[entry["injection"]["donor"]["takeID"]]
                self.assertEqual((donor["language"], donor["gender"]), (source["language"], source["gender"]))
                self.assertEqual(donor["speaker"] != source["speaker"], entry["injection"]["severity"] != "sham")
        # Donors need a gender, and a splice word intervals: English and Korean receive only IDN-SHIFT.
        by_language = {takes[entry["sourceTakeID"]]["language"]
                       for injector in ("IDN-IMPOSTOR", "IDN-SWAP", "IDN-ONSET") for entry in self.entries(injector)}
        self.assertFalse(by_language & {"english", "korean"})
        report = quiet(m2.run_verify, self.set_path, self.cohort["confirmation"], jobs=1,
                       alignments_path=self.alignments)
        self.assertTrue(report["verified"], report["failures"][:3])

    def test_the_panel_manifest_hands_every_take_and_positive_its_reference_clip(self) -> None:
        cohort = self.manifest("confirmation")
        takes = {take["takeID"]: take for take in cohort["takes"]}
        for panel in (panel_manifest(self.cohort["confirmation"]), panel_manifest(self.set_path)):
            for take in panel["takes"]:
                path = Path(take["referenceAudioPath"])
                self.assertTrue(path.is_file(), take["id"])
                self.assertEqual(sha(path.read_bytes()), take["referenceAudioSHA256"])
                self.assertNotEqual(take["referenceAudioSHA256"], take["audioSHA256"])
        entries = {entry["takeID"]: entry for entry in self.summary["entries"]}
        for take in panel_manifest(self.set_path)["takes"]:
            entry = entries[take["id"]]
            source = takes[entry["sourceTakeID"]]
            # An impostor is scored against its source take, the speaker it is presented as; every other
            # construction against its source's own reference clip.
            expected = source["wavSHA256"] if entry["injection"]["injectorID"] == speaker_donors.IMPOSTOR_ID \
                else source["reference"]["wavSHA256"]
            self.assertEqual(take["referenceAudioSHA256"], expected, take["id"])

    def test_scores_and_plans_for_the_three_identity_detectors(self) -> None:
        out = self.root / "scores"
        calibration_panel = panel_manifest(self.cohort["calibration"])
        calibration_bundle = write_bundle(self.root / "bundles" / "calibration", calibration_panel)
        pending = []
        for detector in DETECTORS:
            scores = out / f"{detector}-calibration.json"
            self.cli("scores", "--detector", detector, "--role", "calibration", "--cohort",
                     str(self.cohort["calibration"]), "--n1-manifest", str(self.n1["calibration"]),
                     "--bundle", str(calibration_bundle), "--output", str(scores))
            document = json.loads(scores.read_text(encoding="utf-8"))
            self.assertEqual(document["counts"]["abstained"], {})
            self.assertEqual(len({unit["language"] for unit in document["units"]}), len(corpora.SPEAKER_SOURCES))
            self.assertTrue(all(unit["speaker"].startswith("speaker:") for unit in document["units"]))
            def plan(confirmation: str, *, expect: int = 0) -> str:
                return self.cli("plan", "--detector", detector, "--calibration-cohort", str(self.cohort["calibration"]),
                                "--calibration-n1-manifest", str(self.n1["calibration"]),
                                "--confirmation-cohort", str(self.cohort[confirmation]),
                                "--confirmation-n1-manifest", str(self.n1[confirmation]),
                                "--calibration-scores", str(scores), "--alpha", ALPHA, *INJECTION, expect=expect)

            # The confirmation cohort's split must be its own: the calibration cohort cannot stand in.
            self.assertIn("the role set confirms on the confirmation split", plan("calibration", expect=2))
            plan("confirmation")
            plan = json.loads((self.repo / f"config/audio-qc-preregistrations/{detector}.json").read_text(
                encoding="utf-8"))
            self.assertEqual((plan["split"]["calibration"]["source"], plan["split"]["confirmation"]["source"]),
                             (f"{corpora.SPEAKER_CORPUS}-calibration", f"{corpora.SPEAKER_CORPUS}-confirmation"))
            self.assertEqual(plan["split"]["speakers"], {"unit": "corpus-speaker", "claim": "identified"})
            pending.append(detector)
        git(self.repo, "add", "config/audio-qc-preregistrations")
        git(self.repo, "commit", "-q", "--no-verify", "-m", "plans", date=PLAN_DATE)
        for detector in pending:
            self.cli("derive", "--detector", detector, "--calibration-scores",
                     str(out / f"{detector}-calibration.json"))
        # The confirmation panels, fresh after the plans: the cohort's and the positives'.
        injections = {entry["takeID"]: entry["injection"] for entry in self.summary["entries"]}
        cohort_bundle = write_bundle(self.root / "bundles" / "confirmation",
                                     panel_manifest(self.cohort["confirmation"]))
        positive_bundle = write_bundle(self.root / "bundles" / "positives", panel_manifest(self.set_path), injections)
        targets = {"identity.clone-similarity@1": {"IDN-IMPOSTOR", "IDN-SHIFT"},
                   "identity.window-drift@1": {"IDN-SWAP"}, "identity.onset-drift@1": {"IDN-ONSET"}}
        for detector in pending:
            scores = out / f"{detector}-confirmation.json"
            self.cli("scores", "--detector", detector, "--role", "confirmation", "--cohort",
                     str(self.cohort["confirmation"]), "--n1-manifest", str(self.n1["confirmation"]),
                     "--bundle", str(cohort_bundle), "--injection-set", str(self.set_path),
                     "--positive-bundle", str(positive_bundle), "--output", str(scores))
            units = json.loads(scores.read_text(encoding="utf-8"))["units"]
            positives = [unit for unit in units if unit["population"] in ("P1", "S")]
            self.assertEqual({unit["injectorID"] for unit in positives}, targets[detector])
            self.assertTrue(all(unit["abstain"] is None for unit in units), detector)
            # An impostor's sham is a cohort take scored against another take: a pairing no negative holds.
            shams = [unit for unit in positives if unit["population"] == "S" and unit["injectorID"] == "IDN-IMPOSTOR"]
            self.assertTrue(all(unit["cleanAudio"] is False for unit in shams))
            severe = [unit["score"] for unit in positives if unit["severity"] == "severe"]
            clean = [unit["score"] for unit in units if unit["population"] == "N2"]
            if detector == "identity.clone-similarity@1":
                self.assertLess(max(severe), min(clean))
            else:
                self.assertGreater(min(severe), max(clean))


if __name__ == "__main__":
    unittest.main()
