import Foundation

/// Debug-only benchmark hook: force an explicit model unload immediately before the next
/// generation so telemetry records `warmState=cold`. Honored only when durable telemetry
/// is enabled (`TelemetryGate`, which an explicit telemetry-off mode keeps off even under
/// `QWENVOICE_DEBUG`) and the explicit runtime master gate is active.
public enum BenchForceColdPolicy {
    private static let environmentKey = "QWENVOICE_BENCH_FORCE_COLD"
    private static let lock = NSLock()
    nonisolated(unsafe) private static var consumed = false

    public static var shouldUnloadBeforeGeneration: Bool {
        guard isRequested(
            environment: ProcessInfo.processInfo.environment,
            telemetryEnabled: TelemetryGate.resolvedEnabled
        ) else { return false }

        // A cold benchmark launch must unload exactly once. The same process then
        // owns the warm repetitions; re-reading a permanently set environment key
        // for every request would silently turn the entire block into cold takes.
        lock.lock()
        defer { lock.unlock() }
        guard !consumed else { return false }
        consumed = true
        return true
    }

    /// Pure resolution seam for deterministic tests. Forcing an unload changes
    /// production runtime state, so telemetry alone is insufficient: the flag must
    /// also pass through the explicit `QWENVOICE_DEBUG` master gate.
    static func isRequested(
        environment: [String: String],
        telemetryEnabled: Bool
    ) -> Bool {
        guard telemetryEnabled else { return false }
        let value = RuntimeDebugGate.value(for: environmentKey, environment: environment)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        return value.map { ["1", "true", "on", "yes"].contains($0) } ?? false
    }
}
