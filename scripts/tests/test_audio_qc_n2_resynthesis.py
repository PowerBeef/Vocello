#!/usr/bin/env python3
"""Audio QC population N2: resampling, plan, result binding and validation.

No model runs: the round-trip results are the `vocello bench --codec-roundtrip`
shape of `Sources/VocelloCLI/BenchCodecRoundTrip.swift`, written by the tests
beside placeholder output bytes.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import wave

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_n2_resynthesis as n2  # noqa: E402
from audio_qc_calibration_takes import self_digest  # noqa: E402
import audio_qc_orchestrator as orchestrator  # noqa: E402
from audio_qc_n2_resynthesis import N2Error  # noqa: E402

TOKENIZER = "836b7b357f5e" + "0" * 52
REVISION = "47ab65f7eda0aad7e1c1a008d9c12d93a10ac475"


def reference_resample_poly(x: np.ndarray, up: int, down: int) -> np.ndarray:
    """SciPy's resample_poly(x, up, down, window=('kaiser', 5.0)) by direct convolution."""
    scale = max(up, down)
    half = 10 * scale
    n = np.arange(2 * half + 1) - half
    window = np.i0(5.0 * np.sqrt(np.maximum(0.0, 1.0 - (n / half) ** 2))) / np.i0(5.0)
    taps = np.sinc(n / scale) / scale * window
    taps = taps / taps.sum() * up
    upsampled = np.zeros(len(x) * up)
    upsampled[::up] = x
    full = np.convolve(upsampled, taps)
    count = (len(x) * up + down - 1) // down
    return full[half::down][:count]


def resample(x: np.ndarray, rate: int, block: int = 997) -> np.ndarray:
    return np.concatenate(list(n2.CodecRateFIR(rate).blocks(
        (x[i:i + block] for i in range(0, len(x), block)), len(x))))


def write_wav(path: Path, samples: np.ndarray, *, rate: int = 16_000, channels: int = 1) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as writer:
        writer.setparams((channels, 2, rate, 0, "NONE", "not compressed"))
        writer.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_wav(path: Path) -> tuple[int, np.ndarray]:
    with wave.open(str(path), "rb") as reader:
        return reader.getframerate(), np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2")


def tone(seconds: float, rate: int = 16_000) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return np.rint(8_000 * np.sin(2 * np.pi * 220 * t)).astype("<i2")


class ResamplingTests(unittest.TestCase):
    def test_codec_rate_design_matches_resample_poly_and_is_block_invariant(self) -> None:
        x = np.sin(np.arange(4_001) ** 2 / 3e5) * 1_000
        for rate, (up, down) in ((16_000, (3, 2)), (48_000, (1, 2)), (22_050, (160, 147))):
            with self.subTest(rate=rate):
                actual = resample(x, rate)
                np.testing.assert_allclose(actual, reference_resample_poly(x, up, down), atol=1e-9, rtol=0)
                np.testing.assert_array_equal(actual, resample(x, rate, 16_384))
        np.testing.assert_array_equal(resample(np.array([1.0, 2.0, 3.0]), 24_000), [1.0, 2.0, 3.0])

    def test_passband_survives_and_the_l0_resampler_is_untouched(self) -> None:
        rate = 16_000
        t = np.arange(rate) / rate
        output = resample(np.sin(2 * np.pi * 1_000 * t), rate)[100:-100]
        self.assertAlmostEqual(float(np.sqrt(np.mean(output ** 2))), 2 ** -0.5, delta=0.003)
        from audio_resampling import OUTPUT_RATE, RationalFIR
        self.assertEqual(OUTPUT_RATE, 16_000)
        self.assertEqual((RationalFIR(24_000).up, RationalFIR(24_000).down), (2, 3))
        self.assertEqual(n2.resampler_identity()["version"], "polyphase-kaiser5-v2")


class N2Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.n1_dir = self.root / "n1"
        self.run = self.root / "run"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def n1_take(self, take_id: str, *, eligible: bool = True, seconds: float = 0.5,
                samples: np.ndarray | None = None, rate: int = 16_000) -> dict:
        wav = f"audio/{take_id}.wav"
        audio = tone(seconds, rate) if samples is None else samples
        digest = write_wav(self.n1_dir / wav, audio, rate=rate)
        return {
            "takeID": take_id, "family": f"fleurs:{take_id}", "scriptID": f"script-{take_id}",
            "language": "english", "text": f"Recording {take_id}.", "wavPath": wav, "wavSHA256": digest,
            "durationSeconds": len(audio) / rate, "population": "N1", "eligible": eligible,
        }

    def n1_manifest(self, takes: list[dict], **overrides) -> Path:
        manifest = {"schemaVersion": 1, "kind": "audio-qc-n1-cohort", "population": "N1", "runID": "n1-fixture",
                    "takes": takes}
        manifest.update(overrides)
        manifest["manifestDigest"] = self_digest(manifest, "manifestDigest")  # as the N1 builder signs it
        path = self.n1_dir / "n1-manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return path

    def planned(self) -> dict:
        path = self.n1_manifest([self.n1_take("en-001"), self.n1_take("en-002", eligible=False),
                                 self.n1_take("en-003", seconds=0.3)])
        return n2.build_plan(n1_manifest=path, out_dir=self.run, run_id="mac-qc-n2-fixture", label="L1")

    def fake_result(self, plan: dict, **overrides) -> Path:
        """What the CLI writes: a result JSON beside `<id>.wav` and `<id>.codes.bin`."""
        out = self.run / "roundtrip"
        out.mkdir(parents=True, exist_ok=True)
        items = []
        for item in plan["items"]:
            _, pcm = read_wav(self.run / item["inputWAVPath"])
            wav_sha = write_wav(out / f"{item['id']}.wav", (pcm // 2).astype("<i2"), rate=24_000)
            codes = out / f"{item['id']}.codes.bin"
            codes.write_bytes(b"VQCT" + item["id"].encode())
            items.append({
                "id": item["id"], "inputSHA256": item["inputWAVSHA256"], "status": "complete",
                "inputSampleCount": item["inputSampleCount"], "outputPath": f"{item['id']}.wav",
                "outputSHA256": wav_sha, "outputByteCount": (out / f"{item['id']}.wav").stat().st_size,
                "outputSampleCount": item["inputSampleCount"], "clampedSampleCount": 0,
                "frameCount": 7, "codebookCount": 16, "codesPath": f"{item['id']}.codes.bin",
                "codesSHA256": hashlib.sha256(codes.read_bytes()).hexdigest(),
            })
        result = {
            "schemaVersion": 1, "kind": "audio-qc-n2-roundtrip-result", "runID": "codec-roundtrip-x",
            "jobSHA256": plan["job"]["sha256"], "modelID": "pro_clone_speed", "catalogModelID": "pro_clone",
            "catalogVariantID": "speed", "modelRepository": "PowerBeef02/Qwen3-TTS-12Hz-1.7B-Base-4bit",
            "modelRevision": REVISION, "modelArtifactVersion": "2026.09.14.1", "catalogSHA256": "c" * 64,
            "tokenizerSHA256": TOKENIZER, "installedManifestSHA256": "d" * 64, "installedRevision": REVISION,
            "modelBinding": "all_installed_file_bytes_match_pinned_catalog",
            "encoderInput": "clone_reference_encoder_input_trailing_silence_500ms",
            "decodeSemantics": "production_nonstreaming_25_frame_schedule", "trim": "input_sample_count",
            "outputFormat": "pcm16_mono_24000hz_without_output_limiter", "codesFormat": "codec_trace_v1",
            "sampleRate": 24_000, "status": "complete", "modelLoadCount": 1, "elapsedSeconds": 1.5,
            "items": items,
        }
        result.update(overrides)
        path = out / "codec-roundtrip-result.json"
        path.write_text(json.dumps(result), encoding="utf-8")
        return path


class PlanTests(N2Fixture):
    def test_plan_resamples_eligible_recordings_and_writes_a_text_free_job(self) -> None:
        plan = self.planned()
        self.assertEqual(plan["planDigest"], n2.self_digest(plan, "planDigest"))
        self.assertEqual(plan["counts"], {"n1Takes": 3, "planned": 2})
        self.assertEqual([item["n1TakeID"] for item in plan["items"]], ["en-001", "en-003"])
        self.assertEqual([item["id"] for item in plan["items"]], ["n2-00001", "n2-00002"])
        job_bytes = (self.run / "n2-job.json").read_bytes()
        self.assertEqual(hashlib.sha256(job_bytes).hexdigest(), plan["job"]["sha256"])
        job = json.loads(job_bytes)
        self.assertEqual((job["schemaVersion"], job["kind"], job["sampleRate"]),
                         (1, "audio-qc-n2-roundtrip-job", 24_000))
        self.assertEqual(set(job["items"][0]), {"id", "wavPath", "wavSHA256"})
        self.assertNotIn("Recording", job_bytes.decode())
        for item, job_item in zip(plan["items"], job["items"]):
            path = self.run / job_item["wavPath"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), job_item["wavSHA256"])
            rate, pcm = read_wav(path)
            self.assertEqual(rate, 24_000)
            self.assertEqual(len(pcm), item["inputSampleCount"])
            self.assertEqual(item["n1SampleRate"], 16_000)
            self.assertEqual(item["textSHA256"], hashlib.sha256(item["text"].encode()).hexdigest())
        self.assertEqual(plan["items"][0]["inputSampleCount"], 12_000)
        # The 24 kHz input is the rounded, clipped v2 resample of the N1 PCM.
        _, source = read_wav(self.n1_dir / "audio/en-001.wav")
        expected = np.clip(np.rint(resample(source.astype(np.float64), 16_000)), -32768, 32767)
        np.testing.assert_array_equal(read_wav(self.run / "inputs/n2-00001.wav")[1], expected.astype("<i2"))

    def test_plan_refuses_unusable_n1_cohorts(self) -> None:
        good = self.n1_take("en-001")
        cases = {
            "kind": ([good], {"kind": "audio-qc-calibration-takes"}),
            "population": ([{**good, "population": "N3"}], {}),
            "none-eligible": ([{**good, "eligible": False}], {}),
            "duplicate": ([good, good], {}),
            "digest": ([{**good, "wavSHA256": "0" * 64}], {}),
            "absolute": ([{**good, "wavPath": str(self.n1_dir / good["wavPath"])}], {}),
            "text": ([{**good, "text": ""}], {}),
            "duration": ([{**good, "durationSeconds": 61}], {}),
        }
        for name, (takes, overrides) in cases.items():
            with self.subTest(name), self.assertRaises(N2Error):
                n2.build_plan(n1_manifest=self.n1_manifest(takes, **overrides), out_dir=self.root / name,
                              run_id="run-1")
        stereo = self.n1_take("en-002")
        write_wav(self.n1_dir / stereo["wavPath"], np.zeros(200, dtype="<i2"), channels=2)
        stereo["wavSHA256"] = hashlib.sha256((self.n1_dir / stereo["wavPath"]).read_bytes()).hexdigest()
        with self.assertRaisesRegex(N2Error, "mono PCM16"):
            n2.build_plan(n1_manifest=self.n1_manifest([stereo]), out_dir=self.root / "stereo", run_id="run-1")
        self.assertFalse((self.root / "stereo" / "inputs" / "n2-00001.wav").exists())
        with self.assertRaisesRegex(N2Error, "run id"):
            n2.build_plan(n1_manifest=self.n1_manifest([good]), out_dir=self.root / "bad-id", run_id="../x")

    def test_a_second_plan_never_mixes_into_an_existing_input_directory(self) -> None:
        self.planned()
        with self.assertRaisesRegex(N2Error, "new directory"):
            n2.build_plan(n1_manifest=self.n1_dir / "n1-manifest.json", out_dir=self.run, run_id="again")


class ManifestTests(N2Fixture):
    def test_manifest_binds_each_resynthesis_to_its_n1_recording_and_codec(self) -> None:
        plan = self.planned()
        result = self.fake_result(plan)
        output = self.run / "n2-manifest.json"
        manifest = n2.build_manifest(plan_path=self.run / "n2-plan.json", result_path=result, output=output)
        self.assertEqual(manifest["kind"], "audio-qc-n2-cohort")
        self.assertEqual(manifest["codec"]["tokenizerSHA256"], TOKENIZER)
        self.assertEqual(manifest["codec"]["modelRevision"], REVISION)
        first = manifest["takes"][0]
        self.assertEqual((first["takeID"], first["n1TakeID"], first["population"]), ("en-001--n2", "en-001", "N2"))
        self.assertEqual((first["family"], first["scriptID"]), ("fleurs:en-001", "script-en-001"))
        self.assertEqual(first["wavPath"], "roundtrip/n2-00001.wav")
        self.assertEqual(first["durationSeconds"], 0.5)
        self.assertEqual(first["codec"]["modelID"], "pro_clone_speed")
        self.assertEqual(first["codec"]["codesPath"], "roundtrip/n2-00001.codes.bin")
        report = n2.validate_manifest(json.loads(output.read_text()), manifest_dir=self.run,
                                      plan=json.loads((self.run / "n2-plan.json").read_text()))
        self.assertEqual(report["status"], "PASS", report["errors"])

        (self.run / "roundtrip/n2-00002.wav").write_bytes(b"changed")
        report = n2.validate_manifest(json.loads(output.read_text()), manifest_dir=self.run)
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("en-003--n2: the WAV bytes do not match their digest", report["errors"])

        tampered = json.loads(output.read_text())
        tampered["takes"][0]["family"] = "other"
        self.assertEqual(n2.validate_manifest(tampered, manifest_dir=self.run)["errors"],
                         ["the manifest digest does not match its content"])

    def test_the_orchestrator_takes_the_n2_cohort_and_refuses_a_tampered_one(self) -> None:
        plan = self.planned()
        output = self.run / "n2-manifest.json"
        manifest = n2.build_manifest(plan_path=self.run / "n2-plan.json", result_path=self.fake_result(plan),
                                     output=output)
        value = orchestrator.manifest_from_calibration_takes(manifest, source_sha256="f" * 64, base_dir=self.run)
        orchestrator.validate_manifest(value)
        self.assertEqual([take["id"] for take in value["takes"]], ["en-001--n2", "en-003--n2"])
        self.assertEqual(value["source"], {"kind": "audio-qc-n2-cohort", "sha256": "f" * 64, "skippedTakes": 0})
        self.assertEqual(value["takes"][0]["referenceText"], "Recording en-001.")
        tampered = copy.deepcopy(manifest)
        tampered["takes"][0]["text"] = "Another text."
        with self.assertRaisesRegex(orchestrator.OrchestratorError, "digest"):
            orchestrator.manifest_from_calibration_takes(tampered, source_sha256="f" * 64, base_dir=self.run)

    def test_a_speaker_labelled_take_keeps_its_labels_and_names_its_references_resynthesis(self) -> None:
        takes = [self.n1_take(f"sp-{index}", samples=tone(0.5) // (index + 1)) for index in range(3)]
        for index, take in enumerate(takes):
            take.update(speaker=f"corpus:{index // 2:016x}", gender="female")
        takes[0]["reference"] = {"takeID": "sp-1", "wavPath": takes[1]["wavPath"], "wavSHA256": takes[1]["wavSHA256"]}
        takes[1]["reference"] = {"takeID": "sp-0", "wavPath": takes[0]["wavPath"], "wavSHA256": takes[0]["wavSHA256"]}
        # A FLEURS take names no speaker: its gender stays behind, as before.
        fleurs = {**self.n1_take("fl-0"), "gender": "male"}
        plan = n2.build_plan(n1_manifest=self.n1_manifest([*takes, fleurs]), out_dir=self.run, run_id="speakers")
        self.assertEqual(plan["items"][0]["referenceN1TakeID"], "sp-1")
        self.assertNotIn("gender", plan["items"][3])
        output = self.run / "n2-manifest.json"
        manifest = n2.build_manifest(plan_path=self.run / "n2-plan.json", result_path=self.fake_result(plan),
                                     output=output)
        by_id = {take["takeID"]: take for take in manifest["takes"]}
        first = by_id["sp-0--n2"]
        self.assertEqual((first["speaker"], first["gender"]), (takes[0]["speaker"], "female"))
        self.assertEqual(first["reference"], {key: by_id["sp-1--n2"][key] for key in
                                              ("takeID", "n1TakeID", "wavPath", "wavSHA256")})
        self.assertNotIn("reference", by_id["sp-2--n2"])
        self.assertFalse({"speaker", "gender", "reference"} & set(by_id["fl-0--n2"]))
        self.assertEqual(n2.validate_manifest(manifest, manifest_dir=self.run)["status"], "PASS")
        # The orchestrator hands each take's reference, the resynthesis, to the speaker judges.
        value = orchestrator.manifest_from_calibration_takes(manifest, source_sha256="f" * 64, base_dir=self.run)
        panel = {take["id"]: take for take in value["takes"]}
        self.assertEqual(Path(panel["sp-0--n2"]["referenceAudioPath"]),
                         (self.run / by_id["sp-1--n2"]["wavPath"]).resolve())
        self.assertEqual(panel["sp-0--n2"]["referenceAudioSHA256"], by_id["sp-1--n2"]["wavSHA256"])
        tampered = copy.deepcopy(manifest)
        tampered["takes"][0]["reference"]["wavSHA256"] = tampered["takes"][2]["wavSHA256"]
        tampered["manifestDigest"] = n2.self_digest(tampered, "manifestDigest")
        self.assertIn("sp-0--n2: its reference clip is not another take of the manifest",
                      n2.validate_manifest(tampered, manifest_dir=self.run)["errors"])
        # A reference must be another eligible take of the cohort, so the round trip resynthesizes it.
        takes[2]["reference"] = {"takeID": "gone", "wavPath": "audio/gone.wav", "wavSHA256": "0" * 64}
        with self.assertRaisesRegex(N2Error, "not another eligible take"):
            n2.build_plan(n1_manifest=self.n1_manifest(takes), out_dir=self.root / "unreferenced", run_id="refused")

    def test_plan_refuses_an_n1_manifest_edited_after_it_was_signed(self) -> None:
        path = self.n1_manifest([self.n1_take("en-001"), self.n1_take("en-002", eligible=False)])
        edited = json.loads(path.read_text())
        edited["takes"][1]["eligible"] = True
        path.write_text(json.dumps(edited), encoding="utf-8")
        with self.assertRaisesRegex(N2Error, "N1 manifest digest"):
            n2.build_plan(n1_manifest=path, out_dir=self.run, run_id="mac-qc-n2-fixture", label="L1")

    def test_manifest_refuses_an_incomplete_or_unbound_round_trip(self) -> None:
        plan = self.planned()
        item_overrides = {
            "item-failed": {"status": "failed"},
            "item-input": {"inputSHA256": "0" * 64},
            "item-codebooks": {"codebookCount": 15},
            "item-length": {"outputSampleCount": 1},
            "item-output": {"outputSHA256": "0" * 64},
            "item-codes": {"codesSHA256": "0" * 64},
        }
        result_overrides = {
            "status": {"status": "failed"},
            "job": {"jobSHA256": "0" * 64},
            "loads": {"modelLoadCount": 2},
            "limiter": {"outputFormat": "pcm16_limited"},
            "schedule": {"decodeSemantics": "streaming"},
            "revision": {"modelRevision": "main"},
            "tokenizer": {"tokenizerSHA256": None},
        }
        for name, overrides in {**item_overrides, **result_overrides}.items():
            with self.subTest(name):
                path = self.fake_result(plan, **({} if name in item_overrides else overrides))
                if name in item_overrides:
                    result = json.loads(path.read_text())
                    result["items"][0].update(overrides)
                    path.write_text(json.dumps(result), encoding="utf-8")
                with self.assertRaises(N2Error):
                    n2.build_manifest(plan_path=self.run / "n2-plan.json", result_path=path,
                                      output=self.run / "n2-manifest.json")
        path = self.fake_result(plan)
        result = json.loads(path.read_text())
        result["items"] = result["items"][:1]
        path.write_text(json.dumps(result), encoding="utf-8")
        with self.assertRaisesRegex(N2Error, "plan order"):
            n2.build_manifest(plan_path=self.run / "n2-plan.json", result_path=path,
                              output=self.run / "n2-manifest.json")
        with self.assertRaisesRegex(N2Error, "under the manifest"):
            n2.build_manifest(plan_path=self.run / "n2-plan.json", result_path=self.fake_result(plan),
                              output=self.root / "elsewhere" / "n2-manifest.json")

    def test_validation_checks_the_plan_binding_and_codec_identity(self) -> None:
        plan = self.planned()
        output = self.run / "n2-manifest.json"
        manifest = n2.build_manifest(plan_path=self.run / "n2-plan.json", result_path=self.fake_result(plan),
                                     output=output)
        other_plan = copy.deepcopy(plan)
        other_plan["items"] = other_plan["items"][:1]
        other_plan["planDigest"] = n2.self_digest(other_plan, "planDigest")
        errors = n2.validate_manifest(manifest, manifest_dir=self.run, plan=other_plan)["errors"]
        self.assertIn("the manifest does not bind its plan", errors)
        self.assertIn("the manifest's takes are not exactly the plan's items in plan order", errors)

        drifted = copy.deepcopy(manifest)
        drifted["takes"][1]["codec"]["modelRevision"] = "f" * 40
        drifted["manifestDigest"] = n2.self_digest(drifted, "manifestDigest")
        self.assertIn("en-003--n2: the take does not bind the manifest's codec identity",
                      n2.validate_manifest(drifted, manifest_dir=self.run)["errors"])

        escaped = copy.deepcopy(manifest)
        escaped["takes"][0]["wavPath"] = "../outside.wav"
        escaped["manifestDigest"] = n2.self_digest(escaped, "manifestDigest")
        self.assertIn("en-001--n2: wavPath must stay under its manifest's directory",
                      n2.validate_manifest(escaped, manifest_dir=self.run)["errors"])

    def test_command_line_runs_plan_manifest_and_validation(self) -> None:
        n1 = self.n1_manifest([self.n1_take("en-001")])
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(n2.main(["plan", "--n1-manifest", str(n1), "--out-dir", str(self.run),
                                      "--run-id", "run-1"]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["counts"], {"n1Takes": 1, "planned": 1})
        plan = json.loads((self.run / "n2-plan.json").read_text())
        result = self.fake_result(plan)
        manifest = self.run / "n2-manifest.json"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(n2.main(["manifest", "--plan", str(self.run / "n2-plan.json"), "--result",
                                      str(result), "--output", str(manifest)]), 0)
            self.assertEqual(n2.main(["validate-manifest", "--manifest", str(manifest), "--plan",
                                      str(self.run / "n2-plan.json")]), 0)
        (self.run / "roundtrip/n2-00001.codes.bin").write_bytes(b"changed")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(n2.main(["validate-manifest", "--manifest", str(manifest)]), 1)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(n2.main(["plan", "--n1-manifest", str(self.root / "missing.json"), "--out-dir",
                                      str(self.root / "x"), "--run-id", "run-1"]), 1)


if __name__ == "__main__":
    unittest.main()
