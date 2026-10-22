import Foundation
import QwenVoiceCore
import XCTest
@testable import VocelloCLICore
import VocelloDesktopCore

/// TEST-13: the CLI's argument parser, its command dispatch table and the
/// `generate` option helpers (compiled into this bundle by path), plus where the
/// CLI finds its trust anchors (SEC-09).
final class CLIArgumentsTests: XCTestCase {
    func testCloneReferenceExplainsAudioOnlyAndPreservesSavedTranscriptOverride() {
        let raw = GenerateCommand.rawCloneReference(audioPath: "reference.wav", transcript: nil)
        XCTAssertTrue(raw.conditioningMode.isXVectorOnly)
        XCTAssertNotNil(GenerateCommand.rawReferenceConditioningNote(for: raw))
        let explicit = GenerateCommand.rawCloneReference(audioPath: "reference.wav", transcript: "Words")
        XCTAssertNil(GenerateCommand.rawReferenceConditioningNote(for: explicit))
        let voice = PreparedVoice(id: "Voice", name: "Voice", audioPath: "voices/Voice.wav", hasTranscript: true)
        let saved = GenerateCommand.savedVoiceCloneReference(voice, transcriptOverride: "Corrected words")
        XCTAssertEqual(saved.transcript, "Corrected words")
        XCTAssertEqual(saved.preparedVoiceID, voice.id)
        XCTAssertNil(GenerateCommand.rawReferenceConditioningNote(for: saved))
        XCTAssertNil(GenerateCommand.savedVoiceCloneReference(voice, transcriptOverride: nil).transcript)
    }

    // MARK: - Parser

    private func parse(_ argv: [String]) throws -> CLIInvocation { try CLIParser.parse(argv) }
    private func generate(_ argv: [String]) throws -> Args { try CLIParser.args(argv, for: "generate") }

    private func usageMessage(_ argv: [String], file: StaticString = #filePath, line: UInt = #line) -> String {
        do {
            _ = try CLIParser.parse(argv)
            XCTFail("\(argv) must be refused", file: file, line: line)
            return ""
        } catch let error as CLIError {
            XCTAssertEqual(error.code, .usageError, file: file, line: line)
            return error.description + " | " + (error.hint ?? "")
        } catch {
            XCTFail("unexpected \(error)", file: file, line: line)
            return ""
        }
    }

    func testParserReadsDeclaredValuesFlagsAndOperands() throws {
        let args = try generate(["--mode", "clone", "--seed=42", "--text", "hello world", "--quiet", "--play"])
        XCTAssertEqual(args.string("mode"), "clone")
        XCTAssertEqual(args.string("seed"), "42")
        XCTAssertEqual(args.string("text"), "hello world")
        XCTAssertTrue(args.flag("quiet"))
        XCTAssertTrue(args.flag("play"))
        XCTAssertNil(args.string("play"), "a bare flag carries no value")
        XCTAssertFalse(args.flag("mode"), "a flag with a value is not a bare flag")
        XCTAssertEqual(try generate(["--seed", "1", "--seed", "2"]).string("seed"), "2", "the last value wins")
        XCTAssertEqual(try generate(["--delivery=--calm"]).string("delivery"), "--calm", "= carries a dashed value")
        XCTAssertEqual(try generate(["--text", "-"]).string("text"), "-", "a lone dash is a value")
        XCTAssertEqual(try parse(["models", "status", "pro_custom_speed"]).args.positionals, ["pro_custom_speed"])
        XCTAssertEqual(try parse(["models", "list", "--", "--odd-id"]).args.positionals, ["--odd-id"])

        // An empty `--key=` value is recorded, but `require` refuses it.
        let empty = try generate(["--voice="])
        XCTAssertEqual(empty.string("voice"), "")
        XCTAssertThrowsError(try empty.require("voice", "a saved voice")) { error in
            XCTAssertEqual((error as? CLIError)?.description, "missing required --voice (a saved voice)")
        }
        XCTAssertEqual(try generate(["--voice", "Ava"]).require("voice", "a saved voice"), "Ava")
    }

    func testParserRefusesWhatTheCommandDoesNotDeclare() {
        XCTAssertTrue(usageMessage(["generate", "--vioce", "Ava"]).contains("did you mean --voice?"))
        XCTAssertTrue(usageMessage(["generat"]).contains("did you mean 'generate'?"))
        XCTAssertTrue(usageMessage(["models", "instal", "x"]).contains("did you mean 'install'?"))
        XCTAssertTrue(usageMessage(["generate", "--delivery", "--calm"]).hasPrefix("--delivery needs a value"))
        XCTAssertTrue(usageMessage(["generate", "--speaker"]).hasPrefix("--speaker needs a value"))
        XCTAssertTrue(usageMessage(["generate", "--play=yes"]).contains("--play takes no value"))
        XCTAssertTrue(usageMessage(["speakers", "list", "extra"]).hasPrefix("unexpected argument 'extra'"))
        XCTAssertTrue(usageMessage(["models", "install"]).hasPrefix("missing <id>"))
        XCTAssertTrue(usageMessage(["batch", "--language", "en"]).hasPrefix("--language is not supported by batch"))
        XCTAssertTrue(usageMessage(["--json", "--ndjson", "version"]).contains("conflicts"))
        XCTAssertTrue(usageMessage(["--output-format", "yaml", "version"]).hasPrefix("invalid --output-format"))
        XCTAssertTrue(usageMessage(["bench", "--json"]).contains("writes its own output"))
        XCTAssertTrue(usageMessage([]).hasPrefix("missing command"))
        XCTAssertTrue(usageMessage(["Generate"]).hasPrefix("unknown command"), "commands are case-sensitive")
        XCTAssertTrue(usageMessage(["-x"]).hasPrefix("unknown option -x"))
    }

    func testCommandPathsAliasesShortcutsAndDefaults() throws {
        XCTAssertEqual(try parse(["gen", "--text", "hi"]).path, ["generate"])
        let clone = try parse(["clone", "--voice", "Ava"])
        XCTAssertEqual(clone.path, ["generate"])
        XCTAssertEqual(clone.args.string("mode"), "clone")
        XCTAssertEqual(try parse(["design", "--file", "lines.txt"]).path, ["batch"])
        XCTAssertEqual(try parse(["custom", "--file=lines.txt"]).args.string("mode"), "custom")
        XCTAssertEqual(CLIParser.expandingShortcut(["custom", "--", "--file"]).first, "generate",
                       "an operand after -- never routes to batch")
        XCTAssertEqual(try parse(["voice", "ls"]).path, ["voices", "list"])
        XCTAssertEqual(try parse(["voices"]).path, ["voices", "list"], "the default subcommand")
        XCTAssertEqual(try parse(["delivery", "--shipped-only"]).path, ["deliveries", "list"])
        XCTAssertEqual(try parse(["model"]).path, ["models", "list"])
        XCTAssertEqual(try parse(["benchmark", "--modes", "custom"]).path, ["bench"])
        for version in [["version"], ["--version"], ["-v"]] {
            XCTAssertEqual(try parse(version).path, ["version"], "\(version)")
        }
        XCTAssertEqual(try parse(["models", "install", "pro_custom_speed"]).commandName, "models.install")
    }

    func testOptionalValuesSubcommandsAfterOptionsAndHelpPastAMistake() throws {
        let bare = try parse(["bench", "--delivery", "--modes", "custom"])
        XCTAssertTrue(bare.args.flag("delivery"), "a value-optional option alone is a flag")
        XCTAssertEqual(bare.args.string("modes"), "custom")
        XCTAssertEqual(try parse(["bench", "--delivery", "happy.strong"]).args.string("delivery"), "happy.strong")
        XCTAssertEqual(try parse(["bench", "--delivery=calm"]).args.string("delivery"), "calm")
        XCTAssertEqual(try parse(["bench", "--delivery", "-h"]).action, .help, "-h is never an optional value")

        let enroll = try parse(["voices", "--confirm-consent", "enroll", "--name", "Ava", "--audio", "a.wav"])
        XCTAssertEqual(enroll.path, ["voices", "enroll"], "an option before the subcommand belongs to it")
        XCTAssertTrue(enroll.args.flag("confirm-consent"))
        XCTAssertEqual(enroll.args.string("name"), "Ava")

        let help = try parse(["generate", "--vioce", "x", "-h"])
        XCTAssertEqual(help.action, .help, "help wins over a mistake on the same line")
        XCTAssertEqual(help.path, ["generate"])
        XCTAssertTrue(usageMessage(["help", "models", "nope"]).contains("unknown command 'nope'"))
    }

    func testHelpAnywhereAndGlobalOptionsAnywhereBeforeTheEnd() throws {
        for argv in [["--help"], ["-h"], ["help"]] {
            let invocation = try parse(argv)
            XCTAssertEqual(invocation.action, .help, "\(argv)")
            XCTAssertEqual(invocation.path, [], "\(argv)")
        }
        XCTAssertEqual(try parse(["generate", "--text", "hi", "-h"]).path, ["generate"])
        XCTAssertEqual(try parse(["generate", "--text", "hi", "-h"]).action, .help)
        XCTAssertEqual(try parse(["help", "models", "install"]).path, ["models", "install"])
        XCTAssertEqual(try parse(["models", "help"]).path, ["models"])
        XCTAssertEqual(try parse(["models", "help"]).action, .help)

        let machine = try parse(["--json", "models", "--verbose", "status", "--data-dir", "/tmp/x"])
        XCTAssertEqual(machine.path, ["models", "status"])
        XCTAssertEqual(machine.format, .json)
        XCTAssertEqual(machine.verbosity, .verbose)
        XCTAssertEqual(machine.args.string("data-dir"), "/tmp/x")
        XCTAssertEqual(try parse(["version", "--output-format=ndjson"]).format, .ndjson)
        XCTAssertEqual(try parse(["version", "--json", "--output-format", "json"]).format, .json)
        XCTAssertTrue(try parse(["generate", "--no-input"]).noInput)
        XCTAssertEqual(CLIParser.requestedFormat(["generat", "--json"]), .json, "a refused line keeps its format")
        XCTAssertEqual(CLIParser.requestedFormat(["--", "--json"]), .text)
    }

    // MARK: - generate options

    func testGenerateOptionParsingAcceptsDocumentedValuesAndRejectsTheRest() throws {
        XCTAssertNil(try GenerateCommand.parseSeed(generate([])))
        XCTAssertEqual(try GenerateCommand.parseSeed(generate(["--seed", "18446744073709551615"])), UInt64.max)
        XCTAssertThrowsError(try GenerateCommand.parseSeed(generate(["--seed=-1"])))
        XCTAssertThrowsError(try GenerateCommand.parseSeed(generate(["--seed", "1.5"])))

        XCTAssertNil(try GenerateCommand.parseVariation(generate([])))
        XCTAssertEqual(try GenerateCommand.parseVariation(generate(["--variation", "Balanced"])), .balanced)
        XCTAssertThrowsError(try GenerateCommand.parseVariation(generate(["--variation", "wild"])))

        XCTAssertEqual(try GenerateCommand.resolveMode(generate([])), .custom)
        XCTAssertEqual(try GenerateCommand.resolveMode(generate(["--mode", "CLONE"])), .clone)
        XCTAssertThrowsError(try GenerateCommand.resolveMode(generate(["--mode", "sing"]))) { error in
            XCTAssertEqual(
                (error as? CLIError)?.description,
                "invalid --mode 'sing' (use custom | design | clone)"
            )
        }

        XCTAssertNil(try GenerateCommand.parseVariantFlag(generate([])), "absent: the app's choice applies")
        XCTAssertEqual(try GenerateCommand.parseVariantFlag(generate(["--variant", "fast"])), false)
        XCTAssertEqual(try GenerateCommand.parseVariantFlag(generate(["--variant", "HQ"])), true)
        XCTAssertThrowsError(try GenerateCommand.parseVariantFlag(generate(["--variant", "turbo"])))

        XCTAssertNil(try GenerateCommand.resolveDeliveryInstructionCellID(generate([]), mode: .design))
        XCTAssertEqual(
            try GenerateCommand.resolveDeliveryInstructionCellID(
                generate(["--delivery-cell", "angry.normal"]),
                mode: .custom
            ),
            "angry.normal"
        )
        XCTAssertThrowsError(try GenerateCommand.resolveDeliveryInstructionCellID(
            generate(["--delivery-cell", "angry.normal"]),
            mode: .design
        ))
        XCTAssertThrowsError(try GenerateCommand.resolveDeliveryInstructionCellID(
            generate(["--delivery-cell", "angry"]),
            mode: .custom
        ))
    }

    /// RF-27: without --variant a take uses the package the Mac app would use for the
    /// mode; without --variation, the app's variation (nil for expressive, as the app sends it).
    func testTakesDefaultToTheAppsPackageAndVariation() throws {
        let manifest = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        let registry = try ContractBackedModelRegistry(manifestURL: manifest)
            .expandedForPlatform(.macOS, deviceClass: .mid16GBMac, includeBaseAliases: true)
        let models = FileManager.default.temporaryDirectory.appendingPathComponent("cli-variant-\(UUID().uuidString)")
        addTeardownBlock { try? FileManager.default.removeItem(at: models) }
        func install(_ id: String) throws {
            let descriptor = try XCTUnwrap(registry.model(id: id))
            for path in descriptor.requiredRelativePaths {
                let url = descriptor.installDirectory(in: models).appendingPathComponent(path)
                try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
                try Data().write(to: url)
            }
        }
        func settings(_ values: [String: any Sendable]) -> DesktopAppSettings {
            DesktopAppSettings(domain: DesktopAppSettings.releaseDomain) { values[$0] }
        }
        func resolve(_ explicit: Bool?, _ stored: [String: any Sendable] = [:]) -> GenerateCommand.VariantChoice {
            GenerateCommand.resolveVariant(
                explicitQuality: explicit, mode: .custom, registry: registry, modelsDirectory: models,
                settings: settings(stored), deviceClass: .mid16GBMac
            )
        }
        try install("pro_custom_speed")
        XCTAssertEqual(resolve(true), GenerateCommand.VariantChoice(quality: true, source: "flag"), "the flag wins")
        XCTAssertEqual(resolve(nil), GenerateCommand.VariantChoice(quality: false, source: "app"),
                       "Quality is recommended but not installed: the installed Speed package")
        try install("pro_custom_quality")
        XCTAssertEqual(resolve(nil).quality, true, "the 16 GB recommendation once installed")
        XCTAssertEqual(resolve(nil, ["QwenVoice.PreferSpeedEverywhere": true]).quality, false)
        XCTAssertEqual(resolve(nil, ["QwenVoice.MacModelVariantPreference.custom": "speed"]).quality, false)

        XCTAssertNil(GenerateCommand.appVariation(settings([:])), "expressive is sent as no variation")
        XCTAssertEqual(GenerateCommand.appVariation(settings(["generationVariation": "balanced"])), .balanced)
    }

    /// P15-07 / P02-09: an unknown `--language` is refused before boot instead of
    /// silently running as Auto; names, codes and region-tagged codes resolve to
    /// the canonical language the apps send.
    func testLanguageResolvesNamesAndCodesAndRefusesTheRest() throws {
        func parse(_ value: String) throws -> Qwen3SupportedLanguage? {
            try GenerateCommand.parseLanguage(generate(["--language", value]))
        }
        XCTAssertNil(try GenerateCommand.parseLanguage(generate([])), "omitted stays Auto with no hint")
        XCTAssertEqual(try parse("auto"), .auto)
        XCTAssertEqual(try parse("Automatic"), .auto)
        XCTAssertEqual(try parse("French"), .french)
        XCTAssertEqual(try parse("fr"), .french)
        XCTAssertEqual(try parse(" pt-BR "), .portuguese)
        XCTAssertEqual(try parse("ja-JP"), .japanese, "a region subtag never changes the language")
        XCTAssertEqual(try parse("ko_KR"), .korean)
        XCTAssertEqual(try parse("zh-Hant"), .chinese)
        XCTAssertEqual(try parse("es-MX"), .spanish)
        XCTAssertEqual(try parse("en-AU"), .english)
        for invalid in ["englsh", "portugese", "cantonese", "français", "klingon", "auto-detect", ""] {
            XCTAssertThrowsError(try parse(invalid), invalid) { error in
                let message = (error as? CLIError)?.description ?? ""
                XCTAssertTrue(message.hasPrefix("invalid --language '\(invalid)'"), message)
                XCTAssertTrue(message.contains("auto | chinese | english"), "the refusal lists the accepted values")
            }
        }
        XCTAssertThrowsError(try GenerateCommand.parseLanguage(generate(["--language"])), "a bare flag has no language")
        // `vocello languages` lists one code per language; each must parse back to it.
        for language in Qwen3SupportedLanguage.allCases {
            XCTAssertEqual(try parse(CLILanguageCodes.code(for: language)), language, language.rawValue)
        }
    }

    /// P15-08 / P05-05: an empty speaker (an unset shell variable) is refused,
    /// never sent as a take with no speaker conditioning; P02-09: Clone refuses
    /// a delivery it would drop unseen; P15-06: `--app-delivery` is a bare flag.
    func testPayloadOptionsRefuseAnEmptySpeakerAndACloneDelivery() throws {
        XCTAssertNil(try GenerateCommand.explicitSpeaker(generate([])), "omitted takes the contract default")
        XCTAssertEqual(try GenerateCommand.explicitSpeaker(generate(["--speaker", " ryan "])), "ryan")
        XCTAssertThrowsError(try generate(["--speaker", "--json"]), "a missing value is a usage error")
        for argv in [["--speaker", ""], ["--speaker=   "], ["--speaker=", "--json"]] {
            XCTAssertThrowsError(try GenerateCommand.explicitSpeaker(generate(argv)), "\(argv)") { error in
                XCTAssertTrue((error as? CLIError)?.description.hasPrefix("empty --speaker") == true)
            }
            XCTAssertThrowsError(try GenerateCommand.validatePayloadOptions(generate(argv), mode: .custom))
            XCTAssertNoThrow(
                try GenerateCommand.validatePayloadOptions(generate(argv), mode: .design),
                "only Built-in Voice reads --speaker"
            )
        }

        XCTAssertNoThrow(try GenerateCommand.validatePayloadOptions(generate(["--delivery", "Calm."]), mode: .custom))
        XCTAssertNoThrow(try GenerateCommand.validatePayloadOptions(generate(["--delivery", "Calm."]), mode: .design))
        XCTAssertNoThrow(try GenerateCommand.validatePayloadOptions(generate(["--app-delivery"]), mode: .clone))
        XCTAssertThrowsError(try GenerateCommand.validatePayloadOptions(generate(["--delivery", "Calm."]), mode: .clone))

        XCTAssertFalse(try GenerateCommand.parseAppDelivery(generate([])))
        XCTAssertTrue(try GenerateCommand.parseAppDelivery(generate(["--app-delivery"])))
        XCTAssertThrowsError(try GenerateCommand.parseAppDelivery(generate(["--app-delivery=yes"])))
    }

    /// U28: two runs that resolve their default output in the same second and
    /// mode still get distinct files, named by their generation ids.
    func testDefaultOutputNamesAreUniquePerTake() throws {
        let dataDir = URL(fileURLWithPath: "/fixture/data", isDirectory: true)
        let now = Date(timeIntervalSince1970: 1_790_431_387)
        let first = UUID()
        let second = UUID()
        let a = try GenerateCommand.resolveOutputDestination(
            generate([]), dataDir: dataDir, mode: .custom, generationID: first, now: now)
        let b = try GenerateCommand.resolveOutputDestination(
            generate([]), dataDir: dataDir, mode: .custom, generationID: second, now: now)
        XCTAssertNotEqual(a.path, b.path)
        XCTAssertEqual(
            a.path,
            "/fixture/data/outputs/cli/\(GenerateCommand.defaultOutputStamp(now))_custom_\(first.uuidString.lowercased()).wav"
        )
        XCTAssertFalse(a.replacesExistingFile)
        XCTAssertTrue(GenerateCommand.defaultOutputStamp(now).allSatisfy { $0.isASCII })
        XCTAssertEqual(GenerateCommand.defaultOutputStamp(now).count, "yyyyMMdd_HHmmss".count)
    }

    /// P15-09 / P09-02: an explicit `--out` must name a `.wav` file, checked
    /// before any model work; an existing file is reported as replaced.
    func testExplicitOutputIsValidatedBeforeBoot() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("cli-out-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let existing = root.appendingPathComponent("existing.wav")
        try Data([0]).write(to: existing)
        let folderNamedLikeAWAV = root.appendingPathComponent("folder.wav", isDirectory: true)
        try FileManager.default.createDirectory(at: folderNamedLikeAWAV, withIntermediateDirectories: true)

        func resolve(_ out: String) throws -> GenerateCommand.OutputDestination {
            try GenerateCommand.resolveOutputDestination(
                generate(["--out", out]), dataDir: root, mode: .design, generationID: UUID())
        }
        let fresh = try resolve(root.appendingPathComponent("take.wav").path)
        XCTAssertEqual(fresh.path, root.appendingPathComponent("take.wav").path)
        XCTAssertFalse(fresh.replacesExistingFile)
        XCTAssertTrue(try resolve(root.appendingPathComponent("TAKE.WAV").path).path.hasSuffix("TAKE.WAV"))
        XCTAssertTrue(try resolve(existing.path).replacesExistingFile, "an existing file is replaced, and says so")
        let home = try resolve("~/take.wav").path
        XCTAssertFalse(home.hasPrefix("~"), "the tilde is expanded")
        XCTAssertTrue(home.hasSuffix("/take.wav"))

        for refused in [
            root.path,                                            // an existing folder
            root.path + "/",                                      // a trailing slash
            folderNamedLikeAWAV.path,                             // a folder with a .wav name
            root.appendingPathComponent("take").path,             // no extension: CAF bytes
            root.appendingPathComponent("take.aiff").path,        // another container
            "",
        ] {
            XCTAssertThrowsError(try resolve(refused), refused) { error in
                XCTAssertTrue(error is CLIError)
            }
        }
        XCTAssertThrowsError(try GenerateCommand.resolveOutputDestination(
            generate(["--out"]), dataDir: root, mode: .custom, generationID: UUID()))

        // The folder is created when missing, and a file in its place is refused.
        let nested = root.appendingPathComponent("a/b/take.wav").path
        try GenerateCommand.prepareOutputFolder(of: nested)
        var isDirectory: ObjCBool = false
        unsafe XCTAssertTrue(FileManager.default.fileExists(atPath: root.appendingPathComponent("a/b").path, isDirectory: &isDirectory))
        XCTAssertTrue(isDirectory.boolValue)
        XCTAssertThrowsError(try GenerateCommand.prepareOutputFolder(of: existing.appendingPathComponent("take.wav").path))
    }

    // MARK: - Engine-initiated cancellation (P15-02)

    func testAnEngineCancellationIsReportedApartFromASignal() {
        let engine = CLIEngineCancellation.classify(CancellationError(), commandCancelled: false)
        XCTAssertEqual(engine as? CLIEngineCancellation, CLIEngineCancellation(reason: .memoryPressure))
        XCTAssertEqual((engine as? CLIEngineCancellation)?.errorCode, "memory_pressure")
        XCTAssertTrue(CLIEngineCancellation.classify(CancellationError(), commandCancelled: true) is CancellationError,
                      "a signalled run stays the operator's interrupt")
        XCTAssertEqual(
            CLIEngineCancellation.classify(CancellationError(), commandCancelled: false, observedReason: .shutdown)
                as? CLIEngineCancellation,
            CLIEngineCancellation(reason: .shutdown),
            "the take's own `.cancelled` event names the reason"
        )
        XCTAssertEqual(
            CLIEngineCancellation.classify(
                CLIEngineCancellation(reason: .memoryPressure), commandCancelled: false, observedReason: .user
            ) as? CLIEngineCancellation,
            CLIEngineCancellation(reason: .memoryPressure),
            "the engine's `user` default never relabels an engine stop"
        )
        let other = CLIError(.internalError, "fixture")
        XCTAssertEqual((CLIEngineCancellation.classify(other, commandCancelled: false) as? CLIError)?.description, "fixture")
        XCTAssertEqual(CLIEngineCancellation.exitStatus, 75)
        XCTAssertNotEqual(CLIEngineCancellation.exitStatus, 130)
        XCTAssertTrue(CLIEngineCancellation(reason: .memoryPressure).errorDescription?.contains("memory pressure") == true)
    }

    func testScriptTextComesFromTheFlagOrAFile() throws {
        XCTAssertEqual(try GenerateCommand.resolveText(generate(["--text", "Hello there."])), "Hello there.")
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("cli-text-\(UUID().uuidString).txt")
        try "From a file.".write(to: url, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: url) }
        XCTAssertEqual(try GenerateCommand.resolveText(generate(["--text-file", url.path])), "From a file.")
        XCTAssertThrowsError(
            try GenerateCommand.resolveText(generate(["--text-file", url.path + ".missing"]))
        ) { error in
            XCTAssertTrue((error as? CLIError)?.description.hasPrefix("could not read --text-file") == true)
        }
    }

    /// U29 and P15-03: `generate` refuses, before the engine boots, a script with
    /// nothing to speak and one past the apps' single-take limit, pointing the
    /// latter at `batch --long-form`.
    func testGenerateRefusesUnspeakableAndOverLongScriptsBeforeTheEngine() throws {
        func refusal(_ text: String) -> String? {
            do {
                try GenerateCommand.validateSingleTakeText(text)
                return nil
            } catch {
                return (error as? CLIError)?.description ?? "unexpected \(error)"
            }
        }
        XCTAssertEqual(refusal(" \n")?.hasPrefix("empty text"), true)
        for text in ["...", "!?", "— · —", "🙂"] {
            XCTAssertEqual(refusal(text)?.hasPrefix("nothing to speak"), true, text)
        }
        for text in [String(repeating: "a", count: 901), String(repeating: "火", count: 301), String(repeating: "word ", count: 600)] {
            let message = try XCTUnwrap(refusal(text), "\(text.count) characters")
            XCTAssertTrue(message.hasPrefix("text is too long for one take"), message)
            XCTAssertTrue(message.contains("vocello batch --long-form"), message)
        }
        for text in ["Hi", "Hello there.", String(repeating: "a", count: 900), String(repeating: "火", count: 300)] {
            XCTAssertNil(refusal(text), "\(text.prefix(12)) (\(text.count))")
        }
    }

    /// A short-form `batch` line is one take: every line is checked by the
    /// same rule before the engine boots, and the refusal names the line.
    func testBatchRefusesAShortFormLineThatCannotBeOneTake() throws {
        XCTAssertNoThrow(try CLIBatchExecution.validateShortFormLines(["First line.", "Second line."]))
        for (lines, prefix) in [(["Fine.", "***"], "line 2: nothing to speak"),
                                (["Fine.", "Also fine.", String(repeating: "火", count: 301)], "line 3: text is too long")] {
            do {
                try CLIBatchExecution.validateShortFormLines(lines)
                XCTFail("\(lines.count) lines must be refused")
            } catch let error as CLIError {
                XCTAssertTrue(error.description.hasPrefix(prefix), error.description)
            }
        }
    }

    // MARK: - Trust anchors (SEC-09)

    func testTrustAnchorsNeverComeFromTheWorkingDirectoryOfASealedPayload() {
        let name = "qwenvoice_production_model_catalog.json"
        let executableDirectory = URL(fileURLWithPath: "/tmp/vocello-cli-fixture/bin", isDirectory: true)
        let besideExecutable = executableDirectory.path + "/" + name
        let repository = "/tmp/vocello-cli-fixture/repo"
        let repositoryCopy = repository + "/Sources/Resources/" + name
        let bundled = URL(fileURLWithPath: "/tmp/vocello-cli-fixture/bundle/" + name)
        let sealedManifest = executableDirectory.path + "/" + CLIRuntime.sealedPayloadManifestName

        func resolve(_ bundledURL: URL?, _ existing: Set<String>) -> String? {
            CLIRuntime.resolveTrustAnchor(
                fileName: name,
                bundledURL: bundledURL,
                executableDirectory: executableDirectory,
                currentDirectory: repository + "/Sources/Views",
                fileExists: { existing.contains($0) }
            )?.path
        }

        XCTAssertEqual(resolve(bundled, [besideExecutable, repositoryCopy]), bundled.path, "the bundled resource wins")
        XCTAssertEqual(resolve(nil, [besideExecutable, repositoryCopy]), besideExecutable)
        XCTAssertEqual(
            resolve(nil, [repositoryCopy]),
            repositoryCopy,
            "a development build finds the repository copy from any repository folder"
        )
        XCTAssertNil(
            resolve(nil, [sealedManifest, repositoryCopy]),
            "a sealed payload never reads an anchor planted where it runs"
        )
        XCTAssertEqual(resolve(nil, [sealedManifest, besideExecutable]), besideExecutable)
        XCTAssertNil(resolve(nil, []))
    }

    // MARK: - Started through a link (RF-08)

    func testALinkedStartExecsTheRealBinary() {
        let links = [
            "/usr/local/bin/vocello": "/usr/local/lib/vocello/vocello",
            "/repo/build/vocello": "/repo/build/cache/Release/vocello",
        ]
        func real(_ loaded: String, executable: Bool = true) -> String? {
            CLIExecutableLocation.realPath(
                ofLoaded: loaded, resolve: { links[$0] ?? $0 }, isExecutable: { _ in executable }
            )
        }
        XCTAssertEqual(real("/usr/local/bin/vocello"), "/usr/local/lib/vocello/vocello")
        XCTAssertEqual(real("/repo/build/vocello"), "/repo/build/cache/Release/vocello")
        XCTAssertNil(real("/usr/local/lib/vocello/vocello"), "the real binary runs as it is")
        XCTAssertNil(real("/usr/local/bin/vocello", executable: false), "a link to nothing runnable keeps the process")
        XCTAssertNil(
            CLIExecutableLocation.realPath(
                ofLoaded: "/private/tmp/payload/vocello", resolve: { _ in "/tmp/payload/vocello" }, isExecutable: { _ in true }
            ),
            "the /private firmlinks never cause an exec"
        )
    }
}
