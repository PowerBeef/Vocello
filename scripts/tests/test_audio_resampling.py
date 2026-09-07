"""Numerical/streaming/cache identity fixtures; no models or SciPy dependency."""
import json
from pathlib import Path
import sys
import tempfile
import tracemalloc
import unittest
import wave
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_resampling import RationalFIR, RESAMPLER_VERSION, INPUT_BLOCK_FRAMES
from delivery_analysis_cache import (
    DeliveryAnalysisCache, AnalysisCacheError, configured_resampler, canonicalization_identity,
    LEGACY_RESAMPLER_VERSION, select_resampler,
)


def resample(x, rate, block=997):
    return np.concatenate(list(RationalFIR(rate).blocks(
        (x[i:i+block] for i in range(0, len(x), block)), len(x))))


class ResamplingTests(unittest.TestCase):
    def test_default_cache_preserves_endpoint_and_rejects_alias_energy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = DeliveryAnalysisCache(root / 'cache')
            self.assertEqual(cache.resampler_version, RESAMPLER_VERSION)
            path = root / 'input.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                wav.writeframes(np.array([100, 200, 300], dtype='<i2').tobytes())
            canonical = cache.canonicalize(path)
            self.assertEqual(canonical.sample_count, 3)
            np.testing.assert_array_equal(
                np.frombuffer(canonical.derivative_path.read_bytes(), dtype='<i2'), [100, 200, 300])
            samples = np.rint(10000 * np.sin(2*np.pi*10000*np.arange(24000)/24000)).astype('<i2')
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                wav.writeframes(samples.tobytes())
            canonical = cache.canonicalize(path)
            actual = np.frombuffer(canonical.derivative_path.read_bytes(), dtype='<i2')[100:-100].astype(float)
            self.assertLess(float(np.sqrt(np.mean(actual**2))), 30)

    def test_frozen_scipy_reference_and_block_invariance(self):
        fixture = json.loads(Path(__file__).with_name('fixtures').joinpath('audio_resampling_v2.json').read_text())
        x = np.array(fixture['input'])
        for rate, expected in fixture['outputs'].items():
            with self.subTest(rate=rate):
                actual = resample(x, int(rate))
                np.testing.assert_allclose(actual, expected, atol=1e-12, rtol=0)
                np.testing.assert_array_equal(actual, resample(x, int(rate), 1))

    def test_antialias_and_passband(self):
        rate = 24000
        t = np.arange(rate) / rate
        low = resample(np.sin(2*np.pi*1000*t), rate)[100:-100]
        high = resample(np.sin(2*np.pi*10000*t), rate)[100:-100]
        self.assertAlmostEqual(float(np.sqrt(np.mean(low**2))), 2**-.5, delta=.003)
        self.assertLess(float(np.sqrt(np.mean(high**2))), .003)

    def test_chirp_and_long_block_boundaries(self):
        x = np.sin(np.arange(35003)**2 / 1e6)
        np.testing.assert_array_equal(resample(x, 44100, 997), resample(x, 44100, INPUT_BLOCK_FRAMES))

    def test_equal_rate_includes_endpoint_and_single_frame(self):
        np.testing.assert_array_equal(resample(np.array([1., 2., 3.]), 16000), [1., 2., 3.])
        self.assertEqual(len(resample(np.ones(1), 24000)), 1)

    def test_invalid_and_truncated_input(self):
        for rate in (0, True, 7999, 192001, 24000.0):
            with self.assertRaises(ValueError):
                RationalFIR(rate)
        for blocks, count in (([np.ones(2)], 3), ([np.ones(2)], 1),
                              ([np.array([np.nan])], 1), ([np.ones(16385)], 16385),
                              ([np.ones((2, 2))], 4), ([np.ones(1)], 0)):
            with self.assertRaises(ValueError):
                list(RationalFIR(24000).blocks(blocks, count))

    def test_working_memory_does_not_follow_duration(self):
        def peak(blocks):
            block = np.sin(np.arange(4096) / 10)
            tracemalloc.start()
            for _ in RationalFIR(24000).blocks((block for _ in range(blocks)), len(block)*blocks):
                pass
            result = tracemalloc.get_traced_memory()[1]
            tracemalloc.stop()
            return result
        short = peak(20)
        long = peak(200)
        self.assertLess(long, short + 256*1024)
        self.assertLess(long, 8*1024*1024)

    def test_cache_version_coexistence_stereo_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root/'input.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setnchannels(2); wav.setsampwidth(2); wav.setframerate(24000)
                wav.writeframes(np.tile(np.array([1000, 3000], dtype='<i2'), 1001).tobytes())
            legacy_cache = DeliveryAnalysisCache(root/'cache', resampler_version=LEGACY_RESAMPLER_VERSION)
            old = legacy_cache.canonicalize(path)
            cache = DeliveryAnalysisCache(root/'cache', resampler_version=RESAMPLER_VERSION)
            new = cache.canonicalize(path)
            self.assertNotEqual(old.derivative_path, new.derivative_path)
            self.assertEqual(new.sample_count, 668)
            self.assertEqual(new.resampler_version, RESAMPLER_VERSION)
            np.testing.assert_allclose(np.frombuffer(new.derivative_path.read_bytes(), dtype='<i2')[30:-30], 2000, atol=3)
            with patch('delivery_analysis_cache._write_canonical_pcm', side_effect=AssertionError('cache miss')):
                self.assertEqual(new, cache.canonicalize(path))
            new.derivative_path.write_bytes(b'corrupt')
            with self.assertRaises(AnalysisCacheError):
                cache.canonicalize(path)
            self.assertEqual(old, legacy_cache.canonicalize(path))

    def test_legacy_requires_explicit_selection_and_identity_is_not_inferred(self):
        legacy = {'preprocessingConfig': {}}
        self.assertEqual(configured_resampler(legacy), LEGACY_RESAMPLER_VERSION)
        self.assertEqual(select_resampler(), RESAMPLER_VERSION)
        with self.assertRaisesRegex(AnalysisCacheError, 'resampler'):
            select_resampler(config=legacy)
        self.assertEqual(select_resampler(LEGACY_RESAMPLER_VERSION, legacy), LEGACY_RESAMPLER_VERSION)
        for identity in (None, {}, {'resamplerVersion': 'unknown'}):
            with self.subTest(identity=identity), self.assertRaises(AnalysisCacheError):
                configured_resampler({'preprocessingConfig': {'canonicalizationIdentity': identity}})
        for version in ('unknown', '', False):
            with self.assertRaises(AnalysisCacheError):
                select_resampler(version)

    def test_model_preprocessing_identity_drift(self):
        identity = canonicalization_identity(RESAMPLER_VERSION)
        config = {'preprocessingConfig': {'canonicalizationIdentity': identity}}
        self.assertEqual(configured_resampler(config), RESAMPLER_VERSION)
        identity['resamplerSourceSHA256'] = '0'*64
        with self.assertRaises(AnalysisCacheError):
            configured_resampler(config)
        with self.assertRaises(AnalysisCacheError):
            configured_resampler({'preprocessingConfig': None})

    def test_v2_interrupted_publication_leaves_no_accepted_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root/'input.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                wav.writeframes(np.ones(300, dtype='<i2').tobytes())
            cache = DeliveryAnalysisCache(root/'cache', resampler_version=RESAMPLER_VERSION)
            with patch('delivery_analysis_cache.os.replace', side_effect=OSError('interrupted')):
                with self.assertRaises(OSError):
                    cache.canonicalize(path)
            self.assertEqual(list((root/'cache').rglob('*.json')), [])
            self.assertEqual(cache.canonicalize(path).sample_count, 200)

    def test_v2_derivative_rejects_changed_implementation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root/'input.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                wav.writeframes(np.ones(300, dtype='<i2').tobytes())
            cache = DeliveryAnalysisCache(root/'cache', resampler_version=RESAMPLER_VERSION)
            cache.canonicalize(path)
            changed = {**canonicalization_identity(RESAMPLER_VERSION), 'resamplerSourceSHA256': '0'*64}
            with patch('delivery_analysis_cache.canonicalization_identity', return_value=changed):
                with self.assertRaisesRegex(AnalysisCacheError, 'preprocessing'):
                    cache.canonicalize(path)


if __name__ == '__main__':
    unittest.main()
