import Foundation
import Synchronization

/// Bench metadata stamped into telemetry `notes` when the macOS bench env vars are set.
public enum BenchRunContext {
    private static let runIDKey = "QVOICE_MAC_BENCH_RUN_ID"
    private static let takeIndexKey = "QVOICE_MAC_BENCH_TAKE_INDEX"
    private static let cellKey = "QVOICE_MAC_BENCH_CELL"
    private static let warmStateKey = "QVOICE_MAC_BENCH_WARM_STATE"

    /// The take a bench driver in this process last announced through
    /// `writeCurrentTakeFile`, until `clearCurrentTakeFile`. A process that
    /// drives its own takes (`vocello bench`, the iPhone diagnostics runner)
    /// stamps them from here in any build, without reading the file back.
    private static let announcedTake = Mutex<[String: String]?>(nil)

    public static var isActive: Bool {
        guard TelemetryGate.resolvedEnabled else { return false }
        let env = ProcessInfo.processInfo.environment
        return env[runIDKey]?.isEmpty == false
    }

    public static var runID: String? {
        trimmedEnv(runIDKey)
    }

    /// Notes merged into every telemetry row for the current bench take.
    public static func telemetryNotes(intendedWarmState: String? = nil) -> [String: String] {
        guard TelemetryGate.resolvedEnabled else { return [:] }
        var notes = notesFromEnvironment(intendedWarmState: intendedWarmState)
        if let takeNotes = currentTakeNotes() {
            // The process keeps the environment from its launch, while the
            // benchmark advances multiple warm takes in that same process. The
            // current take is therefore authoritative for the fields it
            // carries.
            for (key, value) in takeNotes {
                notes[key] = value
            }
        }
        return notes
    }

    /// The current take's identity: what a driver in this process announced,
    /// or the file a driver in another process wrote.
    ///
    /// The file is read only in an internal-diagnostics build. On macOS it is
    /// a fixed path under `/tmp` that any process can write, so a shipped
    /// build with telemetry on must not take bench identity from it. The
    /// macOS UI benchmark, whose runner writes the file from outside the app,
    /// runs a build with that capability.
    static func currentTakeNotes(
        internalDiagnosticsAvailable: Bool = RuntimeDebugGate.internalDiagnosticsAvailable
    ) -> [String: String]? {
        if let announced = announcedTake.withLock({ $0 }) {
            return announced
        }
        guard internalDiagnosticsAvailable else { return nil }
        return currentTakeFileNotes()
    }

    /// Bench driver writes a current-take manifest in temporary storage so
    /// warm-session takes still stamp take index + cell without relaunching.
    ///
    /// macOS uses a fixed global path because processes outside the app write
    /// it: `scripts/ui_test.sh` and the XCUITest runner
    /// (`VocelloMacBenchmarkUITests`). The app reads it only in an
    /// internal-diagnostics build (`currentTakeNotes`); a process that calls
    /// this itself, such as the CLI, stamps its takes from what it announced.
    /// iOS uses its sandbox-owned temporary directory.
    public static func writeCurrentTakeFile(
        takeIndex: Int,
        cell: String,
        intendedWarmState: String,
        startupPredecessorIdentityDigest: String? = nil
    ) throws {
        var payload: [String: String] = [
            "benchTakeIndex": String(takeIndex),
            "benchCell": cell,
            "benchWarmState": intendedWarmState,
        ]
        if let digest = startupPredecessorIdentityDigest?.lowercased(),
           digest.count == 64,
           digest.allSatisfy({ $0.isHexDigit }) {
            payload["startupPredecessorIdentityDigest"] = digest
        }
        let data = try JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
        try data.write(to: currentTakeFileURL, options: .atomic)
        guard currentTakeFileNotes() == payload else {
            throw BenchRunContextError.currentTakeReadbackMismatch
        }
        let announced = payload
        announcedTake.withLock { $0 = announced }
    }

    public static func clearCurrentTakeFile() {
        announcedTake.withLock { $0 = nil }
        try? FileManager.default.removeItem(at: currentTakeFileURL)
    }

    static var currentTakeFileURL: URL {
        #if os(iOS)
        FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-bench-current-take.json", isDirectory: false)
        #else
        URL(fileURLWithPath: "/tmp/vocello-bench-current-take.json", isDirectory: false)
        #endif
    }

    private static func notesFromEnvironment(intendedWarmState: String?) -> [String: String] {
        var notes: [String: String] = [:]
        if let runID = trimmedEnv(runIDKey) { notes["benchRunID"] = runID }
        if let take = trimmedEnv(takeIndexKey) { notes["benchTakeIndex"] = take }
        if let cell = trimmedEnv(cellKey) { notes["benchCell"] = cell }
        if let warm = intendedWarmState ?? trimmedEnv(warmStateKey) {
            notes["benchWarmState"] = warm
        }
        return notes
    }

    static func currentTakeFileNotes() -> [String: String]? {
        guard let data = try? Data(contentsOf: currentTakeFileURL),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: String] else {
            return nil
        }
        return object
    }

    public static func applyLaunchEnvironment(
        runID: String,
        takeIndex: Int,
        cell: String,
        intendedWarmState: String
    ) -> [String: String] {
        [
            runIDKey: runID,
            takeIndexKey: String(takeIndex),
            cellKey: cell,
            warmStateKey: intendedWarmState,
        ]
    }

    private static func trimmedEnv(_ key: String) -> String? {
        guard let raw = ProcessInfo.processInfo.environment[key]?
            .trimmingCharacters(in: .whitespacesAndNewlines),
            !raw.isEmpty else {
            return nil
        }
        return raw
    }
}

private enum BenchRunContextError: LocalizedError {
    case currentTakeReadbackMismatch

    var errorDescription: String? {
        "benchmark current-take identity could not be verified after writing"
    }
}
