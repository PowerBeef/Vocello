import Foundation
import QwenVoiceCore
import QwenVoiceNative

struct BatchGenerationSheetConfiguration: Identifiable, Equatable {
    let id = UUID()
    let mode: GenerationMode
    let voice: String?
    let emotion: String?
    let deliveryProfile: DeliveryProfile?
    let voiceDescription: String?
    let refAudio: String?
    let refText: String?
    let initialText: String
    let initialSegmentationMode: BatchSegmentationMode

    static func custom(
        draft: CustomVoiceDraft,
        initialText: String = "",
        initialSegmentationMode: BatchSegmentationMode = .lineSeparated
    ) -> BatchGenerationSheetConfiguration {
        BatchGenerationSheetConfiguration(
            mode: .custom,
            voice: draft.selectedSpeaker,
            emotion: draft.emotion,
            deliveryProfile: draft.deliveryProfile,
            voiceDescription: nil,
            refAudio: nil,
            refText: nil,
            initialText: initialText,
            initialSegmentationMode: initialSegmentationMode
        )
    }

    static func design(
        draft: VoiceDesignDraft,
        initialText: String = "",
        initialSegmentationMode: BatchSegmentationMode = .lineSeparated
    ) -> BatchGenerationSheetConfiguration {
        BatchGenerationSheetConfiguration(
            mode: .design,
            voice: nil,
            emotion: draft.emotion,
            deliveryProfile: nil,
            voiceDescription: draft.voiceDescription,
            refAudio: nil,
            refText: nil,
            initialText: initialText,
            initialSegmentationMode: initialSegmentationMode
        )
    }

    static func clone(
        draft: VoiceCloningDraft,
        initialText: String = "",
        initialSegmentationMode: BatchSegmentationMode = .lineSeparated
    ) -> BatchGenerationSheetConfiguration {
        BatchGenerationSheetConfiguration(
            mode: .clone,
            voice: nil,
            emotion: nil,
            deliveryProfile: nil,
            voiceDescription: nil,
            refAudio: draft.referenceAudioPath,
            refText: draft.referenceTranscript.isEmpty ? nil : draft.referenceTranscript,
            initialText: initialText,
            initialSegmentationMode: initialSegmentationMode
        )
    }
}

enum CustomVoicePresentedSheet: Identifiable {
    case batch(BatchGenerationSheetConfiguration)

    var id: UUID {
        switch self {
        case .batch(let configuration):
            return configuration.id
        }
    }
}

enum VoiceDesignPresentedSheet: Identifiable {
    case batch(BatchGenerationSheetConfiguration)
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
    case batch(BatchGenerationSheetConfiguration)

    var id: UUID {
        switch self {
        case .batch(let configuration):
            return configuration.id
        }
    }
}
