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

    /// The reference transcript as conditioning: nil when blank, and always a
    /// single line.
    ///
    /// The field it comes from is a multi-line `TextField` (it has to be — the
    /// transcript is what a user checks against the reference clip, and on one
    /// line it truncated mid-word even at the widest window). That means Return
    /// inserts a newline instead of committing, so interior line breaks reach
    /// this property. A transcript of spoken audio has no line structure to
    /// preserve, and a stray newline is a token the model never heard, so every
    /// run of whitespace collapses to one space before it becomes conditioning.
    var trimmedReferenceTranscript: String? {
        TranscriptNormalization.conditioningLine(referenceTranscript)
    }
}
