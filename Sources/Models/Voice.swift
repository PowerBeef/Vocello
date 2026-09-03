import Foundation
import QwenVoiceCore
import QwenVoiceNative

/// An enrolled voice reference for voice cloning.
struct Voice: Identifiable, Hashable {
    let id: String          // same as name
    let name: String
    let wavPath: String
    let hasTranscript: Bool
    /// Forwarded from `PreparedVoice.qualityWarnings`. Tokens come from
    /// `MLXTTSEngine.savedReferenceQualityWarnings(forAudioAt:)` —
    /// e.g. `reference_duration_short`, `reference_duration_long`,
    /// `reference_duration_excessive` (hard-block, >60 s),
    /// `reference_quality_unreadable`. UI surfaces these via warning
    /// dialogs at enrollment + indicator badges in the saved-voices
    /// list.
    let qualityWarnings: [String]
    /// Privacy-safe enrollment provenance persisted by the prepared-voice repository.
    /// Reference language describes the saved clip only; it never overrides a future
    /// Clone request's independently selected output language.
    let enrollmentMetadata: PreparedVoiceEnrollmentMetadata?
    /// Cached `headline` for the first warning token. Computed once at
    /// init time so the saved-voices list rendering doesn't re-run the
    /// `PreparedVoiceQualityWarning.headline(for:)` lookup for every
    /// row on every body recomputation.
    let qualityHeadline: String?

    func loadTranscript(fileManager: FileManager = .default) throws -> String? {
        let txtURL = URL(fileURLWithPath: wavPath).deletingPathExtension().appendingPathExtension("txt")
        guard fileManager.fileExists(atPath: txtURL.path) else { return nil }
        return try String(contentsOfFile: txtURL.path, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    init(
        name: String,
        wavPath: String,
        hasTranscript: Bool,
        qualityWarnings: [String] = [],
        enrollmentMetadata: PreparedVoiceEnrollmentMetadata? = nil
    ) {
        self.id = name
        self.name = name
        self.wavPath = wavPath
        self.hasTranscript = hasTranscript
        self.qualityWarnings = qualityWarnings
        self.enrollmentMetadata = enrollmentMetadata
        self.qualityHeadline = qualityWarnings.first.flatMap(PreparedVoiceQualityWarning.headline(for:))
    }

    init(preparedVoice: PreparedVoice) {
        self.id = preparedVoice.id
        self.name = preparedVoice.name
        self.wavPath = preparedVoice.audioPath
        self.hasTranscript = preparedVoice.hasTranscript
        self.qualityWarnings = preparedVoice.qualityWarnings
        self.enrollmentMetadata = preparedVoice.enrollmentMetadata
        self.qualityHeadline = preparedVoice.qualityWarnings.first.flatMap(PreparedVoiceQualityWarning.headline(for:))
    }
}
