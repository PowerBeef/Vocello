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

        let safeDuration = max(duration, 0)
        let heardTime = max(currentTime, previewDuration)
        let safeCurrentTime = min(max(heardTime, 0), safeDuration)
        let replayThreshold: TimeInterval = 0.12
        guard safeDuration > replayThreshold,
              safeCurrentTime < safeDuration - replayThreshold else {
            return Self(preserveCurrentTime: 0, shouldAutoPlay: false)
        }
        // A held take (S3) keeps where it stopped and waits for Play there.
        return Self(preserveCurrentTime: safeCurrentTime, shouldAutoPlay: autoPlayEnabled)
    }
}

/// What a take promoted from the queue does once its buffered chunks are
/// scheduled again (S2). Long-form segments get no result of their own, so a
/// take whose stream has ended (a successor already waits behind it) cannot
/// rely on more chunks to fill its prebuffer.
enum LivePreviewPromotionPolicy {
    enum Action: Equatable, Sendable {
        /// Its stream has ended: play what it has now.
        case play
        /// Its stream has ended with nothing to play: the next take starts.
        case skipToNext
        /// Playing already, held, or still streaming: nothing to do yet.
        case wait
    }

    static func decide(
        streamEnded: Bool,
        queuedBuffers: Int,
        isPlaying: Bool,
        allowsAutomaticPlayback: Bool
    ) -> Action {
        guard streamEnded, !isPlaying else { return .wait }
        guard queuedBuffers > 0 else { return .skipToNext }
        return allowsAutomaticPlayback ? .play : .wait
    }
}

/// The takes of one generation operation waiting for the take that plays
/// (U07), in take order. Generic over what the player stores, so its order and
/// bookkeeping are unit-tested apart from audio.
///
/// - A take is admitted by its first chunk, or by a prepared long-form
///   segment before any chunk; it consumes the pending estimate, which a
///   later submission then replaces for the take after it.
/// - A chunk goes to the take of its stream; a take admitted without a name
///   adopts the first chunk of a stream that is not the current one.
/// - A result arrives after its take's last chunk and in take order, so it
///   belongs to the newest waiting take; when that take already has one, the
///   result is a take that streamed nothing and waits with its file alone.
/// - The waiting audio is bounded (N1/N2): past `maximumBacklogSeconds`,
///   counted with what the playing take still has to play, the newcomer stops
///   buffering its preview (it keeps its result, so a line still plays from
///   its file) and nothing that plays is cut.
struct LivePreviewTakeQueue<Chunk, Completion, Details> {
    struct Take {
        /// nil until the first chunk names it (a prepared take without a
        /// generation ID, or a completed take that streamed nothing).
        fileprivate(set) var sessionID: String?
        let operationID: UUID?
        let details: Details
        let estimate: LivePreviewEstimate?
        fileprivate(set) var sessionDirectory: String?
        fileprivate(set) var chunks: [Chunk] = []
        fileprivate(set) var completion: Completion?
        fileprivate(set) var queuedSeconds: TimeInterval = 0
        /// Past the bound: later chunks are dropped, the result is kept.
        fileprivate(set) var isPreviewTruncated = false
        fileprivate(set) var hasStoredAudio = false

        var acceptsUnnamedChunks: Bool { sessionID == nil && completion == nil }
    }

    enum Routing: Equatable, Sendable {
        /// No waiting take owns the chunk; the player handles it.
        case notQueued
        /// Stored; `firstAudio` marks the take's first stored audio.
        case stored(firstAudio: Bool)
        /// Its take waits past the bound; the chunk is not kept.
        case dropped
    }

    /// About 14 MB of 24 kHz 16-bit mono preview audio.
    static var maximumBacklogSeconds: TimeInterval { 300 }

    private(set) var takes: [Take] = []

    init() {}

    var isEmpty: Bool { takes.isEmpty }
    var backlogSeconds: TimeInterval { takes.reduce(0) { $0 + $1.queuedSeconds } }

    /// Admits a take behind the take that plays, consuming the pending
    /// estimate (or the fallback derived from its title).
    mutating func admit(
        sessionID: String?,
        operationID: UUID?,
        details: Details,
        sessionDirectory: String?,
        pendingEstimate: inout LivePreviewEstimate?,
        fallbackEstimate: LivePreviewEstimate?,
        currentBacklogSeconds: TimeInterval
    ) {
        var take = Take(
            sessionID: sessionID,
            operationID: operationID,
            details: details,
            estimate: pendingEstimate ?? fallbackEstimate,
            sessionDirectory: sessionDirectory
        )
        pendingEstimate = nil
        take.isPreviewTruncated = currentBacklogSeconds + backlogSeconds >= Self.maximumBacklogSeconds
        takes.append(take)
    }

    /// Routes a streamed chunk (nil: nothing playable in it) to its waiting
    /// take.
    mutating func route(
        _ chunk: Chunk?,
        sessionID: String,
        isCurrentSession: Bool,
        sessionDirectory: String?,
        chunkSeconds: TimeInterval,
        cumulativeDuration: TimeInterval?,
        currentBacklogSeconds: TimeInterval
    ) -> Routing {
        let index: Int
        if let named = takes.lastIndex(where: { $0.sessionID == sessionID }) {
            index = named
        } else if !isCurrentSession, let last = takes.indices.last, takes[last].acceptsUnnamedChunks {
            index = last
        } else {
            return .notQueued
        }
        takes[index].sessionID = sessionID
        if takes[index].sessionDirectory == nil {
            takes[index].sessionDirectory = sessionDirectory
        }
        guard let chunk else { return .stored(firstAudio: false) }
        guard !takes[index].isPreviewTruncated else { return .dropped }
        let queued = cumulativeDuration ?? (takes[index].queuedSeconds + chunkSeconds)
        let increment = max(0, queued - takes[index].queuedSeconds)
        guard currentBacklogSeconds + backlogSeconds + increment <= Self.maximumBacklogSeconds else {
            takes[index].isPreviewTruncated = true
            return .dropped
        }
        takes[index].chunks.append(chunk)
        takes[index].queuedSeconds = max(queued, takes[index].queuedSeconds)
        let firstAudio = !takes[index].hasStoredAudio
        takes[index].hasStoredAudio = true
        return .stored(firstAudio: firstAudio)
    }

    /// Keeps a result for the newest waiting take; false when none waits.
    mutating func attach(_ completion: Completion, details: Details) -> Bool {
        guard let last = takes.indices.last else { return false }
        if takes[last].completion == nil {
            takes[last].completion = completion
        } else {
            var take = Take(
                sessionID: nil,
                operationID: takes[last].operationID,
                details: details,
                estimate: nil,
                sessionDirectory: nil
            )
            take.completion = completion
            takes.append(take)
        }
        return true
    }

    mutating func popFirst() -> Take? {
        takes.isEmpty ? nil : takes.removeFirst()
    }

    /// Removes the takes that match (S1: an operation that no longer owns
    /// playback) and returns them for cleanup.
    @discardableResult
    mutating func removeAll(where shouldRemove: (Take) -> Bool) -> [Take] {
        let removed = takes.filter(shouldRemove)
        takes.removeAll(where: shouldRemove)
        return removed
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

    /// The listener pressed Play on the shared player: a hold ends, including
    /// a submitted take's, and later underruns, handoffs and the operation's
    /// next takes play on their own. Another player starting does not call
    /// this, so a take it held stays held.
    mutating func play() {
        isHeld = false
        explicitlyPlayed = true
        holdsUpcomingSession = false
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
/// before it (U07). Inside one generation operation (a line batch, a
/// long-form project) the previous take plays to its end, live tail and final
/// file alike, and the next take waits in `LivePreviewTakeQueue`; a tail its
/// prebuffer or an underrun was holding back is released first, because a
/// successor means its stream has ended. A pause holds the whole narration
/// (S5): the next take waits behind a held take too, and Play resumes the
/// held take, then the queue. A silent previous take (nothing left to play)
/// or a take of another operation (or of none) starts the new take at once.
enum LivePreviewSuccessionPolicy {
    enum PreviousTake: Equatable, Sendable {
        /// Nothing left that would play.
        case silent
        /// Paused by the listener or the system, with audio left to resume.
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

    static func decide(
        incomingOperationID: UUID?,
        previousOperationID: UUID?,
        previous: PreviousTake
    ) -> Decision {
        guard let incomingOperationID, incomingOperationID == previousOperationID else { return .startNow }
        switch previous {
        case .silent:
            return .startNow
        case .held, .playing:
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
