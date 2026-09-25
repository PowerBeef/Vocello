import Foundation
@testable import QwenVoiceCore
import XCTest

/// Thrown by `LongFormFixtureEngine` for a take the test scripts to fail.
private struct LongFormFixtureEngineFailure: LocalizedError {
    var errorDescription: String? { "fixture engine failure" }
}

/// The store's fake engine (`StoreFixtureEngine`), publishing a real 24 kHz
/// PCM16 WAV at the request's output path when a take ends: a steady tone that
/// passes the persisted-WAV QC, or silence that fails it. A take can instead
/// throw, or be held open until the test releases it or the cancellation
/// barrier ends it. Like the engine's atomic publication, a cancelled take
/// leaves no file.
@MainActor
private final class LongFormFixtureEngine: StoreFixtureEngine {
    enum Take: Equatable {
        case speech
        case silence
        case failure
    }

    /// Outcome by take index over the engine's life; unlisted takes speak.
    var scriptedTakes: [Int: Take] = [:]
    /// Take indices held open until `releaseGeneration()` or the barrier.
    var heldTakes: Set<Int> = []
    /// Every request that reached the engine, including failed takes.
    private(set) var takeRequests: [GenerationRequest] = []

    override func generate(_ request: GenerationRequest) async throws -> GenerationResult {
        let index = takeRequests.count
        takeRequests.append(request)
        let take = scriptedTakes[index] ?? .speech
        if take == .failure {
            throw LongFormFixtureEngineFailure()
        }
        holdsGeneration = heldTakes.contains(index)
        let result = try await super.generate(request)
        try Self.write(take, to: request.outputPath)
        return result
    }

    /// Half a second at 24 kHz: a 250 Hz tone (a whole number of periods) at
    /// about -15 dBFS, or digital silence.
    private static func write(_ take: Take, to path: String) throws {
        let sampleRate = 24_000
        let samples: [Int16] = (0..<12_000).map { frame in
            guard take == .speech else { return 0 }
            let phase = 2 * Double.pi * 250 * Double(frame) / Double(sampleRate)
            return Int16((sin(phase) * 8_000).rounded())
        }
        try AtomicPCM16WAVWriter.write(
            pcmSamples: samples,
            sampleRate: sampleRate,
            outputURL: URL(fileURLWithPath: path)
        )
    }
}

/// Records the shared-player calls the runner and its coordinator make.
@MainActor
private final class LongFormFixturePlayer: IOSLongFormAudioPlayback {
    enum Call: Equatable {
        case beginGenerationPlayback
        case setLivePreviewEstimate
        case prepareStreamingPreview(generationID: UUID?)
        case completeStreamingPreview(audioPath: String, shouldAutoPlay: Bool)
        case abortLivePreview
        case finishGenerationPreview
    }

    private(set) var calls: [Call] = []

    func beginGenerationPlayback(operationID: UUID, mode: GenerationMode) {
        calls.append(.beginGenerationPlayback)
    }

    func setLivePreviewEstimate(_ estimate: LivePreviewEstimate?) {
        calls.append(.setLivePreviewEstimate)
    }

    func prepareStreamingPreview(
        title: String,
        shouldAutoPlay: Bool,
        generationID: UUID?,
        playbackOperationID: UUID?
    ) {
        calls.append(.prepareStreamingPreview(generationID: generationID))
    }

    func completeStreamingPreview(
        result: GenerationResult,
        title: String,
        shouldAutoPlay: Bool,
        playbackOperationID: UUID?
    ) {
        calls.append(.completeStreamingPreview(audioPath: result.audioPath, shouldAutoPlay: shouldAutoPlay))
    }

    func abortLivePreviewIfNeeded() {
        calls.append(.abortLivePreview)
    }

    func finishGenerationPreview(playbackOperationID: UUID) {
        calls.append(.finishGenerationPreview)
    }
}

/// Platform hooks that record the side effects the apps route elsewhere.
@MainActor
private final class LongFormFixtureHooks: IOSLongFormPlatformHooks {
    private(set) var finalizedGenerationIDs: [UUID] = []
    private(set) var acceptedJoinedPaths: [String] = []
    private(set) var successCount = 0
    private(set) var warningCount = 0

    var presentation: VocelloPresentationText { IOSAppLanguage.shared.presentation }

    func requestVariation() -> Qwen3SamplingVariation? { nil }

    func waveformSeed(for text: String) -> Int { text.count }

    func segmentTitle(index: Int, total: Int) -> String { "Segment \(index + 1) of \(total)" }

    var longFormModeLabel: String { "Long-form" }

    var longFormProjectTitle: String { "Long-form project" }

    func segmentTelemetryFinalized(generationID: UUID, publishedAudioURL: URL?) {
        finalizedGenerationIDs.append(generationID)
    }

    func projectAccepted(_ saved: Generation, joinedAudioPath: String) {
        acceptedJoinedPaths.append(joinedAudioPath)
    }

    func notifySuccess() { successCount += 1 }

    func notifyWarning() { warningCount += 1 }
}

/// The shared services over a private History on real SQLite: segment rows are
/// saved the way the outbox commits them, and the joined project goes through
/// the real long-form acceptance unless the test makes it throw.
@MainActor
private final class LongFormFixtureServices: IOSLongFormProjectServices {
    enum TimelineEvent: Equatable {
        case submitted(UUID)
        case completed(UUID)
        case failed(UUID, GenerationTerminalReason)
    }

    let database: DatabaseService
    let outputsRoot: URL
    var shouldAutoPlay = false
    /// Thrown in place of History acceptance of the joined project.
    var acceptanceError: LongFormAcceptanceError?
    private(set) var timeline: [TimelineEvent] = []
    private(set) var persistenceCallers: [String] = []
    private(set) var acceptanceCandidates: [LongFormHistoryAcceptance] = []
    private var outputCount = 0

    init(database: DatabaseService, outputsRoot: URL) {
        self.database = database
        self.outputsRoot = outputsRoot
    }

    func segmentOutputPath(subfolder: String, text: String) -> String {
        let directory = outputsRoot.appendingPathComponent(subfolder, isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        outputCount += 1
        return directory.appendingPathComponent("take-\(outputCount).wav").path
    }

    func recordSubmitted(id: UUID, mode: String) async {
        timeline.append(.submitted(id))
    }

    func recordCompleted(
        id: UUID,
        mode: String,
        usedStreaming: Bool,
        finishReason: String?,
        summary: TelemetrySummary?
    ) async {
        timeline.append(.completed(id))
    }

    func recordFailed(id: UUID, finishReason: GenerationTerminalReason) async {
        timeline.append(.failed(id, finishReason))
    }

    func persistSegment(_ record: Generation, caller: String) async -> GenerationHistoryPersistenceOutcome {
        persistenceCallers.append(caller)
        do {
            _ = try await database.saveGenerationAsync(record)
            return .saved
        } catch {
            return .unableToQueue
        }
    }

    func acceptLongFormProject(_ candidate: LongFormHistoryAcceptance) async throws -> Generation {
        acceptanceCandidates.append(candidate)
        if let acceptanceError {
            throw acceptanceError
        }
        return try await database.acceptLongFormProject(candidate)
    }
}

/// Holds a runner outcome produced inside a task.
@MainActor
private final class LongFormOutcomeBox {
    var outcome: IOSLongFormOutcome?
}

/// PA-19: the long-form coordinator and runner both apps share, compiled by path
/// and driven over the store's fake engine, a player recorder and a private
/// History on real SQLite. Covers one sequential take per segment and History
/// acceptance of the joined output, cancellation mid-project and resume, a take
/// that finishes after the cancellation request, a failed and a QC-rejected
/// segment, an acceptance left to recovery (PA-30) or refused, and
/// single-segment regeneration.
@MainActor
final class IOSLongFormProjectRunnerTests: XCTestCase {
    /// Three sentences of nine planner tokens each: one segment per sentence
    /// under a twelve-token limit.
    private static let script = "Gulls circled the pier. Rain fell on the harbor. Lamps lit the long quay."

    @MainActor
    private struct Fixture {
        let engine: LongFormFixtureEngine
        let store: TTSEngineStore
        let database: DatabaseService
        let services: LongFormFixtureServices
        let hooks: LongFormFixtureHooks
        let player: LongFormFixturePlayer
        let studio: StudioGenerationCoordinator
        let request: IOSLongFormProjectRequest

        var plan: LongFormPlan { request.plan }

        var pendingSegments: [IOSLongFormSegmentState] {
            request.lines.enumerated().map { index, line in
                IOSLongFormSegmentState(index: index, line: line, status: .pending)
            }
        }

        func makeCoordinator() -> IOSLongFormCoordinator {
            IOSLongFormCoordinator(hooks: hooks, services: services)
        }

        func makeRunner(cancellation: IOSLongFormCancellationState) -> IOSLongFormProjectRunner {
            IOSLongFormProjectRunner(
                ttsEngine: store,
                audioPlayer: player,
                cancellationState: cancellation,
                hooks: hooks,
                services: services
            )
        }
    }

    private func makeFixture() throws -> Fixture {
        let created = FileManager.default.temporaryDirectory
            .appendingPathComponent("IOSLongFormProjectRunner-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: created, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: created) }
        let root = created.resolvingSymlinksInPath()

        let contractURL = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        let registry = try ContractBackedModelRegistry(manifestURL: contractURL)
        let model = try XCTUnwrap(registry.models.first { $0.mode == .custom })
        let engine = LongFormFixtureEngine(modelRegistry: registry)
        let backend = AnyTTSEngineBackend(
            engine: engine,
            supportsSavedVoiceMutation: true,
            supportsModelManagementMutation: true,
            supportedModes: [.custom, .design, .clone],
            voiceCloningConsent: { VoiceCloningConsentPolicy(isConsentRecorded: true) }
        )
        let dial = MemoryHeadroomDial(megabytes: MemoryHeadroomDial.healthy)
        let store = TTSEngineStore(
            backend: backend,
            memoryBudgetPolicy: .iPhoneShippingDefault,
            memorySnapshotProvider: { dial.snapshot() }
        )

        let plan = try LongFormPlanner.plan(
            spokenTextPlan: try SpokenTextPlanner.plan(originalText: Self.script),
            configuration: LongFormPlanningConfiguration(runtimeTokenLimit: 12, baseSeed: 19)
        )
        let request = IOSLongFormProjectRequest(
            mode: .custom,
            model: model,
            plan: plan,
            voice: "aiden",
            emotion: nil,
            deliveryInstructionCellID: nil,
            languageHint: "en",
            voiceDescription: nil,
            refAudio: nil,
            refText: nil,
            preparedVoiceID: nil
        )
        XCTAssertEqual(
            request.lines,
            ["Gulls circled the pier.", "Rain fell on the harbor.", "Lamps lit the long quay."],
            "The fixture plans one segment per sentence"
        )

        let historyRoot = root.appendingPathComponent("history", isDirectory: true)
        try FileManager.default.createDirectory(at: historyRoot, withIntermediateDirectories: true)
        let database = DatabaseService(rootDirectory: historyRoot)
        return Fixture(
            engine: engine,
            store: store,
            database: database,
            services: LongFormFixtureServices(
                database: database,
                outputsRoot: root.appendingPathComponent("outputs", isDirectory: true)
            ),
            hooks: LongFormFixtureHooks(),
            player: LongFormFixturePlayer(),
            studio: StudioGenerationCoordinator(mode: .custom),
            request: request
        )
    }

    /// Runs the whole project on a fresh runner under one Studio attempt.
    private func runProject(
        _ f: Fixture,
        cancellation: IOSLongFormCancellationState = IOSLongFormCancellationState()
    ) async throws -> IOSLongFormOutcome {
        let attempt = try XCTUnwrap(f.studio.start(live: nil))
        return await f.makeRunner(cancellation: cancellation).run(
            request: f.request,
            initialSegments: f.pendingSegments,
            priorReplacements: [],
            onProgress: { _ in },
            onSegmentsUpdated: { _ in },
            studioCoordinator: f.studio,
            studioAttempt: attempt
        )
    }

    /// Lets the main actor run the coordinator's task, the store's state syncs
    /// and the detached QC passes.
    private func waitUntil(
        _ description: String,
        timeout: Duration = .seconds(10),
        file: StaticString = #filePath,
        line: UInt = #line,
        _ condition: () -> Bool
    ) async {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while !condition() {
            guard clock.now < deadline else {
                XCTFail("Timed out waiting for \(description)", file: file, line: line)
                return
            }
            await Task.yield()
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
    }

    private func rows(_ f: Fixture, role: String) throws -> [Generation] {
        try f.database.fetchAllGenerations().filter { $0.longFormRole == role }
    }

    // MARK: - A whole project

    func testAProjectRunsOneTakePerSegmentInOrderAndAcceptsOneJoinedRow() async throws {
        let f = try makeFixture()
        let coordinator = f.makeCoordinator()

        coordinator.start(request: f.request, ttsEngine: f.store, audioPlayer: f.player, studioCoordinator: f.studio)
        XCTAssertTrue(coordinator.isProcessing)
        XCTAssertTrue(f.studio.isGenerating)
        XCTAssertEqual(coordinator.lastMode, .custom)
        await waitUntil("the project to finish") { !coordinator.isProcessing }

        guard case .completed(let segments, let joinedAudioPath, _) = coordinator.outcome else {
            return XCTFail("Expected a completed project, got \(String(describing: coordinator.outcome))")
        }
        // One ordinary streaming take per segment, in plan order, on its planned sub-seed.
        let takes = f.engine.takeRequests
        XCTAssertEqual(takes.map(\.text), f.request.lines)
        XCTAssertEqual(takes.map(\.seed), f.plan.segments.map { Optional($0.evidence.effectiveSubseed) })
        XCTAssertTrue(takes.allSatisfy { $0.shouldStream && $0.mode == .custom && $0.modelID == f.request.model.id })
        let generationIDs = takes.compactMap(\.generationID)
        XCTAssertEqual(Set(generationIDs).count, 3, "Every take has its own identity")
        // Each take is submitted only once the previous one completed.
        XCTAssertEqual(f.services.timeline, generationIDs.flatMap { id -> [LongFormFixtureServices.TimelineEvent] in
            [.submitted(id), .completed(id)]
        })
        XCTAssertEqual(f.hooks.finalizedGenerationIDs, generationIDs)
        XCTAssertEqual(f.services.persistenceCallers, Array(repeating: "IOSLongFormSegment", count: 3))
        XCTAssertEqual(segments.map(\.audioPath), takes.map { Optional($0.outputPath) })
        XCTAssertEqual(segments.map(\.generationID), generationIDs.map { Optional($0) })
        XCTAssertTrue(segments.allSatisfy { $0.qualityReport?.passed == true })

        // One joined History row next to the three segment rows, all in the project.
        let segmentRows = try rows(f, role: "segment")
        XCTAssertEqual(Set(segmentRows.map(\.audioPath)), Set(takes.map(\.outputPath)))
        XCTAssertEqual(
            Set(segmentRows.compactMap(\.seed)),
            Set(f.plan.segments.map { Int64(bitPattern: $0.evidence.effectiveSubseed) })
        )
        let joinedRows = try rows(f, role: "joined")
        XCTAssertEqual(joinedRows.map(\.audioPath), [joinedAudioPath])
        XCTAssertEqual(joinedRows.first?.text, f.request.lines.joined(separator: " "))
        XCTAssertEqual(try f.database.fetchAllGenerations().count, 4)
        XCTAssertTrue(
            try f.database.fetchAllGenerations().allSatisfy { $0.longFormProjectID == f.plan.evidence.planDigest }
        )
        XCTAssertTrue(FileManager.default.fileExists(atPath: joinedAudioPath))

        // The accepted manifest records every segment's identity, seed and QC.
        let candidate = try XCTUnwrap(f.services.acceptanceCandidates.last)
        XCTAssertEqual(f.services.acceptanceCandidates.count, 1)
        XCTAssertEqual(try Data(contentsOf: candidate.manifestURL), try candidate.manifest.canonicalJSONData())
        XCTAssertEqual(candidate.manifest.plan.planDigest, f.plan.evidence.planDigest)
        XCTAssertEqual(candidate.manifest.execution?.segments.map(\.qcPassed), [true, true, true])
        XCTAssertEqual(candidate.manifest.execution?.segments.map(\.generationID), generationIDs.map { Optional($0) })
        XCTAssertEqual(
            candidate.manifest.execution?.segments.map(\.effectiveSeed),
            f.plan.segments.map { Optional($0.evidence.effectiveSubseed) }
        )
        XCTAssertEqual(candidate.manifest.assembly?.segmentCount, 3)
        XCTAssertNil(candidate.manifest.replacements)
        XCTAssertEqual(candidate.ownedAudioURLs.map(\.path), [joinedAudioPath])

        // Live narration per take, then the joined output reaches the player and the dock.
        var expectedCalls: [LongFormFixturePlayer.Call] = [.beginGenerationPlayback]
        for id in generationIDs {
            expectedCalls.append(.setLivePreviewEstimate)
            expectedCalls.append(.prepareStreamingPreview(generationID: id))
        }
        expectedCalls.append(.finishGenerationPreview)
        expectedCalls.append(.completeStreamingPreview(audioPath: joinedAudioPath, shouldAutoPlay: false))
        XCTAssertEqual(f.player.calls, expectedCalls)
        XCTAssertEqual(f.hooks.acceptedJoinedPaths, [joinedAudioPath])
        XCTAssertEqual(f.hooks.successCount, 1)
        XCTAssertEqual(f.hooks.warningCount, 0)
        XCTAssertFalse(f.studio.isGenerating)
        XCTAssertNil(f.studio.errorMessage)
        XCTAssertEqual(f.studio.lastCompletedOutput?.audioURL.path, joinedAudioPath)
        XCTAssertEqual(f.studio.lastCompletedOutput?.transcript, f.request.lines.joined(separator: " "))
        XCTAssertFalse(coordinator.canResume)
        XCTAssertTrue(coordinator.canRegenerateSegments)
        XCTAssertEqual(coordinator.progress, IOSLongFormProgressSnapshot())
        XCTAssertFalse(f.store.hasActiveGeneration)
        XCTAssertFalse(f.store.hasSustainedPerformanceActivity, "The run released its fixed-refresh hold")
    }

    // MARK: - Cancellation and resume

    func testCancellingMidProjectKeepsTheSavedSegmentAndResumeFinishesWithoutRegeneratingIt() async throws {
        let f = try makeFixture()
        let coordinator = f.makeCoordinator()
        f.engine.heldTakes = [1]

        coordinator.start(request: f.request, ttsEngine: f.store, audioPlayer: f.player, studioCoordinator: f.studio)
        await waitUntil("the second take to reach the engine") { f.engine.generateRequests.count == 2 }
        let barrier = try XCTUnwrap(coordinator.startCancellation(
            ttsEngine: f.store,
            audioPlayer: f.player,
            studioCoordinator: f.studio,
            reason: .user
        ))
        XCTAssertFalse(
            coordinator.cancel(ttsEngine: f.store, audioPlayer: f.player, studioCoordinator: f.studio),
            "A duplicate cancellation is rejected"
        )
        await barrier.value
        await waitUntil("the run to stop") { !coordinator.isProcessing }

        XCTAssertEqual(f.engine.cancellationReasons, [.user], "The engine barrier ends the held take")
        guard case .cancelled(let stopped) = coordinator.outcome else {
            return XCTFail("Expected a cancelled project, got \(String(describing: coordinator.outcome))")
        }
        let firstTake = f.engine.takeRequests[0]
        let cancelledTake = f.engine.takeRequests[1]
        XCTAssertEqual(stopped.map(\.status), [.saved(audioPath: firstTake.outputPath), .cancelled, .cancelled])
        XCTAssertEqual(f.engine.takeRequests.count, 2, "The third segment never reaches the engine")
        let cancelledID = try XCTUnwrap(cancelledTake.generationID)
        XCTAssertEqual(f.services.timeline.last, .failed(cancelledID, .cancelled))
        XCTAssertEqual(f.services.persistenceCallers.count, 1, "The cancelled take never reaches the History write")
        XCTAssertEqual(try f.database.fetchAllGenerations().map(\.audioPath), [firstTake.outputPath])
        XCTAssertTrue(f.services.acceptanceCandidates.isEmpty, "A cancelled project is never accepted")
        XCTAssertTrue(f.player.calls.contains(.abortLivePreview))
        XCTAssertFalse(f.studio.isGenerating)
        XCTAssertNil(f.studio.errorMessage)
        XCTAssertNil(f.studio.lastCompletedOutput)
        XCTAssertEqual(f.hooks.warningCount, 0, "A cancellation is not a failure")
        XCTAssertFalse(f.store.hasActiveGeneration)
        XCTAssertTrue(coordinator.canResume)

        f.engine.heldTakes = []
        coordinator.resume(ttsEngine: f.store, audioPlayer: f.player, studioCoordinator: f.studio)
        XCTAssertTrue(coordinator.isProcessing)
        await waitUntil("the resumed project to finish") { !coordinator.isProcessing }

        guard case .completed(let segments, let joinedAudioPath, _) = coordinator.outcome else {
            return XCTFail("Expected a completed project, got \(String(describing: coordinator.outcome))")
        }
        let takes = f.engine.takeRequests
        let lines = f.request.lines
        XCTAssertEqual(takes.map(\.text), [lines[0], lines[1], lines[1], lines[2]], "Resume regenerates only what is missing")
        XCTAssertEqual(segments[0], stopped[0], "The saved take is reused as it was")
        XCTAssertEqual(segments.map(\.audioPath), [firstTake.outputPath, takes[2].outputPath, takes[3].outputPath])
        XCTAssertTrue(segments.allSatisfy { $0.qualityReport?.passed == true }, "The reused take is verified again")
        XCTAssertEqual(Set(try rows(f, role: "segment").map(\.audioPath)), Set(segments.compactMap(\.audioPath)))
        XCTAssertEqual(try rows(f, role: "joined").map(\.audioPath), [joinedAudioPath])
        XCTAssertEqual(try f.database.fetchAllGenerations().count, 4)
        XCTAssertEqual(f.studio.lastCompletedOutput?.audioURL.path, joinedAudioPath)
        XCTAssertFalse(coordinator.canResume)
    }

    func testATakeThatFinishesAfterTheCancellationRequestNeverReachesHistory() async throws {
        let f = try makeFixture()
        f.engine.heldTakes = [1]
        let cancellation = IOSLongFormCancellationState()
        let attempt = try XCTUnwrap(f.studio.start(live: nil))
        let runner = f.makeRunner(cancellation: cancellation)
        let request = f.request
        let initialSegments = f.pendingSegments
        let studio = f.studio
        let box = LongFormOutcomeBox()
        let run = Task {
            box.outcome = await runner.run(
                request: request,
                initialSegments: initialSegments,
                priorReplacements: [],
                onProgress: { _ in },
                onSegmentsUpdated: { _ in },
                studioCoordinator: studio,
                studioAttempt: attempt
            )
        }
        await waitUntil("the second take to reach the engine") { f.engine.generateRequests.count == 2 }

        // The foreground-exit order (PA-15): the cancellation is recorded first,
        // and the engine still hands back the take it finished.
        await cancellation.request()
        f.engine.releaseGeneration()
        await run.value

        guard case .cancelled(let segments) = box.outcome else {
            return XCTFail("Expected a cancelled project, got \(String(describing: box.outcome))")
        }
        let firstTake = f.engine.takeRequests[0]
        let finishedTake = f.engine.takeRequests[1]
        XCTAssertEqual(segments.map(\.status), [.saved(audioPath: firstTake.outputPath), .cancelled, .cancelled])
        XCTAssertFalse(FileManager.default.fileExists(atPath: finishedTake.outputPath), "The finished take is discarded")
        let finishedID = try XCTUnwrap(finishedTake.generationID)
        XCTAssertEqual(Array(f.services.timeline.suffix(2)), [.submitted(finishedID), .failed(finishedID, .cancelled)])
        XCTAssertEqual(f.hooks.finalizedGenerationIDs.last, finishedID)
        XCTAssertEqual(try f.database.fetchAllGenerations().map(\.audioPath), [firstTake.outputPath])
        XCTAssertEqual(f.engine.takeRequests.count, 2)
        XCTAssertEqual(f.player.calls.last, .abortLivePreview)
        XCTAssertFalse(f.store.hasSustainedPerformanceActivity)
    }

    // MARK: - Failed segments

    func testAFailedSegmentTakeStopsTheProjectWithItsMessage() async throws {
        let f = try makeFixture()
        let coordinator = f.makeCoordinator()
        f.engine.scriptedTakes = [1: .failure]

        coordinator.start(request: f.request, ttsEngine: f.store, audioPlayer: f.player, studioCoordinator: f.studio)
        await waitUntil("the project to stop") { !coordinator.isProcessing }

        let message = f.hooks.presentation.generationFailureMessage(LongFormFixtureEngineFailure())
        guard case .failed(let segments, let failure) = coordinator.outcome else {
            return XCTFail("Expected a failed project, got \(String(describing: coordinator.outcome))")
        }
        let firstTake = f.engine.takeRequests[0]
        XCTAssertEqual(failure, message)
        XCTAssertEqual(segments.map(\.status), [.saved(audioPath: firstTake.outputPath), .failed(message: message), .pending])
        XCTAssertEqual(f.engine.takeRequests.count, 2, "Nothing runs after the failed segment")
        let failedID = try XCTUnwrap(f.engine.takeRequests[1].generationID)
        XCTAssertEqual(Array(f.services.timeline.suffix(2)), [.submitted(failedID), .failed(failedID, .failed)])
        XCTAssertEqual(try f.database.fetchAllGenerations().map(\.audioPath), [firstTake.outputPath])
        XCTAssertTrue(f.services.acceptanceCandidates.isEmpty)
        XCTAssertEqual(f.studio.errorMessage, message)
        XCTAssertFalse(f.studio.isGenerating)
        XCTAssertNil(f.studio.lastCompletedOutput)
        XCTAssertEqual(f.hooks.warningCount, 1)
        XCTAssertEqual(f.hooks.successCount, 0)
        XCTAssertTrue(coordinator.canResume, "The saved segment keeps the project resumable")
    }

    func testASegmentThatFailsQCIsDiscardedAndStopsTheProject() async throws {
        let f = try makeFixture()
        f.engine.scriptedTakes = [1: .silence]

        let outcome = try await runProject(f)

        guard case .failed(let segments, let message) = outcome else {
            return XCTFail("Expected a failed project, got \(outcome)")
        }
        let report = try XCTUnwrap(segments[1].qualityReport)
        XCTAssertFalse(report.passed)
        XCTAssertEqual(segments[1].status, .failed(message: report.failureSummary))
        XCTAssertEqual(message, f.hooks.presentation.segmentQC(2, detail: report.failureSummary))
        XCTAssertEqual(segments[0].qualityReport?.passed, true)
        XCTAssertEqual(segments[2].status, .pending)
        XCTAssertFalse(
            FileManager.default.fileExists(atPath: f.engine.takeRequests[1].outputPath),
            "The rejected take is deleted"
        )
        XCTAssertEqual(try f.database.fetchAllGenerations().map(\.audioPath), [f.engine.takeRequests[0].outputPath])
        XCTAssertEqual(f.engine.takeRequests.count, 2)
        XCTAssertEqual(f.player.calls.last, .abortLivePreview)
        XCTAssertTrue(f.services.acceptanceCandidates.isEmpty)
    }

    // MARK: - History acceptance

    func testAnInterruptedAcceptanceLeavesTheJoinedOutputToRecovery() async throws {
        let f = try makeFixture()
        f.services.acceptanceError = .interrupted

        let outcome = try await runProject(f)

        guard case .failed(let segments, let message) = outcome else {
            return XCTFail("Expected a failed project, got \(outcome)")
        }
        XCTAssertEqual(message, f.hooks.presentation.longFormAcceptanceInterrupted)
        XCTAssertEqual(segments.map(\.isSaved), [true, true, true], "The project stays resumable")
        let candidate = try XCTUnwrap(f.services.acceptanceCandidates.last)
        XCTAssertTrue(
            FileManager.default.fileExists(atPath: candidate.joined.audioPath),
            "Recovery owns the joined output and completes it after resume (PA-30)"
        )
        XCTAssertEqual(candidate.ownedAudioURLs.map(\.path), [candidate.joined.audioPath])
        XCTAssertTrue(f.hooks.acceptedJoinedPaths.isEmpty)
    }

    func testARefusedAcceptanceDiscardsTheJoinedCandidateAndKeepsTheSegments() async throws {
        let f = try makeFixture()
        f.services.acceptanceError = .invalidCandidate

        let outcome = try await runProject(f)

        guard case .failed(let segments, let message) = outcome else {
            return XCTFail("Expected a failed project, got \(outcome)")
        }
        XCTAssertEqual(
            message,
            f.hooks.presentation.assemblyFailed(LongFormAcceptanceError.invalidCandidate.localizedDescription)
        )
        let candidate = try XCTUnwrap(f.services.acceptanceCandidates.last)
        XCTAssertFalse(FileManager.default.fileExists(atPath: candidate.joined.audioPath), "The candidate is discarded")
        let segmentPaths = segments.compactMap(\.audioPath)
        XCTAssertEqual(segmentPaths.count, 3)
        XCTAssertTrue(segmentPaths.allSatisfy { FileManager.default.fileExists(atPath: $0) }, "Saved takes stay for Resume")
        XCTAssertTrue(try rows(f, role: "joined").isEmpty)
        XCTAssertEqual(try rows(f, role: "segment").count, 3)
    }

    // MARK: - Regeneration

    func testRegeneratingASegmentRecordsItsLineageAndSupersedesTheJoinedRow() async throws {
        let f = try makeFixture()
        let coordinator = f.makeCoordinator()
        coordinator.start(request: f.request, ttsEngine: f.store, audioPlayer: f.player, studioCoordinator: f.studio)
        await waitUntil("the project to finish") { !coordinator.isProcessing }
        guard case .completed(let original, let originalJoinedPath, _) = coordinator.outcome else {
            return XCTFail("Expected a completed project, got \(String(describing: coordinator.outcome))")
        }

        coordinator.regenerateSegment(index: 1, ttsEngine: f.store, audioPlayer: f.player, studioCoordinator: f.studio)
        XCTAssertTrue(coordinator.isRegeneratingSegment)
        await waitUntil("the replacement to finish") { !coordinator.isProcessing }
        XCTAssertFalse(coordinator.isRegeneratingSegment)

        guard case .completed(let segments, let joinedAudioPath, _) = coordinator.outcome else {
            return XCTFail("Expected the replaced project, got \(String(describing: coordinator.outcome))")
        }
        XCTAssertEqual(f.engine.takeRequests.count, 4, "Only the chosen segment is regenerated")
        let replacementTake = try XCTUnwrap(f.engine.takeRequests.last)
        XCTAssertEqual(replacementTake.text, f.request.lines[1])
        XCTAssertEqual(segments[0], original[0])
        XCTAssertEqual(segments[2], original[2])
        XCTAssertEqual(segments[1].audioPath, replacementTake.outputPath)
        XCTAssertNotEqual(joinedAudioPath, originalJoinedPath)

        // Replacement lineage: revision 2 on a fresh, recorded seed.
        XCTAssertEqual(coordinator.replacements.count, 1)
        let replacement = try XCTUnwrap(coordinator.replacements.first)
        XCTAssertEqual(replacement.segmentID, f.plan.segments[1].segmentID)
        XCTAssertEqual(replacement.revision, 2)
        XCTAssertTrue(replacement.qcPassed)
        XCTAssertEqual(replacementTake.seed, replacement.effectiveSeed)
        XCTAssertEqual(segments[1].historyRecord?.seed, Int64(bitPattern: replacement.effectiveSeed))
        let candidate = try XCTUnwrap(f.services.acceptanceCandidates.last)
        XCTAssertEqual(candidate.manifest.replacements, [replacement])
        XCTAssertEqual(try Data(contentsOf: candidate.manifestURL), try candidate.manifest.canonicalJSONData())

        // The new joined row supersedes the old one; the replaced take stays in History.
        XCTAssertEqual(try rows(f, role: "joined").map(\.audioPath), [joinedAudioPath])
        XCTAssertEqual(try rows(f, role: "superseded").map(\.audioPath), [originalJoinedPath])
        XCTAssertEqual(try rows(f, role: "segment").count, 4)
        let replacedTakePath = try XCTUnwrap(original[1].audioPath)
        XCTAssertTrue(try rows(f, role: "segment").map(\.audioPath).contains(replacedTakePath))
        XCTAssertTrue(FileManager.default.fileExists(atPath: replacedTakePath), "History still references the replaced take")
        XCTAssertTrue(FileManager.default.fileExists(atPath: originalJoinedPath))
        XCTAssertEqual(f.hooks.acceptedJoinedPaths, [originalJoinedPath, joinedAudioPath])
        XCTAssertEqual(f.studio.lastCompletedOutput?.audioURL.path, joinedAudioPath)
        XCTAssertTrue(coordinator.canRegenerateSegments)
    }
}
