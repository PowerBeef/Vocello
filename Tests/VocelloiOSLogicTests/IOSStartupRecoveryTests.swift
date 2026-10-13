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

    /// The runner a container drives: the first pass fails and keeps its error
    /// with Retry available, the retried pass succeeds and keeps the
    /// dependencies, and nothing starts after success. Every change is announced
    /// before it happens.
    @MainActor
    func testTheRunnerShowsAFailureThenSucceedsOnRetry() async {
        var passes = 0
        let runner = IOSStartupRunner<String> {
            passes += 1
            if passes == 1 { throw StartupProbeError.unavailable }
            return "dependencies"
        }
        var announcements = 0
        runner.willChange = { announcements += 1 }

        await runner.start()?.value
        XCTAssertEqual(runner.attempt.phase, .failed)
        XCTAssertEqual(runner.error as? StartupProbeError, .unavailable)
        XCTAssertNil(runner.dependencies)
        XCTAssertFalse(runner.attempt.isStarting, "Retry is available after a failure")

        await runner.start()?.value
        XCTAssertEqual(runner.attempt.phase, .ready)
        XCTAssertNil(runner.error, "Retry clears the failure")
        XCTAssertEqual(runner.dependencies, "dependencies")
        XCTAssertNil(runner.start(), "a started app never runs startup again")
        XCTAssertEqual(passes, 2)
        XCTAssertEqual(announcements, 4, "two passes, each announced at its start and its end")
    }

    /// Retry while a pass runs starts nothing; the running pass still ends it.
    @MainActor
    func testTheRunnerRefusesASecondPassWhileOneRuns() async {
        let gate = StartupProbeGate()
        var passes = 0
        let runner = IOSStartupRunner<Int> {
            passes += 1
            await gate.wait()
            return 7
        }
        let running = runner.start()
        XCTAssertNotNil(running)
        // Let the pass begin and suspend inside its operation.
        while passes == 0 { await Task.yield() }
        XCTAssertTrue(runner.attempt.isStarting)
        XCTAssertNil(runner.start(), "Retry during a pass starts nothing")
        gate.open()
        await running?.value
        XCTAssertEqual(runner.dependencies, 7)
        XCTAssertEqual(passes, 1)
    }
}

private enum StartupProbeError: Error, Equatable {
    case unavailable
}

/// Holds a startup pass until the test opens it.
@MainActor
private final class StartupProbeGate {
    private var isOpen = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        guard !isOpen else { return }
        await withCheckedContinuation { waiters.append($0) }
    }

    func open() {
        isOpen = true
        let pending = waiters
        waiters.removeAll()
        pending.forEach { $0.resume() }
    }
}
