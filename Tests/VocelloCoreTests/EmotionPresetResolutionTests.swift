import Foundation
@testable import QwenVoiceCore
import XCTest

/// Instruction-string → (preset, tier) resolution. The regression this pins:
/// Neutral's tier strings are identical, and a resolver that checks `.normal`
/// first synced the macOS picker to `.normal` on appearance, after which every
/// preset pick silently emitted the normal-tier copy — reversing DP-8's
/// ship-strong decision without anyone deciding it (2026-08-04 audit, F4).
final class EmotionPresetResolutionTests: XCTestCase {
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
}
