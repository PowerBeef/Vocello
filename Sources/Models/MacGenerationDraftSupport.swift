import Foundation

/// Desktop conveniences over the shared iOS generation drafts
/// (`Sources/iOSSupport/Models/GenerationDrafts.swift`, compiled by path):
/// the readiness and routing predicates the macOS screens and the warmup
/// context read. The prewarm hints of the retired macOS drafts had no
/// consumer; `MacGenerationWarmupCoordinator` debounces on its own context.
extension CustomVoiceDraft {
    /// The script has a letter or a digit to speak (U29), the shared rule
    /// the iOS Studio gates Generate on.
    var hasText: Bool {
        GenerationTextLimitPolicy.hasSpeakableText(text)
    }
}

extension VoiceDesignDraft {
    var hasVoiceDescription: Bool {
        GenerationTextLimitPolicy.hasVoiceDescription(voiceDescription)
    }

    /// The script has a letter or a digit to speak (U29), the shared rule
    /// the iOS Studio gates Generate on.
    var hasText: Bool {
        GenerationTextLimitPolicy.hasSpeakableText(text)
    }
}

extension VoiceCloningDraft {
    /// The script has a letter or a digit to speak (U29), the shared rule
    /// the iOS Studio gates Generate on.
    var hasText: Bool {
        GenerationTextLimitPolicy.hasSpeakableText(text)
    }

}
