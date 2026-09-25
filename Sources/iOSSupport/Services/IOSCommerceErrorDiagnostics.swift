import Foundation
import QwenVoiceCore

/// Internal diagnostics builds only: records the shape of the last StoreKit purchase
/// error that was not a user cancellation (type, enum case, domain, code, underlying
/// chain) in the devicectl-pullable caches, so a local StoreKit lane can see what the
/// adapter received. Never touches paid access; distribution builds write nothing.
enum IOSCommerceErrorDiagnostics {
    static func recordPurchaseFailure(_ error: any Error) {
        guard RuntimeDebugGate.internalDiagnosticsAvailable,
              let root = IOSPullableDiagnosticsMirror.pullableRoot,
              let data = purchaseFailureRecord(error) else { return }
        let directory = root.appendingPathComponent("commerce", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try? data.write(to: directory.appendingPathComponent("last-purchase-error.json"), options: .atomic)
    }

    /// Schema v2 keeps the typed `DiagnosticPrivacy` summary only. v1 stored a
    /// `String(describing:)` prefix, which carries user-info values such as a
    /// failing URL or file path (AUD-08).
    static func purchaseFailureRecord(_ error: any Error, recordedAt: Date = Date()) -> Data? {
        struct Record: Encodable {
            let schemaVersion: Int
            let recordedAt: String
            let error: DiagnosticErrorSummary
        }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try? encoder.encode(Record(
            schemaVersion: 2,
            recordedAt: ISO8601DateFormatter().string(from: recordedAt),
            error: DiagnosticPrivacy.summary(of: error)
        ))
    }
}
