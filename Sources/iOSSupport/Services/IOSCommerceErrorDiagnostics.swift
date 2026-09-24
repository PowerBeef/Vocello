import Foundation
import QwenVoiceCore

/// Internal diagnostics builds only: records the shape of the last StoreKit purchase
/// error that was not a user cancellation (type, domain, code, underlying chain) in the
/// devicectl-pullable caches, so a local StoreKit lane can see what the adapter
/// received. Never touches paid access; distribution builds write nothing.
enum IOSCommerceErrorDiagnostics {
    static func recordPurchaseFailure(_ error: any Error) {
        guard RuntimeDebugGate.internalDiagnosticsAvailable,
              let root = IOSPullableDiagnosticsMirror.pullableRoot else { return }
        var chain: [[String: String]] = []
        var current: (any Error)? = error
        while let value = current, chain.count < 5 {
            let nsError = value as NSError
            chain.append([
                "type": String(reflecting: type(of: value)),
                "domain": nsError.domain,
                "code": String(nsError.code),
                "description": String(String(describing: value).prefix(240)),
            ])
            current = nsError.userInfo[NSUnderlyingErrorKey] as? any Error
        }
        let record: [String: Any] = [
            "schemaVersion": 1,
            "recordedAt": ISO8601DateFormatter().string(from: Date()),
            "chain": chain,
        ]
        let directory = root.appendingPathComponent("commerce", isDirectory: true)
        guard let data = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]) else {
            return
        }
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try? data.write(to: directory.appendingPathComponent("last-purchase-error.json"), options: .atomic)
    }
}
