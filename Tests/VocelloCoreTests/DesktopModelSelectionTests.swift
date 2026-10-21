import Foundation
import QwenVoiceCore
import XCTest
import VocelloDesktopCore

/// RF-26: the CLI resolves each mode's package the way the Mac app does: the
/// explicit choice, then the lower-memory preference, then the hardware
/// recommendation; a take falls back to the first installed package.
final class DesktopModelSelectionTests: XCTestCase {
    private func registry(_ deviceClass: NativeDeviceMemoryClass) throws -> ContractBackedModelRegistry {
        let manifest = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        return try ContractBackedModelRegistry(manifestURL: manifest)
            .expandedForPlatform(.macOS, deviceClass: deviceClass, includeBaseAliases: true)
    }

    private func resolve(
        _ deviceClass: NativeDeviceMemoryClass,
        explicit: [GenerationMode: String] = [:],
        prefersLowerMemory: Bool = false,
        installed: Set<String>? = nil
    ) throws -> [String: DesktopModelSelection.Choice] {
        let choices = DesktopModelSelection.resolve(
            registry: try registry(deviceClass),
            explicitVariantID: { explicit[$0] },
            prefersLowerMemory: prefersLowerMemory,
            deviceClass: deviceClass,
            isInstalled: { installed?.contains($0) ?? true }
        )
        return Dictionary(uniqueKeysWithValues: choices.map { ($0.mode, $0) })
    }

    func testTheHardwareRecommendationFollowsTheMemoryTier() throws {
        let floor = try resolve(.floor8GBMac)
        let mid = try resolve(.mid16GBMac)
        for mode in ["custom", "design", "clone"] {
            XCTAssertEqual(floor[mode]?.activeVariant, "speed", mode)
            XCTAssertEqual(floor[mode]?.source, "hardware", mode)
            XCTAssertEqual(mid[mode]?.activeVariant, "quality", mode)
            XCTAssertEqual(mid[mode]?.variants, ["speed", "quality"], "the picker order")
        }
        XCTAssertEqual(mid["custom"]?.activeModelID, "pro_custom_quality")
    }

    func testAnExplicitChoiceThenTheLowerMemoryPreferenceWin() throws {
        let explicit = try resolve(.mid16GBMac, explicit: [.design: "speed"], prefersLowerMemory: false)
        XCTAssertEqual(explicit["design"]?.activeVariant, "speed")
        XCTAssertEqual(explicit["design"]?.source, "explicit")
        XCTAssertEqual(explicit["custom"]?.activeVariant, "quality")

        let lower = try resolve(.mid16GBMac, explicit: [.clone: "quality"], prefersLowerMemory: true)
        XCTAssertEqual(lower["custom"]?.activeVariant, "speed")
        XCTAssertEqual(lower["custom"]?.source, "prefer-lower-memory")
        XCTAssertEqual(lower["clone"]?.activeVariant, "quality", "an explicit choice outranks the preference")

        let unknown = try resolve(.floor8GBMac, explicit: [.custom: "turbo"])
        XCTAssertEqual(unknown["custom"]?.activeVariant, "speed", "an unknown stored choice is ignored")
    }

    func testATakeFallsBackToAnInstalledPackage() throws {
        let choices = try resolve(.mid16GBMac, installed: ["pro_custom_speed"])
        XCTAssertEqual(choices["custom"]?.activeVariant, "quality")
        XCTAssertEqual(choices["custom"]?.activeInstalled, false)
        XCTAssertEqual(choices["custom"]?.generationVariant, "speed")
        XCTAssertEqual(choices["custom"]?.generationModelID, "pro_custom_speed")
        XCTAssertNil(choices["design"]?.generationVariant, "nothing installed for Design")
    }
}
