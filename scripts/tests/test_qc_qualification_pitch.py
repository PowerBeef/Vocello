#!/usr/bin/env python3
"""The T1 catalog's pitch shifter and tempo stretch reach the pitch they label (catalog version 4).

Up to catalog version 3 the shifter's plain overlap-add left most speaking
voices near their original pitch, so its positives did not carry the defect
they labelled. These tests measure the output's pitch with YIN, written here in
NumPy, on synthetic harmonic voices with 1% vibrato: every shift lands within
0.5 st of its target, a tempo change keeps the pitch, and PRS-ERRATIC, PRS-OCT
and PRS-BRK read the shift of each span they label.
"""

from __future__ import annotations

import math
from pathlib import Path
import sys
from typing import NamedTuple
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.qc_qualification import fixtures, injectors  # noqa: E402

RATE = 24_000
SEED = 7
VOICE_F0S = (85.0, 110.0, 140.0, 180.0, 220.0, 280.0)
SHIFTS = (-12.0, -7.0, -4.0, -2.0, 2.0, 4.0, 7.0, 12.0)
# YIN's aperiodicity threshold: a frame whose normalized difference never dips below it is unvoiced.
YIN_THRESHOLD = 0.1
# Clear of the 5 ms crossfades that straddle each labelled span's boundaries.
SPAN_MARGIN = int(0.01 * RATE)


def harmonic_voice(f0: float, seconds: float) -> np.ndarray:
    """Harmonics up to 5 kHz at 1/h, a 5 Hz vibrato of 1%, 20 ms raised-cosine edges, peak 0.3."""
    time = np.arange(int(round(seconds * RATE))) / RATE
    phase = 2.0 * math.pi * np.cumsum(f0 * (1.0 + 0.01 * np.sin(2.0 * math.pi * 5.0 * time))) / RATE
    count = int(5_000.0 // (1.01 * f0))
    voice = sum(np.sin(harmonic * phase) / harmonic for harmonic in range(1, count + 1))
    edge = int(0.02 * RATE)
    ramp = 0.5 - 0.5 * np.cos(math.pi * (np.arange(edge) + 0.5) / edge)
    voice[:edge] *= ramp
    voice[voice.size - edge:] *= ramp[::-1]
    return 0.3 * voice / float(np.max(np.abs(voice)))


def voice_fixture(f0: float, seconds: float, *, words: tuple[tuple[int, int], ...] = ()) -> fixtures.Fixture:
    name = f"harmonic-voice-{int(f0)}"
    return fixtures.make_fixture(name, name, "modal", harmonic_voice(f0, seconds), words=words)


class Track(NamedTuple):
    """A YIN frame track: each frame's first sample, its F0 in Hz (NaN when unvoiced), and the frame length."""

    starts: np.ndarray
    f0: np.ndarray
    length: int

    def median(self, start: int, end: int) -> float:
        """The median F0 of the voiced frames lying wholly inside [start, end)."""
        inside = (self.starts >= start) & (self.starts + self.length <= end)
        voiced = self.f0[inside & np.isfinite(self.f0)]
        if voiced.size < 3:
            raise AssertionError(f"fewer than three voiced frames in [{start}, {end})")
        return float(np.median(voiced))


def f0_track(samples: np.ndarray, *, fmin: float, fmax: float, hop: int = 48) -> Track:
    """YIN (de Cheveigné and Kawahara, 2002) on frames every `hop` samples.

    The difference function over an integration window of the longest period,
    its cumulative-mean normalization, the first lag that dips below
    YIN_THRESHOLD followed down to its local minimum, and a parabolic refinement.
    """
    shortest, longest = int(RATE // fmax), int(math.ceil(RATE / fmin))
    width = longest
    length = width + longest
    starts = np.arange(0, samples.size - length + 1, hop)
    frames = samples[starts[:, None] + np.arange(length)[None, :]]
    size = 1 << (length - 1).bit_length()
    lagged = np.fft.irfft(np.fft.rfft(frames, size) * np.conj(np.fft.rfft(frames[:, :width], size)), size)
    squares = np.concatenate([np.zeros((starts.size, 1)), np.cumsum(frames * frames, axis=1)], axis=1)
    energy = squares[:, width:width + longest + 1] - squares[:, :longest + 1]
    difference = energy[:, :1] + energy - 2.0 * lagged[:, :longest + 1]
    normalized = np.ones_like(difference)
    normalized[:, 1:] = difference[:, 1:] * np.arange(1, longest + 1) / np.maximum(
        np.cumsum(difference[:, 1:], axis=1), 1e-12)
    f0 = np.full(starts.size, np.nan)
    for index, row in enumerate(normalized):
        if energy[index, 0] < 1e-6 * width:
            continue
        below = np.flatnonzero(row[shortest:longest] < YIN_THRESHOLD)
        if not below.size:
            continue
        lag = shortest + int(below[0])
        while lag + 1 < longest and row[lag + 1] < row[lag]:
            lag += 1
        before, at, after = row[lag - 1], row[lag], row[lag + 1]
        bend = before - 2.0 * at + after
        f0[index] = RATE / (lag + (0.5 * (before - after) / bend if bend > 0 else 0.0))
    return Track(starts, f0, length)


def semitones(frequency: float, reference: float) -> float:
    return 12.0 * math.log2(frequency / reference)


def span_shift(output: Track, source: Track, start: int, end: int) -> float:
    """The shift a labelled span reads, against the source over the same frames, clear of its crossfades."""
    first, last = start + SPAN_MARGIN, end - SPAN_MARGIN
    return semitones(output.median(first, last), source.median(first, last))


class PitchShiftTests(unittest.TestCase):
    def test_every_shift_reaches_its_pitch_and_keeps_the_length(self) -> None:
        # The steady part: the middle second of 1.4 s, clear of the edges.
        steady = (int(0.2 * RATE), int(1.2 * RATE))
        for f0 in VOICE_F0S:
            source = harmonic_voice(f0, 1.4)
            reference = f0_track(source, fmin=35.0, fmax=700.0).median(*steady)
            self.assertLess(abs(semitones(reference, f0)), 0.05, f0)
            for shift in SHIFTS:
                shifted = injectors.pitch_shift(source, shift)
                self.assertEqual(shifted.size, source.size, f"{f0} Hz {shift:+} st")
                measured = semitones(f0_track(shifted, fmin=35.0, fmax=700.0).median(*steady), reference)
                self.assertLess(abs(measured - shift), 0.5, f"{f0} Hz {shift:+} st read {measured:+.2f} st")

    def test_a_zero_shift_and_a_unit_stretch_are_the_identity(self) -> None:
        source = harmonic_voice(140.0, 1.0)
        np.testing.assert_allclose(injectors.pitch_shift(source, 0.0), source, rtol=0, atol=1e-9)
        np.testing.assert_allclose(injectors.wsola_stretch(source, 1.0), source, rtol=0, atol=1e-12)
        with self.assertRaises(ValueError):
            injectors.wsola_stretch(source, 0.0)

    def test_the_identity_shift_injector_reads_its_semitones(self) -> None:
        fixture = voice_fixture(110.0, 1.4)
        steady = (int(0.2 * RATE), int(1.2 * RATE))
        reference = f0_track(fixture.samples, fmin=50.0, fmax=400.0).median(*steady)
        for variant in injectors.CATALOG["IDN-SHIFT"].variants:
            injection = injectors.inject("IDN-SHIFT", variant.name, fixture, SEED)
            self.assertEqual(injection.samples.size, fixture.samples.size, variant.name)
            measured = semitones(f0_track(injection.samples, fmin=50.0, fmax=400.0).median(*steady), reference)
            self.assertLess(abs(measured - variant.parameters["semitones"]), 0.5, variant.name)


class TempoTests(unittest.TestCase):
    def test_rate_changes_keep_the_pitch_and_scale_the_duration(self) -> None:
        speeds = {"mild": 1.1, "moderate": 0.8, "severe": 0.7, "fast-severe": 1.3}
        self.assertEqual({variant.name: variant.parameters["speed"]
                          for variant in injectors.CATALOG["PRS-RATE"].variants if variant.name != "sham"}, speeds)
        for f0 in (85.0, 140.0, 220.0):
            fixture = voice_fixture(f0, 1.5)
            size = fixture.samples.size
            edge = int(0.2 * RATE)
            reference = f0_track(fixture.samples, fmin=50.0, fmax=400.0).median(edge, size - edge)
            for variant, speed in speeds.items():
                output = injectors.inject("PRS-RATE", variant, fixture, SEED).samples
                self.assertEqual(output.size, round(size / speed), f"{f0} Hz {variant}")
                edge_out = int(edge / speed)
                measured = semitones(f0_track(output, fmin=50.0, fmax=400.0).median(edge_out, output.size - edge_out),
                                     reference)
                self.assertLess(abs(measured), 0.3, f"{f0} Hz {variant} read {measured:+.2f} st")


class LabelledSpanTests(unittest.TestCase):
    def test_erratic_spans_read_their_labelled_shift_and_sign_changes_step(self) -> None:
        for f0 in (110.0, 140.0, 220.0):
            fixture = voice_fixture(f0, 3.0)
            injection = injectors.inject("PRS-ERRATIC", "severe", fixture, SEED)
            (label,) = injection.labels
            spans = label["spans"]
            output = f0_track(injection.samples, fmin=50.0, fmax=500.0)
            source = f0_track(fixture.samples, fmin=50.0, fmax=500.0)
            readings = [span_shift(output, source, start, end) for start, end, _shift in spans]
            for (start, end, shift), reading in zip(spans, readings):
                self.assertIn(shift, (-7.0, 7.0))
                self.assertLess(abs(reading - shift), 1.0, f"{f0} Hz [{start}, {end}) {shift:+} st read {reading:+.2f}")
            changes = 0
            for (_, _, before), (_, _, after), first, second in zip(spans, spans[1:], readings, readings[1:]):
                if before != after:
                    # A sign change is a 14 st step from one span to the next.
                    changes += 1
                    self.assertLess(abs((second - first) - (after - before)), 1.0,
                                    f"{f0} Hz step from {first:+.2f} to {second:+.2f} st")
            self.assertGreater(changes, 2, f0)

    def test_octave_and_break_spans_read_their_shift(self) -> None:
        # One long word, so the longest word is known: PRS-OCT acts at its middle, PRS-BRK from there to its end.
        word = (int(0.1 * RATE), int(1.4 * RATE))
        fixture = voice_fixture(140.0, 1.5, words=(word,))
        source = f0_track(fixture.samples, fmin=50.0, fmax=500.0)
        for injector_id, variant, shift in (("PRS-OCT", "severe", 12.0), ("PRS-OCT", "down-moderate", -12.0),
                                            ("PRS-OCT", "moderate", 12.0), ("PRS-BRK", "severe", 7.0),
                                            ("PRS-BRK", "mild", 3.0)):
            self.assertEqual(injectors.CATALOG[injector_id].variant(variant).parameters["semitones"], shift)
            injection = injectors.inject(injector_id, variant, fixture, SEED)
            (label,) = injection.labels
            start, end = label["startSample"], label["endSample"]
            reading = span_shift(f0_track(injection.samples, fmin=50.0, fmax=500.0), source, start, end)
            self.assertLess(abs(reading - shift), 0.5, f"{injector_id} {variant} read {reading:+.2f} st")
            # Outside the label the take is the source's own.
            self.assertTrue(np.array_equal(injection.samples[:start], fixture.samples[:start]))
            self.assertTrue(np.array_equal(injection.samples[end:], fixture.samples[end:]))


if __name__ == "__main__":
    unittest.main()
