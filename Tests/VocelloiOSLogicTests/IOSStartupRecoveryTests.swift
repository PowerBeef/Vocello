import Foundation
import XCTest

/// AUD-01: startup is an owned, retryable operation, and an opened file waits
/// for the root view and for onboarding to finish.
final class IOSStartupRecoveryTests: XCTestCase {
    /// A failed pass offers Retry; the retried pass can succeed; nothing starts
    /// beside a running pass or after success, and only the running pass ends.
    func testAFailedStartupRetriesUntilItSucceeds() {
        var attempt = IOSStartupAttempt()
        XCTAssertEqual(attempt.phase, .idle)
        attempt.finish(succeeded: true)
        XCTAssertEqual(attempt.phase, .idle, "no pass is running, so nothing finishes")

        XCTAssertTrue(attempt.begin())
        XCTAssertTrue(attempt.isStarting)
        XCTAssertFalse(attempt.begin(), "Retry while a pass runs starts nothing")
        attempt.finish(succeeded: false)
        XCTAssertEqual(attempt.phase, .failed)
        XCTAssertFalse(attempt.isStarting)

        XCTAssertTrue(attempt.begin(), "Retry after a failure starts the next pass")
        attempt.finish(succeeded: true)
        XCTAssertEqual(attempt.phase, .ready)
        XCTAssertFalse(attempt.begin(), "a started app never runs startup again")
        attempt.finish(succeeded: false)
        XCTAssertEqual(attempt.phase, .ready, "a late result cannot undo a finished startup")
    }

    /// A file opened during onboarding waits, is handed out exactly once after
    /// onboarding, and a later open replaces one still waiting.
    func testAnOpenedFileWaitsForOnboardingAndIsTakenOnce() {
        let first = URL(fileURLWithPath: "/tmp/first.wav")
        let second = URL(fileURLWithPath: "/tmp/second.m4a")
        var queue = IOSExternalImportQueue()
        XCTAssertNil(queue.take(onboardingIsPresented: false))

        queue.enqueue(first)
        XCTAssertNil(queue.take(onboardingIsPresented: true), "never over the onboarding cover")
        XCTAssertEqual(queue.pending, first, "kept while onboarding is up")

        queue.enqueue(second)
        XCTAssertEqual(queue.take(onboardingIsPresented: false), second)
        XCTAssertNil(queue.pending)
        XCTAssertNil(queue.take(onboardingIsPresented: false), "each file is handed out once")
    }
}
