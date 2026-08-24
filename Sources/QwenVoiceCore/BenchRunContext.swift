import Foundation

/// Bench metadata stamped into telemetry `notes` when macOS XPC UI bench env vars are set.
public enum BenchRunContext {
    private static let runIDKey = "QVOICE_MAC_BENCH_RUN_ID"
    private static let takeIndexKey = "QVOICE_MAC_BENCH_TAKE_INDEX"
    private static let cellKey = "QVOICE_MAC_BENCH_CELL"
    private static let warmStateKey = "QVOICE_MAC_BENCH_WARM_STATE"

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
        if let fileNotes = currentTakeFileNotes() {
            // The engine service keeps the environment from its first launch,
            // while the benchmark advances multiple warm takes in that same
            // process. The current-take file is therefore authoritative for
            // the fields it carries.
            for (key, value) in fileNotes {
                notes[key] = value
            }
        }
        return notes
    }

    /// Bench driver writes a current-take manifest in temporary storage so
    /// warm-session takes still stamp take index + cell without relaunching.
    ///
    /// macOS deliberately uses the global temporary directory because the app,
    /// CLI, and XPC service must share this file. iOS runs the engine in-process
    /// and must use its sandbox-owned temporary directory.
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
    }

    public static func clearCurrentTakeFile() {
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
