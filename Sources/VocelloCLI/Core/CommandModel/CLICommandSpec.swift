import Foundation

/// What an option's value is, for help, completion, capabilities and validation
/// of the shape (the command validates the meaning).
public enum CLIValueKind: Sendable, Equatable {
    case text
    case file
    case directory
    case integer
    /// An unsigned 64-bit value such as a seed, a decimal string in JSON.
    case unsignedInteger
    case choice([String])
    /// A comma-separated subset of the choices.
    case list([String])

    var typeName: String {
        switch self {
        case .text: return "string"
        case .file: return "file"
        case .directory: return "directory"
        case .integer: return "integer"
        case .unsignedInteger: return "uint64"
        case .choice: return "choice"
        case .list: return "list"
        }
    }

    var choices: [String]? {
        switch self {
        case .choice(let values), .list(let values): return values
        default: return nil
        }
    }
}

/// One `--option`. A flag takes no value; any other option takes exactly one
/// (`--name value` or `--name=value`); repeating it keeps the last value.
public struct CLIOptionSpec: Sendable, Equatable {
    public let name: String
    public let value: CLIValueKind?
    public let placeholder: String?
    public let summary: String
    /// Internal-diagnostics options stay out of help and completion.
    public let hidden: Bool
    /// The value may be omitted (`--delivery` alone runs a default set): a next
    /// token that starts with `--` is then the next option, not this value.
    public let valueOptional: Bool

    public static func flag(_ name: String, _ summary: String, hidden: Bool = false) -> CLIOptionSpec {
        CLIOptionSpec(name: name, value: nil, placeholder: nil, summary: summary, hidden: hidden, valueOptional: false)
    }

    public static func value(
        _ name: String, _ kind: CLIValueKind, _ placeholder: String, _ summary: String,
        hidden: Bool = false, optional: Bool = false
    ) -> CLIOptionSpec {
        CLIOptionSpec(
            name: name, value: kind, placeholder: placeholder, summary: summary, hidden: hidden,
            valueOptional: optional
        )
    }

    public var isFlag: Bool { value == nil }
}

public struct CLIPositionalSpec: Sendable, Equatable {
    public let name: String
    public let summary: String
    public let required: Bool
    public let value: CLIValueKind

    public init(_ name: String, _ summary: String, required: Bool = false, value: CLIValueKind = .text) {
        self.name = name
        self.summary = summary
        self.required = required
        self.value = value
    }
}

/// A command or subcommand. A command with subcommands runs its default
/// subcommand when none is named.
public struct CLICommandSpec: Sendable, Equatable {
    public let name: String
    public let aliases: [String]
    public let summary: String
    public let usage: [String]
    public let discussion: String?
    public let options: [CLIOptionSpec]
    public let positionals: [CLIPositionalSpec]
    public let subcommands: [CLICommandSpec]
    public let defaultSubcommand: String?
    /// Options this command refuses with a reason, rather than as unknown.
    public let refusedOptions: [String: String]
    /// Internal tools keep their own output and stay out of the top-level list.
    public let internalTool: Bool
    /// Whether the command reports through the machine contract (`--json`).
    public let machineContract: Bool

    public init(
        name: String,
        aliases: [String] = [],
        summary: String,
        usage: [String] = [],
        discussion: String? = nil,
        options: [CLIOptionSpec] = [],
        positionals: [CLIPositionalSpec] = [],
        subcommands: [CLICommandSpec] = [],
        defaultSubcommand: String? = nil,
        refusedOptions: [String: String] = [:],
        internalTool: Bool = false,
        machineContract: Bool = true
    ) {
        self.name = name
        self.aliases = aliases
        self.summary = summary
        self.usage = usage
        self.discussion = discussion
        self.options = options
        self.positionals = positionals
        self.subcommands = subcommands
        self.defaultSubcommand = defaultSubcommand
        self.refusedOptions = refusedOptions
        self.internalTool = internalTool
        self.machineContract = machineContract
    }

    public func subcommand(named token: String) -> CLICommandSpec? {
        subcommands.first { $0.name == token || $0.aliases.contains(token) }
    }

    public func option(named name: String) -> CLIOptionSpec? {
        options.first { $0.name == name }
    }
}

/// The options every command accepts, anywhere before `--`.
public enum CLIGlobalOptionSpecs {
    public static let all: [CLIOptionSpec] = [
        .value("output-format", .choice(CLIOutputFormat.allCases.map(\.rawValue)), "format",
               "text (default), json (one envelope on stdout) or ndjson (events, then the envelope)"),
        .flag("json", "same as --output-format json"),
        .flag("ndjson", "same as --output-format ndjson"),
        .flag("quiet", "suppress progress notes on stderr"),
        .flag("verbose", "more progress notes on stderr (also in the json formats)"),
        .flag("no-input", "never prompt and never read stdin unless a flag names it (-)"),
        .value("data-dir", .directory, "dir",
               "runtime data directory (default ~/Library/Application Support/QwenVoice)"),
        .value("manifest", .file, "path", "override the bundled qwenvoice_contract.json"),
        .flag("help", "show help for the command"),
    ]

    static func named(_ name: String) -> CLIOptionSpec? { all.first { $0.name == name } }
}
