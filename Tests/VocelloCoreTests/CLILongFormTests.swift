import Foundation
import QwenVoiceCore
import XCTest
@testable import VocelloCLICore

/// RF-27: `generate` routes a script past one take to a long-form project, as the
/// apps' `LongTextGenerationRouter` does, and plans it before any engine work.
final class CLILongFormTests: XCTestCase {
    private static let contract = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")

    /// About 1,500 characters: past one take (900), two or more segments.
    private static let story = Array(repeating: "The lighthouse keeper climbed the stairs again, counting each step aloud.", count: 20)
        .joined(separator: " ")

    private func makeRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("CLILongForm-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }

    @MainActor
    private func prepare(_ argv: [String]) async throws -> GenerateCommand.PreparedTake {
        let root = try makeRoot()
        let args = try CLIParser.args(
            argv + ["--data-dir=\(root.path)", "--manifest=\(Self.contract.path)"], for: "generate"
        )
        return try await GenerateCommand.prepare(args, interactive: false)
    }

    private func code(_ body: () throws -> Bool) -> VocelloErrorCode? {
        do {
            _ = try body()
            return nil
        } catch {
            return (error as? CLIError)?.code
        }
    }

    func testTheRouteFollowsTheAppsSingleTakePredicate() throws {
        XCTAssertTrue(SingleTakeScriptBudget.measure(Self.story).exceedsSingleTake, "the fixture is past one take")
        XCTAssertFalse(try GenerateCommand.routesToLongForm("Hello there.", route: .auto))
        XCTAssertTrue(try GenerateCommand.routesToLongForm(Self.story, route: .auto), "past one take, as the apps route it")
        XCTAssertTrue(try GenerateCommand.routesToLongForm("Hello there.", route: .always))
        XCTAssertFalse(try GenerateCommand.routesToLongForm("Hello there.", route: .never))
        XCTAssertEqual(code { try GenerateCommand.routesToLongForm(Self.story, route: .never) }, .textTooLong)
        XCTAssertEqual(code { try GenerateCommand.routesToLongForm("  ", route: .always) }, .invalidInput)
        XCTAssertEqual(code { try GenerateCommand.routesToLongForm("…!", route: .auto) }, .invalidInput)
        do {
            _ = try GenerateCommand.routesToLongForm(Self.story, route: .never)
        } catch let error as CLIError {
            XCTAssertTrue(error.description.contains("drop --long-form never"), error.description)
        }
    }

    func testAProjectPlansWithTheGivenSeedWithinTheAppsLimit() throws {
        let plan = try CLILongFormProject.plan(Self.story, seed: 42)
        XCTAssertGreaterThan(plan.segments.count, 1)
        XCTAssertEqual(plan.configuration.baseSeed, 42)
        XCTAssertEqual(try CLILongFormProject.plan(Self.story, seed: 42).evidence.planDigest, plan.evidence.planDigest,
                       "the same script and seed plan the same project")

        XCTAssertNoThrow(try CLILongFormProject.admit(segmentCount: CLILimits.longFormMaximumSegments))
        XCTAssertThrowsError(try CLILongFormProject.admit(segmentCount: CLILimits.longFormMaximumSegments + 1)) {
            XCTAssertEqual(($0 as? CLIError)?.code, .textTooLong, "more segments than the apps accept")
        }
    }

    @MainActor
    func testGeneratePlansALongScriptBeforeAnyEngineWork() async throws {
        let long = try await prepare(["--text", Self.story, "--seed", "7"])
        let plan = try XCTUnwrap(long.longFormPlan, "a script past one take is a long-form project")
        XCTAssertEqual(plan.configuration.baseSeed, 7)
        let report = try GenerateCommand.plan(long)
        XCTAssertTrue(report.longForm)
        XCTAssertEqual(report.segments, plan.segments.count)

        let short = try await prepare(["--text", "Hello there."])
        XCTAssertNil(short.longFormPlan)
        XCTAssertNil(try GenerateCommand.plan(short).segments)
        let forced = try await prepare(["--text", "Hello there.", "--long-form", "always"])
        XCTAssertNotNil(forced.longFormPlan)
        XCTAssertNotEqual(try GenerateCommand.identity(of: forced), try GenerateCommand.identity(of: short),
                          "a long-form project is a different request from the single take")

        for argv in [["--text", Self.story, "--long-form", "never"], ["--text", Self.story, "--no-stream"]] {
            do {
                _ = try await prepare(argv)
                XCTFail("\(argv.suffix(2)) is refused before boot")
            } catch {
                XCTAssertEqual((error as? CLIError)?.code, argv.last == "never" ? .textTooLong : .invalidInput)
            }
        }
        let request = try CLIGenerateRequest.parse(.object(["longForm": .string("never")]))
        XCTAssertEqual(request.argv, ["--long-form=never"])
    }
}
