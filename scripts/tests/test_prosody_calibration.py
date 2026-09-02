#!/usr/bin/env python3
"""Unit tests for scripts/prosody_calibration.py.

Builds a tiny labeled corpus of synthetic WAVs and verifies the CLI emits a
valid, usable profile.
"""
import json
import hashlib
import importlib.util
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "scripts"))
from prosody_calibration import corpus_digest, load_labels
from analyze_prosody import ANALYZER_ALGORITHM_VERSION
from prosody_profile import SCHEMA_VERSION

SR = 24000
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CALIBRATION = os.path.join(REPO, "scripts", "prosody_calibration.py")
HISTORY = os.path.join(REPO, "benchmarks", "HISTORY.md")
RUNS = os.path.join(REPO, "benchmarks", "runs")


def write_sine(path, freq, duration, amplitude=0.5, freq_end=None, pause_ranges=None):
    n = int(SR * duration)
    samples = []
    for i in range(n):
        t = i / SR
        f = freq + (freq_end - freq) * (i / n) if freq_end else freq
        samples.append(amplitude * math.sin(2 * math.pi * f * t))
    if pause_ranges:
        for start, end in pause_ranges:
            a = max(0, int(start * SR))
            b = min(n, int(end * SR))
            for i in range(a, b):
                samples[i] = 0.0
    pcm = [max(-32768, min(32767, int(s * 32767))) for s in samples]
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(v.to_bytes(2, "little", signed=True) for v in pcm))


class ProsodyCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.registry_before = self._registry_digest()

    def tearDown(self):
        self.assertEqual(self.registry_before, self._registry_digest(), "unit tests must not mutate benchmark history")
        self.tmp.cleanup()

    @staticmethod
    def _registry_digest():
        digest = hashlib.sha256()
        for path in [HISTORY] + sorted(
            os.path.join(root, name)
            for root, _dirs, files in os.walk(RUNS)
            for name in files if name.endswith(".json")
        ):
            digest.update(os.path.relpath(path, REPO).encode())
            if os.path.isfile(path):
                with open(path, "rb") as handle:
                    digest.update(handle.read())
        return digest.hexdigest()

    @staticmethod
    def _test_env():
        return {**os.environ, "QVOICE_BENCHMARK_HISTORY_TEST_DISABLE": "1"}

    def _generate_corpus(self):
        clips = [
            ("good_01.wav", 140, 2.5, 0.6, 180, None),
            ("good_02.wav", 130, 2.0, 0.5, 170, None),
            ("bad_monotone.wav", 120, 2.5, 0.3, None, None),
            ("bad_pause.wav", 150, 2.0, 0.5, None, [(0.3, 1.7)]),
        ]
        labels = []
        for name, freq, dur, amp, fend, pauses in clips:
            path = os.path.join(self.dir, name)
            write_sine(path, freq, dur, amp, fend, pauses)
            label = "bad" if name.startswith("bad") else "good"
            labels.append({"path": name, "label": label})
        labels_path = os.path.join(self.dir, "labels.jsonl")
        with open(labels_path, "w", encoding="utf-8") as f:
            for entry in labels:
                f.write(json.dumps(entry) + "\n")
        return labels_path

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "requires optional NumPy analysis dependency")
    def test_cli_emits_valid_profile(self):
        labels = self._generate_corpus()
        out = os.path.join(self.dir, "profile.json")
        result = subprocess.run(
            [sys.executable, CALIBRATION, "--labels", labels, "--out", out, "--target-fpr", "0.1"],
            capture_output=True,
            text=True,
            env=self._test_env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.exists(out))
        with open(out, "r", encoding="utf-8") as f:
            profile = json.load(f)
        self.assertEqual(profile["schema_version"], SCHEMA_VERSION)
        # A calibrated profile records the analyzer it was fitted against, so
        # this tracks the constant rather than pinning a historical version.
        self.assertEqual(profile["analyzer_algorithm_version"], ANALYZER_ALGORITHM_VERSION)
        self.assertIn("thresholds", profile)
        for key in ["monotone_f0_std_hz", "pause_max_seconds", "pause_ratio_max"]:
            self.assertIn(key, profile["thresholds"])

    @unittest.skipUnless(importlib.util.find_spec("numpy"), "requires optional NumPy analysis dependency")
    def test_calibrated_profile_flags_bad_clips(self):
        labels = self._generate_corpus()
        out = os.path.join(self.dir, "profile.json")
        subprocess.run(
            [sys.executable, CALIBRATION, "--labels", labels, "--out", out, "--target-fpr", "0.2"],
            check=True,
            env=self._test_env(),
        )
        sys.path.insert(0, os.path.join(REPO, "scripts"))
        from prosody_quality_gate import evaluate
        from prosody_profile import load_profile

        profile = load_profile(out)
        monotone = evaluate(os.path.join(self.dir, "bad_monotone.wav"), profile)
        pause = evaluate(os.path.join(self.dir, "bad_pause.wav"), profile)
        # At least one obvious defect should be flagged on each bad clip.
        self.assertTrue(monotone["flags"] or pause["flags"])

    def test_corpus_digest_includes_referenced_wav_bytes(self):
        labels = self._generate_corpus()
        entries = load_labels(labels)
        before = corpus_digest(entries)
        with open(entries[0]["path"], "ab") as handle:
            handle.write(b"changed")
        after = corpus_digest(entries)
        self.assertNotEqual(before, after)

    def test_corpus_digest_binds_metadata_but_not_paths(self):
        labels = self._generate_corpus()
        entries = load_labels(labels)
        entries[0]["speakerGroup"] = "speaker-a"
        before = corpus_digest(entries)
        entries[0]["speakerGroup"] = "speaker-b"
        self.assertNotEqual(before, corpus_digest(entries))

        original_path = entries[0]["path"]
        relocated = os.path.join(self.dir, "relocated.wav")
        shutil.copyfile(original_path, relocated)
        entries[0]["path"] = relocated
        relocated_digest = corpus_digest(entries)
        entries[0]["path"] = original_path
        self.assertEqual(relocated_digest, corpus_digest(entries))


if __name__ == "__main__":
    unittest.main()
