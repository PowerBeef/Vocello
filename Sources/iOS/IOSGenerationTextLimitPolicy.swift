import Foundation
import QwenVoiceCore

/// The counts and routing live in the shared `GenerationTextLimitPolicy`
/// (`Sources/SharedSupport/Services`) since 2026-09-15; the iOS name and the
/// interface-language messages stay here so every call site is unchanged.
typealias IOSGenerationTextLimitPolicy = GenerationTextLimitPolicy

extension GenerationTextLimitPolicy.State {
    @MainActor var helperMessage: String {
        if isOverLimit {
            return warningMessage
        }
        if routesToLongForm {
            return IOSAppLanguage.shared.presentation.longFormGuidance
        }
        if remainingCount == 0 {
            return IOSAppLanguage.shared.presentation.longFormLimit
        }
        return IOSAppLanguage.shared.presentation.charactersRemaining(remainingCount)
    }

    @MainActor var warningMessage: String {
        IOSAppLanguage.shared.presentation.shortenScript(GenerationTextLimitPolicy.longFormScriptLimit)
    }

    @MainActor var readinessTitle: String {
        IOSAppLanguage.shared.presentation.shortenScriptTitle(GenerationTextLimitPolicy.longFormScriptLimit)
    }
}
