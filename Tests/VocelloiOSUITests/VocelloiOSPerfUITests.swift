import CoreGraphics
import Foundation
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
/// clock.
///
/// Snapshot-free posture (matching `VocelloMacPerfUITests` BKL-77 / RF-61):
/// - Pure-UI scenarios (`01`–`08`) suppress proactive model prewarm via the
///   registered `QVOICE_IOS_DISABLE_PROACTIVE_PREFETCH=1` knob so they measure
///   UI responsiveness, not background MLX load churn.
/// - Seeded History scenarios (`03`, `03b`, `03c`, `07`, `08`) isolate their
///   database in a dedicated per-row-count `QVOICE_APP_SUPPORT_DIR` child so
///   previous lanes cannot grow the archive past the 500-row page boundary
///   (RF-61 T11), and stamp `archiveCount` in `VOCELLO_UIPERF_SETUP=`.
/// - Repeated interactions resolve settled frames relative to `app.frame`
///   once *outside* the measured window, record `VocelloPerfPhaseLog` spans
///   (`action` vs `query`), and prove non-vacuous post-window ground truth,
///   keeping accessibility snapshot walks out of the measured frames.
///
/// Method names carry numeric prefixes because XCTest runs alphabetically;
/// generation-active runs last so its thermal load cannot color the pure-UI
/// scenarios.
@MainActor
final class VocelloiOSPerfUITests: VocelloiOSUITestCase {
    override class var keepsSteadyWaitCadence: Bool { true }

    private static let seededHistoryRows = 400
    /// More than one History page (500), so a search is answered by the
    /// database rather than the loaded page (RF-61, audit finding A1).
    private static let pagedHistoryRows = 700

    private static func historyProfileName(rows: Int) -> String {
        "ios-uiperf-history-rows-\(rows)"
    }

    override func setUp() {
        super.setUp()
        continueAfterFailure = false
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

    /// The running scenario's setup stamps (audit #82).
    private var setupStamps: [String: Int64] = [:]
    private var setupScenario = ""
    private var setupArchiveCount: Int?

    private static func epochMS() -> Int64 {
        Int64(Date().timeIntervalSince1970 * 1000)
    }

    private func beginScenario(
        _ name: String,
        seedHistoryRows: Int? = nil,
        suppressWarmup: Bool = false
    ) {
        setupScenario = name
        setupStamps = ["launchStart": Self.epochMS()]
        setupArchiveCount = seedHistoryRows
        var environment = [
            "QWENVOICE_UIPERF_FRAME_PROBE": name,
            // Run-scoped device manifest: the checker proves canonical
            // iPhone hardware from diagnostics/<runID>/manifest.json.
            "QVOICE_IOS_DEVICE_RUN_ID": perfRunID,
        ]
        if let seedHistoryRows {
            environment["QWENVOICE_UIPERF_SEED_HISTORY"] = String(seedHistoryRows)
            environment["QVOICE_APP_SUPPORT_DIR"] = Self.historyProfileName(rows: seedHistoryRows)
        }
        if suppressWarmup {
            environment["QVOICE_IOS_DISABLE_PROACTIVE_PREFETCH"] = "1"
        }
        beginSession(additionalEnvironment: environment)
        setupStamps["launchReady"] = Self.epochMS()
        // Post-launch settle: launch transient and first-layout churn stay
        // out of every marked window.
        Thread.sleep(forTimeInterval: 3.0)
        setupStamps["settled"] = Self.epochMS()
    }

    /// Prints the scenario's marker and, with it, where the scenario's lane
    /// time went before and during its window (audit #82).
    ///
    /// Waits 0.65 s *after* `windowEnd` is stamped so `IOSUIPerfFrameProbe`'s
    /// straddling 500 ms `CADisplayLink` block flushes to disk before `tearDown`
    /// calls `app.terminate()` (which does not deliver `willTerminate`).
    private func emit(_ marker: VocelloUIPerfScenarioMarker) {
        marker.emit()
        setupStamps["windowStart"] = marker.windowStartEpochMS
        setupStamps["windowEnd"] = marker.windowEndEpochMS
        VocelloUIPerfSetupMarker(
            scenario: setupScenario,
            stamps: setupStamps,
            archiveCount: setupArchiveCount
        ).emit()
        Thread.sleep(forTimeInterval: 0.65)
    }

    private func measuredWindow(
        _ name: String,
        actionCount: Int,
        _ body: () -> Void
    ) {
        let start = Self.epochMS()
        VocelloUIWait.withSteadyCadence(body)
        let end = Self.epochMS()
        emit(VocelloUIPerfScenarioMarker(
            scenario: name,
            windowStartEpochMS: start,
            windowEndEpochMS: end,
            actionCount: actionCount
        ))
    }

    /// A measured window made of repeated cycles; the marker carries each
    /// cycle's sub-window so the checker reports within-run spread, and any
    /// phases `phaseLog` collected (matching `VocelloMacPerfUITests`).
    private func measuredCycles(
        _ name: String,
        cycles: Int,
        actionsPerCycle: Int,
        phaseLog: VocelloPerfPhaseLog? = nil,
        _ body: (Int) -> Void
    ) {
        var marks: [VocelloUIPerfCycle] = []
        let start = Self.epochMS()
        VocelloUIWait.withSteadyCadence {
            for cycle in 0..<cycles {
                let cycleStart = Self.epochMS()
                body(cycle)
                marks.append(VocelloUIPerfCycle(startEpochMS: cycleStart, endEpochMS: Self.epochMS()))
            }
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

    /// Waits for `element` to exist, become hittable, and hold an identical
    /// non-empty frame across two reads 0.15 s apart so sheet slide-in or
    /// layout animations finish before coordinates are frozen.
    private func settledFrame(of target: XCUIElement, description: String) -> CGRect {
        XCTAssertTrue(VocelloUIWait.exists(target, timeout: 20), "\(description) must exist")
        XCTAssertTrue(
            VocelloUIWait.condition("\(description) to become hittable", timeout: 20) {
                target.exists && target.isHittable
            }
        )
        var previous = target.frame
        for _ in 0..<12 {
            RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.15))
            let current = target.frame
            if current == previous, current.width > 0, current.height > 0 {
                return current
            }
            previous = current
        }
        XCTAssertGreaterThan(previous.width, 0, "\(description) frame width must be positive")
        XCTAssertGreaterThan(previous.height, 0, "\(description) frame height must be positive")
        return previous
    }

    /// Anchors a screen-space point directly on `app` relative to `app.frame`
    /// (matching `VocelloMacPerfUITests` window-offset anchoring), so tapping or
    /// dragging inside the measured window issues zero accessibility queries.
    private func rootCoordinate(for point: CGPoint) -> XCUICoordinate {
        let appFrame = app.frame
        XCTAssertGreaterThan(appFrame.width, 0)
        XCTAssertGreaterThan(appFrame.height, 0)
        return app.coordinate(withNormalizedOffset: .zero).withOffset(
            CGVector(dx: point.x - appFrame.minX, dy: point.y - appFrame.minY)
        )
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
    ///
    /// Drives the search field directly rather than through
    /// `replaceHistorySearch`: typing must wait for the software keyboard to
    /// finish presenting (keystrokes fired during the presentation animation
    /// drop silently — the first device run failed exactly there), the token
    /// is digits-only so live autocorrection cannot rewrite it at a word
    /// boundary, and clearing is proven by the filter dropping — an empty
    /// `TextField` reports its placeholder as `value`, so `value == ""` can
    /// never confirm a clear.
    private func assertSeededHistoryReady(rows: Int) {
        select(tab: .history)
        let searchField = app.textFields["historySearchField"].firstMatch
        XCTAssertTrue(VocelloUIWait.exists(searchField, timeout: 30))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: searchField, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("software keyboard to present", timeout: 15) {
                self.app.keyboards.firstMatch.exists
            }
        )
        let token = unsafe String(format: "%04d", rows - 1)
        searchField.typeText(token)
        XCTAssertTrue(
            VocelloUIWait.condition("History search to match the sentinel token", timeout: 15) {
                (searchField.value as? String) == token
            }
        )
        XCTAssertTrue(
            VocelloUIWait.condition("the seeded sentinel row to be visible", timeout: 30) {
                self.historyRows().count >= 1
            }
        )
        searchField.typeText(
            String(repeating: XCUIKeyboardKey.delete.rawValue, count: token.count))
        XCTAssertTrue(
            VocelloUIWait.condition("History filter to clear", timeout: 15) {
                self.historyRows().count > 1
            }
        )
        // Submit dismisses the keyboard (the field's submit label is Search),
        // so no keyboard overlays the measured windows that follow.
        searchField.typeText("\n")
        XCTAssertTrue(
            VocelloUIWait.condition("software keyboard to dismiss", timeout: 15) {
                !self.app.keyboards.firstMatch.exists
            }
        )
    }

    private func runHistoryFilter(scenario: String, rows: Int, query: String) {
        beginScenario(scenario, seedHistoryRows: rows, suppressWarmup: true)
        assertSeededHistoryReady(rows: rows)
        let searchField = app.textFields["historySearchField"].firstMatch
        XCTAssertTrue(VocelloUIWait.exists(searchField, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: searchField, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("software keyboard to present", timeout: 15) {
                self.app.keyboards.firstMatch.exists
            }
        )
        Thread.sleep(forTimeInterval: 1.0)
        let clearSequence = String(repeating: XCUIKeyboardKey.delete.rawValue, count: query.count)
        let log = VocelloPerfPhaseLog()
        // Use `app.typeText` rather than `searchField.typeText` so XCUITest does
        // not walk the 400/700-row accessibility tree on every keystroke inside
        // the measured window.
        measuredCycles(scenario, cycles: 3, actionsPerCycle: 2, phaseLog: log) { _ in
            let actionStart = Self.epochMS()
            app.typeText(query)
            Thread.sleep(forTimeInterval: 1.0)
            app.typeText(clearSequence)
            Thread.sleep(forTimeInterval: 1.0)
            log.append("action", from: actionStart, to: Self.epochMS())
        }
        // Post-window ground-truth check: verify `app.typeText` still reaches
        // `historySearchField` and filters rows, then clear and dismiss keyboard.
        app.typeText(query)
        XCTAssertTrue(
            VocelloUIWait.condition("History search to receive post-window query", timeout: 15) {
                (searchField.value as? String) == query
            }
        )
        XCTAssertTrue(
            VocelloUIWait.condition("History filter to display matching rows", timeout: 15) {
                self.historyRows().count >= 1
            }
        )
        app.typeText(clearSequence)
        XCTAssertTrue(
            VocelloUIWait.condition("History filter to clear after check", timeout: 15) {
                (searchField.value as? String) != query && self.historyRows().count > 1
            }
        )
        app.typeText("\n")
        XCTAssertTrue(
            VocelloUIWait.condition("History keyboard to dismiss", timeout: 15) {
                !self.app.keyboards.firstMatch.exists
            }
        )
    }

    // MARK: - Scenarios

    func test01IdleBaseline() {
        beginScenario("ios-idle-baseline", suppressWarmup: true)
        measuredWindow("ios-idle-baseline", actionCount: 0) {
            Thread.sleep(forTimeInterval: 15.0)
        }
    }

    func test02TabNavigation() {
        beginScenario("ios-tab-navigation", suppressWarmup: true)
        // End on `.settings` (not `.studio`, which `beginSession` starts on) so
        // the post-window selection assertion proves root-coordinate taps worked.
        let cycle: [VocelloiOSTab] = [.voices, .history, .studio, .settings]
        XCTAssertFalse(element(VocelloiOSTab.settings.identifier).isSelected)
        var tabCoordinates: [XCUICoordinate] = []
        tabCoordinates.reserveCapacity(cycle.count)
        for tab in cycle {
            let buttonFrame = settledFrame(of: element(tab.identifier), description: tab.identifier)
            tabCoordinates.append(
                rootCoordinate(for: CGPoint(x: buttonFrame.midX, y: buttonFrame.midY))
            )
        }
        let log = VocelloPerfPhaseLog()
        measuredCycles("ios-tab-navigation", cycles: 3, actionsPerCycle: cycle.count, phaseLog: log) { _ in
            for coordinate in tabCoordinates {
                let actionStart = Self.epochMS()
                coordinate.tap()
                Thread.sleep(forTimeInterval: 0.35)
                log.append("action", from: actionStart, to: Self.epochMS())
            }
        }
        XCTAssertTrue(
            VocelloUIWait.condition("Settings tab selected after navigation cycles", timeout: 10) {
                self.element(VocelloiOSTab.settings.identifier).isSelected
            }
        )
    }

    /// Exploratory control (mirroring macOS `harness-control`, audit #32):
    /// performs the tab readiness queries with no tap, on an app that stays on
    /// Studio. Every span is a `query` phase, isolating XCTest's accessibility
    /// snapshot cost on the iPhone.
    func test02aHarnessControl() {
        beginScenario("ios-harness-control", suppressWarmup: true)
        let cycle: [VocelloiOSTab] = [.voices, .history, .studio, .settings]
        let log = VocelloPerfPhaseLog()
        measuredCycles("ios-harness-control", cycles: 3, actionsPerCycle: cycle.count, phaseLog: log) { _ in
            for tab in cycle {
                let queryStart = Self.epochMS()
                let button = element(tab.identifier)
                _ = button.exists && button.isEnabled && button.isHittable
                _ = button.isSelected
                log.append("query", from: queryStart, to: Self.epochMS())
            }
        }
    }

    func test03HistoryScroll() {
        beginScenario("ios-history-scroll", seedHistoryRows: Self.seededHistoryRows, suppressWarmup: true)
        assertSeededHistoryReady(rows: Self.seededHistoryRows)
        measuredWindow("ios-history-scroll", actionCount: 10) {
            for sweepIndex in 0..<10 {
                sweep(up: sweepIndex.isMultiple(of: 2))
                Thread.sleep(forTimeInterval: 0.6)
            }
        }
    }

    func test03bHistoryFilter() {
        // "-03" matches strictly `uiperf-seed-0300`..`0399` (100 rows) without autocorrection.
        runHistoryFilter(scenario: "ios-history-filter", rows: Self.seededHistoryRows, query: "-03")
    }

    /// The same filter journey over 700 rows (past the 500-row page): "-06"
    /// matches strictly `uiperf-seed-0600`..`0699` (all outside the newest
    /// 500-row page), forcing SQLite-backed queries (RF-61, audit finding A1).
    func test03cHistoryFilterPaged() {
        runHistoryFilter(scenario: "ios-history-filter-paged", rows: Self.pagedHistoryRows, query: "-06")
    }

    func test04VoicesScroll() {
        beginScenario("ios-voices-scroll", suppressWarmup: true)
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
        beginScenario("ios-settings-scroll", suppressWarmup: true)
        openSettingsRoot()
        XCTAssertTrue(VocelloUIWait.exists(element("iosSettings_audioRow"), timeout: 20))
        measuredWindow("ios-settings-scroll", actionCount: 8) {
            for sweepIndex in 0..<8 {
                sweep(up: sweepIndex.isMultiple(of: 2))
                Thread.sleep(forTimeInterval: 0.6)
            }
        }
    }

    func test06ComposerTyping() {
        beginScenario("ios-composer-typing", suppressWarmup: true)
        // Start from a clean draft so prior Studio text cannot push 4 bursts
        // past the 900-char long-form routing cap mid-measurement.
        replaceScript(with: "")
        let editor = element("textInput_textEditor")
        XCTAssertTrue(VocelloUIWait.exists(editor, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: editor, timeout: 20))
        XCTAssertTrue(
            VocelloUIWait.condition("software keyboard to present", timeout: 15) {
                self.app.keyboards.firstMatch.exists
            }
        )
        // Let the keyboard slide-in animation finish so presentation frames do
        // not spill into cycle 0 or drop leading characters of the first burst.
        Thread.sleep(forTimeInterval: 1.0)
        // 4 x 91 chars (364 total) stays far below the 900-char long-form routing cap.
        let burst = "The quick brown fox rehearses a long steady line for interface measurement purposes today. "
        let log = VocelloPerfPhaseLog()
        // Focus is established above; type via `app.typeText` (matching macOS
        // `test07ComposerTyping`) so XCUITest does not re-query the editor tree
        // on every burst inside the measured window.
        measuredCycles("ios-composer-typing", cycles: 4, actionsPerCycle: 1, phaseLog: log) { _ in
            let actionStart = Self.epochMS()
            app.typeText(burst)
            Thread.sleep(forTimeInterval: 0.5)
            log.append("action", from: actionStart, to: Self.epochMS())
        }
        // Post-window ground-truth check + keyboard dismissal so teardown tab
        // navigation (e.g. App Language restore) is never blocked by the keyboard.
        let expectedFragment = burst.trimmingCharacters(in: .whitespaces)
        XCTAssertTrue(
            VocelloUIWait.condition("composer to contain typed bursts", timeout: 10) {
                (editor.value as? String)?.contains(expectedFragment) == true
            }
        )
        editor.typeText("\n")
        XCTAssertTrue(
            VocelloUIWait.condition("composer keyboard to dismiss", timeout: 15) {
                !self.app.keyboards.firstMatch.exists
            }
        )
    }

    func test07SheetPresentDismiss() {
        beginScenario("ios-sheet-present-dismiss", seedHistoryRows: Self.seededHistoryRows, suppressWarmup: true)
        assertSeededHistoryReady(rows: Self.seededHistoryRows)
        let row = historyRows().firstMatch
        let rowFrame = settledFrame(of: row, description: "first History row")
        let rowPoint = rootCoordinate(for: CGPoint(x: rowFrame.midX, y: rowFrame.midY))

        let player = element("iosPlayer_playPause")
        let close = element("iosPlayer_close")
        // Pre-warm using the exact root-anchored coordinates to prove both
        // `rowPoint` and `closePoint` hit live controls after sheet settle.
        rowPoint.tap()
        XCTAssertTrue(VocelloUIWait.exists(player, timeout: 20))
        let closeFrame = settledFrame(of: close, description: "iosPlayer_close")
        let closePoint = rootCoordinate(for: CGPoint(x: closeFrame.midX, y: closeFrame.midY))
        closePoint.tap()
        XCTAssertTrue(VocelloUIWait.disappears(player, timeout: 20))

        let log = VocelloPerfPhaseLog()
        measuredCycles("ios-sheet-present-dismiss", cycles: 6, actionsPerCycle: 2, phaseLog: log) { _ in
            let actionStart = Self.epochMS()
            rowPoint.tap()
            Thread.sleep(forTimeInterval: 0.7)
            closePoint.tap()
            Thread.sleep(forTimeInterval: 0.7)
            log.append("action", from: actionStart, to: Self.epochMS())
        }
        // Post-window ground-truth check: confirm the sheet closed cleanly and
        // both coordinates remain live after all 6 cycles.
        XCTAssertTrue(VocelloUIWait.disappears(player, timeout: 10))
        rowPoint.tap()
        XCTAssertTrue(VocelloUIWait.exists(player, timeout: 10))
        closePoint.tap()
        XCTAssertTrue(VocelloUIWait.disappears(player, timeout: 10))
    }

    private static func parsePlaybackSeconds(_ formatted: String?) -> Int? {
        guard let formatted else { return nil }
        let parts = formatted.split(separator: ":")
        guard parts.count == 2, let minutes = Int(parts[0]), let seconds = Int(parts[1]) else {
            return nil
        }
        return minutes * 60 + seconds
    }

    /// Exploratory: drives the custom DragGesture scrubber using root-anchored
    /// coordinates resolved from a settled `scrubber.frame` once `AVAudioPlayer`
    /// is loaded, eliminating per-drag accessibility snapshot walks.
    func test08PlayerScrub() {
        beginScenario("ios-player-scrub", seedHistoryRows: Self.seededHistoryRows, suppressWarmup: true)
        assertSeededHistoryReady(rows: Self.seededHistoryRows)
        let row = historyRows().firstMatch
        XCTAssertTrue(VocelloUIWait.exists(row, timeout: 20))
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: row, timeout: 20))
        let playPause = element("iosPlayer_playPause")
        XCTAssertTrue(VocelloUIWait.exists(playPause, timeout: 20))
        // Wait until `IOSPlayerSheetController.load(item:)` finishes so
        // `scrub(to:)` operates on a live `AVAudioPlayer` rather than no-oping.
        XCTAssertTrue(VocelloUIWait.enabled(playPause, timeout: 20))
        let scrubber = element("iosPlayer_scrubber")
        let scrubberFrame = settledFrame(of: scrubber, description: "iosPlayer_scrubber")
        guard let initialSeconds = Self.parsePlaybackSeconds(scrubber.value as? String) else {
            XCTFail("Expected m:ss playback value on iosPlayer_scrubber, got \(String(describing: scrubber.value))")
            return
        }
        // `VocelloUIWait.enabled` + `settledFrame` take ~5-6 s over XCUITest while
        // the 30 s seeded track autoplays from 0:00.
        XCTAssertLessThan(initialSeconds, 10, "Seeded player should start near the beginning before scrubbing")

        let leftPoint = rootCoordinate(
            for: CGPoint(x: scrubberFrame.minX + scrubberFrame.width * 0.15, y: scrubberFrame.midY)
        )
        // 80% of the 30 s seeded WAV (~24.0 s): leaves 6 s before EOF during
        // forward holds so playback never finishes between drags.
        let rightPoint = rootCoordinate(
            for: CGPoint(x: scrubberFrame.minX + scrubberFrame.width * 0.80, y: scrubberFrame.midY)
        )
        let beforeWindow = Date()
        let log = VocelloPerfPhaseLog()
        measuredCycles("ios-player-scrub", cycles: 8, actionsPerCycle: 1, phaseLog: log) { drag in
            let actionStart = Self.epochMS()
            let forward = drag.isMultiple(of: 2)
            // Odd final drag (drag == 7) sweeps right -> left back to 15% (~4.5 s),
            // which uninterrupted forward autoplay can never reach after ~10-20 s of drags.
            let from = forward ? leftPoint : rightPoint
            let to = forward ? rightPoint : leftPoint
            from.press(forDuration: 0.1, thenDragTo: to)
            Thread.sleep(forTimeInterval: 0.4)
            log.append("action", from: actionStart, to: Self.epochMS())
        }
        XCTAssertTrue(
            VocelloUIWait.condition(
                "scrubber playback position to rewind behind uninterrupted autoplay",
                timeout: 3
            ) {
                guard let currentSeconds = Self.parsePlaybackSeconds(scrubber.value as? String) else {
                    return false
                }
                let elapsedSeconds = Int(Date().timeIntervalSince(beforeWindow).rounded(.down))
                let uninterruptedSeconds = min(30, initialSeconds + elapsedSeconds)
                return currentSeconds <= 11 && currentSeconds + 4 <= uninterruptedSeconds
            }
        )
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
        // Readiness polling is harness work; the window opens once Generate is
        // enabled and closes when the completed player appears.
        XCTAssertTrue(VocelloUIWait.enabled(element("textInput_generateButton"), timeout: 60))
        let start = Int64(Date().timeIntervalSince1970 * 1000)
        _ = generateAndWaitForCompletedPlayer(timeout: 300)
        let end = Int64(Date().timeIntervalSince1970 * 1000)
        emit(VocelloUIPerfScenarioMarker(
            scenario: "ios-generation-active",
            windowStartEpochMS: start,
            windowEndEpochMS: end,
            actionCount: 1
        ))
    }
}
