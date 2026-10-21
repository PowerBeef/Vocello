import Foundation
import QwenVoiceCore
import VocelloDesktopCore
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

    // MARK: - The apps' runner's outcome

    private func segment(
        _ index: Int, _ status: DesktopLongFormSegment.Status, qcPassed: Bool? = true, finish: String? = "eos"
    ) -> DesktopLongFormSegment {
        DesktopLongFormSegment(
            index: index, segmentID: "s\(index)", boundary: "sentence", intendedPauseMilliseconds: 300,
            seed: UInt64.max - UInt64(index), status: status, generationID: UUID(),
            audioPath: status == .saved ? "/takes/\(index).wav" : nil, durationSeconds: status == .saved ? 2 : nil,
            finishReason: status == .saved ? finish : nil, qcPassed: status == .pending ? nil : qcPassed,
            qcRequiredFailures: qcPassed == false ? ["pause_budget"] : [], qcWarnings: []
        )
    }

    private func outcome(
        _ status: DesktopLongFormOutcome.Status, _ segments: [DesktopLongFormSegment],
        failure: DesktopLongFormOutcome.Failure? = nil
    ) -> DesktopLongFormOutcome {
        DesktopLongFormOutcome(
            status: status, failure: failure, message: failure == nil ? nil : "Segment 2 didn't pass.",
            segments: segments, languageHint: "english", joinedPath: status == .completed ? "/takes/joined.wav" : nil,
            durationSeconds: status == .completed ? 4 : nil, manifestPath: status == .completed ? "/takes/m.json" : nil,
            assembly: nil
        )
    }

    /// Every failure reason's copy is distinct, so a failed project's message reads
    /// back to its own reason and contract code.
    func testAFailureMessageReadsBackToItsReason() {
        let messages = GenerationFailurePresentationReason.allCases.map(DesktopLongFormOutcome.Failure.message(for:))
        XCTAssertEqual(Set(messages).count, messages.count, "two reasons share copy: the read-back would be ambiguous")
        for reason in GenerationFailurePresentationReason.allCases {
            let failure = DesktopLongFormOutcome.Failure(
                message: DesktopLongFormOutcome.Failure.message(for: reason), segments: [segment(0, .failed, qcPassed: nil)]
            )
            XCTAssertEqual(failure, .generation(reason))
            XCTAssertEqual(CLILongFormProject.classify(failure, failing: nil).0, CLIFailure.code(for: reason))
        }
        XCTAssertEqual(
            DesktopLongFormOutcome.Failure(message: "anything", segments: [segment(0, .saved), segment(1, .failed, qcPassed: false)]),
            .segmentQCRejected(index: 1), "a QC verdict wins over the message"
        )
        XCTAssertEqual(DesktopLongFormOutcome.Failure(message: "unknown", segments: [segment(0, .saved)]), .other)
    }

    /// The runner's outcome as the CLI reports it: kept takes, typed stops, and
    /// an interrupt told apart from the engine's own stop.
    func testTheOutcomeMapsToTypedStops() throws {
        let start = CLILongFormProject.Outcome(baseSeed: 7, planDigest: "digest")
        let completed = CLILongFormProject.report(
            outcome(.completed, [segment(0, .saved, finish: "max_tokens"), segment(1, .saved)]),
            into: start, lastSubmitted: nil, signalled: false
        )
        XCTAssertTrue(completed.completed)
        XCTAssertEqual(completed.segments.map(\.effectiveSeed), [String(UInt64.max), String(UInt64.max - 1)])
        XCTAssertEqual(completed.finishReason, "max_tokens", "a truncated segment is the project's finish reason")
        XCTAssertEqual(completed.language, "english")
        XCTAssertEqual(completed.manifestPath, "/takes/m.json")

        let rejected = CLILongFormProject.report(
            outcome(.failed, [segment(0, .saved), segment(1, .failed, qcPassed: false), segment(2, .pending)],
                    failure: .segmentQCRejected(index: 1)),
            into: start, lastSubmitted: nil, signalled: false
        )
        guard case .failed(let error, let code, let signalled)? = rejected.stop else { return XCTFail("failed") }
        XCTAssertEqual(code, .qcRejected)
        XCTAssertFalse(signalled)
        XCTAssertEqual((error as? CLIError)?.detail?["segment"], .integer(1))
        XCTAssertEqual(rejected.segments.count, 1, "the kept take stays reported")
        XCTAssertNotNil(rejected.generationID, "the rejected take is named")

        let joined = CLILongFormProject.report(
            outcome(.failed, [segment(0, .saved)], failure: .joinedQCRejected), into: start, lastSubmitted: UUID(),
            signalled: false
        )
        guard case .failed(_, .qcRejected, _)? = joined.stop else { return XCTFail("the join's QC") }
        XCTAssertNil(joined.generationID, "the join, not a take, failed")

        let interrupted = CLILongFormProject.report(
            outcome(.cancelled, [segment(0, .cancelled)]), into: start, lastSubmitted: nil, signalled: true
        )
        guard case .cancelled? = interrupted.stop else { return XCTFail("a signal is an interrupt") }
        let engineStop = CLILongFormProject.report(
            outcome(.cancelled, [segment(0, .cancelled)]), into: start, lastSubmitted: nil, signalled: false
        )
        guard case .engine(let stopped)? = engineStop.stop else { return XCTFail("no signal: the engine stopped it") }
        XCTAssertEqual(stopped, CLIEngineCancellation(reason: .memoryPressure))
    }

    // MARK: - Files

    /// Review B1 (01f9206f): each attempt creates its own project folder, so a stop
    /// never removes another run's segments and two runs never share one.
    func testEachAttemptOwnsItsProjectFolder() throws {
        let root = try makeRoot()
        let output = root.appendingPathComponent("story.wav")
        let attempt = UUID()
        let first = try CLILongFormProject.makeProjectFolder(beside: output, attempt: attempt)
        XCTAssertEqual(first.lastPathComponent, "story_segments")
        let second = try CLILongFormProject.makeProjectFolder(beside: output, attempt: attempt)
        XCTAssertEqual(
            second.lastPathComponent, "story_segments-\(attempt.uuidString.lowercased().prefix(8))",
            "an existing folder is never reused"
        )
        XCTAssertThrowsError(try CLILongFormProject.makeProjectFolder(beside: output, attempt: attempt)) {
            XCTAssertEqual(($0 as? CLIError)?.code, .outputUnavailable)
        }
    }

    /// Review B2 (01f9206f): a clone project never replaces its reference audio,
    /// whether --out names it directly, through a symlink or as a hard link.
    func testAProjectNeverReplacesItsCloneReference() throws {
        let root = try makeRoot()
        let reference = root.appendingPathComponent("voice.wav")
        try Data([1]).write(to: reference)
        let clone = GenerationRequest.Payload.clone(
            reference: CloneReference(audioPath: reference.path, transcript: nil, preparedVoiceID: nil)
        )
        let symlink = root.appendingPathComponent("alias.wav")
        try FileManager.default.createSymbolicLink(at: symlink, withDestinationURL: reference)
        let hardLink = root.appendingPathComponent("hard.wav")
        try FileManager.default.linkItem(at: reference, to: hardLink)
        for alias in [reference.path, root.path + "/./voice.wav", symlink.path, hardLink.path] {
            XCTAssertThrowsError(try CLILongFormProject.refuseReferenceAlias(output: alias, payload: clone), alias) {
                XCTAssertEqual(($0 as? CLIError)?.code, .invalidInput)
            }
        }
        XCTAssertNoThrow(try CLILongFormProject.refuseReferenceAlias(
            output: root.appendingPathComponent("take.wav").path, payload: clone
        ))
        XCTAssertNoThrow(try CLILongFormProject.refuseReferenceAlias(
            output: reference.path, payload: .custom(speakerID: "ryan", deliveryStyle: nil)
        ), "only a clone has a reference to protect")
    }

    // MARK: - Line by line

    /// RF-27: `--line-by-line` splits the script as the app's line batch does and
    /// refuses, before boot, what that batch would refuse.
    @MainActor
    func testLineByLineFollowsTheAppsLineBatch() async throws {
        let script = "Hello there.\n  Hello there.  \n***\n\nGoodbye for now.\n"
        let take = try await prepare(["--text", script, "--line-by-line", "--seed", "5"])
        XCTAssertEqual(take.lineBatch, ["Hello there.", "Hello there.", "Goodbye for now."],
                       "trimmed; blank and unspeakable lines skipped")
        XCTAssertNil(take.longFormPlan, "one take per line wins over long-form routing")
        let report = try GenerateCommand.plan(take)
        XCTAssertTrue(report.lineByLine)
        XCTAssertEqual(report.lines, 3)
        XCTAssertEqual(report.outputPath, take.lineOutputDirectory?.path)

        let longScript = Array(repeating: "The lighthouse keeper climbed the stairs again.", count: 30)
            .joined(separator: "\n")
        XCTAssertTrue(SingleTakeScriptBudget.measure(longScript).exceedsSingleTake)
        let longLines = try await prepare(["--text", longScript, "--line-by-line"])
        XCTAssertNotNil(longLines.lineBatch, "a long script whose lines each fit one take")
        let tooMany = (0 ... DesktopLineBatch.maxLines).map { "Line \($0)." }.joined(separator: "\n")
        for (argv, expected) in [
            (["--text", "Hi.", "--line-by-line", "--out", "/tmp/x.wav"], VocelloErrorCode.usageError),
            (["--text", "Hi.", "--line-by-line", "--long-form", "always"], .usageError),
            (["--text", "Hi.", "--out-dir", "/tmp/takes"], .usageError),
            (["--text", "Hi.", "--line-by-line", "--no-stream"], .invalidInput),
            (["--text", "***\n---", "--line-by-line"], .invalidInput),
            (["--text", tooMany, "--line-by-line"], .textTooLong),
            (["--text", Self.story, "--line-by-line"], .textTooLong),
        ] {
            do {
                _ = try await prepare(argv)
                XCTFail("\(argv.dropFirst(2)) is refused before boot")
            } catch {
                XCTAssertEqual((error as? CLIError)?.code, expected, "\(argv.dropFirst(2))")
            }
        }
    }

    /// The requests come from the app's plan: streaming, one batch seed (a repeated
    /// line derives its own), one script language, the Neutral delivery by default.
    func testLineRequestsAreTheAppsRequests() throws {
        let registry = try ContractBackedModelRegistry(manifestURL: Self.contract)
            .expandedForPlatform(.macOS, deviceClass: .mid16GBMac, includeBaseAliases: true)
        let custom = try XCTUnwrap(registry.model(id: "pro_custom_speed"))
        let lines = [
            "The lighthouse keeper climbed the stairs again.", "The lighthouse keeper climbed the stairs again.",
            "Far below, the harbour lights flickered one by one.",
        ]
        let batch = DesktopLineBatch(
            mode: .custom, model: custom, lines: lines, payload: .custom(speakerID: "ryan", deliveryStyle: nil),
            deliveryInstructionCellID: nil, language: nil, variation: .balanced, batchSeed: 5
        )
        XCTAssertEqual(batch.language, .english, "Auto resolves once over the script")
        XCTAssertEqual(batch.seed(forLineAt: 0), 5)
        XCTAssertNotEqual(batch.seed(forLineAt: 1), 5, "a repeated line derives its own seed")
        XCTAssertEqual(batch.seed(forLineAt: 2), 5)
        let request = try XCTUnwrap(batch.request(forLineAt: 1, outputPath: "/tmp/1.wav", generationID: UUID()))
        XCTAssertTrue(request.shouldStream)
        XCTAssertEqual(request.seed, batch.seed(forLineAt: 1))
        XCTAssertEqual(request.variation, .balanced)
        XCTAssertEqual(Qwen3SupportedLanguage.normalized(request.languageHint), .english)
        if custom.supportsInstructionControl {
            XCTAssertEqual(request.payload.deliveryInstructionText, EmotionPreset.neutralPresetInstruction,
                           "the app sends the Neutral delivery when none is given")
        }
        XCTAssertNil(batch.request(forLineAt: 3, outputPath: "/tmp/3.wav", generationID: UUID()))

        let styled = DesktopLineBatch(
            mode: .custom, model: custom, lines: lines, payload: .custom(speakerID: "ryan", deliveryStyle: "Whisper."),
            deliveryInstructionCellID: nil, language: .french, variation: nil, batchSeed: nil
        )
        XCTAssertEqual(styled.language, .french, "an explicit language is kept")
        let styledRequest = try XCTUnwrap(styled.request(forLineAt: 0, outputPath: "/tmp/0.wav", generationID: UUID()))
        if custom.supportsInstructionControl {
            XCTAssertEqual(styledRequest.payload.deliveryInstructionText, "Whisper.")
        }
    }
}
