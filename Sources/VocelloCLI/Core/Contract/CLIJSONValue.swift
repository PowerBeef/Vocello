import Foundation

/// A JSON value for the contract's open-ended fields (`error.detail`, event `data`).
/// 64-bit identifiers such as seeds travel as decimal strings, never numbers.
public enum CLIJSONValue: Codable, Sendable, Equatable {
    case string(String)
    case integer(Int)
    /// An integer above `Int.max`, kept exact (a seed drawn from the full range).
    case unsigned(UInt64)
    case number(Double)
    case bool(Bool)
    case array([CLIJSONValue])
    case object([String: CLIJSONValue])
    case null

    public init(from decoder: any Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .integer(value)
        } else if let value = try? container.decode(UInt64.self) {
            self = .unsigned(value)
        } else if let value = try? container.decode(Double.self) {
            self = .number(value)
        } else if let value = try? container.decode(String.self) {
            self = .string(value)
        } else if let value = try? container.decode([CLIJSONValue].self) {
            self = .array(value)
        } else {
            self = .object(try container.decode([String: CLIJSONValue].self))
        }
    }

    public func encode(to encoder: any Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value): try container.encode(value)
        case .integer(let value): try container.encode(value)
        case .unsigned(let value): try container.encode(value)
        case .number(let value): try container.encode(value)
        case .bool(let value): try container.encode(value)
        case .array(let value): try container.encode(value)
        case .object(let value): try container.encode(value)
        case .null: try container.encodeNil()
        }
    }
}

extension CLIJSONValue {
    /// Any encodable value as a JSON value (64-bit integers kept exact).
    public init(encoding value: some Encodable) throws {
        self = try JSONDecoder().decode(CLIJSONValue.self, from: CLIJSONEncoding.encoder().encode(value))
    }
}

extension CLIJSONValue: ExpressibleByStringLiteral, ExpressibleByIntegerLiteral, ExpressibleByBooleanLiteral {
    public init(stringLiteral value: String) { self = .string(value) }
    public init(integerLiteral value: Int) { self = .integer(value) }
    public init(booleanLiteral value: Bool) { self = .bool(value) }
}

/// The one JSON encoding every contract surface uses: sorted keys, unescaped
/// slashes, one line.
enum CLIJSONEncoding {
    static func encoder() -> JSONEncoder {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return encoder
    }

    static func line<T: Encodable>(_ value: T) throws -> Data {
        var data = try encoder().encode(value)
        data.append(0x0A)
        return data
    }

    /// The envelope written when the real one cannot be encoded, so stdout still
    /// carries exactly one envelope and the exit status still says failure.
    static func unencodableEnvelope(command: String, requestID: String) -> Data {
        let fallback = CLIEnvelope(
            ok: false, command: command, requestID: requestID, result: nil,
            error: CLIErrorObject(code: .internalError, message: "the command's result could not be encoded as JSON"),
            warnings: [],
            meta: CLIEnvelopeMeta(
                vocelloVersion: vocelloCLIVersion, build: vocelloCLIBuild, contractRevision: CLIContract.revision,
                durationMs: 0, replayed: false
            )
        )
        return (try? line(fallback)) ?? Data("{\"ok\":false}\n".utf8)
    }
}
