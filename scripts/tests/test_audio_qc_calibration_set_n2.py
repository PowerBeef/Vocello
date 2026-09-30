#!/usr/bin/env python3
"""N2 cohorts in the AQ-07 calibration set: word intervals, sampling, language swaps, text and the bridge.

Every take is a procedural speech-like render written as a 24 kHz WAV in a
temporary directory; the aligner's output, the panel bundle and its L1 cache
are synthetic. No audio is committed.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_calibration_set as m2  # noqa: E402
import audio_qc_n2_resynthesis as n2  # noqa: E402
import audio_qc_orchestrator as orchestrator  # noqa: E402
from delivery_analysis_cache import CanonicalAudio, DeliveryAnalysisCache  # noqa: E402
from lib.jsonio import sha256_json  # noqa: E402
from lib.qc_pipeline.evidence import BUNDLE_SCHEMA  # noqa: E402
from lib.qc_pipeline.layered_cache import l1_identity  # noqa: E402
from lib.qc_pipeline.panel_jobs import (  # noqa: E402
    identity_components, judge_scope, panel_identity, panel_request, profile,
)
from lib.qc_qualification import fixtures, injectors, language_swap, pcm, recordings  # noqa: E402

RATE = 24_000
JUDGE = m2.ALIGNER_JUDGE
# Three sentences read twice in each of three aligned languages, and once in Korean (outside the aligner).
LANGUAGES = ("english", "french", "german")
SENTENCES = ("flores-11", "flores-12", "flores-13")
KOREAN = "n1-ko-0001"
SQUEEZED = "n1-en-0000"


def quiet(function, *args, **kwargs):
    with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
        return function(*args, **kwargs)


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def seconds(samples: int) -> float:
    return samples / RATE


def write_cohort(root: Path) -> tuple[Path, dict[str, fixtures.Script]]:
    """A sealed N2 cohort manifest of procedural takes, and each take's script (its true word timing)."""
    takes, scripts = [], {}
    index = 0
    plan = [(sentence, language, reading) for sentence in SENTENCES for language in LANGUAGES
            for reading in range(2)] + [(SENTENCES[0], "korean", 0)]
    for sentence, language, reading in plan:
        n1_id = KOREAN if language == "korean" else f"n1-{language[:2]}-{index:04d}"
        script = fixtures.make_script(700 + index, word_count=8)
        voice = fixtures.VOICES["low" if index % 2 else "high"]
        samples = fixtures.render(script, voice)
        wav = root / "roundtrip" / f"n2-{index:05d}.wav"
        digest = recordings.write_pcm16_wav(wav, samples)
        text = f"{language} reading {reading} of {sentence}: {script.text}"
        takes.append({
            "takeID": f"{n1_id}--n2", "n1TakeID": n1_id, "population": "N2", "family": n1_id,
            "scriptID": sentence, "language": language, "text": text, "textSHA256": text_sha256(text),
            "wavPath": f"roundtrip/n2-{index:05d}.wav", "wavSHA256": digest,
            "durationSeconds": samples.size / RATE, "eligible": True, "clampedSampleCount": 0,
            "codec": {"tokenizerSHA256": "a" * 64, "modelID": "pro_clone_speed", "modelRevision": "b" * 40,
                      "codesSHA256": hashlib.sha256(n1_id.encode()).hexdigest(), "codesPath": "codes.bin",
                      "frameCount": 10, "codebookCount": 16},
            "source": {"planItemID": f"n2-{index:05d}", "n1WAVSHA256": "c" * 64, "inputWAVSHA256": "d" * 64},
        })
        scripts[f"{n1_id}--n2"] = script
        index += 1
    manifest = {"schemaVersion": 1, "kind": n2.MANIFEST_KIND, "runID": "mac-qc-n2-fixture", "planDigest": "e" * 64,
                "n1ManifestSHA256": "f" * 64, "resultSHA256": "0" * 64, "resampler": {}, "codec": {},
                "counts": {"takes": len(takes)}, "takes": takes}
    manifest["manifestDigest"] = n2.self_digest(manifest, "manifestDigest")
    path = root / "n2-manifest.json"
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return path, scripts


def aligner_output(take_id: str, script: fixtures.Script) -> dict:
    """What the aligner's worker returns: units and intervals in seconds (one squeezed unit for SQUEEZED)."""
    intervals = [{"unit": f"w{number}", "start": seconds(start), "end": seconds(end)}
                 for number, (start, end) in enumerate(script.words)]
    units = [item["unit"] for item in intervals]
    if take_id.startswith(SQUEEZED):
        at = intervals[3]["end"]
        intervals.insert(4, {"unit": "squeezed", "start": at, "end": at})
        units.insert(4, "squeezed")
    return {"language": "English", "units": units, "intervals": intervals, "sampleRateHz": 16_000,
            "decodedSampleCount": 1}


def write_panel(root: Path, manifest_path: Path, scripts: dict[str, fixtures.Script], *,
                uncached: str | None = None) -> tuple[Path, Path]:
    """A panel bundle and the L1 entries the orchestrator would have stored for the aligner."""
    registry = json.loads((Path(__file__).resolve().parents[2] / "config/audio-qc-judges.json").read_text())
    judge = registry["judges"][JUDGE]
    execution = judge["execution"]
    components = identity_components(JUDGE, registry, engine=execution["engine"], threads=execution["threads"],
                                     host={"machine": "fixture"})
    identity = panel_identity(JUDGE, registry, components)
    spec, scope = profile(JUDGE), judge_scope(judge)
    source = json.loads(manifest_path.read_text())
    lane = orchestrator.manifest_from_calibration_takes(source, source_sha256="1" * 64,
                                                        base_dir=manifest_path.parent)
    cache_root = root / "cache"
    cache = DeliveryAnalysisCache(cache_root)
    bundle = root / "bundle"
    entries = []
    for number, take in enumerate(lane["takes"], 1):
        canonical_digest = hashlib.sha256(f"canonical:{take['id']}".encode()).hexdigest()
        canonical = CanonicalAudio(take["audioSHA256"], canonical_digest, 1, 1.0, Path("unused"),
                                   "polyphase-kaiser5-v2")
        request = panel_request(spec, scope, take)
        if request is None:
            measurement = {"judge": JUDGE, "status": "out-of-scope", "outputIdentity": identity.output_identity,
                           "reasons": ["out-of-scope"], "metrics": {}}
        else:
            measurement = {"judge": JUDGE, "status": "complete", "outputIdentity": identity.output_identity,
                           "reasons": [], "metrics": {}}
            if take["id"] != uncached:
                cache.store(l1_identity(canonical, identity, request), aligner_output(take["id"], scripts[take["id"]]))
        evidence = {"schema": "vocello.audioqc.take-evidence/1", "measurements": [measurement],
                    "take": {"takeID": take["id"], "audioSHA256": take["audioSHA256"],
                             "canonicalPCMSHA256": canonical_digest, "textSHA256": text_sha256(take["referenceText"]),
                             "language": take["language"], "durationSeconds": take["durationSeconds"]}}
        path = bundle / "evidence" / f"{number:04d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence), encoding="utf-8")
        entries.append({"takeID": take["id"], "evidence": f"evidence/{number:04d}.json",
                        "evidenceSHA256": recordings.file_sha256(path)})
    body = {"schema": BUNDLE_SCHEMA, "runID": "panel-fixture", "manifestSHA256": "2" * 64, "takes": entries}
    (bundle / "bundle.json").write_text(json.dumps({**body, "bundleDigest": sha256_json(body, ascii=False,
                                                                                      allow_nan=False)}))
    return bundle, cache_root


class N2Fixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.manifest_path, cls.scripts = write_cohort(cls.root / "n2")
        cls.bundle, cls.cache_root = write_panel(cls.root, cls.manifest_path, cls.scripts)
        cls.alignments_path = cls.root / "alignments.json"
        cls.alignments = quiet(m2.export_alignments, cls.manifest_path, cls.bundle, cls.alignments_path,
                               cache_root=cls.cache_root)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def manifest(self) -> dict:
        return json.loads(self.manifest_path.read_text())


class CohortAndAlignmentTests(N2Fixture):
    def test_an_n2_cohort_loads_as_eligible_generated_24khz_takes(self) -> None:
        manifest, _ = m2.load_takes(self.manifest_path)
        generated = m2.generated_takes(manifest)
        self.assertEqual(len(generated), 19)
        self.assertEqual(m2.population_of(manifest), "N2")
        self.assertEqual(m2.stratum(generated[0]), "N2/english")
        self.assertEqual({m2.source_rate(take) for take in generated}, {RATE})
        tampered = self.manifest()
        tampered["takes"][0]["text"] = "Changed after the manifest was sealed."
        path = self.root / "tampered.json"
        path.write_text(json.dumps(tampered))
        with self.assertRaisesRegex(m2.CalibrationError, "digest"):
            m2.load_takes(path)

    def test_the_word_rule_maps_seconds_to_samples_and_refuses_bad_alignments(self) -> None:
        pairs = [(0.24, 0.56), (0.56, 0.64), (0.64, 0.64), (0.96, 1.2), (1.2, 1.44), (1.44, 1.68), (1.68, 2.0)]
        alignment = recordings.word_alignment(pairs, frames=int(2.02 * RATE))
        self.assertTrue(alignment.usable)
        self.assertEqual(alignment.words[0], (5_760, 13_440))
        self.assertEqual((alignment.squeezed, len(alignment.words)), (1, 6))
        # 0.64 -> 0.96 is a 320 ms gap: a declared pause; 0.56 -> 0.64 is not a gap at all.
        self.assertEqual(alignment.pauses, ((15_360, 23_040),))
        # An overrun of less than one aligner frame is clamped to the take; more is refused.
        self.assertEqual(recordings.word_alignment(pairs, frames=int(1.95 * RATE)).words[-1][1], int(1.95 * RATE))
        self.assertIn("overruns", recordings.word_alignment(pairs, frames=int(1.9 * RATE)).issue)
        self.assertIn("overlap", recordings.word_alignment([(0.0, 0.5), (0.4, 0.8)] + pairs[3:],
                                                           frames=3 * RATE).issue)
        self.assertIn("fewer than", recordings.word_alignment(pairs[3:], frames=3 * RATE).issue)
        squeezed = [(0.1 * k, 0.1 * k) for k in range(3)] + pairs[3:]
        self.assertIn("squeezed", recordings.word_alignment(squeezed, frames=3 * RATE).issue)
        # A reversed interval is malformed, never counted as squeezed.
        reversed_interval = [(0.4, 0.2)] + pairs[1:]
        self.assertIn("ends before it starts", recordings.word_alignment(reversed_interval, frames=3 * RATE).issue)

    def test_the_export_rebuilds_the_orchestrators_l1_key_and_keeps_no_text(self) -> None:
        export = self.alignments
        self.assertEqual(export["kind"], m2.ALIGNMENTS_KIND)
        self.assertEqual(export["counts"]["byStatus"], {"complete": 18, "out-of-scope": 1})
        self.assertEqual(export["counts"]["wordAlignment"], {"usable": 18})
        self.assertEqual(export["takes"][f"{KOREAN}--n2"]["status"], "out-of-scope")
        record = export["takes"]["n1-en-0000--n2"]
        script = self.scripts["n1-en-0000--n2"]
        self.assertEqual(record["units"], len(script.words) + 1)
        self.assertEqual(record["intervals"][0]["start"], seconds(script.words[0][0]))
        self.assertEqual(record["intervals"][0]["unitSHA256"], text_sha256("w0"))
        self.assertEqual(len(export["aligner"]["outputIdentities"]), 1)
        self.assertEqual(export["aligner"]["judge"], JUDGE)
        self.assertEqual(export["takesSHA256"], pcm.json_digest(export["takes"]))
        written = self.alignments_path.read_text()
        for take in self.manifest()["takes"]:
            self.assertNotIn(take["text"], written)
        self.assertNotIn('"w0"', written)
        # An entry the cache does not hold refuses the export (never guessed, never exported around), and so
        # does a cache root without analysis layers (a pruned confirmation root, or not the panel's own root).
        other = self.root / "uncached"
        bundle, cache_root = write_panel(other, self.manifest_path, self.scripts, uncached="n1-fr-0002--n2")
        with self.assertRaisesRegex(m2.CalibrationError, "no usable L1 entry"):
            quiet(m2.export_alignments, self.manifest_path, bundle, other / "alignments.json", cache_root=cache_root)
        self.assertFalse((other / "alignments.json").exists())
        with self.assertRaisesRegex(m2.CalibrationError, "holds no analysis layers"):
            m2.export_alignments(self.manifest_path, bundle, other / "alignments.json",
                                 cache_root=self.root / "pruned")
        # A bundle whose digest no longer matches is refused.
        record = json.loads((bundle / "bundle.json").read_text())
        record["runID"] = "edited"
        (bundle / "bundle.json").write_text(json.dumps(record))
        with self.assertRaisesRegex(m2.CalibrationError, "digest"):
            m2.export_alignments(self.manifest_path, bundle, other / "again.json", cache_root=cache_root)
        shutil.rmtree(other)

    def test_word_level_injections_on_a_recording_carry_exact_labels(self) -> None:
        manifest, _ = m2.load_takes(self.manifest_path)
        take = next(take for take in m2.generated_takes(manifest) if take["takeID"] == "n1-fr-0002--n2")
        task = {"take": take, "wav": str(m2.take_wav(self.manifest_path, take)),
                "alignment": m2.alignment_context(self.alignments["takes"][take["takeID"]])}
        fixture, _digest, description, status = m2._source_fixture(task)
        script = self.scripts[take["takeID"]]
        self.assertIsNone(status)
        self.assertEqual(fixture.words, script.words)
        self.assertEqual(description["words"], len(script.words))
        fade = int(round(injectors.SPLICE_FADE_MS * RATE / 1000))
        cuts = injectors.boundaries(fixture)
        size = fixture.samples.size
        first = (len(fixture.words) - 2) // 2
        deletion = injectors.inject("CNT-DEL", "moderate", fixture, 7)
        (label,) = deletion.labels
        self.assertEqual((label["startSample"], label["endSample"]), (cuts[first] - fade, cuts[first] - fade))
        self.assertEqual(label["deletedSamples"], cuts[first + 2] - cuts[first])
        self.assertEqual(deletion.samples.size, size - (cuts[first + 2] - cuts[first]) - fade)
        repeat = injectors.inject("CNT-REP", "mild", fixture, 7)
        first = (len(fixture.words) - 1) // 2
        segment = cuts[first + 1] - cuts[first]
        (label,) = repeat.labels
        self.assertEqual(label["startSample"], cuts[first + 1] - fade)
        self.assertEqual(label["endSample"], cuts[first + 1] + segment - 2 * fade)
        start, end = fixture.words[-2]
        truncation = injectors.inject("BND-TRUNC", "moderate", fixture, 7)
        cut = end - int(round(0.5 * (end - start)))
        self.assertEqual(truncation.labels[0]["startSample"], cut)
        self.assertEqual(truncation.samples.size, cut)
        insertion = injectors.inject("CNT-INS", "moderate", fixture, 7)
        self.assertEqual(insertion.labels[0]["words"], 2)
        self.assertEqual(insertion.labels[0]["startSample"], cuts[(len(fixture.words) - 1) // 2] - fade)
        # The squeezed unit is no word; its neighbours stay exact.
        squeezed = next(take for take in m2.generated_takes(manifest) if take["takeID"].startswith(SQUEEZED))
        fixture, _, description, _ = m2._source_fixture(
            {"take": squeezed, "wav": str(m2.take_wav(self.manifest_path, squeezed)),
             "alignment": m2.alignment_context(self.alignments["takes"][squeezed["takeID"]])})
        self.assertEqual(fixture.words, self.scripts[squeezed["takeID"]].words)
        self.assertEqual((description["squeezed"], description["intervals"]), (1, len(fixture.words) + 1))
        # Too few words is a counted refusal, not a crash.
        short = recordings.with_alignment(fixture, recordings.WordAlignment(fixture.words[:2], (), 2, 0, None))
        with self.assertRaises(injectors.InjectorNotApplicable):
            injectors.inject("CNT-DEL", "severe", short, 7)


class AnalysisLockTests(unittest.TestCase):
    def test_an_export_holds_the_host_analysis_lock_shared_and_refuses_an_exclusive_holder(self) -> None:
        import fcntl
        from unittest import mock

        import delivery_resource_supervisor as supervisor

        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(supervisor, "host_analysis_lock_root", return_value=Path(directory)):
            lock = Path(directory) / supervisor.HOST_LOCK_NAME
            with m2.shared_analysis_lock():
                # A prune (exclusive) cannot start while an export reads a cache; another reader can.
                with lock.open("a+b") as prune:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(prune.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with lock.open("a+b") as reader:
                    fcntl.flock(reader.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
            with lock.open("a+b") as holder:
                fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(m2.CalibrationError, "host analysis lock"):
                    with m2.shared_analysis_lock():
                        pass


class SamplingTests(unittest.TestCase):
    def test_the_draw_is_seeded_and_as_even_as_the_pool_allows(self) -> None:
        pool = {**{f"en-{k}": "english" for k in range(10)}, **{f"fr-{k}": "french" for k in range(2)},
                **{f"de-{k}": "german" for k in range(6)}}
        first = m2.stratified_sample(pool, 9, seed=1, key="SIG-CLICK@1")
        self.assertEqual(first, m2.stratified_sample(dict(reversed(list(pool.items()))), 9, seed=1,
                                                     key="SIG-CLICK@1"))
        counts = {language: sum(1 for family in first if pool[family] == language)
                  for language in ("english", "french", "german")}
        # French holds only two, so the other seven split as evenly as round-robin allows.
        self.assertEqual(counts["french"], 2)
        self.assertEqual(sorted((counts["english"], counts["german"])), [3, 4])
        self.assertNotEqual(first, m2.stratified_sample(pool, 9, seed=2, key="SIG-CLICK@1"))
        self.assertNotEqual(first, m2.stratified_sample(pool, 9, seed=1, key="SIG-DROP@2"))
        self.assertEqual(sorted(m2.stratified_sample(pool, 99, seed=1, key="x")), sorted(pool))
        self.assertEqual(m2.stratified_sample(pool, 0, seed=1, key="x"), [])


class N2InjectionTests(N2Fixture):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.set_dir = cls.root / "set"
        cls.summary = quiet(m2.run_inject, cls.manifest_path, cls.set_dir, catalog_seed=7, classes=None, jobs=1,
                            alignments_path=cls.alignments_path, sample_per_cell=6, sample_seed=3)
        cls.set_path = cls.set_dir / "injection-set.json"
        cls.takes = {take["takeID"]: take for take in json.loads(cls.manifest_path.read_text())["takes"]}

    def entries(self, injector_id: str) -> list[dict]:
        return [entry for entry in self.summary["entries"] if entry["injection"]["injectorID"] == injector_id]

    def test_sampling_is_recorded_shared_by_each_cell_and_its_sham_and_stratified(self) -> None:
        summary = self.summary
        self.assertEqual(summary["classes"], ["A", "B", "C", "D", "F"])
        sampling = summary["sampling"]
        self.assertEqual((sampling["perCell"], sampling["seed"]), (6, 3))
        drawn = sampling["injectors"]
        # Word-level injectors draw only from takes with a usable alignment (never Korean).
        self.assertEqual(drawn["CNT-DEL@1"]["needs"], ["words"])
        self.assertNotIn("korean", drawn["CNT-DEL@1"]["eligible"])
        self.assertEqual(drawn["CNT-DEL@1"]["chosen"], {"english": 2, "french": 2, "german": 2})
        # Korean holds one family, so it gives that one and the other five split as evenly as they can.
        chosen = drawn["SIG-DC@1"]["chosen"]
        self.assertEqual((sum(chosen.values()), chosen["korean"]), (6, 1))
        others = [count for language, count in chosen.items() if language != "korean"]
        self.assertLessEqual(max(others) - min(others), 1)
        for key, cell in drawn.items():
            injector_id = key.split("@")[0]
            if injector_id == language_swap.INJECTOR_ID:
                continue
            by_severity: dict[str, set[str]] = {}
            for entry in self.entries(injector_id):
                by_severity.setdefault(entry["injection"]["severity"], set()).add(entry["family"])
            self.assertEqual(set(by_severity), set(m2.SEVERITY_SWEEP), key)
            for severity, families in by_severity.items():
                self.assertEqual(families, set(cell["families"]), f"{key} {severity}")
        self.assertEqual(summary["counts"]["sourceTakes"], len({entry["sourceTakeID"] for entry in summary["entries"]}))
        # The same draw on a rerun, with any job count.
        again = self.root / "again"
        quiet(m2.run_inject, self.manifest_path, again, catalog_seed=7, classes=None, jobs=2,
              alignments_path=self.alignments_path, sample_per_cell=6, sample_seed=3)
        self.assertEqual((again / "injection-set.json").read_bytes(), self.set_path.read_bytes())
        shutil.rmtree(again)

    def test_word_level_variants_run_through_the_catalog_on_aligned_takes(self) -> None:
        plan = {(row["injectorID"], row["severity"]): row for row in self.summary["plan"]}
        self.assertEqual(plan[("BND-TRUNC", "severe")]["variant"], "severe")
        self.assertEqual(plan[("BND-TRUNC", "severe")]["replacesRecordingVariant"], "take-severe")
        self.assertEqual(plan[("CNT-DEL", "mild")]["status"], "scheduled")
        self.assertEqual(plan[("SIG-CLICK", "mild")]["variant"], "take-mild")
        self.assertEqual(plan[("IDN-SHIFT", "mild")]["status"], "out-of-scope")
        for injector_id in ("CNT-DEL", "CNT-REP", "CNT-INS", "PRS-OCT", "PRS-BRK", "BND-TRUNC"):
            entries = self.entries(injector_id)
            self.assertEqual(len(entries), 6 * 4, injector_id)
            for entry in entries:
                self.assertEqual(entry["injection"]["sourceAlignment"]["rule"], recordings.ALIGNMENT_RULE)
                self.assertNotIn("korean", entry["language"])
        self.assertEqual(self.summary["identitySwap"]["status"], "not-applicable")
        self.assertEqual(self.summary["alignments"]["usableTakes"], 18)

    def test_language_swaps_present_another_language_and_a_same_language_sham(self) -> None:
        swaps = self.entries(language_swap.INJECTOR_ID)
        self.assertTrue(swaps)
        by_source: dict[str, dict[str, dict]] = {}
        for entry in swaps:
            by_source.setdefault(entry["sourceTakeID"], {})[entry["injection"]["variant"]] = entry
        for source_id, pair in by_source.items():
            source = self.takes[source_id]
            self.assertEqual(set(pair), {"sham", "severe"})
            for variant, entry in pair.items():
                recipe = entry["injection"]
                donor = self.takes[recipe["donorTakeID"]]
                self.assertNotEqual(donor["takeID"], source_id)
                self.assertEqual(donor["scriptID"], source["scriptID"])
                self.assertEqual((entry["language"], entry["text"]), (source["language"], source["text"]))
                self.assertEqual(entry["family"], donor["family"])
                self.assertEqual(recipe["sourceFamily"], source["family"])
                self.assertEqual((recipe["sourceWAVSHA256"], recipe["donorWAVSHA256"]),
                                 (source["wavSHA256"], donor["wavSHA256"]))
                self.assertEqual(entry["wavSHA256"], donor["wavSHA256"])
                clip, donor_wav = self.set_dir / entry["wavPath"], self.manifest_path.parent / donor["wavPath"]
                self.assertEqual(clip.read_bytes(), donor_wav.read_bytes())
                # A copy, never a hard link to the cohort's own file.
                self.assertNotEqual(clip.stat().st_ino, donor_wav.stat().st_ino)
                self.assertEqual(recipe["mechanism"], "T1-parallel-corpus")
                self.assertEqual(recipe["expectedLanguage"], source["language"])
                self.assertEqual(recipe["audioLanguage"], donor["language"])
                if variant == "severe":
                    self.assertNotEqual(donor["language"], source["language"])
                    self.assertEqual((recipe["severity"], recipe["population"]), ("severe", "P1"))
                    self.assertEqual(recipe["labels"][0]["language"], donor["language"])
                else:
                    self.assertEqual(donor["language"], source["language"])
                    self.assertEqual((recipe["severity"], recipe["population"], recipe["labels"]), ("sham", "S", []))
        # Korean has no second Korean reading, so it is never a source, only a possible donor.
        self.assertNotIn(f"{KOREAN}--n2", by_source)
        # Donors repeat only when a sentence runs out: here each variant's donors are distinct.
        for variant in ("sham", "severe"):
            donors = [pair[variant]["injection"]["donorTakeID"] for pair in by_source.values()]
            self.assertEqual(len(donors), len(set(donors)), variant)

    def test_every_entry_carries_its_bound_text(self) -> None:
        self.assertEqual(self.summary["textPolicy"], m2.TEXT_POLICY_EMBEDDED)
        for entry in self.summary["entries"]:
            source = self.takes[entry["sourceTakeID"]]
            self.assertEqual(entry["text"], source["text"])
            self.assertEqual(entry["textSHA256"], text_sha256(entry["text"]))

    def test_verify_replays_words_and_swaps_and_catches_tampering(self) -> None:
        result = quiet(m2.run_verify, self.set_path, self.manifest_path, jobs=1, alignments_path=self.alignments_path)
        self.assertTrue(result["verified"], result["failures"][:3])
        refused = quiet(m2.run_verify, self.set_path, self.manifest_path, jobs=1)
        self.assertIn("needs its --alignments", " ".join(reason for _, reason in refused["failures"]))
        tampered = self.root / "tampered"
        shutil.copytree(self.set_dir, tampered)
        injection_set = json.loads((tampered / "injection-set.json").read_text())
        swap = next(entry for entry in injection_set["entries"]
                    if entry["injection"]["injectorID"] == language_swap.INJECTOR_ID
                    and entry["injection"]["variant"] == "severe")
        other = next(take for take in self.takes.values()
                     if take["scriptID"] == self.takes[swap["sourceTakeID"]]["scriptID"]
                     and take["takeID"] not in (swap["injection"]["donorTakeID"], swap["sourceTakeID"]))
        swap["injection"]["donorTakeID"] = other["takeID"]
        word = next(entry for entry in injection_set["entries"] if entry["injection"]["injectorID"] == "CNT-DEL")
        word["text"] = "another text"
        injection_set["entriesSHA256"] = pcm.json_digest(injection_set["entries"])
        (tampered / "injection-set.json").write_text(json.dumps(injection_set))
        result = quiet(m2.run_verify, tampered / "injection-set.json", self.manifest_path, jobs=1,
                       alignments_path=self.alignments_path)
        failed = dict(result["failures"])
        self.assertIn("re-derived swap", failed[swap["takeID"]])
        self.assertIn("text", failed[word["takeID"]])
        shutil.rmtree(tampered)
        # A set filtered after the fact, with a recomputed entriesSHA256, is incomplete against its sample.
        filtered = self.root / "filtered"
        shutil.copytree(self.set_dir, filtered)
        injection_set = json.loads((filtered / "injection-set.json").read_text())
        dropped = next(entry for entry in injection_set["entries"] if entry["injection"]["injectorID"] == "SIG-CLICK")
        injection_set["entries"].remove(dropped)
        injection_set["entriesSHA256"] = pcm.json_digest(injection_set["entries"])
        (filtered / "injection-set.json").write_text(json.dumps(injection_set))
        result = quiet(m2.run_verify, filtered / "injection-set.json", self.manifest_path, jobs=1,
                       alignments_path=self.alignments_path)
        self.assertFalse(result["verified"])
        self.assertTrue(any("account for" in reason and dropped["injection"]["variant"] in reason
                            for _where, reason in result["failures"]), result["failures"][:3])
        shutil.rmtree(filtered)

    def test_the_orchestrator_bridge_takes_the_n2_set_with_each_expectation(self) -> None:
        source = json.loads(self.set_path.read_text())
        manifest = orchestrator.manifest_from_calibration_takes(source, source_sha256="9" * 64,
                                                                base_dir=self.set_path.parent)
        orchestrator.validate_manifest(manifest)
        self.assertEqual(len(manifest["takes"]), len(source["entries"]))
        taken = {take["id"]: take for take in manifest["takes"]}
        for entry in source["entries"]:
            take = taken[entry["takeID"]]
            expected = "fail" if entry["injection"]["population"] == "P1" else "pass"
            self.assertEqual(take["expectedOutcome"], expected, entry["takeID"])
            self.assertEqual(take["referenceText"], self.takes[entry["sourceTakeID"]]["text"])
            self.assertEqual(take["language"], self.takes[entry["sourceTakeID"]]["language"])
            self.assertEqual(Path(take["audioPath"]), (self.set_dir / entry["wavPath"]).resolve())
        swap = next(entry for entry in source["entries"]
                    if entry["injection"]["injectorID"] == language_swap.INJECTOR_ID
                    and entry["injection"]["variant"] == "severe")
        self.assertNotEqual(taken[swap["takeID"]]["language"], swap["injection"]["audioLanguage"])
        # The command writes the lane manifest from the set file; an edited entry breaks entriesSHA256.
        output = self.root / "lane-manifest.json"
        with redirect_stdout(StringIO()) as printed:
            self.assertEqual(orchestrator.main(["manifest", "--from-calibration-takes", str(self.set_path),
                                                "--output", str(output)]), 0)
        self.assertEqual(json.loads(printed.getvalue())["takes"], len(source["entries"]))
        source["entries"][0]["text"] = "edited"
        with self.assertRaisesRegex(orchestrator.OrchestratorError, "entriesSHA256"):
            orchestrator.manifest_from_calibration_takes(source, source_sha256="9" * 64, base_dir=self.set_path.parent)


class N2ScoreTests(N2Fixture):
    def test_score_labels_n2_negatives_without_the_unlabeled_bound(self) -> None:
        output = self.root / "score-clean"
        report = quiet(m2.run_score, self.manifest_path, None, output, jobs=1)
        self.assertEqual(report["populations"], {"N2": {"clips": 19, "families": 19, "engineRejected": 0},
                                                 "S": {"clips": 0, "families": 0}, "P1": {"clips": 0, "families": 0}})
        self.assertIn("labeledBound", report["n2"])
        self.assertNotIn("n3", report)
        self.assertNotIn("unlabeledBound", json.dumps(report))
        self.assertIsNone(report["inputs"]["injectionSetSHA256"])
        measurements = json.loads((output / "measurements.json").read_text())
        self.assertEqual({clip["population"] for clip in measurements["clips"]}, {"N2"})
        markdown = (output / "report.md").read_text()
        self.assertNotIn("pi_max", markdown)
        self.assertIn("N2 codec resyntheses", markdown)
        for take in self.manifest()["takes"]:
            self.assertNotIn(take["text"], markdown)

    def test_score_with_a_set_keeps_the_measurement_interface(self) -> None:
        set_dir = self.root / "small-set"
        summary = quiet(m2.run_inject, self.manifest_path, set_dir, catalog_seed=7, classes=("A", "D"), jobs=1,
                        alignments_path=self.alignments_path, sample_per_cell=2, sample_seed=3)
        output = self.root / "score-set"
        report = quiet(m2.run_score, self.manifest_path, set_dir / "injection-set.json", output, jobs=1)
        self.assertEqual(set(report["populations"]), {"N2", "S", "P1"})
        clips = json.loads((output / "measurements.json").read_text())["clips"]
        self.assertEqual(len(clips), 19 + len(summary["entries"]))
        entries = {entry["takeID"]: entry for entry in summary["entries"]}
        for clip in clips:
            self.assertTrue({"clipID", "population", "family", "sourceTakeID", "language", "injection", "fastQC",
                             "observations"} <= set(clip))
            if clip["injection"] is not None:
                self.assertEqual(set(clip["injection"]), {"injector", "injectorID", "variant", "severity", "classes",
                                                          "outputPCMSHA256"})
                self.assertEqual(clip["family"], entries[clip["clipID"]]["family"])
                self.assertTrue({"verdict", "flags", "flagLevels"} <= set(clip["fastQC"]))
        swap = next(row for row in report["detection"] if row["injector"] == language_swap.KEY)
        self.assertEqual((swap["classes"], swap["targets"], swap["target"]), (["D"], [], None))


class N3TextTests(unittest.TestCase):
    def test_an_n3_set_embeds_text_only_when_asked(self) -> None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import test_audio_qc_calibration_set as n3_tests

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            takes = n3_tests.write_takes(root / "takes")
            plain = quiet(m2.run_inject, takes, root / "plain", catalog_seed=7, classes=("A",), jobs=1)
            embedded = quiet(m2.run_inject, takes, root / "embedded", catalog_seed=7, classes=("A",), jobs=1,
                             embed_text=True)
            self.assertTrue(all("text" not in entry for entry in plain["entries"]))
            texts = {take["takeID"]: take["text"] for take in json.loads(takes.read_text())["takes"]}
            self.assertTrue(all(entry["text"] == texts[entry["sourceTakeID"]] for entry in embedded["entries"]))
            self.assertEqual(quiet(m2.run_verify, root / "embedded" / "injection-set.json", takes,
                                   jobs=1)["failures"], [])
            # A language swap needs FLoRes parallel recordings, which natural takes are not.
            swap = quiet(m2.run_inject, takes, root / "d", catalog_seed=7, classes=("D",), jobs=1)
            rows = [row for row in swap["plan"] if row["injectorID"] == language_swap.INJECTOR_ID]
            self.assertEqual({row["status"] for row in rows}, {"not-applicable"})
            self.assertEqual(swap["entries"], [])


if __name__ == "__main__":
    unittest.main()
