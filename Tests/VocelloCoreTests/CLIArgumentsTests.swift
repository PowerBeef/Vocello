import Foundation
import QwenVoiceCore
import XCTest

/// TEST-13: the CLI's argument parser, its command dispatch table and the
/// `generate` option helpers (compiled into this bundle by path), plus where the
/// CLI finds its trust anchors (SEC-09).
final class CLIArgumentsTests: XCTestCase {
    // MARK: - Args

    func testArgsParsesValuesFlagsAndPositionals() {
        let args = Args([
            "list", "--mode", "clone", "--seed=42", "--json", "--text", "hello world", "extra", "--quiet",
        ])
        XCTAssertEqual(args.positionals, ["list", "extra"])
        XCTAssertEqual(args.string("mode"), "clone")
        XCTAssertEqual(args.string("seed"), "42")
        XCTAssertEqual(args.string("text"), "hello world")
        XCTAssertTrue(args.flag("json"))
        XCTAssertTrue(args.flag("quiet"))
        XCTAssertNil(args.string("json"), "a bare flag carries no value")
        XCTAssertFalse(args.flag("mode"), "a flag with a value is not a bare flag")
        XCTAssertEqual(Args(["--seed", "1", "--seed", "2"]).string("seed"), "2", "the last value wins")
    }

    func testDoubleDashEndsFlagsAndTheEqualsFormCarriesDashedValues() throws {
        let args = Args(["--delivery=--calm", "--", "--not-a-flag", "-"])
        XCTAssertEqual(args.string("delivery"), "--calm")
        XCTAssertEqual(args.positionals, ["--not-a-flag", "-"])
        XCTAssertFalse(args.flag("not-a-flag"))

        // Without `=`, a value that starts with `--` reads as the next flag.
        let ambiguous = Args(["--delivery", "--calm"])
        XCTAssertNil(ambiguous.string("delivery"))
        XCTAssertTrue(ambiguous.flag("delivery"))
        XCTAssertTrue(ambiguous.flag("calm"))

        // An empty `--key=` value is recorded, but `require` refuses it.
        let empty = Args(["--voice="])
        XCTAssertEqual(empty.string("voice"), "")
        XCTAssertThrowsError(try empty.require("voice", "a saved voice")) { error in
            XCTAssertEqual((error as? CLIError)?.description, "missing required --voice (a saved voice)")
        }
        XCTAssertThrowsError(try Args([]).require("voice", "a saved voice"))
        XCTAssertEqual(try Args(["--voice", "Ava"]).require("voice", "a saved voice"), "Ava")
    }

    // MARK: - Dispatch

    func testCommandRoutingForwardsArgumentsAndModeShortcuts() {
        XCTAssertEqual(CLICommandRoute([]), .missingCommand)
        XCTAssertEqual(CLICommandRoute(["generate"]), .generate([]))
        XCTAssertEqual(CLICommandRoute(["gen", "--text", "hi"]), .generate(["--text", "hi"]))
        XCTAssertEqual(
            CLICommandRoute(["clone", "--voice", "Ava"]),
            .generate(["--mode", "clone", "--voice", "Ava"])
        )
        XCTAssertEqual(
            CLICommandRoute(["design", "--file", "lines.txt"]),
            .batch(["--mode", "design", "--file", "lines.txt"])
        )
        XCTAssertEqual(
            CLICommandRoute(["custom", "--file=lines.txt"]),
            .batch(["--mode", "custom", "--file=lines.txt"])
        )
        XCTAssertEqual(
            CLICommandRoute(["custom", "--text", "--file"]),
            .batch(["--mode", "custom", "--text", "--file"]),
            "the shortcut routes on the bare token, as the batch command reads it"
        )
        XCTAssertEqual(CLICommandRoute(["batch", "--file", "x"]), .batch(["--file", "x"]))
        XCTAssertEqual(CLICommandRoute(["modes", "--json"]), .modes(["--json"]))
        XCTAssertEqual(CLICommandRoute(["delivery"]), .deliveries([]))
        XCTAssertEqual(CLICommandRoute(["voice", "list"]), .voices(["list"]))
        XCTAssertEqual(CLICommandRoute(["speaker", "list"]), .speakers(["list"]))
        XCTAssertEqual(CLICommandRoute(["model"]), .models([]))
        XCTAssertEqual(CLICommandRoute(["benchmark", "--cells", "a"]), .bench(["--cells", "a"]))
        for help in ["help", "-h", "--help"] {
            XCTAssertEqual(CLICommandRoute([help, "extra"]), .help, help)
        }
        for version in ["version", "--version", "-v"] {
            XCTAssertEqual(CLICommandRoute([version]), .version, version)
        }
        XCTAssertEqual(CLICommandRoute(["synthesize"]), .unknown("synthesize"))
        XCTAssertEqual(CLICommandRoute(["Generate"]), .unknown("Generate"), "commands are case-sensitive")
    }

    // MARK: - generate options

    func testGenerateOptionParsingAcceptsDocumentedValuesAndRejectsTheRest() throws {
        XCTAssertNil(try GenerateCommand.parseSeed(Args([])))
        XCTAssertEqual(try GenerateCommand.parseSeed(Args(["--seed", "18446744073709551615"])), UInt64.max)
        XCTAssertThrowsError(try GenerateCommand.parseSeed(Args(["--seed=-1"])))
        XCTAssertThrowsError(try GenerateCommand.parseSeed(Args(["--seed", "1.5"])))

        XCTAssertNil(try GenerateCommand.parseVariation(Args([])))
        XCTAssertEqual(try GenerateCommand.parseVariation(Args(["--variation", "Balanced"])), .balanced)
        XCTAssertThrowsError(try GenerateCommand.parseVariation(Args(["--variation", "wild"])))

        XCTAssertEqual(try GenerateCommand.resolveMode(Args([])), .custom)
        XCTAssertEqual(try GenerateCommand.resolveMode(Args(["--mode", "CLONE"])), .clone)
        XCTAssertThrowsError(try GenerateCommand.resolveMode(Args(["--mode", "sing"]))) { error in
            XCTAssertEqual(
                (error as? CLIError)?.description,
                "invalid --mode 'sing' (use custom | design | clone)"
            )
        }

        XCTAssertFalse(try GenerateCommand.resolveQuality(Args([])))
        XCTAssertFalse(try GenerateCommand.resolveQuality(Args(["--variant", "fast"])))
        XCTAssertTrue(try GenerateCommand.resolveQuality(Args(["--variant", "HQ"])))
        XCTAssertThrowsError(try GenerateCommand.resolveQuality(Args(["--variant", "turbo"])))

        XCTAssertNil(try GenerateCommand.resolveDeliveryInstructionCellID(Args([]), mode: .design))
        XCTAssertEqual(
            try GenerateCommand.resolveDeliveryInstructionCellID(
                Args(["--delivery-cell", "angry.normal"]),
                mode: .custom
            ),
            "angry.normal"
        )
        XCTAssertThrowsError(try GenerateCommand.resolveDeliveryInstructionCellID(
            Args(["--delivery-cell", "angry.normal"]),
            mode: .design
        ))
        XCTAssertThrowsError(try GenerateCommand.resolveDeliveryInstructionCellID(
            Args(["--delivery-cell", "angry"]),
            mode: .custom
        ))
    }

    /// P15-07 / P02-09: an unknown `--language` is refused before boot instead of
    /// silently running as Auto; names, codes and region-tagged codes resolve to
    /// the canonical language the apps send.
    func testLanguageResolvesNamesAndCodesAndRefusesTheRest() throws {
        func parse(_ value: String) throws -> Qwen3SupportedLanguage? {
            try GenerateCommand.parseLanguage(Args(["--language", value]))
        }
        XCTAssertNil(try GenerateCommand.parseLanguage(Args([])), "omitted stays Auto with no hint")
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
        XCTAssertThrowsError(try GenerateCommand.parseLanguage(Args(["--language"])), "a bare flag has no language")
    }

    /// P15-08 / P05-05: an empty speaker (an unset shell variable) is refused,
    /// never sent as a take with no speaker conditioning; P02-09: Clone refuses
    /// a delivery it would drop unseen; P15-06: `--app-delivery` is a bare flag.
    func testPayloadOptionsRefuseAnEmptySpeakerAndACloneDelivery() throws {
        XCTAssertNil(try GenerateCommand.explicitSpeaker(Args([])), "omitted takes the contract default")
        XCTAssertEqual(try GenerateCommand.explicitSpeaker(Args(["--speaker", " ryan "])), "ryan")
        for argv in [["--speaker", ""], ["--speaker=   "], ["--speaker=", "--json"], ["--speaker", "--json"]] {
            XCTAssertThrowsError(try GenerateCommand.explicitSpeaker(Args(argv)), "\(argv)") { error in
                XCTAssertTrue((error as? CLIError)?.description.hasPrefix("empty --speaker") == true)
            }
            XCTAssertThrowsError(try GenerateCommand.validatePayloadOptions(Args(argv), mode: .custom))
            XCTAssertNoThrow(
                try GenerateCommand.validatePayloadOptions(Args(argv), mode: .design),
                "only Built-in Voice reads --speaker"
            )
        }

        XCTAssertNoThrow(try GenerateCommand.validatePayloadOptions(Args(["--delivery", "Calm."]), mode: .custom))
        XCTAssertNoThrow(try GenerateCommand.validatePayloadOptions(Args(["--delivery", "Calm."]), mode: .design))
        XCTAssertNoThrow(try GenerateCommand.validatePayloadOptions(Args(["--app-delivery"]), mode: .clone))
        XCTAssertThrowsError(try GenerateCommand.validatePayloadOptions(Args(["--delivery", "Calm."]), mode: .clone))

        XCTAssertFalse(try GenerateCommand.parseAppDelivery(Args([])))
        XCTAssertTrue(try GenerateCommand.parseAppDelivery(Args(["--app-delivery"])))
        XCTAssertThrowsError(try GenerateCommand.parseAppDelivery(Args(["--app-delivery=yes"])))
    }

    /// U28: two runs that resolve their default output in the same second and
    /// mode still get distinct files, named by their generation ids.
    func testDefaultOutputNamesAreUniquePerTake() throws {
        let dataDir = URL(fileURLWithPath: "/fixture/data", isDirectory: true)
        let now = Date(timeIntervalSince1970: 1_790_431_387)
        let first = UUID()
        let second = UUID()
        let a = try GenerateCommand.resolveOutputDestination(
            Args([]), dataDir: dataDir, mode: .custom, generationID: first, now: now)
        let b = try GenerateCommand.resolveOutputDestination(
            Args([]), dataDir: dataDir, mode: .custom, generationID: second, now: now)
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
                Args(["--out", out]), dataDir: root, mode: .design, generationID: UUID())
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
            Args(["--out"]), dataDir: root, mode: .custom, generationID: UUID()))

        // The folder is created when missing, and a file in its place is refused.
        let nested = root.appendingPathComponent("a/b/take.wav").path
        try GenerateCommand.prepareOutputFolder(of: nested)
        var isDirectory: ObjCBool = false
        XCTAssertTrue(FileManager.default.fileExists(atPath: root.appendingPathComponent("a/b").path, isDirectory: &isDirectory))
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
        let other = CLIError("fixture")
        XCTAssertEqual((CLIEngineCancellation.classify(other, commandCancelled: false) as? CLIError)?.description, "fixture")
        XCTAssertEqual(CLIEngineCancellation.exitStatus, 75)
        XCTAssertNotEqual(CLIEngineCancellation.exitStatus, 130)
        XCTAssertTrue(CLIEngineCancellation(reason: .memoryPressure).errorDescription?.contains("memory pressure") == true)
    }

    func testScriptTextComesFromTheFlagOrAFile() throws {
        XCTAssertEqual(try GenerateCommand.resolveText(Args(["--text", "Hello there."])), "Hello there.")
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("cli-text-\(UUID().uuidString).txt")
        try "From a file.".write(to: url, atomically: true, encoding: .utf8)
        defer { try? FileManager.default.removeItem(at: url) }
        XCTAssertEqual(try GenerateCommand.resolveText(Args(["--text-file", url.path])), "From a file.")
        XCTAssertThrowsError(
            try GenerateCommand.resolveText(Args(["--text-file", url.path + ".missing"]))
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
}
