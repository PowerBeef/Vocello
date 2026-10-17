@testable import QwenVoiceCore
import XCTest

/// BG-01 review: the commit-time prompt prebuilds run one after another. A newer
/// one waits for the running one instead of cancelling it (the cancelled one
/// would still hold the proactive lease, and both prompts would be lost), and
/// leaving the foreground cancels every one.
@MainActor
final class ProactiveTaskChainTests: XCTestCase {
    func testANewerOperationWaitsForTheRunningOneInsteadOfCancellingIt() async {
        let chain = ProactiveTaskChain()
        let began = OpenOnceGate()
        let release = OpenOnceGate()
        let log = EntryLog()
        chain.append {
            began.open()
            await release.wait()
            log.append(Task.isCancelled ? "first-cancelled" : "first-finished")
        }
        chain.append { log.append("second-ran") }

        await began.wait()
        XCTAssertEqual(log.entries, [], "the second waits while the first runs")
        release.open()
        await chain.settle()
        XCTAssertEqual(log.entries, ["first-finished", "second-ran"])
    }

    func testCancellingTheChainCancelsTheRunningAndTheWaitingOperation() async {
        let chain = ProactiveTaskChain()
        let began = OpenOnceGate()
        let release = OpenOnceGate()
        let log = EntryLog()
        chain.append {
            began.open()
            await release.wait()
            log.append(Task.isCancelled ? "first-cancelled" : "first-finished")
        }
        chain.append { log.append("second-ran") }

        await began.wait()
        chain.cancelAll()
        release.open()
        await chain.settle()
        XCTAssertEqual(log.entries, ["first-cancelled"], "the waiting operation never starts")

        chain.append { log.append("later-ran") }
        await chain.settle()
        XCTAssertEqual(log.entries, ["first-cancelled", "later-ran"], "work appended after a cancel runs")
    }
}

/// A gate that stays open once opened; waiting does not observe cancellation,
/// so an operation sees it only after the gate opens.
@MainActor
private final class OpenOnceGate {
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

@MainActor
private final class EntryLog {
    private(set) var entries: [String] = []

    func append(_ entry: String) {
        entries.append(entry)
    }
}
