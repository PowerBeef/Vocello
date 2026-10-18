import Foundation
import Synchronization

/// Measures main-thread responsiveness during generation — the project's
/// "does the UI lag under engine load" KPI.
///
/// Mechanism: a utility-QoS `DispatchSourceTimer` ticks every 100 ms and
/// dispatches a no-op block to the main queue, measuring the block's arrival
/// latency. A saturated main thread delays the measurement block itself,
/// which is exactly the metric we want: how late a user event would be
/// serviced right now. Delayed heartbeats are bucketed at >50 ms (noticeable) and
/// >250 ms (a visible hang per Apple's hang-detection threshold).
///
/// A heartbeat still queued when the session ends is folded in as a censored
/// observation: its delay is at least the time since it was sent, so that
/// lower bound counts toward the thresholds and the maximum (audit #18; the
/// frontend metrics name this `completedAndCensoredPending`). Before this,
/// those heartbeats were dropped, which biased the maxima low exactly at the
/// generation boundary, where the completion path runs on the main thread.
///
/// Lifecycle: `begin()`/`end()` are refcounted so overlapping generations
/// (e.g. batch + single) share one timer. Callers only invoke it when
/// `TelemetryGate` is on (same convention as `AppGenerationTimeline`), so
/// shipped non-debug runs never start the timer. The whole thing costs one
/// no-op main-queue block per 100 ms while a generation is active.
///
/// A watchdog created with `recordsIntervals` (the UI-perf frame probes' private
/// instance, audit #80) also keeps, per interval the probe drains, its completed
/// heartbeat count and each delayed heartbeat's completion time and delay, so the
/// checker can scope heartbeat statistics to a measured window instead of the
/// launch. The shared generation session never records intervals.
final class MainThreadStallWatchdog: Sendable {
    /// One heartbeat that ran more than 50 ms late: when it completed (wall-clock
    /// epoch milliseconds, the probe's block clock) and by how much.
    struct DelayedHeartbeat: Sendable {
        let completedEpochMS: Int64
        let delayMS: Int
    }

    /// What one interval of an interval-recording watchdog saw.
    struct IntervalHeartbeats: Sendable {
        let completedHeartbeatCount: Int
        /// Oldest first, at most `intervalEventLimit`; `droppedEventCount` more.
        let delayedHeartbeats: [DelayedHeartbeat]
        let droppedEventCount: Int
    }

    static let intervalEventLimit = 256

    struct Report {
        let delayedHeartbeatCount50: Int
        let delayedHeartbeatCount250: Int
        let maximumDelayedHeartbeatMS: Int
        let scheduledHeartbeatCount: Int
        let completedHeartbeatCount: Int
        /// Heartbeats still queued at `end()`, counted by their lower bound.
        let censoredHeartbeatCount: Int

        var asCounters: [String: Int] {
            let coveragePPM = scheduledHeartbeatCount > 0
                ? Int((Double(completedHeartbeatCount) / Double(scheduledHeartbeatCount) * 1_000_000).rounded())
                : 0
            return [
                "delayedHeartbeatCount50": delayedHeartbeatCount50,
                "delayedHeartbeatCount250": delayedHeartbeatCount250,
                "maximumDelayedHeartbeatMS": maximumDelayedHeartbeatMS,
                "heartbeatScheduledCount": scheduledHeartbeatCount,
                "heartbeatCompletedCount": completedHeartbeatCount,
                "heartbeatCoveragePPM": coveragePPM,
                // Its presence marks the censored delay definition.
                "censoredHeartbeatCount": censoredHeartbeatCount,
                // Compatibility keys for v1-v6 readers. These describe sampled
                // heartbeat delay, not an exhaustive count of main-thread stalls.
                "uiStallCount50": delayedHeartbeatCount50,
                "uiStallCount250": delayedHeartbeatCount250,
                "uiMaxStallMS": maximumDelayedHeartbeatMS,
                "uiHeartbeats": completedHeartbeatCount,
            ]
        }
    }

    static let shared = MainThreadStallWatchdog()

    /// The session's timer and counters, read and written only inside `state.withLock`.
    private struct State {
        var timer: DispatchSourceTimer?
        var activeSessions = 0
        var sessionToken: UInt64 = 0

        var delayedHeartbeatCount50 = 0
        var delayedHeartbeatCount250 = 0
        var maximumDelayedHeartbeatMS = 0
        var scheduledHeartbeatCount = 0
        var completedHeartbeatCount = 0
        /// Send instants of this session's heartbeats that have not run yet.
        var pendingSentAt: [UInt64: ContinuousClock.Instant] = [:]
        var nextHeartbeatID: UInt64 = 0
        var intervalCompletedCount = 0
        var intervalDelayed: [DelayedHeartbeat] = []
        var intervalDroppedCount = 0

        mutating func recordInterval(_ ms: Int) {
            intervalCompletedCount += 1
            guard ms > 50 else { return }
            guard intervalDelayed.count < MainThreadStallWatchdog.intervalEventLimit else {
                intervalDroppedCount += 1
                return
            }
            intervalDelayed.append(DelayedHeartbeat(
                completedEpochMS: Int64((Date().timeIntervalSince1970 * 1_000).rounded()),
                delayMS: ms
            ))
        }

        mutating func recordDelay(_ ms: Int) {
            if ms > 50 { delayedHeartbeatCount50 += 1 }
            if ms > 250 { delayedHeartbeatCount250 += 1 }
            if ms > maximumDelayedHeartbeatMS { maximumDelayedHeartbeatMS = ms }
        }
    }

    private let state = Mutex(State())
    private let queue = DispatchQueue(label: "com.qwenvoice.ui-watchdog", qos: .utility)
    private let recordsIntervals: Bool

    init(recordsIntervals: Bool = false) {
        self.recordsIntervals = recordsIntervals
    }

    /// Start (or join) a measurement session.
    func begin() {
        state.withLock { state in
            state.activeSessions += 1
            guard state.timer == nil else { return }

            state.sessionToken &+= 1
            let token = state.sessionToken
            state.delayedHeartbeatCount50 = 0
            state.delayedHeartbeatCount250 = 0
            state.maximumDelayedHeartbeatMS = 0
            state.scheduledHeartbeatCount = 0
            state.completedHeartbeatCount = 0
            state.pendingSentAt.removeAll(keepingCapacity: true)
            state.intervalCompletedCount = 0
            state.intervalDelayed.removeAll(keepingCapacity: true)
            state.intervalDroppedCount = 0

            // The handler runs on `queue`, never inside this critical section, so its
            // `makeHeartbeatCompletion` call takes the mutex afresh.
            let source = DispatchSource.makeTimerSource(queue: queue)
            source.schedule(deadline: .now() + .milliseconds(100), repeating: .milliseconds(100))
            source.setEventHandler { [weak self] in
                guard let self else { return }
                let sentAt = ContinuousClock.now
                guard let completion = self.makeHeartbeatCompletion(token: token, sentAt: sentAt) else {
                    return
                }
                DispatchQueue.main.async(execute: completion)
            }
            source.resume()
            state.timer = source
        }
    }

    /// Leave the session; returns the accumulated report when the last
    /// participant leaves (nil while other generations are still active,
    /// or when `end()` is called without a matching `begin()`).
    @discardableResult
    func end() -> Report? {
        state.withLock { state -> Report? in
            guard state.activeSessions > 0 else { return nil }
            state.activeSessions -= 1
            guard state.activeSessions == 0 else { return nil }

            state.timer?.cancel()
            state.timer = nil
            state.sessionToken &+= 1
            // Heartbeats still queued behind the main thread are late by at least
            // their age. The token bump drops their completions, so this lower
            // bound is the only observation of them.
            let now = ContinuousClock.now
            let censoredHeartbeatCount = state.pendingSentAt.count
            for sentAt in state.pendingSentAt.values {
                state.recordDelay(Self.milliseconds(from: sentAt, to: now))
            }
            state.pendingSentAt.removeAll(keepingCapacity: true)
            return Report(
                delayedHeartbeatCount50: state.delayedHeartbeatCount50,
                delayedHeartbeatCount250: state.delayedHeartbeatCount250,
                maximumDelayedHeartbeatMS: state.maximumDelayedHeartbeatMS,
                scheduledHeartbeatCount: state.scheduledHeartbeatCount,
                completedHeartbeatCount: state.completedHeartbeatCount,
                censoredHeartbeatCount: censoredHeartbeatCount
            )
        }
    }

    /// Test seam for deterministically delivering a callback after its owning
    /// session has retired. Production heartbeat accounting uses the same path.
    func heartbeatCompletionForTesting() -> (@Sendable () -> Void)? {
        let token = state.withLock { $0.sessionToken }
        return makeHeartbeatCompletion(token: token, sentAt: ContinuousClock.now)
    }

    private func makeHeartbeatCompletion(
        token: UInt64,
        sentAt: ContinuousClock.Instant
    ) -> (@Sendable () -> Void)? {
        let scheduledID = state.withLock { state -> UInt64? in
            guard state.sessionToken == token, state.activeSessions > 0 else {
                return nil
            }
            state.scheduledHeartbeatCount += 1
            state.nextHeartbeatID &+= 1
            let heartbeatID = state.nextHeartbeatID
            state.pendingSentAt[heartbeatID] = sentAt
            return heartbeatID
        }
        guard let heartbeatID = scheduledID else { return nil }
        return { [weak self] in
            guard let self else { return }
            let ms = MainThreadStallWatchdog.milliseconds(from: sentAt, to: ContinuousClock.now)
            let recordsIntervals = self.recordsIntervals
            self.state.withLock { state in
                guard state.sessionToken == token, state.activeSessions > 0 else {
                    return
                }
                state.pendingSentAt.removeValue(forKey: heartbeatID)
                state.completedHeartbeatCount += 1
                state.recordDelay(ms)
                if recordsIntervals {
                    state.recordInterval(ms)
                }
            }
        }
    }

    /// The heartbeats completed since the previous drain (an interval-recording
    /// watchdog; empty otherwise), and a fresh interval.
    func drainInterval() -> IntervalHeartbeats {
        state.withLock { state -> IntervalHeartbeats in
            let interval = IntervalHeartbeats(
                completedHeartbeatCount: state.intervalCompletedCount,
                delayedHeartbeats: state.intervalDelayed,
                droppedEventCount: state.intervalDroppedCount
            )
            state.intervalCompletedCount = 0
            state.intervalDelayed.removeAll(keepingCapacity: true)
            state.intervalDroppedCount = 0
            return interval
        }
    }

    private static func milliseconds(
        from start: ContinuousClock.Instant,
        to end: ContinuousClock.Instant
    ) -> Int {
        let latency = start.duration(to: end)
        return Int(Double(latency.components.seconds) * 1_000
            + Double(latency.components.attoseconds) / 1_000_000_000_000_000)
    }
}
