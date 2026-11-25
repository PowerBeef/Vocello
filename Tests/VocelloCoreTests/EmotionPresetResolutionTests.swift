import CryptoKit
import Foundation
@testable import QwenVoiceCore
import XCTest

/// Instruction-string → (preset, tier) resolution. The regression this pins:
/// Neutral's tier strings are identical, and a resolver that checks `.normal`
/// first synced the macOS picker to `.normal` on appearance, after which every
/// preset pick silently emitted the normal-tier copy — reversing DP-8's
/// ship-strong decision without anyone deciding it (2026-08-04 audit, F4).
final class EmotionPresetResolutionTests: XCTestCase {
    func testAngryBilingualV3CopyAndCanonicalDigestsAreExact() throws {
        let angry = try XCTUnwrap(EmotionPreset.preset(id: "angry"))
        XCTAssertEqual(
            angry.instruction(for: .normal),
            "Sound fiercely angry and frustrated. Use a tense, forceful voice, hard clipped consonants, strong energy, and fast emphatic pacing."
        )
        XCTAssertEqual(
            angry.instruction(for: .strong),
            "Speak with fierce controlled anger and seething resentment. Use a harsher tense resonance, biting consonants, compressed forceful phrasing, and hard deliberate stress; sound openly hostile and confrontational rather than excited or triumphant."
        )
        let english = try XCTUnwrap(
            angry.instructionVariant(for: .normal, language: .english)
        )
        let mandarin = try XCTUnwrap(
            angry.instructionVariant(for: .normal, language: .mandarin)
        )
        XCTAssertEqual(english.version, "angry-bilingual-v3")
        XCTAssertEqual(english.instruction, angry.instruction(for: .normal))
        XCTAssertEqual(mandarin.version, "angry-bilingual-v3")
        XCTAssertEqual(
            mandarin.instruction,
            "语气要强烈愤怒、充满挫败感。使用紧张有力的声音、硬朗辅音、短促重音、强能量和快速强调的节奏。"
        )
        XCTAssertEqual(Self.sha256(english.instruction), "e029abc96a23c5afe766f0dd1e57335ac1791074bc5882e86754b9d92d7e9fdf")
        XCTAssertEqual(Self.sha256(mandarin.instruction), "5d08a1b31bfa30c53741656f259ab0184c36f192b35b647afa78349735e9606d")
        XCTAssertNil(angry.instructionVariant(for: .strong, language: .mandarin))
    }

    func testStrictDeliveryCellRequiresExplicitValidTier() throws {
        let cell = try DeliveryInstructionCell.resolveStrict("calm.strong")
        XCTAssertEqual(cell.id, "calm.strong")
        XCTAssertEqual(cell.preset.id, "calm")
        XCTAssertEqual(cell.intensity, .strong)
        XCTAssertEqual(cell.instruction, cell.preset.instruction(for: .strong))

        XCTAssertThrowsError(try DeliveryInstructionCell.resolveStrict("calm"))
        XCTAssertThrowsError(try DeliveryInstructionCell.resolveStrict("calm.loud"))
        XCTAssertThrowsError(try DeliveryInstructionCell.resolveStrict("missing.strong"))
        XCTAssertThrowsError(try DeliveryInstructionCell.resolveStrict("calm.strong.extra"))
    }

    func testIdenticalTierStringsResolveToStrong() {
        let neutral = EmotionPreset.preset(id: "neutral")
        XCTAssertNotNil(neutral)
        let match = EmotionPreset.matchInstruction(EmotionPreset.neutralPresetInstruction)
        XCTAssertEqual(match?.preset.id, "neutral")
        XCTAssertEqual(match?.intensity, .strong)
    }

    func testEveryPresetStrongInstructionRoundTrips() {
        // Derived from the live roster rather than restated: a hardcoded list
        // silently passes for presets that no longer exist.
        for preset in EmotionPreset.all {
            let match = EmotionPreset.matchInstruction(preset.instruction(for: .strong))
            XCTAssertEqual(match?.preset.id, preset.id, "strong instruction of \(preset.id)")
            XCTAssertEqual(match?.intensity, .strong, "strong instruction of \(preset.id)")
        }
    }

    func testDistinctNormalTierStringStillResolvesToNormal() {
        // Legacy drafts that stored a genuine normal-tier string keep resolving
        // to exactly what they stored (same contract as the iOS legacy-draft
        // resolver); only identical-copy ties prefer strong.
        for preset in EmotionPreset.all where preset.id != "neutral" {
            let normalInstruction = preset.instruction(for: .normal)
            guard normalInstruction != preset.instruction(for: .strong) else { continue }
            let match = EmotionPreset.matchInstruction(normalInstruction)
            XCTAssertEqual(match?.preset.id, preset.id)
            XCTAssertEqual(match?.intensity, .normal)
        }
    }

    func testResolutionTrimsAndIgnoresCase() {
        guard let happy = EmotionPreset.preset(id: "happy") else {
            return XCTFail("happy preset missing")
        }
        let noisy = "  " + happy.instruction(for: .strong).uppercased() + "\n"
        let match = EmotionPreset.matchInstruction(noisy)
        XCTAssertEqual(match?.preset.id, "happy")
        XCTAssertEqual(match?.intensity, .strong)
    }

    func testUnknownAndEmptyTextResolveToNil() {
        XCTAssertNil(EmotionPreset.matchInstruction("speak like a pirate"))
        XCTAssertNil(EmotionPreset.matchInstruction("   "))
        XCTAssertNil(EmotionPreset.matchInstruction(""))
    }

    func testShippedTierIsPerPreset() {
        // The measured mapping (DP-22 branch (a), maintainer call 2026-08-15):
        // happy and angry ship their normal copy — the only channel ever
        // measured to carry the happy/angry distinction — and everything else
        // keeps the DP-8 strong anchor. Membership changes require a new
        // measurement, not taste.
        let rosterIDs = Set(EmotionPreset.all.map(\.id))
        XCTAssertEqual(EmotionPreset.normalTierShippedIDs, ["happy", "angry"])
        XCTAssertTrue(EmotionPreset.normalTierShippedIDs.isSubset(of: rosterIDs))
        for preset in EmotionPreset.all {
            let expected: EmotionIntensity =
                EmotionPreset.normalTierShippedIDs.contains(preset.id) ? .normal : .strong
            XCTAssertEqual(preset.shippedIntensity, expected, preset.id)
        }
    }

    func testShippedTierProfileEmitsTheShippedCopy() {
        // A pick made through either platform's selection path resolves the
        // preset's shipped tier; the profile's final instruction must be that
        // tier's copy verbatim (and, for the normal-shipping presets, must
        // differ from the strong copy the pair used to ship).
        for preset in EmotionPreset.all {
            let profile = DeliveryProfile.preset(preset, intensity: preset.shippedIntensity)
            XCTAssertEqual(
                profile.finalInstruction,
                preset.instruction(for: preset.shippedIntensity),
                preset.id
            )
        }
        for id in EmotionPreset.normalTierShippedIDs {
            guard let preset = EmotionPreset.preset(id: id) else {
                return XCTFail("\(id) missing from roster")
            }
            XCTAssertNotEqual(
                preset.instruction(for: .normal), preset.instruction(for: .strong),
                "\(id) tiers must stay distinct for the shipped-tier change to mean anything"
            )
        }
    }

    func testRemediatedPresetTiersRemainDistinct() throws {
        for id in ["happy", "angry", "fearful", "surprised"] {
            let preset = try XCTUnwrap(EmotionPreset.preset(id: id))
            XCTAssertNotEqual(
                preset.instruction(for: .normal),
                preset.instruction(for: .strong),
                "\(id) must preserve two independently addressable experiment cells"
            )
        }
    }

    func testRemediatedPresetDictionAppendDecisionsRemainStableAcrossTiers() throws {
        for id in ["happy", "surprised"] {
            let preset = try XCTUnwrap(EmotionPreset.preset(id: id))
            for intensity in EmotionIntensity.allCases {
                let instruction = preset.instruction(for: intensity)
                XCTAssertEqual(
                    GenerationSemantics.englishDictionReinforcedInstruction(
                        baseInstruction: instruction,
                        language: "english"
                    ),
                    instruction,
                    "\(id).\(intensity.rpcValue) must suppress redundant diction reinforcement"
                )
            }
        }

        for id in ["angry", "fearful"] {
            let preset = try XCTUnwrap(EmotionPreset.preset(id: id))
            for intensity in EmotionIntensity.allCases {
                let instruction = preset.instruction(for: intensity)
                XCTAssertEqual(
                    GenerationSemantics.englishDictionReinforcedInstruction(
                        baseInstruction: instruction,
                        language: "english"
                    ),
                    "\(instruction) \(GenerationSemantics.englishDictionReinforcement)",
                    "\(id).\(intensity.rpcValue) must retain the English diction append"
                )
            }
        }
    }

    func testMeasuredRosterSplitStaysCoherent() {
        // The distinct/hint split is measured (DP-12), not taste: every
        // distinct id must exist in the roster, and the two halves must
        // partition it exactly — a retired preset lingering in the split, or
        // a new preset silently landing unclassified, both fail here.
        let rosterIDs = Set(EmotionPreset.all.map(\.id))
        XCTAssertTrue(EmotionPreset.distinctDeliveryIDs.isSubset(of: rosterIDs))
        let hints = Set(EmotionPreset.all.filter(\.isDirectionalHint).map(\.id))
        XCTAssertEqual(hints.union(EmotionPreset.distinctDeliveryIDs), rosterIDs)
        XCTAssertTrue(hints.isDisjoint(with: EmotionPreset.distinctDeliveryIDs))
        XCTAssertFalse(EmotionPreset.directionalHintAdvisory.isEmpty)
    }

    // MARK: - One Studio delivery reading on both apps (P02-07)

    /// The Mac read a blank or typed-"neutral" Custom tone back through the
    /// legacy instruction parser and sent the Neutral preset; the iPhone sent
    /// no instruction. Both apps now resolve the control through one builder.
    func testABlankCustomToneIsNoInstructionOnEveryApp() {
        for blank in ["", "   ", "\n"] {
            let profile = DeliveryProfile.studioSelection(presetID: "neutral", intensity: .strong, customTone: blank)
            XCTAssertEqual(profile, .neutral)
            XCTAssertNil(GenerationSemantics.customInstruction(deliveryStyle: profile.finalInstruction))
            XCTAssertNil(profile.instructionCellID)
        }
    }

    func testCustomToneTextIsSentVerbatimNeverReadAsAPreset() throws {
        let neutralTyped = DeliveryProfile.studioSelection(presetID: "neutral", intensity: .strong, customTone: " neutral ")
        XCTAssertEqual(neutralTyped.finalInstruction, "neutral")
        XCTAssertNil(
            GenerationSemantics.customInstruction(deliveryStyle: neutralTyped.finalInstruction),
            "A typed neutral synonym drops, as EmotionPreset documents, rather than becoming the preset"
        )

        let calm = try XCTUnwrap(EmotionPreset.preset(id: "calm"))
        let presetWording = calm.instruction(for: .strong)
        let typed = DeliveryProfile.studioSelection(presetID: "neutral", intensity: .strong, customTone: presetWording)
        XCTAssertEqual(typed.finalInstruction, presetWording)
        XCTAssertNil(typed.presetID)
        XCTAssertNil(typed.instructionCellID, "Custom text never claims a canonical delivery cell")
    }

    func testAPresetSelectionShipsItsTierAndCell() throws {
        let neutral = DeliveryProfile.studioSelection(presetID: "neutral", intensity: .strong, customTone: nil)
        XCTAssertEqual(neutral.finalInstruction, EmotionPreset.neutralPresetInstruction)

        let calm = try XCTUnwrap(EmotionPreset.preset(id: "calm"))
        let selected = DeliveryProfile.studioSelection(presetID: "calm", intensity: calm.shippedIntensity, customTone: nil)
        XCTAssertEqual(selected, .preset(calm, intensity: calm.shippedIntensity))
        XCTAssertEqual(selected.instructionCellID, "calm.\(calm.shippedIntensity.rpcValue)")

        XCTAssertEqual(
            DeliveryProfile.studioSelection(presetID: "retired-preset", intensity: .strong, customTone: nil),
            .neutral
        )
    }

    // MARK: - The diction sentence is its own sentence (P12-08)

    /// A neutral-delivery Voice Design brief loses its final period, and the
    /// English diction sentence was glued on after a space: "…a subtle British
    /// accent Native English pronunciation…".
    func testTheDictionSentenceFollowsANeutralDesignBriefAsItsOwnSentence() {
        let brief = "A deep, low-pitched male narrator, warm and bass-resonant, with a subtle British accent."
        let instruction = GenerationSemantics.englishDictionReinforcedInstruction(
            baseInstruction: GenerationSemantics.designInstruction(voiceDescription: brief, emotion: ""),
            language: "english"
        )
        XCTAssertEqual(
            instruction,
            "A deep, low-pitched male narrator, warm and bass-resonant, with a subtle British accent. "
                + GenerationSemantics.englishDictionReinforcement
        )
    }

    func testTheDictionSentenceJoinsFreeFormAndClosedTextWithOneSentenceBoundary() {
        XCTAssertEqual(
            GenerationSemantics.englishDictionReinforcedInstruction(baseInstruction: "Warm and confident", language: "english"),
            "Warm and confident. \(GenerationSemantics.englishDictionReinforcement)"
        )
        for (open, closedForm) in [("Warm and confident,", "Warm and confident."),
                                   ("Warm and confident;", "Warm and confident."),
                                   ("Warm and confident:", "Warm and confident.")] {
            XCTAssertEqual(
                GenerationSemantics.englishDictionReinforcedInstruction(baseInstruction: open, language: "english"),
                "\(closedForm) \(GenerationSemantics.englishDictionReinforcement)",
                open
            )
        }
        for closed in ["Warm and confident.", "Warm and confident!", "Warm and confident?", "Warm and confident…",
                       "She says \u{201C}warm.\u{201D}", "(Warm and confident.)"] {
            XCTAssertEqual(
                GenerationSemantics.englishDictionReinforcedInstruction(baseInstruction: closed, language: "english"),
                "\(closed) \(GenerationSemantics.englishDictionReinforcement)",
                closed
            )
        }
        XCTAssertEqual(
            GenerationSemantics.englishDictionReinforcedInstruction(baseInstruction: "Warm and confident", language: "french"),
            "Warm and confident",
            "Only English output takes the sentence"
        )
    }

    /// P02-10: the impersonation guard refuses a named likeness, never an
    /// ordinary character or mood description that shares its wording.
    func testTheImpersonationGuardRefusesNamedLikenessesOnly() {
        func customRequest(_ delivery: String) -> GenerationRequest {
            GenerationRequest(
                mode: .custom, modelID: "pro_custom", text: "Guard fixture.",
                outputPath: "/nonexistent/p02-10.wav", shouldStream: false,
                payload: .custom(speakerID: "aiden", deliveryStyle: delivery)
            )
        }
        func designRequest(_ brief: String) -> GenerationRequest {
            GenerationRequest(
                mode: .design, modelID: "pro_design", text: "Guard fixture.",
                outputPath: "/nonexistent/p02-10.wav", shouldStream: false,
                payload: .design(voiceDescription: brief, deliveryStyle: nil)
            )
        }
        for allowed in [
            "Make it sound just like a cozy bedtime story.",
            "Sounding exactly like an excited sports commentator.",
        ] {
            XCTAssertNoThrow(try GenerationSemantics.validateQwenPromptContract(for: customRequest(allowed)), allowed)
        }
        XCTAssertNoThrow(try GenerationSemantics.validateQwenPromptContract(
            for: designRequest("In the voice of an old sea captain, gravelly and warm.")))
        for refused in [
            "Impersonate a celebrity announcer.",
            "Sound just like Morgan Freeman.",
            "It sounds exactly like my neighbour.",
            "Imitate the voice of the narrator.",
            // RF-73 / D2: multilingual impersonation intent across all 10 languages.
            "Imiter la voix de mon patron.",
            "Avec la voix de Jean-Luc.",
            "Dans la voix d'Emmanuel.",
            "Imitar la voz de un famoso.",
            "Con la voz de Pedro.",
            "Die Stimme imitieren von meinem Chef.",
            "Klingt genau wie mein Nachbar.",
            "Imitare la voce di Marco.",
            "Clonar a voz de uma celebridade.",
            "模仿名人的声音",
            "有名人の声真似で話して",
            "유명인 성대모사로 말해줘",
            "Имитировать голос диктора.",
            "Точно как голос моего начальника.",
        ] {
            XCTAssertThrowsError(try GenerationSemantics.validateQwenPromptContract(for: customRequest(refused)), refused) { error in
                guard case TTSEngineError.disallowedVoiceImitation = error else {
                    XCTFail("Expected TTSEngineError.disallowedVoiceImitation for '\(refused)', got \(error)")
                    return
                }
            }
        }
        for multilingualAllowed in [
            "Dans la voix d'un vieux capitaine de mer, chaleureux et grave.",
            "Con la voz de un narrador tranquilo y cálido.",
            "Mit der Stimme von einem ruhigen Erzähler.",
            "Eine prominente Bassstimme mit ruhigem Tempo.",
            "Con la voce di un narratore calmo e profondo.",
            "Con la voce di un'anziana narratrice.",
            "Con la voce di un’anziana narratrice.",
            "Com a voz de um narrador acolhedor.",
            "Personificar um narrador sábio e calmo.",
            "温暖沉稳的男性旁白声音。",
            "落ち着いた温かいナレーターの声。",
            "海賊のふりをする陽気な声。",
            "차분하고 따뜻한 내레이터 목소리.",
            "Спокойный, тёплый голос рассказчика.",
            "Точно как голос доброго рассказчика.",
        ] {
            XCTAssertNoThrow(
                try GenerationSemantics.validateQwenPromptContract(for: designRequest(multilingualAllowed)),
                multilingualAllowed
            )
        }
        for refusedDesign in [
            "In the voice of Morgan Freeman, slow and deep.",
            "A celebrity radio host.",
        ] {
            XCTAssertThrowsError(
                try GenerationSemantics.validateQwenPromptContract(for: designRequest(refusedDesign)),
                refusedDesign
            ) { error in
                guard case TTSEngineError.disallowedVoiceImitation = error else {
                    XCTFail("Expected TTSEngineError.disallowedVoiceImitation for '\(refusedDesign)', got \(error)")
                    return
                }
            }
        }
        // Voice Design deliveryStyle is also checked alongside voiceDescription.
        let designWithDisallowedDelivery = GenerationRequest(
            mode: .design, modelID: "pro_design", text: "Guard fixture.",
            outputPath: "/nonexistent/p02-10.wav", shouldStream: false,
            payload: .design(voiceDescription: "Warm narrator.", deliveryStyle: "Impersonate a celebrity announcer.")
        )
        XCTAssertThrowsError(
            try GenerationSemantics.validateQwenPromptContract(for: designWithDisallowedDelivery)
        ) { error in
            guard case TTSEngineError.disallowedVoiceImitation = error else {
                XCTFail("Expected TTSEngineError.disallowedVoiceImitation, got \(error)")
                return
            }
        }
        // RF-73 / D3: spoken script (`request.text`) is never filtered in any mode.
        let scriptWithImpersonationWords = "Do not impersonate a celebrity or sound just like Morgan Freeman in this documentary."
        for request in [
            GenerationRequest(
                mode: .custom, modelID: "pro_custom", text: scriptWithImpersonationWords,
                outputPath: "/nonexistent/d3-custom.wav", shouldStream: false,
                payload: .custom(speakerID: "aiden", deliveryStyle: "Calm and measured.")
            ),
            GenerationRequest(
                mode: .design, modelID: "pro_design", text: scriptWithImpersonationWords,
                outputPath: "/nonexistent/d3-design.wav", shouldStream: false,
                payload: .design(voiceDescription: "A calm documentary narrator.", deliveryStyle: nil)
            ),
            GenerationRequest(
                mode: .clone, modelID: "pro_clone", text: scriptWithImpersonationWords,
                outputPath: "/nonexistent/d3-clone.wav", shouldStream: false,
                payload: .clone(reference: CloneReference(audioPath: "/nonexistent/ref.wav", transcript: "Hello."))
            ),
        ] {
            XCTAssertNoThrow(
                try GenerationSemantics.validateQwenPromptContract(for: request),
                "Spoken script text must remain unfiltered in mode \(request.mode)"
            )
        }
    }

    private static func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8))
            .map { unsafe String(format: "%02x", $0) }
            .joined()
    }
}
