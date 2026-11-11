#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/encoder_golden_codes.py"
SPEC = importlib.util.spec_from_file_location("encoder_golden_codes", SCRIPT)
assert SPEC and SPEC.loader
golden_codes = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = golden_codes
SPEC.loader.exec_module(golden_codes)

GOLDEN = json.loads((ROOT / "config/encoder-golden-codes.json").read_text(encoding="utf-8"))


def trace(frames: list[list[int]], *, magic: bytes = b"VQCT", version: int = 1) -> bytes:
    data = magic + struct.pack("<III", version, len(frames), 0)
    for frame in frames:
        data += struct.pack("<H", len(frame)) + struct.pack(f"<{len(frame)}i", *frame)
    return data


class FixtureTests(unittest.TestCase):
    def test_this_host_generates_the_clips_the_golden_file_was_made_from(self):
        # The committed codes describe exact PCM bytes. A host whose math
        # library rounds a sample differently must be told, not compared.
        with tempfile.TemporaryDirectory() as temp:
            described = golden_codes.write_fixture(Path(temp), GOLDEN)
            self.assertEqual(described, GOLDEN["fixture"])
            job = json.loads((Path(temp) / "job.json").read_text(encoding="utf-8"))
            self.assertEqual(job["kind"], "audio-qc-n2-roundtrip-job")
            self.assertEqual([item["id"] for item in job["items"]], ["vowels-low", "syllables", "vowels-high"])
            for item in job["items"]:
                self.assertEqual(golden_codes.sha256_file(Path(temp) / item["wavPath"]), item["wavSHA256"])

    def test_a_fixture_that_differs_from_the_golden_files_is_refused(self):
        altered = json.loads(json.dumps(GOLDEN))
        altered["fixture"]["clips"][0]["pcmSHA256"] = "0" * 64
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(golden_codes.GoldenError):
                golden_codes.write_fixture(Path(temp), altered)

    def test_the_golden_file_holds_both_conventions_for_every_clip_and_they_differ(self):
        clips = [clip["id"] for clip in GOLDEN["fixture"]["clips"]]
        for convention in golden_codes.CONVENTIONS:
            for padding, zeros in golden_codes.PADDINGS.items():
                for clip in clips:
                    frames = GOLDEN["codes"][convention][padding][clip]
                    expected = -(-(6 * 24_000 + zeros) // 1_920)  # 12.5 frames a second, rounded up
                    self.assertEqual(len(frames), expected, (convention, padding, clip))
                    self.assertTrue(all(len(frame) == 16 for frame in frames))
        # A fixture on which the conventions agreed would pin nothing.
        self.assertLess(GOLDEN["conventionsAgree"]["overall"], 0.5)


class TraceTests(unittest.TestCase):
    def read(self, data: bytes) -> list[list[int]]:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "clip.codes.bin"
            path.write_bytes(data)
            return golden_codes.read_codes(path)

    def test_a_trace_reads_back_as_its_frames(self):
        frames = [list(range(index, index + 16)) for index in range(3)]
        self.assertEqual(self.read(trace(frames)), frames)

    def test_malformed_traces_are_refused(self):
        frame = list(range(16))
        for data in (
            trace([frame], magic=b"NOPE"),
            trace([frame], version=2),
            trace([frame])[:-3],
            trace([frame]) + b"\0",
            trace([frame[:15]]),
            trace([]),
        ):
            with self.assertRaises(golden_codes.GoldenError):
                self.read(data)


class CompareTests(unittest.TestCase):
    def codes(self, convention: str, padding: str = "padded") -> dict[str, list[list[int]]]:
        return {clip: [list(frame) for frame in frames]
                for clip, frames in GOLDEN["codes"][convention][padding].items()}

    def test_codes_that_follow_a_convention_pass_only_when_it_is_the_expected_one(self):
        for convention, other in (("adjacent", "reference"), ("reference", "adjacent")):
            verdict = golden_codes.compare(GOLDEN, self.codes(convention), convention)
            self.assertTrue(verdict["passed"], verdict["reasons"])
            self.assertEqual(verdict["follows"], convention)
            self.assertEqual(verdict["rates"][convention]["overall"], 1.0)
            self.assertEqual(verdict["rates"][convention]["padding"], "padded")
            wrong = golden_codes.compare(GOLDEN, self.codes(convention), other)
            self.assertFalse(wrong["passed"])
            self.assertEqual(wrong["follows"], convention)

    def test_the_better_fitting_padding_is_the_one_reported(self):
        verdict = golden_codes.compare(GOLDEN, self.codes("adjacent", "as-is"), "adjacent")
        self.assertEqual(verdict["rates"]["adjacent"]["padding"], "as-is")
        self.assertTrue(verdict["passed"])

    def test_cross_framework_disagreement_in_the_fine_codebooks_still_passes(self):
        # What two frameworks do: the first codebook agrees, the last ones
        # split near-ties differently on about one frame in ten.
        swift = self.codes("adjacent")
        for frames in swift.values():
            for index in range(0, len(frames), 10):
                for codebook in range(10, 16):
                    frames[index][codebook] ^= 1
        verdict = golden_codes.compare(GOLDEN, swift, "adjacent")
        self.assertTrue(verdict["passed"], verdict["reasons"])
        self.assertLess(verdict["rates"]["adjacent"]["overall"], 1.0)
        self.assertEqual(verdict["rates"]["adjacent"]["firstCodebook"], 1.0)

    def test_a_drifted_first_codebook_fails_even_when_the_rest_agree(self):
        swift = self.codes("adjacent")
        for frames in swift.values():
            for index in range(0, len(frames), 8):
                frames[index][0] ^= 1
        verdict = golden_codes.compare(GOLDEN, swift, "adjacent")
        self.assertFalse(verdict["passed"])
        self.assertGreater(verdict["rates"]["adjacent"]["overall"], 0.98)

    def test_codes_for_other_clips_are_an_error_not_a_failure(self):
        swift = self.codes("adjacent")
        swift.pop("syllables")
        with self.assertRaises(golden_codes.GoldenError):
            golden_codes.compare(GOLDEN, swift, "adjacent")


if __name__ == "__main__":
    unittest.main()
