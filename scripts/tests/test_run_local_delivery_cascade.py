#!/usr/bin/env python3
"""Deterministic cascade routing and cache-reuse tests."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from delivery_analysis_cache import (  # noqa: E402
    DeliveryAnalysisCache, digest, canonicalization_identity, RESAMPLER_VERSION, LEGACY_RESAMPLER_VERSION,
)
from run_local_delivery_cascade import (  # noqa: E402
    CascadeError,
    GLOBAL_ANALYZER,
    TEMPORAL_ANALYZER,
    _identity,
    build_cascade_manifest,
    run_cascade,
    review_automated_audio,
)


class LocalDeliveryCascadeTests(unittest.TestCase):
    def review_row(self):
        text = 'The quiet garden is open today.'
        row = self._row('review', self.one, 17)
        row.update(referenceText=text, scriptSHA256=hashlib.sha256(text.encode()).hexdigest())
        qc = {'algorithmVersion': 6, 'verdict': 'pass', 'instabilityVerdict': 'pass',
              'writtenOutputVerdict': 'pass', 'durationSeconds': 2.0, 'flags': [],
              **{key: 0 for key in ('nonFiniteSamples', 'clippedSamples', 'hotSamples',
                                   'clickEvents', 'longestSilenceMS', 'trailingSilenceMS')}}
        recognitions = [{'modelFamily': family, 'audioSHA256': row['instructedSHA256'],
                         'inputTextSHA256': row['scriptSHA256'], 'status': 'complete',
                         'outputLanguage': 'english', 'detectedLanguage': 'english',
                         'fullFileProcessed': True, 'processedDurationSeconds': 2.0,
                         'transcript': text,
                         'provenance': {key: digest(f'{family}-{key}') for key in
                                        ('runtimeSHA256', 'modelIdentitySHA256', 'configSHA256')}}
                        for family in ('whisper', 'sensevoice')]
        row['reviewEvidence'] = {'instructed': {'audioSHA256': row['instructedSHA256'],
                                               'audioQC': qc, 'recognitions': recognitions}}
        return row

    def test_automated_review_needs_no_listener_and_recomputes_content(self):
        row = self.review_row()
        report = review_automated_audio(row, 'instructed', 2.0)
        self.assertEqual(report['status'], 'pass')
        self.assertFalse(report['humanListeningRequired'])
        self.assertEqual(report['perceptualQuality'], 'not-established')
        self.assertNotIn(row['referenceText'], json.dumps(report))
        self.assertNotIn(str(self.root), json.dumps(report))
        for recognition in row['reviewEvidence']['instructed']['recognitions']:
            recognition['transcript'] = 'Wrong words completely replace the content.'
            recognition['errorRate'] = 0.0  # A supplied perfect score must be ignored.
        report = review_automated_audio(row, 'instructed', 2.0)
        self.assertEqual(report['status'], 'fail')
        self.assertTrue(all(r['errorRate'] > .15 for r in report['recognitions']))

    def test_native_failure_wins_over_perfect_asr_and_no_models_launch(self):
        row = self.review_row()
        row['reviewEvidence']['instructed']['audioQC']['writtenOutputVerdict'] = 'fail'
        self.assertEqual(review_automated_audio(row, 'instructed', 2.0)['status'], 'fail')
        manifest = self._seal({**self.manifest, 'rows': [row]})
        with mock.patch('run_local_delivery_cascade.run_compact_adapter') as adapter:
            result = run_cascade(manifest=manifest, cache=self.cache, lock_root=self.root,
                                 compact_config={'preprocessingConfig': {
                                     'canonicalizationIdentity': canonicalization_identity(RESAMPLER_VERSION)}})
        adapter.assert_not_called()
        self.assertEqual(result['rows'][0]['route'], 'rejected')

    def test_missing_partial_drifted_unsupported_or_disagreeing_asr_is_inconclusive(self):
        import copy
        original = self.review_row()
        changes = [
            ('audioSHA256', '0' * 64), ('inputTextSHA256', '0' * 64),
            ('fullFileProcessed', False), ('processedDurationSeconds', 1.0),
            ('processedDurationSeconds', float('nan')), ('outputLanguage', 'french'),
            ('provenance', {}), ('transcript', 'Wrong words.'),
        ]
        for field, value in changes:
            with self.subTest(field=field):
                row = copy.deepcopy(original)
                row['reviewEvidence']['instructed']['recognitions'][0][field] = value
                self.assertEqual(review_automated_audio(row, 'instructed', 2.0)['status'], 'inconclusive')
        row = copy.deepcopy(original)
        row['reviewEvidence']['instructed']['recognitions'][1]['modelFamily'] = 'whisper'
        self.assertEqual(review_automated_audio(row, 'instructed', 2.0)['independentASRFamilies'], 1)
        self.assertEqual(review_automated_audio(row, 'instructed', 2.0)['status'], 'inconclusive')
        row = copy.deepcopy(original)
        row['outputLanguage'] = 'French'
        for r in row['reviewEvidence']['instructed']['recognitions']:
            r['outputLanguage'] = r['detectedLanguage'] = 'french'
        self.assertEqual(review_automated_audio(row, 'instructed', 2.0)['status'], 'inconclusive')
        row = copy.deepcopy(original)
        row['reviewEvidence']['instructed']['audioQC']['verdict'] = 'warn'
        self.assertEqual(review_automated_audio(row, 'instructed', 2.0)['status'], 'inconclusive')

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.neutral = self.root / "neutral.wav"
        self.one = self.root / "one.wav"
        self.two = self.root / "two.wav"
        self._tone(self.neutral, 150)
        self._tone(self.one, 180)
        self._tone(self.two, 210)
        self.manifest = self._seal({
            "schemaVersion": 1,
            "kind": "source-bound-delivery-cascade-input",
            "generationProcessExited": True,
            "executionPlanDigest": "1" * 64,
            "sourceDigests": {
                "retainedPlanSHA256": "2" * 64,
                "executionStateSHA256": "3" * 64,
                "acousticLayerSHA256": "4" * 64,
                "binarySHA256": "5" * 64,
                "runnerSHA256": "6" * 64,
                "analyzerSHA256": "7" * 64,
                "temporalAnalyzerSHA256": "8" * 64,
            },
            "rows": [self._row("one", self.one, 1), self._row("two", self.two, 2)],
        })
        self.cache = DeliveryAnalysisCache(self.root / "cache")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _tone(path: Path, frequency: float) -> None:
        samples = [int(math.sin(2 * math.pi * frequency * index / 16_000) * 8000) for index in range(32_000)]
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16_000)
            output.writeframes(struct.pack(f"<{len(samples)}h", *samples))

    @staticmethod
    def _sha(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def _seal(body: dict) -> dict:
        body = dict(body)
        body.pop("manifestDigest", None)
        return {**body, "manifestDigest": digest(body)}

    def _row(self, generation: str, instructed: Path, seed: int) -> dict:
        return {
            "generationID": generation,
            "speakerID": "aiden", "scriptID": "script-1",
            "scriptTranslationGroup": "translation-1",
            "outputLanguage": "English", "preset": "happy", "seed": seed,
            "instructedWAV": str(instructed), "instructedSHA256": self._sha(instructed),
            "neutralWAV": str(self.neutral), "neutralSHA256": self._sha(self.neutral),
        }

    def test_always_layers_run_and_shared_neutral_is_reused(self) -> None:
        first = run_cascade(
            manifest=self.manifest, cache=self.cache, lock_root=self.root / "lock",
        )
        self.assertEqual(first["rowCount"], 2)
        self.assertEqual(first["canonicalizationIdentity"], canonicalization_identity(RESAMPLER_VERSION))
        self.assertEqual(len(first["composerSHA256"]), 64)
        self.assertEqual(
            first["reportDigest"],
            digest({key: value for key, value in first.items() if key != "reportDigest"}),
        )
        self.assertTrue(all(row["route"] == "abstained" for row in first["rows"]))
        self.assertFalse(first['humanListeningRequired'])
        self.assertTrue(all(row['semanticDelivery'] == 'unmeasured' for row in first['rows']))
        self.assertNotIn('manual-listening', json.dumps(first))
        self.assertGreater(first["cache"]["hits"], 0)
        self.assertTrue(all(
            row["alwaysLayers"]["temporalAcoustics"]["kind"] == "instructed-minus-neutral-temporal-delta"
            for row in first["rows"]
        ))
        self.assertTrue(all(
            row["alwaysLayers"]["audioQC"]["instructed"]["status"] == "complete"
            for row in first["rows"]
        ))
        self.assertTrue(all(
            row["alwaysLayers"]["audioQC"]["instructed"]["scope"] == "canonical-pcm-integrity-only"
            for row in first["rows"]
        ))
        second = run_cascade(
            manifest=self.manifest, cache=self.cache, lock_root=self.root / "lock",
        )
        self.assertEqual(second["cache"]["misses"], 0)
        self.assertGreater(second["cache"]["hits"], first["cache"]["hits"])
        self.assertNotIn(str(self.root), json.dumps(second))

    def test_generation_process_must_exit_and_audio_is_digest_bound(self) -> None:
        active = dict(self.manifest)
        active["generationProcessExited"] = False
        active = self._seal(active)
        with self.assertRaisesRegex(CascadeError, "must exit"):
            run_cascade(manifest=active, cache=self.cache, lock_root=self.root / "lock")
        changed = json.loads(json.dumps(self.manifest))
        changed["rows"][0]["instructedSHA256"] = "0" * 64
        changed = self._seal(changed)
        with self.assertRaisesRegex(CascadeError, "missing or changed"):
            run_cascade(manifest=changed, cache=self.cache, lock_root=self.root / "lock")

    def test_all_zero_pcm_is_rejected_by_the_distinct_qc_layer(self) -> None:
        silent = self.root / "silent.wav"
        with wave.open(str(silent), "wb") as output:
            output.setnchannels(1); output.setsampwidth(2); output.setframerate(16_000)
            output.writeframes(b"\0\0" * 32_000)
        manifest = dict(self.manifest)
        manifest["rows"] = [self._row("silent", silent, 3)]
        manifest = self._seal(manifest)
        result = run_cascade(
            manifest=manifest, cache=self.cache, lock_root=self.root / "lock",
        )
        self.assertEqual(result["rows"][0]["route"], "rejected")
        self.assertEqual(
            result["rows"][0]["alwaysLayers"]["audioQC"]["instructed"]["errorCode"],
            "all-zero-pcm",
        )

    def test_neither_side_launches_a_model_when_a_pair_is_rejected(self) -> None:
        for bad_role in ("instructed", "neutral"):
            with self.subTest(bad_role=bad_role):
                manifest = json.loads(json.dumps(self.manifest))
                manifest["rows"] = manifest["rows"][:1]
                # A very short, valid WAV: integrity can finish but frame-based
                # analysis cannot. Both controls must qualify BEFORE any model.
                short = self.root / f"short-{bad_role}.wav"
                with wave.open(str(short), "wb") as output:
                    output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
                    output.writeframes(b"\x01\x00" * 100)
                manifest["rows"][0][f"{bad_role}WAV"] = str(short)
                manifest["rows"][0][f"{bad_role}SHA256"] = self._sha(short)
                with mock.patch("run_local_delivery_cascade.run_compact_adapter") as adapter:
                    result = run_cascade(
                        manifest=self._seal(manifest), cache=self.cache,
                        lock_root=self.root / "lock", compact_config={
                            "adapterID": "unneeded", "preprocessingConfig": {
                                "canonicalizationIdentity": canonicalization_identity(RESAMPLER_VERSION),
                            },
                        },
                    )
                adapter.assert_not_called()
                self.assertEqual(result["rows"][0]["route"], "rejected")
                self.assertFalse(result["rows"][0]["finalistLayers"]["required"])
                self.assertFalse(result["promotionAuthority"])

    def test_temporal_cache_binds_its_imported_global_analyzer(self) -> None:
        canonical = self.cache.canonicalize(self.one)
        first = _identity(canonical, layer="temporal-contour", version="1", source=TEMPORAL_ANALYZER)
        self.cache.store(first, {"score": 1.0})
        from delivery_analysis_cache import file_sha256
        with mock.patch("run_local_delivery_cascade.file_sha256", side_effect=lambda path: (
            "a" * 64 if path == GLOBAL_ANALYZER else file_sha256(path)
        )):
            changed = _identity(canonical, layer="temporal-contour", version="1", source=TEMPORAL_ANALYZER)
        self.assertNotEqual(first.key, changed.key)
        self.assertIsNone(self.cache.load(changed))

    def test_mismatched_config_is_rejected_before_any_analysis(self) -> None:
        with mock.patch.object(self.cache, "canonicalize") as canonicalize:
            with self.assertRaisesRegex(ValueError, "resampler"):
                run_cascade(manifest=self.manifest, cache=self.cache,
                            lock_root=self.root, compact_config={"preprocessingConfig": {}})
            canonicalize.assert_not_called()

    def test_cli_never_silently_selects_legacy_and_explicit_replay_is_retained(self) -> None:
        import run_local_delivery_cascade as cascade
        config_path = self.root / "legacy.json"
        config_path.write_text(json.dumps({"preprocessingConfig": {}}))
        base = ["cascade", "--plan", str(self.root / "plan.json"), "--run-dir", str(self.root),
                "--out", str(self.root / "out.json"), "--compact-adapter-config", str(config_path)]
        with mock.patch.object(sys, "argv", base), mock.patch.object(
            cascade, "build_cascade_manifest", return_value=self.manifest,
        ) as manifest, mock.patch.object(cascade, "run_cascade", return_value={"rowCount": 2}) as run:
            self.assertEqual(cascade.main(), 1)
            manifest.assert_not_called()
            run.assert_not_called()
            with mock.patch.object(sys, "argv", base + ["--resampler", LEGACY_RESAMPLER_VERSION]):
                self.assertEqual(cascade.main(), 0)
            self.assertEqual(run.call_args.kwargs["cache"].resampler_version, LEGACY_RESAMPLER_VERSION)
            run.reset_mock()
            with mock.patch.object(sys, "argv", base[:-2]):
                self.assertEqual(cascade.main(), 0)
            self.assertEqual(run.call_args.kwargs["cache"].resampler_version, RESAMPLER_VERSION)

    def test_operator_manifest_is_derived_from_one_sealed_runner_identity(self) -> None:
        run_dir = self.root / "run"
        audio_dir = run_dir / "audio"
        audio_dir.mkdir(parents=True)
        instructed = audio_dir / "take.wav"
        neutral = audio_dir / "neutral.wav"
        instructed.write_bytes(self.one.read_bytes())
        neutral.write_bytes(self.neutral.read_bytes())
        execution_digest = "a" * 64
        identity = {
            "binarySHA256": "b" * 64,
            "runnerSHA256": "c" * 64,
            "analyzerSHA256": "d" * 64,
            "temporalAnalyzerSHA256": "e" * 64,
        }
        plan = {
            "executionPlanDigest": execution_digest,
            "executionIdentity": identity,
            "rows": [{
                "takeID": "take-1", "speakerID": "aiden", "seed": 9,
                "outputLanguage": "English", "preset": "happy",
                "script": {"scriptID": "script-1", "translationGroup": "translation-1"},
            }],
        }
        state = {
            "executionPlanDigest": execution_digest,
            "takes": {"take-1": {
                "status": "complete", "generationID": "generation-1",
                "referenceKey": "reference-1", "audio": "audio/take.wav",
                "audioSHA256": self._sha(instructed),
            }},
            "references": {"reference-1": {
                "status": "complete", "audio": "audio/neutral.wav",
                "audioSHA256": self._sha(neutral),
            }},
        }
        acoustic = {
            "manifestDigest": execution_digest,
            "rows": [{"takeID": "take-1", "generationID": "generation-1"}],
        }
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        (run_dir / "execution-plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (run_dir / "execution-state.json").write_text(json.dumps(state), encoding="utf-8")
        (run_dir / "acoustic-layer.json").write_text(json.dumps(acoustic), encoding="utf-8")
        manifest = build_cascade_manifest(plan_path=plan_path, run_dir=run_dir)
        self.assertEqual(manifest["executionPlanDigest"], execution_digest)
        self.assertEqual(manifest["rows"][0]["generationID"], "generation-1")
        self.assertEqual(manifest["manifestDigest"], digest({
            key: value for key, value in manifest.items() if key != "manifestDigest"
        }))
        state["executionPlanDigest"] = "f" * 64
        (run_dir / "execution-state.json").write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(CascadeError, "identities differ"):
            build_cascade_manifest(plan_path=plan_path, run_dir=run_dir)


if __name__ == "__main__":
    unittest.main()
