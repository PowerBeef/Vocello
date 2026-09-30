#!/usr/bin/env python3
"""Class I positives: the COD-LOOP (T2) and GEN-NOEOS (T3) injection sets.

No model runs. The confirmation takes are procedural renders written at run
time with random codec traces; the engine rows are the shape the engine writes
(reduced by `audio_qc_calibration_takes.py collect-diagnostics`), the codec-loop
result is `Sources/VocelloCLI/BenchCodecLoop.swift`'s, and the batch outputs are
`vocello batch --json`'s. No WAV is committed.
"""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_calibration_set as m2  # noqa: E402
import audio_qc_calibration_takes as takes_tool  # noqa: E402
import audio_qc_detector_calibration as calibration  # noqa: E402
import audio_qc_introspection_positives as positives  # noqa: E402
from audio_qc_introspection_positives import PositivesError  # noqa: E402
from lib import audio_qc_observations, jsonio  # noqa: E402
from lib.qc_qualification import codec_trace, fixtures, recordings  # noqa: E402
from lib.qc_qualification.pcm import pcm_digest  # noqa: E402

TOKENIZER = "836b7b357f5e" + "0" * 52
REVISION = "47ab65f7eda0aad7e1c1a008d9c12d93a10ac475"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "audio_qc_codec_loop.json"
SAMPLES_PER_FRAME = 1_920


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def quiet(function, *args, **kwargs):
    with redirect_stderr(StringIO()), redirect_stdout(StringIO()):
        return function(*args, **kwargs)


def random_frames(seed: int, count: int) -> list[list[int]]:
    rng = np.random.default_rng(seed)
    return [[int(rng.integers(0, 4_096))] + [int(value) for value in rng.integers(0, 2_048, size=15)]
            for _ in range(count)]


def tone(frames: int, seed: int) -> np.ndarray:
    """A placeholder decode: one codec frame is 1,920 samples at 24 kHz."""
    rng = np.random.default_rng(seed)
    t = np.arange(frames * SAMPLES_PER_FRAME) / 24_000
    return 0.2 * np.sin(2 * np.pi * 180 * t) + 0.01 * rng.standard_normal(t.size)


class Fixture(unittest.TestCase):
    """A confirmation qc-takes run: its manifest, collected engine rows and the codec traces it kept."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.run = self.root / "qc-takes-run"
        engine_root = self.root / "engine-root"
        (engine_root / "engine").mkdir(parents=True)
        self.frames: dict[str, list[list[int]]] = {}
        self.generation: dict[str, str] = {}
        takes, rows = [], []
        # (script, language, voice, trace frames, what the run kept of its trace)
        plan = [("s00", "english", "ryan", 100, "trace"), ("s01", "french", "ryan", 100, "trace"),
                ("s02", "english", "design", 90, "trace"), ("s03", "french", "design", 90, "trace"),
                ("s04", "english", "ryan", 30, "trace"), ("s05", "french", "ryan", 100, "no-trace"),
                ("s06", "english", "clone", 100, "trace"), ("s07", "french", "long", 100, "trace")]
        for index, (script, language, voice_name, count, kept) in enumerate(plan):
            voice, mode = {"ryan": ({"kind": "builtin", "id": "ryan"}, "custom"),
                           "design": ({"kind": "design", "briefID": "calm", "brief": "A calm narrator."}, "design"),
                           "clone": ({"kind": "clone", "referenceKey": "ref0123456789ab"}, "clone"),
                           "long": ({"kind": "builtin", "id": "ryan"}, "custom")}[voice_name]
            key = takes_tool.voice_key(voice)
            # One seed per batch, as the take plan derives it.
            take_id, seed = f"{script}--{key}", int(sha(f"confirmation-{language}-{key}")[:6], 16)
            text = f"Script {script} speaks eight plain words for the test."
            samples = fixtures.render(fixtures.make_script(700 + index, word_count=8), fixtures.VOICES["low"])
            wav = recordings.write_pcm16_wav(self.run / "wav" / f"{take_id}.wav", samples)
            frames = random_frames(index, count)
            self.frames[take_id] = frames
            summary = audio_qc_observations.introspection_summary(codec_trace.codebook0(frames))
            generation_id = f"0A1B2C3D-0000-4000-8000-{index:012d}"
            self.generation[take_id] = generation_id
            notes = {"samplingWAVDigest": wav, "audioQCFlags": "clicks:1", "message": "a raw error message"}
            if kept == "trace":
                data = codec_trace.encode(frames)
                trace = self.run / "engine-traces" / generation_id / positives.TRACE_FILE
                trace.parent.mkdir(parents=True)
                trace.write_bytes(data)
                notes.update(codecTraceSHA256=codec_trace.sha256(data), codecTraceFrameCount=str(count),
                             codecTraceComplete="true")
            rows.append({"generationID": generation_id, "text": "Private script text.", "notes": notes,
                         "engineIntrospection": summary, "timingsMS": {"qwen_token_loop_total": 9},
                         "modelRuntimeIdentity": {"speechTokenizerDigest": TOKENIZER}})
            take = {"takeID": take_id, "family": f"{script}:{key}:{seed}", "scriptID": script, "language": language,
                    "role": "primary", "mode": mode, "variant": "speed", "variation": "expressive", "voice": voice,
                    "seed": seed, "batchID": f"confirmation-{language}-{key}", "text": text,
                    "textSHA256": sha(text), "cell": "long-form" if voice_name == "long" else "standard",
                    "voiceLanguage": language, "wavPath": f"wav/{take_id}.wav", "wavSHA256": wav,
                    "durationSeconds": round(samples.size / 24_000, 6), "finishReason": "eos", "status": "generated",
                    "engineIntrospection": {**summary, "wavSHA256": wav}, "longForm": None}
            takes.append(take)
        (engine_root / "engine" / "generations.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        takes_tool.collect_diagnostics(engine_root, self.run / "diagnostics")
        self.takes = takes
        self.manifest_path = self.write_manifest(takes)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def write_manifest(self, takes: list[dict]) -> Path:
        manifest = {"schemaVersion": 1, "kind": takes_tool.MANIFEST_KIND, "runID": "mac-qc-takes-x",
                    "planDigest": "0" * 64, "poolDigest": "1" * 64, "policyDigest": "2" * 64,
                    "split": "confirmation", "counts": takes_tool.status_counts(takes), "takes": takes}
        manifest["manifestDigest"] = takes_tool.self_digest(manifest, "manifestDigest")
        path = self.run / "takes-manifest.json"
        jsonio.atomic_json(path, manifest, ascii=False, allow_nan=False)
        return path

    def by_id(self, take_id: str) -> dict:
        return next(take for take in self.takes if take["takeID"] == take_id)


# --------------------------------------------------------------------------- #
# COD-LOOP (T2)
# --------------------------------------------------------------------------- #

class CodecLoopTests(Fixture):
    def loop_plan(self, **options) -> dict:
        return positives.loop_plan(takes_path=self.manifest_path, diagnostics=self.run / "diagnostics",
                                   traces=self.run / "engine-traces", out_dir=self.root / "loop",
                                   per_cell=options.get("per_cell", 0), sample_seed=1, catalog_seed=7)

    def replay(self, plan: dict, *, corrupt: str | None = None) -> Path:
        """`vocello bench --codec-loop` of the plan's job: mutated traces, placeholder decodes, the result."""
        job_path = self.root / "loop" / "codec-loop-job.json"
        job = json.loads(job_path.read_text(encoding="utf-8"))
        out = self.root / "loop" / "replay"
        out.mkdir()
        items = []
        for index, item in enumerate(job["items"]):
            source = (job_path.parent / item["tracePath"]).read_bytes()
            self.assertEqual(codec_trace.sha256(source), item["traceSHA256"])
            mutated = codec_trace.apply(codec_trace.complete_frames(source), item["recipe"])
            codes = codec_trace.encode(mutated)
            if corrupt == item["id"]:
                codes = codec_trace.encode(mutated[:-1])
            (out / f"{item['id']}.codes.bin").write_bytes(codes)
            wav = recordings.write_pcm16_wav(out / f"{item['id']}.wav", tone(len(mutated), index))
            items.append({"id": item["id"], "traceSHA256": item["traceSHA256"], "recipe": item["recipe"],
                          "status": "complete", "sourceFrameCount": len(mutated), "mutatedFrameCount": len(mutated),
                          "codesPath": f"{item['id']}.codes.bin", "codesSHA256": codec_trace.sha256(codes),
                          "wavPath": f"{item['id']}.wav", "wavSHA256": wav, "wavByteCount": 0,
                          "sampleCount": len(mutated) * SAMPLES_PER_FRAME, "samplesAboveCeiling": 0, "marked": True})
        result = {"schemaVersion": 1, "kind": positives.LOOP_RESULT_KIND, "runID": "codec-loop-x",
                  "jobSHA256": jsonio.sha256_file(job_path), "jobTokenizerSHA256": job["tokenizerSHA256"],
                  "modelID": "pro_custom_speed", "catalogModelID": "pro_custom", "catalogVariantID": "speed",
                  "modelRepository": "Qwen/Qwen3-TTS-Custom", "modelRevision": REVISION,
                  "modelArtifactVersion": "1", "catalogSHA256": "3" * 64, "tokenizerSHA256": TOKENIZER,
                  "installedManifestSHA256": "4" * 64, "installedRevision": REVISION,
                  "modelBinding": "all_installed_file_bytes_match_pinned_catalog",
                  "decodeSemantics": "production_nonstreaming_25_frame_schedule",
                  "sampleWindow": "quality_first_generated_frames",
                  "outputStage": "pcm16_production_output_limiter_then_publication_marking", "sampleRate": 24_000,
                  "markingEnabled": True, "status": "complete", "items": items}
        path = out / "codec-loop-result.json"
        path.write_text(json.dumps(result, sort_keys=True), encoding="utf-8")
        return path

    def loop_set(self, plan: dict, result: Path) -> dict:
        return positives.loop_set(plan_path=self.root / "loop" / "codec-loop-plan.json", result_path=result,
                                  takes_path=self.manifest_path, output=self.root / "loop-set")

    def test_the_plan_binds_each_take_to_its_trace_and_pairs_every_variant(self) -> None:
        plan = self.loop_plan()
        self.assertEqual(plan["notApplicable"], {"long-form": 1, "no-codec-trace": 1, "trace-too-short": 1})
        # The clone take has a trace: the loop acts on codes, so every mode is a source.
        selected = {entry["sourceTakeID"] for entry in plan["entries"]}
        self.assertEqual(selected, {"s00--ryan", "s01--ryan", "s02--design-calm", "s03--design-calm",
                                    "s06--clone-ref0123456789ab"})
        self.assertEqual(plan["counts"]["items"], 4 * len(selected))
        for take_id in selected:
            recipes = [entry["recipe"] for entry in plan["entries"] if entry["sourceTakeID"] == take_id]
            self.assertEqual([recipe["variant"] for recipe in recipes], ["sham", "mild", "moderate", "severe"])
            self.assertEqual(len({recipe["startFrame"] for recipe in recipes}), 1, "one placement per take")
            start, count = recipes[0]["startFrame"], len(self.frames[take_id])
            self.assertTrue(0.2 * count <= start <= 0.8 * count - 32)
        job_text = (self.root / "loop" / "codec-loop-job.json").read_text(encoding="utf-8")
        job = json.loads(job_text)
        self.assertEqual(job["tokenizerSHA256"], TOKENIZER)
        self.assertNotIn("Script s0", job_text)
        self.assertEqual(plan["planDigest"], positives.self_digest(plan, "planDigest"))
        # Each language keeps an even share of a smaller draw.
        shutil.rmtree(self.root / "loop")
        languages = {entry["language"] for entry in self.loop_plan(per_cell=2)["entries"]}
        self.assertEqual(languages, {"english", "french"})

    def test_a_trace_that_does_not_reproduce_the_takes_introspection_is_refused(self) -> None:
        take = self.by_id("s01--ryan")
        take["engineIntrospection"] = {**take["engineIntrospection"], "tokenCyclePeriod": 3,
                                       "tokenCycleSpanFrames": 12}
        self.manifest_path = self.write_manifest(self.takes)
        with self.assertRaisesRegex(PositivesError, "another generation's trace"):
            self.loop_plan()

    def test_the_set_declares_p2_positives_the_driver_and_scorer_accept(self) -> None:
        plan = self.loop_plan()
        result = self.replay(plan)
        injection_set = self.loop_set(plan, result)
        set_path = self.root / "loop-set" / "injection-set.json"
        entries = injection_set["entries"]
        self.assertEqual(injection_set["counts"], {"S": 5, "P2": 15})
        for entry in entries:
            injection = entry["injection"]
            self.assertEqual(calibration.provenance_problems(injection["population"], injection,
                                                             injection["mechanism"]), [])
            self.assertEqual(injection["provenance"]["tier"], "T2")
            self.assertEqual(entry["engineIntrospection"]["wavSHA256"], entry["wavSHA256"])
            self.assertNotIn("text", entry)
        loaded = calibration.load_injection_set(set_path)
        self.assertEqual(loaded["construction"]["tierCatalogVersions"], {"T2": [1]})
        self.assertEqual(loaded["construction"]["classes"], ["I"])
        # The loop's cycle is exact in codebook 0: span x (1 + copies), period span.
        spans = {"mild": (4, 8), "moderate": (12, 24), "severe": (32, 64)}
        for entry in entries:
            summary, variant = entry["engineIntrospection"], entry["injection"]["variant"]
            source = self.by_id(entry["sourceTakeID"])["engineIntrospection"]
            if variant == "sham":
                self.assertEqual({key: summary[key] for key in positives.CYCLE_FIELDS},
                                 {key: source[key] for key in positives.CYCLE_FIELDS})
                continue
            period, span = spans[variant]
            self.assertEqual((summary["tokenCyclePeriod"], summary["tokenCycleSpanFrames"]), (period, span))
            self.assertEqual(summary["codecFrameCount"], source["codecFrameCount"] + period)
            self.assertEqual((summary["observedStepCount"], summary["eosLikelyStepsWithoutStop"]), (0, 0))
        report = positives.verify_set(set_path, self.manifest_path)
        self.assertTrue(report["verified"], report)
        # The scorer carries each entry's own summary into its clip, and the driver reads it as P2 and S.
        measurements_path = self.root / "score" / "measurements.json"
        quiet(m2.run_score, self.manifest_path, set_path, self.root / "score", jobs=1)
        clips = {clip["clipID"]: clip for clip in json.loads(measurements_path.read_text())["clips"]}
        for entry in entries:
            self.assertEqual(clips[entry["takeID"]]["introspection"], entry["engineIntrospection"])
        _, detector = calibration.Repository().entry("introspection.token-loop@1")
        cohort = calibration.load_cohort(self.manifest_path)
        measurements = calibration.load_measurements(measurements_path)
        document = calibration.build_scores(
            detector, cohort, role="confirmation", split="confirmation", measurements=measurements,
            injection_set=calibration.load_injection_set(set_path), positive_measurements=measurements,
            positives_population=("P2",))
        scored = {unit["unitID"]: unit for unit in document["units"] if unit.get("injectorID") == "COD-LOOP"}
        self.assertEqual(len(scored), len(entries))
        for entry in entries:
            unit, variant = scored[entry["takeID"]], entry["injection"]["variant"]
            self.assertEqual(unit["score"], entry["engineIntrospection"]["tokenCycleSpanFrames"] or 0)
            self.assertEqual(unit["cell"], "COD-LOOP/severe" if variant == "severe" else None)
            self.assertEqual(unit["sham"], variant == "sham")
            if variant != "sham":
                self.assertEqual(unit["provenance"]["decoderSHA256"], injection_set["decoderSHA256"])

    def test_a_replay_of_another_trace_or_changed_audio_is_refused(self) -> None:
        plan = self.loop_plan()
        corrupt = next(entry["itemID"] for entry in plan["entries"] if entry["variant"] == "moderate")
        result = self.replay(plan, corrupt=corrupt)
        with self.assertRaisesRegex(PositivesError, "decoded another trace"):
            self.loop_set(plan, result)
        shutil.rmtree(self.root / "loop-set")
        data = json.loads(result.read_text())
        data["items"][0]["wavSHA256"] = "5" * 64
        result.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(PositivesError, "WAV is missing or differs"):
            self.loop_set(plan, result)

    def test_a_built_set_whose_copies_changed_no_longer_verifies(self) -> None:
        plan = self.loop_plan()
        self.loop_set(plan, self.replay(plan))
        set_path = self.root / "loop-set" / "injection-set.json"
        entry = json.loads(set_path.read_text())["entries"][3]
        (self.root / "loop-set" / entry["wavPath"]).write_bytes(b"RIFF")
        report = positives.verify_set(set_path, self.manifest_path)
        self.assertFalse(report["verified"])
        self.assertTrue(any("WAV differs" in failure for failure in report["failures"]), report)

    def test_the_shared_fixture_pins_the_swift_parity_cases(self) -> None:
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        frames = [[(frame * 7 + codebook * 13 + (frame * codebook) % 5) % (4_096 if codebook == 0 else 2_048)
                   for codebook in range(16)] for frame in range(fixture["frameCount"])]
        self.assertEqual(codec_trace.sha256(codec_trace.encode(frames)), fixture["sourceTraceSHA256"])
        self.assertEqual([case["recipe"]["variant"] for case in fixture["cases"]], list(codec_trace.VARIANTS))
        for case in fixture["cases"]:
            self.assertEqual(codec_trace.recipe_problems(case["recipe"]), [])
            mutated = codec_trace.apply(frames, case["recipe"])
            self.assertEqual(len(mutated), case["mutatedFrameCount"])
            self.assertEqual(codec_trace.sha256(codec_trace.encode(mutated)), case["mutatedTraceSHA256"])

    def test_the_trace_codec_refuses_malformed_bytes_and_recipes(self) -> None:
        frames = random_frames(9, 5)
        data = codec_trace.encode(frames)
        self.assertEqual(codec_trace.decode(data), (frames, 0))
        for broken in (data[:-1], data + b"\0", b"VQCX" + data[4:], data[:4] + b"\2" + data[5:]):
            with self.assertRaises(codec_trace.TraceError):
                codec_trace.decode(broken)
        with self.assertRaisesRegex(codec_trace.TraceError, "incomplete"):
            codec_trace.complete_frames(codec_trace.encode(frames, dropped=1))
        with self.assertRaisesRegex(codec_trace.TraceError, "16 codes"):
            codec_trace.complete_frames(codec_trace.encode([frame[:8] for frame in frames]))
        self.assertTrue(codec_trace.recipe_problems({**codec_trace.recipe("severe", 0), "spanFrames": 16}))
        self.assertTrue(codec_trace.recipe_problems({**codec_trace.recipe("sham", 0), "injector": "COD-SKIP@1"}))
        with self.assertRaisesRegex(codec_trace.TraceError, "runs past"):
            codec_trace.apply(frames, codec_trace.recipe("mild", 3))
        self.assertIsNone(codec_trace.placement(codec_trace.minimum_frames() - 1, seed=7, take_id="t"))
        self.assertIsNotNone(codec_trace.placement(codec_trace.minimum_frames(), seed=7, take_id="t"))


# --------------------------------------------------------------------------- #
# GEN-NOEOS (T3)
# --------------------------------------------------------------------------- #

class NoEOSTests(Fixture):
    def noeos_plan(self) -> dict:
        return positives.noeos_plan(takes_path=self.manifest_path, out_dir=self.root / "noeos", per_cell=0,
                                    sample_seed=1, catalog_seed=7)

    def generate(self, plan: dict, *, hold_frames: dict[str, int] | None = None, rejected: str | None = None,
                 never_opened: str | None = None) -> None:
        """The lane's `vocello batch` runs under the knob: WAVs, `--json` outputs and the engine's rows. A sham
        is its source take again; a positive runs past the source's stop by its hold."""
        results, wav_root = self.root / "noeos" / "batch-results", self.root / "noeos" / "batch-out"
        results.mkdir(parents=True)
        engine_root = self.root / "noeos-engine"
        (engine_root / "engine").mkdir(parents=True)
        rows, failures = [], []
        entries = {entry["entryID"]: entry for entry in plan["entries"]}
        for batch_number, batch in enumerate(plan["batches"]):
            items = []
            failed_at = None
            for index, entry_id in enumerate(batch["entryIDs"]):
                entry = entries[entry_id]
                source = self.by_id(entry["sourceTakeID"])
                generation_id = f"0B1B2C3D-0000-4000-8000-{batch_number:06d}{index:06d}"
                if entry_id == rejected:
                    failed_at = index
                    failures.append({"generationID": generation_id, "errorCode": "audio.quality_rejected"})
                    rows.append({"generationID": generation_id, "notes": {"audioQCFlags": "speaking_rate:slow"}})
                    items.append({"index": index, "generationID": generation_id, "status": "failed",
                                  "errorCode": "generation_failed"})
                    continue
                frames = batch["suppressionFrames"]
                path = wav_root / batch["batchID"] / f"{index:03d}.wav"
                if frames == 0:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(self.run / source["wavPath"], path)
                    samples = recordings.read_pcm16_wav(path)
                else:
                    samples = fixtures.render(fixtures.make_script(800 + 20 * batch_number + index, word_count=10),
                                              fixtures.VOICES["low"])
                wav = recordings.write_pcm16_wav(path, samples) if frames else jsonio.sha256_file(path)
                natural = source["engineIntrospection"]["codecFrameCount"]
                summary = {key: value for key, value in source["engineIntrospection"].items() if key != "wavSHA256"}
                summary.update(codecFrameCount=natural + frames, eosLikelyStepsWithoutStop=frames,
                               longestHighEntropyRunSteps=frames // 2)
                timings = {positives.HOLD_FRAMES: (hold_frames or {}).get(entry_id, frames)}
                if frames and entry_id != never_opened:
                    timings[positives.HOLD_START] = natural
                rows.append({"generationID": generation_id, "notes": {"samplingWAVDigest": wav},
                             "engineIntrospection": summary, "timingsMS": timings})
                items.append({"index": index, "text": source["text"], "audioPath": str(path),
                              "durationSeconds": round(samples.size / 24_000, 3), "finishReason": "eos",
                              "generationID": generation_id, "status": "completed"})
            if failed_at is None:
                payload = {"mode": batch["mode"], "variant": batch["takeVariant"], "modelID": "pro_custom_speed",
                           "count": len(items), "wallSeconds": 1.0,
                           "items": [{key: item[key] for key in ("index", "text", "audioPath", "durationSeconds",
                                                                 "finishReason")} for item in items]}
                (results / f"{batch['batchID']}.json").write_text(json.dumps(payload), encoding="utf-8")
                continue
            # The batch stopped at the refused item; the lane resumed after it in a new segment.
            head = [{**{key: item.get(key) for key in ("index", "generationID", "status", "errorCode",
                                                        "audioPath", "durationSeconds", "finishReason")}}
                    for item in items[:failed_at + 1]]
            (results / f"{batch['batchID']}.json").write_text(json.dumps({
                "schemaVersion": 2, "mode": batch["mode"], "variant": batch["takeVariant"], "modelID": "m",
                "plannedCount": len(batch["entryIDs"]), "completedCount": failed_at, "wallSeconds": 1.0,
                "items": head + [{"index": index, "status": "not_attempted"}
                                 for index in range(failed_at + 1, len(batch["entryIDs"]))]}), encoding="utf-8")
            rest = items[failed_at + 1:]
            if rest:
                (results / f"{batch['batchID']}@{failed_at + 1}.json").write_text(json.dumps({
                    "mode": batch["mode"], "variant": batch["takeVariant"], "modelID": "m", "count": len(rest),
                    "wallSeconds": 1.0, "items": [{"index": position, "text": item["text"],
                                                   "audioPath": item["audioPath"],
                                                   "durationSeconds": item["durationSeconds"],
                                                   "finishReason": "eos"} for position, item in enumerate(rest)]}),
                    encoding="utf-8")
        (engine_root / "engine" / "generations.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        (engine_root / "engine" / "generation-failures.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in failures), encoding="utf-8")
        takes_tool.collect_diagnostics(engine_root, self.root / "noeos" / "diagnostics")

    def noeos_set(self) -> dict:
        return positives.noeos_set(plan_path=self.root / "noeos" / "noeos-plan.json",
                                   batch_results=self.root / "noeos" / "batch-results",
                                   wav_root=self.root / "noeos" / "batch-out",
                                   diagnostics=self.root / "noeos" / "diagnostics", takes_path=self.manifest_path,
                                   output=self.root / "noeos-set")

    def test_the_plan_writes_one_knob_batch_per_source_batch_and_variant(self) -> None:
        plan = self.noeos_plan()
        self.assertEqual(plan["notApplicable"], {"clone-regeneration": 1, "long-form": 1})
        sources = {entry["sourceTakeID"] for entry in plan["entries"]}
        self.assertEqual(len(sources), 6)
        self.assertEqual(len(plan["entries"]), 4 * len(sources))
        rows = (self.root / "noeos" / "noeos-batches.tsv").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(rows), len(plan["batches"]))
        for row, batch in zip(rows, plan["batches"]):
            fields = row.split(positives.FIELD_SEPARATOR)
            self.assertEqual(len(fields), 10)
            self.assertEqual((fields[0], fields[1], fields[9]), (batch["batchID"], batch["mode"],
                                                                 str(batch["suppressionFrames"])))
            lines = Path(fields[8]).read_text(encoding="utf-8").splitlines()
            texts = [self.by_id(entry["sourceTakeID"])["text"] for entry in plan["entries"]
                     if entry["batchID"] == batch["batchID"]]
            self.assertEqual(lines, texts)
            if batch["mode"] == "design":
                self.assertEqual((fields[5], fields[6]), ("", "A calm narrator."))
            else:
                self.assertEqual((fields[5], fields[6]), ("ryan", ""))
        recipe = plan["entries"][0]["recipe"]
        self.assertEqual((recipe["knob"], recipe["delivery"]), (positives.NOEOS_KNOB, "app-default"))
        self.assertNotIn("Script s0", (self.root / "noeos" / "noeos-plan.json").read_text(encoding="utf-8"))

    def test_the_set_binds_published_takes_to_their_engine_recorded_hold(self) -> None:
        plan = self.noeos_plan()
        severe = [entry["entryID"] for entry in plan["entries"] if entry["variant"] == "severe"]
        rejected, never_opened = severe[0], severe[1]
        self.generate(plan, rejected=rejected, never_opened=never_opened)
        injection_set = self.noeos_set()
        set_path = self.root / "noeos-set" / "injection-set.json"
        entries = {entry["takeID"]: entry for entry in injection_set["entries"]}
        self.assertNotIn(rejected, entries)
        self.assertNotIn(never_opened, entries)
        self.assertEqual(injection_set["unpublished"]["severe"], {"fast-qc-rejected": 1, "hold-never-opened": 1})
        self.assertEqual(injection_set["rejectedFlagFamilies"], {"speaking_rate": 1})
        self.assertEqual(injection_set["counts"], {"S": 6, "P3": 16})
        for entry in entries.values():
            injection = entry["injection"]
            self.assertEqual(calibration.provenance_problems(injection["population"], injection,
                                                             injection["mechanism"]), [])
            self.assertEqual(injection["hold"]["frames"], injection["parameters"]["suppressionFrames"])
            self.assertEqual(entry["engineIntrospection"]["wavSHA256"], entry["wavSHA256"])
        # Every sham reproduced its source take, and every hold opened where its source stopped.
        self.assertEqual(injection_set["determinism"], {"holdOpenedAtSourceStop": 16, "positivesWithSourceSummary": 16,
                                                        "shamPCMEqualsSource": 6, "shams": 6})
        loaded = calibration.load_injection_set(set_path)
        self.assertEqual(loaded["construction"]["tierCatalogVersions"], {"T3": [1]})
        self.assertTrue(positives.verify_set(set_path, self.manifest_path)["verified"])
        # The scorer measures each published take with its own generation's summary.
        quiet(m2.run_score, self.manifest_path, set_path, self.root / "score", jobs=1)
        clips = {clip["clipID"]: clip for clip in
                 json.loads((self.root / "score" / "measurements.json").read_text())["clips"]}
        for entry_id, entry in entries.items():
            self.assertEqual(clips[entry_id]["introspection"]["eosLikelyStepsWithoutStop"],
                             entry["injection"]["parameters"]["suppressionFrames"])
            self.assertEqual(clips[entry_id]["population"], entry["injection"]["population"])

    def test_a_take_the_knob_did_not_hold_is_refused(self) -> None:
        plan = self.noeos_plan()
        moderate = next(entry["entryID"] for entry in plan["entries"] if entry["variant"] == "moderate")
        self.generate(plan, hold_frames={moderate: 0})
        with self.assertRaisesRegex(PositivesError, "was not applied"):
            self.noeos_set()

    def test_a_take_regenerated_from_another_manifest_is_refused(self) -> None:
        plan = self.noeos_plan()
        self.generate(plan)
        self.takes[0]["seed"] += 1
        self.manifest_path = self.write_manifest(self.takes)
        with self.assertRaisesRegex(PositivesError, "not the one the plan was drawn from"):
            self.noeos_set()


# --------------------------------------------------------------------------- #
# The engine rows the lane collects
# --------------------------------------------------------------------------- #

class ReducedRowTests(unittest.TestCase):
    def test_reduced_rows_keep_the_trace_the_hold_and_the_tokenizer_and_nothing_private(self) -> None:
        row = takes_tool._reduced_generation({
            "generationID": "0a1b2c3d-0000-4000-8000-000000000001", "text": "Private script text.",
            "notes": {"samplingWAVDigest": "a" * 64, "codecTraceSHA256": "b" * 64, "codecTraceFrameCount": "120",
                      "codecTraceComplete": "true", "codecTraceChunkRanges": "0:25", "message": "raw error"},
            "timingsMS": {positives.HOLD_FRAMES: 50, positives.HOLD_START: 88, "qwen_token_loop_total": 9},
            "modelRuntimeIdentity": {"speechTokenizerDigest": TOKENIZER, "modelRepository": "Qwen/private"}})
        self.assertEqual(row, {
            "generationID": "0A1B2C3D-0000-4000-8000-000000000001",
            "notes": {"samplingWAVDigest": "a" * 64, "codecTraceSHA256": "b" * 64, "codecTraceFrameCount": "120",
                      "codecTraceComplete": "true"},
            "timingsMS": {positives.HOLD_FRAMES: 50, positives.HOLD_START: 88},
            "speechTokenizerDigest": TOKENIZER})
        view = positives.row_view(row)
        self.assertEqual((view["codecTraceSHA256"], view["tokenizer"], view["hold"]),
                         ("b" * 64, TOKENIZER, {positives.HOLD_FRAMES: 50, positives.HOLD_START: 88}))
        # A row of a take without a trace or a hold keeps its original shape.
        plain = takes_tool._reduced_generation({"generationID": "0a1b2c3d-0000-4000-8000-000000000002",
                                                "notes": {"samplingWAVDigest": "c" * 64}})
        self.assertEqual(set(plain), {"generationID", "notes"})

    def test_pcm_digest_of_a_copied_take_is_its_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            samples = fixtures.render(fixtures.make_script(901, word_count=4), fixtures.VOICES["low"])
            path = Path(directory) / "a.wav"
            recordings.write_pcm16_wav(path, samples)
            self.assertEqual(positives.pcm_of(path)[0], pcm_digest(recordings.read_pcm16_wav(path)))


if __name__ == "__main__":
    unittest.main()
