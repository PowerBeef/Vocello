"""No downloaded audio/models: frozen reference integrity and actual composer tests."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
import struct
import wave
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import delivery_acoustic_reference as ref
from delivery_analysis_cache import DeliveryAnalysisCache, file_sha256, RESAMPLER_VERSION, LEGACY_RESAMPLER_VERSION


class AcousticReferenceTests(unittest.TestCase):
    def setUp(self):
        self.base = ref.load_base()

    def test_frozen_manifest_accounting_and_provenance(self):
        ref.validate_base(self.base)
        rows = self.base['rows']
        self.assertEqual(len(rows), 45)
        self.assertEqual(sum(r['neutralID'] is not None for r in rows), 24)
        self.assertEqual([sum(r['nativeQC']['verdict'] == v for r in rows) for v in ('pass', 'warn', 'fail')], [39, 3, 3])
        self.assertEqual(sum(bool(r['sourceWarnings']) for r in rows), 15)
        self.assertEqual(sum(bool(r['advisoryWarnings']) for r in rows), 5)
        self.assertFalse(self.base['qualityLabels'])
        self.assertNotIn('/Users/', json.dumps(self.base))
        for source in self.base['sources'].values():
            self.assertEqual(len(source['revision']), 40)
            self.assertTrue(source['licenseURLs'])

    def test_corruption_and_registration_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'config').mkdir()
            path = root/'config/base.json'; path.write_text(json.dumps(self.base))
            contract = root/'contract.json'
            contract.write_text(json.dumps({'acousticReferenceBase': {
                'manifest': 'config/base.json', 'sha256': file_sha256(path)}}))
            with mock.patch.object(ref, 'REPO', root), mock.patch.object(ref, 'CONTRACT', contract):
                self.assertEqual(ref.load_base()['id'], self.base['id'])
                path.write_text('{corrupt')
                with self.assertRaisesRegex(ValueError, 'manifest-drift'):
                    ref.load_base()

    def test_invalid_pairs_duplicate_rows_and_nonfinite_features_rejected(self):
        for mutation in (
            lambda b: b['rows'][0].update(neutralID='ref-009'),
            lambda b: b['rows'][0].update(language='french'),
            lambda b: b['rows'][0].update(id='ref-002'),
            lambda b: b['rows'][0]['features'].update(f0_median_hz=float('nan')),
            lambda b: b.update(qualityLabels=True),
        ):
            base = copy.deepcopy(self.base); mutation(base)
            with self.assertRaises(ValueError): ref.validate_base(base)

    def test_preprocessing_and_analyzer_drift_are_explicit(self):
        # Source upgrades may disable this optional base without requiring audio
        # reanalysis to pass CI. Test both compatibility branches deterministically.
        with mock.patch.object(ref, 'file_sha256', side_effect=lambda p: self.base['featureSources'][p.name]):
            self.assertIsNone(ref.availability(self.base, RESAMPLER_VERSION))
        self.assertEqual(ref.availability(self.base, LEGACY_RESAMPLER_VERSION), 'reference-preprocessing-mismatch')
        self.base['featureSources']['analyze_prosody.py'] = '0' * 64
        self.assertEqual(ref.availability(self.base, RESAMPLER_VERSION), 'reference-feature-source-drift')

    def comparison(self, preset, language):
        features = self.base['rows'][0]['features']
        return ref.compare(self.base, preset=preset, language=language, instructed=features, neutral=features)

    def test_same_language_pairs_and_sensitivity_preserve_every_warning(self):
        report = self.comparison('angry', 'English')
        self.assertEqual(report['referenceCount'], 6)
        self.assertEqual(report['speakerCount'], 6)
        self.assertEqual(report['scriptCount'], 3)
        self.assertEqual(len(report['references']), 12)
        self.assertEqual(report['sensitivityExcludedIDs'], ['ref-001', 'ref-011', 'ref-016', 'ref-021', 'ref-026'])
        metric = report['metrics']['pitchShiftSemitones']
        self.assertEqual(metric['allReferences']['n'], 6)
        self.assertEqual(metric['excludingFlaggedSensitivity']['n'], 1)
        self.assertEqual(metric['allReferences']['observed'], 0)
        self.assertEqual(metric['allReferences']['comparison'], 'below-observed-range')
        self.assertFalse(report['promotionAuthority'])
        self.assertEqual(report['qualityVerdict'], 'not-assessed')

    def test_missing_coverage_never_falls_back_across_language_or_preset(self):
        for preset, language in [('calm', 'english'), ('angry', 'french'), ('whisper', 'english'), ('happy', 'german')]:
            report = self.comparison(preset, language)
            self.assertEqual(report['status'], 'missing-coverage')
            self.assertEqual(report['referenceCount'], 0)

    def test_unpaired_german_retains_cutoff_and_empty_sensitivity(self):
        report = self.comparison('whisper', 'German')
        self.assertEqual(report['comparisonKind'], 'unpaired-style-context')
        self.assertEqual(report['referenceCount'], 5)
        self.assertEqual(report['speakerCount'], 1)
        self.assertEqual(len(report['sensitivityExcludedIDs']), 5)
        self.assertTrue(all(r['sourceWarnings'] for r in report['references']))
        self.assertEqual(report['metrics']['f0_median_hz']['excludingFlaggedSensitivity'], {'n': 0, 'comparison': 'unavailable'})

    def test_zero_pitch_abstains_and_identical_pair_delta_zero(self):
        a = dict(self.base['rows'][0]['features'])
        delta = ref.contrast(a, a)
        self.assertEqual(delta.pop('durationRatio'), 1)
        self.assertTrue(all(v == 0 for v in delta.values()))
        a['f0_median_hz'] = 0
        self.assertIsNone(ref.contrast(a, a)['pitchShiftSemitones'])

    def test_original_audio_audit_missing_changed_and_redacted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = ref.verify_originals(self.base, root)
            self.assertFalse(result['allMatched'])
            self.assertEqual(len(result['rows']), 45)
            (root/'ref-001.wav').write_bytes(b'changed')
            result = ref.verify_originals(self.base, root)
            self.assertEqual(result['rows'][0]['status'], 'mismatch')
            self.assertNotIn(folder, json.dumps(result))

    def test_actual_24k_audio_uses_common_16k_and_original_is_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); path = root/'test.wav'
            with wave.open(str(path), 'wb') as wav:
                wav.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                wav.writeframes(struct.pack('<48000h', *[int(8000 * math.sin(2*math.pi*200*i/24000)) for i in range(48000)]))
            original = file_sha256(path)
            cache = DeliveryAnalysisCache(root/'cache')
            canonical = cache.canonicalize(path)
            first, hit = ref.extract_canonical(canonical, cache, self.base)
            self.assertFalse(hit)
            self.assertEqual(canonical.sample_count, 32000)
            self.assertAlmostEqual(first['f0_median_hz'], 200, delta=2)
            self.assertEqual(first['durationSec'], 2)
            with mock.patch.object(ref, 'analyze', side_effect=AssertionError('must reuse neutral')):
                second, hit = ref.extract_canonical(canonical, cache, self.base)
            self.assertTrue(hit)
            self.assertEqual(first, second)
            self.assertEqual(file_sha256(path), original)
            self.assertNotIn(folder, json.dumps(second))


if __name__ == '__main__':
    unittest.main()
