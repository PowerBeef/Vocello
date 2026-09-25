#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave


SCRIPT = Path(__file__).resolve().parents[1] / "telemetry_overhead.py"
SPEC = importlib.util.spec_from_file_location("telemetry_overhead", SCRIPT)
assert SPEC and SPEC.loader
overhead = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = overhead
SPEC.loader.exec_module(overhead)


def identity(*, runtime_profile: str = "pro_custom_speed:fixture-v1") -> dict:
    return {
        "resolvedModelID": "pro_custom_speed",
        "modelRepository": "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-4bit",
        "huggingFaceRevision": "f35faf19b0cc2160865af64ecf0f22f83d335135",
        "artifactVersion": "2026.04.05.2",
        "quantization": "4-bit",
        "integrityManifestDigest": "f" * 64,
        "runtimeProfileSignature": runtime_profile,
        "nativeLoadCapabilityProfile": "pro1b7:custom_voice",
    }


def engine_row(
    generation_id: str,
    *,
    run_id: str = "overhead-subrun",
    runtime_profile: str = "pro_custom_speed:fixture-v1",
) -> dict:
    return {
        "schemaVersion": 8,
        "generationID": generation_id,
        "layer": "engine",
        "modelID": "pro_custom_speed",
        "notes": {"benchRunID": run_id},
        "modelRuntimeIdentity": identity(runtime_profile=runtime_profile),
    }


class TelemetryOverheadIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.telemetry = self.root / "diagnostics" / "engine" / "generations.jsonl"
        self.telemetry.parent.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_rows(self, rows: list[dict]) -> None:
        self.telemetry.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )

    def write_wave(self, path: Path, frames: bytes) -> None:
        with wave.open(str(path), "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(24_000)
            stream.writeframes(frames)

    def test_off_arm_engine_telemetry_leftovers_are_listed(self) -> None:
        data_dir = self.root
        self.assertEqual(overhead.engine_telemetry_leftovers(data_dir / "missing"), [])
        self.assertEqual(overhead.engine_telemetry_leftovers(data_dir), [])
        # bench-results.json belongs to the CLI observer, never the engine sink.
        (data_dir / "diagnostics" / "bench-results.json").write_text("{}", encoding="utf-8")
        self.assertEqual(overhead.engine_telemetry_leftovers(data_dir), [])
        self.write_rows([engine_row("generation-1")])
        sidecar = data_dir / "diagnostics" / "engine" / "samples-generation-1.jsonl"
        sidecar.write_text("{}\n", encoding="utf-8")
        v9 = data_dir / "diagnostics" / "engine" / "streaming-telemetry-v9" / "generation-1.json"
        v9.parent.mkdir()
        v9.write_text("{}", encoding="utf-8")
        self.assertEqual(
            overhead.engine_telemetry_leftovers(data_dir),
            [
                "diagnostics/engine/generations.jsonl",
                "diagnostics/engine/samples-generation-1.jsonl",
                "diagnostics/engine/streaming-telemetry-v9/generation-1.json",
            ],
        )

    def test_artifact_root_comes_from_validated_build_policy(self) -> None:
        self.assertEqual(
            overhead.managed_output_path("QVOICE_ARTIFACTS_MACOS"),
            SCRIPT.parents[1] / "build" / "artifacts" / "macos",
        )

    def test_pcm_digest_rejects_zero_duration_audio(self) -> None:
        empty = self.root / "empty.wav"
        self.write_wave(empty, b"")
        with self.assertRaisesRegex(RuntimeError, "empty or invalid PCM"):
            overhead.pcm_digest(empty)

        nonempty = self.root / "nonempty.wav"
        self.write_wave(nonempty, b"\0\0" * 24)
        self.assertEqual(len(overhead.pcm_digest(nonempty)), 64)

    def test_loads_only_requested_rows_and_returns_exact_identity(self) -> None:
        self.write_rows([
            engine_row("unrelated", run_id="other-run"),
            engine_row("take-two"),
            engine_row("take-one"),
        ])
        observed = overhead.load_model_runtime_identity(
            self.root, ["take-one", "take-two"], run_id="overhead-subrun"
        )
        self.assertEqual(observed, identity())

    def test_rejects_identity_drift_between_measured_generations(self) -> None:
        self.write_rows([
            engine_row("take-one"),
            engine_row("take-two", runtime_profile="different-profile"),
        ])
        with self.assertRaisesRegex(RuntimeError, "do not share one exact"):
            overhead.load_model_runtime_identity(
                self.root, ["take-one", "take-two"], run_id="overhead-subrun"
            )

    def test_rejects_missing_schema_v8_runtime_identity(self) -> None:
        row = engine_row("take-one")
        row["schemaVersion"] = 6
        self.write_rows([row])
        with self.assertRaisesRegex(RuntimeError, "not schema-v8"):
            overhead.load_model_runtime_identity(
                self.root, ["take-one"], run_id="overhead-subrun"
            )

    def test_rejects_duplicate_or_wrong_run_rows(self) -> None:
        duplicate = engine_row("take-one")
        self.write_rows([duplicate, duplicate])
        with self.assertRaisesRegex(RuntimeError, "duplicate engine telemetry"):
            overhead.load_model_runtime_identity(
                self.root, ["take-one"], run_id="overhead-subrun"
            )

        self.write_rows([engine_row("take-one", run_id="wrong-run")])
        with self.assertRaisesRegex(RuntimeError, "another benchmark run"):
            overhead.load_model_runtime_identity(
                self.root, ["take-one"], run_id="overhead-subrun"
            )


SLOTS = ((1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2))


def samples(rtfs: list[float]) -> list[dict]:
    return [
        {"rotation": rotation, "measuredTake": take, "rtf": rtf, "ttfcMS": 1000.0 * rtf}
        for (rotation, take), rtf in zip(SLOTS, rtfs)
    ]


class PairedOverheadAnnotationTests(unittest.TestCase):
    """Audit #63/#106: overhead verdicts carry paired uncertainty as annotations."""

    def test_pairs_each_take_with_the_off_take_of_its_rotation(self) -> None:
        off = [0.30, 0.31, 0.32, 0.30, 0.29, 0.31]
        factors = [1.01, 1.02, 1.03, 1.04, 1.05, 1.06]
        annotation = overhead.paired_overhead_annotation(
            samples([value * factor for value, factor in zip(off, factors)]), samples(off), "rtf",
        )
        self.assertTrue(annotation["annotationOnly"])
        self.assertEqual((annotation["n"], annotation["unpairedTakes"]), (6, 0))
        self.assertAlmostEqual(annotation["medianRatio"], 1.035)
        self.assertAlmostEqual(annotation["meanPercentDifference"], 3.5)
        # Six distinct positive paired differences: exact two-sided p = 2/64.
        self.assertEqual(annotation["wilcoxon"]["method"], "exact")
        self.assertAlmostEqual(annotation["wilcoxon"]["pValue"], 0.03125)
        interval = annotation["confidenceInterval95"]
        self.assertEqual(interval["method"], "BCa")
        self.assertGreater(interval["lower"], 0.0)
        self.assertLess(interval["lower"], 3.5)
        self.assertGreater(interval["upper"], 3.5)

    def test_pairing_cancels_drift_between_rotations(self) -> None:
        # Rotation 3 ran 20% slower for every arm: unpaired medians move, the
        # paired percent difference stays a steady +2%.
        off = [0.30, 0.30, 0.30, 0.30, 0.36, 0.36]
        on = [value * 1.02 for value in off]
        annotation = overhead.paired_overhead_annotation(samples(on), samples(off), "ttfcMS")
        self.assertAlmostEqual(annotation["medianRatio"], 1.02)
        self.assertAlmostEqual(annotation["confidenceInterval95"]["lower"], 2.0)
        self.assertAlmostEqual(annotation["confidenceInterval95"]["upper"], 2.0)

    def test_a_take_without_its_off_partner_is_counted_not_paired(self) -> None:
        off = samples([0.30, 0.31, 0.32, 0.30, 0.29, 0.31])[:-1]
        annotation = overhead.paired_overhead_annotation(
            samples([0.31, 0.32, 0.33, 0.31, 0.30, 0.32]), off, "rtf",
        )
        self.assertEqual((annotation["n"], annotation["unpairedTakes"]), (5, 1))


if __name__ == "__main__":
    unittest.main()
