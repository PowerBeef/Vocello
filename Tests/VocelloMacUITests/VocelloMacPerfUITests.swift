import XCTest

/// macOS UI-performance scenarios for `scripts/ui_test.sh macos perf`.
///
/// Each scenario launches the app once with the frame probe enabled
/// (`QWENVOICE_UIPERF_FRAME_PROBE=<scenario>`), performs a scripted
/// interaction inside a marked wall-clock window, and terminates. The in-app
/// probe streams 500 ms frame-health rows continuously; the marker line this
/// class prints is what scopes each scenario's measured window
/// (`scripts/check_macos_ui_perf.py` does the join). The thresholds contract
/// owns scenario designation: History, resizing and active generation remain
/// exploratory. Accessibility work runs on the app's main thread, and probe
/// blocks touching a measured window can include setup or teardown work.
///
/// Method names carry numeric prefixes because XCTest runs alphabetically;
/// generation-active runs last so its thermal load cannot color the pure-UI
/// scenarios, and sidebar-navigation-warms, which loads models, runs just
/// before it.
///
/// sidebar-navigation measures pure UI with proactive warms suppressed
/// (`QWENVOICE_SUPPRESS_WARMUP`, audit #33); sidebar-navigation-warms repeats
/// it with the product's warms on (exploratory), and harness-control makes the
/// same readiness queries with no click, so the harness's accessibility cost is
/// measured on its own (audit #32). Every scenario prints its setup stamps
/// (`VOCELLO_UIPERF_SETUP=`, audit #82).
@MainActor
final class VocelloMacPerfUITests: VocelloMacUITestCase {
    private static let seededHistoryRows = 400

    override func setUp() {
        super.setUp()
        continueAfterFailure = false
    }

    // MARK: - Scenario driver

    private var scenarioEnvironment: [String: String] = [:]
    /// The running scenario's setup stamps (audit #82).
    private var setupStamps: [String: Int64] = [:]
    private var setupScenario = ""

    override var additionalLaunchEnvironment: [String: String] { scenarioEnvironment }

    /// `suppressWarmup` sets the registered `QWENVOICE_SUPPRESS_WARMUP`, so
    /// selection and draft changes schedule no model warms (audit #33).
    private func beginScenario(_ name: String, seedHistory: Bool = false, suppressWarmup: Bool = false) {
        setupScenario = name
        setupStamps = ["launchStart": Self.epochMS()]
        scenarioEnvironment = ["QWENVOICE_UIPERF_FRAME_PROBE": name]
        if seedHistory {
            scenarioEnvironment["QWENVOICE_UIPERF_SEED_HISTORY"] = String(Self.seededHistoryRows)
        }
        if suppressWarmup {
            scenarioEnvironment["QWENVOICE_SUPPRESS_WARMUP"] = "1"
        }
        beginSession()
        setupStamps["launchReady"] = Self.epochMS()
        VocelloUICursor.park()
        // Post-launch settle: launch transient and first-layout churn stay
        // out of every marked window.
        Thread.sleep(forTimeInterval: 3.0)
        setupStamps["settled"] = Self.epochMS()
    }

    /// Prints the scenario's marker and, with it, where the scenario's lane
    /// time went before and during its window (audit #82).
    private func emit(_ marker: VocelloUIPerfScenarioMarker) {
        marker.emit()
        setupStamps["windowStart"] = marker.windowStartEpochMS
        setupStamps["windowEnd"] = marker.windowEndEpochMS
        VocelloUIPerfSetupMarker(scenario: setupScenario, stamps: setupStamps).emit()
    }

    private func measuredWindow(
        _ name: String,
        actionCount: Int,
        _ body: () -> Void
    ) {
        let start = Self.epochMS()
        body()
        let end = Self.epochMS()
        emit(VocelloUIPerfScenarioMarker(
            scenario: name,
            windowStartEpochMS: start,
            windowEndEpochMS: end,
            actionCount: actionCount
        ))
    }

    /// A measured window made of repeated cycles; the marker carries each
    /// cycle's sub-window so the checker reports within-run spread (audit #34(b)),
    /// and the phases `phaseLog` collected (audit #32).
    private func measuredCycles(
        _ name: String,
        cycles: Int,
        actionsPerCycle: Int,
        phaseLog: VocelloPerfPhaseLog? = nil,
        _ body: (Int) -> Void
    ) {
        var marks: [VocelloUIPerfCycle] = []
        let start = Self.epochMS()
        for cycle in 0..<cycles {
            let cycleStart = Self.epochMS()
            body(cycle)
            marks.append(VocelloUIPerfCycle(startEpochMS: cycleStart, endEpochMS: Self.epochMS()))
        }
        let end = Self.epochMS()
        emit(VocelloUIPerfScenarioMarker(
            scenario: name,
            windowStartEpochMS: start,
            windowEndEpochMS: end,
            actionCount: cycles * actionsPerCycle,
            cycles: marks,
            phases: phaseLog?.phases
        ))
    }

    private static let navigationCycle: [VocelloMacScreen] = [
        .customVoice, .voiceDesign, .voiceCloning, .history, .voices, .settings,
    ]

    /// The sidebar items `navigate(to:)` clicks for one destination: the Studio
    /// item before a Studio mode, then the destination's own item.
    private func navigationTargets(_ screen: VocelloMacScreen) -> [XCUIElement] {
        var targets: [XCUIElement] = []
        if [.customVoice, .voiceDesign, .voiceCloning].contains(screen) {
            targets.append(button("sidebar_studio"))
        }
        targets.append(button(screen.sidebarID))
        return targets
    }

    /// `navigate(to:)` with its phases timed apart (audit #32): each readiness
    /// poll is a `query` phase, each click an `action` phase, and the wait for
    /// the destination to show and read selected a `verify` phase. The same
    /// identifiers, conditions and clicks as the base class's navigation.
    private func navigateMarkingPhases(to screen: VocelloMacScreen, log: VocelloPerfPhaseLog) {
        let targets = navigationTargets(screen)
        for target in targets {
            let queryStart = Self.epochMS()
            XCTAssertTrue(
                VocelloUIWait.condition("element to become hittable for its primary action: \(target)", timeout: 20) {
                    target.exists && target.isEnabled && target.isHittable
                }
            )
            let clickStart = Self.epochMS()
            log.append("query", from: queryStart, to: clickStart)
            target.click()
            log.append("action", from: clickStart, to: Self.epochMS())
        }
        let verifyStart = Self.epochMS()
        XCTAssertTrue(VocelloUIWait.exists(element(screen.screenID), timeout: 20))
        let sidebar = targets[targets.count - 1]
        XCTAssertTrue(
            VocelloUIWait.condition("sidebar destination to become selected", timeout: 10) {
                sidebar.isSelected
            }
        )
        log.append("verify", from: verifyStart, to: Self.epochMS())
    }

    private func sidebarNavigation(_ name: String) {
        let log = VocelloPerfPhaseLog()
        measuredCycles(
            name, cycles: 3, actionsPerCycle: Self.navigationCycle.count, phaseLog: log
        ) { _ in
            for screen in Self.navigationCycle {
                navigateMarkingPhases(to: screen, log: log)
            }
        }
    }

    private static func epochMS() -> Int64 {
        Int64(Date().timeIntervalSince1970 * 1000)
    }

    // MARK: - Scenarios

    func test01IdleBaseline() {
        beginScenario("idle-baseline")
        measuredWindow("idle-baseline", actionCount: 0) {
            Thread.sleep(forTimeInterval: 15.0)
        }
    }

    /// Pure UI (audit #33): proactive warms suppressed, so the window measures
    /// navigation, not the tier's warm-and-cancel churn.
    func test02SidebarNavigation() {
        beginScenario("sidebar-navigation", suppressWarmup: true)
        sidebarNavigation("sidebar-navigation")
    }

    /// Exploratory control (audit #32): the same readiness queries as
    /// sidebar-navigation (each destination's sidebar items, the destination's
    /// screen and the selection read) with no click, on an app that stays on
    /// one screen. The window's hitch time is the harness's accessibility cost
    /// alone; every span is a `query` phase.
    func test02aHarnessControl() {
        beginScenario("harness-control", suppressWarmup: true)
        let log = VocelloPerfPhaseLog()
        measuredCycles(
            "harness-control", cycles: 3, actionsPerCycle: Self.navigationCycle.count, phaseLog: log
        ) { _ in
            for screen in Self.navigationCycle {
                let queryStart = Self.epochMS()
                let targets = navigationTargets(screen)
                for target in targets {
                    _ = target.exists && target.isEnabled && target.isHittable
                }
                _ = element(screen.screenID).exists
                _ = targets[targets.count - 1].isSelected
                log.append("query", from: queryStart, to: Self.epochMS())
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
        // Scroll through a WINDOW-anchored coordinate, never through
        // `scrollViews.firstMatch`: an element-addressed scroll re-resolves
        // its query on every event, and that snapshot walk (elementType
        // checked across the 400-row accessibility tree) executes on the
        // app's MAIN thread — a Time Profiler sample (2026-08-05) showed it
        // was the entire "3.1 s History stall" the first baseline reported.
        // The shallow window query reduces this cost; it does not eliminate
        // accessibility work or boundary-block contamination from the report.
        let window = app.windows.firstMatch
        XCTAssertTrue(VocelloUIWait.exists(window, timeout: 10))
        let listPoint = window.coordinate(withNormalizedOffset: CGVector(dx: 0.62, dy: 0.5))
        VocelloUICursor.park()
        measuredWindow("history-scroll", actionCount: 10) {
            for sweep in 0..<10 {
                listPoint.scroll(byDeltaX: 0, deltaY: sweep.isMultiple(of: 2) ? -1400 : 1400)
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
        measuredCycles("delivery-menu", cycles: 10, actionsPerCycle: 1) { repetition in
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

    func test06SettingsScroll() {
        beginScenario("settings-scroll")
        openSettingsCategory("modelsFiles")
        // Window-anchored coordinate for the same reason as history-scroll:
        // element-addressed scrolls re-query the tree per event on the
        // app's main thread.
        let window = app.windows.firstMatch
        XCTAssertTrue(VocelloUIWait.exists(window, timeout: 10))
        let listPoint = window.coordinate(withNormalizedOffset: CGVector(dx: 0.62, dy: 0.5))
        VocelloUICursor.park()
        measuredWindow("settings-scroll", actionCount: 8) {
            for nudge in 0..<8 {
                listPoint.scroll(byDeltaX: 0, deltaY: nudge.isMultiple(of: 2) ? -900 : 900)
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
        measuredCycles("composer-typing", cycles: 4, actionsPerCycle: 1) { _ in
            app.typeText(burst)
            Thread.sleep(forTimeInterval: 0.5)
        }
    }

    /// Exploratory: macOS XCUITest has no window-resize API; an edge drag is
    /// the only native mechanism and the flakiest surface in this suite
    /// (individual drags miss nondeterministically even with cursor parking
    /// between presses). The drag starts on the right edge's midpoint: the
    /// bottom-right corner used until 2026-09-15 sits inside the window's
    /// rounded corner on macOS 27, where the press lands on the desktop and
    /// no drag ever resized. The scenario counts successful resizes across up
    /// to 8 alternating attempts and requires at least one grow and one
    /// shrink; only a *size* change counts, so a drag that merely moved the
    /// window cannot masquerade as a resize. On total failure no marker is
    /// emitted and the gate fails loudly on the missing scenario.
    /// `actionCount` reports the observed resize count.
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
            let edge = window
                .coordinate(withNormalizedOffset: CGVector(dx: 1.0, dy: 0.5))
                .withOffset(CGVector(dx: -1, dy: 0))
            let target = edge.withOffset(CGVector(dx: delta, dy: 0))
            edge.click(forDuration: 0.3, thenDragTo: target)
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
            "expected at least one grow and one shrink across 8 edge drags; "
                + "observed \(resizes) resizes (grew: \(grew), shrank: \(shrank))"
        )
        emit(VocelloUIPerfScenarioMarker(
            scenario: "window-resize",
            windowStartEpochMS: start,
            windowEndEpochMS: end,
            actionCount: resizes
        ))
    }

    /// Exploratory (audit #33): sidebar-navigation with the product's proactive
    /// warms on, so the tier's warm-and-cancel churn during navigation is
    /// measured apart from the pure-UI scenario. It loads models, so it runs
    /// after every pure-UI scenario, just before generation-active.
    func test08bSidebarNavigationWarms() {
        beginScenario("sidebar-navigation-warms")
        sidebarNavigation("sidebar-navigation-warms")
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
        // Readiness polling is harness work; the window opens once the app is
        // ready and closes when the take completes.
        assertReadyToGenerate(mode: .custom)
        let start = Int64(Date().timeIntervalSince1970 * 1000)
        generateAndWaitForCompletion(mode: .custom, timeout: 300)
        let end = Int64(Date().timeIntervalSince1970 * 1000)
        emit(VocelloUIPerfScenarioMarker(
            scenario: "generation-active",
            windowStartEpochMS: start,
            windowEndEpochMS: end,
            actionCount: 1
        ))
    }
}

/// Named spans of one measured window, in wall-clock epoch milliseconds
/// (audit #32); appended in order, so they are disjoint and ordered.
@MainActor
final class VocelloPerfPhaseLog {
    private(set) var phases: [VocelloUIPerfPhase] = []

    func append(_ name: String, from start: Int64, to end: Int64) {
        phases.append(VocelloUIPerfPhase(name: name, startEpochMS: start, endEpochMS: max(start, end)))
    }
}
