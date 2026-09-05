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
