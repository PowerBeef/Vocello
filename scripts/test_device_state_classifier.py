#!/usr/bin/env python3
"""Unit tests for ios_coredevice_probe.py — offline JSON fixtures only."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import ios_coredevice_probe as probe  # noqa: E402

FIXTURES = ROOT / "Tests" / "DeviceProbeFixtures"


class CoreDeviceProbeTests(unittest.TestCase):
    def test_connected_device(self) -> None:
        data = json.loads((FIXTURES / "devicectl-list-connected.json").read_text())
        dev = probe.pick_device(data, "00000000-0000-0000-0000-000000000001")
        self.assertIsNotNone(dev)
        summary = probe.summarize_device(dev)
        self.assertTrue(summary["availableForDevelopment"])
        self.assertEqual(summary["tunnelState"], "connected")

    def test_unavailable_device(self) -> None:
        data = json.loads((FIXTURES / "devicectl-list-unavailable.json").read_text())
        dev = probe.pick_device(data, "00000000-0000-0000-0000-000000000001")
        self.assertIsNotNone(dev)
        summary = probe.summarize_device(dev)
        self.assertFalse(summary["availableForDevelopment"])

    def test_paired_network_device_with_connect_capability_is_reachable(self) -> None:
        device = {
            "identifier": "device",
            "connectionProperties": {
                "tunnelState": "disconnected",
                "pairingState": "paired",
                "transportType": "localNetwork",
            },
            "capabilities": [
                {"featureIdentifier": "com.apple.coredevice.feature.connectdevice"}
            ],
        }
        self.assertTrue(probe.summarize_device(device)["availableForDevelopment"])

    def test_lock_state_locked_fixture_shape(self) -> None:
        raw = json.loads((FIXTURES / "lockState-locked.json").read_text())
        lock = raw["result"]["lockState"]
        self.assertFalse(lock["unlockedSinceBoot"])
        self.assertTrue(lock["passcodeRequired"])

    def test_current_lock_is_not_historical_unlock(self) -> None:
        # A normally used phone has unlockedSinceBoot=true even after Auto-Lock.
        for nested in (False, True):
            for required in (True, False):
                with self.subTest(nested=nested, required=required):
                    fields = {"unlockedSinceBoot": True, "passcodeRequired": required}
                    raw = {"result": {"lockState": fields} if nested else fields}
                    result = probe.summarize_lock_state(raw)
                    self.assertEqual(result["state"], "known")
                    self.assertIs(result["deviceLocked"], required)
                    self.assertIs(result["unlockedSinceBoot"], True)

    def test_missing_or_malformed_current_lock_remains_unknown(self) -> None:
        for value in (None, "false", "true", 0, 1):
            with self.subTest(value=value):
                result = probe.summarize_lock_state({"result": {
                    "unlockedSinceBoot": True, "passcodeRequired": value,
                }})
                self.assertEqual(result["state"], "unknown")
                self.assertIsNone(result["deviceLocked"])

    def test_automation_readiness_does_not_use_lock_state(self) -> None:
        core = {
            "reachable": True,
            "lock": {"state": "known", "deviceLocked": True, "unlockedSinceBoot": False},
        }
        ready, blockers = probe.automation_blockers(verdict="READY", coredevice=core)
        self.assertTrue(ready)
        self.assertEqual(blockers, [])

    def test_headless_lane_does_not_use_lock_state(self) -> None:
        core = {
            "reachable": True,
            "lock": {"state": "known", "deviceLocked": True},
        }
        ready, blockers = probe.automation_blockers(verdict="READY", coredevice=core)
        self.assertTrue(ready)
        self.assertEqual(blockers, [])

    def test_automation_device_unreachable(self) -> None:
        ready, blockers = probe.automation_blockers(
            verdict="DEVICE_UNREACHABLE", coredevice={"reachable": False}
        )
        self.assertFalse(ready)
        self.assertIn("device_unreachable", blockers)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
