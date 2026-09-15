import Foundation
import QwenVoiceCore
import XCTest

final class MacStudioGenerationRequestFactoryTests: XCTestCase {
    func testCloneRequestPreservesExactMacStudioSelections() throws {
        let generationID = UUID(uuidString: "B2BF2D07-8BAE-4A1B-A08A-C78DBDDBA681")!
        let request = try XCTUnwrap(
            MacStudioGenerationRequestFactory.voiceClone(
                modelID: "clone-model",
                text: LanguageFixtures.french,
                outputPath: "/tmp/clone.wav",
                language: .auto,
                referenceAudioPath: "/tmp/reference.wav",
                referenceTranscript: LanguageFixtures.english,
                preparedVoiceID: "reviewed-reference",
                seed: 32_060_828,
                variation: .consistent,
                generationID: generationID
            )
        )

        XCTAssertEqual(request.mode, .clone)
        XCTAssertEqual(request.languageHint, Qwen3SupportedLanguage.auto.rawValue)
        XCTAssertEqual(request.generationID, generationID)
        XCTAssertEqual(request.seed, 32_060_828)
        XCTAssertEqual(request.variation, .consistent)
        XCTAssertTrue(request.shouldStream)
        XCTAssertEqual(
            GenerationSemantics.qwenLanguageHint(
                for: request,
                resolvedCloneTranscript: LanguageFixtures.english
            ),
            Qwen3SupportedLanguage.french.rawValue,
            "Clone Auto language must follow target text, never reference-transcript language"
        )

        guard case .clone(let reference) = request.payload else {
            return XCTFail("Expected Clone payload")
        }
        XCTAssertEqual(reference.audioPath, "/tmp/reference.wav")
        XCTAssertEqual(reference.transcript, LanguageFixtures.english)
        XCTAssertEqual(reference.preparedVoiceID, "reviewed-reference")
    }

    func testExplicitCloneOutputLanguageAlwaysWins() throws {
        let request = try XCTUnwrap(
            MacStudioGenerationRequestFactory.voiceClone(
                modelID: "clone-model",
                text: LanguageFixtures.english,
                outputPath: "/tmp/clone.wav",
                language: .french,
                referenceAudioPath: "/tmp/reference.wav",
                referenceTranscript: LanguageFixtures.english,
                preparedVoiceID: nil,
                seed: nil,
                variation: nil
            )
        )

        XCTAssertEqual(
            GenerationSemantics.qwenLanguageHint(for: request),
            Qwen3SupportedLanguage.french.rawValue
        )
    }

    func testCloneRequestRejectsMissingReferenceOrTargetText() {
        XCTAssertNil(
            MacStudioGenerationRequestFactory.voiceClone(
                modelID: "clone-model",
                text: LanguageFixtures.english,
                outputPath: "/tmp/clone.wav",
                language: .auto,
                referenceAudioPath: nil,
                referenceTranscript: nil,
                preparedVoiceID: nil,
                seed: nil,
                variation: nil
            )
        )
        XCTAssertNil(
            MacStudioGenerationRequestFactory.voiceClone(
                modelID: "clone-model",
                text: "  ",
                outputPath: "/tmp/clone.wav",
                language: .auto,
                referenceAudioPath: "/tmp/reference.wav",
                referenceTranscript: nil,
                preparedVoiceID: nil,
                seed: nil,
                variation: nil
            )
        )
    }

    func testVoiceDesignRequestPreservesFrenchAutoBoundary() {
        let generationID = UUID(uuidString: "BCBC06BC-4E97-4C60-A646-69F77D198A1C")!
        let request = MacStudioGenerationRequestFactory.voiceDesign(
            modelID: "design-model",
            text: LanguageFixtures.french,
            outputPath: "/tmp/design.wav",
            language: .auto,
            voiceDescription: "A warm, mature narrator.",
            deliveryStyle: "Speak calmly.",
            seed: 7,
            variation: .balanced,
            generationID: generationID
        )

        XCTAssertEqual(request.mode, .design)
        XCTAssertEqual(request.languageHint, Qwen3SupportedLanguage.auto.rawValue)
        XCTAssertEqual(
            GenerationSemantics.qwenLanguageHint(for: request),
            Qwen3SupportedLanguage.french.rawValue
        )
        XCTAssertEqual(request.generationID, generationID)
        XCTAssertEqual(request.seed, 7)
        XCTAssertEqual(request.variation, .balanced)

        guard case .design(let voiceDescription, let deliveryStyle) = request.payload else {
            return XCTFail("Expected Voice Design payload")
        }
        XCTAssertEqual(voiceDescription, "A warm, mature narrator.")
        XCTAssertEqual(deliveryStyle, "Speak calmly.")
    }

    func testCustomVoiceRequestCarriesSpeakerDeliveryAndSeed() throws {
        let generationID = UUID(uuidString: "5B0B7E52-1F9E-4C7A-9C41-6A2E9B3E1D10")!
        let request = MacStudioGenerationRequestFactory.customVoice(
            modelID: "pro_custom_speed",
            text: "Bonjour tout le monde.",
            outputPath: "/tmp/custom.wav",
            language: .auto,
            speakerID: "ryan",
            deliveryStyle: "Calm and steady",
            deliveryInstructionCellID: "calm/strong",
            seed: 42,
            variation: .balanced,
            generationID: generationID
        )
        XCTAssertEqual(request.mode, .custom)
        XCTAssertEqual(request.modelID, "pro_custom_speed")
        XCTAssertEqual(request.languageHint, "auto")
        XCTAssertEqual(request.generationID, generationID)
        XCTAssertEqual(request.seed, 42)
        XCTAssertEqual(request.variation, .balanced)
        XCTAssertEqual(request.deliveryInstructionCellID, "calm/strong")
        XCTAssertTrue(request.shouldStream)
        XCTAssertEqual(request.streamingTitle, "Bonjour tout le monde.")
        guard case .custom(let speakerID, let deliveryStyle) = request.payload else {
            return XCTFail("expected a custom payload")
        }
        XCTAssertEqual(speakerID, "ryan")
        XCTAssertEqual(deliveryStyle, "Calm and steady")
    }

    func testCustomVoiceRequestDropsTheDeliveryCellWithoutInstructionControl() {
        let request = MacStudioGenerationRequestFactory.customVoice(
            modelID: "pro_custom_speed",
            text: "Hello.",
            outputPath: "/tmp/custom.wav",
            language: .english,
            speakerID: "ryan",
            deliveryStyle: nil,
            deliveryInstructionCellID: "calm/strong",
            seed: nil,
            variation: nil
        )
        XCTAssertNil(request.deliveryInstructionCellID)
        XCTAssertEqual(request.languageHint, "english")
        guard case .custom(_, let deliveryStyle) = request.payload else {
            return XCTFail("expected a custom payload")
        }
        XCTAssertNil(deliveryStyle)
    }
}
