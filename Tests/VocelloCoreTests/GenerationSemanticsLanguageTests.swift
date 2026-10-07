import Foundation
@testable import QwenVoiceCore
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

    /// CORE-11: a script decides Auto only when it carries most of the text.
    func testStrayNonLatinWordsDoNotRedirectAutoLanguage() {
        let cases: [(String, Qwen3SupportedLanguage)] = [
            ("The capital of Japan is 東京, a city of many trains.", .english),
            ("Our friend Сергей will visit the museum tomorrow morning.", .english),
            ("Nous avons visité Séoul (서울) pendant les vacances d'été.", .french),
            ("我喜欢用iPhone拍照片。", .chinese),
            ("今日はAppleのiPhoneを買いました。", .japanese),
            ("오늘 서울에서 iPhone을 샀습니다.", .korean),
            ("Я купил новый iPhone в Москве.", .russian),
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
                text
            )
        }
    }

    /// U02: within East Asian text, kana or Hangul picks Japanese or Korean
    /// only as a real share of the script. One の, ・, ー, katakana brand or
    /// Korean name used to flip a Chinese take (spoken as garbled speech).
    func testEastAsianAutoLanguageNeedsAMeaningfulKanaOrHangulShare() {
        let cases: [(String, Qwen3SupportedLanguage)] = [
            // Chinese with a stray kana, kana punctuation or Hangul name.
            ("我最喜欢的动画是《鬼滅の刃》，每个周末都会和朋友一起看。", .chinese),
            ("我の世界很大，今天想和大家分享一下。", .chinese),
            ("哈利・波特是一本很好的书。", .chinese),
            ("列夫・托尔斯泰是一位伟大的俄国作家。", .chinese),
            ("我昨天买了一台ソニー的相机。", .chinese),
            ("我很喜欢《君の名は。》这部电影。", .chinese),
            ("我的朋友김민수明天来北京。", .chinese),
            ("我喜欢听아이유的歌。", .chinese),
            ("这是第一期——ー——的节目。", .chinese),
            // Japanese, including kanji-dense text and katakana alone.
            ("今日はいい天気です。", .japanese),
            (LanguageFixtures.japanese, .japanese),
            ("東京駅で火災、3人けが", .japanese),
            ("日本政府は新たな経済対策を発表した。", .japanese),
            ("コーヒーをください。", .japanese),
            ("ソニー", .japanese),
            // Korean, with a stray kana.
            (LanguageFixtures.korean, .korean),
            ("김치찌개를 좋아해요. 東京の", .korean),
            // A kanji-only heading cannot be told apart from Chinese by script:
            // it resolves to Chinese (pick Japanese explicitly for it).
            ("第一章　東京駅", .chinese),
        ]
        for (text, expected) in cases {
            let request = LanguageTestSupport.makeRequest(
                mode: .custom,
                text: text,
                languageHint: Qwen3SupportedLanguage.auto.rawValue
            )
            XCTAssertEqual(GenerationSemantics.qwenLanguageHint(for: request), expected.rawValue, text)
            XCTAssertEqual(GenerationSemantics.autoDetectedLanguage(in: text), expected, text)
        }
    }

    /// U02: the Studio chip reads `autoDetectedLanguage`, the resolver the
    /// engine applies to Auto, so the chip names the language the take is sent
    /// with (`.auto` where the engine falls back).
    func testStudioChipLanguageMatchesTheEngineAutoLanguage() {
        let texts = [
            LanguageFixtures.chinese, LanguageFixtures.japanese, LanguageFixtures.korean,
            LanguageFixtures.russian, LanguageFixtures.english, LanguageFixtures.italian,
            "哈利・波特是一本很好的书。", "我昨天买了一台ソニー的相机。", "我的朋友김민수明天来北京。",
            "你好", "...", "",
        ]
        for text in texts {
            for mode in [GenerationMode.design, .clone] {
                let request = LanguageTestSupport.makeRequest(
                    mode: mode,
                    text: text,
                    languageHint: Qwen3SupportedLanguage.auto.rawValue
                )
                XCTAssertEqual(
                    GenerationSemantics.autoDetectedLanguage(in: text).rawValue,
                    GenerationSemantics.qwenLanguageHint(for: request),
                    "\(mode.rawValue): \(text)"
                )
            }
        }
        XCTAssertEqual(GenerationSemantics.autoDetectedLanguage(in: "..."), .auto)
    }

    func testScriptUnitsIgnoreKanaPunctuation() {
        let units = GenerationSemantics.ScriptUnits(counting: "哈利・波特ー\u{309B}\u{30A0}")
        XCTAssertEqual(units.han, 4)
        XCTAssertEqual(units.kana, 0)
        XCTAssertEqual(units.otherWords, 0)
        XCTAssertEqual(GenerationSemantics.ScriptUnits(counting: "ソニー").kana, 2)
    }

    func testScriptUnitsCountCharactersAndWords() {
        let units = GenerationSemantics.ScriptUnits(counting: "Tokyo 東京, Café\u{301} and Москва 2026!")
        XCTAssertEqual(units.han, 2)
        XCTAssertEqual(units.otherWords, 3, "a combining mark continues its word")
        XCTAssertEqual(units.cyrillicWords, 1)
        XCTAssertEqual(units.total, 6)
        XCTAssertEqual(GenerationSemantics.ScriptUnits(counting: "12:30 — !?").total, 0)
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
