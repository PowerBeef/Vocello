import Foundation

/// User intent is distinct from automatic stream-completion handoff. Buffered
/// preview duration is not a measure of what the listener actually heard.
enum AudioPlaybackResumePolicy {
    struct Decision: Equatable, Sendable {
        let position: TimeInterval
        let shouldPlay: Bool
    }

    static func explicitPlay(currentTime: TimeInterval, duration: TimeInterval) -> Decision {
        guard duration.isFinite, duration > 0 else {
            return Decision(position: 0, shouldPlay: false)
        }
        let position = currentTime.isFinite ? min(max(currentTime, 0), duration) : 0
        return Decision(position: position >= duration ? 0 : position, shouldPlay: true)
    }
}

/// A user-started operation may contain several engine generations (a batch or
/// long-form project). Choosing other audio or dismissing revokes the whole
/// operation, including chunks that have not arrived yet and its final output.
struct GenerationPlaybackOwnership: Equatable, Sendable {
    private(set) var operationID: UUID?
    private(set) var streamID: UUID?
    private var revoked = false

    mutating func begin(_ operationID: UUID) {
        self.operationID = operationID
        streamID = nil
        revoked = false
    }

    func owns(_ operationID: UUID) -> Bool {
        self.operationID == operationID && !revoked
    }

    mutating func claimStream(_ streamID: UUID, operationID: UUID) -> Bool {
        guard owns(operationID) else { return false }
        self.streamID = streamID
        return true
    }

    func acceptsChunk(_ streamID: UUID?) -> Bool {
        guard let streamID else { return false }
        return !revoked && self.streamID == streamID
    }

    mutating func finishStream(operationID: UUID) {
        guard owns(operationID) else { return }
        streamID = nil
    }

    mutating func revoke() { revoked = true }
}

/// Exactly one transport for the current audio, even with the sidebar hidden.
enum PlaybackTransportPlacement: Equatable {
    case none, studio, sidebar, detail

    static func resolve(hasAudio: Bool, studioOwnsAudio: Bool, sidebarVisible: Bool) -> Self {
        guard hasAudio else { return .none }
        if studioOwnsAudio { return .studio }
        return sidebarVisible ? .sidebar : .detail
    }
}

// MARK: - Live preview decisions

/// Whether the live preview has enough buffered audio to begin, or to resume
/// after an underrun, on its own.
///
/// Two policies, picked per call:
///
/// 1. **Smooth-first estimate**: production generation passes an estimated
///    audio duration before streaming begins. The preview waits for a
///    conservative queue depth, `max(3.25 s, min(8 s, estimate * 0.35))`,
///    capped by the estimate for short clips.
/// 2. **Adaptive fallback**: with no estimate, each underrun raises the
///    prebuffer requirement by 75 % up to a 4x cap, trading fast first audio
///    for pauses that grow further apart.
///
/// Automatic playback must be allowed first (`LivePreviewAutoplayState`); a
/// final file always starts it, because nothing more will be queued.
enum LivePreviewStartPolicy {
    enum Decision: Equatable, Sendable {
        case start
        case rejectAutoplay
        case rejectBuffer
    }

    static func decide(
        autoplayEnabled: Bool,
        queuedChunks: Int,
        queuedDuration: TimeInterval,
        prebufferThreshold: Int,
        minimumBufferedDuration: TimeInterval,
        finalFileAvailable: Bool,
        underrunCount: Int = 0,
        estimate: LivePreviewEstimate? = nil
    ) -> Decision {
        guard autoplayEnabled else { return .rejectAutoplay }
        guard !finalFileAvailable else { return .start }

        if let estimate {
            let requiredBuffer = estimate.requiredBufferDuration(
                minimumBufferedDuration: minimumBufferedDuration
            )
            return queuedDuration >= requiredBuffer ? .start : .rejectBuffer
        }

        let multiplier = min(1.0 + 0.75 * Double(max(underrunCount, 0)), 4.0)
        let scaledChunks = max(
            prebufferThreshold,
            Int((Double(prebufferThreshold) * multiplier).rounded(.up))
        )
        let scaledDuration = minimumBufferedDuration * multiplier
        return queuedChunks >= scaledChunks && queuedDuration >= scaledDuration ? .start : .rejectBuffer
    }
}

/// Where the final file takes over from a live preview, and whether it keeps
/// playing on its own. An unheard preview starts the file from 0; a preview
/// heard to its end (or one whose automatic playback is not allowed) loads
/// the file at 0 without playing it.
struct LivePreviewFinalHandoff: Equatable, Sendable {
    let preserveCurrentTime: TimeInterval
    let shouldAutoPlay: Bool

    static func resolve(
        heardLivePreview: Bool,
        currentTime: TimeInterval,
        previewDuration: TimeInterval = 0,
        duration: TimeInterval,
        autoPlayEnabled: Bool
    ) -> Self {
        guard heardLivePreview else {
            return Self(preserveCurrentTime: 0, shouldAutoPlay: autoPlayEnabled)
        }
        guard autoPlayEnabled else {
            return Self(preserveCurrentTime: 0, shouldAutoPlay: false)
        }

        let safeDuration = max(duration, 0)
        let heardTime = max(currentTime, previewDuration)
        let safeCurrentTime = min(max(heardTime, 0), safeDuration)
        let replayThreshold: TimeInterval = 0.12
        guard safeDuration > replayThreshold,
              safeCurrentTime < safeDuration - replayThreshold else {
            return Self(preserveCurrentTime: 0, shouldAutoPlay: false)
        }
        return Self(preserveCurrentTime: safeCurrentTime, shouldAutoPlay: true)
    }
}

/// What a streamed take's result does to its live preview.
enum LivePreviewCompletionPolicy {
    enum Action: Equatable, Sendable {
        /// The preview never started or has drained: the final file takes
        /// over now (`LivePreviewFinalHandoff` decides where and whether it plays).
        case handOffNow
        /// U05: after an underrun the stream has ended, so the queued tail
        /// will never fill the prebuffer the resume waits for. It plays out
        /// now, and its drain hands over to the file.
        case playOutQueuedTail
        /// The preview plays on, or is held; its drain (or Play) hands over.
        case awaitDrain
    }

    static func decide(
        previewStarted: Bool,
        queuedBuffers: Int,
        isPlaying: Bool,
        allowsAutomaticPlayback: Bool,
        previewDisabled: Bool
    ) -> Action {
        guard previewStarted, queuedBuffers > 0 else { return .handOffNow }
        guard !isPlaying, allowsAutomaticPlayback, !previewDisabled else { return .awaitDrain }
        return .playOutQueuedTail
    }
}

/// Who may start or resume a live preview on its own (U04, U06).
///
/// The Auto-play preference lets a session start once its prebuffer fills,
/// resume after an underrun and continue into its final file. A user or
/// system pause (Pause, Space, an audio interruption, a lost output route,
/// another player, a reference recording) holds the preview: no chunk,
/// underrun recovery or final-file handoff starts it again, only an explicit
/// Play does. An underrun is not a hold. Inside one generation operation (a
/// line batch or a long-form project) a hold and an explicit Play carry to
/// the operation's next take, and survive the session teardown so the
/// operation's joined output respects them; a take outside an operation
/// starts from the preference. Another player or a recording can also hold a
/// take that was submitted but has no session yet.
struct LivePreviewAutoplayState: Equatable, Sendable {
    private(set) var operationID: UUID?
    private(set) var isHeld = false
    private(set) var explicitlyPlayed = false
    private(set) var holdsUpcomingSession = false
    private(set) var isSessionActive = false
    private var autoplayPreference = false

    init() {}

    /// The current session may start, resume or hand off on its own.
    var allowsAutomaticPlayback: Bool {
        isSessionActive && !isHeld && (autoplayPreference || explicitlyPlayed)
    }

    /// A live session begins. The operation's next take keeps a hold and an
    /// explicit Play; any other take starts from the preference.
    mutating func beginSession(operationID: UUID?, autoplayPreference: Bool) {
        let continuesOperation = operationID != nil && operationID == self.operationID
        if !continuesOperation {
            isHeld = false
            explicitlyPlayed = false
        }
        if holdsUpcomingSession {
            isHeld = true
            holdsUpcomingSession = false
        }
        self.operationID = operationID
        self.autoplayPreference = autoplayPreference
        isSessionActive = true
    }

    /// A user or system pause.
    mutating func hold() {
        isHeld = true
    }

    /// Another player or a recording started while a submitted take has no
    /// session yet: that take's session begins held.
    mutating func holdUpcomingSession() {
        holdsUpcomingSession = true
    }

    mutating func clearUpcomingHold() {
        holdsUpcomingSession = false
    }

    /// The listener pressed Play: a hold ends, and later underruns, handoffs
    /// and the operation's next takes play on their own. Playing other audio
    /// keeps a submitted take's upcoming hold.
    mutating func play() {
        isHeld = false
        explicitlyPlayed = true
    }

    /// The session ended (teardown, or the handoff to its final file). An
    /// operation's hold and explicit Play outlive it; a lone take's do not.
    mutating func endSession() {
        isSessionActive = false
        if operationID == nil {
            isHeld = false
            explicitlyPlayed = false
        }
    }

    /// Other audio was loaded: nothing carries over, except that a file the
    /// operation itself hands over stays the operation's.
    mutating func reset(operationID: UUID? = nil) {
        self = Self()
        self.operationID = operationID
    }

    /// Whether a final file with no live session left (a result that did not
    /// stream, an operation's joined output, a preview torn down before its
    /// result) may play on its own.
    func allowsAutomaticFinalPlayback(operationID: UUID?, autoplayPreference: Bool) -> Bool {
        guard autoplayPreference, !holdsUpcomingSession else { return false }
        guard let operationID, operationID == self.operationID else { return true }
        return !isHeld
    }
}

/// Whether a new take's live preview starts at once or waits for the take
/// still playing (U07). Inside one generation operation (a line batch, a
/// long-form project) the previous take plays to its end, live tail and final
/// file alike, and the next take's chunks wait in memory for their turn; a
/// tail its prebuffer or an underrun was holding back is released first,
/// because a successor means its stream has ended. A held or silent previous
/// take, a take of another operation (or of none), or a backlog past the
/// bound starts the new take at once, as before.
enum LivePreviewSuccessionPolicy {
    enum PreviousTake: Equatable, Sendable {
        /// Nothing left that would play on its own.
        case silent
        /// Paused by the listener or the system.
        case held
        /// Audible now (live preview or its final file).
        case playing
        /// Queued live audio that automatic playback would still play.
        case unplayedTail
    }

    enum Decision: Equatable, Sendable {
        case startNow
        case queue
        case releaseTailThenQueue
    }

    /// About 14 MB of 24 kHz 16-bit mono preview audio waiting behind the
    /// take that plays; past it the narration skips ahead to the newest take.
    static let maximumBacklogSeconds: TimeInterval = 300

    static func decide(
        incomingOperationID: UUID?,
        previousOperationID: UUID?,
        previous: PreviousTake,
        backlogSeconds: TimeInterval
    ) -> Decision {
        guard let incomingOperationID, incomingOperationID == previousOperationID else { return .startNow }
        guard backlogSeconds < maximumBacklogSeconds else { return .startNow }
        switch previous {
        case .silent, .held:
            return .startNow
        case .playing:
            return .queue
        case .unplayedTail:
            return .releaseTailThenQueue
        }
    }
}

/// What a completed card shows when it adopts the shared player (U08): that
/// player's state only while it holds this card's file. Otherwise the take is
/// idle at its start and its length comes from the file.
struct SharedPlayerAdoption: Equatable, Sendable {
    let mirrorsSharedPlayer: Bool
    let isPlaying: Bool
    let currentTime: TimeInterval
    /// nil: read the length from the card's file.
    let duration: TimeInterval?

    static func resolve(
        cardFilePath: String,
        sharedFilePath: String?,
        sharedIsPlaying: Bool,
        sharedCurrentTime: TimeInterval,
        sharedDuration: TimeInterval
    ) -> Self {
        guard sharedFilePath == cardFilePath else {
            return Self(mirrorsSharedPlayer: false, isPlaying: false, currentTime: 0, duration: nil)
        }
        return Self(
            mirrorsSharedPlayer: true,
            isPlaying: sharedIsPlaying,
            currentTime: sharedCurrentTime,
            duration: sharedDuration > 0 ? sharedDuration : nil
        )
    }
}
