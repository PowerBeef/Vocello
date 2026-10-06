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

    /// A1-01: a Stop that arrives while the finished take is being saved is refused,
    /// so the attempt completes with its card instead of announcing a stop.
    func testAFinalizingAttemptRefusesCancellationAndCompletesWithItsTake() throws {
        let coordinator = StudioGenerationCoordinator(mode: .custom)
        let attempt = try XCTUnwrap(coordinator.start(live: liveItem()))

        XCTAssertTrue(coordinator.beginFinalization(attempt: attempt))
        XCTAssertFalse(coordinator.isAttemptRunning)
        XCTAssertNil(coordinator.requestCancellation(), "The take exists; it can no longer be stopped")
        XCTAssertFalse(coordinator.isCancellationRequested(for: attempt))
        XCTAssertTrue(coordinator.isGenerating)

        let item = completedItem()
        XCTAssertTrue(coordinator.complete(item, attempt: attempt))
        XCTAssertEqual(coordinator.lastCompletedOutput, item)
        XCTAssertFalse(coordinator.isGenerating)

        // A cancellation accepted first keeps the terminal: finalization is refused.
        let second = try XCTUnwrap(coordinator.start())
        XCTAssertEqual(coordinator.requestCancellation(), second)
        XCTAssertFalse(coordinator.beginFinalization(attempt: second))
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

    // MARK: - Design save candidate (A10-01)

    /// The take's own audio, script and brief stay offered as a saved voice
    /// only while the draft still asks for that take; once saved it is no
    /// longer offered.
    func testTheDesignSaveCandidateMatchesOnlyItsOwnTakeUntilSaved() {
        var candidate = VoiceDesignSavedVoiceCandidate(
            audioPath: "/nonexistent/design-take.wav",
            transcript: "A quiet morning by the harbor.",
            voiceDescription: "A warm, mature narrator.",
            emotion: "Speak calmly.",
            text: "A quiet morning by the harbor."
        )
        XCTAssertTrue(candidate.matches(
            voiceDescription: "A warm, mature narrator.",
            emotion: "Speak calmly.",
            text: "A quiet morning by the harbor."
        ))
        XCTAssertFalse(candidate.matches(
            voiceDescription: "A warm, mature narrator.",
            emotion: "Speak calmly.",
            text: "An edited script."
        ), "A script edited after the take never pairs the old audio with new text")
        XCTAssertFalse(candidate.matches(
            voiceDescription: "A bright young voice.",
            emotion: "Speak calmly.",
            text: "A quiet morning by the harbor."
        ))
        XCTAssertFalse(candidate.matches(
            voiceDescription: "A warm, mature narrator.",
            emotion: "Speak with urgency.",
            text: "A quiet morning by the harbor."
        ))

        XCTAssertFalse(candidate.isSaved)
        candidate.markSaved(as: "Warm Narrator")
        XCTAssertTrue(candidate.isSaved)
        XCTAssertEqual(candidate.savedVoiceName, "Warm Narrator")
    }

    // MARK: - Mode switching (A10-02)

    /// While a take runs, is cancelling or is being saved, only its own mode
    /// may be selected, from the capsule selector or any programmatic route;
    /// once it is terminal every mode is free again.
    func testOnlyTheBusyModeCanBeSelectedWhileItsAttemptLasts() throws {
        let custom = StudioGenerationCoordinator(mode: .custom)
        let design = StudioGenerationCoordinator(mode: .design)
        let clone = StudioGenerationCoordinator(mode: .clone)
        let coordinators = [custom, design, clone]
        func busyMode() -> GenerationMode? {
            StudioModeSwitchPolicy.busyMode(coordinators: coordinators, longFormMode: nil)
        }
        func allows(_ target: GenerationMode, from current: GenerationMode) -> Bool {
            StudioModeSwitchPolicy.allows(switchingTo: target, from: current, busyMode: busyMode())
        }

        XCTAssertNil(busyMode())
        XCTAssertTrue(allows(.clone, from: .design))

        let attempt = try XCTUnwrap(design.start())
        XCTAssertEqual(busyMode(), .design)
        XCTAssertFalse(allows(.clone, from: .design), "A Voices tap cannot leave a running take")
        XCTAssertFalse(allows(.custom, from: .design))
        XCTAssertTrue(allows(.design, from: .design))
        XCTAssertTrue(allows(.design, from: .clone), "Returning to the running take stays possible")

        XCTAssertTrue(design.beginFinalization(attempt: attempt))
        XCTAssertFalse(allows(.clone, from: .design), "A take being saved still owns the Studio")
        XCTAssertTrue(design.complete(completedItem(), attempt: attempt))
        XCTAssertNil(busyMode())
        XCTAssertTrue(allows(.clone, from: .design))

        let cancelled = try XCTUnwrap(clone.start())
        XCTAssertNotNil(clone.requestCancellation())
        XCTAssertFalse(allows(.custom, from: .clone), "A pending cancellation barrier still owns the Studio")
        XCTAssertTrue(clone.completeCancellation(attempt: cancelled))
        XCTAssertTrue(allows(.custom, from: .clone))
    }

    func testARunningLongFormProjectOwnsTheStudioMode() {
        let coordinators = [StudioGenerationCoordinator(mode: .custom)]
        let busy = StudioModeSwitchPolicy.busyMode(coordinators: coordinators, longFormMode: .clone)
        XCTAssertEqual(busy, .clone)
        XCTAssertFalse(StudioModeSwitchPolicy.allows(switchingTo: .custom, from: .clone, busyMode: busy))
        XCTAssertTrue(StudioModeSwitchPolicy.allows(switchingTo: .clone, from: .custom, busyMode: busy))
    }
}
