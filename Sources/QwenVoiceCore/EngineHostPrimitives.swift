import Foundation

public enum RemoteErrorCode: String, Codable, Equatable, Sendable {
    case generic
    case cancelled
}

public struct RemoteErrorPayload: Error, Codable, Equatable, Sendable, LocalizedError {
    public let message: String
    public let domain: String?
    public let code: RemoteErrorCode
    /// Curated subset of `NSError.userInfo` that survives the XPC hop — useful
    /// for triaging support reports without leaking non-Sendable state across
    /// the wire (Tier 3.2). Optional for schema compatibility with older
    /// clients that did not emit this field.
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

public struct EngineCapabilities: Codable, Equatable, Sendable {
    public let supportsBatchGeneration: Bool
    public let supportsAudioPreparation: Bool
    public let supportsInteractivePrefetch: Bool
    public let supportsMemoryTrim: Bool
    public let supportsPreparedVoiceManagement: Bool

    public init(
        supportsBatchGeneration: Bool,
        supportsAudioPreparation: Bool,
        supportsInteractivePrefetch: Bool,
        supportsMemoryTrim: Bool,
        supportsPreparedVoiceManagement: Bool
    ) {
        self.supportsBatchGeneration = supportsBatchGeneration
        self.supportsAudioPreparation = supportsAudioPreparation
        self.supportsInteractivePrefetch = supportsInteractivePrefetch
        self.supportsMemoryTrim = supportsMemoryTrim
        self.supportsPreparedVoiceManagement = supportsPreparedVoiceManagement
    }

    public static let macOSXPCDefault = EngineCapabilities(
        supportsBatchGeneration: true,
        supportsAudioPreparation: false,
        supportsInteractivePrefetch: true,
        supportsMemoryTrim: false,
        supportsPreparedVoiceManagement: true
    )

    public static let iOSExtensionDefault = EngineCapabilities(
        supportsBatchGeneration: false,
        supportsAudioPreparation: true,
        supportsInteractivePrefetch: true,
        supportsMemoryTrim: true,
        supportsPreparedVoiceManagement: true
    )
}

public enum QwenVoiceWireSchema {
    public static let currentVersion = 2
    public static let legacyMissingVersion = 1

    public static func validate(version: Int, codingPath: [CodingKey]) throws {
        guard version == currentVersion else {
            throw DecodingError.dataCorrupted(
                DecodingError.Context(
                    codingPath: codingPath,
                    debugDescription: "Unsupported QwenVoice wire schema version \(version)."
                )
            )
        }
    }
}

public enum QwenVoiceWireCodec {
    private static let encoder = JSONEncoder()
    private static let decoder = JSONDecoder()

    public static func encode<T: Encodable>(_ value: T) throws -> Data {
        try encoder.encode(value)
    }

    public static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        try decoder.decode(T.self, from: data)
    }
}
