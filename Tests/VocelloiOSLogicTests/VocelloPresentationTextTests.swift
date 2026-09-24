import QwenVoiceCore
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

    // MARK: - Typed failures (PA-20)

    func testGenerationFailuresPresentTypedCatalogCopyWithoutRawDetail() {
        let text = VocelloPresentationText()
        let privatePath = "/private/fixture/reference.wav"
        XCTAssertEqual(
            text.generationFailureMessage(TTSEngineError.insufficientMemory("raw engine detail")),
            "Vocello needs more available memory before loading this model. Close background apps and try again."
        )
        let unreadable = text.generationFailureMessage(AudioPreparationError.failedToReadAudio(privatePath))
        XCTAssertEqual(unreadable, "Vocello couldn't read this reference audio. Choose another audio file.")
        XCTAssertFalse(unreadable.contains(privatePath))
        XCTAssertEqual(
            text.generationFailureMessage(TTSEngineError.savedVoiceStoreBusy),
            text.savedVoicesStoreBusy
        )
        // An untyped error keeps its own description: host copy is already localized.
        XCTAssertEqual(text.generationFailureMessage(TTSEngineError.unsupportedRequest("Host copy")), "Host copy")
    }

    /// PA-20 (MAC-10): sizes and dates follow the interface language, not the process locale.
    func testFormattersFollowTheInterfaceLanguage() {
        let bundle = Bundle(for: Self.self)
        let french = VocelloLocalization(bundle: bundle, language: "fr")
        let english = VocelloLocalization(bundle: bundle, language: "en")
        let size = french.fileSize(1_500_000_000)
        XCTAssertTrue(size.contains("Go"), size)
        XCTAssertTrue(english.fileSize(1_500_000_000).contains("GB"))
        XCTAssertTrue(english.fileSize(2_400_000_000, allowedUnits: [.gb, .mb]).contains("GB"))
        let middayUTC = Date(timeIntervalSince1970: 1_789_473_600) // 2026-09-15 12:00 UTC
        let frenchDate = french.dateTime(middayUTC)
        XCTAssertTrue(frenchDate.contains("sept"), frenchDate)
        XCTAssertTrue(english.dateTime(middayUTC).contains("Sep"), english.dateTime(middayUTC))
    }

    func testEveryGenerationFailureReasonHasTranslatedCatalogCopy() {
        let bundle = Bundle(for: Self.self)
        let english = VocelloPresentationText(localization: VocelloLocalization(bundle: bundle, language: "en"))
        for reason in GenerationFailurePresentationReason.allCases {
            XCTAssertFalse(english.generationFailureMessage(reason).isEmpty, reason.rawValue)
        }
        for language in ["fr", "es", "de", "it", "pt-BR", "zh-Hans", "ja", "ko", "ru"] {
            let text = VocelloPresentationText(localization: VocelloLocalization(bundle: bundle, language: language))
            for reason in GenerationFailurePresentationReason.allCases {
                XCTAssertNotEqual(
                    text.generationFailureMessage(reason),
                    english.generationFailureMessage(reason),
                    "\(language) \(reason.rawValue)"
                )
            }
        }
    }
}
