import Foundation
import XCTest

/// RF-38: a self-contained smoke journey for a cloud device farm (BrowserStack App Automate),
/// whose phone starts with no Vocello models, History or saved voices and runs a build the
/// farm re-signed without `increased-memory-limit`. It needs nothing from `scripts/ui_test.sh`:
/// no run identity, no installed model, no enrolled voice. No lane selects it; the farm upload
/// names it with only-testing. A pass is exploratory clone-off smoke evidence on that hardware,
/// never floor-device or promotion evidence.
///
/// The app keeps its models and History in an isolated support root (the registered
/// `QVOICE_APP_SUPPORT_DIR` knob, honored by the internal-diagnostics build the farm package
/// uses), so a local run leaves the phone's own models and History untouched; the root itself
/// (about 2 GB once the model is in) stays until removed.
@MainActor
final class VocelloiOSFarmSmokeUITests: VocelloiOSUITestCase {
    private static let isolatedSupportRoot = "farm-smoke"
    private static let modelID = "pro_custom"
    private static let downloadTimeout: TimeInterval = 1_800
    private static let downloadStallBudget: TimeInterval = 300
    private static let takeTimeout: TimeInterval = 300
    /// RF-40: warm takes in the soak's one measurement, about 25 s each on an iPhone 15 Pro.
    private static let soakTakes = 40
    /// BKL-53: warm takes per block of the cache-clearing A/B (four blocks in one session).
    private static let abTakesPerBlock = 5
    /// About fifteen seconds of speech in dictionary words only, so a fresh farm keyboard has
    /// nothing to autocorrect before the composer's exact-text check.
    private static let script = """
        The morning train slipped quietly out of the station, carrying a handful of sleepy \
        travelers toward the coast. Outside the fogged windows, pale fields gave way to grey \
        water, and the rhythm of the rails settled into a steady hum.
        """

    private struct DeviceFacts: Codable {
        let hardware: String
        let osVersion: String
        let physicalMemoryMB: UInt64
        let thermalState: String
    }

    private struct ModelDelivery: Codable {
        let modelID: String
        let action: String
        let seconds: Double?
    }

    private struct Take: Codable {
        let kind: String
        /// Harness wall time from the Generate wait to the completed player, polled about once a
        /// second; not the engine's own timing.
        let wallSeconds: Double
        /// From the take's History row (tenths of a second); nil when unreadable.
        let audioSeconds: Double?
    }

    private struct Summary: Codable {
        let schemaVersion: Int
        let journey: String
        let caveat: String
        let deviceAtStart: DeviceFacts
        let model: ModelDelivery
        let takes: [Take]
        let historyRowsVerified: Int
        let thermalStateAtEnd: String
    }

    private struct MemoryRun: Codable {
        let deviceAtStart: DeviceFacts
        let thermalStateAtEnd: String
    }

    private struct SoakTake: Codable {
        /// 1-based; the n-th value of each `measured [...]` line belongs to this take.
        let index: Int
        let completed: Bool
        /// Harness wall time from the Generate tap to the completed player; the engine's own
        /// timing is the measured `Native Generation Stream` duration.
        let harnessWallSeconds: Double
        /// Seconds since the first measured take began, at this take's end.
        let elapsedSeconds: Double
        let thermalStateAfter: String
        /// From the take's History row (tenths of a second); nil when unread or unmatched.
        var audioSeconds: Double?
    }

    private struct ClearABBlock: Codable {
        let schemaVersion: Int
        let block: Int
        /// `iphone_pro` (shipped) or the forced `high_memory_mac` policy.
        let memoryPolicy: String
        let deviceAtStart: DeviceFacts
        let coldTake: Take
        let takes: [SoakTake]
        let thermalStateAtEnd: String
    }

    private struct Soak: Codable {
        let schemaVersion: Int
        let journey: String
        let caveat: String
        let deviceAtStart: DeviceFacts
        let model: ModelDelivery
        let coldTake: Take
        let takes: [SoakTake]
        let thermalStateAtEnd: String
    }

    private var environment: [String: String] { ["QVOICE_APP_SUPPORT_DIR": Self.isolatedSupportRoot] }

    /// Launch, deliver the Built-in Voice model, two takes (the first loads the model), and both
    /// takes found in History with their exact transcript. Prints one `VOCELLO_FARM_SMOKE` line.
    func testFarmSmokeJourney() throws {
        let clock = ContinuousClock()
        let deviceAtStart = Self.deviceFacts()
        beginSession(additionalEnvironment: environment)
        defer { endSession() }
        VocelloUIScreenshot.attach(app, named: "farm-smoke-launched")

        let model = ensureBuiltInVoiceModel(clock: clock)
        let rowsBefore = try XCTUnwrap(historyRowCensus(expectedScript: Self.script))
        prepare(mode: .custom)
        replaceScript(with: Self.script)

        let kinds = ["cold", "warm"]
        var wallSeconds: [Double] = []
        for kind in kinds {
            let start = clock.now
            let generationID = generateAndWaitForCompletedPlayer(timeout: Self.takeTimeout)
            wallSeconds.append(Self.seconds(clock.now - start))
            XCTAssertFalse(generationID.isEmpty, "The \(kind) take must complete")
            VocelloUIScreenshot.attach(app, named: "farm-smoke-\(kind)-take")
            // The completed player holds Generate's place until it is dismissed.
            dismissCompletedPlayerAndAssertGenerateReady()
        }

        let rowsAfter = try XCTUnwrap(historyRowCensus(expectedScript: Self.script))
        XCTAssertTrue(Set(rowsBefore).isSubset(of: Set(rowsAfter)))
        // Persisted rows are `generation-<n>`, numbered in creation order.
        let added = Set(rowsAfter).subtracting(rowsBefore)
            .sorted { Self.rowNumber($0) < Self.rowNumber($1) }
        XCTAssertEqual(added.count, kinds.count, "Each take must add exactly one History row")
        let takes = zip(kinds, wallSeconds).enumerated().map { index, take in
            Take(
                kind: take.0,
                wallSeconds: take.1,
                audioSeconds: index < added.count ? historyAudioSeconds(rowID: added[index]) : nil
            )
        }
        for rowID in added {
            XCTAssertTrue(verifyHistoryTranscript(rowID: rowID, expectedScript: Self.script))
        }
        VocelloUIScreenshot.attach(app, named: "farm-smoke-history")

        emit(marker: "VOCELLO_FARM_SMOKE", name: "farm-smoke-summary.json", Summary(
            schemaVersion: 1,
            journey: "farm-smoke",
            caveat: "Farm build re-signed without increased-memory-limit: clone-off exploratory smoke "
                + "only; take times are harness wall time",
            deviceAtStart: deviceAtStart,
            model: model,
            takes: takes,
            historyRowsVerified: added.count,
            thermalStateAtEnd: Self.thermalStateName(ProcessInfo.processInfo.thermalState)
        ))
        XCTAssertTrue(takes.allSatisfy { $0.audioSeconds != nil }, "Each take's History row must show its duration")
    }

    /// The app's peak physical memory across the session's first Built-in Voice take, through
    /// XCTest's own memory metric for the target app; xcodebuild prints it as `measured [Memory
    /// Peak Physical, kB]`. XCTest runs the block once more than `iterationCount` and discards the
    /// first run, so that run does nothing and the measured one is the first take. Kept apart from
    /// the journey so a farm that cannot gather the metric still keeps the journey's result.
    /// Delivers the model itself if the farm reinstalled the app.
    func testFarmTakeMemoryPeak() {
        let clock = ContinuousClock()
        let deviceAtStart = Self.deviceFacts()
        beginSession(additionalEnvironment: environment)
        defer { endSession() }
        _ = ensureBuiltInVoiceModel(clock: clock)
        prepare(mode: .custom)
        replaceScript(with: Self.script)

        let options = XCTMeasureOptions()
        options.iterationCount = 1
        options.invocationOptions = [.manuallyStop]
        var invocation = 0
        measure(metrics: [XCTMemoryMetric(application: app), XCTClockMetric()], options: options) {
            invocation += 1
            guard invocation > 1 else {
                stopMeasuring()
                return
            }
            XCTAssertFalse(generateAndWaitForCompletedPlayer(timeout: Self.takeTimeout).isEmpty)
            stopMeasuring()
            dismissCompletedPlayerAndAssertGenerateReady()
        }
        emit(marker: "VOCELLO_FARM_MEMORY", name: "farm-memory-device.json", MemoryRun(
            deviceAtStart: deviceAtStart,
            thermalStateAtEnd: Self.thermalStateName(ProcessInfo.processInfo.thermalState)
        ))
    }

    /// RF-40: the hardware floor's sustained performance. After one cold take loads the model,
    /// `soakTakes` warm takes of the same script run back to back inside one XCTest measurement,
    /// which times the app's own `Native Prepare Generation` and `Native Generation Stream`
    /// signpost intervals and samples its memory and CPU per take; xcodebuild prints each as a
    /// `measured [...]` line whose n-th value is take n. The test records each take's thermal
    /// state and, from History, its audio length, so RTF is (prepare + stream) ÷ audio. The farm
    /// re-signs the app without increased-memory-limit, so this is exploratory evidence, never a
    /// benchmark record. `farm_smoke.sh upload --journey soak` selects it; no lane does.
    func testFarmThermalSoak() throws {
        executionTimeAllowance = 3_600
        let clock = ContinuousClock()
        let deviceAtStart = Self.deviceFacts()
        beginSession(additionalEnvironment: environment)
        defer { endSession() }
        let model = ensureBuiltInVoiceModel(clock: clock)
        let run = try measuredTakes(count: Self.soakTakes, clock: clock)
        emit(marker: "VOCELLO_FARM_SOAK", name: "farm-soak-summary.json", Soak(
            schemaVersion: 1,
            journey: "farm-soak",
            caveat: "Farm build re-signed without increased-memory-limit: clone-off exploratory evidence, "
                + "not a benchmark record; engine timings are the measured signpost durations",
            deviceAtStart: deviceAtStart,
            model: model,
            coldTake: run.cold,
            takes: run.takes,
            thermalStateAtEnd: Self.thermalStateName(ProcessInfo.processInfo.thermalState)
        ))
    }

    // BKL-53: interleaved blocks, so both clearing policies meet the same phone at the same heat.
    // Methods run in name order: shipped iPhone policy, Mac high-memory policy, then both again.
    func testFarmClearAB1IPhonePolicy() throws { try clearABBlock(1, forcedMemoryClass: nil) }
    func testFarmClearAB2HighMemoryPolicy() throws { try clearABBlock(2, forcedMemoryClass: "high_memory_mac") }
    func testFarmClearAB3IPhonePolicy() throws { try clearABBlock(3, forcedMemoryClass: nil) }
    func testFarmClearAB4HighMemoryPolicy() throws { try clearABBlock(4, forcedMemoryClass: "high_memory_mac") }

    /// BKL-53: one block of the MLX cache-clearing A/B. The shipped `iphone_pro` policy clears
    /// MLX's buffer cache at every streamed chunk and every 50 tokens under a 128 MiB cache; the
    /// registered `QWENVOICE_FORCE_MEMORY_CLASS` diagnostic switches the internal-diagnostics
    /// build to `high_memory_mac`, which clears every 200 tokens under a 1 GiB cache, never per
    /// chunk, and also streams 0.4 s chunks instead of 0.6 s (more decoder calls, against it).
    /// `farm_smoke.sh upload --journey clear-ab` selects the four blocks; no lane does.
    private func clearABBlock(_ block: Int, forcedMemoryClass: String?) throws {
        executionTimeAllowance = 1_800
        let clock = ContinuousClock()
        let deviceAtStart = Self.deviceFacts()
        var launchEnvironment = environment
        if let forcedMemoryClass {
            launchEnvironment["QWENVOICE_FORCE_MEMORY_CLASS"] = forcedMemoryClass
        }
        beginSession(additionalEnvironment: launchEnvironment)
        defer { endSession() }
        _ = ensureBuiltInVoiceModel(clock: clock)
        let run = try measuredTakes(count: Self.abTakesPerBlock, clock: clock)
        emit(marker: "VOCELLO_FARM_AB", name: "farm-clear-ab-\(block).json", ClearABBlock(
            schemaVersion: 1,
            block: block,
            memoryPolicy: forcedMemoryClass ?? "iphone_pro",
            deviceAtStart: deviceAtStart,
            coldTake: run.cold,
            takes: run.takes,
            thermalStateAtEnd: Self.thermalStateName(ProcessInfo.processInfo.thermalState)
        ))
    }

    /// One cold take, which loads the model, then `count` warm takes of the same script inside
    /// one XCTest measurement, which times the app's own engine intervals and samples its memory
    /// and CPU per take; xcodebuild prints each metric's per-take values in order. Each take
    /// prints its thermal state as it ends, and History supplies the audio lengths afterwards.
    private func measuredTakes(
        count: Int,
        clock: ContinuousClock
    ) throws -> (cold: Take, takes: [SoakTake]) {
        let rowsBefore = try XCTUnwrap(historyRowCensus(expectedScript: Self.script))
        prepare(mode: .custom)
        replaceScript(with: Self.script)

        let coldStart = clock.now
        XCTAssertFalse(generateAndWaitForCompletedPlayer(timeout: Self.takeTimeout).isEmpty)
        let coldWall = Self.seconds(clock.now - coldStart)
        dismissCompletedPlayerAndAssertGenerateReady()

        let options = XCTMeasureOptions()
        options.iterationCount = count
        options.invocationOptions = [.manuallyStop]
        var invocation = 0
        var takes: [SoakTake] = []
        let firstTakeStart = clock.now
        measure(metrics: Self.soakMetrics(app: app), options: options) {
            invocation += 1
            // XCTest discards the first run, so it generates nothing.
            guard invocation > 1 else {
                stopMeasuring()
                return
            }
            let start = clock.now
            let generationID = generateAndWaitForCompletedPlayer(timeout: Self.takeTimeout)
            stopMeasuring()
            let take = SoakTake(
                index: takes.count + 1,
                completed: !generationID.isEmpty,
                harnessWallSeconds: Self.seconds(clock.now - start),
                elapsedSeconds: Self.seconds(clock.now - firstTakeStart),
                thermalStateAfter: Self.thermalStateName(ProcessInfo.processInfo.thermalState)
            )
            takes.append(take)
            // One line per take, so a session the farm ends early still keeps what ran.
            printMarker("VOCELLO_FARM_SOAK_TAKE", take)
            if take.completed { dismissCompletedPlayerAndAssertGenerateReady() }
        }

        let rowsAfter = try XCTUnwrap(historyRowCensus(expectedScript: Self.script))
        // Persisted rows are `generation-<n>`, numbered in creation order: the cold take, then
        // each completed measured take.
        let added = Set(rowsAfter).subtracting(rowsBefore)
            .sorted { Self.rowNumber($0) < Self.rowNumber($1) }
        let audio = historyAudioSecondsByRow()
        let completed = takes.indices.filter { takes[$0].completed }
        if added.count == completed.count + 1 {
            for (row, index) in zip(added.dropFirst(), completed) {
                takes[index].audioSeconds = audio[row]
            }
        } else {
            XCTFail("History gained \(added.count) rows for \(completed.count + 1) completed takes")
        }
        let cold = Take(kind: "cold", wallSeconds: coldWall, audioSeconds: added.first.flatMap { audio[$0] })
        return (cold, takes)
    }

    /// The soak's per-take metrics: the engine's own intervals for each take (preparation, then
    /// the stream through the published WAV), the app's memory and CPU, and the wall clock.
    private static func soakMetrics(app: XCUIApplication) -> [any XCTMetric] {
        [
            XCTOSSignpostMetric(
                subsystem: "com.qwenvoice.engine",
                category: "runtime",
                name: "Native Prepare Generation"
            ),
            XCTOSSignpostMetric(
                subsystem: "com.qwenvoice.engine",
                category: "generation",
                name: "Native Generation Stream"
            ),
            XCTMemoryMetric(application: app),
            XCTCPUMetric(application: app),
            XCTClockMetric(),
        ]
    }

    /// Starts the Built-in Voice model through the Studio's own install action when the isolated
    /// root lacks it, and waits for Voice Models to show it Ready. A download that shows no
    /// change for five minutes fails rather than holding the farm session.
    private func ensureBuiltInVoiceModel(clock: ContinuousClock) -> ModelDelivery {
        let modelID = Self.modelID
        select(mode: .custom)
        let install = element("textInput_installModelButton")
        let generate = element("textInput_generateButton")
        XCTAssertTrue(VocelloUIWait.condition("the Studio to offer Install or Generate", timeout: 30) {
            install.exists || generate.exists
        })
        guard install.exists else {
            return ModelDelivery(modelID: modelID, action: "alreadyInstalled", seconds: nil)
        }

        let start = clock.now
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: install, timeout: 20))
        XCTAssertTrue(VocelloUIWait.exists(element("screen_voiceModels"), timeout: 30))
        let installed = element("iosModelDelete_\(modelID)")
        let progress = element("iosModelProgress_\(modelID)")
        let status = app.staticTexts["iosModelStatus_\(modelID)"].firstMatch
        XCTAssertTrue(VocelloUIWait.condition("\(modelID) to start downloading", timeout: 120) {
            installed.exists
                || progress.exists
                || self.element("iosModelPhaseActivity_\(modelID)").exists
                || self.element("iosModelCancel_\(modelID)").exists
        })
        var terminalAction: String?
        XCTAssertTrue(VocelloUIWait.progressing(
            "\(modelID) to install or fail",
            timeout: Self.downloadTimeout,
            stallBudget: Self.downloadStallBudget,
            progress: {
                let fraction = progress.exists ? String(describing: progress.value ?? "") : "-"
                let text = status.exists ? String(describing: status.value ?? status.label) : "-"
                return "\(fraction)|\(text)"
            },
            evaluate: {
                if installed.exists { return true }
                terminalAction = ["Retry", "Repair", "Download"].first {
                    self.element("iosModel\($0)_\(modelID)").exists
                }
                return terminalAction != nil
            }
        ))
        let seconds = Self.seconds(clock.now - start)
        if let terminalAction {
            VocelloUIScreenshot.attach(app, named: "farm-smoke-download-\(terminalAction.lowercased())")
            XCTFail("\(modelID) stopped at \(terminalAction) after \(Int(seconds))s instead of installing")
        }
        XCTAssertTrue(VocelloUIWait.value(status, contains: "Ready", timeout: 60))
        VocelloUIScreenshot.attach(app, named: "farm-smoke-model-ready")
        return ModelDelivery(modelID: modelID, action: "downloaded", seconds: seconds)
    }

    /// The take's duration from its History row, whose metadata element reads
    /// "voice, mode, date, 15.3s" (one snapshot of the identified row).
    private func historyAudioSeconds(rowID: String) -> Double? {
        guard let snapshot = try? element("historyRow_\(rowID)").snapshot() else { return nil }
        return Self.audioSeconds(in: snapshot)
    }

    /// Every History row's audio length under the search the last census applied, read from each
    /// row's own metadata while walking the lazy list from its top, one snapshot per viewport.
    /// Rows whose length cannot be read are absent.
    private func historyAudioSecondsByRow() -> [String: Double] {
        let scroll = app.scrollViews.firstMatch
        guard VocelloUIWait.exists(scroll, timeout: 10) else { return [:] }
        for _ in 0..<64 {
            let before = historyViewportSignature()
            scroll.swipeDown()
            if historyViewportSignature() == before { break }
        }
        let prefix = "historyRow_"
        var seconds: [String: Double] = [:]
        for _ in 0..<64 {
            if let root = try? app.snapshot() {
                var pending: [any XCUIElementSnapshot] = [root]
                while let node = pending.popLast() {
                    if node.identifier.hasPrefix(prefix) {
                        if let value = Self.audioSeconds(in: node) {
                            seconds[String(node.identifier.dropFirst(prefix.count))] = value
                        }
                    } else {
                        pending.append(contentsOf: node.children)
                    }
                }
            }
            let before = historyViewportSignature()
            scroll.swipeUp()
            if historyViewportSignature() == before { break }
        }
        return seconds
    }

    /// The duration a History row's metadata ends with ("voice, mode, date, 15.3s").
    private static func audioSeconds(in snapshot: any XCUIElementSnapshot) -> Double? {
        var pending: [any XCUIElementSnapshot] = [snapshot]
        while let node = pending.popLast() {
            if let last = node.label.split(separator: ",").last?.trimmingCharacters(in: .whitespaces),
               last.hasSuffix("s"), let seconds = Double(last.dropLast()) {
                return seconds
            }
            pending.append(contentsOf: node.children)
        }
        return nil
    }

    /// Prints the marker line for the farm's console log and keeps the same JSON as an attachment.
    private func emit(marker: String, name: String, _ value: some Encodable) {
        let line = printMarker(marker, value)
        let attachment = XCTAttachment(string: line)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    /// Prints one marker line for the farm's console log and returns its JSON.
    @discardableResult
    private func printMarker(_ marker: String, _ value: some Encodable) -> String {
        let line = Self.json(value)
        print("\(marker) \(line)")
        // stdout is fully buffered under the runner's pipe; flush before anything later can fail.
        unsafe fflush(stdout)
        return line
    }

    private static func json(_ value: some Encodable) -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        guard let data = try? encoder.encode(value) else { return "{}" }
        return String(decoding: data, as: UTF8.self)
    }

    private static func rowNumber(_ rowID: String) -> Int {
        Int(rowID.split(separator: "-").last ?? "") ?? 0
    }

    private static func seconds(_ duration: Duration) -> Double {
        let (whole, attoseconds) = duration.components
        return ((Double(whole) + Double(attoseconds) / 1e18) * 1_000).rounded() / 1_000
    }

    /// The runner shares the phone with the app, so its hardware, OS, memory and thermal state
    /// are the device's.
    private static func deviceFacts() -> DeviceFacts {
        let info = ProcessInfo.processInfo
        return DeviceFacts(
            hardware: hardwareIdentifier(),
            osVersion: info.operatingSystemVersionString,
            physicalMemoryMB: info.physicalMemory / 1_048_576,
            thermalState: thermalStateName(info.thermalState)
        )
    }

    private static func hardwareIdentifier() -> String {
        var system = utsname()
        guard unsafe uname(&system) == 0 else { return "unknown" }
        let bytes = Mirror(reflecting: system.machine).children
            .compactMap { $0.value as? CChar }
            .prefix { $0 != 0 }
            .map { UInt8(bitPattern: $0) }
        return String(decoding: bytes, as: UTF8.self)
    }

    private static func thermalStateName(_ state: ProcessInfo.ThermalState) -> String {
        switch state {
        case .nominal: "nominal"
        case .fair: "fair"
        case .serious: "serious"
        case .critical: "critical"
        @unknown default: "unknown"
        }
    }
}
