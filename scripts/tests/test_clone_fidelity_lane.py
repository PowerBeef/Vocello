#!/usr/bin/env python3
"""Unit tests for scripts/clone_fidelity_lane.py's deterministic plumbing.

Generation and ML backends are injected/absent; these tests cover the plan,
command construction, and fail-loud generation loop.
"""
from contextlib import redirect_stdout
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clone_fidelity_lane import (
    DEFAULT_CROSS_CLONES,
    DEFAULT_MATCHED_CONTROLS,
    FIXED_TEXT,
    build_take_plan,
    builtin_speaker_genders,
    gate_takes,
    generate_all,
    generation_command,
    infer_reference_gender,
    matched_control_speakers,
    resolve_cross_clones,
)


class CloneFidelityLaneTests(unittest.TestCase):
    def test_plan_orders_clones_then_controls_with_deterministic_seeds(self):
        plan = build_take_plan("A_warm_elderly_woman", 3, 2, 100)
        self.assertEqual([item["kind"] for item in plan],
                         ["clone", "clone", "clone", "control", "control"])
        self.assertEqual([item["seed"] for item in plan], [100, 101, 102, 100, 101])
        # Controls match the reference's gender (audit #103): no cross-gender control.
        self.assertEqual(plan[3]["speaker"], "vivian")
        self.assertEqual(plan[4]["speaker"], "serena")
        self.assertTrue(all(item["matchedGender"] for item in plan[3:]))
        names = [item["name"] for item in plan]
        self.assertEqual(len(names), len(set(names)))

    def test_the_default_plan_has_eight_matched_controls_and_no_unnamed_clones(self):
        """Audit #103 part 1: eight matched controls; cross-clones only when named."""
        self.assertEqual((DEFAULT_MATCHED_CONTROLS, DEFAULT_CROSS_CLONES), (8, 0))
        genders = builtin_speaker_genders()
        self.assertEqual(genders["serena"], "female")
        self.assertEqual(genders["aiden"], "male")
        default = build_take_plan("A_warm_elderly_woman", 6, DEFAULT_MATCHED_CONTROLS, 100,
                                  cross_clone_count=DEFAULT_CROSS_CLONES)
        self.assertFalse([item for item in default if item["kind"] == "cross-clone"])
        self.assertEqual({item["voice"] for item in default if item["mode"] == "clone"},
                         {"A_warm_elderly_woman"})
        plan = build_take_plan(
            "A_warm_elderly_woman", 6, DEFAULT_MATCHED_CONTROLS, 100,
            cross_clone_voices=["Bright_young_man", "Calm_narrator"],
            cross_clone_count=4,
        )
        controls = [item for item in plan if item["kind"] == "control"]
        self.assertEqual(len(controls), 8)
        self.assertTrue(all(genders[item["speaker"]] == "female" for item in controls))
        self.assertEqual(len({item["name"] for item in controls}), 8)
        crosses = [item for item in plan if item["kind"] == "cross-clone"]
        self.assertEqual([item["voice"] for item in crosses],
                         ["Bright_young_man", "Calm_narrator", "Bright_young_man", "Calm_narrator"])
        command = generation_command("/repo/build/vocello", crosses[0], "/tmp/run")
        self.assertIn("--confirm-consent", command)
        self.assertIn("Bright_young_man", command)
        # Without another saved voice there are no cross-clone takes.
        self.assertFalse([item for item in build_take_plan(
            "A_warm_elderly_woman", 1, 8, 1, cross_clone_voices=["A_warm_elderly_woman"],
            cross_clone_count=4) if item["kind"] == "cross-clone"])

    def test_reference_gender_is_inferred_or_required(self):
        self.assertEqual(infer_reference_gender("A_warm_elderly_woman"), "female")
        self.assertEqual(infer_reference_gender("Deep-voiced_man"), "male")
        self.assertIsNone(infer_reference_gender("VoiceX"))
        self.assertEqual(matched_control_speakers("male")[0], "aiden")
        self.assertIn("serena", matched_control_speakers(None))

    def test_cross_clone_voices_are_only_the_ones_the_operator_names(self):
        """Every clone take attests consent, so no voice is cloned unless named."""
        self.assertEqual(resolve_cross_clones("Target", []), ([], 0))
        self.assertEqual(resolve_cross_clones("Target", ["Other_b", "Other_a"]),
                         (["Other_b", "Other_a"], 2))
        self.assertEqual(resolve_cross_clones("Target", ["Other_a"], 3), (["Other_a"], 3))
        for named, count, message in (
            ([], 4, "--cross-clone-voice NAME"),
            (["Other_a"], 0, "contradicts"),
            (["Target"], None, "reference voice"),
            (["Other_a", "Other_a"], None, "named once"),
            ([" "], None, "needs a saved voice name"),
            (["Other_a"], -1, "negative"),
        ):
            with self.subTest(named=named, count=count), self.assertRaisesRegex(ValueError, message):
                resolve_cross_clones("Target", named, count)

    def test_clone_command_uses_saved_voice_and_consistent_variation(self):
        item = build_take_plan("VoiceX", 1, 0, 7)[0]
        command = generation_command("/repo/build/vocello", item, "/tmp/run")
        self.assertIn("--voice", command)
        self.assertIn("VoiceX", command)
        self.assertIn("--variation", command)
        self.assertIn("consistent", command)
        self.assertIn(FIXED_TEXT, command)
        self.assertNotIn("--speaker", command)

    def test_control_command_uses_speaker(self):
        item = build_take_plan("VoiceX", 0, 1, 7)[0]
        command = generation_command("/repo/build/vocello", item, "/tmp/run")
        self.assertIn("--speaker", command)
        self.assertIn("aiden", command)
        self.assertNotIn("--voice", command)

    def test_generate_all_fails_loud_with_take_name(self):
        class Result:
            returncode = 1
            stderr = "engine exploded"

        plan = build_take_plan("VoiceX", 1, 0, 7)
        with self.assertRaisesRegex(RuntimeError, "clone_take_00.wav"):
            generate_all(plan, "/tmp/run", "/repo/build/vocello",
                         run=lambda *args, **kwargs: Result())

    def test_generate_all_runs_one_process_per_take(self):
        calls = []

        class Result:
            returncode = 0
            stderr = ""

        def fake_run(command, **kwargs):
            calls.append(command)
            return Result()

        plan = build_take_plan("VoiceX", 2, 1, 7)
        generate_all(plan, "/tmp/run", "/repo/build/vocello", run=fake_run)
        self.assertEqual(len(calls), 3)

    def test_only_the_clone_takes_are_gated_each_against_the_reference_clip(self):
        plan = build_take_plan("A_warm_elderly_woman", 2, 2, 7, cross_clone_voices=["Calm_narrator"],
                               cross_clone_count=1)
        takes = gate_takes(plan, "/tmp/run", "/data/voices/A_warm_elderly_woman.wav")
        self.assertEqual([take["takeID"] for take in takes if not take["control"]],
                         ["clone_take_00", "clone_take_01"])
        # The matched controls and the cross-clone negative are negative controls, with no reference.
        self.assertEqual(sorted(take["takeID"] for take in takes if take["control"]),
                         ["control_serena_01", "control_vivian_00", "cross_clone_00"])
        self.assertEqual({take["reference"] for take in takes if not take["control"]},
                         {"/data/voices/A_warm_elderly_woman.wav"})
        self.assertEqual({take["reference"] for take in takes if take["control"]}, {None})
        self.assertEqual({(take["language"], take["text"]) for take in takes}, {("english", FIXED_TEXT)})

    def test_gates_that_cannot_be_computed_report_an_error_at_warn(self):
        import audio_qc_lane_gates
        from clone_fidelity_lane import audio_qc_gates

        def refuse(*args, **kwargs):
            raise audio_qc_lane_gates.GateError("speaker.campplus-voxceleb@1 is not acquired")

        plan = build_take_plan("VoiceX", 1, 0, 7)
        with mock.patch.object(audio_qc_lane_gates, "lane_has_fail_gate", return_value=False), \
                redirect_stdout(io.StringIO()), mock.patch.object(sys, "stderr", io.StringIO()) as err:
            self.assertEqual(audio_qc_gates(plan, "/tmp/run", "/data/voices/VoiceX.wav", run_gates=refuse),
                             {"verdict": "error"})
        self.assertIn("ERROR · not computed", err.getvalue())
        with mock.patch.object(audio_qc_lane_gates, "lane_has_fail_gate", return_value=True), \
                mock.patch.object(sys, "stderr", io.StringIO()):
            self.assertEqual(audio_qc_gates(plan, "/tmp/run", "/data/voices/VoiceX.wav", run_gates=refuse),
                             {"verdict": "fail"})

    def test_the_gates_run_after_every_take_and_analyzer_and_only_a_fail_gate_fails_the_lane(self):
        import clone_fidelity_lane as lane

        events = []
        with tempfile.TemporaryDirectory() as temporary:
            root = os.path.join(temporary, "repo")
            os.makedirs(os.path.join(root, "build"))
            open(os.path.join(root, "build", "vocello"), "w").close()
            data = os.path.join(temporary, "data")
            os.makedirs(os.path.join(data, "voices"))
            open(os.path.join(data, "voices", "VoiceX.wav"), "w").close()
            run_dir = os.path.join(temporary, "run")

            def generate(plan, out_dir, vocello):
                events.append("generate")
                for item in plan:
                    open(os.path.join(out_dir, item["name"]), "w").close()

            def gate(plan, out_dir, reference):
                events.append("gates")
                self.assertTrue(all(os.path.isfile(os.path.join(out_dir, item["name"])) for item in plan))
                return {"verdict": verdict}

            argv = ["clone_fidelity_lane.py", "--voice", "VoiceX", "--takes", "2", "--controls", "1",
                    "--reference-gender", "female", "--data-dir", data, "--run-dir", run_dir]
            for verdict, failed in (("warn", False), ("fail", True)):
                events.clear()
                with mock.patch.object(lane, "repo_root", return_value=root), \
                        mock.patch.object(lane, "generate_all", side_effect=generate), \
                        mock.patch("analyze_prosody.analyze",
                                   side_effect=lambda path: events.append("analyze") or {}), \
                        mock.patch.object(lane, "evaluate_takes", return_value={"aggregate": {}}), \
                        mock.patch.object(lane, "ecapa_section",
                                          side_effect=lambda *args: events.append("similarity") or {}), \
                        mock.patch.object(lane, "audio_qc_gates", side_effect=gate), \
                        mock.patch.object(sys, "argv", argv), redirect_stdout(io.StringIO()):
                    if failed:
                        with self.assertRaises(SystemExit) as raised:
                            lane.main()
                        self.assertEqual(raised.exception.code, 1)
                    else:
                        lane.main()
                self.assertEqual(events, ["generate", "analyze", "analyze", "analyze", "similarity", "gates"])
                with open(os.path.join(run_dir, "clone-fidelity-report.json"), encoding="utf-8") as handle:
                    self.assertEqual(json.load(handle)["audioQCGates"], {"verdict": verdict})


if __name__ == "__main__":
    unittest.main()
