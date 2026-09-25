#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import json
import os
import subprocess
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[2]


def shell_function(text: str, name: str) -> str:
    prefix = f"{name}() {{\n"
    start = text.index(prefix)
    end = text.index("\n}\n", start) + 3
    return text[start:end]


class ProfileCaptureContractTests(unittest.TestCase):
    def test_profile_retention_runs_only_after_history_publication(self) -> None:
        for script, platform in (("macos_test.sh", "macos"), ("ios_device.sh", "ios")):
            with self.subTest(script=script):
                text = (REPO / "scripts" / script).read_text(encoding="utf-8")
                profile = shell_function(text, "cmd_profile")
                self.assertIn("--keep-trace", profile)
                self.assertEqual(
                    profile.count("profile_trace_retention.py\" preflight"), 2,
                    "profile must check disk space both before build/install and immediately before launch",
                )
                self.assertIn("profile_trace_retention.py\" mark-failure", text)
                self.assertIn("profile_trace_retention.py\" finalize-success", profile)
                self.assertIn("trap profile_failure_cleanup EXIT", profile)
                self.assertIn(f'--platform {platform} --kind "$kind"', profile)
                self.assertIn('--retention-policy "$retention_policy"', profile)
                self.assertIn('--summary-artifact "$profile_summary"', profile)
                self.assertLess(
                    profile.index('record_benchmark_history "$artifacts"'),
                    profile.index('profile_trace_retention.py" finalize-success'),
                )
                self.assertLess(
                    profile.index('profile_trace_retention.py" preflight'),
                    profile.index("xcrun xctrace record"),
                )
                target_launch = (
                    "xcrun devicectl device process launch"
                    if platform == "ios"
                    else "exec /usr/bin/env -i"
                )
                self.assertLess(
                    profile.rindex('profile_trace_retention.py" preflight'),
                    profile.index(target_launch),
                )
                self.assertIn('PROFILE_TRACE_PHASE="final-disk-preflight"', profile)
                self.assertIn('PROFILE_TRACE_PUBLISHED=1', profile)
                self.assertIn('summaryOnly', profile)
                self.assertIn('keptExplicitly', profile)

    def test_macos_profile_records_cpu_and_signposts_after_exact_pid_attach(self) -> None:
        profile = shell_function(
            (REPO / "scripts" / "macos_test.sh").read_text(encoding="utf-8"),
            "cmd_profile",
        )
        self.assertIn('--attach "$target_pid"', profile)
        self.assertIn('--no-prompt', profile)
        self.assertIn('"$QVOICE_BUILD_ROOT/vocello" bench', profile)
        self.assertIn('local suspended_launcher_source="$SCRIPT_DIR/lib/spawn_suspended.c"', profile)
        self.assertIn(
            'local suspended_launcher="$QVOICE_SCRATCH_TRANSIENT/tools/spawn-suspended"',
            profile,
        )
        self.assertIn('"$suspended_launcher" "$target_pid_file" "$QVOICE_BUILD_ROOT/vocello" bench', profile)
        self.assertIn('wait "$launcher_pid"', profile)
        self.assertNotIn('kill -STOP "$BASHPID"', profile)
        self.assertIn('kill -CONT "$target_pid"', profile)
        self.assertIn('grep -q \'^Starting recording\'', profile)
        self.assertIn('local profiled_pid="$target_pid"', profile)
        self.assertIn('--target-pid "$profiled_pid"', profile)
        self.assertIn('QWENVOICE_NATIVE_TELEMETRY_MODE=verbose', profile)
        self.assertIn('QVOICE_MAC_PROFILE_GRACE_TIMEOUT', profile)
        self.assertIn(
            'profile_deadline=$((SECONDS + duration + profile_grace_timeout))',
            profile,
        )
        self.assertIn('profile_child_finished "$launcher_pid"', profile)
        self.assertIn('profile_child_finished "$xctrace_pid"', profile)
        self.assertIn('profile target/tracer exceeded', profile)
        self.assertIn('artifacts preserved in $artifacts', profile)
        self.assertNotIn("--launch --", profile)

    def test_ios_profile_records_cpu_and_signposts_after_exact_pid_attach(self) -> None:
        profile = shell_function(
            (REPO / "scripts" / "ios_device.sh").read_text(encoding="utf-8"),
            "cmd_profile",
        )
        self.assertIn('--attach "$target_pid"', profile)
        self.assertIn('--no-prompt', profile)
        self.assertIn("grep -q '^Starting recording'", profile)
        self.assertIn("tracer_start_deadline=$((SECONDS + tracer_start_timeout))", profile)
        self.assertNotIn("--notify-tracing-started", profile)
        self.assertIn('device process resume --device "$dev" --pid "$target_pid"', profile)
        self.assertIn('export QWENVOICE_NATIVE_TELEMETRY_MODE=verbose', profile)
        self.assertNotIn("sleep 5", profile)

    def test_memory_profiles_add_allocations_and_vm_tracker_without_losing_cpu_or_signposts(self) -> None:
        for script in ("macos_test.sh", "ios_device.sh"):
            with self.subTest(script=script):
                text = (REPO / "scripts" / script).read_text(encoding="utf-8")
                profile = shell_function(text, "cmd_profile")
                # macOS also accepts the signpost-only witness kind (audit #50).
                self.assertRegex(profile, r'case "\$kind" in cpu\|memory(\|witness)?\)')
                self.assertIn('--template "$capture_instruments"', profile)
                self.assertIn('--target-pid', profile)
                self.assertIn('--profile-kind "$kind"', profile)
                self.assertIn('xctrace export --input "$trace" --toc --output "$toc"', profile)

        mac_profile = shell_function(
            (REPO / "scripts" / "macos_test.sh").read_text(encoding="utf-8"),
            "cmd_profile",
        )
        self.assertIn('profile_length="long"', mac_profile)
        self.assertIn('profile_warm="0"', mac_profile)
        self.assertIn('QVOICE_MAC_MEMORY_PROFILE_DURATION:-180', mac_profile)
        self.assertIn('default_profile_grace_timeout=60', mac_profile)
        publisher = (REPO / "scripts" / "publish_benchmark_history.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'require_disabled_vm_auto_snapshot=args.profile_kind == "memory"',
            publisher,
        )

    @staticmethod
    def profile_instruments(script: str, kind: str) -> tuple[list[str], str]:
        """What a profile kind hands xctrace record, and the label it publishes."""
        helper = shell_function(
            (REPO / "scripts" / script).read_text(encoding="utf-8"), "profile_instrument_args",
        )
        completed = subprocess.run(
            [
                "bash", "-c",
                "set -euo pipefail; " + helper + '\nprofile_instrument_args "$1"; '
                'printf \'%s\\n\' "$PROFILE_CAPTURE_INSTRUMENTS" "${PROFILE_INSTRUMENT_ARGS[@]}"',
                "test", kind,
            ],
            text=True, capture_output=True, check=True,
        )
        label, *arguments = completed.stdout.splitlines()
        return arguments, label

    def test_profile_kinds_pass_their_instruments_to_xctrace(self) -> None:
        cpu = ["--instrument", "CPU Profiler", "--instrument", "os_signpost"]
        # A memory profile records Allocations and VM Tracker only through Apple's
        # Allocations template, whose VM Tracker takes no automatic snapshots;
        # standalone instruments would (audit #51, d52340a0).
        memory = ["--template", "Allocations", "--instrument", "CPU Profiler",
                  "--instrument", "os_signpost"]
        cases = {
            ("macos_test.sh", "cpu"): (cpu, "CPU Profiler + os_signpost"),
            ("macos_test.sh", "memory"): (
                memory, "CPU Profiler + Allocations + VM Tracker + os_signpost",
            ),
            # The witness records signposts alone, no sampler (audit #50).
            ("macos_test.sh", "witness"): (["--instrument", "os_signpost"], "os_signpost"),
            ("ios_device.sh", "cpu"): (cpu, "CPU Profiler + os_signpost"),
            ("ios_device.sh", "memory"): (
                memory, "CPU Profiler + Allocations + VM Tracker + os_signpost",
            ),
        }
        for (script, kind), expected in cases.items():
            with self.subTest(script=script, kind=kind):
                self.assertEqual(self.profile_instruments(script, kind), expected)

    def test_memory_qualification_is_separate_from_instruments_profiles(self) -> None:
        mac = (REPO / "scripts" / "macos_test.sh").read_text(encoding="utf-8")
        ios = (REPO / "scripts" / "ios_device.sh").read_text(encoding="utf-8")
        for script in (mac, ios):
            main = shell_function(script, "main")
            memory_case = main[main.index("memory)") :]
            self.assertIn('cmd_memory "$@"', memory_case)
            self.assertIn("require_build_free_space memory-qualification", memory_case)
        mac_memory = shell_function(mac, "cmd_memory")
        self.assertIn('--memory-qualification retained-memory-v1', mac_memory)
        self.assertIn('mkdir -p "$runtime/voices"', mac_memory)
        self.assertNotIn('ln -s "$HOME/Library/Application Support/QwenVoice-Debug/voices" "$runtime/voices"', mac_memory)
        self.assertIn('--modes custom,design,clone', mac_memory)
        self.assertIn('--warm 3', mac_memory)
        self.assertIn('publish_benchmark_history.py" memory-qualification', mac_memory)
        self.assertNotIn("xctrace", mac_memory)
        ios_memory = shell_function(ios, "cmd_memory")
        self.assertIn('QVOICE_IOS_DEVICE_MEMORY_QUALIFICATION_SPEC', ios_memory)
        self.assertIn('wait_memory_qualification_sentinel', ios_memory)
        self.assertIn(
            'memory-qualification-result.json',
            shell_function(ios, "wait_memory_qualification_sentinel"),
        )
        memory_wait = shell_function(ios, "wait_memory_qualification_sentinel")
        self.assertIn('memory-qualification-failure.json', memory_wait)
        self.assertIn('path.stat().st_size > 4096', memory_wait)
        self.assertIn('record.get("status") != "failed"', memory_wait)
        self.assertIn('return 22', memory_wait)
        self.assertLess(
            memory_wait.index('memory-qualification-failure.json'),
            memory_wait.index('memory-qualification-result.json'),
        )
        self.assertEqual(ios_memory.count("device process launch"), 1)
        self.assertIn('read_devicectl_launch_pid "$launch_json"', ios_memory)
        self.assertIn('f"{mode}/speed/medium/retained#{repetition}"', ios_memory)
        self.assertIn("device process terminate --device %q --pid %q", ios_memory)
        self.assertIn('trap "$cleanup_command" EXIT', ios_memory)
        self.assertIn('publish_benchmark_history.py" memory-qualification', ios_memory)
        self.assertIn('no history was published', ios_memory)
        self.assertLess(
            ios_memory.index('wait_memory_qualification_sentinel'),
            ios_memory.index('publish_benchmark_history.py'),
        )
        self.assertNotIn("xctrace", ios_memory)

    def test_memory_policy_is_versioned_and_platform_topologies_are_fixed(self) -> None:
        import json

        policy = json.loads(
            (REPO / "config" / "memory-qualification-policy.json").read_text(encoding="utf-8")
        )
        self.assertEqual(policy["schemaVersion"], 1)
        self.assertEqual(policy["policyID"], "retained-memory-v1")
        self.assertEqual(policy["metric"], "withinModeRetainedPhysicalFootprintGrowth")
        self.assertEqual(policy["modes"], ["custom", "design", "clone"])
        self.assertEqual(policy["variant"], "speed")
        self.assertEqual(policy["length"], "medium")
        self.assertEqual(policy["repetitionsPerMode"], 3)
        self.assertEqual(policy["seed"], 19790615)
        self.assertEqual(policy["retentionThresholdFractionOfPhysicalMemory"], 0.05)
        self.assertEqual(policy["expectedTakeCounts"], {"macos": 11, "ios": 9})
        # retained-memory-v2 rides the same run matrix under its own ID and has
        # no bound until a consented run calibrates one (audit #25/#26).
        retained_v2 = policy["retainedMemoryV2"]
        self.assertEqual(retained_v2["policyID"], "retained-memory-v2")
        for platform in ("macos", "ios"):
            entry = retained_v2["calibration"][platform]
            if entry["status"] == "uncalibrated":
                self.assertIsNone(entry["calibrationRunID"])
                self.assertEqual(set(entry["growthLimitMBByMode"].values()), {None})
            else:
                self.assertEqual(entry["status"], "calibrated")
                self.assertIsInstance(entry["calibrationRunID"], str)

    def test_ios_memory_wait_terminates_on_bounded_failure_marker(self) -> None:
        ios = (REPO / "scripts" / "ios_device.sh").read_text(encoding="utf-8")
        wait = shell_function(ios, "wait_memory_qualification_sentinel")
        run_id = "ios-memory-qualification-failure-fixture"
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / run_id / "memory-qualification-failure.json"
            marker.parent.mkdir(parents=True)
            marker.write_text(json.dumps({
                "schemaVersion": 1,
                "status": "failed",
                "runID": run_id,
                "policyID": "retained-memory-v1",
                "failedAt": "2026-07-13T07:00:00Z",
                "failureCode": "generation_failed",
                "completedTakeCount": 2,
                "expectedTakeCount": 9,
                "failedTakeIndex": 3,
                "failedCell": "custom/speed/medium/retained#2",
            }), encoding="utf-8")
            completed = subprocess.run(
                [
                    "bash", "-c",
                    "note() { printf '%s\\n' \"$*\" >&2; }; "
                    "warn() { printf '%s\\n' \"$*\" >&2; }; "
                    "sleep() { :; }; cmd_pull() { :; }; probe_device_run_file() { :; }; "
                    "device_process_exited() { return 1; }; "
                    "probe_device_state() { printf 'READY|fixture\\n'; }; "
                    + wait + "\nwait_memory_qualification_sentinel \"$1\" 10 \"$2\"",
                    "test", run_id, directory,
                ],
                text=True,
                capture_output=True,
            )
        self.assertEqual(completed.returncode, 22, completed.stderr)
        self.assertIn("code=generation_failed completed=2/9", completed.stderr)
        self.assertEqual(completed.stdout, "")

    def run_device_wait(
        self, function: str, run_id: str, *, marker: str | None, exits: bool,
        predicted: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        """Run one iOS wait helper against stubbed devicectl calls. The marker
        appears on the second probe of it; `exits` makes the exact PID vanish."""
        ios = (REPO / "scripts" / "ios_device.sh").read_text(encoding="utf-8")
        # Up to the closing brace followed by a blank line: a waiter's embedded
        # Python may itself close a dict at column 0. The real poll-cadence
        # helper comes along; only devicectl and the clock are stubbed.
        wait = "".join(
            ios[start:ios.index("\n}\n\n", start) + 3]
            for start in (
                ios.index("device_poll_step() {\n"), ios.index(f"{function}() {{\n"),
            )
        )
        with tempfile.TemporaryDirectory() as directory:
            calls = Path(directory) / "calls.log"
            dest = Path(directory) / "dest"
            stubs = (
                "note() { printf '%s\\n' \"$*\" >&2; }; "
                "warn() { printf '%s\\n' \"$*\" >&2; }; "
                "die() { printf '%s\\n' \"$*\" >&2; exit 1; }; "
                "sleep() { :; }; "
                "probe_device_state() { printf 'READY|fixture\\n'; }; "
                "report_clone_consent_advice() { :; }; "
                f"cmd_pull() {{ printf 'full-pull\\n' >>'{calls}'; }}; "
                f"pull_device_diagnostics_run() {{ printf 'full-pull\\n' >>'{calls}'; }}; "
                f"probe_device_run_file() {{ printf 'probe %s\\n' \"$3\" >>'{calls}'; mkdir -p \"$2/$1\"; "
                f"  if [[ \"$3\" == '{marker or ''}' ]] && (( $(grep -c \"probe $3\" '{calls}') >= 2 )); then "
                "    printf '{}' >\"$2/$1/$3\"; fi; }; "
                "probe_device_sentinel() { probe_device_run_file \"$1\" \"$2\" device-diagnostics-done.json \"${3:-}\"; }; "
                f"device_process_exited() {{ printf 'exit-check %s %s\\n' \"$1\" \"$2\" >>'{calls}'; "
                f"  return {0 if exits else 1}; }}; "
            )
            completed = subprocess.run(
                [
                    "bash", "-c",
                    "set -euo pipefail; " + stubs + wait
                    + f"\n{function} \"$1\" 60 \"$2\" fixture-device 4242"
                    + (f" {predicted}" if predicted is not None else ""),
                    "test", run_id, str(dest),
                ],
                text=True,
                capture_output=True,
                timeout=60,
            )
            log = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
        return completed, log

    @staticmethod
    def poll_steps(*arguments: tuple[str, ...], environment: dict[str, str] | None = None) -> list[str]:
        ios = (REPO / "scripts" / "ios_device.sh").read_text(encoding="utf-8")
        helpers = "".join(
            ios[start:ios.index("\n}\n\n", start) + 3]
            for start in (
                ios.index("device_poll_step() {\n"), ios.index("predicted_take_seconds() {\n"),
            )
        )
        script = "set -euo pipefail; " + helpers + "".join(
            f"\n{' '.join(call)}" for call in arguments
        )
        completed = subprocess.run(
            ["bash", "-c", script], text=True, capture_output=True, check=True,
            env={"PATH": os.environ.get("PATH", ""), **(environment or {})},
        )
        return completed.stdout.split()

    def test_ios_poll_cadence_probes_at_the_predicted_end_then_every_few_seconds(self) -> None:
        # audit #87: no prediction keeps the 10 s timer; a prediction moves the
        # first probe to the take's predicted end and tightens the rest.
        self.assertEqual(
            self.poll_steps(
                ("device_poll_step", "0"), ("device_poll_step", "20"),
                ("device_poll_step", "0", "24"), ("device_poll_step", "24", "24"),
                ("device_poll_step", "0", "0"), ("device_poll_step", "3", "0"),
            ),
            ["10", "10", "24", "3", "0", "3"],
        )
        self.assertEqual(
            self.poll_steps(
                ("device_poll_step", "5", "24"),
                environment={"QVOICE_IOS_POLL_INTERVAL_SECONDS": "2"},
            ),
            ["2"],
        )
        # A lane's prediction is four fifths of its shortest take so far; none
        # before the first take ends.
        self.assertEqual(
            self.poll_steps(("predicted_take_seconds", "30"), ("predicted_take_seconds", "''")),
            ["24"],
        )

    def test_a_zero_prediction_probes_at_once_then_at_the_interval(self) -> None:
        # The profile's post-recording wait predicts 0: the first probe is
        # immediate and later ones advance the clock, so a missing sentinel
        # still reaches the timeout instead of probing forever.
        completed, calls = self.run_device_wait(
            "wait_device_diagnostics_sentinel", "ios-wait-zero", marker=None, exits=False,
            predicted="0",
        )
        # It fails (the stubbed die exits 1) without pulling a tree it never saw.
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(completed.stdout, "")
        self.assertNotIn("full-pull", calls)
        # One immediate probe, then one every 3 s up to 60 s.
        self.assertEqual(calls.count("probe device-diagnostics-done.json"), 21)

    def record_until_take_ends(
        self, *, tracer: str, predicted: str, sentinel_on_probe: int = 0,
    ) -> tuple[int, list[str], bool]:
        """Drive the iPhone profile's stop-at-take-end loop against a stand-in
        xctrace (a child process) and a stubbed sentinel probe and clock.

        `tracer` is what the stand-in does: `stop` saves the trace and exits 54
        on SIGINT (as xctrace does after a Stop), `unsaved` exits 54 on SIGINT
        without a trace, `limit` exits 0 on its own at once (the time limit),
        `fails` exits 54 on its own. The sentinel appears on probe
        `sentinel_on_probe` (never when 0). Returns the loop's status, the
        stubbed sleeps and probes in order, and whether the trace exists."""
        ios = (REPO / "scripts" / "ios_device.sh").read_text(encoding="utf-8")
        helpers = "".join(
            ios[start:ios.index("\n}\n\n", start) + 3]
            for start in (
                ios.index("device_poll_step() {\n"), ios.index("record_until_take_ends() {\n"),
            )
        )
        stand_in = (
            "import os, signal, sys, time\n"
            "trace, ready, behavior = sys.argv[1:4]\n"
            "def stop(*_):\n"
            "    if behavior == 'stop':\n"
            "        os.makedirs(trace, exist_ok=True)\n"
            "    sys.exit(54)\n"
            "signal.signal(signal.SIGINT, stop)\n"
            "open(ready, 'w').close()\n"
            "if behavior == 'limit':\n"
            "    sys.exit(0)\n"
            "if behavior == 'fails':\n"
            "    sys.exit(54)\n"
            "time.sleep(30)\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls, dest, trace, ready = (root / "calls.log", root / "dest", root / "run.trace",
                                         root / "ready")
            dest.mkdir()
            stubs = (
                "note() { printf '%s\\n' \"$*\" >&2; }; "
                f"sleep() {{ printf 'sleep %s\\n' \"$1\" >>'{calls}'; }}; "
                f"probe_device_sentinel() {{ printf 'probe\\n' >>'{calls}'; "
                f"  if (( {sentinel_on_probe} > 0 && $(grep -c '^probe$' '{calls}') >= {sentinel_on_probe} )); then "
                "    mkdir -p \"$2/$1\"; printf '{}' >\"$2/$1/device-diagnostics-done.json\"; fi; }; "
            )
            script = (
                "set -euo pipefail; " + stubs + helpers
                + f'\npython3 -c "$1" "{trace}" "{ready}" {tracer} &\n'
                "tracer_pid=$!\n"
                f"while [[ ! -e '{ready}' ]]; do command sleep 0.01; done\n"
                "status=0\n"
                f"record_until_take_ends \"$tracer_pid\" ios-profile-fixture '{dest}' fixture-device "
                f"'{trace}' {predicted} || status=$?\n"
                "printf '%s\\n' \"$status\"\n"
            )
            completed = subprocess.run(
                ["bash", "-c", script, "test", stand_in],
                text=True, capture_output=True, timeout=60,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            log = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
            return int(completed.stdout.strip()), log, trace.is_dir()

    def test_ios_profile_first_probes_its_take_at_the_predicted_end(self) -> None:
        # audit #87 for the profile: no devicectl copy during most of the
        # profiled take. The first probe waits the predicted 12 s, later ones
        # 3 s; the sentinel stops the recording with SIGINT, and the 54 xctrace
        # then exits with is a pass because this stop sent it and the trace saved.
        status, calls, saved = self.record_until_take_ends(
            tracer="stop", predicted="12", sentinel_on_probe=2,
        )
        self.assertEqual((status, saved), (0, True))
        self.assertEqual(calls, ["sleep 12", "probe", "sleep 3", "probe"])

    def test_ios_profile_accepts_54_only_after_its_own_stop_with_a_saved_trace(self) -> None:
        # A stop that saved no trace keeps xctrace's 54.
        status, _, saved = self.record_until_take_ends(
            tracer="unsaved", predicted="12", sentinel_on_probe=1,
        )
        self.assertEqual((status, saved), (54, False))
        # xctrace exiting 54 on its own is a failure, not a stop.
        status, _, _ = self.record_until_take_ends(tracer="fails", predicted="12")
        self.assertEqual(status, 54)
        # Reaching the time limit before the take ended is xctrace's own 0.
        status, _, _ = self.record_until_take_ends(tracer="limit", predicted="12")
        self.assertEqual(status, 0)

    def test_ios_waits_poll_only_their_markers_and_pull_the_tree_once(self) -> None:
        for function, marker in (
            ("wait_memory_qualification_sentinel", "memory-qualification-result.json"),
            ("wait_device_diagnostics_sentinel", "device-diagnostics-done.json"),
        ):
            with self.subTest(function=function):
                completed, calls = self.run_device_wait(
                    function, "ios-wait-fixture", marker=marker, exits=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(completed.stdout.strip().endswith(f"ios-wait-fixture/{marker}"))
                # No full copy of the growing tree while the run is measured
                # (audit #45, #56): the one full pull follows the marker.
                self.assertEqual(calls.count("full-pull"), 1, calls)
                self.assertEqual(calls[-1], "full-pull")
                self.assertTrue(
                    all(call.startswith(("probe ", "exit-check ")) for call in calls[:-1]), calls
                )

    def test_ios_waits_stop_with_a_typed_exit_when_the_process_vanishes(self) -> None:
        for function in (
            "wait_memory_qualification_sentinel",
            "wait_clone_conditioning_sentinel",
            "wait_device_diagnostics_sentinel",
        ):
            with self.subTest(function=function):
                completed, calls = self.run_device_wait(
                    function, "ios-wait-exit-fixture", marker=None, exits=True,
                )
                # A jetsam or crash writes no marker: stop now, not at the timeout.
                self.assertEqual(completed.returncode, 27, completed.stderr)
                self.assertEqual(completed.stdout, "")
                # The liveness check asks about the exact device and PID the wait was given.
                self.assertEqual(
                    [call for call in calls if call.startswith("exit-check ")],
                    ["exit-check fixture-device 4242"],
                )
                # The markers are probed once more before giving up, then the
                # partial tree is pulled once for diagnosis.
                self.assertEqual(calls.count("full-pull"), 1, calls)

    def test_local_only_field_report_is_exposed(self) -> None:
        ios = (REPO / "scripts" / "ios_device.sh").read_text(encoding="utf-8")
        report = shell_function(ios, "cmd_memory_field_report")
        self.assertIn('ios_memory_field_report.py" "$source"', report)
        for forbidden in ("resolve_device", "devicectl", "xctrace", "cmd_pull"):
            self.assertNotIn(forbidden, report)

    def test_memory_contract_surfaces_are_fingerprinted(self) -> None:
        history = (REPO / "scripts" / "benchmark_history.py").read_text(encoding="utf-8")
        for relative_path in (
            "benchmarks/schema-v2.json",
            "config/memory-qualification-policy.json",
            "scripts/benchmark_memory.py",
            "scripts/ios_memory_field_report.py",
        ):
            with self.subTest(relative_path=relative_path):
                path_parts = relative_path.split("/")
                history_expression = " / ".join(f'"{part}"' for part in path_parts)
                self.assertIn(history_expression, history)


class MacOSLanguageBenchContractTests(unittest.TestCase):
    def test_auto_language_hint_uses_nonempty_command_array(self) -> None:
        function = shell_function(
            (REPO / "scripts" / "macos_test.sh").read_text(encoding="utf-8"),
            "cmd_lang_bench",
        )
        self.assertIn("local -a generate_command=(", function)
        self.assertIn('--variant "$variant"', function)
        self.assertIn('generate_command+=(--language "$ui_hint")', function)
        self.assertIn('"${generate_command[@]}"', function)
        scoped = function.index("QWENVOICE_NATIVE_TELEMETRY_MODE=verbose")
        command = function.index('"${generate_command[@]}"', scoped)
        self.assertLess(scoped, command)
        self.assertNotIn("export QWENVOICE_NATIVE_TELEMETRY_MODE", function)
        self.assertNotIn('"${lang_args[@]}"', function)
        self.assertNotIn("ensure_mac_test_models --require", function)
        self.assertIn("require_mac_benchmark_models", function)
        self.assertIn('--evidence-manifest "$artifacts/benchmark-evidence.json"', function)

    def test_gate_records_only_after_final_crash_step(self) -> None:
        mac = (REPO / "scripts" / "macos_test.sh").read_text(encoding="utf-8")
        mac_gate = shell_function(mac, "cmd_gate")
        self.assertLess(mac_gate.index("crashes (GATE-FATAL"), mac_gate.index("record_benchmark_history"))
        self.assertIn("overall == 0 && gate_bench", mac_gate)

        ios = (REPO / "scripts" / "ios_device.sh").read_text(encoding="utf-8")
        ios_gate = shell_function(ios, "cmd_gate")
        self.assertLess(
            ios_gate.index('required_step_run "$step_ledger" crash-delta cmd_crashes'),
            ios_gate.index("record_benchmark_history"),
        )

    def test_profiles_use_read_only_models_and_frozen_evidence_summary(self) -> None:
        profile = shell_function(
            (REPO / "scripts" / "macos_test.sh").read_text(encoding="utf-8"),
            "cmd_profile",
        )
        self.assertNotIn("ensure_mac_test_models --require", profile)
        self.assertIn('require_profile_model "$mode" "$variant"', profile)
        self.assertIn("--defer-record", profile)
        self.assertIn('--evidence-manifest "$artifacts/benchmark-evidence.json"', profile)


if __name__ == "__main__":
    unittest.main()
