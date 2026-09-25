import AppKit
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

            let requiresNewSession = Self.startsSession(takes, at: offset)
            let capturesPlayback = Self.capturesPlayback(takes, at: offset)
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
            phases.captured = capturesPlayback
            phases.mark("sessionReadyMS")

            XCTContext.runActivity(named: "Take \(takeIndex): \(take.cellID)") { _ in
                pasteScript(take.text)
                phases.mark("scriptReadyMS")
                if capturesPlayback {
                    capture?.beginTake(index: takeIndex, cell: take.cellID, warmState: take.warmState.rawValue)
                }
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
                if capturesPlayback {
                    // A captured take plays out before the next begins, whether or
                    // not the tap is live (audit #74): the idle gap before the next
                    // take, and so its pacing, never depends on the recording grant.
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
                } else {
                    // Every other take stops its playback at completion through
                    // the visible player control and settles the same half second
                    // (audit #31): one captured repetition per cell is the played-
                    // audio evidence, and the rest no longer wait out their audio.
                    // Which takes play out is fixed by the matrix, never by the grant.
                    stopPlayback()
                    phases.mark("playbackEndedMS")
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

    /// Whether a take starts a new app session: the first take, a cold take,
    /// and the first Clone take after another mode (the saved voice is chosen
    /// on a fresh launch).
    static func startsSession(_ takes: [VocelloUIBenchMatrix.Take], at offset: Int) -> Bool {
        let take = takes[offset]
        return offset == 0
            || take.warmState == .cold
            || (take.mode == .clone && takes[offset - 1].mode != .clone)
    }

    /// Whether a take's played audio is captured (audit #31, #74): the last warm
    /// repetition of each mode and length, never a take that starts a session.
    /// A relaunched app has no Core Audio process object until its first
    /// playback, so a tap armed on a session's first take attaches mid-take; a
    /// later take's process has already opened its device, so the tap is live
    /// before submit. `scripts/check_macos_ui_bench.py` mirrors this plan.
    static func capturesPlayback(_ takes: [VocelloUIBenchMatrix.Take], at offset: Int) -> Bool {
        let take = takes[offset]
        guard take.warmState == .warm, !startsSession(takes, at: offset) else { return false }
        return !takes[(offset + 1)...].contains {
            $0.warmState == .warm && $0.mode == take.mode && $0.length == take.length
        }
    }

    /// Enters the take's script with one genuine paste (Cmd-A, Cmd-V) instead of
    /// typing it a key at a time (audit #31: about 1,450 keystrokes a run), and
    /// leaves a script that already matches alone. Both happen before the take's
    /// submit, outside every measured window. The general pasteboard's previous
    /// items, every type of each, are put back once the paste has landed.
    private func pasteScript(_ text: String) {
        let editor = element("textInput_textEditor")
        if (editor.value as? String) != text {
            XCTAssertTrue(VocelloUIPrimaryAction.perform(on: editor, timeout: 20))
            let pasteboard = NSPasteboard.general
            let saved: [NSPasteboardItem] = (pasteboard.pasteboardItems ?? []).map { item in
                let copy = NSPasteboardItem()
                for type in item.types {
                    if let data = item.data(forType: type) {
                        copy.setData(data, forType: type)
                    }
                }
                return copy
            }
            defer {
                pasteboard.clearContents()
                if !saved.isEmpty {
                    pasteboard.writeObjects(saved)
                }
            }
            pasteboard.clearContents()
            pasteboard.setString(text, forType: .string)
            editor.typeKey("a", modifierFlags: .command)
            editor.typeKey("v", modifierFlags: .command)
            _ = VocelloUIWait.settles("pasted script to land", timeout: 10) {
                editor.value as? String == text
            }
        }
        XCTAssertTrue(VocelloUIWait.condition("script to match entered text", timeout: 10) {
            editor.value as? String == text
        })
    }

    /// Pauses the take's playback through the visible player control, if it is
    /// still playing. The control is labelled with the action it performs, so
    /// "Play" means playback is not running (every lane pins English).
    private func stopPlayback() {
        let inline = button("studio_inlinePlayer_playPause")
        let control = inline.exists ? inline : button("sidebarPlayer_playPause")
        guard control.exists, control.label != "Play" else { return }
        XCTAssertTrue(VocelloUIPrimaryAction.perform(on: control, timeout: 10))
        XCTAssertTrue(VocelloUIWait.condition("playback to stop", timeout: 10) {
            !control.exists || control.label == "Play"
        })
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
        // The seed policy scripts/ui_test.sh selects (audit #29): the app
        // samples each take with the seed of the cell the current-take file
        // names, so two runs of one build produce the same take per cell.
        if let policy = VocelloUIBenchMatrix.seedPolicy(
            environment: ProcessInfo.processInfo.environment, keyPrefix: "QVOICE_MAC_BENCH"
        ) {
            environment[VocelloUIBenchMatrix.seedPolicyAppKey] = policy
        }
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
        // An unsandboxed runner (scripts/ui_test.sh re-signed it and says so)
        // writes the file itself instead of relaying it through the log and
        // polling for the shell (audit #31); the relay stays the fallback.
        if Self.writesManifestDirectly, writeCurrentTakeManifest(data) {
            print("VOCELLO_BENCH_TAKE_FILE_WRITTEN take=\(takeIndex)")
            fflush(stdout)
            return true
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

    private static var writesManifestDirectly: Bool {
        ProcessInfo.processInfo.environment["QVOICE_MAC_BENCH_DIRECT_MANIFEST"] == "1"
    }

    /// Writes the current-take file atomically and reads it back.
    private func writeCurrentTakeManifest(_ data: Data) -> Bool {
        do {
            try data.write(to: Self.takeFile, options: .atomic)
            return (try? Data(contentsOf: Self.takeFile)) == data
        } catch {
            return false
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
    /// Whether the take played out for the played-audio capture (audit #31).
    var captured = false

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
            "captured": captured,
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
