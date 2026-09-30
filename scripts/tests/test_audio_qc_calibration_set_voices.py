#!/usr/bin/env python3
"""Voice donors for SEAM-VOICE on generated long-form takes (class J, the take plan's long-form cell).

A generated long-form take names no corpus speaker, but the voice it was
generated with is its speaker label: its donors are the manifest's other
long-form takes of the same language, of another voice (a positive) or of the
same voice (the sham). Every take here is a procedural speech-like render in
segments joined by exact-zero pauses, as the product's assembler joins them,
written as a 24 kHz WAV in a temporary directory with its `longForm` block.
No audio is committed.
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
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_calibration_set as m2  # noqa: E402
from lib.qc_qualification import fixtures, injectors, pcm, recordings, speaker_donors  # noqa: E402

RATE = 24_000
SEGMENTS = 3
WORDS_PER_SEGMENT = 4
PAUSE = 4_800  # 200 ms of exact zeros before each seam, as the assembler inserts
BRIEF = {"kind": "design", "briefID": "calm-narrator",
         "brief": "A warm, friendly narrator with a calm, measured pace."}
VOICES = {
    "aiden": ({"kind": "builtin", "id": "aiden"}, fixtures.VOICES["low"]),
    "serena": ({"kind": "builtin", "id": "serena"}, fixtures.VOICES["high"]),
    "calm-narrator": (BRIEF, replace(fixtures.VOICES["high"], voice_id="brief", f0_hz=165.0)),
}
# (language, voice, projects): English has the three standard voices, French two Built-in speakers of
# different genders only, so its Built-in takes find no other voice they may take; one English take is a
# single-segment take, which is never a seam source nor a donor.
LAYOUT = (("english", "aiden", 2), ("english", "serena", 2), ("english", "calm-narrator", 2),
          ("french", "aiden", 2), ("french", "serena", 2))
SINGLE = "english-single--aiden"


def quiet(function, *args, **kwargs):
    with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
        return function(*args, **kwargs)


def long_form_samples(index: int, voice: fixtures.Voice, *, segments: int = SEGMENTS) -> tuple[np.ndarray, list[int]]:
    """A script read in segments, each after the first preceded by an exact-zero pause; the seams are where each
    segment after the first starts (its first word's onset)."""
    script = fixtures.make_script(index, word_count=segments * WORDS_PER_SEGMENT)
    samples = fixtures.render(script, voice)
    cuts = [0] + [script.words[segment * WORDS_PER_SEGMENT][0] for segment in range(1, segments)] + [samples.size]
    pieces, seams, length = [], [], 0
    for segment, (start, end) in enumerate(zip(cuts, cuts[1:])):
        if segment:
            pieces.append(np.zeros(PAUSE))
            length += PAUSE
            seams.append(length)
        pieces.append(samples[start:end])
        length += end - start
    return np.concatenate(pieces), seams


def write_long_form_takes(root: Path) -> Path:
    takes = []
    plan = [(language, voice, project) for language, voice, count in LAYOUT for project in range(count)]
    plan.append(("english", "aiden", None))
    for index, (language, voice_id, project) in enumerate(plan):
        voice, render_voice = VOICES[voice_id]
        key = voice_id if voice["kind"] == "builtin" else f"design-{voice_id}"
        take_id = SINGLE if project is None else f"{language}-p{project}--{key}"
        samples, seams = long_form_samples(900 + index, render_voice, segments=1 if project is None else SEGMENTS)
        digest = recordings.write_pcm16_wav(root / "wav" / f"{take_id}.wav", samples)
        pcm16 = recordings.read_pcm16_wav(root / "wav" / f"{take_id}.wav")
        text = f"{language} project {index}"
        take = {"takeID": take_id, "family": f"{take_id}:{index}", "scriptID": f"lf-{index:03d}",
                "language": language, "role": "project", "mode": "custom" if voice["kind"] == "builtin" else "design",
                "variant": "speed", "variation": "expressive", "voice": dict(voice), "seed": 100 + index,
                "cell": "long-form", "text": text, "textSHA256": hashlib.sha256(text.encode()).hexdigest(),
                "wavPath": f"wav/{take_id}.wav", "wavSHA256": digest, "durationSeconds": round(samples.size / RATE, 6),
                "finishReason": "eos", "status": "generated"}
        if seams:
            take["longForm"] = {"schemaVersion": 1, "algorithmVersion": 1, "sampleRate": RATE,
                                "segmentCount": len(seams) + 1, "outputFrameCount": int(pcm16.size),
                                "maximumSegmentBoundaryJump": m2.boundary_jump(pcm16, seams), "seamFrames": seams}
        takes.append(take)
    manifest = {"schemaVersion": 1, "kind": "audio-qc-calibration-takes", "runID": "long-form-voices",
                "planDigest": "0" * 64, "poolDigest": "1" * 64, "split": "calibration", "takes": takes}
    path = root / "takes.json"
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return path


def identity(take: dict) -> str:
    voice = take["voice"]
    return voice.get("id") or voice["briefID"]


class VoiceLabelTests(unittest.TestCase):
    speakers = {"aiden": "male", "serena": "female"}

    def label(self, voice: dict, briefs: dict | None = None) -> dict | None:
        return speaker_donors.voice_label({"voice": voice}, speaker_genders=self.speakers, brief_genders=briefs or {})

    def test_the_voice_is_the_speaker_label_with_the_gender_the_plan_records(self) -> None:
        self.assertEqual(self.label({"kind": "builtin", "id": "aiden"}),
                         {"identity": "builtin:aiden", "gender": "male",
                          "label": {"kind": "builtin", "id": "aiden", "gender": "male"}})
        # A brief is labelled by its id, with a gender only where the policy declares one.
        self.assertEqual(self.label(BRIEF)["label"], {"kind": "design", "briefID": "calm-narrator", "gender": None})
        self.assertEqual(self.label(BRIEF, {"calm-narrator": "female"})["gender"], "female")
        text_only = self.label({"kind": "design", "brief": "A bright presenter."})
        self.assertEqual(text_only["label"]["briefSHA256"], hashlib.sha256(b"A bright presenter.").hexdigest())
        # A clone reference speaker is recorded only as a digest; its corpus gender label stands.
        clone = self.label({"kind": "clone", "source": "libritts-r", "speaker": "1234", "gender": "female",
                            "referenceKey": "ref0123456789ab"})
        self.assertEqual(clone["gender"], "female")
        self.assertNotIn("1234", json.dumps(clone["label"]))
        self.assertEqual(clone["label"]["speakerSHA256"], hashlib.sha256(b"libritts-r|1234").hexdigest())
        # An unknown gender is unrecorded; a voice of no known kind is no label.
        self.assertIsNone(self.label({"kind": "builtin", "id": "eric"})["gender"])
        self.assertIsNone(self.label({"kind": "builtin"}))
        self.assertIsNone(speaker_donors.voice_label({}, speaker_genders={}, brief_genders={}))

    def test_the_committed_take_policy_gives_the_builtin_genders(self) -> None:
        genders = m2.voice_genders()
        self.assertEqual((genders["speakers"]["aiden"], genders["speakers"]["serena"]), ("male", "female"))
        # Policy version 2 declares no brief gender: every Voice Design voice is gender-unrecorded.
        self.assertEqual(genders["briefs"], {})


class VoicePoolTests(unittest.TestCase):
    @staticmethod
    def pool(rows, *, eligible=None):
        takes = [{"takeID": take_id, "language": language, "voice": {"kind": "builtin", "id": voice}}
                 for take_id, language, voice in rows]
        genders = {"a": "male", "b": "male", "c": "female"}
        labels = {take["takeID"]: speaker_donors.voice_label(take, speaker_genders=genders, brief_genders={})
                  for take in takes}
        return takes, speaker_donors.VoicePool(takes, labels, eligible=eligible)

    def test_a_donor_is_another_voice_whose_gender_does_not_differ_and_the_sham_the_same_voice(self) -> None:
        takes, pool = self.pool([("a1", "en", "a"), ("a2", "en", "a"), ("b1", "en", "b"), ("c1", "en", "c"),
                                 ("u1", "en", "u"), ("a3", "fr", "a")])
        found = pool.candidates(takes[0])
        # b is male like a; c is female, never drawn for a male voice; u records no gender, so it may be.
        self.assertEqual([take["takeID"] for take in found["other-voice"]], ["b1", "u1"])
        self.assertEqual([take["takeID"] for take in found["same-voice"]], ["a2"])
        # An unrecorded gender takes any other voice; a lone voice has no sham.
        self.assertEqual([take["takeID"] for take in pool.candidates(takes[4])["other-voice"]],
                         ["a1", "a2", "b1", "c1"])
        self.assertIn("other long-form take of the same voice", pool.issue(takes[3]))
        # Donors share the source's language.
        self.assertIn("another voice", pool.issue(takes[5]))
        self.assertEqual([take["takeID"] for take in pool.sources()], ["a1", "a2"])
        # Only a long-form take (one that declares seams) is ever a donor.
        takes, narrow = self.pool([("a1", "en", "a"), ("a2", "en", "a"), ("b1", "en", "b")], eligible={"a1", "a2"})
        self.assertIn("another voice", narrow.issue(takes[0]))
        self.assertEqual(speaker_donors.VoicePool([{"takeID": "x", "language": "en"}], {"x": None}).issue(
            {"takeID": "x", "language": "en"}), speaker_donors.NO_VOICE)

    def test_the_choice_is_seeded_fresh_first_and_keyed_by_injector(self) -> None:
        rows = [(f"{voice}{take}", "en", voice) for voice in "ab" for take in range(4)]
        takes, pool = self.pool(rows)
        sources = [take["takeID"] for take in takes]
        first = pool.choose(sources, seed=3, key="SEAM-VOICE@1")
        self.assertEqual(first, pool.choose(sources, seed=3, key="SEAM-VOICE@1"))
        self.assertNotEqual(first, pool.choose(sources, seed=4, key="SEAM-VOICE@1"))
        for source, picks in first.items():
            self.assertNotEqual(picks["other-voice"][0], source[0])
            self.assertEqual(picks["same-voice"][0], source[0])
            self.assertNotEqual(picks["same-voice"], source)
        # Four sources of voice a and four candidates of voice b: no donor repeats before the pool runs out.
        self.assertEqual(len({first[source]["other-voice"] for source in sources if source[0] == "a"}), 4)


class LongFormVoiceInjectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.takes_path = write_long_form_takes(cls.root / "takes")
        cls.takes = {take["takeID"]: take for take in json.loads(cls.takes_path.read_text())["takes"]}
        cls.set_dir = cls.root / "set"
        cls.summary = quiet(m2.run_inject, cls.takes_path, cls.set_dir, catalog_seed=7, classes=("J",), jobs=1,
                            sample_seed=5)
        cls.set_path = cls.set_dir / "injection-set.json"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def seam_voice(self) -> list[dict]:
        return [entry for entry in self.summary["entries"] if entry["injection"]["injectorID"] == "SEAM-VOICE"]

    def test_the_plan_draws_voice_donors_for_seam_voice(self) -> None:
        plan = {(row["injectorID"], row["severity"]): row for row in self.summary["plan"]}
        for severity in ("sham", "mild", "moderate", "severe"):
            self.assertEqual(plan[("SEAM-VOICE", severity)]["variant"], f"take-voice-{severity}")
            self.assertEqual(plan[("SEAM-VOICE", severity)]["status"], "scheduled")
            self.assertEqual(plan[("SEAM-DISC", severity)]["variant"], severity)
        self.assertNotIn("speakerDonors", self.summary)
        voices = self.summary["voiceDonors"]
        self.assertEqual((voices["seed"], voices["labelledTakes"]), (5, len(self.takes)))
        self.assertEqual(voices["splices"]["SEAM-VOICE@1"]["relations"], ["other-voice", "same-voice"])
        self.assertIn({"kind": "builtin", "id": "serena", "gender": "female"}, voices["voices"])
        self.assertIn({"kind": "design", "briefID": "calm-narrator", "gender": None}, voices["voices"])
        self.assertEqual(self.summary["longForm"], m2.LONG_FORM_ENTRY_RULE)
        # A standard N3 manifest (no seams) keeps the speaker-donor take-* rows, as before.
        rows = {row["severity"]: row["variant"] for row in m2.build_plan(("J",)) if row["injectorID"] == "SEAM-VOICE"}
        self.assertEqual(rows["severe"], "take-severe")

    def test_donors_follow_the_identity_rules(self) -> None:
        entries = self.seam_voice()
        self.assertTrue(entries)
        positives = 0
        genders = {"aiden": "male", "serena": "female", "calm-narrator": None}
        for entry in entries:
            recipe = entry["injection"]
            source, donor = self.takes[entry["sourceTakeID"]], self.takes[recipe["donor"]["takeID"]]
            self.assertNotEqual(donor["takeID"], source["takeID"])
            self.assertEqual(donor["language"], source["language"])
            self.assertIn("longForm", donor)
            self.assertEqual(recipe["donor"]["wavSHA256"], donor["wavSHA256"])
            self.assertEqual(recipe["donor"]["seamSamples"], donor["longForm"]["seamFrames"])
            self.assertEqual(recipe["donor"]["voice"]["gender"], genders[identity(donor)])
            if recipe["population"] == "P1":
                positives += 1
                self.assertEqual(recipe["donor"]["relation"], "other-voice")
                self.assertNotEqual(identity(donor), identity(source))
                self.assertNotIn({genders[identity(donor)], genders[identity(source)]}, ({"male", "female"},))
                (label,) = recipe["labels"]
                self.assertEqual(label["donorRelation"], "other-voice")
                self.assertIn(label["donorSeamSample"], donor["longForm"]["seamFrames"])
            else:
                self.assertEqual(recipe["donor"]["relation"], "same-voice")
                self.assertEqual(identity(donor), identity(source))
                self.assertEqual(recipe["labels"], [])
        # English: every long-form take has both donors (the Built-in speakers take the brief, the brief either).
        english = {entry["sourceTakeID"] for entry in entries if self.takes[entry["sourceTakeID"]]["language"] == "english"}
        self.assertEqual(english, {take_id for take_id, take in self.takes.items()
                                   if take["language"] == "english" and "longForm" in take})
        self.assertEqual(positives, 3 * len(english))

    def test_a_voice_without_a_donor_is_counted_with_its_reason(self) -> None:
        # French pairs a male and a female Built-in speaker only: no other voice either may take.
        french = [entry for entry in self.seam_voice() if self.takes[entry["sourceTakeID"]]["language"] == "french"]
        self.assertEqual(french, [])
        reasons = self.summary["notApplicable"]["SEAM-VOICE@1"]["byVariant"]["take-voice-severe"]
        self.assertTrue(any("long-form take of another voice" in reason for reason in reasons), reasons)
        self.assertEqual(sum(count for reason, count in reasons.items() if "another voice" in reason), 4)
        # The single-segment take has no seam to act at.
        self.assertTrue(any("seam offsets" in reason for reason in reasons), reasons)

    def test_labels_seams_and_long_form_blocks_describe_each_output(self) -> None:
        moved = 0
        for entry in self.seam_voice():
            recipe = entry["injection"]
            source = self.takes[entry["sourceTakeID"]]
            samples = recordings.read_pcm16_wav(self.set_dir / entry["wavPath"])
            source_samples = recordings.read_pcm16_wav(self.takes_path.parent / source["wavPath"])
            seams = source["longForm"]["seamFrames"]
            self.assertEqual(recipe["sourceSeams"], seams)
            self.assertEqual(len(entry["seamSamples"]), len(seams))
            block = entry["longForm"]
            self.assertEqual((block["outputFrameCount"], block["seamFrames"]), (samples.size, entry["seamSamples"]))
            self.assertEqual(block["maximumSegmentBoundaryJump"], m2.boundary_jump(samples, entry["seamSamples"]))
            delta = samples.size - source_samples.size
            if recipe["population"] != "P1":
                continue
            (label,) = recipe["labels"]
            start, end = label["startSample"], label["endSample"]
            # Exactly the replaced samples: the source before, the source moved by the length change after.
            self.assertEqual((start, end - start, delta), (label["seamSample"], label["donorSamples"],
                                                            label["donorSamples"] - label["replacedSamples"]))
            self.assertIn(start, seams)
            self.assertTrue(np.array_equal(samples[:start], source_samples[:start]))
            self.assertTrue(np.array_equal(samples[end:], source_samples[end - delta:]))
            self.assertEqual(entry["seamSamples"], [seam if seam <= start else seam + delta for seam in seams])
            moved += any(after != before for before, after in zip(seams, entry["seamSamples"]))
        # A whole-segment splice before the last seam moved the seams after it.
        self.assertTrue(moved)

    def test_verify_replays_and_score_reads_the_output_seams(self) -> None:
        again = self.root / "again"
        quiet(m2.run_inject, self.takes_path, again, catalog_seed=7, classes=("J",), jobs=2, sample_seed=5)
        self.assertEqual((again / "injection-set.json").read_bytes(), self.set_path.read_bytes())
        shutil.rmtree(again)
        result = quiet(m2.run_verify, self.set_path, self.takes_path, jobs=1)
        self.assertTrue(result["verified"], result["failures"][:3])
        score = self.root / "score"
        quiet(m2.run_score, self.takes_path, self.set_path, score, jobs=1)
        clips = {clip["clipID"]: clip for clip in json.loads((score / "measurements.json").read_text())["clips"]}
        for entry in self.seam_voice():
            clip = clips[entry["takeID"]]
            self.assertEqual(clip["longForm"], entry["longForm"])
        shutil.rmtree(score)

    def test_a_sampled_set_draws_only_sources_with_both_voice_donors(self) -> None:
        sampled = self.root / "sampled"
        summary = quiet(m2.run_inject, self.takes_path, sampled, catalog_seed=7, classes=("J",), jobs=1,
                        sample_per_cell=3, sample_seed=5)
        cell = summary["sampling"]["injectors"]["SEAM-VOICE@1"]
        self.assertEqual(cell["needs"], ["seams", "voice-donor"])
        self.assertEqual(cell["eligible"], {"english": 6})
        self.assertEqual(len(cell["families"]), 3)
        result = quiet(m2.run_verify, sampled / "injection-set.json", self.takes_path, jobs=1)
        self.assertTrue(result["verified"], result["failures"][:3])
        shutil.rmtree(sampled)

    def test_verify_catches_a_changed_donor_block_and_gender(self) -> None:
        tampered = self.root / "tampered"
        shutil.copytree(self.set_dir, tampered)
        path = tampered / "injection-set.json"
        injection_set = json.loads(path.read_text())
        positive = next(entry for entry in injection_set["entries"]
                        if entry["injection"].get("donor", {}).get("relation") == "other-voice")
        positive["injection"]["donor"]["voice"]["id"] = "serena"
        block = next(entry for entry in injection_set["entries"] if entry is not positive and "longForm" in entry
                     and entry["injection"]["injectorID"] == "SEAM-VOICE")
        block["longForm"]["maximumSegmentBoundaryJump"] += 1
        injection_set["entriesSHA256"] = pcm.json_digest(injection_set["entries"])
        path.write_text(json.dumps(injection_set))
        failed = dict(quiet(m2.run_verify, path, self.takes_path, jobs=1)["failures"])
        self.assertIn("donor differs", failed[positive["takeID"]])
        self.assertIn("longForm block", failed[block["takeID"]])
        shutil.rmtree(tampered)
        # A take policy that now records another gender re-derives other voices: verify says so.
        policy = json.loads(m2.TAKE_POLICY.read_text(encoding="utf-8"))
        policy["designBriefs"]["calm-narrator"]["gender"] = "female"
        changed = self.root / "policy.json"
        changed.write_text(json.dumps(policy), encoding="utf-8")
        with mock.patch.object(m2, "TAKE_POLICY", changed):
            result = quiet(m2.run_verify, self.set_path, self.takes_path, jobs=1)
        self.assertFalse(result["verified"])
        self.assertTrue(any("genders differ" in reason for _where, reason in result["failures"]))

    def test_a_procedural_donor_splice_matches_the_injector(self) -> None:
        # The calibration set's recipe replays through the catalog: the same donor fixture, the same digest.
        entry = next(entry for entry in self.seam_voice() if entry["injection"]["variant"] == "take-voice-severe")
        source = self.takes[entry["sourceTakeID"]]
        donor = self.takes[entry["injection"]["donor"]["takeID"]]
        fixture = recordings.recording_fixture(source["takeID"], source["family"], "N3/english/custom",
                                               recordings.read_pcm16_wav(self.takes_path.parent / source["wavPath"]),
                                               seams=source["longForm"]["seamFrames"])
        donor_fixture = recordings.recording_fixture(donor["takeID"], donor["family"], "N3/english/custom",
                                                     recordings.read_pcm16_wav(self.takes_path.parent / donor["wavPath"]),
                                                     seams=donor["longForm"]["seamFrames"])
        replay = injectors.inject("SEAM-VOICE", "take-voice-severe", fixture, entry["injection"]["seed"],
                                  donor=donor_fixture)
        self.assertEqual(replay.digest, entry["injection"]["outputPCMSHA256"])


if __name__ == "__main__":
    unittest.main()
