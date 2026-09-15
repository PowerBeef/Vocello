import Foundation
import QwenVoiceCore

enum MacShellActivityPresentation: Equatable {
    case inlinePlayer
    case standaloneCard
}

struct MacShellActivity: Equatable {
    let label: String
    let fraction: Double?
    let presentation: MacShellActivityPresentation
}

/// What the sidebar footer says about the in-process engine.
enum MacShellStatus: Equatable {
    case idle
    /// The engine is up but no model weights are resident (idle unload, cold).
    case standby
    case starting
    case running(MacShellActivity)
    case error(String)
    case crashed(String)
}

/// Maps the engine snapshot to the footer status.
enum MacShellStatusPresentation {
    static func resolve(
        snapshot: TTSEngineSnapshot,
        prefersInlinePresentation: Bool
    ) -> MacShellStatus {
        if case .starting = snapshot.loadState {
            if let visibleErrorMessage = snapshot.visibleErrorMessage,
               !visibleErrorMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return .running(
                    MacShellActivity(
                        label: visibleErrorMessage,
                        fraction: nil,
                        presentation: .standaloneCard
                    )
                )
            }
            return .starting
        }

        if let visibleErrorMessage = snapshot.visibleErrorMessage,
           !visibleErrorMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return snapshot.isReady ? .error(visibleErrorMessage) : .crashed(visibleErrorMessage)
        }

        switch snapshot.loadState {
        case .idle:
            return snapshot.isReady ? .standby : .starting
        case .loaded:
            return snapshot.isReady ? .idle : .starting
        case .starting:
            if snapshot.isReady {
                return .running(
                    MacShellActivity(
                        label: MacInterfaceText.activityPreparingModel,
                        fraction: nil,
                        presentation: prefersInlinePresentation ? .inlinePlayer : .standaloneCard
                    )
                )
            }
            return .starting
        case .running(_, let label, let fraction):
            return .running(
                MacShellActivity(
                    label: label.map(MacInterfaceText.activityLabel) ?? MacInterfaceText.activityGeneratingAudio,
                    fraction: fraction,
                    presentation: prefersInlinePresentation ? .inlinePlayer : .standaloneCard
                )
            )
        case .failed(let message):
            return snapshot.isReady ? .error(message) : .crashed(message)
        }
    }
}

/// Which footer surface carries a running activity: the player card while a
/// live stream plays, the status strip otherwise.
struct MacShellFooterPresentation: Equatable {
    let inlinePlayerActivity: MacShellActivity?
    let showsStandaloneStatus: Bool

    static func resolve(status: MacShellStatus, isLiveStream: Bool) -> Self {
        guard isLiveStream,
              case .running(let activity) = status,
              activity.presentation == .inlinePlayer else {
            return Self(inlinePlayerActivity: nil, showsStandaloneStatus: true)
        }
        return Self(inlinePlayerActivity: activity, showsStandaloneStatus: false)
    }
}
