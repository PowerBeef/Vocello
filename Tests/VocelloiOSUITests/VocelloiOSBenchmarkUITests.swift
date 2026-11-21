import Darwin
import Foundation
import XCTest

/// Ordered, configurable physical-device benchmark. The default configuration
/// is the exact shared 29-take matrix; Clone is a hard prerequisite and is
/// never skipped.
@MainActor
final class VocelloiOSBenchmarkUITests: VocelloiOSUITestCase {
    override class var keepsSteadyWaitCadence: Bool { true }

    func testOrderedConfigurableMatrix() throws {
        beginSession()
        defer { endSession() }

        let processEnvironment = ProcessInfo.processInfo.environment
        for key in [
            "QVOICE_IOS_BENCH_RUN_ID",
            "QVOICE_IOS_BENCH_MODES",
            "QVOICE_IOS_BENCH_LENGTHS",
            "QVOICE_IOS_BENCH_WARM",
            "QVOICE_IOS_BENCH_LABEL",
        ] {
            _ = try XCTUnwrap(
                processEnvironment[key].flatMap { $0.isEmpty ? nil : $0 },
                "Physical-device benchmark requires runner environment value \(key)"
            )
        }
        let configuration = try VocelloUIBenchMatrix.Configuration(
            environment: processEnvironment,
            keyPrefix: "QVOICE_IOS_BENCH"
        )
        let takes = VocelloUIBenchMatrix.takes(configuration: configuration)
        let runID = try XCTUnwrap(processEnvironment["QVOICE_IOS_BENCH_RUN_ID"])
        let label = try XCTUnwrap(processEnvironment["QVOICE_IOS_BENCH_LABEL"])

        XCTAssertFalse(takes.isEmpty)
        if configuration == VocelloUIBenchMatrix.defaultConfiguration {
            XCTAssertEqual(takes, VocelloUIBenchMatrix.defaultTakes)
            XCTAssertEqual(takes.count, 29)
        }

        // Readiness is observed through Settings and Saved Voices before the
        // first generation; no headless inventory or model repair is invoked.
        assertVisibleModelReadiness()
        ensureCloneConsentEnabled()
        _ = assertRequiredCloneVoice()
        let autoplayWasEnabled = ensureAutoplayEnabled()
        defer { restoreAutoplayPreference(originallyEnabled: autoplayWasEnabled) }

        var previousTake: VocelloUIBenchMatrix.Take?
        var preparedMode: VocelloUIBenchMatrix.Mode?
        var previousTakeRefused = false
        var completedCount = 0
        var refusedCount = 0
        var generationMap: [[String: Any]] = []

        for (offset, take) in takes.enumerated() {
            let takeNumber = offset + 1
            let phases = VocelloIOSBenchTakePhases(takeIndex: takeNumber, cell: take.cellID)
            // BenchForceColdPolicy consumes its flag once. A mode's cold take
            // and warm grid therefore remain in one process; only a mode
            // boundary starts a new process. Clone starts warm by definition.
            let requiresNewSession = previousTake == nil
                || previousTake?.mode != take.mode

            if requiresNewSession {
                phases.relaunched = true
                previousTakeRefused = false
                var environment = [
                    "QVOICE_MAC_BENCH_RUN_ID": runID,
                    "QVOICE_IOS_BENCH_LABEL": label,
                    "QWENVOICE_BENCH_FORCE_COLD": take.warmState == .cold ? "1" : "0",
                    // Enables the app's device-diagnostics action log (memory
                    // contexts + proactive-warm gate decisions) so UI-lane
                    // triage can read it from the pullable caches mirror.
                    "QVOICE_IOS_DEVICE_RUN_ID": runID,
                ]
                // The seed policy scripts/ui_test.sh selects (audit #29). The
                // app cannot read the runner's take file, so it gets this
                // process's cells in take order and samples each generation
                // with the next cell's seed.
                if let policy = VocelloUIBenchMatrix.seedPolicy(
                    environment: processEnvironment, keyPrefix: "QVOICE_IOS_BENCH"
                ) {
                    let cells = takes[offset...].prefix(while: { $0.mode == take.mode }).map(\.cellID)
                    environment[VocelloUIBenchMatrix.seedPolicyAppKey] = policy
                    environment[VocelloUIBenchMatrix.seedCellsAppKey] = cells.joined(separator: ",")
                }
                launchApp(additionalEnvironment: environment)
                preparedMode = nil
            }

            if preparedMode != take.mode {
                prepare(mode: take.mode)
                preparedMode = take.mode
            }
            phases.mark("sessionReadyMS")

            print("[ios-xcui-benchmark] begin \(takeNumber)/\(takes.count) \(take.cellID)")
            XCTContext.runActivity(named: "Take \(takeNumber): \(take.cellID)") { _ in
                replaceScript(with: take.text)
                phases.mark("scriptReadyMS")
                let generationID = generateAndWaitForCompletedPlayer(
                    timeout: timeout(for: take),
                    startingFromNotice: previousTakeRefused,
                    failTestOnVisibleError: false
                )
                phases.mark("terminalSeenMS")

                if generationID.isEmpty {
                    // A take refused by Fast QC ends on the retryable error notice. Record its
                    // marker and continue the matrix; scripts/check_ios_ui_benchmark.py verifies
                    // the engine row proved `audio.quality_rejected` and enforces --max-refused-takes.
                    phases.refused = true
                    refusedCount += 1
                    previousTakeRefused = true
                    VocelloUIScreenshot.attach(
                        app,
                        named: "ios-benchmark-\(takeNumber)-\(sanitized(take.cellID))-refused"
                    )
                    Self.emitRefusedTake(takeIndex: takeNumber, cell: take.cellID)
                    generationMap.append([
                        "takeIndex": takeNumber,
                        "cell": take.cellID,
                        "refused": true,
                    ])
                    return
                }

                previousTakeRefused = false
                generationMap.append([
                    "takeIndex": takeNumber,
                    "cell": take.cellID,
                    "generationID": generationID,
                ])

                if take.warmState == .cold || offset == 0 || offset == takes.count - 1 {
                    VocelloUIScreenshot.attach(
                        app,
                        named: "ios-benchmark-\(takeNumber)-\(sanitized(take.cellID))"
                    )
                }

                dismissCompletedPlayerAndAssertGenerateReady()
                phases.mark("settledMS")
            }
            phases.mark("endMS")
            phases.emit()
            print("[ios-xcui-benchmark] complete \(takeNumber)/\(takes.count) \(take.cellID)")
            completedCount += 1
            previousTake = take
        }

        XCTAssertEqual(completedCount, takes.count)
        let mapPayload: [String: Any] = [
            "schemaVersion": 1,
            "runID": runID,
            "takes": generationMap,
        ]
        let mapData = try JSONSerialization.data(withJSONObject: mapPayload, options: [.sortedKeys])
        let mapAttachment = XCTAttachment(data: mapData, uniformTypeIdentifier: "public.json")
        mapAttachment.name = "ios-benchmark-generation-map.json"
        mapAttachment.lifetime = .keepAlways
        add(mapAttachment)
        print("VOCELLO-BENCH-UI-MANIFEST ran=\(completedCount) refused=\(refusedCount) runID=\(runID) skippedClone=false")
    }

    /// One line per take that ended on its retryable error, for `scripts/check_ios_ui_benchmark.py`
    /// (matching macOS `VOCELLO_BENCH_TAKE_REFUSED`, audit T5).
    private static func emitRefusedTake(takeIndex: Int, cell: String) {
        let payload: [String: Any] = ["schemaVersion": 1, "takeIndex": takeIndex, "cell": cell]
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) else {
            return
        }
        print("VOCELLO_BENCH_TAKE_REFUSED=\(data.base64EncodedString())")
        unsafe fflush(stdout)
    }

    private func sanitized(_ value: String) -> String {
        value.replacingOccurrences(of: "/", with: "-")
            .replacingOccurrences(of: "#", with: "-")
    }
}

/// Per-take harness phases mirroring macOS `VocelloBenchTakePhases`: monotonic
/// millisecond offsets printed as `VOCELLO_BENCH_TAKE_PHASES=` JSON lines that
/// `scripts/ui_test.sh` retains in `take-phases.jsonl`.
@MainActor
private final class VocelloIOSBenchTakePhases {
    private let clock = ContinuousClock()
    private let start: ContinuousClock.Instant
    private let startEpochMS: Int64
    private let takeIndex: Int
    private let cell: String
    private var offsetsMS: [String: Int] = [:]
    var relaunched = false
    var refused = false

    init(takeIndex: Int, cell: String) {
        start = clock.now
        startEpochMS = Int64((Date().timeIntervalSince1970 * 1_000).rounded())
        self.takeIndex = takeIndex
        self.cell = cell
    }

    func mark(_ phase: String) {
        offsetsMS[phase] = Int((start.duration(to: clock.now) / .milliseconds(1)).rounded())
    }

    func emit() {
        var payload: [String: Any] = [
            "takeIndex": takeIndex,
            "cell": cell,
            "relaunched": relaunched,
            "startEpochMS": startEpochMS,
        ]
        for (phase, offset) in offsetsMS {
            payload[phase] = offset
        }
        if refused {
            payload["refused"] = true
        }
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
              let line = String(data: data, encoding: .utf8) else { return }
        print("VOCELLO_BENCH_TAKE_PHASES=\(line)")
        unsafe fflush(stdout)
    }
}
