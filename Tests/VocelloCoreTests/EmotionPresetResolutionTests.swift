import Foundation
@testable import QwenVoiceCore
import XCTest

/// Instruction-string → (preset, tier) resolution. The regression this pins:
/// Neutral's tier strings are identical, and a resolver that checks `.normal`
/// first synced the macOS picker to `.normal` on appearance, after which every
/// preset pick silently emitted the normal-tier copy — reversing DP-8's
/// ship-strong decision without anyone deciding it (2026-08-04 audit, F4).
final class EmotionPresetResolutionTests: XCTestCase {
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
}
