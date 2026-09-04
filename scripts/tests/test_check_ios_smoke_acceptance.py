#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts" / "check_ios_smoke_acceptance.py"
RUN_ID = "ios-xcui-smoke-fixture"


def memory_row(
    event: str,
    index: int,
    *,
    reason: str = "active_generation_sample_debug_force_critical_once",
    trim_level: str | None = None,
) -> dict:
    return {
        "event": event,
        "recordedAt": f"2026-07-15T12:00:0{index}Z",
        "processUptimeSeconds": 100.0 + index,
        "runID": RUN_ID,
        "reason": reason,
        "trimLevel": trim_level,
    }


def valid_memory_rows() -> list[dict]:
    return [
        memory_row("debug_force_critical_once", 1),
        memory_row("critical_memory_action", 2),
        memory_row("critical_generation_cancel", 3, reason="memory_pressure"),
        memory_row("critical_full_unload", 4, trim_level="fullUnload"),
    ]


def app_row(
    generation_id: str,
    second: int,
    *,
    finish_reason: str = "eos",
    run_id: str = RUN_ID,
) -> dict:
    return {
        "schemaVersion": 8,
        "generationID": generation_id,
        "layer": "app",
        "recordedAt": f"2026-07-15T12:00:{second:02d}Z",
        "finishReason": finish_reason,
        "notes": {"benchRunID": run_id},
    }


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


class IOSSmokeAcceptanceTests(unittest.TestCase):
    def run_checker(self, root: Path, run_id: str = RUN_ID) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(CHECKER), str(root), "--run-id", run_id],
            text=True,
            capture_output=True,
            check=False,
        )

    def make_valid_fixture(self, root: Path, *, duplicate_mirrors: bool = False) -> None:
        memory = valid_memory_rows()
        app = [
            app_row("user-cancelled-generation", 0, finish_reason="cancelled"),
            app_row("memory-cancelled-generation", 3, finish_reason="cancelled"),
            app_row("reused-generation", 8),
            app_row("unrelated-generation", 9, run_id="another-run"),
        ]
        write_jsonl(root / "pull" / RUN_ID / "memory-contexts.jsonl", memory)
        write_jsonl(root / "pull" / "app" / "generations.jsonl", app)
        if duplicate_mirrors:
            write_jsonl(root / "mirror" / RUN_ID / "memory-contexts.jsonl", memory)
            write_jsonl(root / "mirror" / "app" / "generations.jsonl", app)

    def test_accepts_identical_mirrors_and_proves_post_pressure_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_fixture(root, duplicate_mirrors=True)
            completed = self.run_checker(root)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["memoryMirrorCount"], 2)
        self.assertEqual(result["appMirrorCount"], 2)
        self.assertEqual(result["cancellationReason"], "memory_pressure")
        self.assertEqual(result["trimLevel"], "fullUnload")
        self.assertEqual(result["cancelledGenerationCount"], 2)
        self.assertEqual(result["postPressureGenerationID"], "reused-generation")
        self.assertNotIn(directory, completed.stdout)

    def test_rejects_missing_duplicate_or_out_of_order_events(self) -> None:
        mutations = {
            "missing": lambda rows: rows.pop(1),
            "duplicate": lambda rows: rows.insert(2, dict(rows[1])),
            "out of order": lambda rows: rows.__setitem__(slice(1, 3), [rows[2], rows[1]]),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_valid_fixture(root)
                rows = valid_memory_rows()
                mutate(rows)
                write_jsonl(root / "pull" / RUN_ID / "memory-contexts.jsonl", rows)
                completed = self.run_checker(root)
                self.assertNotEqual(completed.returncode, 0)

    def test_scoped_collection_preserves_acceptance_without_historical_contamination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_fixture(root)
            before = self.run_checker(root / "pull")
            scoped = root / "pull" / RUN_ID
            (scoped / "app").mkdir()
            (root / "pull" / "app" / "generations.jsonl").rename(
                scoped / "app" / "generations.jsonl"
            )
            historical = root / "pull" / "old-run" / "app" / "generations.jsonl"
            historical.parent.mkdir(parents=True)
            historical.write_text("interrupted historical JSON", encoding="utf-8")
            after = self.run_checker(scoped)
            contaminated = self.run_checker(root / "pull")
        self.assertEqual(before.returncode, 0, before.stderr)
        self.assertEqual(after.returncode, 0, after.stderr)
        self.assertEqual(json.loads(before.stdout), json.loads(after.stdout))
        self.assertNotEqual(contaminated.returncode, 0)
        self.assertIn("invalid JSON", contaminated.stderr)

    def test_smoke_collector_is_run_scoped_bounded_and_propagates_copy_failure(self) -> None:
        runner = (ROOT / "scripts" / "ui_test.sh").read_text(encoding="utf-8")
        smoke = runner.split("validate_ios_smoke() {", 1)[1].split(
            "validate_ios_ui_perf() {", 1
        )[0]
        collector = runner.split("pull_ios_run_diagnostics() {", 1)[1].split(
            "pull_ios_model_download_diagnostics() {", 1
        )[0]
        self.assertIn('pull_ios_run_diagnostics "$device" "$run_id"', smoke)
        self.assertNotIn('ios_device.sh" pull', smoke)
        self.assertIn('diagnostics/$target_run_id"', collector)
        self.assertIn('--timeout 60', collector)
        for copy_status in (0, 1):
            with self.subTest(copy_status=copy_status), tempfile.TemporaryDirectory() as directory:
                stub = (
                    'pull_ios_run_diagnostics() { return ' + str(copy_status) + '; }\n'
                    'python3() { echo validator_called; }\n'
                    'validate_ios_smoke() {' + smoke + '\n'
                    'validate_ios_smoke\n'
                )
                completed = subprocess.run(
                    ["bash", "-c", stub], text=True, capture_output=True,
                    env={"out": directory, "device": "fixture", "run_id": RUN_ID},
                )
                self.assertEqual(completed.returncode, copy_status, completed.stderr)
                self.assertEqual("validator_called" in completed.stdout, copy_status == 0)

    def test_rejects_wrong_cancellation_reason_and_trim_level(self) -> None:
        for field, value in (("reason", "active_generation_sample"), ("trimLevel", "hardTrim")):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_valid_fixture(root)
                rows = valid_memory_rows()
                target = rows[2] if field == "reason" else rows[3]
                target[field] = value
                write_jsonl(root / "pull" / RUN_ID / "memory-contexts.jsonl", rows)
                completed = self.run_checker(root)
                self.assertNotEqual(completed.returncode, 0)

    def test_cancel_failed_is_suite_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_fixture(root)
            rows = valid_memory_rows()
            rows.insert(3, memory_row("critical_generation_cancel_failed", 3))
            write_jsonl(root / "pull" / RUN_ID / "memory-contexts.jsonl", rows)
            completed = self.run_checker(root)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("cancel_failed", completed.stderr)

    def test_rejects_divergent_memory_and_app_mirrors(self) -> None:
        for evidence in ("memory", "app"):
            with self.subTest(evidence=evidence), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_valid_fixture(root, duplicate_mirrors=True)
                if evidence == "memory":
                    rows = valid_memory_rows()
                    rows[0]["source"] = "divergent"
                    write_jsonl(root / "mirror" / RUN_ID / "memory-contexts.jsonl", rows)
                else:
                    write_jsonl(
                        root / "mirror" / "app" / "generations.jsonl",
                        [app_row("different-generation", 9)],
                    )
                completed = self.run_checker(root)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("diverge", completed.stderr)

    def test_rejects_mixed_run_identity_in_run_scoped_memory_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_valid_fixture(root)
            rows = valid_memory_rows()
            rows[1]["runID"] = "another-run"
            write_jsonl(root / "pull" / RUN_ID / "memory-contexts.jsonl", rows)
            completed = self.run_checker(root)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("mixes run identities", completed.stderr)

    def test_requires_successful_app_completion_after_full_unload(self) -> None:
        variants = {
            "only before": [
                app_row("user-cancel", 0, finish_reason="cancelled"),
                app_row("memory-cancel", 3, finish_reason="cancelled"),
            ],
            "failed after": [
                app_row("user-cancel", 0, finish_reason="cancelled"),
                app_row("memory-cancel", 3, finish_reason="cancelled"),
                app_row("failed-after", 8, finish_reason="failed"),
            ],
        }
        for label, rows in variants.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_valid_fixture(root)
                write_jsonl(root / "pull" / "app" / "generations.jsonl", rows)
                completed = self.run_checker(root)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("after the critical full unload", completed.stderr)

    def test_requires_distinct_user_and_memory_cancellations(self) -> None:
        variants = {
            "missing user": [
                app_row("memory-cancel", 3, finish_reason="cancelled"),
                app_row("reused", 8),
            ],
            "missing memory": [
                app_row("user-cancel", 0, finish_reason="cancelled"),
                app_row("reused", 8),
            ],
            "duplicate memory": [
                app_row("user-cancel", 0, finish_reason="cancelled"),
                app_row("memory-cancel-1", 2, finish_reason="cancelled"),
                app_row("memory-cancel-2", 3, finish_reason="cancelled"),
                app_row("reused", 8),
            ],
        }
        for label, rows in variants.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.make_valid_fixture(root)
                write_jsonl(root / "pull" / "app" / "generations.jsonl", rows)
                completed = self.run_checker(root)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("cancellation", completed.stderr)

    def test_errors_do_not_disclose_the_local_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            completed = self.run_checker(root)
        self.assertNotEqual(completed.returncode, 0)
        self.assertNotIn(directory, completed.stderr)

    def test_xcode_runner_environment_uses_the_stripped_name(self) -> None:
        runner = (ROOT / "scripts" / "ui_test.sh").read_text(encoding="utf-8")
        smoke = (
            ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSSmokeUITests.swift"
        ).read_text(encoding="utf-8")

        self.assertIn(
            'export TEST_RUNNER_QVOICE_IOS_SMOKE_RUN_ID="$run_id"',
            runner,
        )
        self.assertIn(
            'runnerEnvironment["QVOICE_IOS_SMOKE_RUN_ID"]',
            smoke,
        )
        self.assertNotIn(
            'runnerEnvironment["TEST_RUNNER_QVOICE_IOS_SMOKE_RUN_ID"]',
            smoke,
        )
        model_download = (
            ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSModelDownloadUITests.swift"
        ).read_text(encoding="utf-8")
        for name in ["RUN_ID", "SCENARIO", "ITERATIONS"]:
            self.assertIn(
                f'export TEST_RUNNER_QVOICE_IOS_MODEL_MANAGEMENT_{name}=',
                runner,
            )
            self.assertIn(
                f'"QVOICE_IOS_MODEL_MANAGEMENT_{name}"',
                model_download,
            )
            self.assertNotIn(
                f'ProcessInfo.processInfo.environment["TEST_RUNNER_QVOICE_IOS_MODEL_MANAGEMENT_{name}"]',
                model_download,
            )

    def test_clone_consent_is_settings_owned_and_visibly_enabled_by_ui_lanes(self) -> None:
        settings = (
            ROOT / "Sources" / "iOS" / "Settings" / "SettingsScreen.swift"
        ).read_text(encoding="utf-8")
        clone_view = (
            ROOT / "Sources" / "iOS" / "IOSGenerationModeViews.swift"
        ).read_text(encoding="utf-8")
        test_case = (
            ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSUITestCase.swift"
        ).read_text(encoding="utf-8")
        benchmark = (
            ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSBenchmarkUITests.swift"
        ).read_text(encoding="utf-8")
        smoke = (
            ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSSmokeUITests.swift"
        ).read_text(encoding="utf-8")

        identifier = 'accessibilityIdentifier: "voiceCloning_consentAcknowledgment"'
        self.assertEqual(settings.count(identifier), 1)
        self.assertNotIn(identifier, clone_view)
        self.assertIn('@AppStorage("vocello.voiceCloningConsent.v1")', clone_view)
        self.assertIn("&& cloneConsentAcknowledged", clone_view)
        self.assertIn("guard cloneConsentAcknowledged else", clone_view)
        self.assertIn("func ensureCloneConsentEnabled()", test_case)
        self.assertIn("select(tab: .settings)", test_case)
        self.assertIn("ensureCloneConsentEnabled()", benchmark)
        self.assertIn("ensureCloneConsentEnabled()", smoke)

    def test_settings_information_architecture_and_model_lifecycle_contract(self) -> None:
        settings = (
            ROOT / "Sources" / "iOS" / "Settings" / "SettingsScreen.swift"
        ).read_text(encoding="utf-8")
        models = (
            ROOT / "Sources" / "iOS" / "Settings" / "VoiceModelsScreen.swift"
        ).read_text(encoding="utf-8")
        rows = (ROOT / "Sources" / "iOS" / "IOSSettingsViews.swift").read_text(
            encoding="utf-8"
        )
        test_case = (
            ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSUITestCase.swift"
        ).read_text(encoding="utf-8")
        model_download_test = (
            ROOT
            / "Tests"
            / "VocelloiOSUITests"
            / "VocelloiOSModelDownloadUITests.swift"
        ).read_text(encoding="utf-8")

        section_markers = [
            'IOSSettingsSection(title: "Audio",',
            'IOSSettingsSection(title: "Models & Files")',
            'IOSSettingsSection(title: "Accessibility")',
            'IOSSettingsSection(title: "Privacy")',
            'IOSSettingsSection(title: "About")',
        ]
        positions = [settings.index(marker) for marker in section_markers]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("IOSStudioWorkspaceHeading", settings)
        self.assertNotIn(".navigationTitle", settings)
        self.assertIn(
            'IOSSettingsSection(title: "Audio", accessibilityIdentifier: "screen_settings")',
            settings,
        )
        self.assertIn('.accessibilityIdentifier("iosSettings_voiceModelsRow")', settings)
        self.assertIn(
            "IOSStudioShellMetrics.dockFadeHeight + Theme.Spacing.lg", settings
        )

        self.assertIn('.accessibilityIdentifier("screen_voiceModels")', models)
        self.assertIn('Text("Voice Models")', models)
        self.assertIn(
            '.accessibilityIdentifier("iosSettings_voiceModelsBackButton")', models
        )
        self.assertIn('accessibilityIdentifier: "iosSettings_storageRow"', models)
        self.assertNotIn('accessibilityIdentifier: "iosSettings_storageRow"', settings)

        self.assertIn("Toggle(isOn: $isOn)", rows)
        self.assertIn("IOSSettingsCompactToggleStyle(tint: tint)", rows)
        self.assertIn('Picker("Take variation", selection: $selection)', rows)
        self.assertIn("Text(title.uppercased())", rows)
        self.assertIn(".font(.subheadline.weight(.semibold))", rows)
        self.assertNotIn(".toggleStyle(.switch)", rows)
        self.assertIn("var tint: Color = Theme.Brand.silver", rows)
        self.assertIn(".fill(Theme.Surface.hairline)", rows)
        self.assertIn(".stroke(Theme.Surface.panelStroke", rows)
        self.assertNotIn("IOSSettingsReferenceSwitch", rows)
        self.assertIn(
            "return VocelloPresentationText.status(.ready)",
            rows,
        )
        for state in [
            'return "Not Installed"',
            'return "Update Available"',
            'return "Repair Needed"',
            'return "Retry Needed"',
        ]:
            self.assertIn(state, rows)
        self.assertIn('? "Finishing" : "Downloading"', rows)
        self.assertIn('"Cancel"', rows)
        self.assertIn('accessibilityTitle: "Cancel download"', rows)
        self.assertIn('"Remove"', rows)
        self.assertIn('id: "iosModelDelete_\\(model.id)"', rows)
        self.assertIn('.accessibilityIdentifier("iosModelMenu_\\(model.id)")', rows)
        self.assertIn(".frame(minWidth: 44, minHeight: 44)", rows)
        self.assertIn(
            ".frame(width: dynamicTypeSize.isAccessibilitySize ? nil : 112)",
            rows,
        )
        self.assertNotIn(".background(statusTint.opacity(0.10))", rows)
        self.assertIn("visibleActionCount == 1", rows)
        self.assertNotIn("* 0.90", rows)
        self.assertNotIn("modelProgressView(value: 0.94)", rows)
        self.assertNotIn("modelProgressView(value: 0.98)", rows)
        self.assertIn("IOSModelProgressPresentation", rows)
        self.assertIn('accessibilityIdentifier("iosModelPhaseActivity_\\(model.id)")', rows)
        self.assertIn('accessibilityIdentifier("iosModelProgressDetail_\\(model.id)")', rows)
        self.assertNotIn('Image(systemName: "ellipsis.circle")', rows)

        self.assertIn('IOSSettingsSection(title: "Overview")', models)
        self.assertIn('title: "\\(readyModelCount) of \\(TTSModel.all.count) ready"', models)

        self.assertIn("func openVoiceModels()", test_case)
        self.assertIn("func leaveVoiceModels()", test_case)
        self.assertIn('contains: "Ready"', test_case)
        self.assertIn("resetIsolatedDeliveryForFreshLifecycle()", model_download_test)
        self.assertIn("cancelDownload(modelID: modelID)", model_download_test)
        self.assertIn("assertModelActionContract(", model_download_test)
        self.assertIn('status: "Not Installed"', model_download_test)
        self.assertIn('status: "Downloading"', model_download_test)
        self.assertIn('status: "Ready"', model_download_test)
        self.assertIn('element("iosModelCancelDownloadConfirmButton")', model_download_test)
        self.assertIn('element("deleteModelSheet_confirm")', model_download_test)
        self.assertIn("waitForInstalledModel(", model_download_test)
        self.assertIn("stallTimeout: TimeInterval = 300", model_download_test)
        self.assertNotIn("currentProgress >= 0.999", model_download_test)
        self.assertNotIn("progress claimed completion before", model_download_test)
        self.assertNotIn("restoreCanonicalAfterFailedIsolatedRun", model_download_test)
        self.assertIn("observeIndeterminatePhase(modelID: modelID)", model_download_test)
        self.assertIn("progressSample: sample", model_download_test)
        self.assertIn("screenshot: screenshot", model_download_test)
        self.assertIn("let visibleText: String", model_download_test)
        self.assertIn("let detail = sampledProgress?.visibleText", model_download_test)
        self.assertIn('actions = ["Cancel"]', model_download_test)
        self.assertIn("case 95: 0.90", model_download_test)
        self.assertIn("sample.fraction < 1", model_download_test)
        self.assertIn("appFrame: appFrame", model_download_test)
        self.assertNotIn("VocelloUIScreenshot.attach(measured", model_download_test)
        self.assertIn("runDiagnosticScenario", model_download_test)
        self.assertIn("runQueueScenario", model_download_test)
        self.assertIn("runRecoveryScenario", model_download_test)
        runner = (ROOT / "scripts" / "ui_test.sh").read_text(encoding="utf-8")
        self.assertIn('final_run_status="diagnosedFailure"', runner)
        self.assertIn('write_run_metadata "$final_run_status" "$finished_at" 0', runner)
        self.assertIn("DIAGNOSTIC COMPLETE (diagnosedFailure)", runner)
        wait_helper = model_download_test[
            model_download_test.index("private func waitForInstalledModel(") :
            model_download_test.index("private func modelManagementEnvironment")
        ]
        self.assertNotIn("XCTFail", wait_helper)
        self.assertNotIn("VocelloUIWait.exists(installed, timeout: 3_600)", model_download_test)

    def test_successful_ios_ui_build_preserves_matching_symbols(self) -> None:
        runner = (ROOT / "scripts" / "ui_test.sh").read_text(encoding="utf-8")
        test_start = runner.rindex(
            'required_step_run "$step_ledger" xcuitest run_xcodebuild xcb_run test'
        )
        preserve_index = runner.index("\n  if ! preserve_ios_ui_dsym", test_start)
        crash_delta_index = runner.index(
            "\n  if ! required_step_run \"$step_ledger\" crash-delta",
            preserve_index,
        )
        self.assertLess(test_start, preserve_index)
        self.assertLess(preserve_index, crash_delta_index)
        self.assertIn(
            'preserve_ios_dsym "$source" "$destination" "$app/Vocello"',
            runner,
        )

    def test_streaming_cancel_uses_phase_specific_hittable_button_contract(self) -> None:
        canvas = (ROOT / "Sources" / "iOS" / "IOSStudioCanvas.swift").read_text(
            encoding="utf-8"
        )
        player = (
            ROOT
            / "Sources"
            / "iOS"
            / "Studio"
            / "IOSStudioInlinePlayerCard.swift"
        ).read_text(encoding="utf-8")
        test_case = (
            ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSUITestCase.swift"
        ).read_text(encoding="utf-8")

        self.assertIn('.accessibilityIdentifier("textInput_cancelButton")', canvas)
        self.assertIn('.accessibilityIdentifier("studio_livePreview_cancel")', player)
        streaming_start = test_case.index("func startGenerationAndWaitForLivePreview()")
        streaming_end = test_case.index(
            "func startGenerationAndWaitForAutomaticMemoryPressureTerminal()",
            streaming_start,
        )
        streaming_contract = test_case[streaming_start:streaming_end]
        self.assertEqual(
            streaming_contract.count(
                'let liveCancel = element("studio_livePreview_cancel")'
            ),
            2,
        )
        self.assertNotIn('element("textInput_cancelButton")', streaming_contract)

        memory_contract = test_case[streaming_end:]
        self.assertIn(
            'memory-pressure generation to reach a terminal state',
            memory_contract,
        )
        self.assertNotIn(
            'memory-pressure generation to visibly start',
            memory_contract,
        )

        for source in (canvas, player):
            stop_button = source.index('Image(systemName: "stop.fill")')
            identifier = source.index(".accessibilityIdentifier", stop_button)
            button_contract = source[stop_button:identifier]
            self.assertIn(".frame(width: 44, height: 44)", button_contract)
            self.assertIn(".buttonStyle(.plain)", button_contract)
            self.assertNotIn(".onTapGesture", button_contract)

    def test_history_search_targets_the_editable_control(self) -> None:
        test_case = (
            ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSUITestCase.swift"
        ).read_text(encoding="utf-8")
        search_start = test_case.index("func replaceHistorySearch(with query: String)")
        search_end = test_case.index("func historyRows()", search_start)
        search_contract = test_case[search_start:search_end]

        self.assertIn(
            'app.textFields["historySearchField"].firstMatch',
            search_contract,
        )
        self.assertNotIn('element("historySearchField")', search_contract)

    def test_saved_voice_actions_require_filtered_valid_geometry(self) -> None:
        test_case = (
            ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSUITestCase.swift"
        ).read_text(encoding="utf-8")
        start = test_case.index("func revealSavedVoiceControls(")
        end = test_case.index("func historyRows()", start)
        contract = test_case[start:end]

        self.assertIn('app.textFields["voicesSearchField"].firstMatch', contract)
        self.assertIn("VocelloUITextEntry.replace", contract)
        self.assertIn('element("voicesRow_saved_\\(voiceName)")', contract)
        self.assertIn('element("voicesRowMenu_\\(voiceName)")', contract)
        self.assertIn("self.isValidActivationFrame(rowFrame)", contract)
        self.assertIn("self.isValidActivationFrame(menuFrame)", contract)
        self.assertIn("row.isHittable", contract)
        self.assertIn("menu.isHittable", contract)
        self.assertIn("frame.width >= 44", contract)
        self.assertIn("frame.height >= 44", contract)

        for path in [
            ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSSavedVoiceLifecycleUITests.swift",
            ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSControlAuditUITests.swift",
        ]:
            source = path.read_text(encoding="utf-8")
            self.assertIn("revealSavedVoiceControls", source)

    def test_ui_runner_transport_names_are_exact_and_benchmarks_fail_closed(self) -> None:
        runner = (ROOT / "scripts" / "ui_test.sh").read_text(encoding="utf-8")
        suites = {
            "MAC": (
                ROOT / "Tests" / "VocelloMacUITests" / "VocelloMacBenchmarkUITests.swift"
            ).read_text(encoding="utf-8"),
            "IOS": (
                ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSBenchmarkUITests.swift"
            ).read_text(encoding="utf-8"),
        }
        for platform, source in suites.items():
            for suffix in ("RUN_ID", "MODES", "LENGTHS", "WARM", "LABEL"):
                consumer = f"QVOICE_{platform}_BENCH_{suffix}"
                self.assertIn(f"TEST_RUNNER_{consumer}", runner)
                self.assertIn(f'"{consumer}"', source)
            self.assertNotIn("?? \"mac-xcui-benchmark-", source)
            self.assertNotIn("?? \"ios-xcui-benchmark-", source)

        for path in (ROOT / "Tests").glob("*UITests/*.swift"):
            self.assertNotIn(
                'environment["TEST_RUNNER_',
                path.read_text(encoding="utf-8"),
                f"{path.name} must consume Xcode's stripped runner variable name",
            )


if __name__ == "__main__":
    unittest.main()
