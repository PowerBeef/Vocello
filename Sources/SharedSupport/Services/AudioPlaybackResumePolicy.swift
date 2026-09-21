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
