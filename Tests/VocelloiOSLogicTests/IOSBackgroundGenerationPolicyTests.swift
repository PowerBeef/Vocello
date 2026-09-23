import Foundation
import QwenVoiceCore
import XCTest

/// PA-15: leaving the foreground cancels generation safely. The app-only scene
/// handler and `AppModel` apply these decisions; the physical-device proof that
/// the cancel lands before GPU work is refused is a separate, consent-bound lane.
final class IOSBackgroundGenerationPolicyTests: XCTestCase {
    // MARK: - Background transition

    func testBackgroundWithoutActiveGenerationOnlyReleasesTheRuntime() {
        let plan = IOSBackgroundGenerationPolicy.backgroundPlan(
            hasActiveGeneration: false,
            studioWork: .idle
        )

        XCTAssertFalse(plan.requestsBackgroundTime)
        XCTAssertNil(plan.studioInterruption)
        XCTAssertFalse(plan.cancelsUnownedEngineGeneration)
        XCTAssertEqual(plan.releaseReason, "background")
    }

    func testBackgroundWithSingleTakeRequestsTimeAndDiscardsTheTakeAsShutdown() {
        let plan = IOSBackgroundGenerationPolicy.backgroundPlan(
            hasActiveGeneration: true,
            studioWork: .singleTake
        )

        XCTAssertTrue(plan.requestsBackgroundTime)
        XCTAssertEqual(plan.studioInterruption, .singleTakeDiscarded)
        XCTAssertFalse(
            plan.cancelsUnownedEngineGeneration,
            "The Studio attempt owns the cancel, so the engine barrier runs first, then its task is cancelled and reports .cancelled"
        )
        XCTAssertEqual(plan.cancellationReason, .shutdown)
        XCTAssertEqual(plan.releaseReason, IOSBackgroundGenerationPolicy.releaseReason)
    }

    func testBackgroundWithLongFormStopsTheProjectAndKeepsItsSegments() {
        let plan = IOSBackgroundGenerationPolicy.backgroundPlan(
            hasActiveGeneration: true,
            studioWork: .longForm
        )

        XCTAssertTrue(plan.requestsBackgroundTime)
        XCTAssertEqual(plan.studioInterruption, .longFormStopped)
        XCTAssertFalse(plan.cancelsUnownedEngineGeneration)
        XCTAssertEqual(plan.cancellationReason, .shutdown)
    }

    func testStudioAttemptBeforeEngineAdmissionIsStillCancelled() {
        // Clone preparation or model admission runs before the engine reports
        // an active generation; the attempt must not survive into suspension.
        let plan = IOSBackgroundGenerationPolicy.backgroundPlan(
            hasActiveGeneration: false,
            studioWork: .singleTake
        )

        XCTAssertTrue(plan.requestsBackgroundTime)
        XCTAssertEqual(plan.studioInterruption, .singleTakeDiscarded)
        XCTAssertFalse(plan.cancelsUnownedEngineGeneration)
    }

    func testEngineGenerationWithoutStudioOwnerIsCancelledDirectly() {
        let plan = IOSBackgroundGenerationPolicy.backgroundPlan(
            hasActiveGeneration: true,
            studioWork: .idle
        )

        XCTAssertTrue(plan.requestsBackgroundTime)
        XCTAssertNil(plan.studioInterruption, "No Studio attempt means no Studio notice")
        XCTAssertTrue(plan.cancelsUnownedEngineGeneration)
        XCTAssertEqual(plan.cancellationReason, .shutdown)
    }

    func testPendingStudioCancellationIsAwaitedNotRepeated() {
        let plan = IOSBackgroundGenerationPolicy.backgroundPlan(
            hasActiveGeneration: true,
            studioWork: .cancelling
        )

        XCTAssertTrue(plan.requestsBackgroundTime)
        XCTAssertNil(plan.studioInterruption)
        XCTAssertFalse(plan.cancelsUnownedEngineGeneration)
    }

    func testSegmentRegenerationIsAnnouncedAsADiscardedTake() {
        // A cancelled regeneration restores the completed project, so there is
        // no Resume project to point at; the new take is what was discarded.
        let plan = IOSBackgroundGenerationPolicy.backgroundPlan(
            hasActiveGeneration: true,
            studioWork: .segmentRegeneration
        )

        XCTAssertTrue(plan.requestsBackgroundTime)
        XCTAssertEqual(plan.studioInterruption, .singleTakeDiscarded)
        XCTAssertFalse(plan.cancelsUnownedEngineGeneration)
        XCTAssertEqual(plan.cancellationReason, .shutdown)
    }

    // MARK: - Cancellation order

    func testTypedNonUserReasonsReachTheEngineBarrierBeforeTheSwiftTaskIsCancelled() {
        XCTAssertEqual(IOSStudioCancellationOrder.forReason(.user), .taskThenBarrier)
        XCTAssertEqual(IOSStudioCancellationOrder.forReason(.shutdown), .barrierThenTask)
        XCTAssertEqual(IOSStudioCancellationOrder.forReason(.memoryPressure), .barrierThenTask)
        XCTAssertEqual(IOSStudioCancellationOrder.forReason(.superseded), .barrierThenTask)
    }

    // MARK: - Foreground exit sequencing and background-time grant

    @MainActor
    func testReleaseIsRequestedExplicitlyAfterTheBarrierReturns() {
        var exitState = IOSForegroundExitState()
        let release = RuntimeReleaseCoordinator()
        let reason = IOSBackgroundGenerationPolicy.releaseReason

        let epoch = exitState.enterBackground()
        XCTAssertTrue(exitState.awaitsBarrier)
        XCTAssertFalse(
            exitState.endsBackgroundTime(followUpReleaseExecutes: false, pendingReleaseReason: nil),
            "The grant must outlive the barrier: the release is not requested yet"
        )

        // The barrier returned and the engine is idle: the release executes now
        // instead of waiting for a `hasActiveGeneration` emission.
        XCTAssertTrue(exitState.barrierReturned(for: epoch))
        XCTAssertEqual(
            release.requestRelease(reason: reason, hasActiveGeneration: false),
            .execute(reason: reason, wasDeferred: false)
        )
        let followUp = release.completeRelease(hasActiveGeneration: false)
        XCTAssertEqual(followUp, .none)
        XCTAssertTrue(
            exitState.endsBackgroundTime(
                followUpReleaseExecutes: false,
                pendingReleaseReason: release.pendingReason
            )
        )
    }

    func testReturningBeforeTheBarrierSkipsTheRelease() {
        var exitState = IOSForegroundExitState()
        let epoch = exitState.enterBackground()

        exitState.returnToForeground()

        XCTAssertFalse(exitState.barrierReturned(for: epoch))
        XCTAssertFalse(exitState.isBackgrounded)
    }

    func testAnEarlierReleaseNeverEndsANewerGrant() {
        var exitState = IOSForegroundExitState()
        let first = exitState.enterBackground()
        XCTAssertTrue(exitState.barrierReturned(for: first))
        exitState.returnToForeground()

        // A second exit is still waiting on its barrier when the first exit's
        // release completes.
        let second = exitState.enterBackground()
        XCTAssertFalse(exitState.barrierReturned(for: first), "A superseded exit never requests a release")
        XCTAssertFalse(exitState.endsBackgroundTime(followUpReleaseExecutes: false, pendingReleaseReason: nil))

        XCTAssertTrue(exitState.barrierReturned(for: second))
        XCTAssertFalse(
            exitState.endsBackgroundTime(
                followUpReleaseExecutes: false,
                pendingReleaseReason: IOSBackgroundGenerationPolicy.releaseReason
            ),
            "A foreground-exit release is still pending"
        )
        XCTAssertFalse(
            exitState.endsBackgroundTime(followUpReleaseExecutes: true, pendingReleaseReason: nil),
            "A queued follow-up release is still to run"
        )
        XCTAssertTrue(exitState.endsBackgroundTime(followUpReleaseExecutes: false, pendingReleaseReason: nil))
    }

    @MainActor
    func testDeferredReleaseRunsFromTheEmittedIdleValue() {
        // `@Published` emits before the property is written: the sink passes the
        // emitted `false`, so a release deferred behind the generation runs.
        let release = RuntimeReleaseCoordinator()
        let reason = IOSBackgroundGenerationPolicy.releaseReason
        XCTAssertEqual(
            release.requestRelease(reason: reason, hasActiveGeneration: true),
            .deferred(reason: reason)
        )
        let emittedHasActiveGeneration = false
        XCTAssertEqual(
            release.executeDeferredReleaseIfReady(hasActiveGeneration: emittedHasActiveGeneration),
            .execute(reason: reason, wasDeferred: true)
        )
    }

    // MARK: - Screen awake while generating

    func testIdleTimerFollowsGenerationActivity() {
        var hold = IOSGenerationScreenAwakeHold()

        XCTAssertNil(hold.update(isGenerating: false, idleTimerDisabled: false))
        XCTAssertEqual(hold.update(isGenerating: true, idleTimerDisabled: false), true)
        XCTAssertTrue(hold.ownsIdleTimerHold)
        XCTAssertNil(hold.update(isGenerating: true, idleTimerDisabled: true), "Already held")
        XCTAssertEqual(hold.update(isGenerating: false, idleTimerDisabled: true), false)
        XCTAssertFalse(hold.ownsIdleTimerHold)
        XCTAssertNil(hold.update(isGenerating: false, idleTimerDisabled: false))
    }

    func testIdleTimerHoldPlacedByAnotherOwnerIsNeverReleased() {
        // The headless diagnostics runner disables the idle timer for its whole
        // run; generations inside it must not re-enable auto-lock.
        var hold = IOSGenerationScreenAwakeHold()

        XCTAssertNil(hold.update(isGenerating: true, idleTimerDisabled: true))
        XCTAssertFalse(hold.ownsIdleTimerHold)
        XCTAssertNil(hold.update(isGenerating: false, idleTimerDisabled: true))
    }

    // MARK: - Deferred release across the round trip

    @MainActor
    func testReturningToForegroundCancelsTheDeferredBackgroundRelease() {
        let coordinator = RuntimeReleaseCoordinator()
        let reason = IOSBackgroundGenerationPolicy.releaseReason

        XCTAssertEqual(
            coordinator.requestRelease(reason: reason, hasActiveGeneration: true),
            .deferred(reason: reason)
        )
        XCTAssertTrue(coordinator.cancelPendingRelease(reason: reason))
        XCTAssertNil(coordinator.pendingReason)
        // The cancellation barrier returns after the user is back: nothing fires.
        XCTAssertEqual(coordinator.executeDeferredReleaseIfReady(hasActiveGeneration: false), .none)
        XCTAssertFalse(coordinator.cancelPendingRelease(reason: reason))
    }

    @MainActor
    func testDeferredBackgroundReleaseRunsOnceTheBarrierReturnsWhileBackgrounded() {
        let coordinator = RuntimeReleaseCoordinator()
        let reason = IOSBackgroundGenerationPolicy.releaseReason

        XCTAssertEqual(
            coordinator.requestRelease(reason: reason, hasActiveGeneration: true),
            .deferred(reason: reason)
        )
        XCTAssertEqual(coordinator.executeDeferredReleaseIfReady(hasActiveGeneration: true), .none)
        XCTAssertEqual(
            coordinator.executeDeferredReleaseIfReady(hasActiveGeneration: false),
            .execute(reason: reason, wasDeferred: true)
        )
        XCTAssertEqual(coordinator.completeRelease(hasActiveGeneration: false), .none)
    }

    @MainActor
    func testCancellingThePendingBackgroundReleaseKeepsOtherReasons() {
        let coordinator = RuntimeReleaseCoordinator()

        XCTAssertEqual(
            coordinator.requestRelease(reason: "other", hasActiveGeneration: true),
            .deferred(reason: "other")
        )
        XCTAssertFalse(coordinator.cancelPendingRelease(reason: IOSBackgroundGenerationPolicy.releaseReason))
        XCTAssertEqual(coordinator.pendingReason, "other")
    }

    // MARK: - Notice on return

    func testNoticeIsRecordedInBackgroundAndShownOnlyOnReturn() {
        var notice = IOSBackgroundInterruptionNoticeState()

        notice.record(.singleTakeDiscarded)
        XCTAssertNil(notice.presented, "Nothing is shown while the app is in the background")
        XCTAssertEqual(notice.pending, .singleTakeDiscarded)

        notice.presentOnReturn()
        XCTAssertEqual(notice.presented, .singleTakeDiscarded)
        XCTAssertNil(notice.pending)

        // A second activation without a new interruption keeps the same notice.
        notice.presentOnReturn()
        XCTAssertEqual(notice.presented, .singleTakeDiscarded)

        notice.clear()
        XCTAssertEqual(notice, IOSBackgroundInterruptionNoticeState())
    }

    func testReturnWithoutInterruptionShowsNothing() {
        var notice = IOSBackgroundInterruptionNoticeState()
        notice.presentOnReturn()
        XCTAssertNil(notice.presented)
    }

    func testNewInterruptionReplacesAnUnacknowledgedNotice() {
        var notice = IOSBackgroundInterruptionNoticeState()
        notice.record(.singleTakeDiscarded)
        notice.presentOnReturn()

        notice.record(.longFormStopped)
        XCTAssertNil(notice.presented)
        notice.presentOnReturn()
        XCTAssertEqual(notice.presented, .longFormStopped)
    }

    func testNoticeCopyUsesTheCatalogEnglishSource() {
        XCTAssertEqual(
            VocelloPresentationText.backgroundTakeStopped,
            "Generation stopped when Vocello left the screen. The unfinished take was discarded."
        )
        XCTAssertEqual(
            VocelloPresentationText.backgroundLongFormStopped,
            "Long-form stopped when Vocello left the screen. Finished segments are kept; choose Resume project to continue."
        )
    }
}
