import Foundation
import Darwin
@preconcurrency import XCTest

@MainActor
final class VocelloMacBenchmarkUITests: VocelloMacUITestCase {
    private static let takeFile = URL(fileURLWithPath: "/tmp/vocello-bench-current-take.json")
    /// Registered diagnostics scripts/ui_test.sh hands through for the emulated
    /// 8 GB floor (audit #11 option b); absent, the app runs on the real machine.
    private static let floorEmulationKeys = [
        "QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB",
        "QVOICE_IOS_MEMORY_GUARD_FORCE_BAND",
        "QVOICE_IOS_MEMORY_GUARD_FORCE_CRITICAL_ONCE",
    ]

    override var additionalLaunchEnvironment: [String: String] { Self.floorEmulationEnvironment() }

    private static func floorEmulationEnvironment() -> [String: String] {
        let processEnvironment = ProcessInfo.processInfo.environment
        var environment: [String: String] = [:]
        for key in floorEmulationKeys {
            if let value = processEnvironment[key], !value.isEmpty {
                environment[key] = value
            }
        }
        return environment
    }

    func testOrderedConfigurableMatrix() throws {
        beginSession()
        defer { endSession() }

        let processEnvironment = ProcessInfo.processInfo.environment
        for key in [
            "QVOICE_MAC_BENCH_RUN_ID",
            "QVOICE_MAC_BENCH_MODES",
            "QVOICE_MAC_BENCH_LENGTHS",
            "QVOICE_MAC_BENCH_WARM",
            "QVOICE_MAC_BENCH_LABEL",
        ] {
            _ = try XCTUnwrap(
                processEnvironment[key].flatMap { $0.isEmpty ? nil : $0 },
                "macOS benchmark requires runner environment value \(key)"
            )
        }
        let configuration = try VocelloUIBenchMatrix.Configuration(
            environment: processEnvironment,
            keyPrefix: "QVOICE_MAC_BENCH"
        )
        let takes = VocelloUIBenchMatrix.takes(configuration: configuration)
        let runID = try XCTUnwrap(processEnvironment["QVOICE_MAC_BENCH_RUN_ID"])
        let label = try XCTUnwrap(processEnvironment["QVOICE_MAC_BENCH_LABEL"])

        XCTAssertFalse(takes.isEmpty)
        if configuration == VocelloUIBenchMatrix.defaultConfiguration {
            XCTAssertEqual(takes, VocelloUIBenchMatrix.defaultTakes)
            XCTAssertEqual(takes.count, 29)
        }

        assertVisibleSpeedModelReadiness()
        // Every take runs Speed whatever the tier recommends (audit #17); the
        // first take relaunches the app, so this setup never reaches a take.
        selectVisibleSpeedVariant(for: configuration.modes)
        ensureCloneConsentEnabled()
        assertSavedCloneVoice()
        // The schema-v8 gate requires a genuine playback-scheduled milestone on
        // every take, so the benchmark always runs with the visible Auto-play
        // toggle on and restores the user's original value afterwards.
        let autoplayWasEnabled = ensureAutoplayEnabled()
        defer { restoreAutoplayPreference(originallyEnabled: autoplayWasEnabled) }
        // Played-audio capture (PC-01): armed by scripts/ui_test.sh through
        // QVOICE_MAC_BENCH_CAPTURE_DIR; absent or failing capture never fails a take.
        let capture = VocelloPlaybackCaptureCoordinator(environment: processEnvironment, runID: runID)
        print("VOCELLO_PLAYBACK_CAPTURE_DIR=\(processEnvironment[VocelloPlaybackCaptureCoordinator.environmentKey] ?? "missing")")
        fflush(stdout)
        defer { capture?.abort() }

        var preparedMode: VocelloUIBenchMatrix.Mode?
        for (offset, take) in takes.enumerated() {
            let takeIndex = offset + 1
            let phases = VocelloBenchTakePhases(takeIndex: takeIndex, cell: take.cellID)
            guard publishCurrentTakeManifest(
                runID: runID,
                takeIndex: takeIndex,
                cell: take.cellID,
                intendedWarmState: take.warmState.rawValue
            ) else {
                return
            }
            phases.mark("manifestReadyMS")

            let previous = offset > 0 ? takes[offset - 1] : nil
            let requiresNewSession = offset == 0
                || take.warmState == .cold
                || (take.mode == .clone && previous?.mode != .clone)
            if requiresNewSession {
                relaunchApp(
                    additionalEnvironment: launchEnvironment(
                        runID: runID,
                        label: label,
                        takeIndex: takeIndex,
                        take: take
                    )
                )
                preparedMode = nil
            }

            if preparedMode != take.mode {
                prepare(mode: take.mode)
                preparedMode = take.mode
            }
            phases.relaunched = requiresNewSession
            phases.mark("sessionReadyMS")

            XCTContext.runActivity(named: "Take \(takeIndex): \(take.cellID)") { _ in
                replaceScript(with: take.text)
                phases.mark("scriptReadyMS")
                capture?.beginTake(index: takeIndex, cell: take.cellID, warmState: take.warmState.rawValue)
                generateAndWaitForCompletion(
                    mode: take.mode,
                    timeout: timeout(for: take),
                    onBeforeGenerate: {
                        phases.mark("submitMS")
                        capture?.markSubmit()
                    },
                    onAfterGenerateClick: { capture?.markSubmitReturned() }
                )
                phases.mark("completedMS")
                // Every take plays out before the next begins, whether or not the
                // capture is live (audit #74): the idle gap before the next take,
                // and so its pacing, never depends on the recording grant.
                let playbackEnded = waitForPlaybackToFinish(timeout: timeout(for: take))
                phases.mark("playbackEndedMS")
                if let capture, !capture.isIdle {
                    // The tap stops once the captured audio itself has been quiet
                    // for half a second after the player stopped.
                    _ = VocelloUIWait.condition("captured audio to fall silent after playback", timeout: 5) {
                        capture.capturedAudioIsQuiet(forLast: 0.5)
                    }
                    capture.endTake(playbackEnded: playbackEnded)
                } else {
                    capture?.endTake(playbackEnded: playbackEnded)
                    // The same half-second tail the capture's quiet check waits.
                    _ = XCTWaiter.wait(for: [XCTestExpectation(description: "post-playback settle")], timeout: 0.5)
                }
                phases.mark("settledMS")

                if take.warmState == .cold || offset == 0 || offset == takes.count - 1 {
                    VocelloUIScreenshot.attach(
                        app,
                        named: "mac-benchmark-\(takeIndex)-\(sanitized(take.cellID))"
                    )
                }
            }
            phases.mark("endMS")
            phases.emit()
        }
    }

    private func launchEnvironment(
        runID: String,
        label: String,
        takeIndex: Int,
        take: VocelloUIBenchMatrix.Take
    ) -> [String: String] {
        var environment = Self.floorEmulationEnvironment()
        environment.merge([
            "QVOICE_MAC_BENCH_RUN_ID": runID,
            "QVOICE_MAC_BENCH_TAKE_INDEX": String(takeIndex),
            "QVOICE_MAC_BENCH_CELL": take.cellID,
            "QVOICE_MAC_BENCH_WARM_STATE": take.warmState.rawValue,
        ]) { _, take in take }
        environment["QVOICE_MAC_BENCH_LABEL"] = label
        environment["QWENVOICE_BENCH_FORCE_COLD"] = take.warmState == .cold ? "1" : "0"
        if take.mode != .clone {
            environment["QWENVOICE_SUPPRESS_WARMUP"] = "1"
        }
        return environment
    }

    private func publishCurrentTakeManifest(
        runID: String,
        takeIndex: Int,
        cell: String,
        intendedWarmState: String
    ) -> Bool {
        let payload = [
            "benchRunID": runID,
            "benchTakeIndex": String(takeIndex),
            "benchCell": cell,
            "benchWarmState": intendedWarmState,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) else {
            XCTFail("Could not encode benchmark take manifest")
            return false
        }
        print("VOCELLO_BENCH_TAKE_MANIFEST=\(data.base64EncodedString())")
        fflush(stdout)
        return VocelloUIWait.condition(
            "shell runner to publish take \(takeIndex) metadata",
            timeout: 10
        ) {
            (try? Data(contentsOf: Self.takeFile)) == data
        }
    }

    private func sanitized(_ value: String) -> String {
        value.replacingOccurrences(of: "/", with: "-")
            .replacingOccurrences(of: "#", with: "-")
    }
}

/// Per-take harness phases (audit #31): monotonic offsets in milliseconds from
/// the start of each take's loop iteration (manifest published, session ready,
/// script entered, submit, completion seen, playback ended, settled, end),
/// printed as one `VOCELLO_BENCH_TAKE_PHASES=` JSON line that
/// `scripts/ui_test.sh` keeps as `take-phases.jsonl`. They time the harness
/// around the measured windows, never inside them, so per-take overhead is
/// measured rather than inferred. `startEpochMS` only correlates the line
/// with other evidence.
@MainActor
private final class VocelloBenchTakePhases {
    private let clock = ContinuousClock()
    private let start: ContinuousClock.Instant
    private let startEpochMS: Int64
    private let takeIndex: Int
    private let cell: String
    private var offsetsMS: [String: Int] = [:]
    var relaunched = false

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
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]),
              let line = String(data: data, encoding: .utf8) else { return }
        print("VOCELLO_BENCH_TAKE_PHASES=\(line)")
        fflush(stdout)
    }
}
