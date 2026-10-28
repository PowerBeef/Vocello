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
        let line = Self.json(value)
        print("\(marker) \(line)")
        // stdout is fully buffered under the runner's pipe; flush before anything later can fail.
        unsafe fflush(stdout)
        let attachment = XCTAttachment(string: line)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
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
