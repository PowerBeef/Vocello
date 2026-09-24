import Foundation

public enum RemoteErrorCode: String, Codable, Equatable, Sendable {
    case generic
    case cancelled
}

public struct RemoteErrorPayload: Error, Codable, Equatable, Sendable, LocalizedError {
    public let message: String
    public let domain: String?
    public let code: RemoteErrorCode
    /// Curated, redacted subset of `NSError.userInfo` — useful for triaging
    /// support reports without carrying non-Sendable state (Tier 3.2).
    /// Optional because older payloads did not emit this field.
    public let details: [String: String]?

    public init(
        message: String,
        domain: String? = nil,
        code: RemoteErrorCode = .generic,
        details: [String: String]? = nil
    ) {
        self.message = Self.redactedMessage(message)
        self.domain = domain
        self.code = code
        self.details = details
    }

    public var errorDescription: String? {
        message
    }

    public static func make(for error: Error) -> RemoteErrorPayload {
        if let remoteError = error as? RemoteErrorPayload {
            return remoteError
        }

        let nsError = error as NSError
        let code: RemoteErrorCode = error is CancellationError ? .cancelled : .generic
        return RemoteErrorPayload(
            message: redactedMessage(nsError.localizedDescription),
            domain: nsError.domain,
            code: code,
            details: capturedDetails(from: nsError)
        )
    }

    private static func capturedDetails(from error: NSError) -> [String: String]? {
        var captured: [String: String] = [:]
        for (key, value) in error.userInfo {
            // String-valued keys survive the hop cleanly; everything else
            // goes through `description` so we get *something* rather than
            // dropping context entirely. Values are capped to keep the
            // payload bounded.
            let stringValue: String
            if let string = value as? String {
                stringValue = string
            } else if let custom = value as? CustomStringConvertible {
                stringValue = custom.description
            } else {
                stringValue = String(describing: value)
            }
            captured[key] = redactedDetailValue(key: key, value: stringValue)
        }
        if let failureReason = error.localizedFailureReason {
            captured["NSLocalizedFailureReason"] = redactedDetailValue(
                key: "NSLocalizedFailureReason",
                value: failureReason
            )
        }
        if let recoverySuggestion = error.localizedRecoverySuggestion {
            captured["NSLocalizedRecoverySuggestion"] = redactedDetailValue(
                key: "NSLocalizedRecoverySuggestion",
                value: recoverySuggestion
            )
        }
        return captured.isEmpty ? nil : captured
    }

    private static func redactedDetailValue(key: String, value: String) -> String {
        let key = key.lowercased()
        if ["prompt", "transcript", "reference"].contains(where: key.contains) {
            return "<redacted>"
        }
        return bounded(redactPaths(in: value))
    }

    private static func redactedMessage(_ value: String) -> String {
        let promptRedacted = value.replacingOccurrences(
            of: #"(?i)\b(prompt|transcript|reference)\b\s*[:=]\s*["“]?[^.,;\n]+"#,
            with: "<redacted>",
            options: .regularExpression
        )
        return bounded(redactPaths(in: promptRedacted))
    }

    private static func redactPaths(in value: String) -> String {
        value.replacingOccurrences(
            of: #"(^|[\s=:'"“(])(?:file://)?/(?:Users|private|var|tmp|Volumes)/[^\s,;)'"”]+"#,
            with: "$1<redacted-path>",
            options: .regularExpression
        )
    }

    private static func bounded(_ value: String) -> String {
        String(value.prefix(512))
    }
}

public enum EngineLifecycleState: String, Codable, Equatable, Sendable {
    case idle
    case launching
    case connected
    case interrupted
    case recovering
    case invalidated
    case failed
}
