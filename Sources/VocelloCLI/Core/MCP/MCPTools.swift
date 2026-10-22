import Foundation

/// One MCP tool (RF-29): what an agent sees, and the `vocello` command it
/// runs. Arguments become that command's options and operands and go through
/// the same strict parser, so a tool can never do what the command line
/// refuses; paths pass `MCPPathPolicy` first.
struct MCPTool: Sendable {
    enum Kind: Sendable, Equatable {
        /// A read: runs at once, beside anything else.
        case read
        /// Uses the engine or changes a store: waits its turn at the gate.
        case engine
        /// Answered by the server itself.
        case server
    }

    struct Argument: Sendable {
        enum Target: Sendable, Equatable {
            case option(String)
            case flag(String)
            case operand
            /// Present, it runs the command at this path with the value as its operand.
            case selectsCommand([String])
        }

        let name: String
        let schema: CLIJSONValue
        let target: Target
        let required: Bool
        /// Set for a path the policy confines.
        let access: MCPPathPolicy.Access?

        init(
            _ name: String, _ schema: CLIJSONValue, _ target: Target, required: Bool = false,
            access: MCPPathPolicy.Access? = nil
        ) {
            self.name = name
            self.schema = schema
            self.target = target
            self.required = required
            self.access = access
        }
    }

    struct Hints: Sendable {
        var readOnly = false
        var destructive = false
        var idempotent = false
        var openWorld = false
    }

    let name: String
    let title: String
    let description: String
    let kind: Kind
    let path: [String]
    let arguments: [Argument]
    let hints: Hints
    /// generate_speech: the arguments are one generation request.
    var takesGenerationRequest = false

    var inputSchema: CLIJSONValue {
        if takesGenerationRequest { return MCPTools.generationRequestSchema }
        return .object([
            "type": "object",
            "properties": .object(Dictionary(uniqueKeysWithValues: arguments.map { ($0.name, $0.schema) })),
            "required": .array(arguments.filter(\.required).map { .string($0.name) }),
            "additionalProperties": false,
        ])
    }

    /// How tools/list describes it.
    var definition: CLIJSONValue {
        .object([
            "name": .string(name),
            "title": .string(title),
            "description": .string(description),
            "inputSchema": inputSchema,
            "annotations": .object([
                "title": .string(title),
                "readOnlyHint": .bool(hints.readOnly),
                "destructiveHint": .bool(hints.destructive),
                "idempotentHint": .bool(hints.idempotent),
                "openWorldHint": .bool(hints.openWorld),
            ]),
        ])
    }

    /// The command line `arguments` ask for: the command path, its options and
    /// its operands (after `--`, so an operand may start with a dash). The
    /// server adds the global options.
    func commandLine(
        _ arguments: [String: CLIJSONValue], policy: MCPPathPolicy
    ) throws -> (path: [String], options: [String], operands: [String]) {
        if takesGenerationRequest { return try generationCommandLine(arguments, policy: policy) }
        let known = Set(self.arguments.map(\.name))
        for key in arguments.keys.sorted() where !known.contains(key) {
            throw unknownArgument(key, among: Array(known))
        }
        var path = self.path
        var options: [String] = []
        var operands: [String] = []
        for argument in self.arguments {
            guard let value = arguments[argument.name], value != .null else {
                if argument.required {
                    throw CLIError(.usageError, "\(name) needs \(argument.name)")
                }
                continue
            }
            switch argument.target {
            case .flag(let flag):
                guard case .bool(let on) = value else {
                    throw CLIError(.invalidInput, "\(argument.name) must be true or false")
                }
                if on { options.append("--\(flag)") }
            case .option(let option):
                var text = try Self.scalar(value, argument: argument.name)
                if let access = argument.access { text = try policy.check(text, access: access, argument: argument.name) }
                options.append("--\(option)=\(text)")
            case .operand:
                operands.append(try Self.scalar(value, argument: argument.name))
            case .selectsCommand(let alternate):
                path = alternate
                operands.append(try Self.scalar(value, argument: argument.name))
            }
        }
        return (path, options, operands)
    }

    /// generate_speech: the request's paths are confined, then it becomes
    /// `generate` options exactly as `vocello run` makes them.
    private func generationCommandLine(
        _ arguments: [String: CLIJSONValue], policy: MCPPathPolicy
    ) throws -> (path: [String], options: [String], operands: [String]) {
        var request = arguments
        for key in arguments.keys.sorted() where !MCPTools.generationFields.contains(key) {
            throw unknownArgument(key, among: Array(MCPTools.generationFields))
        }
        for (field, access) in [("reference", MCPPathPolicy.Access.read), ("out", .write)] {
            guard let value = request[field], value != .null else { continue }
            guard case .string(let raw) = value else { throw CLIError(.invalidInput, "\(field) must be a string") }
            request[field] = .string(try policy.check(raw, access: access, argument: field))
        }
        let parsed = try CLIGenerateRequest.parse(.object(request))
        var options = parsed.argv
        if let id = parsed.clientRequestID { options.append("--client-request-id=\(id)") }
        return (["generate"], options, [])
    }

    private func unknownArgument(_ key: String, among known: [String]) -> CLIError {
        let suggestion = CLISuggestion.closest(to: key, in: known)
        return CLIError(
            .usageError, "\(name) takes no argument '\(key)'",
            hint: suggestion.map { "did you mean '\($0)'?" } ?? "see the tool's input schema"
        )
    }

    /// A string or an integer, as text.
    private static func scalar(_ value: CLIJSONValue, argument: String) throws -> String {
        switch value {
        case .string(let text): return text
        case .integer(let number): return String(number)
        case .unsigned(let number): return String(number)
        default: throw CLIError(.invalidInput, "\(argument) must be a string")
        }
    }
}

/// The tools `vocello mcp` offers.
enum MCPTools {
    /// generate_speech's fields: a `vocello run` request without `textFile`
    /// (an agent passes the text itself).
    static let generationFields = CLIGenerateRequest.fieldNames.subtracting(["textFile"])

    static func catalog(allowModelInstall: Bool) -> [MCPTool] {
        var tools = [
            MCPTool(
                name: "get_capabilities", title: "Vocello capabilities",
                description: "Describe Vocello on this Mac: generation modes, languages, delivery cells, text limits, "
                    + "error codes and the installed models. Read it before the first generation.",
                kind: .read, path: ["capabilities"], arguments: [], hints: readHints
            ),
            MCPTool(
                name: "get_status", title: "Server status",
                description: "This server's state: its data folder, the folders tools may read and write, whether "
                    + "the engine has started and how many requests are running or waiting.",
                kind: .server, path: [], arguments: [], hints: readHints
            ),
            MCPTool(
                name: "list_speakers", title: "List speakers",
                description: "List the Built-in Voice speakers generate_speech accepts as speaker in custom mode.",
                kind: .read, path: ["speakers", "list"], arguments: [], hints: readHints
            ),
            MCPTool(
                name: "list_languages", title: "List languages",
                description: "List the languages generate_speech accepts as language.",
                kind: .read, path: ["languages", "list"], arguments: [], hints: readHints
            ),
            MCPTool(
                name: "list_deliveries", title: "List deliveries",
                description: "List the delivery preset cells (deliveryCell in custom mode) and the instruction each sends.",
                kind: .read, path: ["deliveries", "list"],
                arguments: [
                    .init("shippedOnly", boolean("One row per preset the app ships, at its shipped intensity."),
                          .flag("shipped-only")),
                ],
                hints: readHints
            ),
            MCPTool(
                name: "list_briefs", title: "List voice briefs",
                description: "List Voice Design's starting briefs: voice descriptions to use as voiceBrief in design mode.",
                kind: .read, path: ["briefs", "list"],
                arguments: [.init("language", string("The speech language to show them in (default english)."), .option("language"))],
                hints: readHints
            ),
            MCPTool(
                name: "list_voices", title: "List saved voices",
                description: "List the saved clone voices (shared with the Vocello app); use one as voice in clone mode.",
                kind: .read, path: ["voices", "list"], arguments: [], hints: readHints
            ),
            MCPTool(
                name: "get_voice", title: "Show a saved voice",
                description: "Show one saved voice: its reference clip, transcript and how it was enrolled.",
                kind: .read, path: ["voices", "show"],
                arguments: [.init("voice", string("The saved voice's name or id."), .operand, required: true)],
                hints: readHints
            ),
            MCPTool(
                name: "list_models", title: "List models",
                description: "List the model packages (Speed and Quality per mode) and whether each is installed.",
                kind: .read, path: ["models", "list"],
                arguments: [.init("id", string("Show only this model."), .operand)],
                hints: readHints
            ),
            MCPTool(
                name: "list_history", title: "List History",
                description: "List takes in the app's History, newest first; with query, only those whose text or "
                    + "voice contains it.",
                kind: .read, path: ["history", "list"],
                arguments: [
                    .init("query", string("Words to find in the text or voice."), .selectsCommand(["history", "search"])),
                    .init("mode", choice(VocelloCommandTree.modes, "Only takes of this mode."), .option("mode")),
                    .init("order", choice(["newest", "oldest", "longest", "shortest", "mode"], "The order (default newest)."),
                          .option("order")),
                    .init("limit", .object([
                        "type": "integer", "minimum": 1, "maximum": 500, "description": "Rows to return (default 50).",
                    ]), .option("limit")),
                ],
                hints: readHints
            ),
            MCPTool(
                name: "get_history_item", title: "Show a take",
                description: "Show one History take with its completion receipt.",
                kind: .read, path: ["history", "show"],
                arguments: [.init("id", historyID, .operand, required: true)],
                hints: readHints
            ),
            MCPTool(
                name: "get_settings", title: "Read settings",
                description: "List the Vocello app's settings, which generation follows when a request leaves them out.",
                kind: .read, path: ["settings", "list"], arguments: [], hints: readHints
            ),
            MCPTool(
                name: "generate_speech", title: "Generate speech",
                description: "Speak text in one of three modes and write a WAV file. custom: a Built-in Voice "
                    + "speaker; design: a voice described by voiceBrief; clone: a "
                    + "saved voice or a reference clip, which needs confirmConsent true. A script longer than one take "
                    + "runs as a long-form project. The result names audioPath. Without out, the file goes under the "
                    + "data folder's outputs; out replaces an existing file only when the take succeeds.",
                kind: .engine, path: ["generate"], arguments: [],
                hints: MCPTool.Hints(readOnly: false, destructive: true, idempotent: false, openWorld: false),
                takesGenerationRequest: true
            ),
            MCPTool(
                name: "enroll_voice", title: "Save a clone voice",
                description: "Save a clone voice from a reference clip, as the app's voice sheet does. Needs "
                    + "confirmConsent true: the user owns the voice or has permission to clone it. Without transcript "
                    + "or audioOnly the clip is recognized on this Mac when Speech is already allowed.",
                kind: .engine, path: ["voices", "enroll"],
                arguments: [
                    .init("name", string("The voice's name."), .option("name"), required: true),
                    .init("audio", string("The reference clip (an absolute path)."), .option("audio"), required: true,
                          access: .read),
                    .init("transcript", string("The clip's words."), .option("transcript")),
                    .init("audioOnly", boolean("Save no transcript: the voice conditions on the audio alone."),
                          .flag("audio-only")),
                    .init("transcribe", choice(["auto", "always", "never"],
                                               "Recognize the clip without a transcript: auto (default, only if Speech is allowed), always or never."),
                          .option("transcribe")),
                    .init("language", string("The reference's language (default: detected from the transcript)."),
                          .option("language")),
                    .init("onWarnings", choice(["keep", "discard", "fail"],
                                               "A clip with quality warnings: keep it, discard it or fail (default)."),
                          .option("on-warnings")),
                    .init("confirmConsent", boolean("Required true: the user owns or has permission to clone this voice."),
                          .flag("confirm-consent"), required: true),
                ],
                hints: MCPTool.Hints(readOnly: false, destructive: false, idempotent: false, openWorld: false)
            ),
            MCPTool(
                name: "delete_voice", title: "Delete a saved voice",
                description: "Delete a saved voice from the store the app shares. It cannot be undone.",
                kind: .engine, path: ["voices", "delete"],
                arguments: [.init("id", string("The saved voice id (see list_voices)."), .option("id"), required: true)],
                hints: MCPTool.Hints(readOnly: false, destructive: true, idempotent: false, openWorld: false)
            ),
            MCPTool(
                name: "export_history_item", title: "Export a take",
                description: "Copy one History take's audio to a .wav file. An existing file is replaced only with replace true.",
                kind: .read, path: ["history", "export"],
                arguments: [
                    .init("id", historyID, .operand, required: true),
                    .init("out", string("The .wav file to write (an absolute path)."), .option("out"), required: true,
                          access: .write),
                    .init("replace", boolean("Overwrite an existing file once the copy is complete."), .flag("replace")),
                ],
                hints: MCPTool.Hints(readOnly: false, destructive: true, idempotent: true, openWorld: false)
            ),
        ]
        if allowModelInstall {
            tools.append(MCPTool(
                name: "install_model", title: "Install a model",
                description: "Download and verify a model package into the store the app shares (several GB). "
                    + "Offered because the server was started with --allow-model-install.",
                kind: .engine, path: ["models", "install"],
                arguments: [.init("id", string("The model id (see list_models)."), .operand, required: true)],
                hints: MCPTool.Hints(readOnly: false, destructive: false, idempotent: true, openWorld: true)
            ))
        }
        return tools
    }

    private static let readHints = MCPTool.Hints(readOnly: true, destructive: false, idempotent: true, openWorld: false)

    private static func string(_ description: String) -> CLIJSONValue {
        .object(["type": "string", "description": .string(description)])
    }

    private static func boolean(_ description: String) -> CLIJSONValue {
        .object(["type": "boolean", "description": .string(description)])
    }

    private static func choice(_ values: [String], _ description: String) -> CLIJSONValue {
        .object(["enum": .array(values.map { .string($0) }), "description": .string(description)])
    }

    private static let historyID: CLIJSONValue = .object([
        "oneOf": .array([
            .object(["type": "string", "pattern": "^[0-9]{1,19}$"]),
            .object(["type": "integer", "minimum": 0]),
        ]),
        "description": "The take's History id (see list_history).",
    ])

    /// generate_speech's input: `config/cli-contract/v1/generate-request.schema.json`
    /// without `textFile` (a test keeps the two equal).
    static let generationRequestSchema: CLIJSONValue = .object([
        "type": "object",
        "properties": .object([
            "mode": choice(VocelloCommandTree.modes, "custom (default), design or clone."),
            "variant": choice(VocelloCommandTree.variants, "The model package; absent, the one the Mac app uses for the mode."),
            "text": string("The script; never \"-\" (stdin carries the requests)."),
            "speaker": string("custom: a Built-in Voice speaker id."),
            "voiceBrief": string("design: the voice description."),
            "voice": string("clone: a saved voice name or id."),
            "reference": string("clone: a reference clip instead of a saved voice."),
            "transcript": string("clone: the reference clip's words."),
            "delivery": string("A delivery instruction (custom and design)."),
            "deliveryCell": string("custom: a preset cell such as calm.normal."),
            "language": string("auto, a language name or a code such as fr."),
            "seed": .object([
                "oneOf": .array([
                    .object(["type": "string", "pattern": "^[0-9]{1,20}$"]),
                    .object(["type": "integer", "minimum": 0]),
                ]),
                "description": "A deterministic sampling seed, preferably as a decimal string.",
            ]),
            "variation": choice(VocelloCommandTree.variations, "Absent, the app's Variation setting."),
            "out": string("The .wav file to write."),
            "longForm": choice(
                ["auto", "always", "never"],
                "auto (default): a script past one take runs as a long-form project, as the apps route it; always: any "
                    + "script does; never: one past a take is refused."
            ),
            "confirmConsent": boolean("Required true to clone: you own or have permission to clone this voice."),
            "appDelivery": boolean("With no delivery given, send the app's default delivery."),
            "stream": boolean("Streaming synthesis (default true)."),
            "clientRequestID": .object([
                "type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9._:-]*$", "maxLength": 128,
                "description": "Idempotency: the same id and request replays the stored result.",
            ]),
        ]),
        "required": .array([.string("text")]),
        "additionalProperties": false,
    ])
}
