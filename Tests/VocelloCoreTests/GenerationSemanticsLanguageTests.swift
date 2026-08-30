import Foundation
import QwenVoiceCore
import XCTest

final class GenerationSemanticsLanguageTests: XCTestCase {
    func testAngryMandarinRoutingRequiresBothNativeSpeakerAndChineseOutput() throws {
        let vivianChinese = try Self.angryRequest(speaker: "vivian", language: "chinese")
        let localized = GenerationSemantics.resolvedDeliveryInstruction(
            for: vivianChinese,
            speakerNativeLanguage: "Chinese"
        )
        XCTAssertEqual(localized.language, .mandarin)
        XCTAssertEqual(localized.instruction, EmotionPreset.angryBilingualV3Mandarin)

        let aidenChinese = try Self.angryRequest(speaker: "aiden", language: "chinese")
        let nonNativeFallback = GenerationSemantics.resolvedDeliveryInstruction(
            for: aidenChinese,
            speakerNativeLanguage: "English"
        )
        XCTAssertEqual(nonNativeFallback.language, .english)
        XCTAssertEqual(nonNativeFallback.instruction, EmotionPreset.angryBilingualV3English)

        let vivianEnglish = try Self.angryRequest(speaker: "vivian", language: "english")
        let nonChineseOutputFallback = GenerationSemantics.resolvedDeliveryInstruction(
            for: vivianEnglish,
            speakerNativeLanguage: "Chinese"
        )
        XCTAssertEqual(nonChineseOutputFallback.language, .english)
        XCTAssertEqual(nonChineseOutputFallback.instruction, EmotionPreset.angryBilingualV3English)
    }

    func testMandarinSkipsAndEnglishRetainsExistingDictionReinforcement() throws {
        let vivianChinese = try Self.angryRequest(speaker: "vivian", language: "chinese")
        let mandarin = GenerationSemantics.resolvedDeliveryInstruction(
            for: vivianChinese,
            speakerNativeLanguage: "Chinese"
        )
        XCTAssertEqual(
            GenerationSemantics.englishDictionReinforcedInstruction(
                baseInstruction: mandarin.instruction,
                language: "chinese"
            ),
            EmotionPreset.angryBilingualV3Mandarin
        )

        let aidenEnglish = try Self.angryRequest(speaker: "aiden", language: "english")
        let english = GenerationSemantics.resolvedDeliveryInstruction(
            for: aidenEnglish,
            speakerNativeLanguage: "English"
        )
        XCTAssertEqual(
            GenerationSemantics.englishDictionReinforcedInstruction(
                baseInstruction: english.instruction,
                language: "english"
            ),
            "\(EmotionPreset.angryBilingualV3English) \(GenerationSemantics.englishDictionReinforcement)"
        )
    }

    func testCustomAndLegacyRawInstructionsRemainVerbatim() {
        for raw in [
            EmotionPreset.angryBilingualV3English,
            "Speak with controlled resentment and unmistakable irritation.",
            "Say this in my exact custom style.",
        ] {
            let request = GenerationRequest(
                mode: .custom,
                modelID: "pro_custom_speed",
                text: LanguageFixtures.chinese,
                outputPath: "/tmp/verbatim.wav",
                shouldStream: true,
                languageHint: "chinese",
                payload: .custom(speakerID: "vivian", deliveryStyle: raw)
            )
            let resolved = GenerationSemantics.resolvedDeliveryInstruction(
                for: request,
                speakerNativeLanguage: "Chinese"
            )
            XCTAssertEqual(resolved.instruction, raw)
            XCTAssertEqual(resolved.language, .verbatim)
        }
    }

    func testCanonicalDeliveryCellMismatchFailsClosed() throws {
        let angry = try DeliveryInstructionCell.resolveStrict("angry.normal")
        let mismatch = GenerationRequest(
            mode: .custom,
            modelID: "pro_custom_speed",
            text: LanguageFixtures.english,
            outputPath: "/tmp/mismatch.wav",
            shouldStream: true,
            languageHint: "english",
            payload: .custom(speakerID: "aiden", deliveryStyle: "Not the canonical copy."),
            deliveryInstructionCellID: angry.id
        )
        XCTAssertThrowsError(
            try GenerationSemantics.validateDeliveryInstructionIdentity(for: mismatch)
        ) { error in
            XCTAssertEqual(
                error as? GenerationSemantics.DeliveryInstructionIdentityError,
                .canonicalInstructionMismatch("angry.normal")
            )
        }
    }

    func testGenerationRequestDecodesWhenDeliveryCellIdentityIsAbsent() throws {
        let request = try Self.angryRequest(speaker: "aiden", language: "english")
        var object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(request)) as? [String: Any]
        )
        object.removeValue(forKey: "deliveryInstructionCellID")
        let decoded = try JSONDecoder().decode(
            GenerationRequest.self,
            from: JSONSerialization.data(withJSONObject: object)
        )
        XCTAssertNil(decoded.deliveryInstructionCellID)
        XCTAssertEqual(decoded.payload.deliveryInstructionText, request.payload.deliveryInstructionText)
    }

    func testPinnedLanguageWinsOverScriptDetection() {
        let request = LanguageTestSupport.makeRequest(
            mode: .custom,
            text: LanguageFixtures.french,
            languageHint: Qwen3SupportedLanguage.english.rawValue
        )
        XCTAssertEqual(
            GenerationSemantics.qwenLanguageHint(for: request),
            Qwen3SupportedLanguage.english.rawValue
        )
    }

    func testCustomAutoDetectsFrenchScript() {
        let request = LanguageTestSupport.makeRequest(
            mode: .custom,
            text: LanguageFixtures.french,
            languageHint: Qwen3SupportedLanguage.auto.rawValue
        )
        XCTAssertEqual(
            GenerationSemantics.qwenLanguageHint(for: request),
            Qwen3SupportedLanguage.french.rawValue
        )
    }

    func testCustomAutoFallsBackToEnglishWhenUndetected() {
        let request = LanguageTestSupport.makeRequest(
            mode: .custom,
            text: LanguageFixtures.tooShort,
            languageHint: Qwen3SupportedLanguage.auto.rawValue
        )
        XCTAssertEqual(
            GenerationSemantics.qwenLanguageHint(for: request),
            GenerationSemantics.canonicalCustomWarmLanguage
        )
    }

    func testDesignAutoFallsBackToAutoWhenUndetected() {
        let request = LanguageTestSupport.makeRequest(
            mode: .design,
            text: LanguageFixtures.ambiguousLatin,
            languageHint: Qwen3SupportedLanguage.auto.rawValue
        )
        XCTAssertEqual(
            GenerationSemantics.qwenLanguageHint(for: request),
            Qwen3SupportedLanguage.auto.rawValue
        )
    }

    func testDesignAutoDetectsSpanishScript() {
        let request = LanguageTestSupport.makeRequest(
            mode: .design,
            text: LanguageFixtures.spanish,
            languageHint: Qwen3SupportedLanguage.auto.rawValue
        )
        XCTAssertEqual(
            GenerationSemantics.qwenLanguageHint(for: request),
            Qwen3SupportedLanguage.spanish.rawValue
        )
    }

    func testCloneAutoUsesTargetTextInsteadOfReferenceTranscript() {
        let request = LanguageTestSupport.makeRequest(
            mode: .clone,
            text: LanguageFixtures.english,
            languageHint: Qwen3SupportedLanguage.auto.rawValue
        )
        XCTAssertEqual(
            GenerationSemantics.qwenLanguageHint(
                for: request,
                resolvedCloneTranscript: LanguageFixtures.french
            ),
            Qwen3SupportedLanguage.english.rawValue
        )
    }

    func testCloneExplicitOutputLanguageWinsOverReferenceAndTargetLanguages() {
        let request = LanguageTestSupport.makeRequest(
            mode: .clone,
            text: LanguageFixtures.english,
            languageHint: Qwen3SupportedLanguage.japanese.rawValue
        )
        XCTAssertEqual(
            GenerationSemantics.qwenLanguageHint(
                for: request,
                resolvedCloneTranscript: LanguageFixtures.french
            ),
            Qwen3SupportedLanguage.japanese.rawValue
        )
    }

    func testCloneAutoDetectsFromTargetTextWhenTranscriptMissing() {
        let request = LanguageTestSupport.makeRequest(
            mode: .clone,
            text: LanguageFixtures.german,
            languageHint: Qwen3SupportedLanguage.auto.rawValue
        )
        XCTAssertEqual(
            GenerationSemantics.qwenLanguageHint(for: request),
            Qwen3SupportedLanguage.german.rawValue
        )
    }

    func testUnicodeFastPaths() {
        let cases: [(String, Qwen3SupportedLanguage)] = [
            (LanguageFixtures.japanese, .japanese),
            (LanguageFixtures.korean, .korean),
            (LanguageFixtures.russian, .russian),
            (LanguageFixtures.chinese, .chinese),
        ]
        for (text, expected) in cases {
            let request = LanguageTestSupport.makeRequest(
                mode: .custom,
                text: text,
                languageHint: Qwen3SupportedLanguage.auto.rawValue
            )
            XCTAssertEqual(
                GenerationSemantics.qwenLanguageHint(for: request),
                expected.rawValue,
                "expected \(expected.rawValue) for script snippet"
            )
        }
    }

    func testOmittedLanguageHintBehavesLikeAutoForCustom() {
        let request = LanguageTestSupport.makeRequest(
            mode: .custom,
            text: LanguageFixtures.italian,
            languageHint: nil
        )
        XCTAssertEqual(
            GenerationSemantics.qwenLanguageHint(for: request),
            Qwen3SupportedLanguage.italian.rawValue
        )
    }

    private static func angryRequest(
        speaker: String,
        language: String
    ) throws -> GenerationRequest {
        let cell = try DeliveryInstructionCell.resolveStrict("angry.normal")
        return GenerationRequest(
            mode: .custom,
            modelID: "pro_custom_speed",
            text: language == "chinese" ? LanguageFixtures.chinese : LanguageFixtures.english,
            outputPath: "/tmp/angry-routing.wav",
            shouldStream: true,
            languageHint: language,
            payload: .custom(speakerID: speaker, deliveryStyle: cell.instruction),
            seed: 32_060_828,
            variation: .expressive,
            deliveryInstructionCellID: cell.id
        )
    }
}
