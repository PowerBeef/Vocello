import XCTest

/// iOS UI-performance scenarios for `scripts/ui_test.sh ios perf`, on the
/// paired physical iPhone only.
///
/// Each scenario launches the app once with the frame probe enabled
/// (`QWENVOICE_UIPERF_FRAME_PROBE=<scenario>`), performs a scripted
/// interaction inside a marked wall-clock window, and terminates. The in-app
/// probe streams 500 ms frame-health rows continuously; the marker line this
/// class prints is what scopes each scenario's measured window
/// (`scripts/check_ios_ui_perf.py` does the join). Marker timestamps come
/// from the on-device test runner, so marker and probe share the device
/// clock. Scenarios 01-07 are confirmatory-designated; 08 (player scrub) and
/// 09 (generation-active) are exploratory by design — the scrubber is a
/// custom drag surface whose element-anchored drags re-query per event, and
/// generation duration is model-dependent.
///
/// Method names carry numeric prefixes because XCTest runs alphabetically;
/// generation-active runs last so its thermal load cannot color the pure-UI
/// scenarios.
@MainActor
final class VocelloiOSPerfUITests: VocelloiOSUITestCase {
    private static let seededHistoryRows = 400

    override func setUp() {
        super.setUp()
        continueAfterFailure = false
    }

    override func tearDown() {
        endSession()
        super.tearDown()
    }

    // MARK: - Scenario driver

    private var perfRunID: String {
        // Xcode forwards inherited TEST_RUNNER_* variables to the remote test
        // runner after removing that transport prefix.
        let runnerEnvironment = ProcessInfo.processInfo.environment
        guard let runID = runnerEnvironment["QVOICE_IOS_PERF_RUN_ID"], !runID.isEmpty else {
            XCTFail("QVOICE_IOS_PERF_RUN_ID is required (run through scripts/ui_test.sh ios perf)")
            return ""
        }
        return runID
    }

    private func beginScenario(_ name: String, seedHistory: Bool = false) {
        var environment = [
            "QWENVOICE_UIPERF_FRAME_PROBE": name,
            // Run-scoped device manifest: the checker proves canonical
            // iPhone hardware from diagnostics/<runID>/manifest.json.
            "QVOICE_IOS_DEVICE_RUN_ID": perfRunID,
        ]
        if seedHistory {
            environment["QWENVOICE_UIPERF_SEED_HISTORY"] = String(Self.seededHistoryRows)
        }
        beginSession(additionalEnvironment: environment)
        // Post-launch settle: launch transient and first-layout churn stay
        // out of every marked window.
        Thread.sleep(forTimeInterval: 3.0)
    }

    private func measuredWindow(
        _ name: String,
        actionCount: Int,
        _ body: () -> Void
    ) {
        let start = Int64(Date().timeIntervalSince1970 * 1000)
        body()
        let end = Int64(Date().timeIntervalSince1970 * 1000)
        VocelloUIPerfScenarioMarker(
            scenario: name,
            windowStartEpochMS: start,
            windowEndEpochMS: end,
            actionCount: actionCount
        ).emit()
    }

    /// Vertical sweep through a coordinate anchored on the APPLICATION
    /// element, never on a deep child: an element-addressed gesture
    /// re-resolves its query on every event, and that snapshot walk executes
    /// on the app's main thread (the macOS history-scroll finding). The root
    /// query is shallow, so the measured window contains only the app's own
    /// scroll work. Offsets stay inside 0.30-0.75 so no drag can read as a
    /// system edge swipe or reach the tab dock.
    private func sweep(up: Bool) {
        let start = app.coordinate(
            withNormalizedOffset: CGVector(dx: 0.5, dy: up ? 0.72 : 0.34))
        let end = app.coordinate(
            withNormalizedOffset: CGVector(dx: 0.5, dy: up ? 0.34 : 0.72))
        start.press(forDuration: 0.05, thenDragTo: end)
    }

    /// Seeder-completion sentinel: the highest-index row must be present and
    /// findable through the production search UI before any seeded scenario
    /// measures (mirrors the macOS `assertHistoryRows` sentinel).
    private func assertSeededHistoryReady() {
        replaceHistorySearch(
            with: String(format: "uiperf-seed-%04d", Self.seededHistoryRows - 1))
        XCTAssertTrue(
            VocelloUIWait.condition("the seeded sentinel row to be visible", timeout: 30) {
                self.historyRows().count >= 1
            }
        )
        replaceHistorySearch(with: "")
    }

    // MARK: - Scenarios

    func test01IdleBaseline() {
        beginScenario("ios-idle-baseline")
        measuredWindow("ios-idle-baseline", actionCount: 0) {
            Thread.sleep(forTimeInterval: 15.0)
        }
    }

    func test02TabNavigation() {
        beginScenario("ios-tab-navigation")
        let cycle: [VocelloiOSTab] = [.voices, .history, .settings, .studio]
        measuredWindow("ios-tab-navigation", actionCount: cycle.count * 3) {
            for _ in 0..<3 {
                for tab in cycle {
                    select(tab: tab)
                }
            }
        }
    }

    func test03HistoryScroll() {
        beginScenario("ios-history-scroll", seedHistory: true)
        assertSeededHistoryReady()
        measuredWindow("ios-history-scroll", actionCount: 10) {
            for sweepIndex in 0..<10 {
                sweep(up: sweepIndex.isMultiple(of: 2))
                Thread.sleep(forTimeInterval: 0.6)
            }
        }
    }

    func test04VoicesScroll() {
        beginScenario("ios-voices-scroll")
        select(tab: .voices)
        XCTAssertTrue(VocelloUIWait.exists(element("screen_voices"), timeout: 20))
        measuredWindow("ios-voices-scroll", actionCount: 8) {
            for sweepIndex in 0..<8 {
                sweep(up: sweepIndex.isMultiple(of: 2))
                Thread.sleep(forTimeInterval: 0.6)
            }
        }
    }

    func test05SettingsScroll() {
        beginScenario("ios-settings-scroll")
        select(tab: .settings)
        XCTAssertTrue(VocelloUIWait.exists(element("iosSettings_autoPlayToggle"), timeout: 20))
        measuredWindow("ios-settings-scroll", actionCount: 8) {
            for sweepIndex in 0..<8 {
                sweep(up: sweepIndex.isMultiple(of: 2))
                Thread.sleep(forTimeInterval: 0.6)
            }
        }
    }

    func test06ComposerTyping() {
        beginScenario("ios-composer-typing")
        let editor = element("textInput_textEditor")
        XCTAssertTrue(VocelloUIWait.exists(editor, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: editor, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("software keyboard to present", timeout: 15) {
                self.app.keyboards.firstMatch.exists
            }
        )
        // 4 x 94 chars stays far below the 900-char long-form routing cap.
        let burst = "The quick brown fox rehearses a long steady line for interface measurement purposes today. "
        measuredWindow("ios-composer-typing", actionCount: 4) {
            for _ in 0..<4 {
                editor.typeText(burst)
                Thread.sleep(forTimeInterval: 0.5)
            }
        }
    }

    func test07SheetPresentDismiss() {
        beginScenario("ios-sheet-present-dismiss", seedHistory: true)
        assertSeededHistoryReady()
        let row = historyRows().firstMatch
        XCTAssertTrue(VocelloUIWait.exists(row, timeout: 20))
        let player = element("iosPlayer_playPause")
        let close = element("iosPlayer_close")
        // Pre-warm one present/dismiss outside the window so first-open
        // resource loading (waveform decode, player setup) stays out of the
        // steady-state measurement.
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: row, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(player, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: close, timeout: 20))
        XCTAssertTrue(VocelloUIWait.disappears(player, timeout: 20))
        measuredWindow("ios-sheet-present-dismiss", actionCount: 12) {
            for _ in 0..<6 {
                XCTAssertTrue(VocelloUIPrimaryAction.perform(on: row, timeout: 20))
                XCTAssertTrue(VocelloUIWait.exists(player, timeout: 20))
                XCTAssertTrue(VocelloUIPrimaryAction.perform(on: close, timeout: 20))
                XCTAssertTrue(VocelloUIWait.disappears(player, timeout: 20))
            }
        }
    }

    /// Exploratory: the scrubber is a custom DragGesture surface (not a
    /// UISlider), so scrubbing needs element-anchored coordinate drags that
    /// re-query per event — residual harness query cost is inside the window
    /// by construction.
    func test08PlayerScrub() {
        beginScenario("ios-player-scrub", seedHistory: true)
        assertSeededHistoryReady()
        let row = historyRows().firstMatch
        XCTAssertTrue(VocelloUIWait.exists(row, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: row, timeout: 20))
        let scrubber = element("iosPlayer_scrubber")
        XCTAssertTrue(VocelloUIWait.exists(scrubber, timeout: 20))
        measuredWindow("ios-player-scrub", actionCount: 8) {
            for drag in 0..<8 {
                let forward = drag.isMultiple(of: 2)
                let from = scrubber.coordinate(
                    withNormalizedOffset: CGVector(dx: forward ? 0.15 : 0.85, dy: 0.5))
                let to = scrubber.coordinate(
                    withNormalizedOffset: CGVector(dx: forward ? 0.85 : 0.15, dy: 0.5))
                from.press(forDuration: 0.1, thenDragTo: to)
                Thread.sleep(forTimeInterval: 0.4)
            }
        }
    }

    /// Exploratory: UI frame health while the in-process engine renders a
    /// real take on the phone. Duration is model-dependent, so the window is
    /// the whole visible generation.
    func test09GenerationActive() {
        beginScenario("ios-generation-active")
        assertVisibleModelReadiness()
        prepare(mode: .custom)
        let nonce = String(UUID().uuidString.prefix(8))
        replaceScript(with: VocelloUIBenchMatrix.text(for: .short) + " Marker \(nonce).")
        let start = Int64(Date().timeIntervalSince1970 * 1000)
        _ = generateAndWaitForCompletedPlayer(timeout: 300)
        let end = Int64(Date().timeIntervalSince1970 * 1000)
        VocelloUIPerfScenarioMarker(
            scenario: "ios-generation-active",
            windowStartEpochMS: start,
            windowEndEpochMS: end,
            actionCount: 1
        ).emit()
    }
}
