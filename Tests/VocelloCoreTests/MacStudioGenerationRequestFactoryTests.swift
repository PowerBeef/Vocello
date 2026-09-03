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
}
