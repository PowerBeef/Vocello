import Foundation
import QwenVoiceCore

/// Pure request-boundary assembly shared by the macOS Studio coordinators and their
/// deterministic tests. Keeping this outside SwiftUI makes the exact language, Clone
/// conditioning, seed, and variation values observable before the engine call.
enum MacStudioGenerationRequestFactory {
    static func voiceDesign(
        modelID: String,
        text: String,
        outputPath: String,
        language: Qwen3SupportedLanguage,
        voiceDescription: String,
        deliveryStyle: String,
        seed: UInt64?,
        variation: Qwen3SamplingVariation?,
        generationID: UUID = UUID()
    ) -> GenerationRequest {
        GenerationRequest(
            modelID: modelID,
            text: text,
            outputPath: outputPath,
            shouldStream: true,
            streamingTitle: String(text.prefix(40)),
            languageHint: language.rawValue,
            payload: .design(
                voiceDescription: voiceDescription,
                deliveryStyle: deliveryStyle
            ),
            generationID: generationID,
            seed: seed,
            variation: variation
        )
    }

    static func voiceClone(
        modelID: String,
        text: String,
        outputPath: String,
        language: Qwen3SupportedLanguage,
        referenceAudioPath: String?,
        referenceTranscript: String?,
        preparedVoiceID: String?,
        seed: UInt64?,
        variation: Qwen3SamplingVariation?,
        generationID: UUID = UUID()
    ) -> GenerationRequest? {
        guard let referenceAudioPath else { return nil }
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return nil }

        return GenerationRequest(
            modelID: modelID,
            text: text,
            outputPath: outputPath,
            shouldStream: true,
            streamingTitle: String(text.prefix(40)),
            languageHint: language.rawValue,
            payload: .clone(
                reference: CloneReference(
                    audioPath: referenceAudioPath,
                    transcript: referenceTranscript,
                    preparedVoiceID: preparedVoiceID
                )
            ),
            generationID: generationID,
            seed: seed,
            variation: variation
        )
    }

    /// Built-in Voice: the speaker plus the delivery instruction when the
    /// active package supports it; the delivery cell id travels for the
    /// telemetry matrix, and the language hint is the Studio selection
    /// (`.auto` follows the detected script language inside the engine).
    static func customVoice(
        modelID: String,
        text: String,
        outputPath: String,
        language: Qwen3SupportedLanguage,
        speakerID: String,
        deliveryStyle: String?,
        deliveryInstructionCellID: String?,
        seed: UInt64?,
        variation: Qwen3SamplingVariation?,
        generationID: UUID = UUID()
    ) -> GenerationRequest {
        GenerationRequest(
            mode: .custom,
            modelID: modelID,
            text: text,
            outputPath: outputPath,
            shouldStream: true,
            streamingInterval: GenerationSemantics.appStreamingInterval,
            streamingTitle: String(text.prefix(40)),
            languageHint: language.rawValue,
            payload: .custom(speakerID: speakerID, deliveryStyle: deliveryStyle),
            generationID: generationID,
            seed: seed,
            variation: variation,
            deliveryInstructionCellID: deliveryStyle == nil ? nil : deliveryInstructionCellID
        )
    }
}
