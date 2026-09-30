#!/usr/bin/env python3
"""The AQ-07 natural calibration takes: plan, batch files, binding and validation.

No model runs: the batch outputs are the `vocello batch --json` shapes of
`Sources/VocelloCLI/BatchCommand.swift` (BatchJSON, the schemaVersion 2
FailedBatchJSON and their `--long-form` forms), written by the tests beside
placeholder WAV bytes; the clone cell reads fixture speaker-corpus manifests
built in the `audio_qc_corpora.py extract` layout.
"""

from __future__ import annotations

import collections
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
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

    def test_the_splits_share_no_speaker_in_any_language_and_calibration_pairs_genders(self) -> None:
        # The qualification driver checks speaker disjointness across the whole cohort, not per language.
        genders = self.policy["speakerGenders"]
        partition = self.policy["speakerPartition"]
        self.assertFalse(set(partition["calibration"]) & set(partition["confirmation"]))
        self.assertEqual(set(partition["calibration"]) | set(partition["confirmation"]), contract_speakers())
        briefs = takes_module._split_brief_families(self.policy)
        self.assertFalse(briefs["calibration"] & briefs["confirmation"])
        self.assertIn("calm-narrator-fr", briefs["calibration"])
        self.assertIn("gentle-teacher", briefs["confirmation"])
        for entry in self.policy["languages"]:
            self.assertEqual({genders[speaker] for speaker in entry["calibration"]}, {"male", "female"})
            for split in ("calibration", "confirmation"):
                self.assertTrue(set(entry[split]) <= set(partition[split]), (entry["language"], split))
        # The 2026-09-27 calibration cohort's speakers stay calibration speakers, so it can stand beside a
        # confirmation cohort; the confirmation's female voices are its briefs and clone references.
        self.assertEqual(set(partition["calibration"]), {"aiden", "serena", "vivian", "uncle_fu", "ono_anna", "sohee"})
        self.assertIn("female", self.policy["designBriefs"][self.policy["splits"]["confirmation"]["designBrief"]]["text"])

    def test_a_shared_speaker_or_an_unknown_speaker_is_refused(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["languages"][0]["confirmation"] = list(policy["languages"][0]["calibration"])
        self.assertTrue(any("share" in issue for issue in policy_issues(policy, speakers=contract_speakers())))
        policy = copy.deepcopy(self.policy)
        policy["languages"][0]["calibration"][0] = "nobody"
        self.assertTrue(any("absent" in issue for issue in policy_issues(policy, speakers=contract_speakers())))

    def test_the_cells_layout_is_checked(self) -> None:
        def issues(change) -> list[str]:
            policy = copy.deepcopy(self.policy)
            change(policy)
            return policy_issues(policy, speakers=contract_speakers())

        cases = (
            # A Built-in speaker in both splits' partitions, or one the partition drops.
            (lambda p: p["speakerPartition"]["confirmation"].append("aiden"), "exactly one split"),
            (lambda p: p["speakerPartition"]["confirmation"].remove("eric"), "cover exactly"),
            # A confirmation pair borrowing a calibration speaker.
            (lambda p: p["languages"][0]["confirmation"].__setitem__(1, "serena"), "other split"),
            (lambda p: p["languages"][0]["calibration"].__setitem__(1, "uncle_fu"), "male and a female"),
            # The cross-lingual cell needs the split brief in every other language.
            (lambda p: p["designBriefs"].pop("calm-narrator-fr"), "french translation of calm-narrator"),
            (lambda p: p["designBriefs"]["bright-presenter-de"].update(concept="calm-narrator"),
             "exactly one german translation of bright-presenter"),
            (lambda p: p["splits"]["confirmation"]["crossLingualBriefs"].append("deep-storyteller"),
             "different design briefs"),
            (lambda p: p["cells"]["clone"]["referenceSources"]["english"].append("mls"), "does not cover english"),
            (lambda p: p["cells"]["clone"]["referenceSources"]["english"].append("resd"), "not a registered speaker"),
            (lambda p: p["cells"]["clone"]["referenceSources"]["english"].append("crema-d"), "labels no speaker"),
            (lambda p: p["cells"]["clone"].update(primaryReferencesPerLanguage=11), "one primary take"),
            (lambda p: p["cells"]["clone"]["referenceWindowSeconds"].update(minimum=40.0), "0 < minimum"),
            (lambda p: p["cells"]["long-form"]["estimateWindow"].update(minimum=300), "runtimeTokenLimit < minimum"),
            (lambda p: p["cells"]["long-form"].update(languages=["english", "french"]), "at least 3"),
            (lambda p: p.update(defaultCells=["standard", "long-form"]), "long-form alone"),
            (lambda p: p.update(version=1), "at least 2"),
        )
        for change, fragment in cases:
            found = issues(change)
            self.assertTrue(any(fragment in issue for issue in found), (fragment, found))

    def test_every_built_in_speaker_speaks_every_language_across_the_two_splits(self) -> None:
        natives = takes_module.contract_speaker_languages()
        self.assertEqual(natives["aiden"], "english")
        self.assertEqual(natives["ono_anna"], "japanese")
        for entry in self.policy["languages"]:
            language = entry["language"]
            speakers = set()
            for split in ("calibration", "confirmation"):
                standard = [voice["id"] for voice in takes_module.policy_voices(self.policy, language, split)
                            if voice["kind"] == "builtin"]
                cross = takes_module.cross_lingual_voices(self.policy, language, split)
                crossing = [voice["id"] for voice in cross if voice["kind"] == "builtin"]
                self.assertFalse(set(standard) & set(crossing))
                speakers |= set(standard) | set(crossing)
                briefs = [voice["briefID"] for voice in cross if voice["kind"] == "design"]
                languages = [self.policy["designBriefs"][brief]["language"] for brief in briefs]
                # The English-accent-in-French case: English briefs beside one in the target language.
                self.assertIn("english", languages)
                if language != "english":
                    self.assertEqual(languages.count(language), 1, (language, split))
            self.assertEqual(speakers, contract_speakers(), language)


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


def speakers_of(plan: dict) -> set[str]:
    """The qualification driver's speaker units: a take's voice key (audio_qc_detector_calibration)."""
    return {takes_module.voice_key(take["voice"]) for take in plan["takes"]}


class CellPlanTests(Fixture):
    def committed(self, split: str, cells: list[str], **options) -> dict:
        return build_plan(pool_path=takes_module.DEFAULT_POOL, policy_path=self.policy_path, split=split,
                          run_id="run-1", cells=cells, **options)

    def test_the_standard_cell_keeps_the_version_1_layout(self) -> None:
        plan = self.plan()
        self.assertEqual(plan["cells"], ["standard"])
        self.assertEqual({take["cell"] for take in plan["takes"]}, {"standard"})
        english = [take for take in plan["takes"] if take["language"] == "english"]
        self.assertEqual({take["voiceLanguage"] for take in english if take["mode"] == "custom"},
                         {"english", "chinese"})  # aiden and serena
        take = english[0]
        self.assertEqual(take["batchID"], f"calibration-english-{take['takeID'].split('--')[1]}")
        self.assertEqual(take["seed"], batch_seed(self.policy, "calibration", "english", take["mode"],
                                                  take["takeID"].split("--")[1]))

    def test_the_cross_lingual_cell_records_voice_and_target_languages(self) -> None:
        plans = {split: self.committed(split, ["cross-lingual"]) for split in ("calibration", "confirmation")}
        standard = {split: self.committed(split, ["standard"]) for split in ("calibration", "confirmation")}
        for split, plan in plans.items():
            self.assertEqual(plan["takeCount"], 800)
            self.assertEqual(plan["expectedTakeCount"], 800)
            per_language = collections.Counter(take["language"] for take in plan["takes"])
            self.assertEqual(set(per_language.values()), {80})
            self.assertEqual(collections.Counter(take["role"] for take in plan["takes"]),
                             {"primary": 600, "donor": 200})
            # No batch, take or seed is the standard cell's.
            self.assertFalse({b["batchID"] for b in plan["batches"]} & {b["batchID"] for b in standard[split]["batches"]})
            self.assertFalse({t["takeID"] for t in plan["takes"]} & {t["takeID"] for t in standard[split]["takes"]})
            self.assertFalse({b["seed"] for b in plan["batches"]} & {b["seed"] for b in standard[split]["batches"]})
            french = [take for take in plan["takes"] if take["language"] == "french"]
            design_languages = {take["voiceLanguage"] for take in french if take["mode"] == "design"}
            self.assertEqual(design_languages, {"english", "french"})
            self.assertTrue(any(take["mode"] == "custom" and take["voiceLanguage"] == "chinese" for take in french))
        # Disjoint by speaker (voice key) and script across the whole cohort, with the standard cell too.
        calibration = speakers_of(plans["calibration"]) | speakers_of(standard["calibration"])
        confirmation = speakers_of(plans["confirmation"]) | speakers_of(standard["confirmation"])
        self.assertFalse(calibration & confirmation)
        self.assertFalse({t["scriptID"] for t in plans["calibration"]["takes"]}
                         & {t["scriptID"] for t in plans["confirmation"]["takes"]})

    def test_the_conservative_estimate_mirrors_the_swift_planner(self) -> None:
        estimate = takes_module.conservative_token_estimate
        self.assertEqual(estimate("The quiet garden."), 6)       # 1 + 2 + 2 + the period
        self.assertEqual(estimate("don't-stop"), 4)               # one ASCII run of 10
        self.assertEqual(estimate("été"), 3)                      # each accented letter ends the run
        self.assertEqual(estimate("你好。"), 3)
        self.assertEqual(estimate("a   b"), 2)               # whitespace costs nothing
        self.assertEqual(estimate("\U0001F44D"), 2)               # four UTF-8 bytes
        self.assertEqual(estimate("é"), 1)                  # one grapheme of two scalars

    def test_the_long_form_cell_plans_projects_above_the_token_limit(self) -> None:
        plans = {split: self.committed(split, ["long-form"]) for split in ("calibration", "confirmation")}
        config = self.policy["cells"]["long-form"]
        pool = json.loads(takes_module.DEFAULT_POOL.read_text(encoding="utf-8"))
        split_of = {entry["id"]: entry["split"] for entry in pool["entries"]}
        text_of = {entry["id"]: entry["text"] for entry in pool["entries"]}
        for split, plan in plans.items():
            self.assertEqual((plan["takeCount"], plan["expectedTakeCount"]), (80, 80))
            self.assertTrue(all(batch["longForm"] is True and batch["cell"] == "long-form" for batch in plan["batches"]))
            for take in plan["takes"]:
                units = takes_module.conservative_token_estimate(take["text"])
                self.assertGreater(units, config["runtimeTokenLimit"])
                self.assertTrue(config["estimateWindow"]["minimum"] <= units <= config["estimateWindow"]["maximum"])
                self.assertEqual({split_of[script] for script in take["projectScripts"]}, {split})
                self.assertEqual((take["role"], take["family"].split(":")[0]), ("project", take["scriptID"]))
                self.assertEqual(takes_module.text_issues(take["text"]), [])
                self.assertIn(take["voice"], takes_module.policy_voices(self.policy, take["language"], split))
                joiner = "" if take["language"] in config["unspacedLanguages"] else " "
                self.assertEqual(joiner.join(text_of[script] for script in take["projectScripts"]), take["text"])
            self.assertEqual(len({take["text"] for take in plan["takes"]}), 80)
            self.assertEqual(len({take["language"] for take in plan["takes"]}), 10)
        self.assertFalse(speakers_of(plans["calibration"]) & speakers_of(plans["confirmation"]))
        with self.assertRaisesRegex(TakeError, "alone"):
            self.committed("calibration", ["standard", "long-form"])
        with self.assertRaisesRegex(TakeError, "unknown cell"):
            self.committed("calibration", ["duet"])


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

    def test_a_version_1_plan_and_manifest_still_validate(self) -> None:
        # A plan and manifest written before the cells (the 2026-09-27 cohort's shape) keep validating.
        plan = copy.deepcopy(self.plan_value)
        plan.pop("cells")
        for record in [*plan["takes"], *plan["batches"]]:
            for key in ("cell", "voiceLanguage"):
                record.pop(key, None)
        plan["planDigest"] = takes_module.self_digest(plan, "planDigest")
        self.plan_path = self.write("plan-v1.json", plan)
        for batch in plan["batches"]:
            self._emit(batch, self._batch_json(batch))
        manifest = self._manifest()
        self.assertNotIn("cells", manifest)
        for take in manifest["takes"]:
            for key in ("longFormSegments", "reference", "cell", "voiceLanguage"):
                take.pop(key, None)
        manifest["manifestDigest"] = takes_module.self_digest(manifest, "manifestDigest")
        report = validate_manifest(manifest, plan, manifest_dir=self.run_dir)
        self.assertEqual(report["status"], "PASS", report)


def emit_outputs(plan: dict, results: Path, wav_root: Path) -> None:
    """Every batch completed, as `vocello batch --json` prints it (placeholder WAV bytes per take)."""
    takes = {take["takeID"]: take for take in plan["takes"]}
    results.mkdir(parents=True, exist_ok=True)
    for batch in plan["batches"]:
        out_dir = wav_root / batch["batchID"]
        out_dir.mkdir(parents=True, exist_ok=True)
        items = []
        for index, take_id in enumerate(batch["takeIDs"]):
            path = out_dir / f"stamp_{batch['mode']}_{index:03d}.wav"
            path.write_bytes(b"RIFF" + take_id.encode("utf-8"))
            items.append({"index": index, "text": takes[take_id]["text"], "audioPath": str(path),
                          "durationSeconds": 2.5, "finishReason": "eos"})
        payload = {"count": len(items), "items": items, "mode": batch["mode"], "modelID": f"pro_{batch['mode']}_speed",
                   "variant": "speed", "wallSeconds": 1.0}
        (results / f"{batch['batchID']}.json").write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Clone references over fixture speaker corpora
# --------------------------------------------------------------------------- #

CLONE_SOURCES = {"libritts-r": ["english"], "mls": ["french", "german", "spanish", "italian", "portuguese"],
                 "emozionalmente": ["italian"], "aishell3-subset": ["chinese"], "zeroth-korean": ["korean"]}
GENDERED = frozenset({"emozionalmente", "aishell3-subset"})


def build_corpora(root: Path, speakers: int = 60) -> None:
    """Extracted speaker-corpus manifests in the `audio_qc_corpora.py extract` layout, with placeholder WAVs."""
    import audio_qc_corpora as corpora

    registry = corpora.load_registry()
    for source, languages in CLONE_SOURCES.items():
        directory = corpora.source_directory(registry, source, root) / corpora.EXTRACTED_DIRECTORY
        (directory / "wav").mkdir(parents=True)
        records = []
        for language in languages:
            # One MLS reader also reads German: the same speaker id in two languages.
            extra = ["polyglot"] if source == "mls" and language in ("french", "german") else []
            for number, speaker in enumerate([f"{language[:2]}{index:03d}" for index in range(speakers)] + extra):
                gender = ("female", "male")[(number // 2) % 2] if source in GENDERED else None
                if source == "emozionalmente":
                    # Only a neutral clip may be a reference: odd speakers have none.
                    clips = [(12.0, f"Frase numero {number}.", *(("neutrality", "neutral") if number % 2 == 0
                                                                  else ("anger", "angry")))]
                else:
                    clips = [(12.0, f"Reference sentence {number} in {language}.", None, None),
                             (6.0, f"A shorter sentence {number}.", None, None),
                             (2.0, "Too short.", None, None),
                             (8.0, None, None, None),
                             (15.0, "- a transcript read as a flag", None, None)]
                for index, (duration, text, emotion, canonical) in enumerate(clips):
                    clip_id = f"{source}-{language}-{speaker}-{index}"
                    data = b"RIFF" + clip_id.encode("utf-8")
                    (directory / "wav" / f"{clip_id}.wav").write_bytes(data)
                    records.append({
                        "clipID": clip_id, "family": clip_id, "language": language, "split": "test",
                        "sourceID": clip_id, "speaker": speaker, "gender": gender, "emotion": emotion,
                        "emotionCanonical": canonical, "intensity": None, "accent": None, "scores": None,
                        "text": text, "textID": None, "durationSeconds": duration, "sampleRate": 16000,
                        "samples": int(duration * 16000), "wavPath": f"wav/{clip_id}.wav",
                        "wavSHA256": hashlib.sha256(data).hexdigest(), "wavBytes": len(data), "resampled": False,
                        "clippedSamples": 0, "source": {"origin": clip_id}, "duplicates": [],
                    })
        manifest = corpora.build_manifest(registry, source, records, [], metadata={}, members={})
        (directory / corpora.MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


class CloneTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temporary.name)
        cls.corpora = cls.base / "corpora"
        build_corpora(cls.corpora)
        cls.plans = {split: cls.plan(split) for split in ("calibration", "confirmation")}

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    @classmethod
    def plan(cls, split: str, **options) -> dict:
        return build_plan(pool_path=takes_module.DEFAULT_POOL, policy_path=DEFAULT_POLICY, split=split,
                          run_id="run-clone", cells=["clone"], corpora_root=cls.corpora, **options)

    def test_the_clone_cell_plans_same_and_cross_language_references(self) -> None:
        plan = self.plans["calibration"]
        self.assertEqual((plan["takeCount"], plan["expectedTakeCount"]), (800, 800))
        self.assertEqual(set(plan["references"]["sources"]), set(CLONE_SOURCES))
        references = {}
        for language in LANGUAGE_ORDER:
            rows = [take for take in plan["takes"] if take["language"] == language]
            primary = [take for take in rows if take["role"] == "primary"]
            secondary = [take for take in rows if take["role"] == "secondary"]
            self.assertEqual((len(primary), len(secondary)), (60, 20), language)
            self.assertEqual(len({take["scriptID"] for take in primary}), 60)
            # Same-language references where a corpus covers the language; Japanese and Russian cross.
            same = {take["voice"]["language"] == language for take in primary}
            self.assertEqual(same, {language not in ("japanese", "russian")}, language)
            self.assertFalse(any(take["voice"]["language"] == language for take in secondary), language)
            self.assertTrue(all(take["mode"] == "clone" and take["voiceLanguage"] == take["voice"]["language"]
                                for take in rows))
            counts = collections.Counter(take["batchID"] for take in rows)
            self.assertEqual((len(counts), set(counts.values())), (16, {5}), language)
            references[language] = [take["voice"] for take in primary]
        chinese = {voice["gender"] for voice in references["chinese"]}
        self.assertEqual(chinese, {"female", "male"})
        self.assertEqual({voice["source"] for voice in references["italian"]}, {"mls", "emozionalmente"})
        speakers = [(batch["voice"]["source"], batch["voice"]["language"], batch["voice"]["speaker"])
                    for batch in plan["batches"]]
        self.assertEqual(len(speakers), len(set(speakers)), "a speaker serves one reference per split")
        for batch in plan["batches"]:
            reference = batch["reference"]
            self.assertEqual(reference["referenceKey"], batch["voice"]["referenceKey"])
            # The preferred >= 10 s clip wins; a too-short, untranscribed or flag-like clip never does.
            self.assertEqual(reference["durationSeconds"], 12.0)
            self.assertFalse(reference["transcript"].startswith("-"))
            if batch["voice"]["source"] == "emozionalmente":
                self.assertEqual(int(batch["voice"]["speaker"][2:]) % 2, 0, "only neutral clips")
        self.assertEqual(plan, self.plan("calibration"), "the rule is deterministic")

    def test_the_splits_share_no_reference_speaker_and_a_subset_plans_the_same_references(self) -> None:
        calibration, confirmation = self.plans["calibration"], self.plans["confirmation"]
        self.assertFalse(speakers_of(calibration) & speakers_of(confirmation))
        corpus = {split: {(b["voice"]["source"], b["voice"]["language"], b["voice"]["speaker"])
                          for b in plan["batches"]} for split, plan in self.plans.items()}
        self.assertFalse(corpus["calibration"] & corpus["confirmation"])
        subset = self.plan("calibration", languages=["japanese"])
        self.assertEqual(subset["batches"], [batch for batch in calibration["batches"]
                                             if batch["language"] == "japanese"])
        # A reader of two of a corpus's languages is one speaker, in one split.
        policy = load_policy(DEFAULT_POLICY)
        splits = set()
        for split in ("calibration", "confirmation"):
            candidates, _ = takes_module.reference_candidates(policy, split, corpora_root=self.corpora)
            found = {item["language"] for items in candidates.values() for item in items
                     if (item["source"], item["speaker"]) == ("mls", "polyglot")}
            if found:
                self.assertEqual(found, {"french", "german"})
                splits.add(split)
        self.assertEqual(len(splits), 1)

    def test_missing_or_changed_corpora_are_refused(self) -> None:
        with self.assertRaisesRegex(TakeError, "not extracted"):
            build_plan(pool_path=takes_module.DEFAULT_POOL, policy_path=DEFAULT_POLICY, split="calibration",
                       run_id="run-clone", cells=["clone"], corpora_root=self.base / "empty")
        import audio_qc_corpora as corpora

        stale = self.base / "stale"
        shutil.copytree(self.corpora, stale)
        path = corpora.source_directory(corpora.load_registry(), "libritts-r", stale) / "extracted" / "manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["clips"][0]["text"] = "Edited after extraction."
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(TakeError, "libritts-r extraction is unusable"):
            build_plan(pool_path=takes_module.DEFAULT_POOL, policy_path=DEFAULT_POLICY, split="calibration",
                       run_id="run-clone", cells=["clone"], corpora_root=stale)

    def test_batch_files_copy_each_reference_and_the_manifest_records_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / "run"
            plan = self.plan("calibration", languages=["english", "japanese"])
            plan_path = Path(temporary) / "plan.json"
            plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
            rows = write_batch_files(plan, run / "batches", corpora_root=self.corpora)
            for row, batch in zip(rows, plan["batches"]):
                copy_path = Path(row["reference"])
                self.assertEqual(copy_path, (run / "references" / f"{batch['reference']['referenceKey']}.wav").resolve())
                self.assertEqual(hashlib.sha256(copy_path.read_bytes()).hexdigest(), batch["reference"]["wavSHA256"])
                fields = takes_module.batch_row_line(row).split("\x1f")
                self.assertEqual(fields[9:], [row["reference"], batch["reference"]["transcript"], ""])
            emit_outputs(plan, run / "batch-results", run / "batch-out")
            manifest = build_manifest(plan_path=plan_path, batch_results=run / "batch-results",
                                      wav_root=run / "batch-out", output=run / "takes-manifest.json")
            self.assertEqual(manifest["cells"], {"clone": manifest["counts"]})
            take = manifest["takes"][0]
            voice = take["voice"]
            self.assertEqual(take["reference"]["wavPath"], f"references/{voice['referenceKey']}.wav")
            self.assertEqual((take["reference"]["corpus"], take["reference"]["speaker"]),
                             (voice["source"], voice["speaker"]))
            self.assertNotIn(str(Path(temporary)), json.dumps(manifest), "no absolute local path")
            self.assertNotIn("Reference sentence", json.dumps(manifest), "no reference transcript")
            report = validate_manifest(manifest, plan, manifest_dir=run)
            self.assertEqual(report["status"], "PASS", report)
            # The orchestrator hands the declared reference to the speaker judges.
            import audio_qc_orchestrator as orchestrator

            lane = orchestrator.manifest_from_calibration_takes(manifest, source_sha256="c" * 64, base_dir=run)
            first = lane["takes"][0]
            self.assertEqual(first["referenceAudioSHA256"], take["reference"]["wavSHA256"])
            self.assertEqual(Path(first["referenceAudioPath"]), (run / take["reference"]["wavPath"]).resolve())
            (run / take["reference"]["wavPath"]).write_bytes(b"RIFF other speaker")
            report = validate_manifest(manifest, plan, manifest_dir=run)
            self.assertTrue(any("reference copy" in error for error in report["errors"]), report)
            with self.assertRaisesRegex(TakeError, "reference copy is missing or changed"):
                build_manifest(plan_path=plan_path, batch_results=run / "batch-results", wav_root=run / "batch-out",
                               output=run / "takes-manifest.json", copy=True)
            # A corpus clip whose bytes changed after planning is never copied.
            (run / "references").rename(run / "references-old")
            clip = self.corpora / PurePosixPath(plan["batches"][0]["reference"]["corpusPath"])
            original = clip.read_bytes()
            try:
                clip.write_bytes(b"RIFF changed")
                with self.assertRaisesRegex(TakeError, "bytes changed"):
                    write_batch_files(plan, run / "batches", corpora_root=self.corpora)
            finally:
                clip.write_bytes(original)


LANGUAGE_ORDER = ("english", "french", "german", "spanish", "italian", "portuguese", "russian", "chinese",
                  "japanese", "korean")


# --------------------------------------------------------------------------- #
# Long-form projects: the `vocello batch --long-form` output
# --------------------------------------------------------------------------- #

class LongFormManifestTests(Fixture):
    def setUp(self) -> None:
        super().setUp()
        pool = pool_fixture(calibration=60, confirmation=0, languages={"english": LANGUAGES["english"]})
        self.plan_value = build_plan(pool_path=self.write("pool.json", pool), policy_path=self.policy_path,
                                     split="calibration", run_id="run-lf", languages=["english"], cells=["long-form"])
        self.plan_path = self.write("plan.json", self.plan_value)
        self.run_dir = self.root / "run"
        self.results = self.run_dir / "batch-results"
        self.wav_root = self.run_dir / "batch-out"
        self.results.mkdir(parents=True)
        self.takes = {take["takeID"]: take for take in self.plan_value["takes"]}

    def _project(self, batch: dict, index: int, take_id: str, out_dir: Path, *, digest: str | None = None) -> dict:
        """One completed project: two streaming segment takes and the assembler's evidence of the joined WAV."""
        joined = out_dir / f"stamp_{batch['mode']}_{index:03d}.wav"
        joined.write_bytes(b"RIFF joined " + take_id.encode("utf-8"))
        segments = []
        for position in range(2):
            path = out_dir / f"stamp_{batch['mode']}_{index:03d}_segment_{position:03d}.wav"
            path.write_bytes(b"RIFF segment " + f"{take_id}/{position}".encode("utf-8"))
            segments.append({"index": position, "segmentID": f"lfseg_{position}", "boundary": "sentence" if position
                             == 0 else "end_of_text", "intendedPauseMilliseconds": 300 if position == 0 else 0,
                             "effectiveSeed": 11 + position, "generationID": f"0A1B2C3D-0000-4000-8000-00000000000{position}",
                             "audioPath": str(path), "durationSeconds": 30.0, "finishReason": "eos"})
        assembly = {"schemaVersion": 1, "algorithmVersion": 2, "sampleRate": 24_000, "blockFrames": 4096,
                    "segmentCount": 2, "outputFrameCount": 1_447_200, "workingSetFrameUpperBound": 12_288,
                    "outputDigest": digest or hashlib.sha256(joined.read_bytes()).hexdigest(), "outputReadable": True,
                    "maximumSegmentBoundaryJump": 212,
                    "segments": [{"segmentID": "lfseg_0", "contentOutputRange": {"lowerBound": 0, "upperBound": 720_000},
                                  "insertedPauseOutputRange": {"lowerBound": 720_000, "upperBound": 727_200}},
                                 {"segmentID": "lfseg_1",
                                  "contentOutputRange": {"lowerBound": 727_200, "upperBound": 1_447_200},
                                  "insertedPauseOutputRange": {"lowerBound": 1_447_200, "upperBound": 1_447_200}}]}
        return {"index": index, "text": self.takes[take_id]["text"], "audioPath": str(joined),
                "durationSeconds": 60.3, "finishReason": "eos", "longFormPlanDigest": "d" * 64,
                "longFormSegments": segments, "longFormAssembly": assembly}

    def _emit(self, batch: dict, *, failed_at: int | None = None, digest: str | None = None,
              long_form: bool = True) -> None:
        out_dir = self.wav_root / batch["batchID"]
        out_dir.mkdir(parents=True, exist_ok=True)
        items = []
        for index, take_id in enumerate(batch["takeIDs"]):
            if failed_at is None or index < failed_at:
                items.append(self._project(batch, index, take_id, out_dir, digest=digest))
        if failed_at is None:
            payload = {"count": len(items), "items": items, "mode": batch["mode"], "modelID": "pro_custom_speed",
                       "variant": "speed", "wallSeconds": 30.0}
        else:
            rows = [{**{key: item[key] for key in item if key != "text"}, "status": "completed",
                     "generationID": "0A1B2C3D-0000-4000-8000-000000000001"} for item in items]
            rows.append({"index": failed_at, "generationID": "0A1B2C3D-0000-4000-8000-00000000CCCC",
                         "status": "failed", "errorCode": "generation_failed"})
            rows += [{"index": index, "status": "not_attempted"}
                     for index in range(failed_at + 1, len(batch["takeIDs"]))]
            payload = {"schemaVersion": 2, "completedCount": failed_at, "items": rows, "mode": batch["mode"],
                       "modelID": "pro_custom_speed", "plannedCount": len(batch["takeIDs"]), "variant": "speed",
                       "wallSeconds": 30.0}
        if long_form:
            payload["longForm"] = True
        (self.results / f"{batch['batchID']}.json").write_text(json.dumps(payload, sort_keys=True) + "\n",
                                                                encoding="utf-8")

    def _manifest(self, diagnostics: Path | None = None) -> dict:
        return build_manifest(plan_path=self.plan_path, batch_results=self.results, wav_root=self.wav_root,
                              output=self.run_dir / "takes-manifest.json", diagnostics=diagnostics)

    def test_a_long_form_take_carries_its_seams_and_its_segment_takes(self) -> None:
        self.assertEqual(self.plan_value["takeCount"], 8)
        for batch in self.plan_value["batches"]:
            self._emit(batch)
        first = self.plan_value["takes"][0]
        segment_digest = hashlib.sha256(b"RIFF segment " + f"{first['takeID']}/1".encode("utf-8")).hexdigest()
        engine = self.root / "diagnostics" / "engine"
        engine.mkdir(parents=True)
        (engine / "generations.jsonl").write_text(json.dumps({
            "generationID": "0A1B2C3D-0000-4000-8000-000000000001", "notes": {"samplingWAVDigest": segment_digest},
            "engineIntrospection": ManifestTests._summary(375)}) + "\n", encoding="utf-8")
        manifest = self._manifest(self.root / "diagnostics")
        take = manifest["takes"][0]
        self.assertEqual(take["longForm"], {"schemaVersion": 1, "algorithmVersion": 2, "sampleRate": 24_000,
                                            "segmentCount": 2, "outputFrameCount": 1_447_200,
                                            "maximumSegmentBoundaryJump": 212, "seamFrames": [727_200]})
        self.assertEqual([segment["boundary"] for segment in take["longFormSegments"]], ["sentence", "end_of_text"])
        self.assertIsNone(take["engineIntrospection"])
        self.assertIsNone(take["longFormSegments"][0]["engineIntrospection"])
        self.assertEqual(take["longFormSegments"][1]["engineIntrospection"]["wavSHA256"], segment_digest)
        self.assertEqual(manifest["introspection"], {"bound": 0, "unbound": 0,
                                                     "longFormSegments": {"bound": 1, "unbound": 15}})
        self.assertEqual(manifest["cells"], {"long-form": {"planned": 8, "generated": 8, "rejected": 0,
                                                           "failed": 0, "missing": 0}})
        self.assertNotIn(str(self.root), json.dumps(manifest))
        report = validate_manifest(manifest, self.plan_value, manifest_dir=self.run_dir)
        self.assertEqual(report["status"], "PASS", report)
        edited = copy.deepcopy(manifest)
        edited["takes"][0]["longForm"] = None
        edited["manifestDigest"] = takes_module.self_digest(edited, "manifestDigest")
        self.assertTrue(any("longForm block" in error for error in validate_manifest(
            edited, self.plan_value, manifest_dir=self.run_dir)["errors"]))
        edited = copy.deepcopy(manifest)
        edited["takes"][0]["longFormSegments"][0]["boundary"] = "chapter"
        edited["manifestDigest"] = takes_module.self_digest(edited, "manifestDigest")
        self.assertTrue(any("segment 0 is malformed" in error for error in validate_manifest(
            edited, self.plan_value, manifest_dir=self.run_dir)["errors"]))

    def test_evidence_of_another_wav_or_a_single_take_output_is_refused(self) -> None:
        batch, *rest = self.plan_value["batches"]
        for other in rest:
            self._emit(other)
        self._emit(batch, digest="0" * 64)
        with self.assertRaisesRegex(TakeError, "describes another WAV"):
            self._manifest()
        self._emit(batch, long_form=False)
        with self.assertRaisesRegex(TakeError, "not a long-form batch"):
            self._manifest()

    def test_a_stopped_long_form_batch_keeps_its_completed_projects(self) -> None:
        batch = max(self.plan_value["batches"], key=lambda value: len(value["takeIDs"]))
        self.assertGreaterEqual(len(batch["takeIDs"]), 3)
        for other in self.plan_value["batches"]:
            self._emit(other, failed_at=1 if other is batch else None)
        diagnostics = ManifestTests._diagnostics(self, {"0A1B2C3D-0000-4000-8000-00000000CCCC":
                                                        ("audio.quality_rejected", "dropout:1800ms")})
        manifest = self._manifest(diagnostics)
        by_id = {take["takeID"]: take for take in manifest["takes"]}
        head, refused, *later = batch["takeIDs"]
        self.assertEqual((by_id[head]["status"], by_id[head]["textBinding"]), ("generated", "index"))
        self.assertEqual(by_id[head]["longForm"]["seamFrames"], [727_200])
        self.assertEqual(by_id[refused]["status"], "rejected")
        self.assertEqual({by_id[take_id]["missingReason"] for take_id in later}, {"batch-not_attempted"})
        report = validate_manifest(manifest, self.plan_value, manifest_dir=self.run_dir)
        self.assertEqual(report["status"], "PASS", report)


# --------------------------------------------------------------------------- #
# Collecting the engine's diagnostics rows into the run
# --------------------------------------------------------------------------- #

class CollectDiagnosticsTests(Fixture):
    def _row(self, generation_id: str, digest: str, frames: int) -> dict:
        return {"generationID": generation_id, "text": "Private script text.", "outputPath": "/private/take.wav",
                "notes": {"samplingWAVDigest": digest, "audioQCFlags": "clicks:3", "message": "a raw error message"},
                "engineIntrospection": ManifestTests._summary(frames)}

    def test_each_run_keeps_its_own_reduced_rows_past_the_engine_trim(self) -> None:
        source, run = self.root / "engine-root", self.root / "run" / "diagnostics"
        engine = source / "engine"
        engine.mkdir(parents=True)
        log, failures = engine / "generations.jsonl", engine / "generation-failures.jsonl"
        old = "0A1B2C3D-0000-4000-8000-000000000001"
        log.write_text(json.dumps(self._row(old, "a" * 64, 10)) + "\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(takes_module.main(["collect-diagnostics", "--diagnostics", str(source), "--into", str(run),
                                                "--baseline"]), 0)
        self.assertEqual(json.loads(out.getvalue())["baseline"], 1)
        self.assertEqual((run / "engine" / "generations.jsonl").read_text(encoding="utf-8"), "")
        new, failed = "0A1B2C3D-0000-4000-8000-000000000002", "0a1b2c3d-0000-4000-8000-000000000003"
        with log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self._row(new, "b" * 64, 20)) + "\n")
            handle.write(json.dumps(self._row(failed, "c" * 64, 30))[:40])  # still being written
        failures.write_text(json.dumps({"generationID": failed, "errorCode": "audio.quality_rejected",
                                        "message": "a raw error message", "stage": "stream_failed"}) + "\n",
                            encoding="utf-8")
        counts = takes_module.collect_diagnostics(source, run)
        self.assertEqual((counts["rows"], counts["failures"], counts["taken"]), (1, 1, 2))
        copied = (run / "engine" / "generations.jsonl").read_text(encoding="utf-8")
        for private in ("Private script text", "/private/take.wav", "raw error message"):
            self.assertNotIn(private, copied + (run / "engine" / "generation-failures.jsonl").read_text(encoding="utf-8"))
        self.assertEqual(set(json.loads(copied)), {"generationID", "notes", "engineIntrospection"})
        # The engine front-trims its log; the run keeps what it took, and takes the finished line once.
        log.write_text(json.dumps(self._row(failed, "c" * 64, 30)) + "\n", encoding="utf-8")
        self.assertEqual(takes_module.collect_diagnostics(source, run)["rows"], 1)
        self.assertEqual(takes_module.collect_diagnostics(source, run)["taken"], 0)
        # The manifest binds against the run's rows exactly as against the engine's own root.
        self.assertEqual(set(takes_module.engine_introspections(run, {"a" * 64, "b" * 64, "c" * 64})),
                         {"b" * 64, "c" * 64})
        self.assertEqual(takes_module.engine_failures(run, {failed.upper()}),
                         {failed.upper(): {"errorCode": "audio.quality_rejected", "audioQCFlags": ["clicks:3"]}})


if __name__ == "__main__":
    unittest.main()
