#!/usr/bin/env python3
"""The AQ-07 injected-defect set over natural takes and its report-only scorer (M2).

Takes are procedural speech-like renders written to WAVs in a temporary
directory at run time; no WAV is committed.
"""

from __future__ import annotations

import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_calibration_set as m2  # noqa: E402
from lib.qc_qualification import fixtures, injectors, pcm, pcm_measures, recordings, stats  # noqa: E402

LANGUAGES = ("english", "english", "french")
# Recording variants on the pinned procedural source 1 at seed 7: a changed
# digest means a changed construction (bump the injector's version).
RECORDING_GOLDENS = {
    ("SIG-CLICK", "take-sham"): "d0f9db35ba8a45aa0e8ff6d2802c71bb20ab4d41b5db0a4f5f34cf1b78b2964f",
    ("SIG-CLICK", "take-mild"): "958526ff7e4bb462f4ab77e9f4a2602ab64cca825130e3d86d5e7c2981e2c71d",
    ("SIG-CLICK", "take-moderate"): "597af962878c50141c3ccce1d3542bc2e6ae6760c6559ecb5f231c5cb5251ec5",
    ("SIG-CLICK", "take-severe"): "062a2f684f457dc8e10d86c214a4e5ccb66662c06ca1b8085ee6df9909b063f4",
    ("SIG-DROP", "take-sham"): "d0f9db35ba8a45aa0e8ff6d2802c71bb20ab4d41b5db0a4f5f34cf1b78b2964f",
    ("SIG-DROP", "take-mild"): "13cedec983ea841b473ee09a08f290cfc79eb1f493e1b9223aa02ba44fc6e7db",
    ("SIG-DROP", "take-moderate"): "2f4491386d0632aa27c5dc4e0021cff2adadc2537ba400b11a96e5c3bd8de823",
    ("SIG-DROP", "take-severe"): "eb0a4dc8bb13d41a1375f94c4a21525c74983f38a4a1170b72fd159f0d974821",
    ("SIG-NOISE", "take-sham"): "d0f9db35ba8a45aa0e8ff6d2802c71bb20ab4d41b5db0a4f5f34cf1b78b2964f",
    ("SIG-NOISE", "take-mild"): "3fd2befd715db307a408a8cac2d6942b4dada958ee6639005d2b13cb6b1777a2",
    ("SIG-NOISE", "take-moderate"): "c34792d2ac13aa352fbfeca8edda3396ebfdf1a8cd2003db5010e1c0bbb7519a",
    ("SIG-NOISE", "take-severe"): "57309e9146cd2ae44ca607b1367ac19049d67d0fdc1e90484a6dc6bb3640a1bd",
    ("BND-TRUNC", "take-mild"): "0110b581d6f1a2a3d741db7b99a557468a43ffc2f7d69dcb7b2d6e6582f259de",
    ("BND-TRUNC", "take-moderate"): "b0b133923e6bc474dd9fb2c8b5abc83ed646ff6e6702ed2f5e1c0873b50bb76c",
    ("BND-TRUNC", "take-severe"): "7849dff408eb0a1b16807a493f31d5b8e229d1c732b8a17d6d421cf4994348bd",
    ("BND-RUNON", "take-sham"): "e77ab082e7b4169dc34ace5775b16789b70a21c5c19f43628adb9748386c332d",
    ("BND-RUNON", "take-mild"): "75312b3703275b63ed43be1f851a488248bfbc93e65c383d65e5ef04c63e9778",
    ("BND-RUNON", "take-moderate"): "fa180c257c50d7521e94d16c52264829ffbfac8b88e528fb41f8b4d8574843ae",
    ("BND-RUNON", "take-severe"): "9e16f41eb89ecc34ca8cb7f95993870e062796e61fe8be37cf1e918922cbba91",
}


def write_takes(root: Path, *, shared_family: bool = False, rejected: bool = False) -> Path:
    """Three scripts, each rendered by two voices (donor pairs), and one missing take."""
    takes = []
    voices = {"aiden": fixtures.VOICES["low"], "serena": fixtures.VOICES["high"]}
    for script_index, language in enumerate(LANGUAGES):
        script = fixtures.make_script(500 + script_index, word_count=7)
        for voice_id, voice in voices.items():
            samples = fixtures.render(script, voice)
            take_id = f"s{script_index:04d}__custom-{voice_id}__s{11 + script_index}"
            wav = recordings.write_pcm16_wav(root / "wav" / f"{take_id}.wav", samples)
            family = f"s{script_index:04d}__shared" if shared_family else take_id
            takes.append({"takeID": take_id, "family": family, "scriptID": f"s{script_index:04d}",
                          "language": language, "mode": "custom", "variant": "speed",
                          "voice": {"kind": "builtin", "id": voice_id}, "seed": 11 + script_index,
                          "text": script.text, "wavPath": f"wav/{take_id}.wav", "wavSHA256": wav,
                          "durationSeconds": round(samples.size / 24_000, 3), "finishReason": "eos",
                          "status": "generated"})
    takes.append({"takeID": "s0009__custom-aiden__s9", "family": "s0009__custom-aiden__s9", "scriptID": "s0009",
                  "language": "english", "mode": "custom", "variant": "speed",
                  "voice": {"kind": "builtin", "id": "aiden"}, "seed": 9, "text": "", "wavPath": None,
                  "wavSHA256": None, "durationSeconds": None, "finishReason": None, "status": "missing"})
    if rejected:
        # The engine's mandatory Fast QC refused this take: no audio, only its flags.
        takes.append({"takeID": "s0008__custom-serena__s8", "family": "s0008__custom-serena__s8",
                      "scriptID": "s0008", "language": "french", "mode": "custom", "variant": "speed",
                      "voice": {"kind": "builtin", "id": "serena"}, "seed": 8, "text": "", "wavPath": None,
                      "wavSHA256": None, "durationSeconds": None, "finishReason": None, "status": "rejected",
                      "rejection": {"errorCode": "audio.quality_rejected",
                                    "audioQCFlags": ["dropout:2512ms", "speaking_rate_slow"]}})
    manifest = {"schemaVersion": 1, "kind": "audio-qc-calibration-takes", "runID": "test-run",
                "planDigest": "0" * 64, "poolDigest": "1" * 64, "split": "calibration", "takes": takes}
    path = root / "takes.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def quiet(function, *args, **kwargs):
    with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
        return function(*args, **kwargs)


class RecordingAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        cls.takes_path = write_takes(root)
        manifest, _ = m2.load_takes(cls.takes_path)
        cls.take = m2.generated_takes(manifest)[0]
        cls.source, cls.digest = recordings.load_recording(
            m2.take_wav(cls.takes_path, cls.take), take_id=cls.take["takeID"], family=cls.take["family"],
            stratum=m2.stratum(cls.take), text=cls.take["text"], expected_sha256=cls.take["wavSHA256"])

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def test_a_recording_knows_its_pcm_and_nothing_else(self) -> None:
        source = self.source
        self.assertEqual((source.words, source.pauses, source.script, source.voice), ((), (), None, None))
        self.assertEqual(source.family, self.take["family"])
        with wave.open(str(m2.take_wav(self.takes_path, self.take)), "rb") as reader:
            stored = np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")
        # Read at 1/32767, the source's PCM16 is exactly the file's.
        self.assertTrue(np.array_equal(pcm.to_pcm16(source.samples), stored))
        with self.assertRaises(recordings.RecordingError):
            recordings.load_recording(m2.take_wav(self.takes_path, self.take), take_id="x", family="x",
                                      stratum="x", expected_sha256="0" * 64)

    def test_word_level_variants_are_not_applicable_and_the_rest_apply(self) -> None:
        refused = set()
        for injector in injectors.CATALOG.values():
            for variant in injector.variants:
                needs = injectors.needs(injector.injector_id, variant.parameters)
                if needs:
                    with self.assertRaises(injectors.InjectorNotApplicable, msg=f"{injector.key} {variant.name}"):
                        injectors.inject(injector.injector_id, variant.name, self.source, 7)
                    refused.add(injector.injector_id)
                else:
                    injection = injectors.inject(injector.injector_id, variant.name, self.source, 7)
                    self.assertEqual(injection.source_digest, self.source.digest)
            for variant in injector.recording_variants:
                if "donor" in variant.parameters:
                    # A donor splice (catalog version 3) needs the words of a speaker-labelled recording and
                    # its donor, which a natural take never has.
                    self.assertTrue({"words", "donor"} <= set(injectors.needs(injector.injector_id,
                                                                             variant.parameters)))
                    with self.assertRaises(injectors.InjectorNotApplicable, msg=f"{injector.key} {variant.name}"):
                        injectors.inject(injector.injector_id, variant.name, self.source, 7)
                    continue
                self.assertEqual(injectors.needs(injector.injector_id, variant.parameters), ())
                injection = injectors.inject(injector.injector_id, variant.name, self.source, 7)
                self.assertEqual(bool(injection.labels), injection.positive, f"{injector.key} {variant.name}")
        # Word-aligned edits, voiced or quiet clicks, speech-referenced noise, word-level
        # truncation and run-on, pitch edits in the longest word, identity swaps and the seam families.
        self.assertEqual(refused, {"SIG-CLICK", "SIG-DROP", "SIG-NOISE", "BND-TRUNC", "BND-RUNON", "CNT-REP",
                                   "CNT-DEL", "CNT-INS", "PRS-OCT", "PRS-BRK", "IDN-SWAP", "IDN-ONSET",
                                   "SEAM-DISC", "SEAM-VOICE"})
        with self.assertRaises(injectors.InjectorNotApplicable) as refusal:
            injectors.inject("IDN-SWAP", "moderate", self.source, 7)
        self.assertIn("word intervals", str(refusal.exception))
        self.assertIn("procedural script", str(refusal.exception))

    def test_recording_variants_are_exact_and_pinned(self) -> None:
        source = self.source
        size = source.samples.size
        drop = injectors.inject("SIG-DROP", "take-moderate", source, 7)
        (label,) = drop.labels
        self.assertEqual(label["endSample"] - label["startSample"], 14_400)
        self.assertEqual(label["startSample"], (size - 14_400) // 2)
        changed = np.flatnonzero(drop.samples != source.samples)
        self.assertTrue(label["startSample"] <= changed[0] and changed[-1] < label["endSample"])
        cut = injectors.inject("BND-TRUNC", "take-severe", source, 7)
        self.assertEqual(cut.samples.size, round(0.5 * size))
        self.assertEqual(cut.labels[0]["basis"], "take-fraction")
        run_on = injectors.inject("BND-RUNON", "take-moderate", source, 7)
        (label,) = run_on.labels
        self.assertEqual(label["endSample"], run_on.samples.size)
        self.assertTrue(np.array_equal(run_on.samples[:label["startSample"]], source.samples[:label["startSample"]]))
        clicks = injectors.inject("SIG-CLICK", "take-moderate", source, 7)
        self.assertEqual(sorted(int(index) for index in np.flatnonzero(clicks.samples != source.samples)),
                         [label["startSample"] for label in clicks.labels])
        short = recordings.recording_fixture("short", "short", "N3/test", source.samples[:24_000])
        with self.assertRaises(injectors.InjectorNotApplicable):
            injectors.inject("SIG-DROP", "take-severe", short, 7)
        procedural = fixtures.clean_fixture(1, "modal")
        for (injector_id, variant), expected in RECORDING_GOLDENS.items():
            first = injectors.inject(injector_id, variant, procedural, 7)
            second = injectors.inject(injector_id, variant, procedural, 7)
            self.assertEqual(first.digest, second.digest)
            self.assertEqual(first.digest, expected, f"{injector_id} {variant}")

    def test_recording_variants_stay_out_of_the_catalog_description(self) -> None:
        described = {variant["name"] for injector in injectors.catalog_description()["injectors"]
                     for variant in injector["variants"]}
        self.assertFalse({name for name in described if name.startswith("take-")})


class CalibrationSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.takes_path = write_takes(cls.root / "takes")
        cls.set_dir = cls.root / "set"
        cls.summary = quiet(m2.run_inject, cls.takes_path, cls.set_dir, catalog_seed=7,
                            classes=m2.DEFAULT_CLASSES, jobs=1)
        cls.set_path = cls.set_dir / "injection-set.json"
        cls.score_dir = cls.root / "score"
        cls.report = quiet(m2.run_score, cls.takes_path, cls.set_path, cls.score_dir, jobs=1)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.directory.cleanup()

    def test_the_set_covers_every_applicable_variant(self) -> None:
        summary = self.summary
        self.assertEqual(summary["kind"], "audio-qc-injection-set")
        self.assertEqual(summary["counts"]["generatedTakes"], 6)
        self.assertEqual(summary["counts"]["missingTakes"], 1)
        entries = summary["entries"]
        plan = {(row["injectorID"], row["severity"]): row for row in summary["plan"]}
        self.assertEqual(plan[("SIG-CLICK", "mild")]["variant"], "take-mild")
        self.assertEqual(plan[("SIG-CLICK", "mild")]["replaces"], "mild")
        self.assertEqual(plan[("BND-TRUNC", "sham")]["variant"], "sham")
        self.assertEqual(plan[("CNT-DEL", "mild")]["status"], "out-of-scope")
        self.assertEqual(plan[("IDN-SHIFT", "mild")]["status"], "out-of-scope")
        applied = {(entry["injection"]["injectorID"], entry["injection"]["severity"]) for entry in entries}
        for injector_id in ("SIG-CLICK", "SIG-DROP", "SIG-CLIP", "SIG-DC", "SIG-LEVEL", "SIG-NOISE", "SIG-SIL",
                            "BND-TRUNC", "BND-RUNON", "PRS-RATE"):
            for severity in m2.SEVERITY_SWEEP:
                self.assertIn((injector_id, severity), applied)
        # Word-level prosody edits are not applicable on every take, with their reason.
        for key in ("PRS-OCT@1", "PRS-BRK@1"):
            skipped = summary["notApplicable"][key]
            self.assertEqual(skipped["count"], 6 * 4)
            (reason,) = {reason for reasons in skipped["byVariant"].values() for reason in reasons}
            self.assertIn("word intervals", reason)
            self.assertNotIn("__custom-", reason)
        self.assertEqual(summary["identitySwap"]["status"], "deferred")
        self.assertEqual(summary["identitySwap"]["donorPairs"], 3)
        entry = next(entry for entry in entries if entry["injection"]["variant"] == "take-severe"
                     and entry["injection"]["injectorID"] == "SIG-CLICK")
        source = next(take for take in json.loads(self.takes_path.read_text())["takes"]
                      if take["takeID"] == entry["sourceTakeID"])
        self.assertEqual(entry["family"], source["family"])
        self.assertEqual(entry["scriptID"], source["scriptID"])
        self.assertNotIn("text", entry)
        self.assertEqual(entry["injection"]["mechanism"], "T1-pcm-construction")
        self.assertEqual(entry["injection"]["sourceWAVSHA256"], source["wavSHA256"])
        self.assertEqual(entry["injection"]["seed"], m2.derive_seed(source["wavSHA256"], "SIG-CLICK@1", 7))
        self.assertEqual(entry["wavSHA256"], recordings.file_sha256(self.set_dir / entry["wavPath"]))
        self.assertEqual(len({entry["takeID"] for entry in entries}), len(entries))
        self.assertEqual(summary["entriesSHA256"], pcm.json_digest(entries))

    def test_inject_is_deterministic_across_runs_and_job_counts(self) -> None:
        again = self.root / "again"
        quiet(m2.run_inject, self.takes_path, again, catalog_seed=7, classes=m2.DEFAULT_CLASSES, jobs=2)
        self.assertEqual((again / "injection-set.json").read_bytes(), self.set_path.read_bytes())
        for entry in self.summary["entries"][:40]:
            self.assertEqual((again / entry["wavPath"]).read_bytes(), (self.set_dir / entry["wavPath"]).read_bytes())
        other = self.root / "other-seed"
        changed = quiet(m2.run_inject, self.takes_path, other, catalog_seed=8, classes=("A",), jobs=1)
        self.assertNotEqual(changed["entriesSHA256"], self.summary["entriesSHA256"])
        shutil.rmtree(again)
        shutil.rmtree(other)

    def test_verify_replays_and_catches_tampering(self) -> None:
        result = quiet(m2.run_verify, self.set_path, self.takes_path, jobs=2)
        self.assertTrue(result["verified"], result["failures"][:3])
        self.assertEqual(result["entries"], len(self.summary["entries"]))
        tampered = self.root / "tampered"
        shutil.copytree(self.set_dir, tampered)
        entry = next(entry for entry in self.summary["entries"] if entry["injection"]["severity"] == "moderate")
        wav = tampered / entry["wavPath"]
        with wave.open(str(wav), "rb") as reader:
            params, frames = reader.getparams(), bytearray(reader.readframes(reader.getnframes()))
        frames[200] ^= 0x01
        with wave.open(str(wav), "wb") as writer:
            writer.setparams(params)
            writer.writeframes(bytes(frames))
        result = quiet(m2.run_verify, tampered / "injection-set.json", self.takes_path, jobs=1)
        self.assertFalse(result["verified"])
        self.assertEqual([clip for clip, _ in result["failures"]], [entry["takeID"]])
        # A recipe edited in place breaks the entries digest and its own replay.
        injection_set = json.loads((tampered / "injection-set.json").read_text())
        injection_set["entries"][0]["injection"]["seed"] += 1
        (tampered / "injection-set.json").write_text(json.dumps(injection_set))
        result = quiet(m2.run_verify, tampered / "injection-set.json", self.takes_path, jobs=1)
        reasons = " ".join(reason for _, reason in result["failures"])
        self.assertIn("entriesSHA256", reasons)
        self.assertIn("seed differs", reasons)
        shutil.rmtree(tampered)

    def test_score_writes_privacy_safe_measurements_and_a_report(self) -> None:
        report = self.report
        measurements = json.loads((self.score_dir / "measurements.json").read_text())
        self.assertEqual(measurements["kind"], "audio-qc-calibration-measurements")
        clips = measurements["clips"]
        self.assertEqual(measurements["clipCount"], len(clips))
        self.assertEqual(measurements["clipsSHA256"], pcm.json_digest(clips))
        self.assertEqual(len(clips), 6 + len(self.summary["entries"]))
        clip = clips[0]
        self.assertEqual(clip["population"], "N3")
        self.assertIn(clip["fastQC"]["verdict"], ("pass", "warn", "fail"))
        self.assertTrue(set(m2.FASTQC_FIELDS) <= set(clip["fastQC"]))
        self.assertIn("integratedLoudnessLUFS", clip["observations"])
        # Every clip carries the PCM shape measures, stamped with the code that measured them.
        self.assertEqual({item["pcmMeasures"]["sourceSHA256"] for item in clips},
                         {pcm_measures.source_sha256()})

        def injected(injector: str, severity: str) -> list[dict]:
            return [item for item in clips if (item["injection"] or {}).get("injectorID") == injector
                    and item["injection"]["severity"] == severity]
        for item in injected("SIG-SIL", "severe"):
            self.assertGreaterEqual(item["pcmMeasures"]["trailingDigitalSilenceMS"], 10_000.0)
        for item in injected("SIG-CLIP", "severe"):
            # Hard clipping below full scale flattens both polarities at the level it limits to.
            self.assertGreater(item["pcmMeasures"]["symmetricFlatTopFraction"], 0.0)
        for item in clips:
            if item["population"] == "N3":
                self.assertEqual(item["pcmMeasures"]["symmetricFlatTopFraction"], 0.0)
        populations = {clip["population"] for clip in clips}
        self.assertEqual(populations, {"N3", "S", "P1"})
        texts = [take["text"] for take in json.loads(self.takes_path.read_text())["takes"] if take["text"]]
        for name in ("measurements.json", "report.json", "report.md"):
            written = (self.score_dir / name).read_text()
            for text in texts:
                self.assertNotIn(text, written, name)
        self.assertEqual(report["schema"], "vocello.audioqc.calibration-report/1")
        self.assertTrue(report["reportOnly"])
        self.assertEqual(report["populations"]["N3"], {"clips": 6, "families": 6, "engineRejected": 0})
        self.assertEqual(set(report["languages"]["rows"]), {"english", "french"})
        self.assertIn(report["languages"]["worstN3Alarm"]["language"], {"english", "french"})
        self.assertEqual({row["flag"] for row in report["flags"]}, set(m2.audio_qc.FASTQC_V8_FLAGS))
        severities = {(row["injector"], row["severity"]) for row in report["detection"]}
        self.assertIn(("SIG-CLIP@2", "severe"), severities)
        clip_severe = next(row for row in report["detection"]
                           if row["injector"] == "SIG-CLIP@2" and row["severity"] == "severe")
        # Hard clipping below full scale lowers the peak and is invisible to v8's over-range count.
        self.assertLess(clip_severe["observationMedianDelta"]["truePeakDBTP"], 0.0)
        dc_severe = next(row for row in report["detection"]
                         if row["injector"] == "SIG-DC@1" and row["severity"] == "severe")
        self.assertEqual((dc_severe["target"]["events"], dc_severe["fail"]["events"]), (6, 6))
        french = report["languages"]["rows"]["french"]["severeTargetDetection"]["SIG-DC@1"]
        self.assertEqual((french["events"], french["units"]), (2, 2))
        worst_dc = next(entry for entry in report["languages"]["worstSevereDetection"]
                        if entry["injector"] == "SIG-DC@1")
        self.assertEqual(worst_dc["language"], "french")
        level = next(row for row in report["detection"]
                     if row["injector"] == "SIG-LEVEL@1" and row["severity"] == "moderate")
        self.assertAlmostEqual(level["observationMedianDelta"]["integratedLoudnessLUFS"], -30.0, delta=0.2)
        markdown = (self.score_dir / "report.md").read_text()
        self.assertIn("f / (1 - pi_max)", json.dumps(report["n3"]["unlabeledBound"]))
        self.assertIn("### Detection of T1 injections on natural takes (P1)", markdown)
        self.assertIn("qualifies nothing", markdown)

    def test_an_engine_rejected_take_counts_as_a_natural_fail_without_audio(self) -> None:
        root = self.root / "rejected"
        root.mkdir()
        takes_path = write_takes(root, rejected=True)
        summary = quiet(m2.run_inject, takes_path, root / "set", catalog_seed=7, classes=m2.DEFAULT_CLASSES, jobs=1)
        self.assertEqual(summary["counts"]["generatedTakes"], 6)
        self.assertNotIn("s0008__custom-serena__s8", {entry["sourceTakeID"] for entry in summary["entries"]})
        report = quiet(m2.run_score, takes_path, root / "set" / "injection-set.json", root / "score", jobs=1)
        self.assertEqual(report["populations"]["N3"], {"clips": 7, "families": 7, "engineRejected": 1})
        self.assertEqual(report["n3"]["engineRejected"]["takes"], 1)
        self.assertEqual(report["n3"]["engineRejected"]["flags"], {"dropout": 1, "speaking_rate_slow": 1})
        self.assertEqual(report["n3"]["fail"]["events"], self.report["n3"]["fail"]["events"] + 1)
        self.assertEqual(report["n3"]["fail"]["units"], 7)
        dropout = next(row for row in report["flags"] if row["flag"] == "dropout")
        before = next(row for row in self.report["flags"] if row["flag"] == "dropout")
        self.assertEqual(dropout["n3"]["fail"]["events"], before["n3"]["fail"]["events"] + 1)
        self.assertTrue(any("mandatory Fast QC refused" in line for line in report["headline"]))

    def test_rejection_levels_never_overcount_a_fail(self) -> None:
        self.assertEqual(m2.rejection_levels(["dropout:2512ms", "speaking_rate_slow"]),
                         {"dropout": "fail", "speaking_rate_slow": "warn"})
        # A fail-only family explains the fail; a warn-or-fail family then counts at warn.
        self.assertEqual(m2.rejection_levels(["terminal_silence:3100ms", "clicks"]),
                         {"clicks": "warn", "terminal_silence": "fail"})
        # Two warn-or-fail families: which one failed is unknown, so both count at warn.
        self.assertEqual(m2.rejection_levels(["dropout:1300ms", "clipping"]),
                         {"clipping": "warn", "dropout": "warn"})
        self.assertEqual(m2.rejection_levels(["not_a_v8_flag"]), {})

    def test_rates_use_exact_clopper_pearson_bounds(self) -> None:
        report = self.report
        alarm = report["n3"]["alarm"]
        self.assertEqual(alarm["upper"], round(stats.cp_upper(alarm["events"], alarm["units"]), 6))
        for row in report["detection"]:
            target = row["target"]
            if target:
                self.assertEqual(target["lower"], round(stats.cp_lower(target["events"], target["units"]), 6))
        language = report["languages"]["rows"]["english"]["alarmSimultaneous"]
        confidence = stats.bonferroni_confidence(0.95, 2)
        self.assertEqual(language["upper"],
                         round(stats.cp_upper(language["events"], language["units"], confidence), 6))
        pi = report["n3"]["unlabeledBound"]["farBoundAtPiMax"]["0.1"]
        self.assertAlmostEqual(pi, min(1.0, alarm["upper"] / 0.9), places=5)

    def test_the_command_line_runs_all_three_commands(self) -> None:
        output = self.root / "cli"
        with redirect_stderr(StringIO()), redirect_stdout(StringIO()) as printed:
            self.assertEqual(m2.main(["inject", "--takes", str(self.takes_path), "--output", str(output / "set"),
                                      "--classes", "A", "--jobs", "1"]), 0)
            self.assertEqual(m2.main(["verify", "--set", str(output / "set" / "injection-set.json"),
                                      "--takes", str(self.takes_path), "--jobs", "1"]), 0)
            self.assertEqual(m2.main(["score", "--takes", str(self.takes_path), "--set",
                                      str(output / "set" / "injection-set.json"), "--output", str(output / "score"),
                                      "--jobs", "1"]), 0)
            # A set is scored only against the takes manifest it was built from.
            other = json.loads(self.takes_path.read_text())
            other["runID"] = "another-run"
            other_path = self.takes_path.with_name("other-takes.json")
            other_path.write_text(json.dumps(other))
            self.assertEqual(m2.main(["score", "--takes", str(other_path), "--set", str(self.set_path),
                                      "--output", str(output / "mismatch"), "--jobs", "1"]), 1)
            other_path.unlink()
        self.assertIn("verify: PASS", printed.getvalue())
        shutil.rmtree(output)


class LongFormSeamTests(unittest.TestCase):
    """A take of the take plan's long-form cell records its seams in its `longForm` block, not as `seamSamples`:
    the seam injectors read them there."""

    def test_the_long_form_block_gives_the_seams(self) -> None:
        block = {"schemaVersion": 1, "algorithmVersion": 1, "sampleRate": recordings.ENGINE_SAMPLE_RATE,
                 "segmentCount": 2, "outputFrameCount": 48_000, "maximumSegmentBoundaryJump": 0, "seamFrames": [24_000]}
        self.assertEqual(m2.take_seams({"longForm": block}), [24_000])
        self.assertEqual(m2.take_seams({"longForm": block, "seamSamples": [12_000]}), [12_000])
        self.assertEqual(m2.take_seams({"longForm": {**block, "sampleRate": 16_000}}), [])
        self.assertEqual(m2.take_seams({}), [])

    def test_seam_injectors_run_on_a_long_form_take(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = fixtures.make_script(700, word_count=10)
            samples = fixtures.render(script, fixtures.VOICES["low"])
            digest = recordings.write_pcm16_wav(root / "wav" / "lf.wav", samples)
            pcm16 = recordings.read_pcm16_wav(root / "wav" / "lf.wav")
            seam = script.words[5][0]
            block = {"schemaVersion": 1, "algorithmVersion": 1, "sampleRate": recordings.ENGINE_SAMPLE_RATE,
                     "segmentCount": 2, "outputFrameCount": int(pcm16.size),
                     "maximumSegmentBoundaryJump": m2.boundary_jump(pcm16, [seam]), "seamFrames": [seam]}
            take = {"takeID": "lf__custom-aiden__s1", "family": "lf__custom-aiden__s1", "scriptID": "lf",
                    "language": "english", "mode": "custom", "variant": "speed", "cell": "long-form",
                    "voice": {"kind": "builtin", "id": "aiden"}, "seed": 1, "text": script.text,
                    "wavPath": "wav/lf.wav", "wavSHA256": digest, "durationSeconds": round(samples.size / 24_000, 3),
                    "finishReason": "eos", "status": "generated", "longForm": block}
            manifest = {"schemaVersion": 1, "kind": "audio-qc-calibration-takes", "runID": "long-form",
                        "planDigest": "0" * 64, "poolDigest": "1" * 64, "split": "calibration", "takes": [take]}
            takes_path = root / "takes.json"
            takes_path.write_text(json.dumps(manifest), encoding="utf-8")
            summary = quiet(m2.run_inject, takes_path, root / "set", catalog_seed=7, classes=("J",), jobs=1)
            plan = {(row["injectorID"], row["severity"]): row["status"] for row in summary["plan"]}
            self.assertEqual(plan[("SEAM-DISC", "severe")], "scheduled")
            entries = [entry for entry in summary["entries"] if entry["injection"]["injectorID"] == "SEAM-DISC"]
            self.assertEqual(sorted(entry["injection"]["severity"] for entry in entries),
                             ["mild", "moderate", "severe", "sham"])
            self.assertTrue(all(entry["injection"]["sourceSeams"] == [seam] for entry in entries))
            verified = quiet(m2.run_verify, root / "set" / "injection-set.json", takes_path, jobs=1)
            self.assertTrue(verified["verified"], verified["failures"])


class FamilyClusteringTests(unittest.TestCase):
    """Rates count source families (policy thresholdDerivation.unitOfRates), never clips."""

    @staticmethod
    def record(clip: str, family: str, population: str, verdict: str, *, flags: dict | None = None,
               injector: str | None = None, severity: str | None = None, language: str = "english") -> dict:
        return {"clipID": clip, "population": population, "family": family, "sourceTakeID": clip,
                "language": language, "injector": None if injector is None else f"{injector}@1",
                "injectorID": injector, "variant": severity, "severity": severity, "verdict": verdict,
                "flagLevels": flags or {}, "observations": {name: None for name in m2.OBSERVATION_MEASURES}}

    def test_a_family_errs_once_and_a_positive_family_needs_every_clip(self) -> None:
        records = [
            self.record("a1", "fa", "N3", "warn", flags={"clicks": "warn"}),
            self.record("a2", "fa", "N3", "pass"),
            self.record("b1", "fb", "N3", "pass"),
            self.record("c1", "fc", "N3", "pass", language="french"),
            self.record("a-sham", "fa", "S", "pass", injector="SIG-CLICK", severity="sham"),
            self.record("a-p", "fa", "P1", "warn", flags={"clicks": "warn"}, injector="SIG-CLICK", severity="severe"),
            self.record("a-p2", "fa", "P1", "pass", injector="SIG-CLICK", severity="severe"),
            self.record("b-p", "fb", "P1", "fail", flags={"clicks": "fail"}, injector="SIG-CLICK",
                        severity="severe"),
        ]
        report = m2.build_report(records, inputs={}, injection_set={})
        self.assertEqual((report["n3"]["alarm"]["events"], report["n3"]["alarm"]["units"]), (1, 3))
        self.assertEqual(report["n3"]["alarm"]["upper"], round(stats.cp_upper(1, 3), 6))
        self.assertEqual(report["n3"]["flags"]["clicks"]["warnOrWorse"]["events"], 1)
        self.assertEqual(report["n3"]["flags"]["clicks"]["fail"]["events"], 0)
        (row,) = report["detection"]
        # fa has one missed clip, so only fb counts as detected.
        self.assertEqual((row["target"]["events"], row["target"]["units"]), (1, 2))
        (sham,) = report["shams"]
        self.assertEqual(sham["a4"]["cleanSameFamilies"]["events"], 1)
        self.assertEqual(sham["a4"]["cleanSameFamilies"]["units"], 1)
        self.assertEqual(report["languages"]["rows"]["french"]["alarm"]["units"], 1)

    def test_takes_sharing_a_family_count_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            takes = write_takes(root / "takes", shared_family=True)
            quiet(m2.run_inject, takes, root / "set", catalog_seed=7, classes=("A",), jobs=1)
            report = quiet(m2.run_score, takes, root / "set" / "injection-set.json", root / "score", jobs=1)
        self.assertEqual(report["populations"]["N3"], {"clips": 6, "families": 3, "engineRejected": 0})
        self.assertEqual(report["n3"]["alarm"]["units"], 3)
        for row in report["detection"]:
            self.assertEqual(row["alarm"]["units"], 3, row["injector"])


if __name__ == "__main__":
    unittest.main()
