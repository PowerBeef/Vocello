import Foundation
import QwenVoiceNative

enum AppEngineSelection: Equatable {
    static let defaultSelection: Self = .native

    case native

    init(environment _: [String: String] = ProcessInfo.processInfo.environment) {
        self = .native
    }

    static func current(environment _: [String: String] = ProcessInfo.processInfo.environment) -> Self {
        .native
    }

    func effectiveSelection() -> Self {
        self
    }

    func requiresManualInitialization() -> Bool {
        true
    }

    @MainActor
    func makeEngine() -> any MacTTSEngine {
        return XPCNativeEngineClient()
    }

    @MainActor
    func resolveSidebarStatus(
        ttsEngineSnapshot: TTSEngineSnapshot,
        prefersInlinePresentation: Bool
    ) -> SidebarStatus {
        Self.nativeSidebarStatus(
            from: ttsEngineSnapshot,
            prefersInlinePresentation: prefersInlinePresentation
        )
    }

    @MainActor
    func clearSidebarError(
        ttsEngineStore: TTSEngineStore
    ) {
        ttsEngineStore.clearVisibleError()
    }

    private static func nativeSidebarStatus(
        from snapshot: TTSEngineSnapshot,
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
