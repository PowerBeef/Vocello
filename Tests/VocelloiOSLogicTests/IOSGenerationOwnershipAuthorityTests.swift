import XCTest

final class IOSGenerationOwnershipAuthorityTests: XCTestCase {
    /// (a) Both admission checks in `generate` refuse while a generation owns the scope, while the
    /// backend reports activity, or while a critical-memory action holds the runtime — including
    /// the re-check after the async admission snapshot, even if the published flag were stale.
    func testGenerationAdmissionIsRefusedWhileGeneratingOrReleasingMemory() {
        var authority = IOSGenerationOwnershipAuthority()
        XCTAssertTrue(authority.admitsGeneration(hasActiveGeneration: false))
        XCTAssertFalse(authority.admitsGeneration(hasActiveGeneration: true))

        authority.enterGeneration()
        XCTAssertFalse(authority.admitsGeneration(hasActiveGeneration: authority.ownsGenerationScope))
        XCTAssertEqual(authority.completeGeneration(), .released)
        XCTAssertTrue(authority.admitsGeneration(hasActiveGeneration: authority.ownsGenerationScope))

        XCTAssertTrue(authority.beginCriticalMemoryAction())
        XCTAssertFalse(authority.admitsGeneration(hasActiveGeneration: authority.ownsGenerationScope))
        XCTAssertFalse(authority.admitsGeneration(hasActiveGeneration: false))
        authority.completeCriticalMemoryAction()
        XCTAssertTrue(authority.admitsGeneration(hasActiveGeneration: authority.ownsGenerationScope))
    }

    /// (b, normal branch) Completion returns the scope and never underflows.
    func testGenerationCompletionReleasesScopeWithoutCriticalAction() {
        var authority = IOSGenerationOwnershipAuthority()
        authority.enterGeneration()
        XCTAssertTrue(authority.ownsGenerationScope)
        XCTAssertEqual(authority.completeGeneration(), .released)
        XCTAssertFalse(authority.ownsGenerationScope)
        XCTAssertEqual(authority.activeGenerationDepth, 0)
        XCTAssertEqual(authority.completeGeneration(), .released)
        XCTAssertEqual(authority.activeGenerationDepth, 0)
    }

    /// (b, critical branch) While a critical action is in flight, completion changes nothing:
    /// the owner must not stop the guard or clear ownership until the unload completes.
    func testGenerationCompletionLeavesScopeWithCriticalActionUntilUnloadCompletes() {
        var authority = IOSGenerationOwnershipAuthority()
        authority.enterGeneration()
        XCTAssertTrue(authority.beginCriticalMemoryAction())
        let held = authority

        XCTAssertEqual(authority.completeGeneration(), .retainedByCriticalMemoryAction)
        XCTAssertEqual(authority, held)
        XCTAssertTrue(authority.ownsGenerationScope)
        XCTAssertTrue(authority.criticalMemoryActionInFlight)
        XCTAssertFalse(authority.admitsGeneration(hasActiveGeneration: authority.ownsGenerationScope))

        authority.completeCriticalMemoryAction()
        XCTAssertEqual(authority, IOSGenerationOwnershipAuthority())
    }

    /// (c) Begin claims exactly one scope (never a second one, never resets a deeper one),
    /// refuses re-entry, and complete releases everything.
    func testCriticalMemoryActionClaimsExactlyOneScopeAndRefusesReentry() {
        var idle = IOSGenerationOwnershipAuthority()
        XCTAssertTrue(idle.beginCriticalMemoryAction())
        XCTAssertEqual(idle.activeGenerationDepth, 1)
        XCTAssertTrue(idle.ownsGenerationScope)
        XCTAssertTrue(idle.criticalMemoryActionInFlight)
        let claimed = idle
        XCTAssertFalse(idle.beginCriticalMemoryAction())
        XCTAssertEqual(idle, claimed)

        var generating = IOSGenerationOwnershipAuthority()
        generating.enterGeneration()
        XCTAssertTrue(generating.beginCriticalMemoryAction())
        XCTAssertEqual(generating.activeGenerationDepth, 1)
        generating.completeCriticalMemoryAction()
        XCTAssertEqual(generating.activeGenerationDepth, 0)
        XCTAssertFalse(generating.ownsGenerationScope)
        XCTAssertFalse(generating.criticalMemoryActionInFlight)

        var nested = IOSGenerationOwnershipAuthority()
        nested.enterGeneration()
        nested.enterGeneration()
        XCTAssertTrue(nested.beginCriticalMemoryAction())
        XCTAssertEqual(nested.activeGenerationDepth, 2, "an existing deeper scope is preserved, not reset")
        nested.completeCriticalMemoryAction()
        XCTAssertEqual(nested, IOSGenerationOwnershipAuthority())
    }

    /// (d) After the backend barrier, `cancelActiveGeneration` releases ownership only when no
    /// critical action is in flight.
    func testCancellationBarrierReleasesOwnershipOnlyWithoutCriticalAction() {
        var plain = IOSGenerationOwnershipAuthority()
        plain.enterGeneration()
        plain.enterGeneration()
        XCTAssertTrue(plain.releaseGenerationAfterCancellationBarrier())
        XCTAssertEqual(plain.activeGenerationDepth, 0)
        XCTAssertFalse(plain.ownsGenerationScope)

        var critical = IOSGenerationOwnershipAuthority()
        critical.enterGeneration()
        XCTAssertTrue(critical.beginCriticalMemoryAction())
        let held = critical
        XCTAssertFalse(critical.releaseGenerationAfterCancellationBarrier())
        XCTAssertEqual(critical, held)
        XCTAssertTrue(critical.ownsGenerationScope)
    }

    /// (e) A failed cancellation inside the critical action drops the action claim (so the
    /// still-running guard can retry) but keeps generation ownership.
    func testCancellationFailureReleasesActionClaimButKeepsGenerationOwnership() {
        var authority = IOSGenerationOwnershipAuthority()
        authority.enterGeneration()
        XCTAssertTrue(authority.beginCriticalMemoryAction())

        authority.abandonCriticalMemoryActionAfterCancellationFailure()
        XCTAssertFalse(authority.criticalMemoryActionInFlight)
        XCTAssertTrue(authority.ownsGenerationScope)
        XCTAssertEqual(authority.activeGenerationDepth, 1)
        XCTAssertFalse(authority.admitsGeneration(hasActiveGeneration: authority.ownsGenerationScope))

        // The still-running guard can claim again and finally complete.
        XCTAssertTrue(authority.beginCriticalMemoryAction())
        XCTAssertEqual(authority.activeGenerationDepth, 1)
        XCTAssertEqual(authority.completeGeneration(), .retainedByCriticalMemoryAction)
        authority.completeCriticalMemoryAction()
        XCTAssertEqual(authority, IOSGenerationOwnershipAuthority())
    }

    /// (c, completion order) The store returns the scope, publishes idle, then releases the
    /// action claim: while idle is being published, admission is still closed and a second
    /// critical action cannot begin.
    func testCriticalCompletionKeepsAdmissionClosedUntilTheActionClaimIsReleased() {
        var authority = IOSGenerationOwnershipAuthority()
        authority.enterGeneration()
        XCTAssertTrue(authority.beginCriticalMemoryAction())

        XCTAssertTrue(authority.releaseGenerationScopeAfterCriticalUnload())
        XCTAssertFalse(authority.ownsGenerationScope)
        XCTAssertTrue(authority.criticalMemoryActionInFlight)
        XCTAssertFalse(authority.admitsGeneration(hasActiveGeneration: false))
        XCTAssertFalse(authority.beginCriticalMemoryAction())

        XCTAssertTrue(authority.completeCriticalMemoryAction())
        XCTAssertEqual(authority, IOSGenerationOwnershipAuthority())
        XCTAssertTrue(authority.admitsGeneration(hasActiveGeneration: false))
    }

    /// Without a held claim, neither release step may touch a live generation scope.
    func testCriticalReleaseStepsAreNoOpsWithoutAHeldClaim() {
        var authority = IOSGenerationOwnershipAuthority()
        authority.enterGeneration()
        let generating = authority

        XCTAssertFalse(authority.releaseGenerationScopeAfterCriticalUnload())
        XCTAssertFalse(authority.completeCriticalMemoryAction())
        XCTAssertEqual(authority, generating)
        XCTAssertTrue(authority.ownsGenerationScope)
    }

    /// The end-to-end race the deleted Python test named: generation running, guard claims the
    /// runtime, generation body finishes first, user cancel lands, then the unload completes.
    func testCriticalReliefDuringGenerationKeepsOwnershipUntilUnloadCompletes() {
        var authority = IOSGenerationOwnershipAuthority()
        authority.enterGeneration()
        XCTAssertTrue(authority.beginCriticalMemoryAction())
        XCTAssertEqual(authority.completeGeneration(), .retainedByCriticalMemoryAction)
        XCTAssertFalse(authority.releaseGenerationAfterCancellationBarrier())
        XCTAssertFalse(authority.admitsGeneration(hasActiveGeneration: authority.ownsGenerationScope))
        XCTAssertTrue(authority.ownsGenerationScope)
        authority.completeCriticalMemoryAction()
        XCTAssertFalse(authority.ownsGenerationScope)
        XCTAssertTrue(authority.admitsGeneration(hasActiveGeneration: authority.ownsGenerationScope))
    }

    /// (f) The full unload records its completion event only after the awaited unload returned,
    /// then clears backend generation activity exactly once.
    @MainActor
    func testCriticalFullUnloadRecordsCompletionAfterUnloadThenClearsActivityOnce() async {
        var steps: [String] = []
        await CriticalMemoryFullUnloadSequence.execute(
            unload: {
                steps.append("unload_started")
                await Task.yield()
                steps.append("unload_returned")
            },
            recordUnloadCompleted: { steps.append("critical_full_unload") },
            clearGenerationActivity: { steps.append("clear_generation_activity") }
        )
        XCTAssertEqual(steps, [
            "unload_started",
            "unload_returned",
            "critical_full_unload",
            "clear_generation_activity",
        ])
    }
}
