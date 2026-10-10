import Foundation
import QwenVoiceCore

/// What the saved-voice sheet opens with, per flow (add, save a Clone or Voice
/// Design take, replace a voice's reference), and the name rules it applies
/// before the store does. Pure values, so the flows are unit-tested without
/// the sheet (`MacSavedVoiceSheet`).
struct SavedVoiceSheetConfiguration: Identifiable, Sendable {
    let id = UUID()
    let title: String
    let subtitle: String
    let confirmLabel: String
    let initialName: String
    let initialAudioPath: String
    let initialTranscript: String
    let initialReferenceLanguage: Qwen3SupportedLanguage
    let initialTranscriptReadySource: ReferenceTranscriptionReviewState.ReadySource
    /// The store ID of an existing saved voice that this enrollment replaces.
    /// The duplicate-name guard ignores this name so the user can keep the
    /// same identifier; the repository replaces the old assets in the same
    /// commit. Nil for the add, cloneResult and designResult flows.
    let replacingVoiceID: String?

    init(
        title: String,
        subtitle: String,
        confirmLabel: String,
        initialName: String,
        initialAudioPath: String,
        initialTranscript: String,
        initialReferenceLanguage: Qwen3SupportedLanguage = .auto,
        initialTranscriptReadySource: ReferenceTranscriptionReviewState.ReadySource = .existing,
        replacingVoiceID: String? = nil
    ) {
        self.title = title
        self.subtitle = subtitle
        self.confirmLabel = confirmLabel
        self.initialName = initialName
        self.initialAudioPath = initialAudioPath
        self.initialTranscript = initialTranscript
        self.initialReferenceLanguage = initialReferenceLanguage
        self.initialTranscriptReadySource = initialTranscriptReadySource
        self.replacingVoiceID = replacingVoiceID
    }

    static let manualAdd = SavedVoiceSheetConfiguration(
        title: MacInterfaceText.savedVoiceAddTitle,
        subtitle: MacInterfaceText.savedVoiceAddSubtitle,
        confirmLabel: MacInterfaceText.savedVoiceAddConfirm,
        initialName: "",
        initialAudioPath: "",
        initialTranscript: ""
    )

    static func cloneResult(
        suggestedName: String,
        audioPath: String,
        transcript: String
    ) -> SavedVoiceSheetConfiguration {
        SavedVoiceSheetConfiguration(
            title: MacInterfaceText.historySaveToSavedVoices,
            subtitle: MacInterfaceText.savedVoiceCloneSubtitle,
            confirmLabel: MacInterfaceText.historySaveToSavedVoices,
            initialName: suggestedName,
            initialAudioPath: audioPath,
            initialTranscript: transcript,
            initialReferenceLanguage: PromptLanguageDetector.detect(transcript)
        )
    }

    static func designResult(
        voiceDescription: String,
        audioPath: String,
        transcript: String
    ) -> SavedVoiceSheetConfiguration {
        SavedVoiceSheetConfiguration(
            title: MacInterfaceText.savedVoiceDesignTitle,
            subtitle: MacInterfaceText.savedVoiceDesignSubtitle,
            confirmLabel: MacInterfaceText.historySaveToSavedVoices,
            initialName: SavedVoiceNameSuggestion.designResultName(from: voiceDescription),
            initialAudioPath: audioPath,
            initialTranscript: transcript,
            initialReferenceLanguage: PromptLanguageDetector.detect(transcript)
        )
    }

    /// The Saved Voices "Replace reference" flow: the existing name and
    /// transcript are pre-filled and the audio path stays blank so the user
    /// picks a new clip. The replaced voice is named by its store ID (U16): the
    /// store keeps spaces and most punctuation in an ID, so an ID re-derived
    /// from the display name missed any voice whose name has them.
    static func replaceReference(
        voiceID: String,
        name: String,
        transcript: String,
        referenceLanguage: Qwen3SupportedLanguage = .auto
    ) -> SavedVoiceSheetConfiguration {
        SavedVoiceSheetConfiguration(
            title: MacInterfaceText.savedVoiceReplaceTitle,
            subtitle: MacInterfaceText.savedVoiceReplaceSubtitle,
            confirmLabel: MacInterfaceText.savedVoiceReplaceConfirm,
            initialName: name,
            initialAudioPath: "",
            initialTranscript: transcript,
            initialReferenceLanguage: referenceLanguage == .auto
                ? PromptLanguageDetector.detect(transcript)
                : referenceLanguage,
            replacingVoiceID: voiceID
        )
    }

    /// The clip the pre-filled transcript describes (U15): the generated take
    /// it was spoken from, or the replaced reference, which this sheet never
    /// shows, so picking any clip there clears it and runs recognition.
    var initialTranscriptClip: ReferenceTranscriptionReviewState.TranscriptClip {
        guard !initialTranscript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return .unbound
        }
        if replacingVoiceID != nil { return .replacedReference }
        let path = initialAudioPath.trimmingCharacters(in: .whitespacesAndNewlines)
        return path.isEmpty ? .unbound : .clip(path)
    }

    enum NameIssue: Equatable, Sendable {
        /// Nothing is left once the store's normalization runs.
        case needsCharacters
        /// Another saved voice already uses this store ID.
        case exists(String)
    }

    /// The sheet's name check in the store's own normalization
    /// (`NativeSavedVoiceNaming`, U16), so it agrees with the repository: the
    /// sheet compared an underscored form with IDs that keep their spaces, and
    /// a duplicate surfaced only when saving. The repository's file check is
    /// case-insensitive on the default volume, so this one is too. The voice
    /// being replaced is not a collision. A name still needs one letter, digit
    /// or underscore, as before.
    static func nameIssue(
        for trimmedName: String,
        existingVoiceIDs: Set<String>,
        replacingVoiceID: String?
    ) -> NameIssue? {
        guard !trimmedName.isEmpty else { return nil }
        let storeID = NativeSavedVoiceNaming.normalizedName(trimmedName)
        guard !storeID.isEmpty,
              !SavedVoiceNameSanitizer.normalizedName(trimmedName).isEmpty else {
            return .needsCharacters
        }
        if storeID == replacingVoiceID { return nil }
        let collides = existingVoiceIDs.contains {
            $0.caseInsensitiveCompare(storeID) == .orderedSame
        }
        return collides ? .exists(storeID) : nil
    }
}

enum SavedVoiceNameSanitizer {
    static func normalizedName(_ rawName: String) -> String {
        rawName
            .replacingOccurrences(
                of: #"[^\w\s-]"#,
                with: "",
                options: .regularExpression
            )
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: " ", with: "_")
    }
}

enum SavedVoiceNameSuggestion {
    /// Interface-language fallback (`vocello.mac.savedVoice.designedVoiceFallback`).
    static var designedVoiceFallback: String { MacInterfaceText.savedVoiceDesignedVoiceFallback }

    static func designResultName(
        from voiceDescription: String,
        fallback: String = designedVoiceFallback,
        maxLength: Int = 36
    ) -> String {
        let normalized = SavedVoiceNameSanitizer.normalizedName(voiceDescription)
        guard !normalized.isEmpty else { return fallback }
        guard normalized.count > maxLength else { return normalized }

        let components = normalized.split(separator: "_")
        var shortened = ""
        for component in components {
            let separator = shortened.isEmpty ? "" : "_"
            let candidate = shortened + separator + component
            if candidate.count > maxLength {
                break
            }
            shortened = candidate
        }

        if shortened.isEmpty {
            shortened = String(normalized.prefix(maxLength))
                .trimmingCharacters(in: CharacterSet(charactersIn: "_-"))
        }

        return shortened.isEmpty ? fallback : shortened
    }
}
