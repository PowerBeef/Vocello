import XCTest

/// PA-21 / AUD-02: the one audio-session owner's decisions.
final class IOSAudioSessionPolicyTests: XCTestCase {
    private func claim(_ value: UInt64) -> IOSAudioSessionClaim {
        IOSAudioSessionClaim(rawValue: value)
    }

    func testLaunchConfiguresPlaybackWithoutActivating() {
        var ledger = IOSAudioSessionLedger()

        XCTAssertEqual(ledger.prepareForLaunch(), [.configure(.playback)])
        XCTAssertFalse(ledger.isActive)
        XCTAssertEqual(ledger.prepareForLaunch(), [], "a second launch pass changes nothing")
    }

    func testFirstClaimActivatesAndARenewedClaimChangesNothing() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()

        XCTAssertEqual(ledger.claim(claim(1), for: .sharedPlayback), [.activate])
        XCTAssertTrue(ledger.isActive)
        XCTAssertEqual(ledger.claim(claim(1), for: .sharedPlayback), [])
    }

    func testClosingAPreviewKeepsTheSharedPlayerSession() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()
        _ = ledger.claim(claim(1), for: .sharedPlayback)
        XCTAssertEqual(ledger.claim(claim(2), for: .playback), [])

        XCTAssertEqual(ledger.release(claim(2)), [], "the shared player still holds the session")
        XCTAssertTrue(ledger.isActive)
    }

    func testLastReleaseDeactivatesAndNotifiesOthers() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()
        _ = ledger.claim(claim(1), for: .playback)

        XCTAssertEqual(ledger.release(claim(1)), [.deactivate])
        XCTAssertFalse(ledger.isActive)
    }

    func testStaleReleaseNeverSilencesANewerHolder() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()
        _ = ledger.claim(claim(1), for: .playback)
        XCTAssertEqual(ledger.release(claim(1)), [.deactivate])
        XCTAssertEqual(ledger.claim(claim(2), for: .playback), [.activate])

        XCTAssertEqual(ledger.release(claim(1)), [], "a late release of a finished claim")
        XCTAssertTrue(ledger.isActive)
        XCTAssertEqual(ledger.heldClaims, [claim(2)])
    }

    func testMixablePreviewDoesNotLeakMixingIntoLaterPlayback() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()

        XCTAssertEqual(
            ledger.claim(claim(1), for: .mixablePreview),
            [.configure(.mixablePlayback), .activate]
        )
        XCTAssertEqual(ledger.release(claim(1)), [.deactivate, .configure(.playback)])
        XCTAssertEqual(ledger.appliedConfiguration, .playback)
    }

    func testMixablePreviewOverSharedPlaybackRestoresExclusivePlayback() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()
        _ = ledger.claim(claim(1), for: .sharedPlayback)

        XCTAssertEqual(ledger.claim(claim(2), for: .mixablePreview), [.configure(.mixablePlayback)])
        XCTAssertEqual(ledger.release(claim(2)), [.configure(.playback)])
        XCTAssertTrue(ledger.isActive)
    }

    func testRecordingOutranksPlaybackUntilItEnds() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()
        _ = ledger.claim(claim(1), for: .sharedPlayback)

        XCTAssertEqual(ledger.claim(claim(2), for: .recording), [.configure(.recording)])
        XCTAssertEqual(
            ledger.claim(claim(3), for: .playback), [],
            "a player starting mid-recording never flips the category under the recorder"
        )
        XCTAssertEqual(ledger.appliedConfiguration, .recording)
        XCTAssertEqual(ledger.release(claim(2)), [.configure(.playback)])
    }

    func testRecordingAloneRestoresThePlaybackBaseWhenItEnds() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()

        XCTAssertEqual(ledger.claim(claim(1), for: .recording), [.configure(.recording), .activate])
        XCTAssertEqual(ledger.release(claim(1)), [.deactivate, .configure(.playback)])
    }

    func testBackgroundEndsEveryClaimAndAlwaysHandsTheSessionBack() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()
        XCTAssertEqual(ledger.enterBackground(), [.deactivate], "a player may have activated implicitly")
        ledger.enterForeground()

        _ = ledger.claim(claim(1), for: .sharedPlayback)
        _ = ledger.claim(claim(2), for: .recording)
        XCTAssertEqual(ledger.enterBackground(), [.deactivate, .configure(.playback)])
        XCTAssertEqual(ledger.heldClaims, [])
        XCTAssertEqual(ledger.release(claim(1)), [])
        ledger.enterForeground()
        XCTAssertEqual(ledger.claim(claim(1), for: .sharedPlayback), [.activate])
    }

    /// A late live chunk or an interruption ending while the app is in the
    /// background must not reactivate the session during PA-15's background time.
    func testClaimsInTheBackgroundChangeNothingUntilTheAppIsActive() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()
        _ = ledger.claim(claim(1), for: .sharedPlayback)
        XCTAssertEqual(ledger.enterBackground(), [.deactivate])

        XCTAssertEqual(ledger.claim(claim(1), for: .sharedPlayback), [], "a late live chunk")
        XCTAssertEqual(ledger.claim(claim(2), for: .recording), [])
        XCTAssertFalse(ledger.isActive)
        XCTAssertEqual(ledger.heldClaims, [])
        XCTAssertEqual(ledger.appliedConfiguration, .playback)
        XCTAssertEqual(ledger.release(claim(1)), [])

        ledger.enterForeground()
        XCTAssertFalse(ledger.isActive, "returning alone never activates the session")
        XCTAssertEqual(ledger.claim(claim(1), for: .sharedPlayback), [.activate])
    }

    func testFailedActivationDropsTheClaimAndLeavesTheSessionInactive() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()
        let steps = ledger.claim(claim(1), for: .recording)

        XCTAssertEqual(ledger.activationFailed(claim(1), steps: steps), [.configure(.playback)])
        XCTAssertFalse(ledger.isActive)
        XCTAssertEqual(ledger.heldClaims, [])
        XCTAssertEqual(ledger.claim(claim(2), for: .playback), [.activate])
    }

    /// A failed configuration while another holder keeps the session active
    /// leaves it active, so the last release still hands it back.
    func testFailedConfigurationUnderAnotherHolderKeepsTheSessionActive() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()
        _ = ledger.claim(claim(1), for: .sharedPlayback)
        let steps = ledger.claim(claim(2), for: .recording)
        XCTAssertEqual(steps, [.configure(.recording)])

        XCTAssertEqual(ledger.activationFailed(claim(2), steps: steps), [.configure(.playback)])
        XCTAssertTrue(ledger.isActive)
        XCTAssertEqual(ledger.heldClaims, [claim(1)])
        XCTAssertEqual(ledger.release(claim(1)), [.deactivate])
    }

    /// PA-21 review: a recording that stops itself at its time cap releases its
    /// claim, so clip review and Studio playback are no longer held in `.record`.
    /// The release may run twice (the delegate and an explicit stop); the second
    /// changes nothing.
    func testFinishedRecordingReleasesItsClaimAndRestoresPlayback() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()
        _ = ledger.claim(claim(1), for: .sharedPlayback)
        _ = ledger.claim(claim(2), for: .recording)
        XCTAssertEqual(ledger.requiredConfiguration, .recording)

        XCTAssertEqual(ledger.release(claim(2)), [.configure(.playback)])
        XCTAssertEqual(ledger.release(claim(2)), [], "a second release of the finished recording")
        XCTAssertEqual(ledger.requiredConfiguration, .playback)
        XCTAssertEqual(ledger.claim(claim(3), for: .playback), [], "clip review plays at once")
        XCTAssertEqual(ledger.appliedConfiguration, .playback)
    }
}
