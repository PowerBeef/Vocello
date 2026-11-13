#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import random
import struct
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/quality_screen.py"
SPEC = importlib.util.spec_from_file_location("quality_screen", SCRIPT)
assert SPEC and SPEC.loader
screen = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = screen
SPEC.loader.exec_module(screen)

QWEN, WHISPER = screen.ASR_MODELS


def clone_screen() -> dict:
    return screen.load_screen("clone")


def clip(clip_id: str, speaker: str, seconds: float, *, language: str = "english", text: str = "some words",
         clipped: int = 0) -> dict:
    return {"clipID": clip_id, "speaker": speaker, "durationSeconds": seconds, "language": language, "text": text,
            "clippedSamples": clipped, "wavPath": f"wav/{clip_id}.wav", "wavSHA256": "0" * 64, "sampleRate": 24_000}


def row(take_id: str, *, outcome: str = "generated", digest: str = "p", silence: int = 40, flags=()) -> dict:
    if outcome != "generated":
        return {"takeID": take_id, "outcome": outcome, "reason": "qc_rejected"}
    return {"takeID": take_id, "outcome": outcome, "pcmSHA256": digest, "durationSeconds": 4.0,
            "fastQC": {"trailingSilenceMS": silence, "flags": list(flags)}}


def score(similarity: float, qwen: float, whisper: float) -> dict:
    return {"speakerSimilarity": similarity, "errorRate": {QWEN: qwen, WHISPER: whisper}}


def plan_of(voices: int, per_voice: int) -> dict:
    takes = [{"takeID": f"v{voice}--s{index}", "voice": f"v{voice}"} for voice in range(voices) for index in range(per_voice)]
    return {"screen": "clone", "planSHA256": "x", "takes": takes}


def view(plan: dict, rows: dict, scores: dict) -> dict:
    return {"arm": {"environment": {}, "executableSHA256": "e", "commit": "c"},
            "rows": {take["takeID"]: rows.get(take["takeID"], row(take["takeID"])) for take in plan["takes"]},
            "scores": scores}


class ConfigTests(unittest.TestCase):
    def test_every_committed_screen_is_complete_and_a_rule_carries_its_date(self):
        names = list(screen.read_json(screen.CONFIG)["screens"])
        self.assertIn("clone", names)
        for screen_name in names:
            definition = screen.load_screen(screen_name)
            self.assertIn(definition["kind"], ("clone", "long-form"))
            if definition["kind"] == "long-form":
                self.assertGreaterEqual(definition["sentencesPerProject"], 2)
                for stratum in definition["strata"].values():
                    self.assertTrue(stratum.get("speakers") if stratum["mode"] == "custom" else stratum.get("voiceBriefs"))
                continue
            self.assertEqual(len(definition["referenceSeconds"]), 3)
            self.assertIn("default", definition["crossLanguage"])
            self.assertGreaterEqual(definition.get("sentencesPerTake", 1), 1)
            if definition.get("population"):
                self.assertIn(definition["population"], names, f"{screen_name}: its population is a screen")
            for name, rule in definition["rules"].items():
                self.assertTrue(rule.get("recorded"), f"{name}: a rule is recorded before its takes exist")
                self.assertIn("maximumExtraGrossFailures", rule)
                for metric, guard in rule["guards"].items():
                    self.assertIn(metric, screen.METRICS)
                    self.assertGreaterEqual(guard["margin"], 0)
        with self.assertRaises(screen.ScreenError):
            screen.load_screen("no-such-screen")


class PlanTests(unittest.TestCase):
    def test_a_seed_is_stable_and_belongs_to_one_take_and_seed_set(self):
        definition = clone_screen()
        first = screen.take_seed(definition, 1, "voice--script")
        self.assertEqual(first, screen.take_seed(definition, 1, "voice--script"))
        self.assertNotEqual(first, screen.take_seed(definition, 2, "voice--script"))
        self.assertNotEqual(first, screen.take_seed(definition, 1, "voice--other"))
        self.assertTrue(0 <= first < 1 << 63)

    def test_references_are_one_per_speaker_and_prefer_the_preferred_length(self):
        definition = dict(clone_screen(), referencesPerLanguage=2, languages={"english": ["corpus"]})
        clips = [
            clip("a-short", "a", 6.0), clip("a-long", "a", 12.0), clip("b-short", "b", 7.0),
            clip("c-long", "c", 15.0), clip("d-clipped", "d", 12.0, clipped=3), clip("e-empty", "e", 12.0, text=" "),
            clip("f-too-long", "f", 25.0), clip("g-other", "g", 12.0, language="french"),
        ]
        chosen = screen.select_references(definition, "english", {"corpus": (Path("/corpus"), clips)})
        self.assertEqual(sorted(item["clipID"] for item in chosen), ["a-long", "c-long"])
        self.assertEqual(len({item["speaker"] for item in chosen}), 2)
        # A short clip fills in only when no longer one is left.
        definition["referencesPerLanguage"] = 3
        chosen = screen.select_references(definition, "english", {"corpus": (Path("/corpus"), clips)})
        self.assertEqual(sorted(item["clipID"] for item in chosen), ["a-long", "b-short", "c-long"])
        definition["referencesPerLanguage"] = 4
        with self.assertRaises(screen.ScreenError):
            screen.select_references(definition, "english", {"corpus": (Path("/corpus"), clips)})

    def test_two_plans_that_differ_only_in_seeds_are_the_same_takes(self):
        base = {"screen": "clone", "screenVersion": 1, "voices": [{"voice": "v"}],
                "takes": [{"takeID": "t", "voice": "v", "text": "words", "seed": 1}]}
        reseeded = json.loads(json.dumps(base))
        reseeded["takes"][0]["seed"] = 2
        self.assertTrue(screen.same_takes_other_seeds(base, reseeded))
        reseeded["takes"][0]["text"] = "other words"
        self.assertFalse(screen.same_takes_other_seeds(base, reseeded))

    def test_long_takes_join_sentences_in_hash_order_with_the_language_s_separator(self):
        pool = [{"id": f"{language}-{index}", "language": language, "split": "calibration", "text": f"{language} {index}."}
                for language in ("english", "chinese") for index in range(6)]
        single = {"name": "x", "scriptSplit": "calibration"}
        joined = dict(single, sentencesPerTake=3)
        order = screen.select_scripts(single, pool, "english", "ref", 6)
        scripts = screen.select_scripts(joined, pool, "english", "ref", 2)
        self.assertEqual([script["id"] for script in scripts],
                         ["+".join(entry["id"] for entry in order[:3]), "+".join(entry["id"] for entry in order[3:])])
        self.assertEqual(scripts[0]["text"], " ".join(entry["text"] for entry in order[:3]))
        chinese_order = screen.select_scripts(single, pool, "chinese", "ref", 2)
        chinese = screen.select_scripts(dict(joined, sentencesPerTake=2), pool, "chinese", "ref", 1)[0]
        self.assertEqual(chinese["text"], "".join(entry["text"] for entry in chinese_order),
                         "an unspaced script joins with no separator")
        self.assertEqual(screen.select_scripts(single, pool, "english", "ref", 2), order[:2], "one sentence stays as it was")
        with self.assertRaises(screen.ScreenError):
            screen.select_scripts(joined, pool, "english", "ref", 3)

    def test_an_arm_may_run_the_same_takes_on_another_variant_and_says_so(self):
        plan = {"variant": "speed", "planSHA256": "abc", "takes": [{"takeID": "t"}]}
        self.assertEqual(screen.plan_for_variant(plan, None), (plan, None))
        self.assertEqual(screen.plan_for_variant(plan, "speed"), (plan, None))
        other, recorded = screen.plan_for_variant(plan, "quality")
        self.assertEqual((other["variant"], recorded, other["planSHA256"], other["takes"]),
                         ("quality", "quality", "abc", plan["takes"]))
        self.assertEqual(plan["variant"], "speed", "the plan itself is not changed")

    def test_only_registered_environment_families_reach_an_arm(self):
        self.assertEqual(screen.parse_overrides(["QWENVOICE_X=on", "MLX_Y=2"]), {"QWENVOICE_X": "on", "MLX_Y": "2"})
        for bad in ("PATH=/tmp", "QWENVOICE_X", "=on"):
            with self.assertRaises(screen.ScreenError):
                screen.parse_overrides([bad])


class LongFormTests(unittest.TestCase):
    SCREEN = {"name": "lf", "version": 1, "kind": "long-form", "variant": "speed", "scriptSplit": "calibration",
              "sentencesPerProject": 3, "projectsPerStratum": 2, "variations": ["expressive"],
              "strata": {"custom-english": {"mode": "custom", "language": "english", "speakers": ["aiden", "ryan"]},
                         "design-english": {"mode": "design", "language": "english", "voiceBriefs": ["A calm voice."]}}}

    def test_a_project_is_one_take_of_its_script_and_one_cluster(self):
        plan = screen.build_long_form_plan(self.SCREEN, 1)
        self.assertEqual(len(plan["takes"]), 4)
        first = plan["takes"][0]
        self.assertEqual((first["takeID"], first["variation"]), ("custom-english-01--expressive", "expressive"))
        self.assertEqual(first["voice"], "custom-english-01", "the interval resamples projects")
        self.assertEqual(first["text"].count(" "), sum(entry["text"].count(" ") for entry in screen.read_json(
            screen.SCRIPT_POOL)["entries"] if entry["id"] in first["scriptID"].split("+")) + 2,
                         "three sentences joined by two spaces")
        self.assertEqual(len(first["scriptID"].split("+")), 3)
        self.assertEqual([take["speaker"] for take in plan["takes"][:2]], ["aiden", "ryan"])
        design = [take for take in plan["takes"] if take["mode"] == "design"]
        self.assertTrue(all(take["voiceBrief"] == "A calm voice." and "speaker" not in take for take in design))
        self.assertEqual(plan["kind"], "long-form")
        reseeded = screen.build_long_form_plan(self.SCREEN, 2)
        self.assertTrue(screen.same_takes_other_seeds(plan, reseeded))
        expressive = screen.build_long_form_plan(self.SCREEN, 1, variations=["expressive"])
        self.assertEqual(expressive["planSHA256"], plan["planSHA256"], "the same takes, the same seeds")
        with self.assertRaises(screen.ScreenError):
            screen.build_long_form_plan(self.SCREEN, 1, variations=["consistent"])
        with self.assertRaises(screen.ScreenError):
            screen.build_long_form_plan(self.SCREEN, 1, ["no-such-stratum"])

    def test_a_screen_naming_a_retired_variation_is_refused(self):
        # RF-58: the CLI samples every take as Expressive, so a Consistent take
        # would carry a label it was not generated under.
        for variations in (["expressive", "consistent"], ["balanced"]):
            with self.assertRaises(screen.ScreenError):
                screen.build_long_form_plan(dict(self.SCREEN, variations=variations), 1)
        configured = screen.read_json(screen.ROOT / "config/quality-screens.json")["screens"]["long-form"]
        self.assertEqual((configured["version"], configured["variations"]), (2, ["expressive"]))

    def test_a_project_is_asked_for_as_the_apps_route_long_text(self):
        plan = screen.build_long_form_plan(self.SCREEN, 1)
        custom = screen.long_form_command(Path("/v"), plan, plan["takes"][0], Path("/o.wav"), ["--json"])
        self.assertEqual(custom[custom.index("--long-form") + 1], "always")
        self.assertEqual(custom[custom.index("--speaker") + 1], "aiden")
        self.assertEqual(custom[custom.index("--variation") + 1], "expressive")
        self.assertEqual(custom[custom.index("--language") + 1], "english")
        design = screen.long_form_command(Path("/v"), plan, plan["takes"][-1], Path("/o.wav"), [])
        self.assertIn("--voice-brief", design)
        self.assertNotIn("--speaker", design)

    def test_a_screen_may_ask_for_single_takes_and_earlier_plans_keep_their_digests(self):
        plan = screen.build_long_form_plan(self.SCREEN, 1)
        self.assertNotIn("longForm", plan, "a screen that sets nothing plans as before")
        single = screen.build_long_form_plan(dict(self.SCREEN, longForm="never"), 1)
        self.assertEqual(single["longForm"], "never")
        self.assertNotEqual(single["planSHA256"], plan["planSHA256"])
        self.assertEqual([take["text"] for take in single["takes"]], [take["text"] for take in plan["takes"]])
        command = screen.long_form_command(Path("/v"), single, single["takes"][0], Path("/o.wav"), [])
        self.assertEqual(command[command.index("--long-form") + 1], "never")
        with self.assertRaises(screen.ScreenError):
            screen.build_long_form_plan(dict(self.SCREEN, longForm="auto"), 1)
        configured = screen.read_json(screen.ROOT / "config/quality-screens.json")["screens"]["single"]
        self.assertEqual((configured["kind"], configured["longForm"], configured["variations"]),
                         ("long-form", "never", ["expressive"]))

    def test_segments_report_how_they_ended_and_a_runaway_is_a_gross_failure(self):
        summary = screen.segment_summary({"longFormSegments": [
            {"finishReason": "end_of_sequence", "qcWarnings": [], "durationSeconds": 5.0},
            {"finishReason": "maximum_tokens", "qcWarnings": ["dropout:900ms"], "durationSeconds": 9.0}]})
        self.assertEqual(summary, {"count": 2, "finishReasons": {"end_of_sequence": 1, "maximum_tokens": 1},
                                   "warned": 1, "warnings": ["dropout:900ms"], "longestSeconds": 9.0})
        plan = plan_of(voices=2, per_voice=1)
        scores = {take["takeID"]: score(0.7, 0.02, 0.01) for take in plan["takes"]}
        runaway = dict(row("v0--s0"), segments=summary)
        result = screen.summarize(plan, view(plan, {}, scores), view(plan, {"v0--s0": runaway}, scores))
        self.assertEqual(result["grossFailures"], {"a": 0, "b": 1})
        self.assertEqual(screen.take_metrics(runaway, None)["segmentsWarned"], 1)

    def test_without_a_reference_the_speaker_score_is_the_spread_of_the_take_s_windows(self):
        windows = [{"embedding": [1.0, 0.0]}, {"embedding": [1.0, 1.0]}, {"embedding": [1.0, 0.1]}]
        spread = screen.window_spread({"whole": [1.0, 0.0], "windows": windows})
        self.assertAlmostEqual(spread, 1 - 2 ** -0.5)
        self.assertIsNone(screen.window_spread({"whole": [1.0, 0.0], "windows": windows[:1]}))
        metrics = screen.take_metrics(row("t"), {"errorRate": {QWEN: 0.1, WHISPER: 0.2}, "speakerWindowSpread": spread})
        self.assertAlmostEqual(metrics["speakerWindowSpread"], spread)
        self.assertNotIn("speakerSimilarity", metrics)


class ChannelLayoutTests(unittest.TestCase):
    def test_a_layout_copies_samples_and_never_recomputes_them(self):
        mono = struct.pack("<4h", 1, -2, 32767, -32768)
        self.assertEqual(screen.stereo_frames(mono, "duplicate"),
                         struct.pack("<8h", 1, 1, -2, -2, 32767, 32767, -32768, -32768))
        self.assertEqual(screen.stereo_frames(mono, "left-only"),
                         struct.pack("<8h", 1, 0, -2, 0, 32767, 0, -32768, 0))
        with self.assertRaises(screen.ScreenError):
            screen.stereo_frames(mono, "right-only")
        with self.assertRaises(screen.ScreenError):
            screen.stereo_frames(b"\x01", "duplicate")

    def test_layouts_alternate_so_each_language_has_both(self):
        definition = {"referenceChannels": "alternate-duplicate-left-only"}
        self.assertEqual([screen.layout_for(definition, index) for index in range(1, 5)],
                         ["duplicate", "left-only", "duplicate", "left-only"])
        self.assertIsNone(screen.layout_for({}, 1))

    def test_a_variant_draws_its_populations_references(self):
        self.assertEqual(screen.population({"name": "clone-stereo", "population": "clone"}), "clone")
        self.assertEqual(screen.population({"name": "clone"}), "clone")


class OutcomeTests(unittest.TestCase):
    def test_every_answer_is_an_outcome(self):
        self.assertEqual(screen.outcome_of(0, {"ok": True}), ("generated", None))
        self.assertEqual(
            screen.outcome_of(1, {"ok": False, "error": {"code": "qc_rejected", "detail": {"reason": "audio.quality_rejected.no_speech"}}}),
            ("refused", "audio.quality_rejected.no_speech"))
        self.assertEqual(screen.outcome_of(1, {"error": {"code": "generation_failed"}}), ("failed", "generation_failed"))
        # A process that died without a document still counts against its arm.
        self.assertEqual(screen.outcome_of(139, {}), ("failed", "exit 139"))


class EvidenceTests(unittest.TestCase):
    def test_an_arm_is_believed_from_the_engines_rows_not_from_its_environment(self):
        # The CLI reports identifiers in lowercase and the engine's rows in uppercase.
        rows = [{"takeID": "t1", "generationID": "g1"}, {"takeID": "t2", "generationID": "G2"}, {"takeID": "t3"}]
        records = [
            {"generationID": "G1", "requestReceipt": {"normalizedReferenceAudioDigest": "aa"},
             "summary": {"runEnvironment": {"runtimeDebugProvenance": {"activeOverrideKeys": ["QWENVOICE_X"]}}}},
            {"generationID": "G2", "requestReceipt": {"normalizedReferenceAudioDigest": "bb"}, "summary": {}},
            {"generationID": "another-run", "summary": {"runEnvironment": {"runtimeDebugProvenance": {
                "activeOverrideKeys": ["QWENVOICE_OTHER"]}}}},
        ]
        with tempfile.TemporaryDirectory() as temp:
            telemetry = Path(temp) / "generations.jsonl"
            telemetry.write_text("\n".join(json.dumps(record) for record in records) + "\nnot json\n", encoding="utf-8")
            evidence = screen.arm_evidence(telemetry, rows)
            self.assertEqual(evidence["activeOverrideKeys"], ["QWENVOICE_X"])
            self.assertEqual([row.get("referenceAudioDigest") for row in rows], ["aa", "bb", None])
            self.assertEqual(screen.arm_evidence(Path(temp) / "absent.jsonl", rows)["activeOverrideKeys"], [])

    def test_a_key_the_engine_never_read_makes_the_arm_unusable(self):
        overrides = {"QWENVOICE_X": "on", "QWENVOICE_TYPO": "on", "MLX_MAX_OPS_PER_BUFFER": "40"}
        self.assertEqual(screen.unread_overrides(overrides, ["QWENVOICE_X"]), ["QWENVOICE_TYPO"])
        self.assertEqual(screen.unread_overrides({}, []), [])

    def test_pairs_whose_reference_audio_differs_are_counted(self):
        plan = plan_of(voices=2, per_voice=2)
        a_rows = {take["takeID"]: dict(row(take["takeID"]), referenceAudioDigest="same") for take in plan["takes"]}
        b_rows = {take["takeID"]: dict(row(take["takeID"]), referenceAudioDigest="same") for take in plan["takes"]}
        b_rows["v0--s0"]["referenceAudioDigest"] = "other"
        b_rows["v0--s1"]["referenceAudioDigest"] = None
        summary = screen.summarize(plan, view(plan, a_rows, {}), view(plan, b_rows, {}))
        self.assertEqual(summary["referenceAudioDiffers"], 1)


class ErrorRateTests(unittest.TestCase):
    def test_substitutions_deletions_and_insertions_all_count(self):
        reference = "the ferry leaves at seven"
        self.assertEqual(screen.error_rate(reference, "The ferry leaves at seven.", "english"), 0.0)
        self.assertAlmostEqual(screen.error_rate(reference, "the fairy leaves at seven", "english"), 1 / 5)
        self.assertAlmostEqual(screen.error_rate(reference, "the ferry leaves seven", "english"), 1 / 5)
        self.assertAlmostEqual(screen.error_rate(reference, "the ferry leaves at seven sharp", "english"), 1 / 5)
        self.assertEqual(screen.error_rate(reference, "", "english"), 1.0)
        self.assertIsNone(screen.error_rate(" ... ", "anything", "english"))

    def test_unspaced_scripts_are_compared_by_character(self):
        self.assertEqual(screen.error_rate("火车七点出发。", "火车 七点出发", "chinese"), 0.0)
        self.assertAlmostEqual(screen.error_rate("火车七点出发", "火车八点出发", "chinese"), 1 / 6)
        self.assertEqual(screen.error_rate("기차는 일곱 시에", "기차는일곱시에", "korean"), 0.0)
        # Width and case variants are one character.
        self.assertEqual(screen.error_rate("ＡＢＣ １２３", "abc 123", "english"), 0.0)

    def test_late_and_worst_windows_are_scored_against_the_reference(self):
        windows = [{"start": float(start), "embedding": embedding} for start, embedding in
                   ((0, [1.0, 0.0]), (3, [0.0, 1.0]), (6, [1.0, 1.0]), (7, [1.0, 0.0]))]
        values = screen.window_similarities({"reference": [1.0, 0.0], "windows": windows})
        self.assertAlmostEqual(values["speakerSimilarityWorstWindow"], 0.0)
        self.assertAlmostEqual(values["speakerSimilarityLate"], (2 ** -0.5 + 1.0) / 2, msg="windows from 6 s on")
        short = screen.window_similarities({"reference": [1.0, 0.0], "windows": windows[:2]})
        self.assertNotIn("speakerSimilarityLate", short, "a take with no late window has no late value")
        self.assertEqual(screen.window_similarities({"reference": None, "windows": windows}), {})
        metrics = screen.take_metrics(row("t"), dict(score(0.7, 0.1, 0.2), **values))
        self.assertAlmostEqual(metrics["speakerSimilarityLate"], values["speakerSimilarityLate"])

    def test_cosine(self):
        self.assertAlmostEqual(screen.cosine([1.0, 0.0], [2.0, 0.0]), 1.0)
        self.assertAlmostEqual(screen.cosine([1.0, 0.0], [0.0, 3.0]), 0.0)
        self.assertEqual(screen.cosine([0.0, 0.0], [1.0, 1.0]), 0.0)


class CompareTests(unittest.TestCase):
    def test_a_refused_take_counts_against_its_arm_and_leaves_the_pairs(self):
        plan = plan_of(voices=4, per_voice=2)
        scores = {take["takeID"]: score(0.7, 0.02, 0.01) for take in plan["takes"]}
        a = view(plan, {}, scores)
        b = view(plan, {"v0--s0": row("v0--s0", outcome="refused"), "v1--s1": row("v1--s1", outcome="failed")},
                 {key: value for key, value in scores.items() if key not in ("v0--s0", "v1--s1")})
        summary = screen.summarize(plan, a, b)
        self.assertEqual(summary["planned"], 8)
        self.assertEqual(summary["outcomes"]["b"], {"generated": 6, "refused": 1, "failed": 1})
        self.assertEqual(summary["paired"], 6)
        self.assertEqual(summary["grossFailures"], {"a": 0, "b": 2})
        # The survivors look the same; only the failure count tells the arms apart.
        self.assertEqual(summary["metrics"]["speakerSimilarity"]["meanDifference"], 0.0)

    def test_a_take_too_short_to_embed_is_a_gross_failure_not_a_scoring_error(self):
        self.assertTrue(screen.is_measured_outcome({"error": "audio-too-short"}))
        self.assertFalse(screen.is_measured_outcome({"error": "model-missing"}))
        self.assertFalse(screen.is_measured_outcome({"outputs": {}}))
        plan = plan_of(voices=2, per_voice=2)
        scores = {take["takeID"]: score(0.7, 0.02, 0.01) for take in plan["takes"]}
        short = dict(scores, **{"v0--s0": {"speakerSimilarity": None, "tooShortToScore": True,
                                           "errorRate": {QWEN: 0.02, WHISPER: 0.01}}})
        summary = screen.summarize(plan, view(plan, {}, scores), view(plan, {}, short))
        self.assertEqual(summary["grossFailures"], {"a": 0, "b": 1})
        self.assertEqual(summary["metrics"]["speakerSimilarity"]["pairs"], 3, "no similarity is invented for it")

    def test_a_take_that_says_something_else_is_a_gross_failure(self):
        plan = plan_of(voices=2, per_voice=2)
        scores = {take["takeID"]: score(0.7, 0.02, 0.01) for take in plan["takes"]}
        wrong = dict(scores, **{"v0--s0": score(0.7, 0.9, 0.6)})
        one_family = dict(scores, **{"v0--s0": score(0.7, 0.9, 0.05)})
        self.assertEqual(screen.summarize(plan, view(plan, {}, scores), view(plan, {}, wrong))["grossFailures"], {"a": 0, "b": 1})
        # One recognizer mishearing a take is not the take's failure.
        self.assertEqual(screen.summarize(plan, view(plan, {}, scores), view(plan, {}, one_family))["grossFailures"], {"a": 0, "b": 0})

    def test_identity_is_counted_on_pcm_and_the_interval_resamples_references(self):
        plan = plan_of(voices=6, per_voice=3)
        a_scores = {take["takeID"]: score(0.70, 0.02, 0.02) for take in plan["takes"]}
        b_scores = {take["takeID"]: score(0.60, 0.02, 0.02) for take in plan["takes"]}
        b_rows = {take["takeID"]: row(take["takeID"], digest="q") for take in plan["takes"][:5]}
        summary = screen.summarize(plan, view(plan, {}, a_scores), view(plan, b_rows, b_scores))
        self.assertEqual(summary["identicalPCM"], 13)
        measured = summary["metrics"]["speakerSimilarity"]
        self.assertAlmostEqual(measured["meanDifference"], -0.10)
        self.assertAlmostEqual(measured["interval95"][0], -0.10)
        self.assertAlmostEqual(measured["interval95"][1], -0.10)
        low, high = screen.bootstrap_interval({"x": [0.0, 0.2], "y": [0.4], "z": [-0.2, 0.0]}, random.Random(1))
        self.assertLessEqual(low, high)
        self.assertTrue(-0.2 - 1e-9 <= low and high <= 0.4 + 1e-9)


class DurationTests(unittest.TestCase):
    def test_a_decoder_only_change_must_leave_every_length_alone(self):
        plan = plan_of(voices=3, per_voice=2)
        scores = {take["takeID"]: score(0.7, 0.02, 0.01) for take in plan["takes"]}
        longer = dict(row("v0--s0", digest="q"), durationSeconds=4.08)
        changed = screen.summarize(plan, view(plan, {}, scores), view(plan, {"v0--s0": longer}, scores))
        self.assertEqual((changed["paired"], changed["sameDuration"]), (6, 5))
        same = screen.summarize(plan, view(plan, {}, scores), view(plan, {"v0--s0": row("v0--s0", digest="q")}, scores))
        self.assertEqual(same["sameDuration"], 6)
        rule = dict(DecisionTests.RULE, requiresSameDuration=True)
        decided = screen.decide(dict(DecisionTests().summary((-0.01, 0.01), (0.0, 0.0)), paired=6, sameDuration=5), rule)
        self.assertEqual(decided["verdict"], "INCONCLUSIVE")
        self.assertIn("reached the talker", decided["open"][0])
        kept = screen.decide(dict(DecisionTests().summary((-0.01, 0.01), (0.0, 0.0)), paired=6, sameDuration=6), rule)
        self.assertEqual(kept["verdict"], "ADOPT")


class CodeCountTests(unittest.TestCase):
    def test_the_talker_s_code_count_is_read_from_the_engine_row_wherever_it_nests(self):
        record = {"summary": {"timingsMS": {"qwen_generated_code_count": 72}}}
        self.assertEqual(screen.generated_code_count(record), 72)
        self.assertIsNone(screen.generated_code_count({"summary": {}}))
        with tempfile.TemporaryDirectory() as temp:
            telemetry = Path(temp) / "generations.jsonl"
            telemetry.write_text(json.dumps({"generationID": "ABC", "timings": {"qwen_generated_code_count": 40}}) + "\n")
            rows = [{"takeID": "t", "generationID": "abc"}]
            screen.arm_evidence(telemetry, rows)
            self.assertEqual(rows[0]["generatedCodeCount"], 40)

    def test_a_clone_onset_trim_moves_the_length_but_only_the_talker_moves_the_code_count(self):
        plan = plan_of(voices=3, per_voice=2)
        scores = {take["takeID"]: score(0.7, 0.02, 0.01) for take in plan["takes"]}
        a_rows = {take["takeID"]: dict(row(take["takeID"]), generatedCodeCount=50) for take in plan["takes"]}
        trimmed = dict(a_rows, **{"v0--s0": dict(a_rows["v0--s0"], durationSeconds=3.94, digest="q")})
        summary = screen.summarize(plan, view(plan, a_rows, scores), view(plan, trimmed, scores))
        self.assertEqual((summary["sameDuration"], summary["sameCodeCount"]), (5, 6))
        rule = dict(DecisionTests.RULE, requiresSameCodeCount=True)
        decided = screen.decide(dict(DecisionTests().summary((-0.01, 0.01), (0.0, 0.0)), paired=6, sameCodeCount=6), rule)
        self.assertEqual(decided["verdict"], "ADOPT")
        moved = screen.decide(dict(DecisionTests().summary((-0.01, 0.01), (0.0, 0.0)), paired=6, sameCodeCount=5), rule)
        self.assertEqual(moved["verdict"], "INCONCLUSIVE")
        self.assertIn("talker's code count", moved["open"][0])

    def test_a_runaway_transcription_is_read_as_one_edit_per_unit_at_most(self):
        metrics = screen.take_metrics(row("t"), score(0.7, 32.6, 2.6))
        self.assertEqual(metrics["errorRate:" + QWEN], 1.0)
        self.assertEqual(metrics["errorRateBetterFamily"], 1.0)
        self.assertEqual(screen.take_metrics(row("t"), score(0.7, 0.2, 0.3))["errorRateBetterFamily"], 0.2)


class DecisionTests(unittest.TestCase):
    RULE = {"recorded": "2026-01-01", "maximumExtraGrossFailures": 1, "guards": {
        "speakerSimilarity": {"higherIsBetter": True, "margin": 0.02},
        "errorRateBetterFamily": {"higherIsBetter": False, "margin": 0.01}}}

    def summary(self, similarity, error, gross=(0, 0)) -> dict:
        return {"grossFailures": {"a": gross[0], "b": gross[1]}, "metrics": {
            "speakerSimilarity": {"interval95": list(similarity)}, "errorRateBetterFamily": {"interval95": list(error)}}}

    def test_adopt_when_nothing_is_worse_beyond_its_margin(self):
        decision = screen.decide(self.summary((-0.01, 0.01), (-0.004, 0.006)), self.RULE)
        self.assertEqual(decision["verdict"], "ADOPT")
        self.assertEqual(screen.decide(self.summary((0.01, 0.05), (-0.02, -0.01), gross=(2, 3)), self.RULE)["verdict"], "ADOPT")

    def test_reject_when_a_metric_is_worse_for_certain_or_takes_are_lost(self):
        worse = screen.decide(self.summary((-0.06, -0.03), (-0.004, 0.006)), self.RULE)
        self.assertEqual(worse["verdict"], "REJECT")
        lost = screen.decide(self.summary((-0.01, 0.01), (-0.004, 0.006), gross=(0, 2)), self.RULE)
        self.assertEqual(lost["verdict"], "REJECT")
        self.assertIn("2 more gross failures", lost["harms"][0])

    def test_inconclusive_when_the_interval_reaches_past_a_margin_or_a_metric_is_missing(self):
        wide = screen.decide(self.summary((-0.04, 0.03), (-0.004, 0.006)), self.RULE)
        self.assertEqual(wide["verdict"], "INCONCLUSIVE")
        missing = self.summary((-0.01, 0.01), (0.0, 0.0))
        del missing["metrics"]["errorRateBetterFamily"]
        self.assertEqual(screen.decide(missing, self.RULE)["verdict"], "INCONCLUSIVE")


class FloorTests(unittest.TestCase):
    RULE = {"maximumFloorShareOfMargin": 0.71, "guards": {
        "speakerSimilarity": {"higherIsBetter": True, "margin": 0.05},
        "errorRateBetterFamily": {"higherIsBetter": False, "margin": 0.04}}}

    def floor(self, similarity, error) -> dict:
        return {"metrics": {"speakerSimilarity": {"interval95": list(similarity)},
                            "errorRateBetterFamily": {"interval95": list(error)}}}

    def test_a_floor_inside_the_share_of_every_margin_lets_the_rule_decide(self):
        self.assertEqual(screen.floor_violations(self.RULE, self.floor((-0.035, 0.005), (0.0, 0.027))), [])
        self.assertEqual(screen.floor_violations({"guards": {}}, None), [], "a rule without the condition needs no floor")

    def test_a_wide_or_missing_floor_makes_the_screen_unable_to_decide(self):
        wide = screen.floor_violations(self.RULE, self.floor((-0.04, 0.0), (0.0, 0.027)))
        self.assertEqual(len(wide), 1)
        self.assertIn("speakerSimilarity", wide[0])
        self.assertEqual(len(screen.floor_violations(self.RULE, None)), 1)
        missing = {"metrics": {"speakerSimilarity": {"interval95": [0.0, 0.0]}}}
        self.assertIn("errorRateBetterFamily", screen.floor_violations(self.RULE, missing)[0])
        summary = {"grossFailures": {"a": 0, "b": 0}, "metrics": {
            "speakerSimilarity": {"interval95": [0.0, 0.01]}, "errorRateBetterFamily": {"interval95": [-0.01, 0.0]}}}
        rule = dict(self.RULE, maximumExtraGrossFailures=4)
        self.assertEqual(screen.decide(summary, rule, self.floor((-0.01, 0.01), (0.0, 0.01)))["verdict"], "ADOPT")
        self.assertEqual(screen.decide(summary, rule, self.floor((-0.04, 0.01), (0.0, 0.01)))["verdict"], "INCONCLUSIVE")
        self.assertEqual(screen.decide(summary, rule, None)["verdict"], "INCONCLUSIVE")


class ArmTests(unittest.TestCase):
    def test_an_arm_of_another_plan_or_an_unfinished_one_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            for name, arm in (("done", {"planSHA256": "x", "complete": True}),
                              ("partial", {"planSHA256": "x"}), ("other", {"planSHA256": "y", "complete": True})):
                screen.write_json(run / "arms" / name / "arm.json", arm)
                screen.write_json(run / "arms" / name / "takes.json", {"takes": []})
            self.assertEqual(screen.arm_view(run, "done", {"planSHA256": "x"})["rows"], {})
            for name in ("partial", "other"):
                with self.assertRaises(screen.ScreenError):
                    screen.arm_view(run, name, {"planSHA256": "x"})


if __name__ == "__main__":
    unittest.main()
