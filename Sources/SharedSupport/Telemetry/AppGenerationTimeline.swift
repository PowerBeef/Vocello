import Foundation
import QwenVoiceCore

/// Collects the **user-perceived** generation milestones — submit → first chunk
/// delivered → playback scheduled → completion — and writes the app-layer row
/// of the unified telemetry artifact, keyed by the app-minted `generationID` so it
/// joins the middle/engine rows.
///
/// `@MainActor` because every hook site already runs on the main actor
/// (`AudioPlayerViewModel`, the generate coordinators), so recording a milestone is
/// a synchronous dictionary write with no actor hop on the hot chunk path. The only
/// off-main work is the final JSONL write, dispatched via `Task.detached`.
///
/// Lives in `SharedSupport` so both the macOS and iOS app surfaces use it; the
/// per-target `AppPaths` resolves the correct app-support directory in each build.
@MainActor
final class AppGenerationTimeline {
    static let shared = AppGenerationTimeline()

    private struct Marks {
        let submittedAt: ContinuousClock.Instant
        /// Wall-clock twin of `submittedAt` (ms since 1970) so evidence recorded
        /// by another process on the same host (the played-audio capture) can
        /// be placed on this row's timeline without guessing the click-to-submit
        /// latency of the UI driver. Correlation only, never a throughput figure.
        let submittedAtEpochMS: Int
        var firstChunkAt: ContinuousClock.Instant?
        var playbackScheduledAt: ContinuousClock.Instant?
        var mode: String?
        var playbackHealth = PlaybackHealthAccumulator()
        let memorySampler: NativeTelemetrySampler?
        let telemetryMode: NativeTelemetryMode
    }

    private var marksByID: [String: Marks] = [:]
    /// Generations currently holding a `MainThreadStallWatchdog` session —
    /// kept separately from `marksByID` so the watchdog refcount stays
    /// balanced through evictions and failures.
    private var watchdogSessions: Set<String> = []
    private let clock = ContinuousClock()
    /// Backstop against unbounded growth if a `completed` is ever missed.
    private static let maxTrackedGenerations = 16

    private init() {}

    func recordSubmitted(id: UUID?, mode: String?) async {
        guard TelemetryGate.appProcessIntendedEnabled else { return }
        guard let key = id?.uuidString else { return }
        if marksByID.count >= Self.maxTrackedGenerations {
            let evictedSamplers = marksByID.values.compactMap(\.memorySampler)
            marksByID.removeAll(keepingCapacity: true)
            for _ in watchdogSessions { MainThreadStallWatchdog.shared.end() }
            watchdogSessions.removeAll(keepingCapacity: true)
            for sampler in evictedSamplers {
                await sampler.captureBoundary("app_terminal")
                _ = await sampler.stop(stageMarks: [])
            }
        }
        let telemetryMode = TelemetryGate.appProcessIntendedMode
        let memorySampler = Self.makeAppMemorySampler(mode: telemetryMode)
        marksByID[key] = Marks(
            submittedAt: clock.now,
            submittedAtEpochMS: Int((Date().timeIntervalSince1970 * 1000).rounded()),
            mode: mode,
            memorySampler: memorySampler,
            telemetryMode: telemetryMode
        )
        if watchdogSessions.insert(key).inserted {
            MainThreadStallWatchdog.shared.begin()
        }
        if let memorySampler {
            await memorySampler.start()
            await memorySampler.captureBoundary("app_submit")
        }
    }

    /// Finish a failed/cancelled frontend session durably. Failure rows carry
    /// only bounded lifecycle/counter data; no raw error or user content.
    func recordFailed(
        id: UUID?,
        finishReason: GenerationTerminalReason = .failed
    ) async {
        guard TelemetryGate.appProcessIntendedEnabled else { return }
        guard let key = id?.uuidString else { return }
        let now = clock.now
        let marks = marksByID.removeValue(forKey: key)
        var counters: [String: Int] = [:]
        let hadWatchdogSession = watchdogSessions.remove(key) != nil
        guard marks != nil || hadWatchdogSession else { return }
        if hadWatchdogSession {
            counters = MainThreadStallWatchdog.shared.end()?.asCounters ?? [:]
        }
        var timingsMS: [String: Int] = [:]
        if let marks {
            counters["playbackChunksReceived"] = marks.playbackHealth.chunksReceived
            counters["playbackContinuityFailures"] = marks.playbackHealth.continuityFailures
            counters["playbackUnderruns"] = marks.playbackHealth.underruns
            if let startChunks = marks.playbackHealth.startBufferedChunks {
                counters["playbackStartBufferedChunks"] = startChunks
            }
            if let minimumAudioMS = marks.playbackHealth.minimumQueuedAudioMS {
                timingsMS["playbackMinimumQueuedAudioMS"] = minimumAudioMS
            }
            timingsMS["submitToCompletedMS"] = Self.milliseconds(from: marks.submittedAt, to: now)
            if let firstChunkAt = marks.firstChunkAt {
                timingsMS["submitToFirstChunkMS"] = Self.milliseconds(from: marks.submittedAt, to: firstChunkAt)
            }
            if let playbackScheduledAt = marks.playbackScheduledAt {
                timingsMS["submitToPlaybackScheduledMS"] = Self.milliseconds(
                    from: marks.submittedAt,
                    to: playbackScheduledAt
                )
            }
        }
        let appMemorySummary = await finishAppMemoryCapture(
            marks: marks,
            generationID: key
        )
        let record = GenerationTelemetryRecord(
            generationID: key,
            layer: .app,
            recordedAt: ISO8601DateFormatter().string(from: Date()),
            mode: marks?.mode,
            finishReason: finishReason.rawValue,
            summary: appMemorySummary,
            timingsMS: timingsMS,
            counters: counters,
            notes: currentTaskQOSNotes()
                .merging(BenchRunContext.telemetryNotes()) { current, _ in current },
            frontendMetrics: GenerationTelemetryCompatibilityAdapter.frontend(
                timingsMS: timingsMS,
                counters: counters,
                playbackStartSource: marks?.playbackHealth.startSource
            )
        )
        await GenerationTelemetryJSONLSink.shared.write(
            record: record,
            appSupportDirectory: AppPaths.appSupportDir,
            subdirectory: "app"
        )
    }

    /// `id` is the player's session id string (== `generationID.uuidString` whenever
    /// the app minted one, which it now always does). First call per id wins.
    func recordFirstChunk(id: String?) {
        guard let id, var marks = marksByID[id], marks.firstChunkAt == nil else { return }
        marks.firstChunkAt = clock.now
        marksByID[id] = marks
    }

    /// Records the instant a frontend player accepts a successful `play()` call.
    /// This is intentionally named "scheduled": without an acoustic loopback we
    /// cannot prove when a listener first heard a rendered sample. `source` keeps
    /// live PCM queue depth distinct from finalized-file buffer semantics.
    func recordPlaybackScheduled(
        id: String?,
        source: FrontendPlaybackStartSource,
        queuedChunks: Int,
        queuedAudioSeconds: TimeInterval
    ) {
        guard let id, var marks = marksByID[id], marks.playbackScheduledAt == nil else { return }
        marks.playbackScheduledAt = clock.now
        marks.playbackHealth.playbackScheduled(
            source: source,
            queuedChunks: queuedChunks,
            queuedAudioMS: Self.audioMilliseconds(queuedAudioSeconds)
        )
        marksByID[id] = marks
    }

    func recordPlaybackChunk(
        id: String?,
        queuedAudioSeconds: TimeInterval
    ) {
        guard let id, var marks = marksByID[id] else { return }
        marks.playbackHealth.chunkReceived(queuedAudioMS: Self.audioMilliseconds(queuedAudioSeconds))
        marksByID[id] = marks
    }

    func recordPlaybackContinuityFailure(id: String?) {
        guard let id, var marks = marksByID[id] else { return }
        marks.playbackHealth.continuityFailed()
        marksByID[id] = marks
    }

    func recordPlaybackUnderrun(id: String?) {
        guard let id, var marks = marksByID[id] else { return }
        marks.playbackHealth.underrun()
        marksByID[id] = marks
    }

    func recordPlaybackQueueDepth(id: String?, queuedAudioSeconds: TimeInterval) {
        guard let id, var marks = marksByID[id] else { return }
        marks.playbackHealth.queueDrained(queuedAudioMS: Self.audioMilliseconds(queuedAudioSeconds))
        marksByID[id] = marks
    }

    func recordCompleted(
        id: UUID?,
        mode: String?,
        usedStreaming: Bool,
        finishReason: String?,
        summary _: TelemetrySummary?
    ) async {
        guard TelemetryGate.appProcessIntendedEnabled else { return }
        guard let key = id?.uuidString else { return }
        let now = clock.now
        let marks = marksByID.removeValue(forKey: key)

        // UI-responsiveness KPI: the report is only available when this is
        // the last active generation (overlapping generations share one
        // watchdog window, so per-generation attribution isn't meaningful —
        // the counters are simply omitted on all but the closing row).
        var counters: [String: Int] = [:]
        let hadWatchdogSession = watchdogSessions.remove(key) != nil
        guard marks != nil || hadWatchdogSession else { return }
        if hadWatchdogSession,
           let report = MainThreadStallWatchdog.shared.end() {
            counters = report.asCounters
        }

        var timingsMS: [String: Int] = [:]
        if let marks {
            counters["playbackChunksReceived"] = marks.playbackHealth.chunksReceived
            counters["playbackContinuityFailures"] = marks.playbackHealth.continuityFailures
            counters["playbackUnderruns"] = marks.playbackHealth.underruns
            if let startChunks = marks.playbackHealth.startBufferedChunks {
                counters["playbackStartBufferedChunks"] = startChunks
            }
            if let startAudioMS = marks.playbackHealth.startBufferedAudioMS {
                timingsMS["playbackStartBufferedAudioMS"] = startAudioMS
            }
            if let minimumAudioMS = marks.playbackHealth.minimumQueuedAudioMS {
                timingsMS["playbackMinimumQueuedAudioMS"] = minimumAudioMS
            }
            timingsMS["submittedAtEpochMS"] = marks.submittedAtEpochMS
            timingsMS["submitToCompletedMS"] = Self.milliseconds(from: marks.submittedAt, to: now)
            timingsMS["submitToCompletedNS"] = Self.nanoseconds(from: marks.submittedAt, to: now)
            if let firstChunkAt = marks.firstChunkAt {
                timingsMS["submitToFirstChunkMS"] = Self.milliseconds(from: marks.submittedAt, to: firstChunkAt)
                timingsMS["submitToFirstChunkNS"] = Self.nanoseconds(from: marks.submittedAt, to: firstChunkAt)
            }
            if let playbackScheduledAt = marks.playbackScheduledAt {
                timingsMS["submitToPlaybackScheduledMS"] = Self.milliseconds(
                    from: marks.submittedAt,
                    to: playbackScheduledAt
                )
                timingsMS["submitToPlaybackScheduledNS"] = Self.nanoseconds(
                    from: marks.submittedAt,
                    to: playbackScheduledAt
                )
            }
            if let firstChunkAt = marks.firstChunkAt,
               let playbackScheduledAt = marks.playbackScheduledAt {
                timingsMS["firstChunkToPlaybackScheduledMS"] = Self.milliseconds(
                    from: firstChunkAt,
                    to: playbackScheduledAt
                )
                timingsMS["firstChunkToPlaybackScheduledNS"] = Self.nanoseconds(
                    from: firstChunkAt,
                    to: playbackScheduledAt
                )
            }
        }

        let notes = currentTaskQOSNotes()
            .merging(BenchRunContext.telemetryNotes()) { current, _ in current }
        let appMemorySummary = await finishAppMemoryCapture(
            marks: marks,
            generationID: key
        )
        let record = GenerationTelemetryRecord(
            generationID: key,
            layer: .app,
            recordedAt: ISO8601DateFormatter().string(from: Date()),
            mode: mode ?? marks?.mode,
            usedStreaming: usedStreaming,
            finishReason: finishReason,
            // Memory belongs to the process that sampled it. On macOS this is the
            // app-process sampler; iOS deliberately leaves this nil because its
            // app and engine share the single engine-owned process sampler.
            summary: appMemorySummary,
            timingsMS: timingsMS,
            counters: counters,
            notes: notes,
            frontendMetrics: GenerationTelemetryCompatibilityAdapter.frontend(
                timingsMS: timingsMS,
                counters: counters,
                playbackStartSource: marks?.playbackHealth.startSource
            )
        )
        let appSupportDirectory = AppPaths.appSupportDir
        // A completed result is a durability boundary. Await the append before
        // callers schedule the cross-layer merge or a benchmark starts another
        // cold session; this no longer depends on frontend-only UI-test markers.
        await GenerationTelemetryJSONLSink.shared.write(
            record: record,
            appSupportDirectory: appSupportDirectory,
            subdirectory: "app"
        )
    }

    private static func makeAppMemorySampler(mode: NativeTelemetryMode) -> NativeTelemetrySampler? {
        #if os(macOS)
        guard let sampleIntervalMS = mode.sampleIntervalMS(
            for: NativeMemoryPolicyResolver.deviceClass()
        ) else { return nil }
        return NativeTelemetrySampler(
            clock: NativeTelemetryClock(),
            sampleIntervalMS: sampleIntervalMS,
            processRole: .app,
            boundaryRequirements: TelemetryBoundaryRequirement.appGeneration
        )
        #else
        return nil
        #endif
    }

    private func finishAppMemoryCapture(
        marks: Marks?,
        generationID: String
    ) async -> TelemetrySummary? {
        guard let marks, let sampler = marks.memorySampler else { return nil }
        await sampler.captureBoundary("app_terminal")
        let result = await sampler.stop(stageMarks: [])
        if marks.telemetryMode.persistsRawSamples {
            await GenerationTelemetryJSONLSink.shared.writeRawSamples(
                result.samples,
                generationID: generationID,
                appSupportDirectory: AppPaths.appSupportDir,
                subdirectory: "app"
            )
        }
        return result.summary
    }

    private static func milliseconds(
        from start: ContinuousClock.Instant,
        to end: ContinuousClock.Instant
    ) -> Int {
        let duration = start.duration(to: end)
        let components = duration.components
        // 1 ms == 1e15 attoseconds.
        let millis = Double(components.seconds) * 1_000
            + Double(components.attoseconds) / 1_000_000_000_000_000
        return Int(millis.rounded())
    }

    private static func nanoseconds(
        from start: ContinuousClock.Instant,
        to end: ContinuousClock.Instant
    ) -> Int {
        let duration = start.duration(to: end)
        let components = duration.components
        let secondsNS = UInt64(components.seconds) * 1_000_000_000
        let attosecondsNS = UInt64(components.attoseconds / 1_000_000_000)
        return Int(min(UInt64(Int.max), secondsNS + attosecondsNS))
    }

    private static func audioMilliseconds(_ seconds: TimeInterval) -> Int {
        Int((max(seconds, 0) * 1_000).rounded())
    }
}
