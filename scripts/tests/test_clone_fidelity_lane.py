#!/usr/bin/env python3
"""Unit tests for scripts/clone_fidelity_lane.py's deterministic plumbing.

Generation and ML backends are injected/absent; these tests cover the plan,
command construction, and fail-loud generation loop.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from clone_fidelity_lane import (
    FIXED_TEXT,
    build_take_plan,
    generate_all,
    generation_command,
)


class CloneFidelityLaneTests(unittest.TestCase):
    def test_plan_orders_clones_then_controls_with_deterministic_seeds(self):
        plan = build_take_plan("A_warm_elderly_woman", 3, 2, 100)
        self.assertEqual([item["kind"] for item in plan],
                         ["clone", "clone", "clone", "control", "control"])
        self.assertEqual([item["seed"] for item in plan], [100, 101, 102, 100, 101])
        self.assertEqual(plan[3]["speaker"], "aiden")
        self.assertEqual(plan[4]["speaker"], "serena")
        names = [item["name"] for item in plan]
        self.assertEqual(len(names), len(set(names)))

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


if __name__ == "__main__":
    unittest.main()
