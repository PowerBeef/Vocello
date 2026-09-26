import Foundation
import QwenVoiceCore
import XCTest

/// MAC-20: a model deletion never removes files the engine is using. A take, a
/// line batch or long-form project between two takes, or a load, warm or prime
/// blocks it; the weights are released first when the model is loaded; a
/// refused unload keeps the files; and the engine is read again after every
/// await, so a take or warm that starts meanwhile keeps the files too.
@MainActor
final class MacModelDeletionSequenceTests: XCTestCase {
    private struct UnloadRefused: Error {}

    private let modelID = "pro_custom_speed"

    // MARK: - An idle engine

    func testAnIdleEngineWithAnotherModelLoadedDeletesWithoutAnUnload() async {
        let engine = FakeDeletionEngine(loadedModelID: "pro_design_speed")

        let outcome = await run(engine: engine)

        XCTAssertEqual(outcome, .deleted)
        XCTAssertEqual(engine.log, ["stopDownloads", "removeFiles"])
        XCTAssertFalse(outcome.showsEngineBusyAlert)
    }

    func testTheLoadedModelIsUnloadedBeforeItsFilesGo() async {
        let engine = FakeDeletionEngine(loadedModelID: modelID)

        let outcome = await run(engine: engine)

        XCTAssertEqual(outcome, .deleted)
        XCTAssertEqual(engine.log, ["unload", "stopDownloads", "removeFiles"])
    }

    func testWithoutAnEngineTheFilesAreRemoved() async {
        var removed = false
        let outcome = await MacModelDeletionSequence.run(
            modelID: modelID,
            engine: nil,
            stopDownloads: {},
            removeFiles: { removed = true; return true }
        )

        XCTAssertEqual(outcome, .deleted)
        XCTAssertTrue(removed)
    }

    // MARK: - A busy engine changes nothing

    func testARunningTakeBlocksBeforeAnythingChanges() async {
        let engine = FakeDeletionEngine(loadedModelID: modelID)
        engine.hasActiveGeneration = true

        let outcome = await run(engine: engine)

        XCTAssertEqual(outcome, .blockedByActiveGeneration)
        XCTAssertEqual(engine.log, [], "No unload, no download stop, no removal")
        XCTAssertTrue(outcome.showsEngineBusyAlert)
    }

    func testAMultiTakeRunBetweenTwoTakesBlocks() async {
        // A line batch or long-form project holds the sustained activity while
        // no take is generating (between segments, QC, History saves).
        let engine = FakeDeletionEngine(loadedModelID: modelID)
        engine.hasSustainedPerformanceActivity = true

        let outcome = await run(engine: engine)

        XCTAssertEqual(outcome, .blockedByActiveGeneration)
        XCTAssertEqual(engine.log, [])
    }

    func testAColdLoadThatNamesNoModelBlocks() async {
        // A Studio warm publishes `.starting`, whose model ID is nil.
        let engine = FakeDeletionEngine(loadedModelID: nil)
        engine.hasModelOperationInFlight = true

        let outcome = await run(engine: engine)

        XCTAssertEqual(outcome, .blockedByActiveGeneration)
        XCTAssertEqual(engine.log, [])
    }

    // MARK: - A refused unload keeps the files

    func testARefusedUnloadFailsAndKeepsTheFiles() async {
        let engine = FakeDeletionEngine(loadedModelID: modelID)
        engine.unloadError = UnloadRefused()
        var reported: (any Error)?

        let outcome = await MacModelDeletionSequence.run(
            modelID: modelID,
            engine: engine,
            stopDownloads: { engine.log.append("stopDownloads") },
            removeFiles: { engine.log.append("removeFiles"); return true },
            unloadFailed: { reported = $0 }
        )

        XCTAssertEqual(outcome, .failed(.engineRelease))
        XCTAssertEqual(engine.log, ["unload"], "The files and the download stay as they were")
        XCTAssertNotNil(reported as? UnloadRefused, "The refusal reaches the diagnostics hook")
        XCTAssertTrue(outcome.showsEngineBusyAlert, "The localized busy alert explains the refusal")
    }

    // MARK: - Every await is followed by a fresh read

    func testATakeThatStartsDuringTheUnloadKeepsTheFiles() async {
        let engine = FakeDeletionEngine(loadedModelID: modelID)
        engine.onUnload = { [weak engine] in engine?.hasActiveGeneration = true }

        let outcome = await run(engine: engine)

        XCTAssertEqual(outcome, .blockedByActiveGeneration)
        XCTAssertEqual(engine.log, ["unload"])
    }

    func testAWarmThatStartsWhileDownloadsStopKeepsTheFiles() async {
        let engine = FakeDeletionEngine(loadedModelID: nil)

        let outcome = await run(engine: engine) {
            engine.hasModelOperationInFlight = true
        }

        XCTAssertEqual(outcome, .blockedByActiveGeneration)
        XCTAssertEqual(engine.log, ["stopDownloads"], "Nothing is removed after the last read saw a warm")
    }

    func testAModelReloadedWhileDownloadsStopKeepsTheFiles() async {
        let engine = FakeDeletionEngine(loadedModelID: modelID)

        let outcome = await run(engine: engine) {
            engine.loadedModelID = self.modelID
        }

        XCTAssertEqual(outcome, .blockedByActiveGeneration)
        XCTAssertEqual(engine.log, ["unload", "stopDownloads"])
    }

    func testAMultiTakeRunThatStartsWhileDownloadsStopKeepsTheFiles() async {
        let engine = FakeDeletionEngine(loadedModelID: nil)

        let outcome = await run(engine: engine) {
            engine.hasSustainedPerformanceActivity = true
        }

        XCTAssertEqual(outcome, .blockedByActiveGeneration)
        XCTAssertEqual(engine.log, ["stopDownloads"])
    }

    // MARK: - Removal

    func testARemovalFailureIsReportedOnTheRowNotAsBusy() async {
        let engine = FakeDeletionEngine(loadedModelID: nil)

        let outcome = await MacModelDeletionSequence.run(
            modelID: modelID,
            engine: engine,
            stopDownloads: {},
            removeFiles: { false }
        )

        XCTAssertEqual(outcome, .failed(.fileRemoval))
        XCTAssertFalse(outcome.showsEngineBusyAlert)
    }

    // MARK: - The store's model-operation read

    func testTheStoreReadsLoadingWarmingAndPrimingAsAModelOperation() {
        func reads(_ state: EngineLoadState, _ phase: ClonePreparationPhase = .idle) -> Bool {
            MacModelDeletionSequence.showsModelOperation(loadState: state, clonePreparationPhase: phase)
        }
        XCTAssertTrue(reads(.starting), "A cold load names no model")
        XCTAssertTrue(reads(.running(modelID: modelID, label: nil, fraction: nil)))
        XCTAssertTrue(reads(.running(modelID: nil, label: nil, fraction: nil)))
        XCTAssertTrue(reads(.loaded(modelID: modelID), .preparing), "A clone reference being primed")
        XCTAssertFalse(reads(.idle))
        XCTAssertFalse(reads(.loaded(modelID: modelID)))
        XCTAssertFalse(reads(.loaded(modelID: modelID), .primed))
        XCTAssertFalse(reads(.failed(message: "load failed")))
    }

    // MARK: - Helpers

    private func run(
        engine: FakeDeletionEngine,
        whileStoppingDownloads: () -> Void = {}
    ) async -> MacModelDeletionSequence.Outcome {
        await MacModelDeletionSequence.run(
            modelID: modelID,
            engine: engine,
            stopDownloads: {
                engine.log.append("stopDownloads")
                whileStoppingDownloads()
            },
            removeFiles: {
                engine.log.append("removeFiles")
                return true
            }
        )
    }
}

@MainActor
private final class FakeDeletionEngine: MacModelEngineCoordinating {
    var hasActiveGeneration = false
    var hasSustainedPerformanceActivity = false
    var hasModelOperationInFlight = false
    var loadedModelID: String?
    var unloadError: (any Error)?
    /// Runs inside the unload, as a take or warm that starts meanwhile would.
    var onUnload: (() -> Void)?
    var log: [String] = []

    init(loadedModelID: String?) {
        self.loadedModelID = loadedModelID
    }

    func unloadModel() async throws {
        log.append("unload")
        if let unloadError { throw unloadError }
        loadedModelID = nil
        onUnload?()
    }
}
