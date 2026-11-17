#!/usr/bin/env python3
"""scripts/ios_device.sh picks the physical iPhone and its own run's engine rows.

The pulled diagnostics mirror holds every run's subtree (smoke, benchmark and diagnostics runs
mirror there too), so the first generations.jsonl a search returns can be another run's, and
Xcode 27's CoreDevice lists Simulator runtimes as paired devices beside the phone. The iPhone
memory qualification of 2026-10-20 failed both ways (CONV-21). The helpers run as shipped, from
the sourced lane, over trees and device lists shaped like that window's.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest

from shell_stubs import ROOT, LaneShell, quote

DEVICE_LIST = r'''
[[ "$1 $2 $3" == "devicectl list devices" ]] || exit 97
while (( $# )); do case "$1" in --json-output) output="$2"; shift 2 ;; *) shift ;; esac; done
printf '%s\n' "$QV_DEVICE_LIST" >"$output"
'''


class RunDiagnosticsDirTests(unittest.TestCase):
    def setUp(self) -> None:
        self.shell = LaneShell(self, "ios_device.sh")
        self.dest = self.shell.path / "device-diagnostics"

    def write_rows(self, directory: Path) -> None:
        (directory / "engine").mkdir(parents=True, exist_ok=True)
        (directory / "engine" / "generations.jsonl").write_text("{}\n", encoding="utf-8")

    def resolve(self, run: str) -> str:
        sentinel = self.dest / run / "memory-qualification-result.json"
        sentinel.parent.mkdir(parents=True, exist_ok=True)
        sentinel.write_text("{}", encoding="utf-8")
        result = self.shell.run(f"run_diagnostics_dir {quote(self.dest)} {quote(sentinel)}")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_reads_the_rows_beside_its_own_sentinel_among_other_runs(self) -> None:
        self.write_rows(self.dest)
        for other in ("ios-xcui-smoke-20261020-160313-80e6aba4", "ios-xcui-smoke-20261014-002614-3f711b56"):
            self.write_rows(self.dest / other)
        run = "ios-memory-qualification-20261020-174011-67cdd64d"
        self.write_rows(self.dest / run)
        self.assertEqual(self.resolve(run), str(self.dest / run))

    def test_without_rows_of_its_own_it_reads_the_whole_mirror(self) -> None:
        self.write_rows(self.dest)
        self.write_rows(self.dest / "ios-xcui-smoke-20261020-160313-80e6aba4")
        self.assertEqual(self.resolve("ios-logs-20261020-130125"), str(self.dest))


class DiagnosticsLaunchEnvironmentTests(unittest.TestCase):
    """What a diagnostics launch carries from the host's environment into the app."""

    def launch_environment(self, host: dict[str, str]) -> dict[str, str]:
        shell = LaneShell(self, "ios_device.sh")
        result = shell.run("device_diagnostics_env_json 'custom:speed:hello' run-1", env=host)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_forwards_the_tuning_prefixes_and_the_three_named_mlx_keys(self) -> None:
        environment = self.launch_environment({
            "QWENVOICE_STREAM_CHUNK_CACHE_CLEAR": "off",
            "QVOICE_IOS_MEMORY_PROFILE": "iphone15pro",
            "MLX_MAX_OPS_PER_BUFFER": "40",
            "MLX_MAX_MB_PER_BUFFER": "40",
            "MLX_ENABLE_TF32": "0",
        })
        self.assertEqual(environment["QWENVOICE_STREAM_CHUNK_CACHE_CLEAR"], "off")
        self.assertEqual(environment["QVOICE_IOS_MEMORY_PROFILE"], "iphone15pro")
        self.assertEqual(environment["MLX_MAX_OPS_PER_BUFFER"], "40")
        self.assertEqual(environment["MLX_MAX_MB_PER_BUFFER"], "40")
        self.assertEqual(environment["MLX_ENABLE_TF32"], "0")

    def test_keeps_its_own_keys_and_forwards_nothing_else_of_the_host(self) -> None:
        environment = self.launch_environment({
            "QVOICE_IOS_DEVICE_RUN_ID": "another-run",
            "QWENVOICE_DEBUG": "0",
            "MLX_SOMETHING_ELSE": "1",
            "HOME_SECRET": "never",
        })
        self.assertEqual(environment["QVOICE_IOS_DEVICE_RUN_ID"], "run-1")
        self.assertEqual(environment["QWENVOICE_DEBUG"], "1")
        self.assertEqual(environment["QVOICE_IOS_DEVICE_DIAGNOSTICS_SPEC"], "custom:speed:hello")
        self.assertNotIn("MLX_SOMETHING_ELSE", environment)
        self.assertNotIn("HOME_SECRET", environment)
        self.assertNotIn("PATH", environment)

    def test_forwards_only_registered_keys_never_the_build_paths_or_worker_session(self) -> None:
        # BKL-70: sourcing the lane exports scripts/lib/build_paths.sh's absolute build-output
        # paths (QVOICE_BUILD_ROOT, QVOICE_ARTIFACTS_IOS, ...); with the worker session and the
        # lane's own host-side knobs they stay on the Mac. Only registered keys cross.
        registry = json.loads((ROOT / "config/runtime-debug-knobs.json").read_text(encoding="utf-8"))
        registered = {key for group in registry["groups"] for key in group["keys"]}
        environment = self.launch_environment({
            "QVOICE_WORKER_SESSION": "f" * 64,
            "QVOICE_IOS_BENCH_TIMEOUT": "900",
            "QWENVOICE_DEVELOPMENT_TEAM": "TEAMID",
            "QVOICE_LAUNCH_RUN_ID": "host-only",
            "QVOICE_IOS_MODEL_MANAGEMENT_RUN_ID": "run-identity",
            "QWENVOICE_FORCE_MEMORY_CLASS": "constrained",
        })
        for key in ("QVOICE_WORKER_SESSION", "QVOICE_IOS_BENCH_TIMEOUT", "QWENVOICE_DEVELOPMENT_TEAM",
                    "QVOICE_LAUNCH_RUN_ID", "QVOICE_BUILD_ROOT", "QVOICE_ARTIFACTS_IOS",
                    "QVOICE_XCODE_IOS_DERIVED", "QVOICE_NATIVE_LOCK"):
            with self.subTest(key=key):
                self.assertNotIn(key, environment)
        self.assertEqual(environment["QVOICE_IOS_MODEL_MANAGEMENT_RUN_ID"], "run-identity")
        self.assertEqual(environment["QWENVOICE_FORCE_MEMORY_CLASS"], "constrained")
        mlx = {"MLX_MAX_OPS_PER_BUFFER", "MLX_MAX_MB_PER_BUFFER", "MLX_ENABLE_TF32"}
        self.assertLessEqual(set(environment), registered | mlx)
        self.assertFalse([value for value in environment.values() if value.startswith("/")])

    def test_the_build_paths_were_exported_where_the_launch_reads_its_environment(self) -> None:
        # The case above proves something only if the sourced lane really exports them.
        shell = LaneShell(self, "ios_device.sh")
        result = shell.run('printf "%s\\n" "${QVOICE_BUILD_ROOT:?}" "$(printenv QVOICE_ARTIFACTS_IOS)"')
        self.assertEqual(result.returncode, 0, result.stderr)
        root, artifacts = result.stdout.splitlines()
        self.assertTrue(root.startswith("/") and artifacts.startswith("/"), result.stdout)


class ResolveDeviceTests(unittest.TestCase):
    PHONE = {
        "identifier": "physical-phone",
        "hardwareProperties": {"reality": "physical"},
        "deviceProperties": {"name": "A paired iPhone"},
        "connectionProperties": {"pairingState": "paired"},
    }
    # Named like the device the lane prefers by name, so only the reality filter refuses it.
    SIMULATED = {
        "identifier": "simulated-runtime",
        "hardwareProperties": {"reality": "simulated"},
        "deviceProperties": {"name": "iPhone 17 Pro"},
        "connectionProperties": {"pairingState": "paired"},
    }

    def resolve(self, devices: list[dict]) -> subprocess.CompletedProcess[str]:
        shell = LaneShell(self, "ios_device.sh")
        shell.tool("xcrun", DEVICE_LIST)
        return shell.run(
            "unset QVOICE_IOS_DEVICE_ID\nresolve_device\n",
            env={"QV_DEVICE_LIST": json.dumps({"result": {"devices": devices}})},
        )

    def test_a_simulated_runtime_is_never_chosen_or_counted(self) -> None:
        result = self.resolve([self.SIMULATED, self.PHONE])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "physical-phone")

    def test_only_a_simulated_runtime_finds_no_iphone(self) -> None:
        result = self.resolve([self.SIMULATED])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no paired iPhone found", result.stderr)


if __name__ == "__main__":
    unittest.main()
