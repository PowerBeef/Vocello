import Foundation
import XCTest

final class MainThreadStallWatchdogTests: XCTestCase {
    func testOverlappingSessionsCloseOnlyAtFinalOwnerAndDoNotUnderflow() {
        let watchdog = MainThreadStallWatchdog()
        watchdog.begin()
        watchdog.begin()

        XCTAssertNil(watchdog.end())
        let report = watchdog.end()
        XCTAssertNotNil(report)
        XCTAssertNil(watchdog.end())
    }

    func testFreshSessionIsolatedFromRetiredSessionCallbacks() throws {
        let watchdog = MainThreadStallWatchdog()
        watchdog.begin()
        let staleCompletion = try XCTUnwrap(watchdog.heartbeatCompletionForTesting())
        _ = watchdog.end()

        watchdog.begin()
        let currentCompletion = try XCTUnwrap(watchdog.heartbeatCompletionForTesting())
        staleCompletion()
        currentCompletion()
        let report = try XCTUnwrap(watchdog.end())

        XCTAssertEqual(report.scheduledHeartbeatCount, 1)
        XCTAssertEqual(report.completedHeartbeatCount, 1)
        XCTAssertEqual(report.censoredHeartbeatCount, 0)
        XCTAssertGreaterThanOrEqual(report.maximumDelayedHeartbeatMS, 0)
    }

    /// Audit #18: a heartbeat still queued behind the main thread when the
    /// session ends is late by at least its age; it must not vanish.
    func testHeartbeatsQueuedAtEndCountAsCensoredLowerBounds() throws {
        let watchdog = MainThreadStallWatchdog()
        watchdog.begin()
        // XCTest runs this method on the main thread, so every heartbeat the
        // timer sends while it sleeps stays queued until after end().
        Thread.sleep(forTimeInterval: 0.6)
        let report = try XCTUnwrap(watchdog.end())

        XCTAssertEqual(report.completedHeartbeatCount, 0)
        // About five ticks fit in the sleep; the bounds leave room for a
        // loaded CI host firing the utility-queue timer late.
        XCTAssertGreaterThanOrEqual(report.censoredHeartbeatCount, 2)
        XCTAssertEqual(report.scheduledHeartbeatCount, report.censoredHeartbeatCount)
        // The first heartbeat was sent about 100 ms in and waited about 500 ms.
        XCTAssertGreaterThanOrEqual(report.maximumDelayedHeartbeatMS, 300)
        XCTAssertGreaterThanOrEqual(report.delayedHeartbeatCount250, 1)
        XCTAssertGreaterThanOrEqual(report.delayedHeartbeatCount50, report.delayedHeartbeatCount250)
        XCTAssertEqual(report.asCounters["censoredHeartbeatCount"], report.censoredHeartbeatCount)
    }

    func testCensoredHeartbeatsDoNotOutliveTheirSession() throws {
        let watchdog = MainThreadStallWatchdog()
        watchdog.begin()
        let pending = try XCTUnwrap(watchdog.heartbeatCompletionForTesting())
        let first = try XCTUnwrap(watchdog.end())
        XCTAssertEqual(first.censoredHeartbeatCount, 1)

        watchdog.begin()
        pending()  // the retired session's completion is dropped
        let second = try XCTUnwrap(watchdog.end())
        XCTAssertEqual(second.completedHeartbeatCount, 0)
        XCTAssertEqual(second.censoredHeartbeatCount, 0)
    }
}
