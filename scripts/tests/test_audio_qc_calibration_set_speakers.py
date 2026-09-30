#!/usr/bin/env python3
"""Speaker-labelled cohorts in the AQ-07 calibration set: speaker donors, impostors and seams (catalog 3).

Every take is a procedural speech-like render written as a 24 kHz WAV in a
temporary directory, read by a procedural voice standing for a speaker; the
aligner's intervals are the scripts' own word timing. No audio is committed.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import hashlib
from io import StringIO
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_calibration_set as m2  # noqa: E402
import audio_qc_n2_resynthesis as n2  # noqa: E402
import audio_qc_orchestrator as orchestrator  # noqa: E402
from lib.qc_qualification import fixtures, pcm, recordings, speaker_donors  # noqa: E402

RATE = 24_000
LANGUAGES = ("english", "french")
GENDERS = {"female": fixtures.VOICES["high"], "male": fixtures.VOICES["low"]}
UNLABELLED = "n1-en-unlabelled"
LONE = "n1-en-lone"
WORDS = 12
SEGMENT_WORDS = 6


def quiet(function, *args, **kwargs):
    with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
        return function(*args, **kwargs)


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_cohort(root: Path) -> tuple[Path, Path]:
    """A sealed N2 cohort whose takes name their speaker and gender, and its word-interval export.

    Per language and gender, two speakers read two scripts each; the first
    reading of each speaker is a two-segment long-form take with a declared
    seam. One take names no speaker, and one speaker reads only once.
    """
    plan = [(language, gender, f"{language[:2]}-{gender[0]}{speaker}", reading)
            for language in LANGUAGES for gender in GENDERS for speaker in range(2) for reading in range(2)]
    plan += [("english", "female", None, 0), ("english", "female", "en-f-lone", 0)]
    takes, intervals = [], {}
    # Each speaker is one procedural voice of its gender's register, with an F0 of its own.
    speakers = list(dict.fromkeys(speaker for _, _, speaker, _ in plan))
    for index, (language, gender, speaker, reading) in enumerate(plan):
        take_id = f"{UNLABELLED}--n2" if speaker is None else f"{LONE}--n2" if speaker == "en-f-lone" \
            else f"n1-{speaker}-{reading}--n2"
        script = fixtures.make_script(800 + index, word_count=WORDS)
        base = GENDERS[gender]
        voice = replace(base, voice_id=str(speaker), f0_hz=base.f0_hz * (1.0 + 0.04 * speakers.index(speaker)))
        samples = fixtures.render(script, voice)
        wav = root / "roundtrip" / f"{take_id}.wav"
        digest = recordings.write_pcm16_wav(wav, samples)
        text = f"{language} reading {reading}: {script.text}"
        take = {"takeID": take_id, "n1TakeID": take_id[:-4], "population": "N2", "family": take_id[:-4],
                "scriptID": f"script-{index:03d}", "language": language, "text": text, "textSHA256": text_sha256(text),
                "wavPath": f"roundtrip/{take_id}.wav", "wavSHA256": digest, "durationSeconds": samples.size / RATE,
                "eligible": True, "gender": gender}
        if speaker is not None:
            take["speaker"] = speaker
        if reading == 0 and speaker is not None:
            take["seamSamples"] = [script.words[SEGMENT_WORDS][0]]
        takes.append(take)
        intervals[take_id] = script.words
    manifest = {"schemaVersion": 1, "kind": n2.MANIFEST_KIND, "runID": "mac-qc-n2-speakers", "planDigest": "e" * 64,
                "n1ManifestSHA256": "f" * 64, "resultSHA256": "0" * 64, "resampler": {}, "codec": {},
                "counts": {"takes": len(takes)}, "takes": takes}
    manifest["manifestDigest"] = n2.self_digest(manifest, "manifestDigest")
    manifest_path = root / "n2-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    records = {take_id: {"language": take["language"], "audioSHA256": take["wavSHA256"], "status": "complete",
                         "intervals": [{"start": start / RATE, "end": end / RATE, "unitSHA256": "0" * 64}
                                       for start, end in intervals[take_id]]}
               for take_id, take in zip(intervals, takes)}
    alignments = {"schemaVersion": 1, "kind": m2.ALIGNMENTS_KIND,
                  "takesManifest": {"sha256": recordings.file_sha256(manifest_path)},
                  "takes": records, "takesSHA256": pcm.json_digest(records)}
    alignments_path = root / "alignments.json"
    alignments_path.write_text(json.dumps(alignments), encoding="utf-8")
    return manifest_path, alignments_path


class SpeakerCohort(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.manifest_path, cls.alignments_path = write_cohort(cls.root / "n2")
        cls.takes = {take["takeID"]: take for take in json.loads(cls.manifest_path.read_text())["takes"]}
        cls.set_dir = cls.root / "set"
        cls.summary = quiet(m2.run_inject, cls.manifest_path, cls.set_dir, catalog_seed=7, classes=("E", "J"), jobs=1,
                            alignments_path=cls.alignments_path, sample_per_cell=6, sample_seed=3)
        cls.set_path = cls.set_dir / "injection-set.json"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def entries(self, injector_id: str) -> list[dict]:
        return [entry for entry in self.summary["entries"] if entry["injection"]["injectorID"] == injector_id]


class DonorPoolTests(unittest.TestCase):
    def test_pools_keep_language_and_gender_and_split_by_speaker(self) -> None:
        takes = [{"takeID": f"t{index}", "language": language, "gender": gender, "speaker": speaker}
                 for index, (language, gender, speaker) in enumerate([
                     ("english", "female", "a"), ("english", "female", "a"), ("english", "female", "b"),
                     ("english", "male", "c"), ("french", "female", "d"), ("english", "female", "")])]
        pool = speaker_donors.DonorPool(takes)
        found = pool.candidates(takes[0])
        self.assertEqual([take["takeID"] for take in found["other-speaker"]], ["t2"])
        self.assertEqual([take["takeID"] for take in found["same-speaker"]], ["t1"])
        # The only other female English speaker has one take: no utterance of hers to stand in as a sham.
        self.assertIn("other utterance of the same speaker", pool.issue(takes[2]))
        self.assertEqual(pool.issue(takes[5]), speaker_donors.NO_LABEL)
        self.assertEqual([take["takeID"] for take in pool.sources()], ["t0", "t1"])
        # A splice's donors must carry word intervals: an ineligible take is never drawn.
        worded = speaker_donors.DonorPool(takes, eligible={"t0", "t1"})
        self.assertIn("another speaker", worded.issue(takes[0]))

    def test_the_choice_is_seeded_fresh_first_and_keyed_by_injector(self) -> None:
        takes = [{"takeID": f"{speaker}{reading}", "language": "english", "gender": "male", "speaker": speaker}
                 for speaker in "abcde" for reading in range(2)]
        pool = speaker_donors.DonorPool(takes)
        sources = [take["takeID"] for take in takes]
        first = pool.choose(sources, seed=3, key="IDN-SWAP@1")
        self.assertEqual(first, pool.choose(sources, seed=3, key="IDN-SWAP@1"))
        self.assertNotEqual(first, pool.choose(sources, seed=4, key="IDN-SWAP@1"))
        self.assertNotEqual(first, pool.choose(sources, seed=3, key="IDN-ONSET@1"))
        by_id = {take["takeID"]: take for take in takes}
        for source, picks in first.items():
            self.assertNotEqual(by_id[picks["other-speaker"]]["speaker"], by_id[source]["speaker"])
            self.assertEqual(by_id[picks["same-speaker"]]["speaker"], by_id[source]["speaker"])
            self.assertNotEqual(picks["same-speaker"], source)
        # Ten sources and eight other-speaker candidates each: a donor repeats only once the pool runs out.
        others = [picks["other-speaker"] for picks in first.values()]
        self.assertEqual(len(set(others[:8])), 8)


class SpeakerInjectionTests(SpeakerCohort):
    def test_the_plan_schedules_donor_splices_impostors_and_seams(self) -> None:
        summary = self.summary
        self.assertEqual(summary["catalogVersion"], 3)
        plan = {(row["injectorID"], row["severity"]): row for row in summary["plan"]}
        for injector_id in ("IDN-SWAP", "IDN-ONSET", "SEAM-VOICE"):
            self.assertEqual(plan[(injector_id, "severe")]["variant"], "take-severe", injector_id)
            self.assertEqual(plan[(injector_id, "sham")]["variant"], "take-sham", injector_id)
        self.assertEqual(plan[("SEAM-DISC", "severe")]["status"], "scheduled")
        self.assertEqual(plan[("IDN-IMPOSTOR", "severe")]["status"], "scheduled")
        self.assertEqual(plan[("SIG-BAND", "severe")]["status"], "out-of-scope")
        self.assertEqual(summary["identitySwap"]["status"], "donor-splice")
        donors = summary["speakerDonors"]
        self.assertEqual((donors["seed"], donors["labelledTakes"]), (3, len(self.takes) - 1))
        self.assertEqual(donors["splices"]["IDN-SWAP@1"]["relations"], ["other-speaker", "same-speaker"])
        sampling = summary["sampling"]["injectors"]
        # Only sources with both donors (never the unlabelled take or the lone speaker) are drawn.
        for key in ("IDN-SWAP@1", "IDN-ONSET@1", "SEAM-VOICE@1", "IDN-IMPOSTOR@1"):
            families = set(sampling[key]["families"])
            self.assertFalse({UNLABELLED, LONE} & families, key)
        # Seam families draw only from long-form takes.
        seamed = {take["family"] for take in self.takes.values() if take.get("seamSamples")}
        self.assertTrue(set(sampling["SEAM-DISC@1"]["families"]) <= seamed)

    def test_splice_donors_are_another_speaker_for_a_positive_and_the_source_speaker_for_a_sham(self) -> None:
        splices = [entry for entry in self.summary["entries"] if "donor" in entry["injection"]]
        self.assertEqual({entry["injection"]["injectorID"] for entry in splices},
                         {"IDN-SWAP", "IDN-ONSET", "SEAM-VOICE"})
        for entry in splices:
            recipe = entry["injection"]
            source, donor = self.takes[entry["sourceTakeID"]], self.takes[recipe["donor"]["takeID"]]
            self.assertNotEqual(donor["takeID"], source["takeID"])
            self.assertEqual((donor["language"], donor["gender"]), (source["language"], source["gender"]))
            self.assertEqual(recipe["donor"]["wavSHA256"], donor["wavSHA256"])
            self.assertEqual(recipe["donor"]["alignment"]["rule"], recordings.ALIGNMENT_RULE)
            self.assertEqual((entry["family"], entry["speaker"]), (source["family"], source["speaker"]))
            self.assertEqual(entry["text"], source["text"])
            if recipe["population"] == "P1":
                self.assertEqual(recipe["donor"]["relation"], "other-speaker")
                self.assertNotEqual(donor["speaker"], source["speaker"])
                (label,) = recipe["labels"]
                self.assertEqual(label["donorRelation"], "other-speaker")
            else:
                self.assertEqual(recipe["donor"]["relation"], "same-speaker")
                self.assertEqual(donor["speaker"], source["speaker"])
                self.assertEqual(recipe["labels"], [])
        # Each injector draws one donor per relation and source, whatever the severity.
        for injector_id in ("IDN-SWAP", "IDN-ONSET"):
            by_source: dict[str, set[str]] = {}
            for entry in self.entries(injector_id):
                if entry["injection"]["population"] == "P1":
                    by_source.setdefault(entry["sourceTakeID"], set()).add(entry["injection"]["donor"]["takeID"])
            self.assertTrue(by_source)
            self.assertTrue(all(len(donors) == 1 for donors in by_source.values()), injector_id)

    def test_impostors_present_another_speaker_as_the_source_speaker(self) -> None:
        impostors = self.entries(speaker_donors.IMPOSTOR_ID)
        self.assertTrue(impostors)
        by_source: dict[str, dict[str, dict]] = {}
        for entry in impostors:
            by_source.setdefault(entry["sourceTakeID"], {})[entry["injection"]["variant"]] = entry
        for source_id, pair in by_source.items():
            source = self.takes[source_id]
            self.assertEqual(set(pair), {"sham", "severe"})
            for variant, entry in pair.items():
                recipe = entry["injection"]
                donor = self.takes[recipe["donorTakeID"]]
                self.assertEqual(recipe["mechanism"], "T1-parallel-corpus")
                self.assertEqual((entry["speaker"], entry["gender"], entry["language"]),
                                 (source["speaker"], source["gender"], source["language"]))
                self.assertEqual((recipe["presentedSpeaker"], recipe["audioSpeaker"]),
                                 (source["speaker"], donor["speaker"]))
                self.assertEqual(recipe["referenceTakeID"], source_id)
                self.assertEqual((entry["text"], entry["family"]), (donor["text"], donor["family"]))
                self.assertEqual((self.set_dir / entry["wavPath"]).read_bytes(),
                                 (self.manifest_path.parent / donor["wavPath"]).read_bytes())
                if variant == "severe":
                    self.assertNotEqual(donor["speaker"], source["speaker"])
                    self.assertEqual((recipe["population"], recipe["labels"][0]["kind"]), ("P1", "impostor"))
                else:
                    self.assertEqual(donor["speaker"], source["speaker"])
                    self.assertNotEqual(donor["takeID"], source_id)
                    self.assertEqual((recipe["population"], recipe["labels"]), ("S", []))

    def test_seam_entries_carry_their_own_seams(self) -> None:
        for entry in self.entries("SEAM-DISC"):
            recipe = entry["injection"]
            source = self.takes[entry["sourceTakeID"]]
            self.assertEqual(recipe["sourceSeams"], source["seamSamples"])
            if recipe["population"] == "P1":
                (label,) = recipe["labels"]
                self.assertIn(label["seamSample"], source["seamSamples"])
            self.assertEqual(entry["seamSamples"], source["seamSamples"])
        # A donor splice moves the seams after it by its length change and keeps those before it.
        moved = 0
        for entry in self.entries("IDN-SWAP"):
            source = self.takes[entry["sourceTakeID"]]
            if not source.get("seamSamples"):
                self.assertNotIn("seamSamples", entry)
                continue
            delta = round(entry["durationSeconds"] * RATE) - round(source["durationSeconds"] * RATE)
            self.assertEqual(entry["injection"]["sourceSeams"], source["seamSamples"])
            for before, after in zip(source["seamSamples"], entry.get("seamSamples", [])):
                self.assertIn(after - before, (0, delta))
                moved += after != before
        self.assertTrue(moved)

    def test_inject_is_deterministic_and_verify_replays_every_donor(self) -> None:
        again = self.root / "again"
        quiet(m2.run_inject, self.manifest_path, again, catalog_seed=7, classes=("E", "J"), jobs=2,
              alignments_path=self.alignments_path, sample_per_cell=6, sample_seed=3)
        self.assertEqual((again / "injection-set.json").read_bytes(), self.set_path.read_bytes())
        shutil.rmtree(again)
        result = quiet(m2.run_verify, self.set_path, self.manifest_path, jobs=1, alignments_path=self.alignments_path)
        self.assertTrue(result["verified"], result["failures"][:3])

    def test_verify_catches_a_changed_donor_a_missing_impostor_and_another_catalog_version(self) -> None:
        tampered = self.root / "tampered"
        shutil.copytree(self.set_dir, tampered)
        injection_set = json.loads((tampered / "injection-set.json").read_text())
        splice = next(entry for entry in injection_set["entries"]
                      if entry["injection"].get("donor", {}).get("relation") == "other-speaker")
        source = self.takes[splice["sourceTakeID"]]
        other = next(take for take in self.takes.values()
                     if take.get("speaker") not in (None, source["speaker"]) and take["gender"] == source["gender"]
                     and take["language"] == source["language"]
                     and take["takeID"] != splice["injection"]["donor"]["takeID"])
        splice["injection"]["donor"]["takeID"] = other["takeID"]
        dropped = next(entry for entry in injection_set["entries"]
                       if entry["injection"]["injectorID"] == speaker_donors.IMPOSTOR_ID)
        injection_set["entries"].remove(dropped)
        injection_set["entriesSHA256"] = pcm.json_digest(injection_set["entries"])
        (tampered / "injection-set.json").write_text(json.dumps(injection_set))
        result = quiet(m2.run_verify, tampered / "injection-set.json", self.manifest_path, jobs=1,
                       alignments_path=self.alignments_path)
        failed = dict(result["failures"])
        self.assertIn("donor differs", failed[splice["takeID"]])
        self.assertTrue(any("impostors recorded" in reason for _where, reason in result["failures"]))
        # A set of another catalog version is refused whole, naming its version.
        injection_set["catalogVersion"] = 2
        (tampered / "injection-set.json").write_text(json.dumps(injection_set))
        result = quiet(m2.run_verify, tampered / "injection-set.json", self.manifest_path, jobs=1,
                       alignments_path=self.alignments_path)
        self.assertFalse(result["verified"])
        ((where, reason),) = result["failures"]
        self.assertEqual(where, "<set>")
        self.assertIn("catalog version 2", reason)
        shutil.rmtree(tampered)

    def test_the_orchestrator_bridge_presents_an_impostor_with_its_own_text(self) -> None:
        source = json.loads(self.set_path.read_text())
        manifest = orchestrator.manifest_from_calibration_takes(source, source_sha256="9" * 64,
                                                                base_dir=self.set_path.parent)
        taken = {take["id"]: take for take in manifest["takes"]}
        impostor = next(entry for entry in source["entries"]
                        if entry["injection"]["injectorID"] == speaker_donors.IMPOSTOR_ID
                        and entry["injection"]["variant"] == "severe")
        take = taken[impostor["takeID"]]
        self.assertEqual(take["referenceText"], self.takes[impostor["injection"]["donorTakeID"]]["text"])
        self.assertEqual(take["expectedOutcome"], "fail")


class NotApplicableTests(SpeakerCohort):
    def test_every_source_without_labels_or_donors_is_counted_with_its_reason(self) -> None:
        whole = self.root / "whole"
        summary = quiet(m2.run_inject, self.manifest_path, whole, catalog_seed=7, classes=("E",), jobs=1,
                        alignments_path=self.alignments_path, sample_per_cell=0, sample_seed=3)
        skipped = summary["notApplicable"]["IDN-SWAP@1"]["byVariant"]["take-severe"]
        reasons = " | ".join(skipped)
        self.assertIn(speaker_donors.NO_LABEL, reasons)
        self.assertIn("other utterance of the same speaker", reasons)
        self.assertEqual(sum(skipped.values()), 2)
        sources = {entry["sourceTakeID"] for entry in summary["entries"]
                   if entry["injection"]["injectorID"] in ("IDN-SWAP", speaker_donors.IMPOSTOR_ID)}
        self.assertFalse({f"{UNLABELLED}--n2", f"{LONE}--n2"} & sources)
        # IDN-SHIFT needs no donor and runs on every take.
        self.assertEqual(len({entry["sourceTakeID"] for entry in summary["entries"]
                              if entry["injection"]["injectorID"] == "IDN-SHIFT"}), len(self.takes))
        self.assertTrue(quiet(m2.run_verify, whole / "injection-set.json", self.manifest_path, jobs=1,
                              alignments_path=self.alignments_path)["verified"])
        shutil.rmtree(whole)

    def test_a_cohort_without_speaker_labels_builds_no_identity_positive(self) -> None:
        manifest = json.loads(self.manifest_path.read_text())
        for take in manifest["takes"]:
            take.pop("speaker", None)
        manifest["manifestDigest"] = n2.self_digest(manifest, "manifestDigest")
        path = self.manifest_path.parent / "unlabelled.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        summary = quiet(m2.run_inject, path, self.root / "unlabelled", catalog_seed=7, classes=("E",), jobs=1,
                        sample_per_cell=0, sample_seed=3)
        plan = {(row["injectorID"], row["severity"]): row for row in summary["plan"]}
        self.assertEqual(plan[("IDN-IMPOSTOR", "severe")]["status"], "not-applicable")
        self.assertEqual(plan[("IDN-IMPOSTOR", "severe")]["reason"], m2.NO_LABELLED_TAKES)
        self.assertEqual(summary["identitySwap"]["status"], "not-applicable")
        self.assertEqual({entry["injection"]["injectorID"] for entry in summary["entries"]}, {"IDN-SHIFT"})
        self.assertIn("IDN-ONSET@1", summary["notApplicable"])
        shutil.rmtree(self.root / "unlabelled")


class SeamScoreTests(SpeakerCohort):
    def test_score_passes_each_clips_own_seams_to_the_seam_z_score(self) -> None:
        set_dir = self.root / "seam-set"
        quiet(m2.run_inject, self.manifest_path, set_dir, catalog_seed=7, classes=("J",), jobs=1,
              alignments_path=self.alignments_path, sample_per_cell=2, sample_seed=3)
        output = self.root / "seam-score"
        quiet(m2.run_score, self.manifest_path, set_dir / "injection-set.json", output, jobs=1)
        clips = json.loads((output / "measurements.json").read_text())["clips"]
        seamed = [clip for clip in clips if clip["injection"] is not None
                  and clip["injection"]["injectorID"] == "SEAM-DISC"]
        self.assertTrue(seamed)
        for clip in seamed:
            self.assertEqual(clip["observations"]["seamCount"], 1)
            self.assertIsNotNone(clip["observations"]["seamDiscontinuityMaxZ"])
        clean = [clip for clip in clips if clip["injection"] is None]
        with_seams = {take_id for take_id, take in self.takes.items() if take.get("seamSamples")}
        for clip in clean:
            self.assertEqual(clip["observations"]["seamCount"], 1 if clip["clipID"] in with_seams else 0)
        shutil.rmtree(set_dir)
        shutil.rmtree(output)


if __name__ == "__main__":
    unittest.main()
