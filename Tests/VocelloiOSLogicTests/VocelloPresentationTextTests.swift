import XCTest

final class VocelloPresentationTextTests: XCTestCase {
    func testTypedStatusesRetainEnglishSourceValues() {
        XCTAssertEqual(VocelloPresentationText.status(.ready), "Ready")
        XCTAssertEqual(VocelloPresentationText.status(.generationFailed), "Generation failed")
        XCTAssertEqual(
            VocelloPresentationText.status(.checkingDownloadedFiles),
            "Checking downloaded files"
        )
        XCTAssertEqual(
            VocelloPresentationText.status(.makingModelAvailableOffline),
            "Making the model available offline"
        )
    }

    func testDynamicErrorsSubstituteValuesWithoutFragmentConcatenation() {
        XCTAssertEqual(
            VocelloPresentationText.installModel(named: "Voice Design"),
            "Install “Voice Design” in Settings to generate audio."
        )
        XCTAssertEqual(
            VocelloPresentationText.longFormPlanningFailed(details: "No segments"),
            "Long-form planning failed: No segments"
        )
        XCTAssertEqual(
            VocelloPresentationText.cancellationCouldNotFinish(details: "Engine busy"),
            "Cancellation could not finish safely: Engine busy"
        )
    }

    func testPluralContractFormatsTheSourceLanguageFallback() {
        XCTAssertEqual(VocelloPresentationText.readyModelCount(3), "3 models ready")
    }
}
