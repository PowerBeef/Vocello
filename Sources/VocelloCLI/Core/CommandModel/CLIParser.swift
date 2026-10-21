import Foundation

/// A command's parsed options and operands. Values and flags come only from
/// options the command (or the global set) declares, so a lookup of an
/// undeclared name is always empty.
public struct Args: Sendable, Equatable {
    private var values: [String: String]
    private var flags: Set<String>
    public private(set) var positionals: [String]

    public init(values: [String: String] = [:], flags: Set<String> = [], positionals: [String] = []) {
        self.values = values
        self.flags = flags
        self.positionals = positionals
    }

    public func string(_ key: String) -> String? { values[key] }
    public func flag(_ key: String) -> Bool { flags.contains(key) }

    public func require(_ key: String, _ hint: String) throws -> String {
        guard let value = values[key], !value.isEmpty else {
            throw CLIError(.usageError, "missing required --\(key) (\(hint))")
        }
        return value
    }

    /// The options and operands as data, for a request digest: values, flags and
    /// operands, leaving out `excluded` names (output format, verbosity, the id itself).
    public func canonicalForm(excluding excluded: Set<String>) -> CLIJSONValue {
        .object([
            "values": .object(values.filter { !excluded.contains($0.key) }.mapValues { .string($0) }),
            "flags": .array(flags.subtracting(excluded).sorted().map { .string($0) }),
            "operands": .array(positionals.map { .string($0) }),
        ])
    }

    mutating func set(_ key: String, _ value: String) { values[key] = value }
    mutating func set(flag key: String) { flags.insert(key) }
    mutating func append(positional: String) { positionals.append(positional) }
}

/// What `vocello …` asked for, resolved against the command model.
public struct CLIInvocation: Sendable, Equatable {
    public enum Action: Sendable, Equatable {
        case run
        case help
    }

    public let action: Action
    /// Canonical command names from the top, such as `["models", "install"]`;
    /// empty for top-level help.
    public let path: [String]
    public let args: Args
    public let format: CLIOutputFormat
    public let verbosity: CLIVerbosity?
    public let noInput: Bool

    /// The envelope's `command`: the path joined with dots.
    public var commandName: String { path.isEmpty ? "help" : path.joined(separator: ".") }
}

/// Parses `vocello …` against the declared command tree. Strict: an unknown
/// command, subcommand or option, a missing or unexpected value and an extra
/// operand are usage errors with a did-you-mean suggestion where one is close.
public enum CLIParser {
    public static let modeShortcuts = ["custom", "design", "clone"]

    public static func parse(
        _ argv: [String],
        tree: [CLICommandSpec] = VocelloCommandTree.commands
    ) throws -> CLIInvocation {
        var parser = Parser(argv: expandingShortcut(argv), tree: tree)
        return try parser.run()
    }

    /// The parsed options of `argv` for the command at `path`, as if typed
    /// after it (tests and helpers).
    public static func args(_ argv: [String], for path: String...) throws -> Args {
        try parse(path + argv).args
    }

    /// `vocello custom|design|clone …` runs `generate --mode <mode> …`, or
    /// `batch --mode <mode> …` when a `--file` names lines to synthesize.
    static func expandingShortcut(_ argv: [String]) -> [String] {
        guard let first = argv.first, modeShortcuts.contains(first) else { return argv }
        let rest = Array(argv.dropFirst())
        let options = rest.prefix { $0 != "--" }
        let toBatch = options.contains { $0 == "--file" || $0.hasPrefix("--file=") }
        return [toBatch ? "batch" : "generate", "--mode", first] + rest
    }

    /// The output format `argv` asks for, read leniently so a usage error can
    /// still be reported in the format the caller expects.
    public static func requestedFormat(_ argv: [String]) -> CLIOutputFormat {
        var format = CLIOutputFormat.text
        var index = 0
        while index < argv.count, argv[index] != "--" {
            let token = argv[index]
            if token == "--json" { format = .json }
            if token == "--ndjson" { format = .ndjson }
            if token.hasPrefix("--output-format=") {
                format = CLIOutputFormat(rawValue: String(token.dropFirst("--output-format=".count))) ?? format
            } else if token == "--output-format", index + 1 < argv.count {
                format = CLIOutputFormat(rawValue: argv[index + 1]) ?? format
            }
            index += 1
        }
        return format
    }

    private struct Parser {
        let argv: [String]
        let tree: [CLICommandSpec]
        var index = 0
        var optionsEnded = false
        var path: [CLICommandSpec] = []
        /// The current command's subcommand was already named (or defaulted).
        var helpRequested = false
        var helpByWord = false
        var args = Args()
        var formats: [(String, CLIOutputFormat)] = []
        var quiet = false
        var verbose = false
        var noInput = false
        /// Subcommand tokens already taken by an option that preceded them.
        var skipped = Set<Int>()

        init(argv: [String], tree: [CLICommandSpec]) {
            self.argv = argv
            self.tree = tree
        }

        var current: CLICommandSpec? { path.last }
        var commandLine: String { (["vocello"] + path.map(\.name)).joined(separator: " ") }

        /// `-h`/`--help` anywhere before `--` asks for help, even past a mistake.
        var helpTokenPresent: Bool {
            argv.prefix { $0 != "--" }.contains { $0 == "-h" || $0 == "--help" }
        }

        mutating func run() throws -> CLIInvocation {
            do {
                return try parseAll()
            } catch is CLIError where helpTokenPresent {
                // Help for the command named so far, rather than the mistake.
                return CLIInvocation(
                    action: .help, path: path.map(\.name), args: Args(),
                    format: (try? resolvedFormat()) ?? .text, verbosity: nil, noInput: noInput
                )
            }
        }

        mutating func parseAll() throws -> CLIInvocation {
            while index < argv.count {
                let token = argv[index]
                index += 1
                if skipped.contains(index - 1) { continue }
                if !optionsEnded, token == "--" {
                    optionsEnded = true
                    try enterDefaultSubcommandIfNeeded()
                    continue
                }
                if !optionsEnded, token.hasPrefix("-"), token != "-" {
                    try option(token)
                } else {
                    try operand(token)
                }
            }
            if !helpRequested {
                try enterDefaultSubcommandIfNeeded()
                if let current, !current.subcommands.isEmpty {
                    throw usage(
                        "missing subcommand for \(commandLine)",
                        hint: "one of: \(current.subcommands.map(\.name).joined(separator: ", "))"
                    )
                }
                if path.isEmpty {
                    throw usage("missing command", hint: "run `vocello help` for the commands")
                }
                try checkRequiredOperands()
            }
            let format = try resolvedFormat()
            if format.isMachine, !helpRequested, let top = path.first, !top.machineContract {
                throw usage(
                    "\(top.name) writes its own output and does not take --output-format \(format.rawValue)",
                    hint: "run it without --json or --ndjson"
                )
            }
            return CLIInvocation(
                action: helpRequested ? .help : .run,
                path: path.map(\.name),
                args: args,
                format: format,
                verbosity: quiet ? .quiet : verbose ? .verbose : nil,
                noInput: noInput
            )
        }

        // MARK: Options

        mutating func option(_ token: String) throws {
            if token == "-h" {
                helpRequested = true
                return
            }
            if path.isEmpty, token == "-v" || token == "--version" {
                path = [try command(named: "version")]
                return
            }
            guard token.hasPrefix("--"), token.count > 2 else {
                throw usage("unknown option \(token)", hint: "options are spelled --name; see `\(commandLine) --help`")
            }
            let body = token.dropFirst(2)
            let name: String
            var inlineValue: String?
            if let equals = body.firstIndex(of: "=") {
                name = String(body[..<equals])
                inlineValue = String(body[body.index(after: equals)...])
            } else {
                name = String(body)
            }

            if let global = CLIGlobalOptionSpecs.named(name) {
                try apply(global: global, value: takeValue(for: global, inline: inlineValue))
                return
            }
            if let current, !current.subcommands.isEmpty {
                // An option before the subcommand belongs to the subcommand named
                // later on the line, else to the default one.
                if let named = laterSubcommand(of: current) {
                    path.append(named.spec)
                    skipped.insert(named.index)
                } else {
                    guard current.defaultSubcommand != nil else {
                        throw unknownOption(name, among: [])
                    }
                    try enterDefaultSubcommandIfNeeded()
                }
            }
            guard let current else {
                throw unknownOption(name, among: CLIGlobalOptionSpecs.all)
            }
            if let refusal = current.refusedOptions[name] {
                throw usage(refusal)
            }
            guard let spec = current.option(named: name) else {
                throw unknownOption(name, among: current.options.filter { !$0.hidden } + CLIGlobalOptionSpecs.all)
            }
            let value = try takeValue(for: spec, inline: inlineValue)
            if let value { args.set(spec.name, value) } else { args.set(flag: spec.name) }
        }

        mutating func takeValue(for spec: CLIOptionSpec, inline: String?) throws -> String? {
            if spec.isFlag {
                if let inline {
                    throw usage("--\(spec.name) takes no value (got \"\(inline)\"): pass the bare flag --\(spec.name)")
                }
                return nil
            }
            if let inline { return inline }
            if spec.valueOptional, index >= argv.count || argv[index].hasPrefix("-") {
                return nil
            }
            guard index < argv.count, !argv[index].hasPrefix("--") else {
                throw usage(
                    "--\(spec.name) needs a value (\(spec.placeholder ?? "value"))",
                    hint: "pass --\(spec.name)=VALUE for a value that starts with --"
                )
            }
            defer { index += 1 }
            return argv[index]
        }

        mutating func apply(global: CLIOptionSpec, value: String?) throws {
            switch global.name {
            case "output-format":
                guard let value, let format = CLIOutputFormat(rawValue: value) else {
                    throw usage(
                        "invalid --output-format '\(value ?? "")'",
                        hint: "use \(CLIOutputFormat.allCases.map(\.rawValue).joined(separator: " | "))"
                    )
                }
                formats.append(("--output-format \(value)", format))
            case "json":
                formats.append(("--json", .json))
                args.set(flag: "json")
            case "ndjson":
                formats.append(("--ndjson", .ndjson))
            case "quiet":
                quiet = true
                args.set(flag: "quiet")
            case "verbose":
                verbose = true
                args.set(flag: "verbose")
            case "no-input":
                noInput = true
                args.set(flag: "no-input")
            case "help":
                helpRequested = true
            default:
                if let value { args.set(global.name, value) } else { args.set(flag: global.name) }
            }
        }

        func resolvedFormat() throws -> CLIOutputFormat {
            guard let first = formats.first else { return .text }
            if let conflict = formats.first(where: { $0.1 != first.1 }) {
                throw usage("\(first.0) conflicts with \(conflict.0): choose one output format")
            }
            return first.1
        }

        // MARK: Operands

        mutating func operand(_ token: String) throws {
            guard let current else {
                if token == "help" {
                    helpRequested = true
                    helpByWord = true
                    return
                }
                path = [try command(named: token)]
                return
            }
            if !current.subcommands.isEmpty, !optionsEnded {
                if token == "help" {
                    helpRequested = true
                    return
                }
                guard let sub = current.subcommand(named: token) else {
                    throw unknownCommand(token, among: current.subcommands, under: commandLine)
                }
                path.append(sub)
                return
            }
            if helpByWord, current.subcommands.isEmpty, !optionsEnded {
                throw usage("\(commandLine) has no subcommand '\(token)'")
            }
            guard args.positionals.count < current.positionals.count else {
                throw usage(
                    "unexpected argument '\(token)' for \(commandLine)",
                    hint: "see `\(commandLine) --help`"
                )
            }
            args.append(positional: token)
        }

        /// The first later token (before `--`) naming one of `parent`'s subcommands.
        func laterSubcommand(of parent: CLICommandSpec) -> (spec: CLICommandSpec, index: Int)? {
            var position = index
            while position < argv.count, argv[position] != "--" {
                if !argv[position].hasPrefix("-"), let sub = parent.subcommand(named: argv[position]) {
                    return (sub, position)
                }
                position += 1
            }
            return nil
        }

        mutating func enterDefaultSubcommandIfNeeded() throws {
            while let current, !current.subcommands.isEmpty, let name = current.defaultSubcommand {
                guard let sub = current.subcommand(named: name) else { return }
                path.append(sub)
            }
        }

        func checkRequiredOperands() throws {
            guard let current else { return }
            for (position, operand) in current.positionals.enumerated() where operand.required {
                guard position < args.positionals.count else {
                    throw usage(
                        "missing <\(operand.name)> for \(commandLine): \(operand.summary)",
                        hint: "see `\(commandLine) --help`"
                    )
                }
            }
        }

        func command(named token: String) throws -> CLICommandSpec {
            guard let spec = tree.first(where: { $0.name == token || $0.aliases.contains(token) }) else {
                throw unknownCommand(token, among: tree.filter { !$0.internalTool }, under: "vocello")
            }
            return spec
        }

        // MARK: Errors

        func usage(_ message: String, hint: String? = nil) -> CLIError {
            CLIError(.usageError, message, hint: hint)
        }

        func unknownOption(_ name: String, among options: [CLIOptionSpec]) -> CLIError {
            let suggestion = CLISuggestion.closest(to: name, in: options.map(\.name))
            return usage(
                "unknown option --\(name) for \(commandLine)",
                hint: suggestion.map { "did you mean --\($0)? See `\(commandLine) --help`" }
                    ?? "see `\(commandLine) --help`"
            )
        }

        func unknownCommand(_ token: String, among commands: [CLICommandSpec], under parent: String) -> CLIError {
            let names = commands.flatMap { [$0.name] + $0.aliases }
            let suggestion = CLISuggestion.closest(to: token, in: names)
            return usage(
                "unknown command '\(token)' for \(parent)",
                hint: suggestion.map { "did you mean '\($0)'? See `\(parent) help`" } ?? "see `\(parent) help`"
            )
        }
    }
}

/// Did-you-mean: the closest candidate within a small edit distance, where a
/// swapped pair of letters counts as one edit.
enum CLISuggestion {
    static func closest(to word: String, in candidates: [String]) -> String? {
        let limit = word.count <= 3 ? 1 : word.count <= 8 ? 2 : 3
        var best: (candidate: String, distance: Int)?
        for candidate in candidates {
            let distance = editDistance(word, candidate)
            if distance <= limit, best == nil || distance < best!.distance {
                best = (candidate, distance)
            }
        }
        return best?.candidate
    }

    /// Optimal string alignment distance.
    static func editDistance(_ a: String, _ b: String) -> Int {
        let a = Array(a), b = Array(b)
        guard !a.isEmpty else { return b.count }
        guard !b.isEmpty else { return a.count }
        var table = Array(repeating: Array(repeating: 0, count: b.count + 1), count: a.count + 1)
        for i in 0 ... a.count { table[i][0] = i }
        for j in 0 ... b.count { table[0][j] = j }
        for i in 1 ... a.count {
            for j in 1 ... b.count {
                let cost = a[i - 1] == b[j - 1] ? 0 : 1
                table[i][j] = min(table[i - 1][j] + 1, table[i][j - 1] + 1, table[i - 1][j - 1] + cost)
                if i > 1, j > 1, a[i - 1] == b[j - 2], a[i - 2] == b[j - 1] {
                    table[i][j] = min(table[i][j], table[i - 2][j - 2] + 1)
                }
            }
        }
        return table[a.count][b.count]
    }
}
