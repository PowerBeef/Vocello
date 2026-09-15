import Foundation
import QwenVoiceCore

/// Maps the engine snapshot to the sidebar footer's status (formerly part of the
/// retired `AppEngineSelection`).
enum SidebarStatusPresentation {
    static func resolve(
        snapshot: TTSEngineSnapshot,
        prefersInlinePresentation: Bool
    ) -> SidebarStatus {
        if case .starting = snapshot.loadState {
            if let visibleErrorMessage = snapshot.visibleErrorMessage,
               !visibleErrorMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                return .running(
                    ActivityStatus(
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
                    ActivityStatus(
                        label: MacInterfaceText.activityPreparingModel,
                        fraction: nil,
                        presentation: prefersInlinePresentation ? .inlinePlayer : .standaloneCard
                    )
                )
            }
            return .starting
        case .running(_, let label, let fraction):
            return .running(
                ActivityStatus(
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
