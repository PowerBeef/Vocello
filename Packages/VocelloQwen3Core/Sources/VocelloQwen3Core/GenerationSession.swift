import Foundation

/// Emitted when the Qwen producer has completed request/input preparation and
/// is ready to enter token generation. Reservation acceptance or task startup
/// alone must not publish this event.
public struct VocelloQwen3PreparedEvent: Codable, Hashable, Sendable {
    public let generationID: UUID
    public let model: VocelloQwen3ModelIdentity
    public let mode: VocelloQwen3SynthesisMode
    public let elapsedMilliseconds: Int

    public init(
        generationID: UUID,
        model: VocelloQwen3ModelIdentity,
        mode: VocelloQwen3SynthesisMode,
        elapsedMilliseconds: Int
    ) {
        self.generationID = generationID
        self.model = model
        self.mode = mode
        self.elapsedMilliseconds = elapsedMilliseconds
    }
}

/// One ordered mono or interleaved audio payload produced by a generation.
public struct VocelloQwen3AudioChunkEvent: Codable, Hashable, Sendable {
    public let generationID: UUID
    public let sequence: Int
    public let samples: [Float]
    public let sampleRate: Int
    public let channelCount: Int
    /// Timing evidence emitted immediately before this exact audio payload.
    /// Quality-first requests and compatibility producers without timing
    /// support leave this nil rather than attaching stale evidence.
    public let timings: VocelloQwen3ChunkTimings?
    /// Exact codec-frame range that produced this PCM payload. Both bounds are
    /// present together when the streaming producer observed them.
    public let codecStartFrame: UInt64?
    public let codecEndFrameExclusive: UInt64?
    /// One-shot startup observations attached only to the first materialized
    /// audio event. Both token/code timestamps are co-observed because Qwen's
    /// public producer signal materializes one complete code group per token.
    public let startupObservations: VocelloQwen3StartupObservations?

    public init(
        generationID: UUID,
        sequence: Int,
        samples: [Float],
        sampleRate: Int,
        channelCount: Int = 1,
        timings: VocelloQwen3ChunkTimings? = nil,
        codecStartFrame: UInt64? = nil,
        codecEndFrameExclusive: UInt64? = nil,
        startupObservations: VocelloQwen3StartupObservations? = nil
    ) {
        self.generationID = generationID
        self.sequence = sequence
        self.samples = samples
        self.sampleRate = sampleRate
        self.channelCount = channelCount
        self.timings = timings
        self.codecStartFrame = codecStartFrame ?? timings?.codecStartFrame
        self.codecEndFrameExclusive = codecEndFrameExclusive ?? timings?.codecEndFrameExclusive
        self.startupObservations = startupObservations
    }

    public var frameCount: Int {
        guard channelCount > 0 else { return 0 }
        return samples.count / channelCount
    }
}

public struct VocelloQwen3StartupObservations: Codable, Hashable, Sendable {
    public let firstModelTokenAndAudioCodeMilliseconds: Int?
    public let firstDecodedAudioFrameMilliseconds: Int

    public init(
        firstModelTokenAndAudioCodeMilliseconds: Int?,
        firstDecodedAudioFrameMilliseconds: Int
    ) {
        self.firstModelTokenAndAudioCodeMilliseconds = firstModelTokenAndAudioCodeMilliseconds
        self.firstDecodedAudioFrameMilliseconds = firstDecodedAudioFrameMilliseconds
    }
}

/// Monotonic progress snapshot. Counts describe work already completed, not a
/// prediction of the model's final duration.
public struct VocelloQwen3ProgressEvent: Codable, Hashable, Sendable {
    public let generationID: UUID
    public let generatedTokenCount: Int
    public let emittedAudioFrameCount: Int
    public let elapsedMilliseconds: Int

    public init(
        generationID: UUID,
        generatedTokenCount: Int,
        emittedAudioFrameCount: Int,
        elapsedMilliseconds: Int
    ) {
        self.generationID = generationID
        self.generatedTokenCount = generatedTokenCount
        self.emittedAudioFrameCount = emittedAudioFrameCount
        self.elapsedMilliseconds = elapsedMilliseconds
    }
}

/// The single terminal event for a generation session.
public struct VocelloQwen3TerminalEvent: Codable, Hashable, Sendable {
    public let generationID: UUID
    public let outcome: VocelloQwen3TerminalOutcome
    public let generatedTokenCount: Int
    public let emittedAudioFrameCount: Int
    public let elapsedMilliseconds: Int
    /// Final generation statistics captured before the actor releases model
    /// ownership. This remains nil when a producer fails before reporting it.
    public let generationInfo: VocelloQwen3GenerationInfo?
    /// Privacy-safe scalar diagnostics copied while the actor still owns the
    /// loaded model. No text, path, tensor, or raw error crosses this boundary.
    public let diagnostics: VocelloQwen3GenerationDiagnostics?

    public init(
        generationID: UUID,
        outcome: VocelloQwen3TerminalOutcome,
        generatedTokenCount: Int,
        emittedAudioFrameCount: Int,
        elapsedMilliseconds: Int,
        generationInfo: VocelloQwen3GenerationInfo? = nil,
        diagnostics: VocelloQwen3GenerationDiagnostics? = nil
    ) {
        self.generationID = generationID
        self.outcome = outcome
        self.generatedTokenCount = generatedTokenCount
        self.emittedAudioFrameCount = emittedAudioFrameCount
        self.elapsedMilliseconds = elapsedMilliseconds
        self.generationInfo = generationInfo
        self.diagnostics = diagnostics
    }
}

/// Single-resolution terminal latch shared by generation sessions: resolves
/// exactly once, remembers the first requested cancellation reason, and wakes
/// every waiter with the terminal event.
actor VocelloQwen3TerminalState {
    private var terminal: VocelloQwen3TerminalEvent?
    private var waiters: [CheckedContinuation<VocelloQwen3TerminalEvent, Never>] = []
    private var cancellationReason: VocelloQwen3CancellationReason?

    func requestCancellation(_ reason: VocelloQwen3CancellationReason) {
        guard cancellationReason == nil else { return }
        cancellationReason = reason
    }

    func requestedCancellationReason() -> VocelloQwen3CancellationReason {
        cancellationReason ?? .user
    }

    func resolve(_ value: VocelloQwen3TerminalEvent) {
        guard terminal == nil else { return }
        terminal = value
        let pending = waiters
        waiters.removeAll(keepingCapacity: false)
        for waiter in pending { waiter.resume(returning: value) }
    }

    func wait() async -> VocelloQwen3TerminalEvent {
        if let terminal { return terminal }
        return await withCheckedContinuation { waiters.append($0) }
    }
}

/// Concrete production adapter over the opaque loaded Qwen model. Its event
/// channel is bounded and non-suspending: an undrained full buffer fails the
/// session explicitly instead of deadlocking generation. A reserved terminal
/// slot guarantees that completion never depends on consumer progress.
