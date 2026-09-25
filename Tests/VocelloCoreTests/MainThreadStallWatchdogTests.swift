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
        // XCTest runs this method on the main thread, so no heartbeat the
        // timer sends meanwhile can complete before end().
        XCTAssertTrue(Thread.isMainThread)
        let watchdog = MainThreadStallWatchdog()
        watchdog.begin()
        // A heartbeat sent now and never delivered, independent of when (or
        // whether) the utility-queue timer fires on a loaded host.
        _ = try XCTUnwrap(watchdog.heartbeatCompletionForTesting())
        Thread.sleep(forTimeInterval: 0.45)
        let report = try XCTUnwrap(watchdog.end())

        XCTAssertEqual(report.completedHeartbeatCount, 0)
        XCTAssertGreaterThanOrEqual(report.censoredHeartbeatCount, 1)
        XCTAssertEqual(report.scheduledHeartbeatCount, report.censoredHeartbeatCount)
        // Its age at end() is at least the sleep (0.45 s, margin for clock rounding).
        XCTAssertGreaterThanOrEqual(report.maximumDelayedHeartbeatMS, 400)
        XCTAssertGreaterThanOrEqual(report.delayedHeartbeatCount250, 1)
        XCTAssertGreaterThanOrEqual(report.delayedHeartbeatCount50, report.delayedHeartbeatCount250)
        XCTAssertEqual(report.asCounters["censoredHeartbeatCount"], report.censoredHeartbeatCount)
    }

    /// Audit #80: an interval-recording watchdog (the UI-perf probe's) hands
    /// each drained interval its own heartbeats; the shared default keeps none.
    func testIntervalRecordingDrainsEachIntervalsHeartbeats() throws {
        // XCTest runs this on the main thread, so no timer heartbeat can
        // complete meanwhile; only the test's own completion runs.
        XCTAssertTrue(Thread.isMainThread)
        let watchdog = MainThreadStallWatchdog(recordsIntervals: true)
        watchdog.begin()
        let late = try XCTUnwrap(watchdog.heartbeatCompletionForTesting())
        Thread.sleep(forTimeInterval: 0.12)
        late()
        let first = watchdog.drainInterval()
        XCTAssertEqual(first.completedHeartbeatCount, 1)
        XCTAssertEqual(first.delayedHeartbeats.count, 1)
        XCTAssertGreaterThanOrEqual(first.delayedHeartbeats.first?.delayMS ?? 0, 100)
        XCTAssertEqual(first.droppedEventCount, 0)
        let second = watchdog.drainInterval()
        XCTAssertEqual(second.completedHeartbeatCount, 0)
        XCTAssertTrue(second.delayedHeartbeats.isEmpty)
        _ = watchdog.end()

        let shared = MainThreadStallWatchdog()
        shared.begin()
        let completion = try XCTUnwrap(shared.heartbeatCompletionForTesting())
        completion()
        XCTAssertEqual(shared.drainInterval().completedHeartbeatCount, 0)
        _ = shared.end()
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
