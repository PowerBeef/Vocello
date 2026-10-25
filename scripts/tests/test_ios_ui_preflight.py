"""The iPhone UI readiness preflight (audit P1-2) over the shipped ui_test.sh function."""

from __future__ import annotations

import json
import unittest

from shell_stubs import UIFunctionShell, quote


def probe(**fields: object) -> dict[str, object]:
    value: dict[str, object] = {
        "reachable": True, "identifier": "fixture-device", "availableForDevelopment": True,
        "lock": {"state": "known", "deviceLocked": False},
    }
    value.update(fields)
    return value


class IOSUIPreflightTests(unittest.TestCase):
    def run_preflight(self, reported: dict[str, object], team: str = "TEAMFIXTURE",
                      mirroring: bool = False):
        shell = UIFunctionShell(self)
        # Always stubbed: the real check would read this Mac's process list.
        body = (
            f"ios_mirroring_running() {{ return {0 if mirroring else 1}; }}\n"
            f"ios_probe() {{ echo probed >&2; printf '%s' {quote(json.dumps(reported))}; }}\n"
            f"derive_team() {{ printf '%s' {quote(team)}; [[ -n {quote(team)} ]]; }}\n"
            "device='' team=''\n"
            'ios_ui_preflight\n'
            'printf "device=%s team=%s\\n" "$device" "$team"\n'
        )
        return shell.run(("ios_ui_preflight",), body)

    def test_a_ready_phone_sets_the_device_and_team(self) -> None:
        completed = self.run_preflight(probe())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("device=fixture-device team=TEAMFIXTURE", completed.stdout)

    def test_open_iphone_mirroring_refuses_before_the_probe(self) -> None:
        # The phone reports unlocked, as it did under Mirroring in runs 221807-222344.
        completed = self.run_preflight(probe(), mirroring=True)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("iPhone Mirroring is open", completed.stderr)
        self.assertNotIn("probed", completed.stderr)
        self.assertNotIn("device=", completed.stdout)

    def test_each_unready_state_fails_before_the_lane_goes_on(self) -> None:
        cases = {
            "locked": (probe(lock={"state": "known", "deviceLocked": True}), "is locked"),
            "unreachable": (probe(reachable=False), "not reachable through CoreDevice"),
            "developer mode": (probe(availableForDevelopment=False), "Developer Mode"),
        }
        for name, (reported, message) in cases.items():
            with self.subTest(name):
                completed = self.run_preflight(reported)
                self.assertEqual(completed.returncode, 1)
                self.assertIn("ui-preflight: ", completed.stderr)
                self.assertIn(message, completed.stderr)
                self.assertNotIn("device=", completed.stdout)

    def test_an_unknown_lock_state_proceeds_with_a_note(self) -> None:
        completed = self.run_preflight(probe(lock={"state": "unknown"}))
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("does not report the lock state", completed.stderr)
        self.assertIn("device=fixture-device", completed.stdout)

    def test_a_missing_team_fails(self) -> None:
        completed = self.run_preflight(probe(), team="")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("no Apple Development team", completed.stderr)


if __name__ == "__main__":
    unittest.main()
