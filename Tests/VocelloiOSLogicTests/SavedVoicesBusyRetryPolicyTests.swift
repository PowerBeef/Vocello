import XCTest

final class SavedVoicesBusyRetryPolicyTests: XCTestCase {
    func testScheduleBacksOffOneTwoFourSeconds() {
        var policy = SavedVoicesBusyRetryPolicy()
        XCTAssertEqual(policy.nextDelay(), .seconds(1))
        XCTAssertEqual(policy.nextDelay(), .seconds(2))
        XCTAssertEqual(policy.nextDelay(), .seconds(4))
        XCTAssertEqual(policy.attemptsUsed, 3)
    }

    func testRetriesStopAtTheCap() {
        var policy = SavedVoicesBusyRetryPolicy()
        XCTAssertEqual(policy.maximumAttempts, 3)
        for _ in 0..<policy.maximumAttempts {
            XCTAssertNotNil(policy.nextDelay())
        }
        XCTAssertTrue(policy.isExhausted)
        XCTAssertNil(policy.nextDelay())
        XCTAssertNil(policy.nextDelay())
        XCTAssertEqual(policy.attemptsUsed, 3)
    }

    func testResetStartsAFreshSchedule() {
        var policy = SavedVoicesBusyRetryPolicy()
        _ = policy.nextDelay()
        _ = policy.nextDelay()
        policy.reset()
        XCTAssertFalse(policy.isExhausted)
        XCTAssertEqual(policy.nextDelay(), .seconds(1))

        for _ in 0..<policy.maximumAttempts { _ = policy.nextDelay() }
        XCTAssertNil(policy.nextDelay())
        policy.reset()
        XCTAssertEqual(policy, SavedVoicesBusyRetryPolicy())
        XCTAssertEqual(policy.nextDelay(), .seconds(1))
    }
}
