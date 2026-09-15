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

    /// The reference transcript as conditioning: nil when blank.
    var trimmedReferenceTranscript: String? {
        let trimmed = referenceTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
