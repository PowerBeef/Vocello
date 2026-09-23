import Foundation

/// Package-internal counterpart of the product runtime gate. The implementation
/// target cannot import its facade without a dependency cycle, and a SwiftPM
/// target never sees the product's `VOCELLO_INTERNAL_DIAGNOSTICS` compile
/// condition, so the host attests that capability per load
/// (`QwenPreparedLoadBehavior.internalDiagnosticsAvailable`, derived from the
/// product `RuntimeDebugGate`). Both conditions are required: the capability
/// and an explicit `QWENVOICE_DEBUG`. There is no default capability, so a
/// consumer that attests nothing gets every override disabled.
enum VocelloQwen3ImplementationDebugGate {
    static func value(
        for key: String,
        internalDiagnosticsAvailable: Bool,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> String? {
        guard internalDiagnosticsAvailable else { return nil }
        guard let raw = environment["QWENVOICE_DEBUG"]?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased(),
            ["1", "true", "on", "yes"].contains(raw) else {
            return nil
        }
        return environment[key]
    }
}
