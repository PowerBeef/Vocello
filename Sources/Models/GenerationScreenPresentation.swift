import Foundation
import QwenVoiceCore

enum MacBatchSegmentationMode: String, Equatable {
    case lineSeparated
    case longForm
}

/// What a Studio screen hands the batch sheet: the mode's conditioning as the
/// draft holds it when the sheet opens (the shared iOS drafts, resolved the
/// way the iOS long-form start resolves them), the script routed from the
/// composer, and the segmentation the sheet opens in.
struct MacBatchSheetConfiguration: Identifiable, Equatable {
    let id = UUID()
    let mode: GenerationMode
    let voice: String?
    let emotion: String?
    let deliveryInstructionCellID: String?
    let language: Qwen3SupportedLanguage
    let voiceDescription: String?
    let refAudio: String?
    let refText: String?
    let preparedVoiceID: String?
    let initialText: String
    let initialSegmentationMode: MacBatchSegmentationMode

    /// Built-in Voice: the delivery instruction and its cell id travel only
    /// when the active package supports instructions (the iOS long-form start).
    static func custom(
        draft: CustomVoiceDraft,
        model: TTSModel?,
        initialText: String = "",
        initialSegmentationMode: MacBatchSegmentationMode = .lineSeparated
    ) -> MacBatchSheetConfiguration {
        let supportsInstructionControl = model?.supportsInstructionControl ?? false
        return MacBatchSheetConfiguration(
            mode: .custom,
            voice: draft.selectedSpeaker,
            emotion: supportsInstructionControl ? draft.emotion : nil,
            deliveryInstructionCellID: supportsInstructionControl ? draft.resolvedDeliveryProfile.instructionCellID : nil,
            language: draft.selectedLanguage,
            voiceDescription: nil,
            refAudio: nil,
            refText: nil,
            preparedVoiceID: nil,
            initialText: initialText,
            initialSegmentationMode: initialSegmentationMode
        )
    }

    static func design(
        draft: VoiceDesignDraft,
        initialText: String = "",
        initialSegmentationMode: MacBatchSegmentationMode = .lineSeparated
    ) -> MacBatchSheetConfiguration {
        MacBatchSheetConfiguration(
            mode: .design,
            voice: nil,
            emotion: draft.emotion,
            deliveryInstructionCellID: nil,
            language: draft.selectedLanguage,
            voiceDescription: draft.voiceDescription,
            refAudio: nil,
            refText: nil,
            preparedVoiceID: nil,
            initialText: initialText,
            initialSegmentationMode: initialSegmentationMode
        )
    }

    /// Voice Cloning: `voice` is the selected saved voice's name so History
    /// naming matches single takes; the transcript travels only when present.
    static func clone(
        draft: VoiceCloningDraft,
        voice: String?,
        initialText: String = "",
        initialSegmentationMode: MacBatchSegmentationMode = .lineSeparated
    ) -> MacBatchSheetConfiguration {
        MacBatchSheetConfiguration(
            mode: .clone,
            voice: voice,
            emotion: nil,
            deliveryInstructionCellID: nil,
            language: draft.selectedLanguage,
            voiceDescription: nil,
            refAudio: draft.referenceAudioPath,
            refText: draft.trimmedReferenceTranscript,
            preparedVoiceID: draft.selectedSavedVoiceID,
            initialText: initialText,
            initialSegmentationMode: initialSegmentationMode
        )
    }
}

enum CustomVoicePresentedSheet: Identifiable {
    case batch(MacBatchSheetConfiguration)

    var id: UUID {
        switch self {
        case .batch(let configuration):
            return configuration.id
        }
    }
}

enum VoiceDesignPresentedSheet: Identifiable {
    case batch(MacBatchSheetConfiguration)
    case saveVoice(SavedVoiceSheetConfiguration)

    var id: UUID {
        switch self {
        case .batch(let configuration):
            return configuration.id
        case .saveVoice(let configuration):
            return configuration.id
        }
    }
}

enum VoiceCloningPresentedSheet: Identifiable {
    case batch(MacBatchSheetConfiguration)

    var id: UUID {
        switch self {
        case .batch(let configuration):
            return configuration.id
        }
    }
}
