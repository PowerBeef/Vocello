import Foundation

/// Desktop conveniences over the shared iOS generation drafts
/// (`Sources/iOSSupport/Models/GenerationDrafts.swift`, compiled by path):
/// the readiness and routing predicates the macOS screens and the warmup
/// context read. The prewarm hints of the retired macOS drafts had no
/// consumer; `MacGenerationWarmupCoordinator` debounces on its own context.
extension CustomVoiceDraft {
    var hasText: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

extension VoiceDesignDraft {
    var hasVoiceDescription: Bool {
        !voiceDescription.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var hasText: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

extension VoiceCloningDraft {
    var hasText: Bool {
        !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
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
        let collapsed = referenceTranscript
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
        return collapsed.isEmpty ? nil : collapsed
    }
}
