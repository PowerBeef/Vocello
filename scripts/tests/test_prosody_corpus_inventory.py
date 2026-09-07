from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import tracemalloc
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prosody_corpus_inventory as module


def wav_fixture(path, frames=16000):
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        while frames:
            count = min(frames, 16000)
            wav.writeframesraw(b'\x20\x00' * count)
            frames -= count


class ProsodyCorpusInventoryTests(unittest.TestCase):
    def test_PCM_identity_ignores_container_tags_but_binds_format_and_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            wav_fixture(root / 'a.wav')
            data = (root / 'a.wav').read_bytes()
            # Valid RIFF JUNK metadata changes the file, not one audio sample.
            extra = b'JUNK' + struct.pack('<I', 4) + b'priv'
            tagged = data[:4] + struct.pack('<I', len(data) - 8 + len(extra)) + data[8:] + extra
            (root / 'b.wav').write_bytes(tagged)
            first, second = [module.audio_identity(root / name) for name in ('a.wav', 'b.wav')]
            self.assertNotEqual(first['audioSHA256'], second['audioSHA256'])
            self.assertEqual(first['pcmSHA256'], second['pcmSHA256'])
            altered = bytearray(data)
            altered[-1] ^= 1
            (root / 'c.wav').write_bytes(altered)
            self.assertNotEqual(first['pcmSHA256'], module.audio_identity(root / 'c.wav')['pcmSHA256'])

    def test_inventory_readonly_anonymous_and_no_inferred_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            wav_fixture(root / 'private-speaker-angry-failed.wav')
            before = hashlib.sha256((root / 'private-speaker-angry-failed.wav').read_bytes()).hexdigest()
            report, private = module.inventory_audio([root])
            self.assertEqual(report['counts']['uniquePCM'], 1)
            text = json.dumps(report)
            self.assertNotIn('private-speaker', text)
            self.assertNotIn(directory, text)
            self.assertEqual(report['items'][0]['label'], None)
            self.assertEqual(report['items'][0]['eligibility'], 'development-only')
            self.assertFalse(report['promotionAuthority'])
            self.assertEqual(private['inventorySHA256'], report['inventorySHA256'])
            self.assertEqual(before, hashlib.sha256((root / 'private-speaker-angry-failed.wav').read_bytes()).hexdigest())

    def test_truncated_PCM_is_unavailable_not_an_inferred_defect(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'broken.wav'
            wav_fixture(path)
            path.write_bytes(path.read_bytes()[:-2])
            report, _ = module.inventory_audio([path.parent])
            self.assertEqual(report['items'][0]['status'], 'UNAVAILABLE')
            self.assertEqual(report['items'][0]['reason'], 'truncated-PCM')
            self.assertIsNone(report['items'][0]['label'])

    def test_symlinks_missing_roots_and_overlapping_roots_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            wav_fixture(root / 'a.wav')
            (root / 'loop').symlink_to(root, target_is_directory=True)
            (root / 'link.wav').symlink_to(root / 'a.wav')
            report, _ = module.inventory_audio([root, root, root / 'missing'])
            self.assertEqual(report['counts']['wavFiles'], 1)
            self.assertEqual(report['counts']['symlinksSkipped'], 4)
            self.assertEqual(report['status'], 'PARTIAL')

    def test_file_and_traversal_bounds_never_report_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for i in range(3):
                wav_fixture(root / f'{i}.wav')
            report, _ = module.inventory_audio([root], max_files=2)
            self.assertEqual(report['status'], 'PARTIAL')
            self.assertEqual(report['stopReason'], 'file-limit')
            report, _ = module.inventory_audio([root], max_entries=1)
            self.assertEqual(report['stopReason'], 'entry-limit')

    def test_read_memory_does_not_scale_with_duration(self):
        with tempfile.TemporaryDirectory() as directory:
            peaks = []
            for frames in (16000, 16000 * 600):
                path = Path(directory) / f'{frames}.wav'
                wav_fixture(path, frames)
                tracemalloc.start()
                result = module.audio_identity(path)
                peaks.append(tracemalloc.get_traced_memory()[1])
                tracemalloc.stop()
                self.assertEqual(result['frameCount'], frames)
            self.assertLess(max(peaks), 2 * 1024 * 1024)
            self.assertLess(abs(peaks[1] - peaks[0]), 1024 * 1024)

    def test_actual_CLI_separates_map_refuses_overwrite_and_outputs_no_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            clips = root / 'clips'
            clips.mkdir()
            wav_fixture(clips / 'private.wav')
            # macOS /tmp may be a symlink; use resolved test-owned paths.
            command = [sys.executable, str(Path(module.__file__).with_name('prosody_holdout_validation.py')),
                       'inventory', '--audio-root', str(clips.resolve()),
                       '--output', str(root / 'report.json'), '--private-map', str(root / 'private.json')]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertNotIn(directory, result.stdout)
            report = json.loads((root / 'report.json').read_text())
            self.assertEqual(report['counts']['wavFiles'], 1)
            again = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            self.assertIn('already exists', again.stdout)


if __name__ == '__main__':
    unittest.main()
