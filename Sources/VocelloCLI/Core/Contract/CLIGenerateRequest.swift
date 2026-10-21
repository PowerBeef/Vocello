import Foundation

/// A generation request as an agent sends it (`vocello run --request`, and the
/// MCP server's `generate_speech` input): a JSON object whose fields are
/// `generate`'s options. It becomes `generate` arguments and goes through the
/// same strict parser, so a request can never do what the command line refuses.
/// `config/cli-contract/v1/generate-request.schema.json` describes it.
public enum CLIGenerateRequest {
    enum Kind: Equatable {
        /// A string value.
        case text
        /// A decimal string or a non-negative integer.
        case unsignedInteger
        /// true adds the bare flag; false omits it.
        case flag
        /// false adds the bare flag; true omits it (`stream: false` is `--no-stream`).
        case negatedFlag
    }

    /// Request field → `generate` option.
    static let fields: [String: (option: String, kind: Kind)] = [
        "mode": ("mode", .text),
        "variant": ("variant", .text),
        "text": ("text", .text),
        "textFile": ("text-file", .text),
        "speaker": ("speaker", .text),
        "voiceBrief": ("voice-brief", .text),
        "voice": ("voice", .text),
        "reference": ("reference", .text),
        "transcript": ("transcript", .text),
        "delivery": ("delivery", .text),
        "deliveryCell": ("delivery-cell", .text),
        "language": ("language", .text),
        "seed": ("seed", .unsignedInteger),
        "variation": ("variation", .text),
        "out": ("out", .text),
        "longForm": ("long-form", .text),
        "confirmConsent": ("confirm-consent", .flag),
        "appDelivery": ("app-delivery", .flag),
        "stream": ("no-stream", .negatedFlag),
    ]

    public static let clientRequestIDField = "clientRequestID"

    /// Every field a request may carry.
    public static var fieldNames: Set<String> { Set(fields.keys).union([clientRequestIDField]) }

    /// What idempotency compares is the prepared take (`GenerateCommand.identity`),
    /// so a request and the same `generate` command line are one request.
    public struct Parsed: Sendable, Equatable {
        /// `generate` arguments (options only; the caller adds global ones).
        public let argv: [String]
        public let clientRequestID: String?
    }

    public static func parse(_ value: CLIJSONValue) throws -> Parsed {
        guard case .object(let object) = value else {
            throw CLIError(.invalidInput, "a request is a JSON object of generate options")
        }
        var argv: [String] = []
        var clientRequestID: String?
        for key in object.keys.sorted() {
            let field = object[key] ?? .null
            if key == clientRequestIDField {
                switch field {
                case .null:
                    continue
                case .string(let id):
                    try CLIRequestLedger.validate(id: id)
                    clientRequestID = id
                    continue
                default:
                    throw CLIError(.invalidInput, "\(key) must be a string")
                }
            }
            guard let (option, kind) = fields[key] else {
                let suggestion = CLISuggestion.closest(to: key, in: Array(fieldNames))
                throw CLIError(
                    .usageError, "unknown request field '\(key)'",
                    hint: suggestion.map { "did you mean '\($0)'?" } ?? "see generate-request.schema.json"
                )
            }
            switch (kind, field) {
            case (.text, .string(let text)):
                guard text != "-" || (key != "text" && key != "textFile") else {
                    throw CLIError(.invalidInput, "\(key) cannot be \"-\" in a request: stdin carries the requests")
                }
                argv += ["--\(option)=\(text)"]
            case (.unsignedInteger, .string(let text)) where UInt64(text) != nil:
                argv += ["--\(option)=\(text)"]
            case (.unsignedInteger, .integer(let number)) where number >= 0:
                argv += ["--\(option)=\(number)"]
            case (.unsignedInteger, .unsigned(let number)):
                argv += ["--\(option)=\(number)"]
            case (.flag, .bool(let on)):
                if on { argv.append("--\(option)") }
            case (.negatedFlag, .bool(let on)):
                if !on { argv.append("--\(option)") }
            case (_, .null):
                continue
            default:
                let expected: String
                switch kind {
                case .text: expected = "a string"
                case .unsignedInteger: expected = "an unsigned integer or its decimal string"
                case .flag, .negatedFlag: expected = "true or false"
                }
                throw CLIError(.invalidInput, "\(key) must be \(expected)")
            }
        }
        return Parsed(argv: argv, clientRequestID: clientRequestID)
    }
}
