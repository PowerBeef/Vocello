#!/usr/bin/env python3
"""The AQ-07 natural calibration takes: plan, batch files, binding and validation.

No model runs: the batch outputs are the `vocello batch --json` shapes of
`Sources/VocelloCLI/BatchCommand.swift` (BatchJSON and the schemaVersion 2
FailedBatchJSON), written by the tests beside placeholder WAV bytes.
"""

from __future__ import annotations

import collections
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audio_qc_calibration_takes as takes_module  # noqa: E402
from audio_qc_calibration_takes import (  # noqa: E402
    DEFAULT_POLICY,
    TakeError,
    batch_seed,
    build_manifest,
    build_plan,
    contract_speakers,
    load_policy,
    next_segment_offset,
    policy_issues,
    validate_manifest,
    validate_plan,
    write_batch_files,
)

LANGUAGES = {
    "english": ("en", "The quiet garden opens early every morning number {i}."),
    "french": ("fr", "Le jardin tranquille ouvre tôt chaque matin numéro {i}."),
    "chinese": ("zh", "安静的花园每天早上很早开门第{i}次。"),
}


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def pool_fixture(calibration: int = 60, confirmation: int = 9, languages=LANGUAGES) -> dict:
    """The committed pool's layout: languages declared once, scripts flat in `entries`."""
    declared, entries = [], []
    for language, (locale, template) in languages.items():
        scripts = []
        for index in range(calibration + confirmation):
            text = template.format(i=index)
            # Pool order is not script-ID order: the plan sorts by ID itself.
            scripts.append({
                "id": f"{locale}-{index + 1:04d}", "language": language, "text": text, "textSHA256": sha(text),
                "split": "calibration" if index < calibration else "confirmation",
                "unit": "characters" if language == "chinese" else "words", "length": 9, "sourceLine": index,
            })
        declared.append({"language": language, "commonVoiceLocale": locale})
        entries.extend(reversed(scripts))
    return {"schemaVersion": 1, "kind": "audio-qc-script-pool", "version": 1, "poolDigest": "a" * 64,
            "languages": declared, "entries": entries}


class Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.policy_path = DEFAULT_POLICY
        self.policy = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, name: str, value) -> Path:
        path = self.root / name
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def plan(self, pool=None, *, split="calibration", languages=None, run_id="run-1", policy_path=None) -> dict:
        pool_path = self.write("pool.json", pool if pool is not None else pool_fixture())
        return build_plan(pool_path=pool_path, policy_path=policy_path or self.policy_path, split=split,
                          run_id=run_id, languages=languages)


class PolicyTests(Fixture):
    def test_the_committed_policy_is_valid(self) -> None:
        self.assertEqual(policy_issues(self.policy, speakers=contract_speakers()), [])
        load_policy(DEFAULT_POLICY)

    def test_every_language_pairs_a_male_and_a_female_and_the_splits_share_no_speaker(self) -> None:
        genders = self.policy["speakerGenders"]
        briefs = {split: self.policy["splits"][split]["designBrief"] for split in ("calibration", "confirmation")}
        self.assertNotEqual(briefs["calibration"], briefs["confirmation"])
        for entry in self.policy["languages"]:
            for split in ("calibration", "confirmation"):
                self.assertEqual({genders[speaker] for speaker in entry[split]}, {"male", "female"})
            self.assertFalse(set(entry["calibration"]) & set(entry["confirmation"]), entry["language"])

    def test_a_shared_speaker_or_an_unknown_speaker_is_refused(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["languages"][0]["confirmation"] = list(policy["languages"][0]["calibration"])
        self.assertTrue(any("share" in issue for issue in policy_issues(policy, speakers=contract_speakers())))
        policy = copy.deepcopy(self.policy)
        policy["languages"][0]["calibration"][0] = "nobody"
        self.assertTrue(any("absent" in issue for issue in policy_issues(policy, speakers=contract_speakers())))


class PlanTests(Fixture):
    def test_the_committed_pool_plans_both_splits(self) -> None:
        # The lane reads the committed pool; its layout must stay plannable.
        for split in ("calibration", "confirmation"):
            plan = build_plan(pool_path=takes_module.DEFAULT_POOL, policy_path=self.policy_path,
                              split=split, run_id="run-1")
            self.assertEqual(plan["takeCount"] if "takeCount" in plan else len(plan["takes"]), 800, split)
            self.assertEqual(len({take["language"] for take in plan["takes"]}), 10, split)

    def test_the_plan_is_deterministic_and_bound_by_its_digests(self) -> None:
        first, second = self.plan(), self.plan()
        self.assertEqual(first, second)
        self.assertEqual(first["planDigest"], takes_module.self_digest(first, "planDigest"))
        self.assertEqual(first["policyDigest"], hashlib.sha256(DEFAULT_POLICY.read_bytes()).hexdigest())
        self.assertEqual(first["poolDigest"], "a" * 64)
        self.assertEqual(first["poolFileSHA256"], hashlib.sha256((self.root / "pool.json").read_bytes()).hexdigest())
        self.assertNotEqual(first["planDigest"], self.plan(run_id="run-2")["planDigest"])
        validate_plan(first)
        tampered = copy.deepcopy(first)
        tampered["takes"][0]["seed"] += 1
        with self.assertRaisesRegex(TakeError, "digest"):
            validate_plan(tampered)

    def test_primary_voices_rotate_over_the_three_voices_in_script_order(self) -> None:
        plan = self.plan(languages=["english"])
        primaries = sorted((take for take in plan["takes"] if take["role"] == "primary"),
                           key=lambda take: take["scriptID"])
        self.assertEqual(len(primaries), 60)
        order = ["aiden", "serena", "design-calm-narrator"]
        for index, take in enumerate(primaries):
            self.assertEqual(take["takeID"], f"{take['scriptID']}--{order[index % 3]}")
        self.assertEqual(collections.Counter(take["mode"] for take in primaries), {"custom": 40, "design": 20})
        design = next(take for take in primaries if take["mode"] == "design")
        self.assertEqual(design["voice"], {"kind": "design", "briefID": "calm-narrator",
                                           "brief": "A warm, friendly narrator with a calm, measured pace."})

    def test_donors_are_a_stratified_deterministic_subset_with_the_next_voice(self) -> None:
        plan = self.plan()
        for language in LANGUAGES:
            rows = [take for take in plan["takes"] if take["language"] == language]
            primary = {take["scriptID"]: take for take in rows if take["role"] == "primary"}
            donors = [take for take in rows if take["role"] == "donor"]
            self.assertEqual(len(donors), 20)
            voices = [voice["id"] if voice["kind"] == "builtin" else f"design-{voice['briefID']}"
                      for voice in takes_module.policy_voices(self.policy, language, "calibration")]
            by_primary = collections.Counter(primary[take["scriptID"]]["takeID"].split("--")[1] for take in donors)
            self.assertEqual(sorted(by_primary.values()), [6, 7, 7], "every ordered voice pair is represented")
            for donor in donors:
                first = primary[donor["scriptID"]]["takeID"].split("--")[1]
                expected = voices[(voices.index(first) + 1) % 3]
                self.assertEqual(donor["takeID"], f"{donor['scriptID']}--{expected}")
                self.assertEqual(donor["text"], primary[donor["scriptID"]]["text"])
                self.assertNotEqual(donor["family"], primary[donor["scriptID"]]["family"])
        self.assertEqual(plan["takeCount"], 3 * 80)
        # The committed expectation holds for the full ten-language calibration split.
        self.assertEqual(self.policy["splits"]["calibration"]["expectedTakeCount"], 10 * (60 + 20))

    def test_one_batch_per_voice_with_one_derived_seed(self) -> None:
        plan = self.plan()
        self.assertEqual(plan["batchCount"], 9)
        takes = {take["takeID"]: take for take in plan["takes"]}
        seeds = set()
        for batch in plan["batches"]:
            members = [takes[take_id] for take_id in batch["takeIDs"]]
            self.assertEqual({take["seed"] for take in members}, {batch["seed"]})
            self.assertEqual({json.dumps(take["voice"], sort_keys=True) for take in members},
                             {json.dumps(batch["voice"], sort_keys=True)})
            self.assertEqual([take["scriptID"] for take in members], sorted(take["scriptID"] for take in members))
            key = batch["voice"]["id"] if batch["voice"]["kind"] == "builtin" else f"design-{batch['voice']['briefID']}"
            self.assertEqual(batch["seed"], batch_seed(self.policy, "calibration", batch["language"], batch["mode"], key))
            self.assertLess(batch["seed"], 1 << 63)
            for take in members:
                self.assertEqual(take["family"], f"{take['scriptID']}:{key}:{batch['seed']}")
            seeds.add(batch["seed"])
        self.assertEqual(len(seeds), 9)
        self.assertEqual(len({take["family"] for take in plan["takes"]}), plan["takeCount"])
        confirmation = self.plan(split="confirmation")
        self.assertFalse(seeds & {batch["seed"] for batch in confirmation["batches"]})
        self.assertEqual({take["voice"].get("briefID") for take in confirmation["takes"] if take["mode"] == "design"},
                         {"bright-presenter"})

    def test_unknown_languages_empty_splits_and_unsafe_texts_are_refused(self) -> None:
        with self.assertRaisesRegex(TakeError, "unknown language"):
            self.plan(languages=["klingon"])
        with self.assertRaisesRegex(TakeError, "unknown language"):
            self.plan(languages=["german"])  # in the policy, absent from the pool
        with self.assertRaisesRegex(TakeError, "empty"):
            self.plan(pool_fixture(confirmation=0), split="confirmation")
        for bad in ("two\nlines", "carriage\rreturn", "unit\x1fseparator", "para graph", " edge", "tab\tinside"):
            pool = pool_fixture(calibration=3, confirmation=0, languages={"english": LANGUAGES["english"]})
            script = pool["entries"][0]
            script.update(text=bad, textSHA256=sha(bad))
            with self.assertRaisesRegex(TakeError, "one batch line", msg=repr(bad)):
                self.plan(pool)
        pool = pool_fixture(calibration=3, confirmation=0, languages={"english": LANGUAGES["english"]})
        pool["entries"][0]["textSHA256"] = "b" * 64
        with self.assertRaisesRegex(TakeError, "textSHA256"):
            self.plan(pool)
        pool = pool_fixture(calibration=3, confirmation=0, languages={"english": LANGUAGES["english"]})
        pool["languages"].append({"language": "klingon"})
        with self.assertRaisesRegex(TakeError, "klingon"):
            self.plan(pool)

    def test_batch_files_hold_one_text_per_line_in_plan_order(self) -> None:
        plan = self.plan(languages=["chinese"])
        rows = write_batch_files(plan, self.root / "batches")
        takes = {take["takeID"]: take for take in plan["takes"]}
        self.assertEqual([row["batchID"] for row in rows], [batch["batchID"] for batch in plan["batches"]])
        for row, batch in zip(rows, plan["batches"]):
            lines = row["file"].read_text(encoding="utf-8").split("\n")
            self.assertEqual(lines[-1], "")
            self.assertEqual(lines[:-1], [takes[take_id]["text"] for take_id in batch["takeIDs"]])
            fields = takes_module.batch_row_line(row).split("\x1f")
            self.assertEqual(fields[:5], [batch["batchID"], batch["mode"], "speed", "expressive", str(batch["seed"])])
            if batch["mode"] == "custom":
                self.assertEqual(fields[5:7], [batch["voice"]["id"], ""])
            else:
                self.assertEqual(fields[5:7], ["", batch["voice"]["brief"]])
            self.assertEqual(int(fields[7]), len(batch["takeIDs"]))


class ManifestTests(Fixture):
    def setUp(self) -> None:
        super().setUp()
        policy = copy.deepcopy(self.policy)
        policy["assignment"]["donorScriptsPerLanguage"] = 2
        self.small_policy = self.write("policy.json", policy)
        pool = pool_fixture(calibration=6, confirmation=0,
                            languages={key: LANGUAGES[key] for key in ("english", "chinese")})
        self.plan_value = self.plan(pool, policy_path=self.small_policy)
        self.plan_path = self.write("plan.json", self.plan_value)
        self.run_dir = self.root / "run"
        self.results = self.run_dir / "batch-results"
        self.wav_root = self.run_dir / "batch-out"
        self.results.mkdir(parents=True)
        self.takes = {take["takeID"]: take for take in self.plan_value["takes"]}

    def _batch_json(self, batch: dict, *, failed_at: int | None = None, text_override: dict | None = None,
                    offset: int = 0, failed_id: str = "00000000-0000-0000-0000-000000000001") -> dict:
        # One invocation's stdout; a resumed segment runs the batch's items from `offset`.
        out_dir = self.wav_root / (batch["batchID"] + (f"@{offset}" if offset else ""))
        out_dir.mkdir(parents=True, exist_ok=True)
        items, rows = [], []
        take_ids = batch["takeIDs"][offset:]
        for index, take_id in enumerate(take_ids):
            path = out_dir / f"stamp_{batch['mode']}_{index:03d}.wav"
            if failed_at is None or index < failed_at:
                path.write_bytes(b"RIFF" + take_id.encode("utf-8"))
                text = (text_override or {}).get(index, self.takes[take_id]["text"])
                items.append({"index": index, "text": text, "audioPath": str(path), "durationSeconds": 2.5,
                              "finishReason": "eos"})
                rows.append({"index": index, "generationID": "00000000-0000-0000-0000-000000000000",
                             "status": "completed", "audioPath": str(path), "durationSeconds": 2.5,
                             "finishReason": "eos"})
            elif index == failed_at:
                rows.append({"index": index, "generationID": failed_id,
                             "status": "failed", "errorCode": "generation_failed"})
            else:
                rows.append({"index": index, "generationID": "00000000-0000-0000-0000-000000000002",
                             "status": "not_attempted"})
        model = "pro_custom_speed" if batch["mode"] == "custom" else "pro_design_speed"
        if failed_at is None:
            return {"count": len(items), "items": items, "mode": batch["mode"], "modelID": model,
                    "variant": "speed", "wallSeconds": 12.0}
        return {"completedCount": failed_at, "items": rows, "mode": batch["mode"], "modelID": model,
                "plannedCount": len(take_ids), "schemaVersion": 2, "variant": "speed", "wallSeconds": 3.0}

    def _emit(self, batch: dict, payload: dict, *, offset: int = 0) -> Path:
        # The CLI prints sorted-key JSON on one line, as emitJSON does.
        path = self.results / (f"{batch['batchID']}@{offset}.json" if offset else f"{batch['batchID']}.json")
        path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _manifest(self, diagnostics: Path | None = None) -> dict:
        return build_manifest(plan_path=self.plan_path, batch_results=self.results, wav_root=self.wav_root,
                              output=self.run_dir / "takes-manifest.json", diagnostics=diagnostics)

    def _diagnostics(self, records: dict[str, tuple[str, str | None]]) -> Path:
        """An engine diagnostics root recording each generation's failure code and QC flags."""
        engine = self.root / "diagnostics" / "engine"
        engine.mkdir(parents=True, exist_ok=True)
        with (engine / "generation-failures.jsonl").open("w", encoding="utf-8") as failures, \
                (engine / "generations.jsonl").open("w", encoding="utf-8") as generations:
            for generation_id, (code, flags) in records.items():
                failures.write(json.dumps({"generationID": generation_id, "errorCode": code,
                                           "stage": "stream_failed"}) + "\n")
                notes = {"nativeRuntimeFailureCode": code, **({"audioQCFlags": flags} if flags else {})}
                generations.write(json.dumps({"generationID": generation_id, "notes": notes}) + "\n")
        return self.root / "diagnostics"

    def test_every_output_binds_to_its_planned_take_and_validates(self) -> None:
        for batch in self.plan_value["batches"]:
            self._emit(batch, self._batch_json(batch))
        manifest = self._manifest()
        self.assertEqual(manifest["counts"],
                         {"planned": 16, "generated": 16, "rejected": 0, "failed": 0, "missing": 0})
        self.assertEqual([take["takeID"] for take in manifest["takes"]],
                         [take["takeID"] for take in self.plan_value["takes"]])
        for take in manifest["takes"]:
            self.assertEqual(take["wavPath"], f"wav/{take['takeID']}.wav")
            wav = self.run_dir / take["wavPath"]
            self.assertEqual(wav.read_bytes(), b"RIFF" + take["takeID"].encode("utf-8"))
            self.assertEqual(take["wavSHA256"], hashlib.sha256(wav.read_bytes()).hexdigest())
            self.assertEqual((take["durationSeconds"], take["finishReason"], take["textBinding"]), (2.5, "eos", "text"))
        self.assertFalse(any(self.wav_root.rglob("*.wav")), "the WAVs moved into the run's wav directory")
        written = json.loads((self.run_dir / "takes-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(written, manifest)
        self.assertNotIn(str(self.root), json.dumps(written), "no absolute local path in the manifest")
        report = validate_manifest(written, self.plan_value, manifest_dir=self.run_dir)
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(report["duplicateWavDigests"], 0)

    def test_a_text_mismatch_is_refused(self) -> None:
        batch = self.plan_value["batches"][0]
        self._emit(batch, self._batch_json(batch, text_override={1: "Something else entirely."}))
        with self.assertRaisesRegex(TakeError, "differs from the planned text"):
            self._manifest()

    def test_a_foreign_batch_output_is_refused(self) -> None:
        batch = self.plan_value["batches"][0]
        payload = self._batch_json(batch)
        payload["variant"] = "quality"
        self._emit(batch, payload)
        with self.assertRaisesRegex(TakeError, "mode or variant"):
            self._manifest()
        payload = self._batch_json(batch)
        payload["items"].pop()
        payload["count"] -= 1
        self._emit(batch, payload)
        with self.assertRaisesRegex(TakeError, "items"):
            self._manifest()

    def test_a_failed_batch_and_an_absent_batch_leave_missing_rows(self) -> None:
        failed, absent, *rest = self.plan_value["batches"]
        self._emit(failed, self._batch_json(failed, failed_at=1))
        for batch in rest:
            self._emit(batch, self._batch_json(batch))
        manifest = self._manifest()
        by_id = {take["takeID"]: take for take in manifest["takes"]}
        first, second, *later = failed["takeIDs"]
        self.assertEqual((by_id[first]["status"], by_id[first]["textBinding"]), ("generated", "index"))
        self.assertEqual(by_id[second]["missingReason"], "batch-failed:generation_failed")
        for take_id in later:
            self.assertEqual(by_id[take_id]["missingReason"], "batch-not_attempted")
        for take_id in absent["takeIDs"]:
            self.assertEqual((by_id[take_id]["status"], by_id[take_id]["missingReason"]), ("missing", "no-batch-output"))
            self.assertIsNone(by_id[take_id]["wavPath"])
        missing = len(failed["takeIDs"]) - 1 + len(absent["takeIDs"])
        self.assertEqual(manifest["counts"], {"planned": 16, "generated": 16 - missing, "rejected": 0,
                                              "failed": 0, "missing": missing})
        report = validate_manifest(manifest, self.plan_value, manifest_dir=self.run_dir)
        self.assertEqual(report["status"], "PASS", report)
        self.assertEqual(report["counts"]["missing"], missing)

    def test_a_resumed_batch_binds_its_segments_and_the_engine_rejection(self) -> None:
        # Item 1 is refused by the engine's mandatory Fast QC; the lane resumes at 2.
        batch = max(self.plan_value["batches"], key=lambda value: len(value["takeIDs"]))
        rest = [other for other in self.plan_value["batches"] if other is not batch]
        self.assertGreater(len(batch["takeIDs"]), 2)
        rejected_id = "0A1B2C3D-0000-4000-8000-00000000AAAA"
        first = self._emit(batch, self._batch_json(batch, failed_at=1, failed_id=rejected_id))
        self.assertEqual(next_segment_offset(first, 0, len(batch["takeIDs"])), "2")
        self._emit(batch, self._batch_json(batch, offset=2), offset=2)
        for other in rest:
            self._emit(other, self._batch_json(other))
        diagnostics = self._diagnostics({rejected_id: ("audio.quality_rejected", "dropout:2512ms,speaking_rate_slow")})
        manifest = self._manifest(diagnostics)
        by_id = {take["takeID"]: take for take in manifest["takes"]}
        head, refused, *resumed = batch["takeIDs"]
        self.assertEqual(by_id[head]["status"], "generated")
        self.assertEqual(by_id[refused]["status"], "rejected")
        self.assertEqual(by_id[refused]["rejection"], {"errorCode": "audio.quality_rejected",
                                                       "audioQCFlags": ["dropout:2512ms", "speaking_rate_slow"]})
        for take_id in resumed:
            self.assertEqual((by_id[take_id]["status"], by_id[take_id]["textBinding"]), ("generated", "text"))
        self.assertEqual(manifest["counts"], {"planned": 16, "generated": 15, "rejected": 1, "failed": 0,
                                              "missing": 0})
        report = validate_manifest(manifest, self.plan_value, manifest_dir=self.run_dir)
        self.assertEqual(report["status"], "PASS", report)

    def test_an_unrecorded_or_other_engine_failure_is_not_a_rejection(self) -> None:
        batch, *rest = self.plan_value["batches"]
        other_id = "0A1B2C3D-0000-4000-8000-00000000BBBB"
        self._emit(batch, self._batch_json(batch, failed_at=0, failed_id=other_id))
        self._emit(batch, self._batch_json(batch, offset=1), offset=1)
        for later in rest:
            self._emit(later, self._batch_json(later))
        take_id = batch["takeIDs"][0]
        manifest = self._manifest()
        self.assertEqual(manifest["takes"][[t["takeID"] for t in manifest["takes"]].index(take_id)]["status"],
                         "missing")
        manifest = self._manifest(self._diagnostics({other_id: ("model.load_failed", None)}))
        take = {t["takeID"]: t for t in manifest["takes"]}[take_id]
        self.assertEqual((take["status"], take["failure"]), ("failed", {"errorCode": "model.load_failed"}))
        self.assertEqual(validate_manifest(manifest, self.plan_value, manifest_dir=self.run_dir)["status"], "PASS")

    def test_next_offset_resumes_only_after_a_generation_failure(self) -> None:
        batch = self.plan_value["batches"][0]
        count = len(batch["takeIDs"])
        last = self._emit(batch, self._batch_json(batch, failed_at=count - 1))
        self.assertEqual(next_segment_offset(last, 0, count), "done")
        cancelled = self._batch_json(batch, failed_at=0)
        cancelled["items"][0].update(status="cancelled", errorCode="cancelled")
        self.assertEqual(next_segment_offset(self._emit(batch, cancelled), 0, count), "stop")
        self.assertEqual(next_segment_offset(self._emit(batch, self._batch_json(batch)), 0, count), "stop")
        self.assertEqual(next_segment_offset(self.results / "absent.json", 0, count), "stop")

    def test_validate_manifest_catches_tampering(self) -> None:
        for batch in self.plan_value["batches"]:
            self._emit(batch, self._batch_json(batch))
        manifest = self._manifest()

        edited = copy.deepcopy(manifest)
        edited["takes"][0]["seed"] += 1
        self.assertIn("manifest digest", validate_manifest(edited, self.plan_value, manifest_dir=self.run_dir)["errors"][0])
        edited["manifestDigest"] = takes_module.self_digest(edited, "manifestDigest")
        report = validate_manifest(edited, self.plan_value, manifest_dir=self.run_dir)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any("differs from its planned take" in error for error in report["errors"]))

        dropped = copy.deepcopy(manifest)
        dropped["takes"].pop()
        dropped["manifestDigest"] = takes_module.self_digest(dropped, "manifestDigest")
        self.assertEqual(validate_manifest(dropped, self.plan_value, manifest_dir=self.run_dir)["status"], "FAIL")

        other_plan = copy.deepcopy(self.plan_value)
        other_plan["runID"] = "run-other"
        other_plan["planDigest"] = takes_module.self_digest(other_plan, "planDigest")
        report = validate_manifest(manifest, other_plan, manifest_dir=self.run_dir)
        self.assertTrue(any("runID" in error for error in report["errors"]))

        broken_plan = copy.deepcopy(self.plan_value)
        broken_plan["takes"][0]["text"] = "Changed."
        self.assertIn("plan:", validate_manifest(manifest, broken_plan, manifest_dir=self.run_dir)["errors"][0])

        wav = self.run_dir / manifest["takes"][0]["wavPath"]
        wav.write_bytes(b"RIFF tampered")
        report = validate_manifest(manifest, self.plan_value, manifest_dir=self.run_dir)
        self.assertTrue(any("do not match their digest" in error for error in report["errors"]))

    @staticmethod
    def _summary(frames: int, span: int | None = None) -> dict:
        """An engine introspection block as the telemetry row encodes it (nil fields omitted)."""
        block = {"algorithmVersion": 1, "codecFrameCount": frames, "longestRepeatedTokenRunFrames": 2,
                 "observedStepCount": frames + 1, "entropyMeanNats": 0.8, "entropyP95Nats": 1.9,
                 "longestHighEntropyRunSteps": 0, "eosProbabilityFinal": 0.6, "eosProbabilityMax": 0.6,
                 "eosProbabilityMaxStep": frames, "eosLikelyStepsWithoutStop": 0, "seamCodecFrames": []}
        if span is not None:
            block.update(tokenCyclePeriod=8, tokenCycleSpanFrames=span, tokenCycleRepeats=span // 8,
                         tokenCycleStartFrame=4)
        return block

    def test_generated_takes_carry_the_engine_introspection_bound_by_their_wav_digest(self) -> None:
        for batch in self.plan_value["batches"]:
            self._emit(batch, self._batch_json(batch))
        first, second, third, *_ = self.plan_value["takes"]
        digests = {take["takeID"]: hashlib.sha256(b"RIFF" + take["takeID"].encode("utf-8")).hexdigest()
                   for take in (first, second, third)}
        engine = self.root / "diagnostics" / "engine"
        engine.mkdir(parents=True)
        rows = [
            # The first take's row, twice (a resumed item regenerates it identically) beside an unrelated row.
            {"generationID": "A", "notes": {"samplingWAVDigest": digests[first["takeID"]]},
             "engineIntrospection": self._summary(60, span=32)},
            {"generationID": "B", "notes": {"samplingWAVDigest": digests[first["takeID"]]},
             "engineIntrospection": self._summary(60, span=32)},
            {"generationID": "C", "notes": {"samplingWAVDigest": "f" * 64}, "engineIntrospection": self._summary(9)},
            # The second take's rows disagree: no summary is bound.
            {"generationID": "D", "notes": {"samplingWAVDigest": digests[second["takeID"]]},
             "engineIntrospection": self._summary(40)},
            {"generationID": "E", "notes": {"samplingWAVDigest": digests[second["takeID"]]},
             "engineIntrospection": self._summary(41)},
            # The third take's row is not the engine's shape.
            {"generationID": "F", "notes": {"samplingWAVDigest": digests[third["takeID"]]},
             "engineIntrospection": {"codecFrameCount": -1}},
        ]
        (engine / "generations.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        manifest = self._manifest(self.root / "diagnostics")
        by_id = {take["takeID"]: take for take in manifest["takes"]}
        bound = by_id[first["takeID"]]["engineIntrospection"]
        self.assertEqual((bound["tokenCycleSpanFrames"], bound["codecFrameCount"], bound["eosFirstLikelyStep"],
                          bound["wavSHA256"]), (32, 60, None, digests[first["takeID"]]))
        self.assertIsNone(by_id[second["takeID"]]["engineIntrospection"])
        self.assertIsNone(by_id[third["takeID"]]["engineIntrospection"])
        self.assertEqual(manifest["introspection"], {"bound": 1, "unbound": 15})
        self.assertTrue(all(take["longForm"] is None for take in manifest["takes"]))
        report = validate_manifest(manifest, self.plan_value, manifest_dir=self.run_dir)
        self.assertEqual(report["status"], "PASS", report)
        # The block is checked, and so are the counts.
        edited = copy.deepcopy(manifest)
        edited["takes"][0]["engineIntrospection"]["entropyMeanNats"] = -1.0
        edited["manifestDigest"] = takes_module.self_digest(edited, "manifestDigest")
        self.assertTrue(any("entropyMeanNats" in error for error in validate_manifest(
            edited, self.plan_value, manifest_dir=self.run_dir)["errors"]))
        edited = copy.deepcopy(manifest)
        edited["takes"][0]["engineIntrospection"] = None
        edited["manifestDigest"] = takes_module.self_digest(edited, "manifestDigest")
        self.assertIn("the manifest's introspection counts do not match its takes",
                      validate_manifest(edited, self.plan_value, manifest_dir=self.run_dir)["errors"])
        # Without diagnostics, no summary and no counts.
        plain = self._manifest()
        self.assertNotIn("introspection", plain)
        self.assertTrue(all(take["engineIntrospection"] is None for take in plain["takes"]))

    def test_a_long_form_block_reduces_the_assembly_evidence(self) -> None:
        def segment(start: int, end: int, pause: int) -> dict:
            return {"segmentID": f"s{start}", "contentOutputRange": {"lowerBound": start, "upperBound": end},
                    "insertedPauseOutputRange": {"lowerBound": end, "upperBound": end + pause}}
        evidence = {"schemaVersion": 1, "algorithmVersion": 4, "sampleRate": 24_000, "blockFrames": 4096,
                    "segmentCount": 3, "outputFrameCount": 90_000, "maximumSegmentBoundaryJump": 812,
                    "outputDigest": "0" * 64, "outputReadable": True,
                    "segments": [segment(0, 24_000, 7_200), segment(31_200, 60_000, 0), segment(60_000, 90_000, 0)]}
        block = takes_module.long_form_block(evidence)
        self.assertEqual(block, {"schemaVersion": 1, "algorithmVersion": 4, "sampleRate": 24_000, "segmentCount": 3,
                                 "outputFrameCount": 90_000, "maximumSegmentBoundaryJump": 812,
                                 "seamFrames": [31_200, 60_000]})
        self.assertEqual(takes_module.seam_seconds(block), [1.3, 2.5])
        self.assertEqual(takes_module.long_form_issues(block), [])
        for change, fragment in ((lambda value: value.update(seamFrames=[60_000, 31_200]), "increase strictly"),
                                 (lambda value: value.update(seamFrames=[31_200]), "one seam per join"),
                                 (lambda value: value.update(seamFrames=[31_200, 90_000]), "inside the output"),
                                 (lambda value: value.update(maximumSegmentBoundaryJump=-3), "non-negative"),
                                 (lambda value: value.update(extra=1), "declares exactly")):
            broken = copy.deepcopy(block)
            change(broken)
            self.assertTrue(any(fragment in issue for issue in takes_module.long_form_issues(broken)), fragment)
        with self.assertRaisesRegex(TakeError, "lists no segments"):
            takes_module.long_form_block({"sampleRate": 24_000})

    def test_the_command_line_round_trip(self) -> None:
        for batch in self.plan_value["batches"]:
            self._emit(batch, self._batch_json(batch))
        manifest_path = self.run_dir / "takes-manifest.json"
        with contextlib.redirect_stdout(io.StringIO()) as out:
            code = takes_module.main(["manifest", "--plan", str(self.plan_path), "--batch-results", str(self.results),
                                      "--wav-root", str(self.wav_root), "--output", str(manifest_path)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()), {"planned": 16, "generated": 16, "rejected": 0, "failed": 0, "missing": 0})
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(takes_module.main(["validate-manifest", "--manifest", str(manifest_path),
                                                "--plan", str(self.plan_path)]), 0)
        (self.run_dir / "wav" / f"{self.plan_value['takes'][0]['takeID']}.wav").unlink()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(takes_module.main(["validate-manifest", "--manifest", str(manifest_path),
                                                "--plan", str(self.plan_path)]), 1)
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(takes_module.main(["plan", "--pool", str(self.root / "pool.json"), "--policy",
                                                str(self.small_policy), "--split", "calibration",
                                                "--languages", "english,klingon", "--run-id", "run-1",
                                                "--output", str(self.root / "refused.json")]), 1)
        self.assertIn("klingon", err.getvalue())
        self.assertFalse((self.root / "refused.json").exists())


if __name__ == "__main__":
    unittest.main()
