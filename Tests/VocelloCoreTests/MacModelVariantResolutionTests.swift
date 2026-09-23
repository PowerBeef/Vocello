import XCTest

final class MacModelVariantResolutionTests: XCTestCase {
    private func resolution(
        explicit: String? = nil,
        prefersLowerMemory: Bool = false,
        lowerMemory: String? = "speed",
        hardwareRecommended: String? = "quality",
        variants: [String] = ["speed", "quality"]
    ) -> MacModelVariantResolution {
        MacModelVariantResolution(
            variantIDs: variants,
            explicitVariantID: explicit,
            prefersLowerMemory: prefersLowerMemory,
            lowerMemoryVariantID: lowerMemory,
            hardwareRecommendedVariantID: hardwareRecommended
        )
    }

    func testAnExplicitChoiceWinsOverThePreferenceAndTheHardwareRecommendation() {
        XCTAssertEqual(resolution(explicit: "quality", prefersLowerMemory: true).activeVariantID, "quality")
        XCTAssertEqual(
            resolution(explicit: "speed", prefersLowerMemory: false, hardwareRecommended: "quality").activeVariantID,
            "speed"
        )
    }

    func testThePreferenceSelectsSpeedWithoutAnExplicitChoice() {
        XCTAssertEqual(resolution(prefersLowerMemory: true, hardwareRecommended: "quality").activeVariantID, "speed")
    }

    func testWithThePreferenceOffTheHardwareRecommendationApplies() {
        XCTAssertEqual(resolution(prefersLowerMemory: false, hardwareRecommended: "quality").activeVariantID, "quality")
        XCTAssertEqual(resolution(prefersLowerMemory: false, hardwareRecommended: "speed").activeVariantID, "speed")
    }

    func testUnknownCandidatesAreSkipped() {
        XCTAssertEqual(resolution(explicit: "retired", prefersLowerMemory: true).activeVariantID, "speed")
        XCTAssertEqual(resolution(explicit: "retired", hardwareRecommended: "quality").activeVariantID, "quality")
        XCTAssertEqual(
            resolution(prefersLowerMemory: true, lowerMemory: nil, hardwareRecommended: "quality").activeVariantID,
            "quality"
        )
        XCTAssertEqual(resolution(hardwareRecommended: nil).activeVariantID, "speed")
        XCTAssertNil(resolution(variants: []).activeVariantID)
    }

    func testThePreferenceOrderHasEveryVariantOnce() {
        XCTAssertEqual(resolution(explicit: "quality", prefersLowerMemory: true).preferenceOrder, ["quality", "speed"])
        XCTAssertEqual(resolution(prefersLowerMemory: true).preferenceOrder, ["speed", "quality"])
        XCTAssertEqual(resolution().preferenceOrder, ["quality", "speed"])
    }

    func testTheInstalledFallbackFollowsTheSameOrder() {
        let installedBoth: (String) -> Bool = { _ in true }
        let onlyQuality: (String) -> Bool = { $0 == "quality" }
        let onlySpeed: (String) -> Bool = { $0 == "speed" }
        let none: (String) -> Bool = { _ in false }

        XCTAssertEqual(resolution(prefersLowerMemory: true).installedFallbackVariantID(isInstalled: installedBoth), "speed")
        XCTAssertEqual(resolution().installedFallbackVariantID(isInstalled: installedBoth), "quality")
        XCTAssertEqual(
            resolution(explicit: "quality", prefersLowerMemory: true).installedFallbackVariantID(isInstalled: installedBoth),
            "quality"
        )
        XCTAssertEqual(resolution(prefersLowerMemory: true).installedFallbackVariantID(isInstalled: onlyQuality), "quality")
        XCTAssertEqual(resolution(explicit: "quality").installedFallbackVariantID(isInstalled: onlySpeed), "speed")
        XCTAssertNil(resolution().installedFallbackVariantID(isInstalled: none))
    }

    func testOnlyAKnownUninstalledExplicitChoiceIsReplaced() {
        let onlySpeed: (String) -> Bool = { $0 == "speed" }
        let installedBoth: (String) -> Bool = { _ in true }

        XCTAssertEqual(resolution(explicit: "quality").fallbackReplacingExplicitChoice(isInstalled: onlySpeed), "speed")
        XCTAssertNil(resolution(explicit: "retired").fallbackReplacingExplicitChoice(isInstalled: onlySpeed))
        XCTAssertNil(resolution(explicit: "quality").fallbackReplacingExplicitChoice(isInstalled: installedBoth))
        XCTAssertNil(resolution(explicit: nil).fallbackReplacingExplicitChoice(isInstalled: onlySpeed))
        XCTAssertNil(resolution(explicit: "quality").fallbackReplacingExplicitChoice(isInstalled: { _ in false }))
    }

    func testEnablingThePreferenceClearsStoredChoicesAndSelectsSpeed() {
        // Before: an explicit Quality pick keeps Quality even with the preference on.
        XCTAssertEqual(resolution(explicit: "quality", prefersLowerMemory: true).activeVariantID, "quality")
        // Enabling the preference clears the stored choice, so the mode resolves to Speed.
        XCTAssertEqual(resolution(explicit: nil, prefersLowerMemory: true).activeVariantID, "speed")
        // A pick made afterwards wins again.
        XCTAssertEqual(resolution(explicit: "quality", prefersLowerMemory: true).activeVariantID, "quality")
    }
}
