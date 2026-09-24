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

        _ = ledger.claim(claim(1), for: .sharedPlayback)
        _ = ledger.claim(claim(2), for: .recording)
        XCTAssertEqual(ledger.enterBackground(), [.deactivate, .configure(.playback)])
        XCTAssertEqual(ledger.heldClaims, [])
        XCTAssertEqual(ledger.release(claim(1)), [])
        XCTAssertEqual(ledger.claim(claim(1), for: .sharedPlayback), [.activate])
    }

    func testFailedActivationDropsTheClaimAndLeavesTheSessionInactive() {
        var ledger = IOSAudioSessionLedger()
        _ = ledger.prepareForLaunch()
        _ = ledger.claim(claim(1), for: .recording)

        XCTAssertEqual(ledger.activationFailed(claim(1)), [.configure(.playback)])
        XCTAssertFalse(ledger.isActive)
        XCTAssertEqual(ledger.heldClaims, [])
        XCTAssertEqual(ledger.claim(claim(2), for: .playback), [.activate])
    }
}
