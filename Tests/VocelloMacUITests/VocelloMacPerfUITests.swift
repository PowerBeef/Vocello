import XCTest

/// macOS UI-performance scenarios for `scripts/ui_test.sh macos perf`.
///
/// Each scenario launches the app once with the frame probe enabled
/// (`QWENVOICE_UIPERF_FRAME_PROBE=<scenario>`), performs a scripted
/// interaction inside a marked wall-clock window, and terminates. The in-app
/// probe streams 500 ms frame-health rows continuously; the marker line this
/// class prints is what scopes each scenario's measured window
/// (`scripts/check_macos_ui_perf.py` does the join). Scenarios 01-07 are
/// confirmatory-designated; 08 (window resize) and 09 (generation-active)
/// are exploratory by design — resize drags are the flakiest XCUITest
/// surface, and generation duration is model-dependent.
///
/// Method names carry numeric prefixes because XCTest runs alphabetically;
/// generation-active runs last so its thermal load cannot color the pure-UI
/// scenarios.
@MainActor
final class VocelloMacPerfUITests: VocelloMacUITestCase {
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

    private var scenarioEnvironment: [String: String] = [:]

    override var additionalLaunchEnvironment: [String: String] { scenarioEnvironment }

    private func beginScenario(_ name: String, seedHistory: Bool = false) {
        scenarioEnvironment = ["QWENVOICE_UIPERF_FRAME_PROBE": name]
        if seedHistory {
            scenarioEnvironment["QWENVOICE_UIPERF_SEED_HISTORY"] = String(Self.seededHistoryRows)
        }
        beginSession()
        VocelloUICursor.park()
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

    // MARK: - Scenarios

    func test01IdleBaseline() {
        beginScenario("idle-baseline")
        measuredWindow("idle-baseline", actionCount: 0) {
            Thread.sleep(forTimeInterval: 15.0)
        }
    }

    func test02SidebarNavigation() {
        beginScenario("sidebar-navigation")
        let cycle: [VocelloMacScreen] = [
            .customVoice, .voiceDesign, .voiceCloning, .history, .voices, .settings,
        ]
        measuredWindow("sidebar-navigation", actionCount: cycle.count * 3) {
            for _ in 0..<3 {
                for screen in cycle {
                    navigate(to: screen)
                }
            }
        }
    }

    func test03HistoryScroll() {
        beginScenario("history-scroll", seedHistory: true)
        // Sentinel: the seeder finished before we scroll (row 0400 would be
        // absent if the top-up was still running or failed).
        assertHistoryRows(
            matching: String(format: "uiperf-seed-%04d", Self.seededHistoryRows - 1),
            expected: 1
        )
        let search = element("history_searchField", type: .searchField)
        XCTAssertTrue(VocelloUITextEntry.replace(in: search, with: "", timeout: 20))
        let scrollView = app.scrollViews.firstMatch
        XCTAssertTrue(VocelloUIWait.exists(scrollView, timeout: 10))
        VocelloUICursor.park()
        measuredWindow("history-scroll", actionCount: 10) {
            for sweep in 0..<10 {
                scrollView.scroll(byDeltaX: 0, deltaY: sweep.isMultiple(of: 2) ? -1400 : 1400)
                Thread.sleep(forTimeInterval: 0.6)
            }
        }
    }

    func test04HistoryFilter() {
        beginScenario("history-filter", seedHistory: true)
        navigate(to: .history)
        let search = element("history_searchField", type: .searchField)
        XCTAssertTrue(VocelloUIWait.exists(search, timeout: 20))
        measuredWindow("history-filter", actionCount: 6) {
            for _ in 0..<3 {
                XCTAssertTrue(
                    VocelloUITextEntry.replace(in: search, with: "uiperf-seed-03", timeout: 20))
                Thread.sleep(forTimeInterval: 1.0)
                XCTAssertTrue(VocelloUITextEntry.replace(in: search, with: "", timeout: 20))
                Thread.sleep(forTimeInterval: 1.0)
            }
        }
    }

    func test05DeliveryMenu() {
        beginScenario("delivery-menu")
        navigate(to: .customVoice)
        let picker = element("delivery_tonePicker")
        XCTAssertTrue(VocelloUIWait.exists(picker, timeout: 20))
        measuredWindow("delivery-menu", actionCount: 10) {
            for repetition in 0..<10 {
                XCTAssertTrue(VocelloUIPrimaryAction.perform(on: picker, timeout: 10))
                Thread.sleep(forTimeInterval: 0.4)
                if repetition == 4 || repetition == 9 {
                    // Twice, select a different tone so dependent re-render
                    // cost (advisory caption, tint) is inside the window.
                    let target = repetition == 4 ? "Calm" : "Happy"
                    let item = app.menuItems[target].firstMatch
                    if item.exists {
                        item.click()
                    } else {
                        app.typeKey(.escape, modifierFlags: [])
                    }
                } else {
                    app.typeKey(.escape, modifierFlags: [])
                }
                Thread.sleep(forTimeInterval: 0.3)
            }
        }
    }

    func test06SettingsScroll() {
        beginScenario("settings-scroll")
        navigate(to: .settings)
        let scrollView = app.scrollViews.firstMatch
        XCTAssertTrue(VocelloUIWait.exists(scrollView, timeout: 10))
        VocelloUICursor.park()
        measuredWindow("settings-scroll", actionCount: 8) {
            for nudge in 0..<8 {
                scrollView.scroll(byDeltaX: 0, deltaY: nudge.isMultiple(of: 2) ? -900 : 900)
                Thread.sleep(forTimeInterval: 0.6)
            }
        }
    }

    func test07ComposerTyping() {
        beginScenario("composer-typing")
        navigate(to: .customVoice)
        let editor = element("textInput_textEditor")
        XCTAssertTrue(VocelloUIWait.exists(editor, timeout: 20))
        editor.click()
        let burst = "The quick brown fox rehearses a long steady line for interface measurement purposes today. "
        measuredWindow("composer-typing", actionCount: 4) {
            for _ in 0..<4 {
                app.typeText(burst)
                Thread.sleep(forTimeInterval: 0.5)
            }
        }
    }

    /// Exploratory: macOS XCUITest has no window-resize API; the bottom-right
    /// corner drag is the only native mechanism and the flakiest surface in
    /// this suite (individual drags miss nondeterministically even with
    /// cursor parking between presses). The scenario therefore counts
    /// successful resizes across up to 8 alternating attempts and requires at
    /// least one grow and one shrink; only a *size* change counts, so a drag
    /// that merely moved the window cannot masquerade as a resize. On total
    /// failure no marker is emitted and the gate fails loudly on the missing
    /// scenario. `actionCount` reports the observed resize count.
    func test08WindowResize() {
        beginScenario("window-resize")
        let window = app.windows.firstMatch
        XCTAssertTrue(VocelloUIWait.exists(window, timeout: 10))
        var resizes = 0
        var grew = false
        var shrank = false
        let start = Int64(Date().timeIntervalSince1970 * 1000)
        for attempt in 0..<8 {
            let sizeBefore = window.frame.size
            let delta: CGFloat = attempt.isMultiple(of: 2) ? 250 : -250
            let corner = window
                .coordinate(withNormalizedOffset: CGVector(dx: 1.0, dy: 1.0))
                .withOffset(CGVector(dx: -2, dy: -2))
            let target = corner.withOffset(CGVector(dx: delta, dy: delta / 2))
            corner.click(forDuration: 0.3, thenDragTo: target)
            Thread.sleep(forTimeInterval: 0.8)
            if window.frame.size != sizeBefore {
                resizes += 1
                if delta > 0 { grew = true } else { shrank = true }
            }
            // A press at the exact spot where the previous drag released
            // chains into a double-click, which never starts a resize.
            VocelloUICursor.park()
            Thread.sleep(forTimeInterval: 0.4)
            if resizes >= 4 { break }
        }
        let end = Int64(Date().timeIntervalSince1970 * 1000)
        XCTAssertTrue(
            grew && shrank && resizes >= 2,
            "expected at least one grow and one shrink across 8 corner drags; "
                + "observed \(resizes) resizes (grew: \(grew), shrank: \(shrank))"
        )
        VocelloUIPerfScenarioMarker(
            scenario: "window-resize",
            windowStartEpochMS: start,
            windowEndEpochMS: end,
            actionCount: resizes
        ).emit()
    }

    /// Exploratory: UI frame health while the engine renders a real take with
    /// the generation performance gate ON (glass off — the shipped path).
    /// Deliberately not hidden (`HIDE_DURING_TAKE` unset): visible-window
    /// compositing is the subject.
    func test09GenerationActive() {
        beginScenario("generation-active")
        assertVisibleSpeedModelReadiness()
        prepare(mode: .custom)
        let nonce = String(UUID().uuidString.prefix(8))
        replaceScript(with: VocelloUIBenchMatrix.text(for: .short) + " Marker \(nonce).")
        let start = Int64(Date().timeIntervalSince1970 * 1000)
        generateAndWaitForCompletion(mode: .custom, timeout: 300)
        let end = Int64(Date().timeIntervalSince1970 * 1000)
        VocelloUIPerfScenarioMarker(
            scenario: "generation-active",
            windowStartEpochMS: start,
            windowEndEpochMS: end,
            actionCount: 1
        ).emit()
    }
}
