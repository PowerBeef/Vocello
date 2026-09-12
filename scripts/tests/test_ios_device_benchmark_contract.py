#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "ios_device.sh"
RUNNER = Path(__file__).resolve().parents[2] / "Sources/iOS/IOSDeviceDiagnosticsRunner.swift"
INTERRUPTION_RECORDER = (
    Path(__file__).resolve().parents[2]
    / "Sources/iOSSupport/Services/IOSInterruptionRecorder.swift"
)
ENGINE_STORE = Path(__file__).resolve().parents[2] / "Sources/iOS/TTSEngineStore.swift"
IOS_APP = Path(__file__).resolve().parents[2] / "Sources/iOS/QVoiceiOSApp.swift"


def shell_function(text: str, name: str) -> str:
    prefix = f"{name}() {{\n"
    start = text.index(prefix)
    end = text.index("\n}\n", start) + 3
    return text[start:end]


class IOSDeviceBenchmarkContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = SCRIPT.read_text(encoding="utf-8")
        cls.runner = RUNNER.read_text(encoding="utf-8")
        cls.interruption_recorder = INTERRUPTION_RECORDER.read_text(encoding="utf-8")
        cls.engine_store = ENGINE_STORE.read_text(encoding="utf-8")
        cls.ios_app = IOS_APP.read_text(encoding="utf-8")

    def test_canonical_device_cell_matches_publisher_identity(self) -> None:
        function = shell_function(self.text, "device_benchmark_cell")
        for spec, expected in (
            ("custom:speed:hello", "custom/speed/device"),
            ("design:speed:hello", "design/speed/device"),
            ("clone:quality:hello", "clone/quality/device"),
        ):
            completed = subprocess.run(
                ["bash", "-c", f'{function}\ndevice_benchmark_cell "$1"', "test", spec],
                check=True,
                text=True,
                capture_output=True,
            )
            self.assertEqual(completed.stdout, expected)

    def test_headless_and_gate_stamp_the_canonical_device_cell(self) -> None:
        bench = shell_function(self.text, "cmd_bench")
        gate = shell_function(self.text, "_gate_generation_check")
        self.assertIn('QVOICE_MAC_BENCH_CELL="$(device_benchmark_cell "$spec")"', bench)
        self.assertIn(
            'QVOICE_MAC_BENCH_CELL="$(device_benchmark_cell "custom:speed:Gate generation smoke.")"',
            gate,
        )
        self.assertNotIn("device-headless", bench)
        self.assertNotIn("device-gate", gate)
        self.assertIn("export QWENVOICE_NATIVE_TELEMETRY_MODE=verbose", bench)
        self.assertIn("export QWENVOICE_NATIVE_TELEMETRY_MODE=verbose", gate)

    def test_language_generations_use_a_scoped_verbose_telemetry_override(self) -> None:
        language = shell_function(self.text, "cmd_lang_bench")
        launch = 'QWENVOICE_NATIVE_TELEMETRY_MODE=verbose cmd_launch "$spec"'
        self.assertIn(launch, language)
        self.assertNotIn("export QWENVOICE_NATIVE_TELEMETRY_MODE", language)
        self.assertLess(language.index(launch), language.index("wait_device_diagnostics_sentinel"))

    def test_profile_propagates_correlation_before_building_launch_environment(self) -> None:
        profile = shell_function(self.text, "cmd_profile")
        run = 'export QVOICE_MAC_BENCH_RUN_ID="$run_id"'
        take = "export QVOICE_MAC_BENCH_TAKE_INDEX=1"
        cell = 'export QVOICE_MAC_BENCH_CELL="$(device_benchmark_cell "$spec")"'
        capture = 'env_json="$(device_diagnostics_env_json "$spec" "$run_id")"'
        cleanup = "unset QVOICE_MAC_BENCH_RUN_ID QVOICE_MAC_BENCH_TAKE_INDEX QVOICE_MAC_BENCH_CELL"
        for assignment in (run, take, cell):
            self.assertLess(profile.index(assignment), profile.index(capture))
        self.assertLess(profile.index(capture), profile.index(cleanup))

    def test_diagnostics_runner_leaves_model_preparation_inside_generation_session(self) -> None:
        self.assertNotIn("engine.loadModel", self.runner)
        self.assertNotIn("engine.ensureCloneReferencePrimed", self.runner)
        self.assertIn("let result = try await engine.generate(request)", self.runner)
        self.assertIn("per-generation telemetry session before model load", self.runner)

    def test_diagnostics_runner_turns_interruptions_into_failure(self) -> None:
        self.assertIn("if !interruptions.isEmpty", self.runner)
        self.assertIn('if record.status == "ok"', self.runner)
        self.assertIn('record.status = "error"', self.runner)
        self.assertIn("diagnostic run was interrupted", self.runner)

    def test_interruption_recorder_ignores_only_initial_activation(self) -> None:
        self.assertIn("private var hasLostActiveState = false", self.interruption_recorder)
        self.assertIn('case "will_resign_active", "did_enter_background":', self.interruption_recorder)
        self.assertIn("hasLostActiveState = true", self.interruption_recorder)
        self.assertIn('case "did_become_active":', self.interruption_recorder)
        self.assertIn("guard hasLostActiveState else { return }", self.interruption_recorder)
        self.assertIn("self?.recordLifecycle(type: label)", self.interruption_recorder)

    def test_sentinel_contract_rejects_failed_or_interrupted_runs(self) -> None:
        function = shell_function(self.text, "require_uninterrupted_success_sentinel")
        cases = (
            ({"status": "ok", "interruptions": []}, 0),
            ({"status": "error", "error": "generation failed"}, 1),
            ({"status": "ok", "interruptions": [{"type": "will_resign_active"}]}, 2),
        )
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "sentinel.json"
            for payload, expected in cases:
                with self.subTest(payload=payload):
                    sentinel.write_text(json.dumps(payload), encoding="utf-8")
                    completed = subprocess.run(
                        [
                            "bash",
                            "-c",
                            f'{function}\nrequire_uninterrupted_success_sentinel "$1"',
                            "test",
                            str(sentinel),
                        ],
                        text=True,
                        capture_output=True,
                    )
                    self.assertEqual(completed.returncode, expected, completed.stderr)

    def test_sentinel_wait_requires_run_id_as_immediate_parent(self) -> None:
        wait = shell_function(self.text, "wait_device_diagnostics_sentinel")
        self.assertIn(
            '-path "*/${run_id}/device-diagnostics-done.json"',
            wait,
        )
        self.assertNotIn('-path "*/${run_id}/*"', wait)

    def test_all_published_device_generation_lanes_require_clean_sentinel(self) -> None:
        for name in ("cmd_bench", "cmd_profile", "_gate_generation_check"):
            with self.subTest(function=name):
                function = shell_function(self.text, name)
                validation = 'require_uninterrupted_success_sentinel "$sentinel"'
                publication = 'publish_benchmark_history.py'
                self.assertIn(validation, function)
                self.assertLess(function.index(validation), function.index(publication))

    def test_headless_lanes_summarize_frozen_evidence_before_recording(self) -> None:
        for name in ("cmd_bench", "cmd_lang_bench", "cmd_profile", "_gate_generation_check"):
            with self.subTest(function=name):
                function = shell_function(self.text, name)
                publisher = function.index("publish_benchmark_history.py")
                manifest = function.index('--evidence-manifest "$artifacts/benchmark-evidence.json"')
                self.assertLess(publisher, manifest)
                self.assertIn("--defer-record", function[publisher:manifest])
                if name != "_gate_generation_check":
                    self.assertLess(manifest, function.index("record_benchmark_history"))

    def test_gate_rebuilds_and_installs_exact_local_app_before_snapshot_and_launch(self) -> None:
        gate = shell_function(self.text, "_gate_generation_check")
        build = "cmd_build"
        install = "cmd_install >/dev/null"
        snapshot = 'capture_benchmark_source "$artifacts"'
        launch = 'cmd_launch "custom:speed:Gate generation smoke."'
        self.assertLess(gate.index(build), gate.index(install))
        self.assertLess(gate.index(install), gate.index(snapshot))
        self.assertLess(gate.index(snapshot), gate.index(launch))
        self.assertNotIn('[[ -d "$APP_PATH" ]] || cmd_install', gate)

    def test_profile_bounds_tracer_start_and_scopes_summary_to_run(self) -> None:
        profile = shell_function(self.text, "cmd_profile")
        for token in (
            'QVOICE_IOS_PROFILE_START_TIMEOUT:-30',
            'tracer_start_deadline=$((SECONDS + tracer_start_timeout))',
            'SECONDS >= tracer_start_deadline',
            "grep -q '^Starting recording'",
            'kill "$xctrace_pid"',
            'xctrace did not report tracing startup within ${tracer_start_timeout}s',
        ):
            self.assertIn(token, profile)
        self.assertNotIn("notifyutil", profile)
        self.assertNotIn("--notify-tracing-started", profile)
        summary = 'summarize_generation_telemetry.py" "$diag"'
        self.assertIn(summary, profile)
        self.assertIn('--run-id "$run_id"', profile[profile.index(summary):])
        self.assertIn('local cpu_instrument="CPU Profiler"', profile)
        self.assertIn('local -a instrument_args=(--instrument "$cpu_instrument")', profile)
        self.assertIn('instrument_args+=(--instrument os_signpost)', profile)
        self.assertIn('xcrun xctrace record --device "$xctrace_dev" "${instrument_args[@]}"', profile)
        self.assertNotIn('--template "$template"', profile)

    def test_xctrace_inventory_distinguishes_online_offline_and_missing_device(self) -> None:
        function = shell_function(self.text, "xctrace_inventory_status")
        udid = "00008150-00181D580ED8401C"
        fixtures = (
            (f"== Devices ==\nTest iPhone (26.5) ({udid})\n", 0, udid),
            (f"== Devices Offline ==\nTest iPhone (26.5) ({udid})\n", 20, ""),
            ("== Devices ==\nMac mini (HOST-ID)\n", 21, ""),
        )
        for inventory, expected_status, expected_output in fixtures:
            with self.subTest(expected_status=expected_status):
                completed = subprocess.run(
                    ["bash", "-c", f'{function}\nxctrace_inventory_status "$1"', "test", udid],
                    input=inventory,
                    text=True,
                    capture_output=True,
                )
                self.assertEqual(completed.returncode, expected_status, completed.stderr)
                self.assertEqual(completed.stdout.strip(), expected_output)

    def test_profile_resolves_instruments_device_before_mutating_app_state(self) -> None:
        profile = shell_function(self.text, "cmd_profile")
        resolve = 'xctrace_dev="$(resolve_xctrace_device "$dev")"'
        install = "cmd_install >/dev/null"
        launch = "xcrun devicectl device process launch"
        record = 'xcrun xctrace record --device "$xctrace_dev"'
        self.assertLess(profile.index(resolve), profile.index(install))
        self.assertLess(profile.index(install), profile.index(launch))
        self.assertLess(profile.index(launch), profile.index(record))
        self.assertNotIn('xcrun xctrace record --device "$dev"', profile)

    def test_profile_always_cleans_up_the_exact_target_process(self) -> None:
        profile = shell_function(self.text, "cmd_profile")
        cleanup = shell_function(self.text, "profile_failure_cleanup")
        self.assertIn("device process terminate --device %q --pid %q", profile)
        self.assertIn('PROFILE_TRACE_DEVICE_CLEANUP="$cleanup_command"', profile)
        self.assertIn("trap profile_failure_cleanup EXIT", profile)
        self.assertIn('eval "$PROFILE_TRACE_DEVICE_CLEANUP"', cleanup)
        self.assertIn('eval "$cleanup_command"', profile)
        self.assertIn("trap - EXIT", profile)

    def test_device_build_is_safe_when_optional_diagnostic_flags_are_empty(self) -> None:
        build = shell_function(self.text, "cmd_build")
        self.assertIn("local -a command=(", build)
        # -Onone is the default fast loop; `bench` passes --optimized for -O.
        self.assertIn('local swift_optimization="-Onone" optimization_label="Onone"', build)
        self.assertIn('SWIFT_OPTIMIZATION_LEVEL="$swift_optimization"', build)
        self.assertIn('--optimized) optimized_build=1', build)
        self.assertIn("SWIFT_COMPILATION_MODE=incremental", build)
        self.assertRegex(build, r"command\+=\([\s\S]*?\n\s+build\n\s+\)")
        self.assertIn('"${command[@]}" 2>&1 | tee "$log"', build)
        self.assertNotIn('"${diagnostic_flags[@]}"', build)
        self.assertIn('producer+=" --device-diagnostics"', build)
        self.assertIn('write_build_provenance "$DERIVED/last-build.json"', build)
        self.assertIn('"$producer" "$SCHEME"', build)

    def test_clone_conditioning_lane_is_compile_gated_and_local_only(self) -> None:
        build = shell_function(self.text, "cmd_build")
        lane = shell_function(self.text, "cmd_clone_conditioning")
        self.assertIn("--device-diagnostics|--device-diagnostics-crash-test", build)
        self.assertIn("-DQVOICE_DEVICE_DIAGNOSTICS", build)
        self.assertIn("cmd_build --device-diagnostics", lane)
        self.assertIn("check_ios_clone_conditioning.py", lane)
        self.assertIn("MAC_TEST_CLONE_REF_SHA256", lane)
        self.assertIn("MAC_TEST_CLONE_REF_TRANSCRIPT_SHA256", lane)
        self.assertNotIn("record_benchmark_history", lane)
        self.assertNotIn("publish_benchmark_history.py", lane)

    def test_clone_conditioning_runner_proves_both_semantic_modes(self) -> None:
        self.assertIn("#if QVOICE_DEVICE_DIAGNOSTICS", self.runner)
        self.assertIn("runCloneConditioningAcceptance", self.runner)
        self.assertIn('expectedConditioningMode: "transcript_backed"', self.runner)
        self.assertIn('expectedConditioningMode: "x_vector_only"', self.runner)
        self.assertIn('expectedArtifactScope: "saved_voice"', self.runner)
        self.assertIn('expectedArtifactScope: "transient_reference"', self.runner)
        self.assertIn("scratchCleanupVerified: true", self.runner)
        self.assertIn("promptAssemblySHA256", self.runner)
        output_function_start = self.runner.index(
            "private static func makeCloneConditioningOutputPath"
        )
        output_function_end = self.runner.index("\n    #endif", output_function_start)
        output_function = self.runner[output_function_start:output_function_end]
        self.assertIn('scratchDirectory.appendingPathComponent("outputs"', output_function)
        self.assertNotIn("AppPaths.outputsDir", output_function)
        self.assertNotIn("benchmark-evidence.json", shell_function(self.text, "cmd_clone_conditioning"))

    def test_critical_memory_relief_owns_generation_until_full_unload_completes(self) -> None:
        generate_start = self.engine_store.index("func generate(_ request:")
        generate_end = self.engine_store.index("\n    func listPreparedVoices", generate_start)
        generate = self.engine_store[generate_start:generate_end]
        admission = generate.index("guardModelAdmission")
        ownership_guard = generate.index(
            "guard !hasActiveGeneration, !criticalMemoryActionInFlight"
        )
        self.assertLess(ownership_guard, admission)
        self.assertEqual(
            generate.count("guard !hasActiveGeneration, !criticalMemoryActionInFlight"),
            2,
        )

        defer_start = generate.index("defer {")
        defer_end = generate.index("\n        // The physical-device", defer_start)
        cleanup = generate[defer_start:defer_end]
        self.assertIn("if criticalMemoryActionInFlight", cleanup)
        critical_branch, normal_branch = cleanup.split("} else {", 1)
        self.assertNotIn("stopActiveGenerationMemoryGuard", critical_branch)
        self.assertNotIn("hasActiveGeneration = false", critical_branch)
        self.assertIn("stopActiveGenerationMemoryGuard", normal_branch)
        guard_start = self.engine_store.index("private func startActiveGenerationMemoryGuard")
        guard_end = self.engine_store.index(
            "\n    private func stopActiveGenerationMemoryGuard", guard_start
        )
        memory_guard = self.engine_store[guard_start:guard_end]
        self.assertEqual(memory_guard.count("outcome == .completed"), 2)
        self.assertNotIn("outcome != .cancellationFailed", memory_guard)

        action_start = self.engine_store.index(
            "private func enforceCriticalMemoryContext"
        )
        action_end = self.engine_store.index(
            "\n    private func applyCriticalFullUnload", action_start
        )
        action = self.engine_store[action_start:action_end]
        cancellation = action.index("cancelActiveGeneration(reason: reason)")
        trim = action.index(
            "await self.applyCriticalFullUnload(context)",
            action.index("applyRelief:"),
        )
        release = action.index("self.completeCriticalMemoryAction()")
        self.assertLess(cancellation, trim)
        self.assertLess(trim, release)

        unload_start = self.engine_store.index("private func applyCriticalFullUnload")
        unload_end = self.engine_store.index(
            "\n    private func beginCriticalMemoryAction", unload_start
        )
        unload = self.engine_store[unload_start:unload_end]
        trim_completion = unload.index("await backend.trimMemory")
        diagnostic_completion = unload.index('event: "critical_full_unload"')
        clear_activity = unload.index("backend.clearGenerationActivity()")
        self.assertLess(trim_completion, diagnostic_completion)
        self.assertLess(diagnostic_completion, clear_activity)
        self.assertEqual(unload.count("clearGenerationActivity()"), 1)

    def test_application_critical_pressure_uses_store_owned_barrier(self) -> None:
        function_start = self.ios_app.index(
            "private func performMemoryPressureReliefAfterCancellingGeneration"
        )
        function_end = self.ios_app.index(
            "\n    private func performMemoryPressureRelief(", function_start
        )
        function = self.ios_app[function_start:function_end]
        self.assertIn("engine.performCriticalMemoryPressureRelief(reason: reason)", function)
        self.assertNotIn("engine.cancelActiveGeneration", function)
        self.assertNotIn("applyMemoryPressureRelief", function)


if __name__ == "__main__":
    unittest.main()
