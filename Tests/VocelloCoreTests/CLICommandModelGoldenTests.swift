import Foundation
import XCTest
@testable import VocelloCLICore

/// RF-25: everything derived from the command model stays equal to it: the
/// checked-in `config/cli-contract/v1/commands.json` and zsh completion, help
/// and capabilities.
final class CLICommandModelGoldenTests: XCTestCase {
    private static let root = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()

    func testCheckedInCommandModelMatchesTheTree() throws {
        let checkedIn = try Data(contentsOf: Self.root.appendingPathComponent("config/cli-contract/v1/commands.json"))
        let rendered = try CLIJSONEncoding.encoder().encode(CLICommandModelDocument())
        let expected = try XCTUnwrap(JSONSerialization.jsonObject(with: rendered) as? NSDictionary)
        let actual = try XCTUnwrap(JSONSerialization.jsonObject(with: checkedIn) as? NSDictionary)
        XCTAssertEqual(
            actual, expected,
            "regenerate config/cli-contract/v1/commands.json from `vocello capabilities --json` (.result.model)"
        )
    }

    func testCheckedInZshCompletionIsTheGeneratorsOutput() throws {
        let checkedIn = try String(
            contentsOf: Self.root.appendingPathComponent("scripts/completions/_vocello"), encoding: .utf8
        )
        XCTAssertEqual(
            checkedIn, CLICompletionGenerator.script(for: .zsh),
            "regenerate with `vocello completions zsh > scripts/completions/_vocello`"
        )
    }

    func testTheTreeIsWellFormed() {
        let globals = Set(CLIGlobalOptionSpecs.all.map(\.name))
        var topNames = Set<String>()
        for spec in VocelloCommandTree.commands {
            for name in [spec.name] + spec.aliases {
                XCTAssertTrue(topNames.insert(name).inserted, "duplicate command \(name)")
            }
            XCTAssertFalse(CLIParser.modeShortcuts.contains(spec.name))
            if let defaultName = spec.defaultSubcommand {
                XCTAssertNotNil(spec.subcommand(named: defaultName), "\(spec.name) default")
            }
            for command in [spec] + spec.subcommands {
                let names = command.options.map(\.name)
                XCTAssertEqual(names.count, Set(names).count, "\(command.name) repeats an option")
                XCTAssertTrue(globals.isDisjoint(with: names), "\(command.name) shadows a global option")
                XCTAssertTrue(Set(command.refusedOptions.keys).isDisjoint(with: names), command.name)
                let requiredAfterOptional = command.positionals.drop { $0.required }.contains { $0.required }
                XCTAssertFalse(requiredAfterOptional, "\(command.name): a required operand follows an optional one")
            }
        }
    }

    func testHelpNamesEveryVisibleOptionAndSubcommand() {
        let top = CLIHelpRenderer.render(path: [])
        for spec in VocelloCommandTree.commands {
            XCTAssertTrue(top.contains("  \(spec.name) "), "top-level help lacks \(spec.name)")
            let paths = spec.subcommands.isEmpty ? [[spec.name]] : spec.subcommands.map { [spec.name, $0.name] }
            for path in paths {
                let help = CLIHelpRenderer.render(path: path)
                let command = VocelloCommandTree.spec(at: path)!
                XCTAssertTrue(help.hasPrefix("vocello \(path.joined(separator: " ")) — "), help)
                for option in command.options {
                    XCTAssertEqual(help.contains("--\(option.name) ") || help.contains("--\(option.name)\n"),
                                   !option.hidden, "\(path) --\(option.name)")
                }
            }
        }
        XCTAssertTrue(CLIHelpRenderer.render(path: ["models"]).contains("install"))
    }

    func testCapabilitiesDescribeTheWholeContractWithoutTheEngine() throws {
        let data = try CLIJSONEncoding.encoder().encode(CLICapabilitiesDocument())
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(object["contractRevision"] as? Int, CLIContract.revision)
        XCTAssertEqual(
            Set((object["errorCodes"] as? [[String: Any]] ?? []).compactMap { $0["code"] as? String }),
            Set(VocelloErrorCode.allCases.map(\.rawValue))
        )
        let generation = try XCTUnwrap(object["generation"] as? [String: Any])
        XCTAssertEqual(generation["modes"] as? [String], ["custom", "design", "clone"])
        XCTAssertTrue((generation["languages"] as? [String] ?? []).contains("english"))
        XCTAssertFalse((generation["deliveryCells"] as? [String] ?? []).isEmpty)
        let commands = (object["model"] as? [String: Any])?["commands"] as? [[String: Any]] ?? []
        XCTAssertTrue(commands.contains { $0["path"] as? String == "models.install" })
        XCTAssertFalse(
            commands.flatMap { $0["options"] as? [[String: Any]] ?? [] }.contains { $0["name"] as? String == "capture-codec-trace" },
            "hidden diagnostics options stay out"
        )
    }

    func testEveryShellScriptOffersEveryCommandAsACandidate() {
        let names = VocelloCommandTree.commands.flatMap { [$0.name] + $0.aliases } + CLIParser.modeShortcuts
        let zsh = CLICompletionGenerator.script(for: .zsh)
        let bash = CLICompletionGenerator.script(for: .bash)
        let fish = CLICompletionGenerator.script(for: .fish)
        let bashTopLevel = bash.components(separatedBy: "\n").first { $0.contains("compgen -W") } ?? ""
        for name in names {
            XCTAssertTrue(zsh.contains("'\(name):"), "zsh lacks \(name)")
            XCTAssertTrue(bashTopLevel.contains(" \(name) ") || bashTopLevel.contains("\"\(name) ")
                          || bashTopLevel.contains(" \(name)\""), "bash lacks \(name)")
            XCTAssertTrue(fish.contains("__fish_use_subcommand' -a \(name) "), "fish lacks \(name)")
        }
        for script in [zsh, bash, fish] {
            XCTAssertFalse(script.contains("capture-codec-trace"), "a hidden option is offered")
        }
    }
}
