import Foundation
@testable import QwenVoiceCore
import XCTest

/// Name-convention grouping of saved voices into emotion reference banks.
/// The contract under test: only "<Base> (<LivePresetSuffix>)" names with an
/// existing base voice group; everything else stays standalone, so the
/// grouped pickers can never hide a voice or invent a persona.
final class VoiceBankCatalogTests: XCTestCase {
    private func catalog(_ names: [String]) -> VoiceBankCatalog {
        VoiceBankCatalog.build(voices: names.map { (id: $0, name: $0) })
    }

    func testBankGroupsBaseAndPresetSuffixedVariants() {
        let c = catalog(["Warm Narrator", "Warm Narrator (Happy)", "Warm Narrator (Sad)", "Warm Narrator (Angry)"])
        XCTAssertEqual(c.personas.count, 1)
        let persona = try! XCTUnwrap(c.personas.first)
        XCTAssertEqual(persona.baseVoiceID, "Warm Narrator")
        XCTAssertEqual(Set(persona.variantVoiceIDs.keys), ["happy", "sad", "angry"])
        XCTAssertEqual(c.bankMemberVoiceIDs.count, 4)
    }

    func testOrderedVariantsFollowPresetRosterOrder() {
        let c = catalog(["P", "P (Sad)", "P (Happy)", "P (Angry)"])
        let ordered = try! XCTUnwrap(c.personas.first).orderedVariants.map(\.presetID)
        let rosterOrder = EmotionPreset.all.map(\.id).filter { ordered.contains($0) }
        XCTAssertEqual(ordered, rosterOrder)
    }

    func testStandaloneVoicesStayOutOfEveryPersona() {
        let c = catalog(["A_warm_elderly_woman", "Warm Narrator", "Warm Narrator (Happy)"])
        XCTAssertEqual(c.personas.count, 1)
        XCTAssertFalse(c.bankMemberVoiceIDs.contains("A_warm_elderly_woman"))
        XCTAssertNil(c.persona(containing: "A_warm_elderly_woman"))
    }

    func testOrphanVariantWithoutBaseStaysStandalone() {
        let c = catalog(["Warm Narrator (Happy)"])
        XCTAssertTrue(c.personas.isEmpty)
        XCTAssertTrue(c.bankMemberVoiceIDs.isEmpty)
    }

    func testUnknownSuffixStaysStandalone() {
        // "(Backup)" is not a preset; "(Happy)" is. Only the latter groups.
        let c = catalog(["P", "P (Backup)", "P (Happy)"])
        let persona = try! XCTUnwrap(c.personas.first)
        XCTAssertEqual(Array(persona.variantVoiceIDs.keys), ["happy"])
        XCTAssertFalse(c.bankMemberVoiceIDs.contains("P (Backup)"))
    }

    func testBaseWithoutVariantsIsNotAPersona() {
        let c = catalog(["Solo Voice"])
        XCTAssertTrue(c.personas.isEmpty)
    }

    func testPresetIDResolutionForMembers() {
        let c = catalog(["P", "P (Whisper)"])
        let persona = try! XCTUnwrap(c.persona(containing: "P (Whisper)"))
        XCTAssertEqual(persona.presetID(for: "P (Whisper)"), "whisper")
        XCTAssertNil(persona.presetID(for: "P"), "the base is the neutral anchor, not a variant")
        XCTAssertNil(c.persona(containing: nil))
    }

    func testSuffixMatchingIsCaseInsensitiveOnPresetIDToo() {
        // The builder writes labels ("Happy"), but a hand-named "(happy)"
        // must group identically — capitalization is not meaning.
        let c = catalog(["P", "P (happy)"])
        XCTAssertEqual(c.personas.first?.variantVoiceIDs["happy"], "P (happy)")
    }

    func testEveryLivePresetLabelSuffixGroups() {
        // Derived from the roster so a renamed preset cannot silently strand
        // its bank variants as standalone voices.
        let names = ["P"] + EmotionPreset.all.map { "P (\($0.label))" }
        let c = catalog(names)
        let groupedPresetIDs = Set(c.personas.first?.variantVoiceIDs.keys.map { $0 } ?? [])
        XCTAssertEqual(groupedPresetIDs, Set(EmotionPreset.all.map(\.id)))
    }

    func testPersonasSortByNameAndDuplicateSuffixKeepsFirst() {
        let c = VoiceBankCatalog.build(voices: [
            (id: "b-base", name: "Beta"),
            (id: "b-h", name: "Beta (Happy)"),
            (id: "a-base", name: "Alpha"),
            (id: "a-h", name: "Alpha (Happy)"),
        ])
        XCTAssertEqual(c.personas.map(\.name), ["Alpha", "Beta"])
        XCTAssertEqual(c.personas.first?.variantVoiceIDs["happy"], "a-h")
    }
}
