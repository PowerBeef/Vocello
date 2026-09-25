import Foundation
import QwenVoiceCore
import XCTest

private struct CoordinatorFixtureBarrierFailure: LocalizedError {
    var errorDescription: String? { "fixture barrier failure" }
}

/// PA-19: the attempt-scoped Studio lifecycle both apps render. The pure
/// transitions are pinned by `StudioGenerationAttemptAuthorityTests`; these tests
/// hold the observable coordinator itself: what each transition publishes, which
/// stale or overlapping callbacks it rejects, and when it cancels the retained task.
@MainActor
final class StudioGenerationCoordinatorTests: XCTestCase {
    private func liveItem(_ transcript: String = "Live take") -> IOSStudioLivePreviewItem {
        IOSStudioLivePreviewItem(
            voiceName: "Aiden",
            modeLabel: "Built-in Voice",
            mode: .custom,
            transcript: transcript,
            waveformSeed: 7,
            estimatedAudioDuration: 2
        )
    }

    private func completedItem(_ name: String = "take") -> IOSStudioInlinePlayerItem {
        IOSStudioInlinePlayerItem(
            generationID: UUID(),
            audioURL: URL(fileURLWithPath: "/nonexistent/pa19-\(name).wav"),
            voiceName: "Aiden",
            modeLabel: "Built-in Voice",
            mode: .custom,
            transcript: "Completed take",
            waveformSeed: 7,
            autoplay: false
        )
    }

    /// A task that only ends when cancelled, standing in for the generation task.
    private func pendingTask() -> Task<Void, Never> {
        Task {
            try? await Task.sleep(nanoseconds: 60_000_000_000)
        }
    }

    func testStartPublishesARunningAttemptAndClearsThePreviousOutcome() throws {
        let coordinator = StudioGenerationCoordinator(mode: .custom)
        XCTAssertFalse(coordinator.isGenerating)
        XCTAssertNil(coordinator.activeAttempt)
        XCTAssertFalse(coordinator.isAttemptRunning)

        let failed = try XCTUnwrap(coordinator.start())
        XCTAssertTrue(coordinator.fail("The take failed.", attempt: failed))
        coordinator.recordBackgroundInterruption(.singleTakeDiscarded)
        coordinator.presentBackgroundInterruptionNoticeIfPending()
        XCTAssertEqual(coordinator.errorMessage, "The take failed.")
        XCTAssertEqual(coordinator.backgroundInterruptionNotice, .singleTakeDiscarded)

        let live = liveItem()
        let attempt = try XCTUnwrap(coordinator.start(live: live))
        XCTAssertNotEqual(attempt, failed)
        XCTAssertEqual(coordinator.activeAttempt, attempt)
        XCTAssertTrue(coordinator.isGenerating)
        XCTAssertTrue(coordinator.isAttemptRunning)
        XCTAssertEqual(coordinator.liveItem, live)
        XCTAssertNil(coordinator.errorMessage, "A fresh attempt clears the previous error")
        XCTAssertNil(coordinator.backgroundInterruptionNotice)
        XCTAssertNil(coordinator.lastCompletedOutput)
    }

    func testOverlappingStartIsRejectedWithoutDisturbingTheCurrentAttempt() throws {
        let coordinator = StudioGenerationCoordinator(mode: .design)
        let attempt = try XCTUnwrap(coordinator.start(live: liveItem("first")))

        XCTAssertNil(coordinator.start(live: liveItem("second")))
        XCTAssertEqual(coordinator.activeAttempt, attempt)
        XCTAssertEqual(coordinator.liveItem?.transcript, "first")
        coordinator.rejectStart("Validation failed.")
        XCTAssertNil(coordinator.errorMessage, "A validation error cannot overwrite a running attempt")
    }

    func testCompletionSurfacesTheTakeOnlyForTheCurrentRunningAttempt() throws {
        let coordinator = StudioGenerationCoordinator(mode: .custom)
        let attempt = try XCTUnwrap(coordinator.start(live: liveItem()))
        let item = completedItem()

        XCTAssertFalse(coordinator.complete(item, attempt: StudioGenerationAttemptToken()), "A stale token is rejected")
        XCTAssertTrue(coordinator.isGenerating)

        XCTAssertTrue(coordinator.complete(item, attempt: attempt))
        XCTAssertEqual(coordinator.lastCompletedOutput, item)
        XCTAssertFalse(coordinator.isGenerating)
        XCTAssertNil(coordinator.liveItem)
        XCTAssertNil(coordinator.generationTask)
        XCTAssertNil(coordinator.activeAttempt)

        XCTAssertFalse(coordinator.complete(completedItem("late"), attempt: attempt), "A duplicate terminal is rejected")
        XCTAssertFalse(coordinator.fail("late failure", attempt: attempt))
        XCTAssertEqual(coordinator.lastCompletedOutput, item)
        XCTAssertNil(coordinator.errorMessage)

        coordinator.dismissInlinePlayer()
        XCTAssertNil(coordinator.lastCompletedOutput)
    }

    func testTaskInstalledForAnAttemptThatIsNoLongerRunningIsCancelled() throws {
        let coordinator = StudioGenerationCoordinator(mode: .clone)
        let finished = try XCTUnwrap(coordinator.start())
        XCTAssertTrue(coordinator.finish(attempt: finished))

        let late = pendingTask()
        coordinator.installGenerationTask(late, for: finished)
        XCTAssertTrue(late.isCancelled, "A task that lost the race with the terminal transition is cancelled")
        XCTAssertNil(coordinator.generationTask)

        let attempt = try XCTUnwrap(coordinator.start())
        let task = pendingTask()
        defer { task.cancel() }
        coordinator.installGenerationTask(task, for: attempt)
        XCTAssertFalse(task.isCancelled)
        XCTAssertNotNil(coordinator.generationTask)
        XCTAssertTrue(coordinator.finish(attempt: attempt))
        XCTAssertNil(coordinator.generationTask)
    }

    func testUserCancellationCancelsTheTaskButStaysNonTerminalUntilTheBarrierReturns() throws {
        let coordinator = StudioGenerationCoordinator(mode: .custom)
        let attempt = try XCTUnwrap(coordinator.start(live: liveItem()))
        let task = pendingTask()
        coordinator.installGenerationTask(task, for: attempt)

        XCTAssertEqual(coordinator.requestCancellation(), attempt)
        XCTAssertTrue(task.isCancelled)
        XCTAssertTrue(coordinator.isGenerating, "The coordinator waits for the engine barrier")
        XCTAssertFalse(coordinator.isAttemptRunning)
        XCTAssertTrue(coordinator.isCancellationRequested(for: attempt))
        XCTAssertNil(coordinator.requestCancellation(), "A duplicate cancellation is rejected")

        // The finishing take cannot race the pending barrier into a terminal state.
        XCTAssertFalse(coordinator.complete(completedItem(), attempt: attempt))
        XCTAssertFalse(coordinator.finish(attempt: attempt))
        XCTAssertFalse(coordinator.fail("late failure", attempt: attempt))
        XCTAssertFalse(coordinator.updateLiveItem(liveItem("late"), attempt: attempt))
        XCTAssertTrue(coordinator.isGenerating)

        XCTAssertTrue(coordinator.completeCancellation(attempt: attempt))
        XCTAssertFalse(coordinator.isGenerating)
        XCTAssertNil(coordinator.activeAttempt)
        XCTAssertNil(coordinator.liveItem)
        XCTAssertNil(coordinator.errorMessage)
        XCTAssertNil(coordinator.lastCompletedOutput, "A cancelled take never surfaces a result")
        XCTAssertFalse(coordinator.isCancellationRequested(for: attempt))
        XCTAssertFalse(coordinator.completeCancellation(attempt: attempt))
    }

    func testTypedCancellationDefersTaskCancellationUntilTheBarrierReturned() throws {
        let coordinator = StudioGenerationCoordinator(mode: .design)
        let attempt = try XCTUnwrap(coordinator.start())
        let task = pendingTask()
        coordinator.installGenerationTask(task, for: attempt)

        XCTAssertEqual(coordinator.requestCancellation(cancelsTask: false), attempt)
        XCTAssertFalse(task.isCancelled, "A non-user reason reaches the engine barrier first")
        coordinator.cancelGenerationTask()
        XCTAssertTrue(task.isCancelled)
        XCTAssertTrue(coordinator.completeCancellation(attempt: attempt))
    }

    func testFailedCancellationBarrierExplainsItselfAndDropsThePendingNotice() throws {
        let coordinator = StudioGenerationCoordinator(mode: .clone)
        let attempt = try XCTUnwrap(coordinator.start())
        let failure = CoordinatorFixtureBarrierFailure()

        XCTAssertFalse(coordinator.failCancellation(failure, attempt: attempt), "Only a pending cancellation can fail")
        coordinator.recordBackgroundInterruption(.singleTakeDiscarded)
        XCTAssertEqual(coordinator.requestCancellation(), attempt)

        XCTAssertTrue(coordinator.failCancellation(failure, attempt: attempt))
        XCTAssertEqual(
            coordinator.errorMessage,
            IOSAppLanguage.shared.presentation.cancellationCouldNotFinish(details: failure.localizedDescription)
        )
        XCTAssertFalse(coordinator.isGenerating)
        coordinator.presentBackgroundInterruptionNoticeIfPending()
        XCTAssertNil(
            coordinator.backgroundInterruptionNotice,
            "A notice claiming the work stopped cleanly would contradict the error"
        )
    }

    func testLiveItemUpdatesApplyOnlyToTheRunningAttempt() throws {
        let coordinator = StudioGenerationCoordinator(mode: .custom)
        let attempt = try XCTUnwrap(coordinator.start(live: liveItem("segment 1")))

        XCTAssertTrue(coordinator.updateLiveItem(liveItem("segment 2"), attempt: attempt))
        XCTAssertEqual(coordinator.liveItem?.transcript, "segment 2")
        XCTAssertFalse(coordinator.updateLiveItem(liveItem("stale"), attempt: StudioGenerationAttemptToken()))
        XCTAssertTrue(coordinator.updateLiveItem(nil, attempt: attempt))
        XCTAssertNil(coordinator.liveItem)
    }

    func testRejectedStartSurfacesItsMessageOnlyWhileIdle() throws {
        let coordinator = StudioGenerationCoordinator(mode: .custom)
        coordinator.rejectStart("Type a script first.")
        XCTAssertEqual(coordinator.errorMessage, "Type a script first.")
        XCTAssertFalse(coordinator.isGenerating)

        let attempt = try XCTUnwrap(coordinator.start())
        XCTAssertNil(coordinator.errorMessage)
        XCTAssertTrue(coordinator.fail("Engine failure.", attempt: attempt))
        XCTAssertEqual(coordinator.errorMessage, "Engine failure.")
        XCTAssertFalse(coordinator.isGenerating)
    }

    func testForegroundExitNoticeAppearsOnlyAfterReturnAndUntilDismissed() {
        let coordinator = StudioGenerationCoordinator(mode: .design)

        coordinator.recordBackgroundInterruption(.longFormStopped)
        XCTAssertNil(coordinator.backgroundInterruptionNotice, "Hidden while the app is away")
        XCTAssertNil(coordinator.backgroundInterruptionNoticeMessage)

        coordinator.presentBackgroundInterruptionNoticeIfPending()
        XCTAssertEqual(coordinator.backgroundInterruptionNotice, .longFormStopped)
        XCTAssertEqual(
            coordinator.backgroundInterruptionNoticeMessage,
            IOSAppLanguage.shared.presentation.backgroundLongFormStopped
        )

        coordinator.dismissBackgroundInterruptionNotice()
        XCTAssertNil(coordinator.backgroundInterruptionNotice)
        coordinator.presentBackgroundInterruptionNoticeIfPending()
        XCTAssertNil(coordinator.backgroundInterruptionNotice, "A dismissed notice does not come back")

        coordinator.recordBackgroundInterruption(.singleTakeDiscarded)
        coordinator.presentBackgroundInterruptionNoticeIfPending()
        XCTAssertEqual(
            coordinator.backgroundInterruptionNoticeMessage,
            IOSAppLanguage.shared.presentation.backgroundTakeStopped
        )
    }
}
