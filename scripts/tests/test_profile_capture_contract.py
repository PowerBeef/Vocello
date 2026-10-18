#!/usr/bin/env python3
"""Profile, memory-qualification, language-bench and gate wiring of the lane scripts, run.

The shipped cmd_profile, cmd_memory, cmd_lang_bench, cmd_gate, main and their helpers run
from the sourced scripts/macos_test.sh and scripts/ios_device.sh against recorded stand-ins
(scripts/tests/shell_stubs.py): Instruments, devicectl, the builds and every publisher are
shims, so each test reads the calls a lane made, in order, and never the lane's text.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import unittest

from shell_stubs import ROOT, LaneShell, option, quote

REPO = ROOT
RETENTION = "scripts/lib/profile_trace_retention.py"
PUBLISHER = "scripts/publish_benchmark_history.py"
SUMMARIZER = "scripts/summarize_generation_telemetry.py"
HISTORY = "scripts/benchmark_history.py"

LISTED = {
    "templates": ["Allocations", "CPU Profiler", "Time Profiler"],
    "instruments": ["Allocations", "CPU Profiler", "Time Profiler", "VM Tracker", "os_signpost"],
}

# The Mac's xctrace and clang: list LISTED, report startup after 0.2 s and record until
# the exact attached PID is gone (as `--attach` does), export a table of contents, build
# the suspended launcher.
MAC_XCRUN = r'''
case "${1:-} ${2:-}" in
  "xctrace list") cat "$QV_SANDBOX/xctrace-$3" ;;
  "xctrace record")
    attach="" output=""
    while (( $# )); do
      case "$1" in --attach) attach="$2"; shift 2 ;; --output) output="$2"; shift 2 ;; *) shift ;; esac
    done
    sleep 0.2
    qv_record tracer-started
    echo "Starting recording with the Instruments template."
    while kill -0 "$attach" 2>/dev/null; do sleep 0.02; done
    mkdir -p "$output"
    ;;
  "xctrace export")
    output=""
    while (( $# )); do case "$1" in --output) output="$2"; shift 2 ;; *) shift ;; esac; done
    printf '<trace-toc/>\n' >"$output"
    ;;
  clang*)
    output=""
    while (( $# )); do case "$1" in -o) output="$2"; shift 2 ;; *) shift ;; esac; done
    cp "$QV_SANDBOX/spawn-suspended" "$output"
    ;;
  *) exit 97 ;;
esac
'''

# The exact-PID launcher: writes its own PID, stops itself, and once continued becomes
# the profiled CLI (the real one posix_spawns it suspended; the PID contract is the same).
LAUNCHER = '''#!/bin/bash
. {record}
qv_record spawn-suspended "$@"
printf '%s\\n' "$$" >"$1"
shift
kill -STOP "$$"
exec "$@"
'''

# The profiled `vocello` CLI: records its arguments and telemetry environment.
VOCELLO = '''qv_record vocello-env "QWENVOICE_NATIVE_TELEMETRY_MODE=${{QWENVOICE_NATIVE_TELEMETRY_MODE:-}}" \\
  "QWENVOICE_DEBUG=${{QWENVOICE_DEBUG:-}}"
: >{started}
{behaviour}
'''

# The bench-results.json a successful `vocello bench` leaves in its --data-dir.
WRITES_BENCH_RESULTS = '''
data=""
for ((index = 1; index <= $#; index++)); do
  if [[ "${!index}" == --data-dir ]]; then next=$((index + 1)); data="${!next}"; fi
done
mkdir -p "$data/diagnostics"
printf '{}\\n' >"$data/diagnostics/bench-results.json"
'''

MAC_STUBS = '''
SCRIPT_DIR="$QV_SANDBOX/scripts"
qv_stub require_mac_benchmark_models
qv_stub require_mac_benchmark_clone_fixture
qv_stub ensure_mac_test_models
debug_models_dir() { printf '%s\\n' "$QV_SANDBOX/models"; }
'''

# After the profiled CLI starts, every poll of the profile's deadline loop advances the
# clock 15 s, so a hung target reaches its deadline in a fraction of a second.
FAST_CLOCK = '''
sleep() {
  if [[ -e "$QV_SANDBOX/target-started" ]]; then SECONDS=$((SECONDS + 15)); fi
  command sleep 0.02
}
'''

# devicectl and xctrace for the iPhone: the launch reports PID 4242; xctrace record is a
# Python stand-in (a background job ignores SIGINT, which only Python can re-arm).
IOS_XCRUN = r'''
case "${1:-} ${2:-} ${3:-} ${4:-}" in
  "devicectl device copy from") exit 0 ;;
  "devicectl device process launch")
    output=""
    while (( $# )); do case "$1" in --json-output) output="$2"; shift 2 ;; *) shift ;; esac; done
    printf '{"result": {"process": {"processIdentifier": 4242}}}\n' >"$output"
    exit 0
    ;;
  "devicectl device process resume"|"devicectl device process terminate") exit 0 ;;
esac
case "${1:-} ${2:-}" in
  "xctrace record") exec "$QV_REAL_PYTHON" "$QV_SANDBOX/xctrace_record.py" "$@" ;;
  "xctrace export")
    output=""
    while (( $# )); do case "$1" in --output) output="$2"; shift 2 ;; *) shift ;; esac; done
    printf '<trace-toc/>\n' >"$output"
    ;;
  *) exit 97 ;;
esac
'''

# `records` prints xctrace's startup line after 0.2 s and saves the trace on SIGINT (exit
# 54, as after a Stop); `silent` never reports startup.
IOS_TRACER = '''
import os, signal, sys, time
arguments = sys.argv[1:]
output = arguments[arguments.index("--output") + 1]
behaviour = open(os.path.join(os.environ["QV_SANDBOX"], "tracer"), encoding="utf-8").read().strip()

def stop(*_):
    os.makedirs(output, exist_ok=True)
    sys.exit(54)

signal.signal(signal.SIGINT, stop)
if behaviour == "records":
    time.sleep(0.2)
    with open(os.environ["QV_CALLS"], "a", encoding="utf-8") as log:
        log.write("tracer-started\\n")
    print("Starting recording with the CPU Profiler template.", flush=True)
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    time.sleep(0.02)
'''

IOS_STUBS = '''
qv_stub require_team
qv_stub cmd_build
qv_stub cmd_install
resolve_device() { printf 'fixture-device\\n'; }
resolve_xctrace_device() { qv_record resolve_xctrace_device "$@"; printf 'fixture-udid\\n'; }
sleep() { qv_record sleep "$@"; command sleep 0.01; }
probe_device_sentinel() {
  qv_record probe_device_sentinel "$@"
  mkdir -p "$2/$1"
  printf '{"status": "ok"}\\n' >"$2/$1/device-diagnostics-done.json"
}
wait_device_diagnostics_sentinel() {
  qv_record wait_device_diagnostics_sentinel "$@"
  printf '%s\\n' "$3/$1/device-diagnostics-done.json"
}
'''


def nth_preflight_fails(n: int) -> str:
    """A retention stand-in whose `n`-th disk preflight fails."""
    return (
        'if [[ "$1" == preflight ]]; then\n'
        f'  count="$(grep -c "^{RETENTION}"$\'\\x1f\'"preflight" "$QV_CALLS")"\n'
        f'  (( count < {n} ))\n'
        "fi\n"
    )


def fails_on(subcommand: str) -> str:
    """A helper stand-in that fails `subcommand` and passes everything else."""
    return f'[[ "${{1:-}}" != {quote(subcommand)} ]]'


def mac_profile(test: unittest.TestCase, *arguments: str, env: dict[str, str] | None = None,
                vocello: str = "exit 0", listed: dict[str, list[str]] | None = None,
                helpers: dict[str, str] | None = None, launcher_installed: bool = True,
                body: str = "") -> tuple[subprocess.CompletedProcess[str], LaneShell]:
    """The real macOS cmd_profile over stand-ins."""
    shell = LaneShell(test, "macos_test.sh")
    shell.tool("xcrun", MAC_XCRUN)
    shell.tool("xctrace", "exit 0")
    for listing, names in (listed or LISTED).items():
        shell.file(f"xctrace-{listing}", "\n".join([f"== Standard {listing.title()} ==", *names]) + "\n")
    shell.file("scripts/lib/spawn_suspended.c", "/* fixture */\n")
    launcher = shell.file("spawn-suspended", LAUNCHER.format(record=quote(shell.record)))
    launcher.chmod(0o755)
    shell.executable("scripts/build.sh")
    shell.executable("build/vocello", VOCELLO.format(
        started=quote(shell.path / "target-started"), behaviour=vocello))
    for relative in (RETENTION, PUBLISHER, SUMMARIZER, HISTORY):
        shell.helper(relative, "exit 0")
    for relative, behaviour in (helpers or {}).items():
        shell.helper(relative, behaviour)
    install = (
        'mkdir -p "$QVOICE_SCRATCH_TRANSIENT/tools"\n'
        'cp "$QV_SANDBOX/spawn-suspended" "$QVOICE_SCRATCH_TRANSIENT/tools/spawn-suspended"\n'
    ) if launcher_installed else ""
    completed = shell.run(MAC_STUBS + install + body + f"cmd_profile {shlex.join(arguments)}\n",
                          env=env, timeout=60)
    return completed, shell


def ios_profile(test: unittest.TestCase, *arguments: str, env: dict[str, str] | None = None,
                tracer: str = "records", helpers: dict[str, str] | None = None
                ) -> tuple[subprocess.CompletedProcess[str], LaneShell]:
    """The real iPhone cmd_profile over stand-ins for devicectl, xctrace and the phone."""
    shell = LaneShell(test, "ios_device.sh")
    shell.tool("xcrun", IOS_XCRUN)
    shell.tool("xctrace", "exit 0")
    shell.file("xctrace_record.py", IOS_TRACER)
    shell.file("tracer", tracer)
    for relative in (RETENTION, PUBLISHER, SUMMARIZER, HISTORY):
        shell.helper(relative, "exit 0")
    for relative, behaviour in (helpers or {}).items():
        shell.helper(relative, behaviour)
    completed = shell.run(IOS_STUBS + f"cmd_profile {shlex.join(arguments)}\n", env=env, timeout=60)
    return completed, shell


def only_profile(shell: LaneShell, platform: str) -> Path:
    [artifacts] = list((shell.build / "artifacts" / platform / "profiles").iterdir())
    return artifacts


class MacProfileTests(unittest.TestCase):
    def test_history_publishes_before_retention_and_disk_is_checked_around_the_build(self) -> None:
        completed, shell = mac_profile(self, "--allow-dirty")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        calls = shell.calls()
        preflights = [i for i, call in enumerate(calls) if call[:2] == [RETENTION, "preflight"]]
        self.assertEqual(len(preflights), 2, "disk is checked before the build and right before launch")
        build = shell.index("scripts/build.sh", "cli-optimized")
        launch = shell.index("spawn-suspended")
        self.assertLess(preflights[0], build)
        self.assertLess(build, preflights[1])
        self.assertLess(preflights[1], launch)
        self.assertLess(preflights[1], shell.index("xcrun", "xctrace", "record"))
        self.assertLess(shell.index(HISTORY, "record"), shell.index(RETENTION, "finalize-success"))
        artifacts = only_profile(shell, "macos")
        [finalize] = shell.calls_to(RETENTION, "finalize-success")
        self.assertEqual(option(finalize, "--platform"), "macos")
        self.assertEqual(option(finalize, "--kind"), "cpu")
        self.assertEqual(option(finalize, "--policy"), "summaryOnly")
        self.assertEqual(option(finalize, "--summary-artifact"), str(artifacts / "profile-summary.json"))
        self.assertEqual(
            option(finalize, "--history-record"),
            str(REPO / "benchmarks/runs/instrument-profile" / f"{artifacts.name}.json"),
        )
        [published] = shell.calls_to(PUBLISHER, "profile")
        self.assertEqual(option(published, "--retention-policy"), "summaryOnly")
        self.assertEqual(option(published, "--summary-artifact"), str(artifacts / "profile-summary.json"))
        self.assertEqual(shell.calls_to(RETENTION, "mark-failure"), [])

    def test_retention_policy_follows_keep_trace_and_kind(self) -> None:
        for arguments, policy in ((("--keep-trace",), "keptExplicitly"), (("--kind", "memory"), "keptByDefault")):
            with self.subTest(arguments=arguments):
                completed, shell = mac_profile(self, "--allow-dirty", *arguments)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                [published] = shell.calls_to(PUBLISHER, "profile")
                self.assertEqual(option(published, "--retention-policy"), policy)
                [finalize] = shell.calls_to(RETENTION, "finalize-success")
                self.assertEqual(option(finalize, "--policy"), policy)

    def test_a_failed_validation_marks_the_failed_trace_and_publishes_nothing(self) -> None:
        completed, shell = mac_profile(self, "--allow-dirty", helpers={PUBLISHER: fails_on("profile")})
        self.assertEqual(completed.returncode, 1)
        self.assertIn("evidence validation failed", completed.stderr)
        [marked] = shell.calls_to(RETENTION, "mark-failure")
        self.assertEqual(option(marked, "--platform"), "macos")
        self.assertEqual(option(marked, "--kind"), "cpu")
        self.assertEqual(option(marked, "--phase"), "evidence-validation")
        self.assertEqual(option(marked, "--exit-code"), "1")
        self.assertEqual(shell.calls_to(HISTORY), [])
        self.assertEqual(shell.calls_to(RETENTION, "finalize-success"), [])

    def test_a_full_disk_after_the_build_stops_before_the_target_launches(self) -> None:
        completed, shell = mac_profile(self, "--allow-dirty", helpers={RETENTION: nth_preflight_fails(2)})
        self.assertEqual(completed.returncode, 1)
        self.assertNotIn("spawn-suspended", shell.names())
        self.assertNotIn("build/vocello", shell.names())
        [marked] = shell.calls_to(RETENTION, "mark-failure")
        self.assertEqual(option(marked, "--phase"), "final-disk-preflight")

    def test_a_failure_after_publication_does_not_mark_the_published_trace_failed(self) -> None:
        completed, shell = mac_profile(self, "--allow-dirty", helpers={RETENTION: fails_on("finalize-success")})
        self.assertEqual(completed.returncode, 1)
        self.assertIn("raw-trace retention finalization failed", completed.stderr)
        self.assertEqual(len(shell.calls_to(HISTORY, "record")), 1)
        self.assertEqual(shell.calls_to(RETENTION, "mark-failure"), [])

    def test_xctrace_attaches_to_the_exact_suspended_pid_before_the_cli_runs(self) -> None:
        completed, shell = mac_profile(self, "--allow-dirty")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        artifacts = only_profile(shell, "macos")
        pid = (artifacts / "target.pid").read_text(encoding="utf-8").strip()
        [record] = shell.calls_to("xcrun", "xctrace", "record")
        self.assertEqual(option(record, "--attach"), pid)
        self.assertIn("--no-prompt", record)
        self.assertNotIn("--launch", record)
        self.assertEqual(option(record, "--time-limit"), "90s")
        self.assertEqual(option(record, "--output"), str(artifacts / f"{artifacts.name}.trace"))
        [launched] = shell.calls_to("spawn-suspended")
        self.assertEqual(launched[:3], [str(artifacts / "target.pid"), str(shell.build / "vocello"), "bench"])
        # The CLI only runs once the tracer reports recording: the launcher stays stopped until then.
        self.assertLess(shell.index("tracer-started"), shell.index("build/vocello"))
        [bench] = shell.calls_to("build/vocello")
        for name, value in (("--modes", "custom"), ("--variants", "speed"), ("--lengths", "medium"),
                            ("--warm", "3"), ("--label", "instrument-cpu-profile"),
                            ("--data-dir", str(artifacts / "runtime"))):
            self.assertEqual(option(bench, name), value)
        self.assertIn("--no-summary", bench)
        self.assertEqual(shell.calls_to("vocello-env"),
                         [["QWENVOICE_NATIVE_TELEMETRY_MODE=verbose", "QWENVOICE_DEBUG=1"]])
        [published] = shell.calls_to(PUBLISHER, "profile")
        self.assertEqual(option(published, "--target-pid"), pid)
        self.assertEqual(option(published, "--target-process"), "vocello")

    def test_the_suspended_launcher_is_built_from_its_source_only_when_missing(self) -> None:
        completed, shell = mac_profile(self, "--allow-dirty", launcher_installed=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        [launcher] = list(shell.build.rglob("spawn-suspended"))
        [clang] = shell.calls_to("xcrun", "clang")
        self.assertEqual(clang[1:], ["-O2", "-Wall", "-Wextra",
                                     str(shell.path / "scripts/lib/spawn_suspended.c"), "-o", str(launcher)])
        completed, shell = mac_profile(self, "--allow-dirty")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(shell.calls_to("xcrun", "clang"), [])

    def test_a_hung_target_stops_at_duration_plus_grace_and_is_killed(self) -> None:
        for arguments, bound in ((("--allow-dirty",), "90s + 30s grace"),
                                 (("--allow-dirty", "--kind", "memory"), "180s + 60s grace")):
            with self.subTest(arguments=arguments):
                completed, shell = mac_profile(self, *arguments, vocello="exec sleep 30", body=FAST_CLOCK)
                self.assertEqual(completed.returncode, 1)
                artifacts = only_profile(shell, "macos")
                self.assertIn(f"profile target/tracer exceeded {bound}; artifacts preserved in {artifacts}",
                              completed.stderr)
                [marked] = shell.calls_to(RETENTION, "mark-failure")
                self.assertEqual(option(marked, "--phase"), "trace-recording")
                pid = int((artifacts / "target.pid").read_text(encoding="utf-8"))
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(0.05)
                else:
                    self.fail(f"the hung profile target {pid} outlived its profile")

    def test_profiles_require_installed_models_and_freeze_their_evidence_summary(self) -> None:
        completed, shell = mac_profile(self, "--allow-dirty")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("ensure_mac_test_models", shell.names(), "a profile never installs models")
        self.assertEqual(shell.calls_to("require_mac_benchmark_models"), [["pro_custom_speed"]])
        self.assertNotIn("require_mac_benchmark_clone_fixture", shell.names())
        artifacts = only_profile(shell, "macos")
        [published] = shell.calls_to(PUBLISHER, "profile")
        self.assertIn("--defer-record", published)
        [summary] = shell.calls_to(SUMMARIZER)
        self.assertEqual(option(summary, "--evidence-manifest"), str(artifacts / "benchmark-evidence.json"))
        self.assertIn("--engine-only", summary)
        completed, shell = mac_profile(self, "--allow-dirty", "clone:speed:Profile a clone.")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(shell.calls_to("require_mac_benchmark_models"), [["pro_clone_speed"]])
        self.assertEqual(shell.calls_to("require_mac_benchmark_clone_fixture"), [[]])

    def test_a_dirty_tree_is_refused_before_anything_runs(self) -> None:
        shell_git = 'if [[ " $* " == *" status "* ]]; then echo " M scripts/changed.sh"; fi'
        shell = LaneShell(self, "macos_test.sh")
        shell.tool("git", shell_git)
        completed = shell.run(MAC_STUBS + "cmd_profile\n")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("profile needs a clean tree", completed.stderr)
        self.assertEqual(shell.names(), ["git"])

    def test_an_unknown_kind_is_refused_before_anything_runs(self) -> None:
        completed, shell = mac_profile(self, "--allow-dirty", "--kind", "gpu")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("profile kind must be cpu, memory or witness", completed.stderr)
        self.assertEqual(shell.calls(), [])

    def test_memory_profile_records_allocations_and_vm_tracker_beside_cpu_and_signposts(self) -> None:
        completed, shell = mac_profile(self, "--allow-dirty", "--kind", "memory")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        artifacts = only_profile(shell, "macos")
        [record] = shell.calls_to("xcrun", "xctrace", "record")
        self.assertEqual(record[2:8], ["--template", "Allocations", "--instrument", "Time Profiler",
                                       "--instrument", "os_signpost"])
        self.assertEqual(option(record, "--time-limit"), "180s")
        [bench] = shell.calls_to("build/vocello")
        self.assertEqual((option(bench, "--lengths"), option(bench, "--warm")), ("long", "0"))
        [published] = shell.calls_to(PUBLISHER, "profile")
        self.assertEqual(option(published, "--template"), "Time Profiler + Allocations + VM Tracker + os_signpost")
        self.assertEqual(option(published, "--profile-kind"), "memory")
        self.assertEqual(option(published, "--duration"), "180")
        trace, toc = artifacts / f"{artifacts.name}.trace", artifacts / "trace-toc.xml"
        self.assertEqual(shell.calls_to("xcrun", "xctrace", "export"),
                         [["xctrace", "export", "--input", str(trace), "--toc", "--output", str(toc)]])
        completed, shell = mac_profile(self, "--allow-dirty", "--kind", "memory",
                                       env={"QVOICE_MAC_MEMORY_PROFILE_DURATION": "7"})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        [record] = shell.calls_to("xcrun", "xctrace", "record")
        self.assertEqual(option(record, "--time-limit"), "7s")

    def test_an_unlisted_instrument_is_refused_before_building(self) -> None:
        listed = {**LISTED, "instruments": [name for name in LISTED["instruments"] if name != "Time Profiler"]}
        completed, shell = mac_profile(self, "--allow-dirty", listed=listed)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("profile needs the Instruments instrument 'Time Profiler'", completed.stderr)
        self.assertNotIn("scripts/build.sh", shell.names())
        self.assertNotIn("spawn-suspended", shell.names())


class ProfileInstrumentTests(unittest.TestCase):
    def profile_instruments(self, script: str, kind: str) -> tuple[list[str], str]:
        """What a profile kind hands xctrace record, and the label it publishes."""
        shell = LaneShell(self, script)
        completed = shell.run(
            f"profile_instrument_args {quote(kind)}\n"
            'printf \'%s\\n\' "$PROFILE_CAPTURE_INSTRUMENTS" "${PROFILE_INSTRUMENT_ARGS[@]}"\n'
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        label, *arguments = completed.stdout.splitlines()
        return arguments, label

    def test_profile_kinds_pass_their_instruments_to_xctrace(self) -> None:
        def cpu(sampler: str) -> list[str]:
            return ["--instrument", sampler, "--instrument", "os_signpost"]

        # A memory profile records Allocations and VM Tracker only through Apple's
        # Allocations template, whose VM Tracker takes no automatic snapshots;
        # standalone instruments would (audit #51, d52340a0).
        def memory(sampler: str) -> list[str]:
            return ["--template", "Allocations", "--instrument", sampler, "--instrument", "os_signpost"]

        cases = {
            # The Mac samples with Time Profiler since 2026-09-26: CPU Profiler's
            # hardware counters need root on macOS 27 (measurement version 4).
            ("macos_test.sh", "cpu"): (cpu("Time Profiler"), "Time Profiler + os_signpost"),
            ("macos_test.sh", "memory"): (
                memory("Time Profiler"), "Time Profiler + Allocations + VM Tracker + os_signpost",
            ),
            # The witness records signposts alone, no sampler (audit #50).
            ("macos_test.sh", "witness"): (["--instrument", "os_signpost"], "os_signpost"),
            ("ios_device.sh", "cpu"): (cpu("CPU Profiler"), "CPU Profiler + os_signpost"),
            ("ios_device.sh", "memory"): (
                memory("CPU Profiler"), "CPU Profiler + Allocations + VM Tracker + os_signpost",
            ),
        }
        for (script, kind), expected in cases.items():
            with self.subTest(script=script, kind=kind):
                self.assertEqual(self.profile_instruments(script, kind), expected)

    def test_the_instrument_preflight_refuses_whatever_xctrace_does_not_list(self) -> None:
        def preflight(kind: str, *, drop: str | None = None) -> int:
            shell = LaneShell(self, "macos_test.sh")
            for listing, names in LISTED.items():
                # The shape `xcrun xctrace list` prints (Xcode 27): a header, one name per line.
                shell.file(f"xctrace-{listing}",
                           "\n".join([f"== Standard {listing.title()} ==", *(n for n in names if n != drop)]) + "\n")
            shell.tool("xcrun", '[[ "$1 $2" == "xctrace list" ]] || exit 64\ncat "$QV_SANDBOX/xctrace-$3"')
            return shell.run(f"profile_instrument_args {quote(kind)}\nrequire_profile_instruments\n").returncode

        for kind in ("cpu", "memory", "witness"):
            with self.subTest(kind=kind):
                self.assertEqual(preflight(kind), 0)
        for kind, missing in (("cpu", "Time Profiler"), ("memory", "Allocations"), ("witness", "os_signpost")):
            with self.subTest(kind=kind, missing=missing):
                self.assertNotEqual(preflight(kind, drop=missing), 0)


class IOSProfileTests(unittest.TestCase):
    def test_history_publishes_before_retention_and_disk_is_checked_around_build_and_install(self) -> None:
        completed, shell = ios_profile(self)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        calls = shell.calls()
        preflights = [i for i, call in enumerate(calls) if call[:2] == [RETENTION, "preflight"]]
        self.assertEqual(len(preflights), 2)
        launch = shell.index("xcrun", "devicectl", "device", "process", "launch")
        self.assertLess(preflights[0], shell.index("cmd_build"))
        self.assertLess(shell.index("cmd_install"), preflights[1])
        self.assertLess(preflights[1], launch)
        self.assertLess(shell.index(HISTORY, "record"), shell.index(RETENTION, "finalize-success"))
        artifacts = only_profile(shell, "ios")
        [finalize] = shell.calls_to(RETENTION, "finalize-success")
        self.assertEqual((option(finalize, "--platform"), option(finalize, "--kind"), option(finalize, "--policy")),
                         ("ios", "cpu", "summaryOnly"))
        self.assertEqual(option(finalize, "--summary-artifact"), str(artifacts / "profile-summary.json"))
        # The exact profiled process is terminated once the profile is done.
        self.assertEqual(shell.calls_to("xcrun", "devicectl", "device", "process", "terminate"),
                         [["devicectl", "device", "process", "terminate", "--device", "fixture-device",
                           "--pid", "4242", "--quiet"]])
        self.assertLess(shell.index(RETENTION, "finalize-success"),
                        shell.index("xcrun", "devicectl", "device", "process", "terminate"))
        self.assertEqual(completed.stdout.strip(), str(artifacts / "profile-summary.json"))

    def test_retention_policy_follows_keep_trace_and_kind(self) -> None:
        for arguments, policy in ((("--keep-trace",), "keptExplicitly"), (("--kind", "memory"), "keptByDefault")):
            with self.subTest(arguments=arguments):
                completed, shell = ios_profile(self, *arguments)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                [published] = shell.calls_to(PUBLISHER, "ios-profile")
                self.assertEqual(option(published, "--retention-policy"), policy)
                [finalize] = shell.calls_to(RETENTION, "finalize-success")
                self.assertEqual(option(finalize, "--policy"), policy)

    def test_a_failed_validation_marks_the_trace_and_terminates_the_exact_target(self) -> None:
        completed, shell = ios_profile(self, helpers={PUBLISHER: fails_on("ios-profile")})
        self.assertEqual(completed.returncode, 1)
        [marked] = shell.calls_to(RETENTION, "mark-failure")
        self.assertEqual((option(marked, "--platform"), option(marked, "--phase")), ("ios", "evidence-validation"))
        self.assertEqual(shell.calls_to(HISTORY), [])
        self.assertEqual(shell.calls_to(RETENTION, "finalize-success"), [])
        self.assertEqual(len(shell.calls_to("xcrun", "devicectl", "device", "process", "terminate")), 1)

    def test_a_full_disk_after_build_and_install_stops_before_the_target_launches(self) -> None:
        completed, shell = ios_profile(self, helpers={RETENTION: nth_preflight_fails(2)})
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(shell.calls_to("xcrun", "devicectl", "device", "process", "launch"), [])
        [marked] = shell.calls_to(RETENTION, "mark-failure")
        self.assertEqual((option(marked, "--platform"), option(marked, "--phase")), ("ios", "final-disk-preflight"))

    def test_a_failure_after_publication_does_not_mark_the_published_trace_failed(self) -> None:
        completed, shell = ios_profile(self, helpers={RETENTION: fails_on("finalize-success")})
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(len(shell.calls_to(HISTORY, "record")), 1)
        self.assertEqual(shell.calls_to(RETENTION, "mark-failure"), [])
        # The exact target is still terminated on the way out.
        self.assertEqual(len(shell.calls_to("xcrun", "devicectl", "device", "process", "terminate")), 1)

    def test_the_target_resumes_only_after_xctrace_attached_to_its_exact_pid(self) -> None:
        completed, shell = ios_profile(self)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        [launch] = shell.calls_to("xcrun", "devicectl", "device", "process", "launch")
        self.assertIn("--start-stopped", launch)
        self.assertIn("--terminate-existing", launch)
        self.assertEqual(option(launch, "--device"), "fixture-device")
        self.assertEqual(launch[-1], "com.patricedery.vocello")
        environment = json.loads(option(launch, "-e"))
        self.assertEqual(environment["QWENVOICE_NATIVE_TELEMETRY_MODE"], "verbose")
        self.assertEqual(environment["QVOICE_IOS_DEVICE_DIAGNOSTICS_SPEC"], "custom:speed:Profile device diagnostics.")
        [record] = shell.calls_to("xcrun", "xctrace", "record")
        self.assertEqual(option(record, "--device"), "fixture-udid")
        self.assertEqual(option(record, "--attach"), "4242")
        self.assertIn("--no-prompt", record)
        self.assertNotIn("--notify-tracing-started", record)
        self.assertEqual(option(record, "--time-limit"), "90s")
        resume = shell.index("xcrun", "devicectl", "device", "process", "resume")
        self.assertLess(shell.index("tracer-started"), resume)
        self.assertEqual(shell.calls()[resume][1:],
                         ["devicectl", "device", "process", "resume", "--device", "fixture-device", "--pid", "4242"])
        # No fixed wait anywhere: the first probe after the resume waits for the take's
        # predicted end (default 10 s), the tracer-start loop polls every 0.1 s.
        sleeps = [call[1] for call in shell.calls()[resume:] if call[0] == "sleep"]
        self.assertEqual(sleeps[0], "10")
        self.assertLessEqual({call[0] for call in shell.calls_to("sleep")}, {"0.1", "10", "3"})
        [published] = shell.calls_to(PUBLISHER, "ios-profile")
        self.assertEqual(option(published, "--target-pid"), "4242")
        completed, shell = ios_profile(self, env={"QVOICE_IOS_PROFILE_PREDICTED_SECONDS": "4"})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        resume = shell.index("xcrun", "devicectl", "device", "process", "resume")
        self.assertEqual([call[1] for call in shell.calls()[resume:] if call[0] == "sleep"][0], "4")

    def test_a_tracer_that_never_starts_stops_the_profile_before_the_target_resumes(self) -> None:
        completed, shell = ios_profile(self, tracer="silent", env={"QVOICE_IOS_PROFILE_START_TIMEOUT": "1"})
        self.assertEqual(completed.returncode, 1)
        self.assertIn("xctrace did not report tracing startup within 1s", completed.stderr)
        self.assertEqual(shell.calls_to("xcrun", "devicectl", "device", "process", "resume"), [])
        self.assertEqual(len(shell.calls_to("xcrun", "devicectl", "device", "process", "terminate")), 1)
        [marked] = shell.calls_to(RETENTION, "mark-failure")
        self.assertEqual(option(marked, "--phase"), "trace-recording")

    def test_memory_profile_records_allocations_and_vm_tracker_beside_cpu_and_signposts(self) -> None:
        completed, shell = ios_profile(self, "--kind", "memory", env={"QVOICE_IOS_MEMORY_PROFILE_DURATION": "45"})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        artifacts = only_profile(shell, "ios")
        [record] = shell.calls_to("xcrun", "xctrace", "record")
        self.assertEqual(record[4:10], ["--template", "Allocations", "--instrument", "CPU Profiler",
                                        "--instrument", "os_signpost"])
        self.assertEqual(option(record, "--time-limit"), "45s")
        [published] = shell.calls_to(PUBLISHER, "ios-profile")
        self.assertEqual(option(published, "--template"), "CPU Profiler + Allocations + VM Tracker + os_signpost")
        self.assertEqual(option(published, "--profile-kind"), "memory")
        trace, toc = artifacts / f"{artifacts.name}.trace", artifacts / "trace-toc.xml"
        self.assertEqual(shell.calls_to("xcrun", "xctrace", "export"),
                         [["xctrace", "export", "--input", str(trace), "--toc", "--output", str(toc)]])

    def test_an_unknown_kind_is_refused_before_anything_runs(self) -> None:
        completed, shell = ios_profile(self, "--kind", "witness")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("profile kind must be cpu or memory", completed.stderr)
        self.assertEqual(shell.calls(), [])


class MemoryQualificationTests(unittest.TestCase):
    """The retained-memory qualification is its own lane, never an Instruments trace."""

    def test_main_dispatches_memory_after_the_storage_and_quiet_host_preflights(self) -> None:
        for script, host in (("macos_test.sh", "macos-memory"), ("ios_device.sh", "ios-memory")):
            with self.subTest(script=script):
                shell = LaneShell(self, script)
                stubs = "qv_stub require_build_free_space\nqv_stub require_quiet_host\nqv_stub cmd_memory\n"
                completed = shell.run(stubs + "main memory --label fixture-memory\n")
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(shell.calls(), [
                    ["require_build_free_space", "memory-qualification"],
                    ["require_quiet_host", host],
                    ["cmd_memory", "--label", "fixture-memory"],
                ])
                shell = LaneShell(self, script)
                completed = shell.run(stubs + "qv_stub require_build_free_space 1\nmain memory\n")
                self.assertEqual(completed.returncode, 1)
                self.assertNotIn("cmd_memory", shell.names())

    def mac_memory(self, **helpers: str) -> tuple[subprocess.CompletedProcess[str], LaneShell]:
        shell = LaneShell(self, "macos_test.sh")
        shell.executable("scripts/build.sh")
        shell.executable("build/vocello", VOCELLO.format(started=quote(shell.path / "target-started"),
                                                          behaviour=WRITES_BENCH_RESULTS))
        for relative in (PUBLISHER, SUMMARIZER, HISTORY, "scripts/check_marking_peak_equality.py"):
            shell.helper(relative, helpers.get(relative, "exit 0"))
        completed = shell.run(MAC_STUBS + "cmd_memory --label fixture-memory\n")
        return completed, shell

    def test_mac_memory_runs_one_seeded_retained_sequence_and_publishes_after_its_checks(self) -> None:
        completed, shell = self.mac_memory()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        [bench] = shell.calls_to("build/vocello")
        for name, value in (("--modes", "custom,design,clone"), ("--variants", "speed"), ("--lengths", "medium"),
                            ("--warm", "3"), ("--seed", "19790615"), ("--voice", "A_warm_elderly_woman"),
                            ("--memory-qualification", "retained-memory-v1"), ("--label", "fixture-memory")):
            self.assertEqual(option(bench, name), value)
        self.assertEqual(shell.calls_to("vocello-env"),
                         [["QWENVOICE_NATIVE_TELEMETRY_MODE=verbose", "QWENVOICE_DEBUG=1"]])
        # The voices directory is the run's own; only the fixture files are links into the debug store.
        voices = Path(option(bench, "--data-dir")) / "voices"
        self.assertTrue(voices.is_dir() and not voices.is_symlink())
        debug_voices = shell.home / "Library/Application Support/QwenVoice-Debug/voices"
        self.assertEqual({entry.name: os.readlink(entry) for entry in voices.iterdir()}, {
            "A_warm_elderly_woman.wav": str(debug_voices / "A_warm_elderly_woman.wav"),
            "A_warm_elderly_woman.txt": str(debug_voices / "A_warm_elderly_woman.txt"),
        })
        [published] = shell.calls_to(PUBLISHER, "memory-qualification")
        self.assertEqual(option(published, "--platform"), "macos")
        self.assertIn("--defer-record", published)
        order = [shell.index("build/vocello"), shell.index(PUBLISHER, "memory-qualification"),
                 shell.index(SUMMARIZER), shell.index("scripts/check_marking_peak_equality.py"),
                 shell.index(HISTORY, "record")]
        self.assertEqual(order, sorted(order))
        self.assertNotIn("xcrun", shell.names(), "memory qualification records no Instruments trace")

    def test_mac_memory_publishes_nothing_when_marking_raised_the_peak(self) -> None:
        completed, shell = self.mac_memory(**{"scripts/check_marking_peak_equality.py": "exit 1"})
        self.assertEqual(completed.returncode, 1)
        self.assertIn("marking peak-equality assertion failed", completed.stderr)
        self.assertEqual(shell.calls_to(HISTORY), [])

    def ios_memory(self, sentinel: dict | None, *, wait_status: int = 0) -> tuple[subprocess.CompletedProcess[str], LaneShell]:
        shell = LaneShell(self, "ios_device.sh")
        shell.tool("xcrun", IOS_XCRUN)
        for relative in (PUBLISHER, SUMMARIZER, HISTORY):
            shell.helper(relative, "exit 0")
        shell.file("sentinel.json", json.dumps(sentinel or {}))
        body = (
            "qv_stub require_team\nqv_stub cmd_build\nqv_stub cmd_install\nqv_stub capture_benchmark_source\n"
            "qv_stub snapshot_device_process_exit_baseline\n"
            "describe_device_process_exit() { printf 'fixture exit'; }\n"
            "resolve_device() { printf 'fixture-device\\n'; }\n"
            "wait_memory_qualification_sentinel() {\n"
            '  qv_record wait_memory_qualification_sentinel "$@"\n'
            f"  (( {wait_status} == 0 )) || return {wait_status}\n"
            '  mkdir -p "$3/$1"; cp "$QV_SANDBOX/sentinel.json" "$3/$1/memory-qualification-result.json"\n'
            '  printf \'%s\\n\' "$3/$1/memory-qualification-result.json"\n'
            "}\n"
            "cmd_memory --voice-id fixture-voice --label fixture-memory\n"
        )
        return shell.run(body), shell

    @staticmethod
    def nine_takes() -> dict:
        cells = [f"{mode}/speed/medium/retained#{repetition}"
                 for mode in ("custom", "design", "clone") for repetition in range(3)]
        return {"status": "pass", "takes": [
            {"mode": cell.split("/")[0], "takeIndex": index, "cell": cell}
            for index, cell in enumerate(cells, start=1)
        ]}

    def test_ios_memory_launches_one_process_and_publishes_only_its_nine_take_pass(self) -> None:
        completed, shell = self.ios_memory(self.nine_takes())
        self.assertEqual(completed.returncode, 0, completed.stderr)
        [launch] = shell.calls_to("xcrun", "devicectl", "device", "process", "launch")
        environment = json.loads(option(launch, "-e"))
        plan = json.loads(environment["QVOICE_IOS_DEVICE_MEMORY_QUALIFICATION_SPEC"])
        self.assertEqual((plan["policyID"], plan["modes"], plan["repetitionsPerMode"]),
                         ("retained-memory-v1", ["custom", "design", "clone"], 3))
        self.assertEqual(environment["QVOICE_IOS_DEVICE_DIAGNOSTICS_CLONE_VOICE_ID"], "fixture-voice")
        self.assertEqual(environment["QWENVOICE_NATIVE_TELEMETRY_MODE"], "verbose")
        [wait] = shell.calls_to("wait_memory_qualification_sentinel")
        self.assertEqual(wait[1:2] + wait[3:], ["900", "fixture-device", "4242"])
        [published] = shell.calls_to(PUBLISHER, "memory-qualification")
        self.assertEqual(option(published, "--platform"), "ios")
        self.assertLess(shell.index("wait_memory_qualification_sentinel"), shell.index(PUBLISHER))
        self.assertEqual(shell.calls_to("xcrun", "devicectl", "device", "process", "terminate"),
                         [["devicectl", "device", "process", "terminate", "--device", "fixture-device",
                           "--pid", "4242", "--quiet"]])
        self.assertEqual(shell.calls_to("xcrun", "xctrace"), [], "memory qualification records no trace")

    def test_ios_memory_publishes_nothing_without_a_complete_nine_take_pass(self) -> None:
        eight = self.nine_takes()
        eight["takes"].pop()
        reordered = self.nine_takes()
        reordered["takes"][0]["cell"], reordered["takes"][1]["cell"] = (reordered["takes"][1]["cell"],
                                                                        reordered["takes"][0]["cell"])
        for name, sentinel, status, message in (
            ("eight takes", eight, 0, "not a successful nine-take result"),
            ("cells out of order", reordered, 0, "not a successful nine-take result"),
            ("failure marker", None, 22, "no history was published"),
            ("process exited", None, 27, "exited before its terminal marker"),
        ):
            with self.subTest(name):
                completed, shell = self.ios_memory(sentinel, wait_status=status)
                self.assertEqual(completed.returncode, 1)
                self.assertIn(message, completed.stderr)
                self.assertEqual(shell.calls_to(PUBLISHER), [])
                self.assertEqual(shell.calls_to(HISTORY), [])
                # The exact process is still terminated on the way out.
                self.assertEqual(len(shell.calls_to("xcrun", "devicectl", "device", "process", "terminate")), 1)


class IOSDeviceWaitTests(unittest.TestCase):
    def run_device_wait(
        self, function: str, run_id: str, *, marker: str | None, exits: bool,
        predicted: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        """Run one iOS wait helper against stubbed devicectl calls. The marker
        appears on the second probe of it; `exits` makes the exact PID vanish."""
        shell = LaneShell(self, "ios_device.sh")
        dest = shell.path / "dest"
        # The real poll cadence comes along; only the device and the clock are stubbed.
        stubs = (
            "sleep() { :; }\n"
            "probe_device_state() { printf 'READY|fixture\\n'; }\n"
            "report_clone_consent_advice() { :; }\n"
            'cmd_pull() { qv_record full-pull; }\n'
            'pull_device_diagnostics_run() { qv_record full-pull; }\n'
            "probe_device_run_file() {\n"
            '  qv_record probe "$3"; mkdir -p "$2/$1"\n'
            f'  if [[ "$3" == {quote(marker or "")} ]] && (( $(grep -c "^probe.$3\\$" "$QV_CALLS") >= 2 )); then\n'
            "    printf '{}' >\"$2/$1/$3\"\n"
            "  fi\n"
            "}\n"
            f'device_process_exited() {{ qv_record exit-check "$1" "$2"; return {0 if exits else 1}; }}\n'
        )
        call = f"{function} {quote(run_id)} 60 {quote(dest)} fixture-device 4242"
        if predicted is not None:
            call += f" {predicted}"
        completed = shell.run(stubs + call + "\n", timeout=60)
        log = [" ".join(entry) for entry in shell.calls()]
        return completed, log

    def poll_steps(self, *calls: tuple[str, ...], environment: dict[str, str] | None = None) -> list[str]:
        shell = LaneShell(self, "ios_device.sh")
        completed = shell.run("".join(f"{' '.join(call)}\n" for call in calls), env=environment)
        self.assertEqual(completed.returncode, 0, completed.stderr)
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
            self.poll_steps(("device_poll_step", "5", "24"),
                            environment={"QVOICE_IOS_POLL_INTERVAL_SECONDS": "2"}),
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
            "wait_device_diagnostics_sentinel", "ios-wait-zero", marker=None, exits=False, predicted="0",
        )
        # It fails without pulling a tree it never saw.
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(completed.stdout, "")
        self.assertNotIn("full-pull", calls)
        # One immediate probe, then one every 3 s up to 60 s.
        self.assertEqual(calls.count("probe device-diagnostics-done.json"), 21)

    def test_ios_waits_poll_only_their_markers_and_pull_the_tree_once(self) -> None:
        for function, marker in (
            ("wait_memory_qualification_sentinel", "memory-qualification-result.json"),
            ("wait_device_diagnostics_sentinel", "device-diagnostics-done.json"),
        ):
            with self.subTest(function=function):
                completed, calls = self.run_device_wait(function, "ios-wait-fixture", marker=marker, exits=False)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertTrue(completed.stdout.strip().endswith(f"ios-wait-fixture/{marker}"))
                # No full copy of the growing tree while the run is measured
                # (audit #45, #56): the one full pull follows the marker.
                self.assertEqual(calls.count("full-pull"), 1, calls)
                self.assertEqual(calls[-1], "full-pull")
                self.assertTrue(all(call.startswith(("probe ", "exit-check ")) for call in calls[:-1]), calls)

    def test_ios_waits_stop_with_a_typed_exit_when_the_process_vanishes(self) -> None:
        for function in (
            "wait_memory_qualification_sentinel",
            "wait_clone_conditioning_sentinel",
            "wait_device_diagnostics_sentinel",
        ):
            with self.subTest(function=function):
                completed, calls = self.run_device_wait(function, "ios-wait-exit-fixture", marker=None, exits=True)
                # A jetsam or crash writes no marker: stop now, not at the timeout.
                self.assertEqual(completed.returncode, 27, completed.stderr)
                self.assertEqual(completed.stdout, "")
                # The liveness check asks about the exact device and PID the wait was given.
                self.assertEqual([call for call in calls if call.startswith("exit-check ")],
                                 ["exit-check fixture-device 4242"])
                # The markers are probed once more before giving up, then the
                # partial tree is pulled once for diagnosis.
                self.assertEqual(calls.count("full-pull"), 1, calls)

    def memory_markers(self, markers: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], LaneShell]:
        """wait_memory_qualification_sentinel with these markers already on the phone."""
        shell = LaneShell(self, "ios_device.sh")
        run_id = "ios-memory-qualification-failure-fixture"
        for name, content in markers.items():
            shell.file(f"phone/{run_id}/{name}", content)
        body = (
            "sleep() { :; }\ncmd_pull() { :; }\nreport_clone_consent_advice() { :; }\n"
            "device_process_exited() { return 1; }\nprobe_device_state() { printf 'READY|fixture\\n'; }\n"
            "probe_device_run_file() {\n"
            '  mkdir -p "$2/$1"\n'
            '  if [[ -f "$QV_SANDBOX/phone/$1/$3" ]]; then cp "$QV_SANDBOX/phone/$1/$3" "$2/$1/$3"; fi\n'
            "}\n"
            f'wait_memory_qualification_sentinel {run_id} 10 "$QV_SANDBOX/dest"\n'
        )
        return shell.run(body), shell

    def test_ios_memory_wait_stops_on_a_bounded_failure_marker_before_any_result(self) -> None:
        run_id = "ios-memory-qualification-failure-fixture"
        failure = json.dumps({
            "schemaVersion": 1, "status": "failed", "runID": run_id, "policyID": "retained-memory-v1",
            "failedAt": "2026-07-13T07:00:00Z", "failureCode": "generation_failed",
            "completedTakeCount": 2, "expectedTakeCount": 9, "failedTakeIndex": 3,
            "failedCell": "custom/speed/medium/retained#2",
        })
        completed, _ = self.memory_markers({"memory-qualification-failure.json": failure})
        self.assertEqual(completed.returncode, 22, completed.stderr)
        self.assertIn("code=generation_failed completed=2/9", completed.stderr)
        self.assertEqual(completed.stdout, "")
        # A failure marker beside a result still fails: the failure is read first.
        completed, _ = self.memory_markers({"memory-qualification-failure.json": failure,
                                            "memory-qualification-result.json": "{}"})
        self.assertEqual(completed.returncode, 22, completed.stderr)
        self.assertEqual(completed.stdout, "")
        # A marker past the 4 KiB bound, or not a failure, is reported as invalid; it still stops the wait.
        for marker in (json.dumps({**json.loads(failure), "failedCell": "x" * 5000}),
                       json.dumps({**json.loads(failure), "status": "passed"})):
            completed, _ = self.memory_markers({"memory-qualification-failure.json": marker})
            self.assertEqual(completed.returncode, 22, completed.stderr)
            self.assertIn("invalid bounded failure marker", completed.stderr)
            self.assertNotIn("code=generation_failed", completed.stderr)

    def record_until_take_ends(self, *, tracer: str, predicted: str,
                               sentinel_on_probe: int = 0) -> tuple[int, list[str], bool]:
        """Drive the iPhone profile's stop-at-take-end loop against a stand-in
        xctrace (a child process) and a stubbed sentinel probe and clock.

        `tracer` is what the stand-in does: `stop` saves the trace and exits 54
        on SIGINT (as xctrace does after a Stop), `unsaved` exits 54 on SIGINT
        without a trace, `limit` exits 0 on its own at once (the time limit),
        `fails` exits 54 on its own. The sentinel appears on probe
        `sentinel_on_probe` (never when 0). Returns the loop's status, the
        stubbed sleeps and probes in order, and whether the trace exists."""
        shell = LaneShell(self, "ios_device.sh")
        trace, ready, dest = shell.path / "run.trace", shell.path / "ready", shell.path / "dest"
        dest.mkdir()
        shell.file("tracer.py", (
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
        ))
        body = (
            'sleep() { qv_record sleep "$1"; }\n'
            "probe_device_sentinel() {\n"
            "  qv_record probe\n"
            f'  if (( {sentinel_on_probe} > 0 && $(grep -c "^probe$" "$QV_CALLS") >= {sentinel_on_probe} )); then\n'
            '    mkdir -p "$2/$1"; printf \'{}\' >"$2/$1/device-diagnostics-done.json"\n'
            "  fi\n"
            "}\n"
            f'python3 "$QV_SANDBOX/tracer.py" {quote(trace)} {quote(ready)} {tracer} &\n'
            "tracer_pid=$!\n"
            f"while [[ ! -e {quote(ready)} ]]; do command sleep 0.01; done\n"
            "status=0\n"
            f"record_until_take_ends \"$tracer_pid\" ios-profile-fixture {quote(dest)} fixture-device "
            f"{quote(trace)} {predicted} || status=$?\n"
            "printf '%s\\n' \"$status\"\n"
        )
        completed = shell.run(body)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return int(completed.stdout.strip()), [" ".join(call) for call in shell.calls()], trace.is_dir()

    def test_ios_profile_first_probes_its_take_at_the_predicted_end(self) -> None:
        # audit #87 for the profile: no devicectl copy during most of the
        # profiled take. The first probe waits the predicted 12 s, later ones
        # 3 s; the sentinel stops the recording with SIGINT, and the 54 xctrace
        # then exits with is a pass because this stop sent it and the trace saved.
        status, calls, saved = self.record_until_take_ends(tracer="stop", predicted="12", sentinel_on_probe=2)
        self.assertEqual((status, saved), (0, True))
        self.assertEqual(calls, ["sleep 12", "probe", "sleep 3", "probe"])

    def test_ios_profile_accepts_54_only_after_its_own_stop_with_a_saved_trace(self) -> None:
        # A stop that saved no trace keeps xctrace's 54.
        status, _, saved = self.record_until_take_ends(tracer="unsaved", predicted="12", sentinel_on_probe=1)
        self.assertEqual((status, saved), (54, False))
        # xctrace exiting 54 on its own is a failure, not a stop.
        status, _, _ = self.record_until_take_ends(tracer="fails", predicted="12")
        self.assertEqual(status, 54)
        # Reaching the time limit before the take ended is xctrace's own 0.
        status, _, _ = self.record_until_take_ends(tracer="limit", predicted="12")
        self.assertEqual(status, 0)

    def test_the_memory_field_report_reads_local_files_and_never_contacts_the_phone(self) -> None:
        shell = LaneShell(self, "ios_device.sh")
        shell.helper("scripts/ios_memory_field_report.py", "exit 0")
        stubs = "".join(f"qv_stub {name} 1\n" for name in (
            "resolve_device", "cmd_pull", "probe_device_state", "probe_device_run_file", "pull_device_diagnostics_run",
        ))
        completed = shell.run(stubs + 'cmd_memory_field_report "$QV_SANDBOX/pulled"\ncmd_memory_field_report\n')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(shell.calls(), [
            ["scripts/ios_memory_field_report.py", str(shell.path / "pulled")],
            ["scripts/ios_memory_field_report.py",
             str(shell.build / "artifacts/diagnostics/ios/device-diagnostics")],
        ])
        completed = shell.run(stubs + "cmd_memory_field_report one two\n")
        self.assertEqual(completed.returncode, 1)
        self.assertIn("at most one local diagnostics path", completed.stderr)


class PublicationSourceTests(unittest.TestCase):
    """Python-source wiring of the publisher (not shell text; outside DW-02's scope)."""

    def test_memory_profiles_require_disabled_vm_auto_snapshots(self) -> None:
        publisher = (REPO / "scripts" / "publish_benchmark_history.py").read_text(encoding="utf-8")
        self.assertIn('require_disabled_vm_auto_snapshot=args.profile_kind == "memory"', publisher)

    def test_memory_policy_is_versioned_and_platform_topologies_are_fixed(self) -> None:
        policy = json.loads((REPO / "config" / "memory-qualification-policy.json").read_text(encoding="utf-8"))
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

    def test_memory_contract_surfaces_are_fingerprinted(self) -> None:
        history = (REPO / "scripts" / "benchmark_history.py").read_text(encoding="utf-8")
        for relative_path in (
            "benchmarks/schema-v2.json",
            "config/memory-qualification-policy.json",
            "scripts/benchmark_memory.py",
            "scripts/ios_memory_field_report.py",
        ):
            with self.subTest(relative_path=relative_path):
                history_expression = " / ".join(f'"{part}"' for part in relative_path.split("/"))
                self.assertIn(history_expression, history)


class MacOSLanguageBenchTests(unittest.TestCase):
    def test_each_cell_runs_its_planned_command_with_verbose_telemetry_scoped_to_it(self) -> None:
        shell = LaneShell(self, "macos_test.sh")
        shell.executable("scripts/build.sh")
        shell.executable("build/vocello", VOCELLO.format(started=quote(shell.path / "target-started"),
                                                          behaviour="exit 0"))
        shell.helper("scripts/language_bench_evidence.py",
                     f'exec "$QV_REAL_PYTHON" {quote(REPO / "scripts/language_bench_evidence.py")} "$@"')
        shell.helper("scripts/check_language_hints.py", "exit 0")
        shell.helper("scripts/qc.py", '[[ "$1" != run ]] || printf "qc-run-fixture\\n"')
        shell.helper(PUBLISHER, 'qv_record publisher-env "QWENVOICE_NATIVE_TELEMETRY_MODE=$QWENVOICE_NATIVE_TELEMETRY_MODE"')
        shell.helper(SUMMARIZER, "exit 0")
        shell.helper(HISTORY, "exit 0")
        body = (
            MAC_STUBS + "qv_stub capture_benchmark_source\n"
            "require_qc_python() { QC_PYTHON=python3; }\n"
            "export QWENVOICE_NATIVE_TELEMETRY_MODE=summary\n"
            "cmd_lang_bench --subset quick\n"
        )
        completed = shell.run(body)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        [artifacts] = list((shell.build / "artifacts/macos/language").iterdir())
        plan = json.loads((artifacts / "language-run-plan.json").read_text(encoding="utf-8"))
        generated = shell.calls_to("build/vocello")
        self.assertEqual(len(generated), plan["takeCount"])
        for take, command in zip(plan["takes"], generated):
            with self.subTest(cell=take["cellID"]):
                self.assertEqual(command[0], "generate")
                self.assertEqual(option(command, "--mode"), take["mode"])
                self.assertEqual(option(command, "--variant"), take.get("variant", "speed"))
                self.assertEqual(option(command, "--seed"), str(take["seed"]))
                self.assertEqual(option(command, "--out"), str(artifacts / "wav" / f"{take['cellID']}.wav"))
                if take["mode"] == "custom":
                    self.assertEqual(option(command, "--speaker"), take["customSpeakerID"])
                else:
                    self.assertEqual(option(command, "--voice-brief"), take["designInstruction"])
                if take.get("uiHint", "auto") == "auto":
                    self.assertNotIn("--language", command)
                else:
                    self.assertEqual(option(command, "--language"), take["uiHint"])
        self.assertTrue(any(take.get("uiHint", "auto") == "auto" for take in plan["takes"]))
        # Verbose telemetry for each generation; the caller's own preference survives the lane.
        self.assertEqual({tuple(call) for call in shell.calls_to("vocello-env")},
                         {("QWENVOICE_NATIVE_TELEMETRY_MODE=verbose", "QWENVOICE_DEBUG=1")})
        self.assertEqual(shell.calls_to("publisher-env"), [["QWENVOICE_NATIVE_TELEMETRY_MODE=summary"]])
        # Installed models are required, never installed.
        self.assertNotIn("ensure_mac_test_models", shell.names())
        required = {call[0] for call in shell.calls_to("require_mac_benchmark_models")}
        self.assertEqual(required, {f"pro_{take['mode']}_{take.get('variant', 'speed')}" for take in plan["takes"]})
        self.assertLess(shell.index("require_mac_benchmark_models", last=True), shell.index("build/vocello"))
        [summary] = shell.calls_to(SUMMARIZER)
        self.assertEqual(option(summary, "--evidence-manifest"), str(artifacts / "benchmark-evidence.json"))


class IOSGateTests(unittest.TestCase):
    def ios_gate(self, *, crashes: int = 0, env: dict[str, str] | None = None
                 ) -> tuple[subprocess.CompletedProcess[str], LaneShell, Path]:
        shell = LaneShell(self, "ios_device.sh")
        shell.executable("scripts/check_project_inputs.sh")
        shell.helper(HISTORY, "exit 0")
        body = (
            'ROOT_DIR="$QV_SANDBOX"\n'
            "qv_stub cmd_preflight\nqv_stub _gate_generation_check\n"
            f"qv_stub cmd_crashes {crashes}\n"
            "cmd_gate\n"
        )
        completed = shell.run(body, env=env)
        [gate] = list((shell.build / "artifacts/ios/gates").iterdir())
        return completed, shell, gate

    def test_the_gate_publishes_history_only_after_a_clean_crash_delta(self) -> None:
        completed, shell, gate = self.ios_gate()
        self.assertEqual(completed.returncode, 0, completed.stderr)
        order = [shell.index("scripts/check_project_inputs.sh"), shell.index("cmd_preflight"),
                 shell.index("_gate_generation_check"), shell.index("cmd_crashes"), shell.index(HISTORY, "record")]
        self.assertEqual(order, sorted(order))
        ledger = json.loads((gate / "required-steps.json").read_text(encoding="utf-8"))
        self.assertEqual((ledger["workflow"], ledger["status"]), ("ios-gate", "passed"))
        self.assertTrue((gate / "verdict.txt").read_text(encoding="utf-8").rstrip().endswith("GATE: PASS"))

        completed, shell, gate = self.ios_gate(crashes=1)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(shell.calls_to(HISTORY), [])
        verdict = (gate / "verdict.txt").read_text(encoding="utf-8")
        self.assertIn("crashes: FAIL", verdict)
        self.assertNotIn("GATE: PASS", verdict)

    def test_a_gate_without_generation_publishes_nothing_and_passes_its_own_ledger(self) -> None:
        completed, shell, gate = self.ios_gate(env={"QVOICE_GATE_SKIP_GENERATION": "1"})
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertNotIn("_gate_generation_check", shell.names())
        self.assertEqual(shell.calls_to(HISTORY), [])
        ledger = json.loads((gate / "required-steps.json").read_text(encoding="utf-8"))
        self.assertEqual((ledger["workflow"], ledger["status"]), ("ios-gate-without-generation", "passed"))


if __name__ == "__main__":
    unittest.main()
