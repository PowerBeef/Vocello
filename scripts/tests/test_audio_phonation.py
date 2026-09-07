"""Known-frequency/SNR fixtures qualify numbers, never perceptual thresholds."""
from pathlib import Path
import hashlib
import sys
import tempfile
import tracemalloc
import unittest
import wave
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_phonation import WindowCorrectedPitch, analyze_phonation
from analyze_prosody import analyze


class PhonationTests(unittest.TestCase):
    def test_inclusive_frequency_boundaries_survive_lag_rounding(self):
        # Analytic truth, not the outputs of another estimator: integer lag
        # prefiltering discarded 70 Hz and aliased 400 Hz to 200 at 44.1 kHz.
        for sr in (8000, 16000, 22050, 24000, 44100, 48000, 96000, 192000):
            estimator = WindowCorrectedPitch(sr)
            t = np.arange(estimator.count)/sr
            for frequency in (70, 70.1, 399.9, 400):
                for phase in (0, .7, 2.1):
                    with self.subTest(sr=sr, frequency=frequency, phase=phase):
                        pitch, _ = estimator.measure(np.sin(2*np.pi*frequency*t+phase))
                        self.assertAlmostEqual(pitch, frequency, delta=.01)
                        self.assertGreaterEqual(pitch, 70)
                        self.assertLessEqual(pitch, 400)

    def test_interpolated_pitch_cannot_escape_declared_range(self):
        for sr in (16000, 24000, 44100, 48000):
            estimator = WindowCorrectedPitch(sr)
            t = np.arange(estimator.count)/sr
            self.assertEqual(estimator.measure(np.sin(2*np.pi*69*t))[0], 0)
            # Out-of-band fundamentals can alias to in-band subharmonics in
            # bounded autocorrelation. Do not pretend this detects them all.
            for frequency in (401, 450, 600):
                pitch, _ = estimator.measure(np.sin(2*np.pi*frequency*t))
                self.assertTrue(pitch == 0 or 70 <= pitch <= 400)

    def test_frequency_and_harmonicity_no_window_penalty(self):
        for sr in (16000, 24000, 48000):
            estimator = WindowCorrectedPitch(sr)
            t = np.arange(estimator.count)/sr
            for f in (80, 150, 300, 395):
                for phase in (0, .7):
                    with self.subTest(sr=sr, f=f, phase=phase):
                        pitch, r = estimator.measure(np.sin(2*np.pi*f*t+phase))
                        self.assertAlmostEqual(pitch, f, delta=.5)
                        self.assertGreater(r, .99)

    def test_harmonics_and_noise_levels(self):
        estimator = WindowCorrectedPitch(24000)
        t = np.arange(estimator.count)/24000
        x = .3*np.sin(2*np.pi*150*t)+np.sin(2*np.pi*300*t)+.6*np.sin(2*np.pi*450*t)
        self.assertAlmostEqual(estimator.measure(x)[0], 150, delta=.5)
        clean = np.sin(2*np.pi*150*t)
        noise = np.random.default_rng(17).normal(size=len(t))
        measured = []
        for snr in (10, 20, 30):
            x = clean + noise*np.sqrt(np.mean(clean**2)/np.mean(noise**2))*10**(-snr/20)
            pitch, r = estimator.measure(x)
            self.assertAlmostEqual(pitch, 150, delta=2)
            hnr = 10*np.log10(r/(1-r))
            self.assertAlmostEqual(hnr, snr, delta=3)
            measured.append(hnr)
        self.assertEqual(measured, sorted(measured))

    def test_silence_noise_and_invalid_frames_abstain(self):
        estimator = WindowCorrectedPitch(24000)
        for frame in (np.zeros(estimator.count), np.random.default_rng(17).normal(size=estimator.count)):
            self.assertEqual(estimator.measure(frame)[0], 0)
        for frame in (np.zeros(3), np.full(estimator.count, np.nan)):
            with self.assertRaises(ValueError):
                estimator.measure(frame)

    def test_sweep_and_tremor_follow_known_local_frequency(self):
        estimator = WindowCorrectedPitch(24000)
        t = np.arange(estimator.count)/24000
        rising, falling = [], []
        for f in (90, 120, 150, 180, 210):
            rising.append(estimator.measure(np.sin(2*np.pi*f*t))[0])
            falling.append(estimator.measure(np.sin(2*np.pi*(300-f)*t))[0])
        self.assertEqual(rising, sorted(rising))
        self.assertEqual(falling, sorted(falling, reverse=True))
        pitches = [estimator.measure(np.sin(2*np.pi*(150+10*np.sin(i))*t))[0] for i in range(12)]
        self.assertGreater(max(pitches)-min(pitches), 15)

    def test_optional_block_does_not_change_existing_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'fixture.wav')
            with wave.open(path, 'wb') as wav:
                wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
                wav.writeframes((12000*np.sin(2*np.pi*150*np.arange(24000)/24000)).astype('<i2').tobytes())
            baseline = analyze(path)
            candidate = analyze(path, experimental_phonation=True)
            block = candidate.pop('experimentalPhonation')
            self.assertEqual(baseline, candidate)
            self.assertFalse(block['promotionAuthority'])
            self.assertEqual(block['implementationSHA256'], hashlib.sha256(
                (Path(__file__).resolve().parents[1]/'audio_phonation.py').read_bytes()).hexdigest())
            self.assertEqual(block['numpyVersion'], np.__version__)
            self.assertEqual(block['frameReaderSHA256'], hashlib.sha256(
                (Path(__file__).resolve().parents[1]/'analyze_prosody.py').read_bytes()).hexdigest())
            self.assertEqual(block['voicedFrameCount'], 91)
            self.assertLess(block['estimatedPeakWorkingBytes'], 4*1024*1024)
            self.assertEqual(block, analyze_phonation(path))

    def test_working_memory_is_bounded_after_reader_buffer_fills(self):
        # Both durations exceed a full streaming read block; comparing tiny
        # clips would confuse buffer fill with duration-proportional storage.
        results = []
        block = (12000*np.sin(2*np.pi*150*np.arange(8000)/8000)).astype('<i2').tobytes()
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'fixture.wav')
            for seconds in (12, 24):
                with wave.open(path, 'wb') as wav:
                    wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(8000)
                    for _ in range(seconds):
                        wav.writeframesraw(block)
                tracemalloc.start()
                try:
                    report = analyze_phonation(path)
                    peak = tracemalloc.get_traced_memory()[1]
                finally:
                    tracemalloc.stop()
                self.assertLessEqual(peak, report['estimatedPeakWorkingBytes'])
                results.append((report, peak))
        self.assertGreater(results[1][0]['frameCount'], results[0][0]['frameCount'])
        self.assertEqual(results[0][0]['estimatedPeakWorkingBytes'], results[1][0]['estimatedPeakWorkingBytes'])
        self.assertLessEqual(results[1][1], results[0][1] + 128*1024)


if __name__ == '__main__':
    unittest.main()
