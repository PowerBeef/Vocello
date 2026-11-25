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
        XCTAssertEqual(VocelloPresentationText.coolingDownBeforeSegment(2, total: 3),
                       "Paused to cool down. Segment 2 of 3 starts on its own.")
    }

    func testDynamicPresentationPreservesSubstitutedContentVerbatim() {
        let detail = "A %1$@ — 日本語 / français"
        XCTAssertEqual(VocelloPresentationText.playerSubtitle(detail, duration: "1:02"),
                       detail + " · 1:02")
        // Long-form QC copy carries no raw check detail (L14-05).
        XCTAssertEqual(
            VocelloPresentationText.segmentQCRejected(2),
            "Segment 2 did not pass its audio quality check, so its take was not kept. Resume the project to generate a new take."
        )
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
        // A9-01: the store's admission refusals present catalog copy, not the engine's English.
        XCTAssertEqual(
            text.generationFailureMessage(TTSEngineError.generationAdmissionRefused(.engineBusy)),
            text.generationFailureMessage(.engineBusy)
        )
        XCTAssertEqual(
            text.generationFailureMessage(TTSEngineError.generationAdmissionRefused(.releasingMemory)),
            text.generationFailureMessage(.engineReleasingMemory)
        )
        // RF-73 / D2: impersonation refusals map to localized catalog copy without raw detail.
        let imitationMessage = text.generationFailureMessage(
            TTSEngineError.disallowedVoiceImitation("raw English refusal")
        )
        XCTAssertEqual(
            imitationMessage,
            "Voice instructions cannot request celebrity imitation or impersonation of a real person. Describe vocal qualities instead."
        )
        XCTAssertFalse(imitationMessage.contains("raw English refusal"))
    }

    /// PA-20 (IOS-12): one short VoiceOver sentence per generation state change.
    func testGenerationAnnouncementsAreShortCompleteSentences() {
        let text = VocelloPresentationText()
        XCTAssertEqual(text.announceGenerationStarted, "Generating take.")
        XCTAssertEqual(text.announceTakeReady, "Take ready.")
        XCTAssertEqual(text.announceGenerationStopped, "Generation stopped.")
        XCTAssertEqual(text.announceGenerationFailed("Try again."), "Generation failed. Try again.")
        let french = VocelloPresentationText(localization: VocelloLocalization(bundle: Bundle(for: Self.self), language: "fr"))
        XCTAssertEqual(french.announceTakeReady, "Prise prête.")
        XCTAssertEqual(french.announceGenerationFailed("Détail."), "Échec de la génération. Détail.")
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

    /// A5: the shared player's failures keep their English source values and
    /// read in the interface language everywhere else.
    func testPlaybackFailuresKeepTheirEnglishSourceValuesAndAreTranslated() {
        let bundle = Bundle(for: Self.self)
        let english = VocelloPresentationText(localization: VocelloLocalization(bundle: bundle, language: "en"))
        let sources: [(failure: VocelloPresentationText.PlaybackFailure, text: String)] = [
            (.couldNotStart, "Playback could not start."),
            (.livePreviewUndecodable, "Live audio preview could not decode the latest chunk."),
            (.stoppedUnexpectedly, "Playback stopped unexpectedly."),
            (.audioFileMissing, "Audio file not found."),
        ]
        for source in sources {
            XCTAssertEqual(english.playbackFailureMessage(source.failure), source.text)
        }
        for language in ["fr", "es", "de", "it", "pt-BR", "zh-Hans", "ja", "ko", "ru"] {
            let text = VocelloPresentationText(localization: VocelloLocalization(bundle: bundle, language: language))
            for source in sources {
                XCTAssertNotEqual(text.playbackFailureMessage(source.failure), source.text, "\(language) \(source.failure)")
            }
        }

        // A system audio error keeps the system's wording; a thrown typed case keeps its case.
        XCTAssertEqual(english.playbackFailureMessage(.system("The file is damaged.")), "The file is damaged.")
        XCTAssertEqual(
            VocelloPresentationText.PlaybackFailure(VocelloPresentationText.PlaybackFailure.audioFileMissing),
            .audioFileMissing
        )
        let systemError = CocoaError(.fileReadCorruptFile)
        XCTAssertEqual(
            VocelloPresentationText.PlaybackFailure(systemError),
            .system(systemError.localizedDescription)
        )
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

    /// RF-73: model download failures map through typed classes to localized,
    /// path-free copy instead of leaking raw NSError/English descriptions.
    func testModelDeliveryFailureMessagesAreLocalizedAndStripRawDetail() {
        let bundle = Bundle(for: Self.self)
        let english = VocelloPresentationText(localization: VocelloLocalization(bundle: bundle, language: "en"))
        let privatePath = "/private/var/mobile/Containers/raw-download.bin"
        let rawError = NSError(
            domain: NSURLErrorDomain,
            code: NSURLErrorTimedOut,
            userInfo: [NSLocalizedDescriptionKey: "raw timeout at \(privatePath)"]
        )
        let networkMessage = english.modelDeliveryErrorMessage(rawError)
        XCTAssertEqual(
            networkMessage,
            "The download couldn't complete over this network. Check your connection and try again."
        )
        XCTAssertFalse(networkMessage.contains(privatePath))
        XCTAssertEqual(
            english.modelDeliveryErrorMessage(CocoaError(.fileWriteOutOfSpace)),
            "Not enough storage space to download this model. Free up space and try again."
        )
        XCTAssertEqual(
            english.modelDeliveryErrorMessage(
                HuggingFaceDownloader.DownloadError.integrityCheckFailed(path: "a.bin", reason: "mismatch")
            ),
            "The downloaded files could not be verified. Tap Retry to download again."
        )
        XCTAssertEqual(
            english.modelDeliveryErrorMessage(.other),
            "The model download couldn't finish. Tap Retry to try again."
        )
        XCTAssertEqual(
            english.modelRemovalFailed,
            "Couldn't remove this model's files. Try again."
        )

        for language in ["fr", "es", "de", "it", "pt-BR", "zh-Hans", "ja", "ko", "ru"] {
            let localized = VocelloPresentationText(localization: VocelloLocalization(bundle: bundle, language: language))
            for failureClass in [ModelUpdateFailure.space, .verification, .network, .other] {
                XCTAssertNotEqual(
                    localized.modelDeliveryErrorMessage(failureClass),
                    english.modelDeliveryErrorMessage(failureClass),
                    "\(language) \(failureClass.rawValue)"
                )
            }
            XCTAssertNotEqual(localized.modelRemovalFailed, english.modelRemovalFailed, "\(language) removal")
        }
    }

    /// RF-73 / P1-4: iOS cloning consent refusal copy names Settings → Privacy & Permissions
    /// and stays translated across all 10 interface locales.
    func testCloningConsentCopyNamesPrivacyAndPermissionsInEveryLocale() {
        let bundle = Bundle(for: Self.self)
        let english = VocelloPresentationText(localization: VocelloLocalization(bundle: bundle, language: "en"))
        XCTAssertTrue(english.cloningConsentRequired.contains("Privacy & Permissions"))
        XCTAssertTrue(english.cloningConsentRequiredToSaveVoice.contains("Privacy & Permissions"))
        for language in ["fr", "es", "de", "it", "pt-BR", "zh-Hans", "ja", "ko", "ru"] {
            let localized = VocelloPresentationText(localization: VocelloLocalization(bundle: bundle, language: language))
            XCTAssertNotEqual(localized.cloningConsentRequired, english.cloningConsentRequired, language)
            XCTAssertNotEqual(localized.cloningConsentRequiredToSaveVoice, english.cloningConsentRequiredToSaveVoice, language)
        }
    }
}
