import Foundation

/// The machine output format, from `--output-format`, `--json` or `--ndjson`.
/// Text is for people and is not part of the contract.
public enum CLIOutputFormat: String, Sendable, CaseIterable, Codable {
    case text, json, ndjson

    public var isMachine: Bool { self != .text }
}

/// The contract revision: bumped by every additive v1 change
/// (`config/cli-contract/v1/baseline.json`).
public enum CLIContract {
    public static let schemaVersion = 1
    public static let revision = 1
}

public struct CLIWarning: Codable, Sendable, Equatable {
    public let code: String
    public let message: String
    public let detail: [String: CLIJSONValue]?

    public init(code: String, message: String, detail: [String: CLIJSONValue]? = nil) {
        self.code = code
        self.message = message
        self.detail = detail
    }

    private enum CodingKeys: String, CodingKey { case code, message, detail }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(code, forKey: .code)
        try container.encode(message, forKey: .message)
        try container.encodeIfPresent(detail, forKey: .detail)
    }
}

public struct CLIEnvelopeMeta: Encodable, Sendable, Equatable {
    public let vocelloVersion: String
    public let build: String
    public let contractRevision: Int
    public let durationMs: Int
    public let replayed: Bool
}

/// `{schemaVersion, ok, command, requestID, result, error, warnings, meta}`: the
/// one object stdout carries in json mode, and the payload of the final
/// `result` record in ndjson mode. `result` may accompany a failure (a partial
/// batch keeps its rows).
public struct CLIEnvelope: Encodable {
    public let ok: Bool
    public let command: String
    public let requestID: String
    public let result: (any Encodable)?
    public let error: CLIErrorObject?
    public let warnings: [CLIWarning]
    public let meta: CLIEnvelopeMeta

    private enum CodingKeys: String, CodingKey {
        case schemaVersion, ok, command, requestID, result, error, warnings, meta
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(CLIContract.schemaVersion, forKey: .schemaVersion)
        try container.encode(ok, forKey: .ok)
        try container.encode(command, forKey: .command)
        try container.encode(requestID, forKey: .requestID)
        if let result {
            try container.encode(CLIAnyEncodable(result), forKey: .result)
        } else {
            try container.encodeNil(forKey: .result)
        }
        try encodeOrNull(error, forKey: .error, in: &container)
        try container.encode(warnings, forKey: .warnings)
        try container.encode(meta, forKey: .meta)
    }
}

struct CLIAnyEncodable: Encodable {
    let value: any Encodable
    init(_ value: any Encodable) { self.value = value }
    func encode(to encoder: any Encoder) throws { try value.encode(to: encoder) }
}

/// A result with no fields, for a machine-mode command that reports nothing else.
public struct CLIEmptyResult: Encodable, Sendable {
    public init() {}
}
