import QwenVoiceCore
import XCTest

final class LanguageSelectionPresentationTests: XCTestCase {
    func testPromptContentFollowsSpeechThenDetectionThenInterface() {
        XCTAssertEqual(StudioPromptContent.language(
            selected: .french, detected: .english, interfaceLanguage: "en"
        ), .french)
        XCTAssertEqual(StudioPromptContent.language(
            selected: .auto, detected: .japanese, interfaceLanguage: "fr"
        ), .japanese)
        XCTAssertEqual(StudioPromptContent.language(
            selected: .auto, detected: .auto, interfaceLanguage: "fr-CA"
        ), .french)
        XCTAssertEqual(StudioPromptContent.language(
            selected: .auto, detected: .auto, interfaceLanguage: "pt-BR"
        ), .portuguese)
        XCTAssertEqual(StudioPromptContent.language(
            selected: .auto, detected: .auto, interfaceLanguage: "ar"
        ), .english)
    }

    func testEverySpeechLanguageHasCompleteUsablePromptContent() {
        let english = StudioPromptContent.copy(for: .english)
        let presetIDs = Set(EmotionPreset.all.map(\.id))
        for language in Qwen3SupportedLanguage.allCases where language != .auto {
            let copy = StudioPromptContent.copy(for: language)
            XCTAssertFalse(StudioPromptContent.directionalHintAdvisory(in: language).isEmpty)
            XCTAssertEqual(copy.starters.count, english.starters.count, language.rawValue)
            XCTAssertEqual(Set(copy.starters).count, copy.starters.count, language.rawValue)
            XCTAssertEqual(Set(copy.deliveries.keys), presetIDs, language.rawValue)
            for starter in copy.starters {
                XCTAssertFalse(starter.isEmpty)
                XCTAssertLessThanOrEqual(starter.count, VoiceDesignBriefCatalog.descriptionLimit)
            }
            for preset in EmotionPreset.all {
                let delivery = StudioPromptContent.delivery(preset, in: language)
                XCTAssertFalse(delivery.name.isEmpty)
                XCTAssertFalse(delivery.detail.isEmpty)
                XCTAssertNotEqual(delivery.detail, preset.instruction(for: preset.shippedIntensity))
            }
            if language != .english {
                XCTAssertNotEqual(StudioPromptContent.directionalHintAdvisory(in: language),
                                  EmotionPreset.directionalHintAdvisory)
                XCTAssertNotEqual(copy.starters, english.starters, language.rawValue)
                XCTAssertNotEqual(copy.deliveries["sad"]?.detail, english.deliveries["sad"]?.detail)
            }
        }
    }

    func testLocalizedStartingPointAndUserEditsReachGenerationVerbatim() {
        let starter = VoiceDesignBriefCatalog.startingPoints(in: .french)[1]
        let editedBrief = starter + " Une légère voix rauque."
        let customDelivery = "Parler doucement, avec des pauses."
        // Merely changing the available suggestions must not replace the chosen/edited brief.
        XCTAssertNotEqual(VoiceDesignBriefCatalog.startingPoints(in: .german)[1], starter)
        let request = MacStudioGenerationRequestFactory.voiceDesign(
            modelID: "design-model", text: LanguageFixtures.french,
            outputPath: "/tmp/design.wav", language: .german,
            voiceDescription: editedBrief, deliveryStyle: customDelivery,
            seed: 7, variation: .balanced
        )
        guard case .design(let description, let delivery) = request.payload else {
            return XCTFail("Expected Voice Design payload")
        }
        XCTAssertEqual(description, editedBrief)
        XCTAssertEqual(delivery, customDelivery)
        XCTAssertEqual(request.languageHint, Qwen3SupportedLanguage.german.rawValue)
    }

    func testDeliveryPresentationNeverReplacesCanonicalInstruction() throws {
        let preset = try XCTUnwrap(EmotionPreset.preset(id: "happy"))
        let profile = DeliveryProfile.preset(preset, intensity: preset.shippedIntensity)
        for language in Qwen3SupportedLanguage.allCases where language != .auto {
            let displayed = StudioPromptContent.delivery(preset, in: language)
            let request = MacStudioGenerationRequestFactory.customVoice(
                modelID: "custom-model", text: LanguageFixtures.french,
                outputPath: "/tmp/custom.wav", language: language, speakerID: "aiden",
                deliveryStyle: profile.finalInstruction, deliveryInstructionCellID: profile.instructionCellID,
                seed: 7, variation: .balanced
            )
            guard case .custom(_, let instruction) = request.payload else {
                return XCTFail("Expected CustomVoice payload")
            }
            XCTAssertEqual(instruction, profile.finalInstruction)
            XCTAssertNotEqual(instruction, displayed.name)
            XCTAssertNotEqual(instruction, displayed.detail)
            XCTAssertEqual(request.deliveryInstructionCellID, profile.instructionCellID)
        }
    }

    func testEffectiveFollowsDetectionWhileAutoSelected() {
        XCTAssertEqual(
            LanguageSelectionPresentation.effective(selected: .auto, detected: .french),
            .french
        )
        XCTAssertEqual(
            LanguageSelectionPresentation.effective(selected: .auto, detected: .auto),
            .auto
        )
        XCTAssertEqual(
            LanguageSelectionPresentation.effective(selected: .german, detected: .french),
            .german
        )
    }

    func testButtonLabelUsesEffectiveLanguageName() {
        XCTAssertEqual(
            LanguageSelectionPresentation.buttonLabel(selected: .auto, detected: .french),
            Qwen3SupportedLanguage.french.displayName
        )
        XCTAssertEqual(
            LanguageSelectionPresentation.buttonLabel(selected: .auto, detected: .auto),
            Qwen3SupportedLanguage.auto.displayName
        )
        XCTAssertEqual(
            LanguageSelectionPresentation.buttonLabel(selected: .spanish, detected: .french),
            Qwen3SupportedLanguage.spanish.displayName
        )
    }

    func testIsFollowingDetection() {
        XCTAssertTrue(
            LanguageSelectionPresentation.isFollowingDetection(selected: .auto, detected: .english)
        )
        XCTAssertFalse(
            LanguageSelectionPresentation.isFollowingDetection(selected: .auto, detected: .auto)
        )
        XCTAssertFalse(
            LanguageSelectionPresentation.isFollowingDetection(selected: .french, detected: .english)
        )
    }
}
