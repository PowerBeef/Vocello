import XCTest

final class VocelloPresentationTextTests: XCTestCase {
    func testProgressFormatsExactCountsAndPercentWithoutChangingMeaning() {
        XCTAssertEqual(VocelloPresentationText.downloadTransfer(25, completed: "25 B", total: "100 B"),
                       "25% · 25 B of 100 B")
        // UI language and number-formatting region can differ (for example English UI in
        // French Canada). Assert exact locale-formatted counts, not ungrouped ASCII digits.
        let completed = NumberFormatter.localizedString(from: 5_000_000_000, number: .decimal)
        let total = NumberFormatter.localizedString(from: 5_050_000_000, number: .decimal)
        XCTAssertEqual(VocelloPresentationText.downloadAccessibility(99, completed: 5_000_000_000, total: 5_050_000_000),
                       "99% — " + completed + " of " + total + " bytes")
        XCTAssertEqual(VocelloPresentationText.generatedSegmentPending(2, total: 3),
                       "Generated segment 2 of 3; project not yet saved")
        XCTAssertEqual(VocelloPresentationText.regeneratingSegment(1, total: 3),
                       "Regenerating segment 1 of 3…")
    }

    func testDynamicPresentationPreservesSubstitutedContentVerbatim() {
        let detail = "A %1$@ — 日本語 / français"
        XCTAssertEqual(VocelloPresentationText.segmentQC(2, detail: detail),
                       "Segment 2 failed audio quality checks. " + detail)
        XCTAssertEqual(VocelloPresentationText.playerSubtitle(detail, duration: "1:02"),
                       detail + " · 1:02")
        XCTAssertEqual(VocelloPresentationText.regeneratedQC(detail),
                       "The regenerated take failed audio quality checks; the previous take is unchanged. " + detail)
    }

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
