import Foundation
import QwenVoiceCore

/// The command model as data: the body of `config/cli-contract/v1/commands.json`
/// and of `vocello capabilities`'s `commands`.
public struct CLICommandModelDocument: Encodable, Sendable {
    public struct Option: Encodable, Sendable {
        let name: String
        let takesValue: Bool
        let valueOptional: Bool
        let type: String
        let choices: [String]?
        let placeholder: String?
        let summary: String
    }

    public struct Operand: Encodable, Sendable {
        let name: String
        let required: Bool
        let type: String
        let choices: [String]?
        let summary: String
    }

    public struct Command: Encodable, Sendable {
        let path: String
        let name: String
        let aliases: [String]
        let summary: String
        let usage: [String]
        let options: [Option]
        let operands: [Operand]
        let subcommands: [String]
        let defaultSubcommand: String?
        let refusedOptions: [String]
        let internalTool: Bool
        let machineContract: Bool
    }

    let schemaVersion: Int
    let contractRevision: Int
    let modeShortcuts: [String]
    let globalOptions: [Option]
    let commands: [Command]

    public init(tree: [CLICommandSpec] = VocelloCommandTree.commands) {
        schemaVersion = CLIContract.schemaVersion
        contractRevision = CLIContract.revision
        modeShortcuts = CLIParser.modeShortcuts
        globalOptions = CLIGlobalOptionSpecs.all.map(Self.option)
        var commands: [Command] = []
        func visit(_ spec: CLICommandSpec, parent: [String]) {
            let path = parent + [spec.name]
            commands.append(Command(
                path: path.joined(separator: "."),
                name: spec.name,
                aliases: spec.aliases,
                summary: spec.summary,
                usage: spec.usage,
                options: spec.options.filter { !$0.hidden }.map(Self.option),
                operands: spec.positionals.map {
                    Operand(name: $0.name, required: $0.required, type: $0.value.typeName,
                            choices: $0.value.choices, summary: $0.summary)
                },
                subcommands: spec.subcommands.map(\.name),
                defaultSubcommand: spec.defaultSubcommand,
                refusedOptions: spec.refusedOptions.keys.sorted(),
                internalTool: spec.internalTool,
                machineContract: spec.machineContract
            ))
            for sub in spec.subcommands { visit(sub, parent: path) }
        }
        for spec in tree { visit(spec, parent: []) }
        self.commands = commands
    }

    static func option(_ spec: CLIOptionSpec) -> Option {
        Option(
            name: spec.name, takesValue: !spec.isFlag, valueOptional: spec.valueOptional,
            type: spec.value?.typeName ?? "flag", choices: spec.value?.choices,
            placeholder: spec.placeholder, summary: spec.summary
        )
    }

    /// Pretty, sorted JSON as checked in.
    public func renderedJSON() throws -> String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes, .prettyPrinted]
        return String(decoding: try encoder.encode(self), as: UTF8.self) + "\n"
    }
}

/// The primary code `--language` accepts for each language (region subtags are ignored).
public enum CLILanguageCodes {
    public static func code(for language: Qwen3SupportedLanguage) -> String {
        switch language {
        case .auto: return "auto"
        case .chinese: return "zh"
        case .english: return "en"
        case .japanese: return "ja"
        case .korean: return "ko"
        case .german: return "de"
        case .french: return "fr"
        case .russian: return "ru"
        case .portuguese: return "pt"
        case .spanish: return "es"
        case .italian: return "it"
        }
    }
}

/// Limits the CLI enforces before any model work.
public enum CLILimits {
    /// The apps refuse a long-form plan of more segments (`IOSLongFormCoordinator.maxSegments`).
    public static let longFormMaximumSegments = 100
}

/// `vocello capabilities`: everything an agent needs to drive the CLI, with no
/// engine boot. Installed models, saved voices and speakers are runtime facts
/// their own commands report.
public struct CLICapabilitiesDocument: Encodable, Sendable {
    struct ErrorCode: Encodable, Sendable {
        let code: String
        let category: String
        let exitCode: Int32
        let retryable: Bool
    }

    struct ExitCode: Encodable, Sendable {
        let exitCode: Int32
        let category: String
    }

    struct Generation: Encodable, Sendable {
        let modes: [String]
        let variants: [String]
        let variations: [String]
        let languages: [String]
        let deliveryCells: [String]
        let singleTakeCharacterLimit: Int
        let eastAsianCharacterWeight: Int
        let longFormMaximumSegments: Int
    }

    struct MCP: Encodable, Sendable {
        let available: Bool
    }

    /// Facts about this Mac and its shared store, read without an engine boot.
    public struct Runtime: Encodable, Sendable {
        let dataDirectory: String
        let memoryClass: String
        let defaultSpeaker: String
        let speakers: [String]
        let installedModels: [String]

        public init(dataDirectory: String, memoryClass: String, defaultSpeaker: String, speakers: [String], installedModels: [String]) {
            self.dataDirectory = dataDirectory
            self.memoryClass = memoryClass
            self.defaultSpeaker = defaultSpeaker
            self.speakers = speakers
            self.installedModels = installedModels
        }
    }

    let vocelloVersion: String
    let build: String
    let schemaVersion: Int
    let contractRevision: Int
    let outputFormats: [String]
    let model: CLICommandModelDocument
    let exitCodes: [ExitCode]
    let errorCodes: [ErrorCode]
    let eventTypes: [String]
    let generation: Generation
    let mcp: MCP
    /// Nil when the contract cannot be read (`vocello doctor` says why).
    let runtime: Runtime?

    public init(runtime: Runtime? = nil) {
        self.runtime = runtime
        vocelloVersion = vocelloCLIVersion
        build = vocelloCLIBuild
        schemaVersion = CLIContract.schemaVersion
        contractRevision = CLIContract.revision
        outputFormats = CLIOutputFormat.allCases.map(\.rawValue)
        model = CLICommandModelDocument()
        exitCodes = [ExitCode(exitCode: 0, category: "ok")]
            + CLIErrorCategory.allCases.map { ExitCode(exitCode: $0.exitCode, category: $0.rawValue) }
            + [ExitCode(exitCode: 143, category: CLIErrorCategory.cancelled.rawValue)]
        errorCodes = VocelloErrorCode.allCases.map {
            ErrorCode(code: $0.rawValue, category: $0.category.rawValue, exitCode: $0.exitCode, retryable: $0.retryable)
        }
        eventTypes = CLIEventType.allCases.map(\.rawValue)
        generation = Generation(
            modes: VocelloCommandTree.modes,
            variants: VocelloCommandTree.variants,
            variations: VocelloCommandTree.variations,
            languages: Qwen3SupportedLanguage.allCases.map(\.rawValue),
            deliveryCells: EmotionPreset.all.filter { $0.id != "neutral" }.flatMap { preset in
                EmotionIntensity.allCases.compactMap { intensity in
                    preset.instruction(for: intensity).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                        ? nil : "\(preset.id).\(intensity.rpcValue)"
                }
            },
            singleTakeCharacterLimit: SingleTakeScriptBudget.characterLimit,
            eastAsianCharacterWeight: SingleTakeScriptBudget.eastAsianCharacterWeight,
            longFormMaximumSegments: CLILimits.longFormMaximumSegments
        )
        mcp = MCP(available: false)
    }
}
