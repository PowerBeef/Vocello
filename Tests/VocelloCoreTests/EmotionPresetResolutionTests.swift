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

    private static func sha256(_ value: String) -> String {
        SHA256.hash(data: Data(value.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }
}
