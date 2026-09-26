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
