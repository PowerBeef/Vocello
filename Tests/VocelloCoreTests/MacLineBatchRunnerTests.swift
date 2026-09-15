import Foundation
import QwenVoiceCore
import XCTest

/// The pure half of the macOS line batch (`MacLineBatchRequest`, items and
/// outcome): line splitting, validation, History naming, the per-line engine
/// request and the retry derivations, all without an engine.
@MainActor
final class MacLineBatchRunnerTests: XCTestCase {
    private let suiteName = "vocello.tests.MacLineBatchRunner"

    override func setUp() async throws {
        try await super.setUp()
        let suiteName = suiteName
        await MainActor.run {
            let defaults = UserDefaults(suiteName: suiteName)!
            defaults.removePersistentDomain(forName: suiteName)
            MacInterfaceLanguage.bootstrap(IOSAppLanguage(
                defaults: defaults,
                bundle: Bundle(for: MacLineBatchRunnerTests.self),
                preferredLanguages: { ["en-CA"] }
            ))
        }
    }

    override func tearDown() async throws {
        let suiteName = suiteName
        await MainActor.run {
            UserDefaults(suiteName: suiteName)?.removePersistentDomain(forName: suiteName)
            MacInterfaceLanguage.bootstrap(IOSAppLanguage())
        }
        try await super.tearDown()
    }

    private func makeRequest(
        mode: GenerationMode,
        lines: [String] = ["Line one", "Line two"],
        supportsInstructionControl: Bool = true,
        voice: String? = "ryan",
        emotion: String? = "Cheerful and bright",
        deliveryInstructionCellID: String? = "happy.strong",
        voiceDescription: String? = "A warm narrator",
        refAudio: String? = "/tmp/reference.wav",
        refText: String? = "Reference transcript",
        preparedVoiceID: String? = "prepared-voice",
        batchSeed: UInt64 = 42
    ) -> MacLineBatchRequest {
        MacLineBatchRequest(
            mode: mode,
            modelID: "model-\(mode.rawValue)",
            modelTier: "speed",
            outputSubfolder: "batch",
            supportsInstructionControl: supportsInstructionControl,
            lines: lines,
            voice: voice,
            emotion: emotion,
            deliveryInstructionCellID: deliveryInstructionCellID,
            language: .french,
            voiceDescription: voiceDescription,
            refAudio: refAudio,
            refText: refText,
            preparedVoiceID: preparedVoiceID,
            displayVoiceName: "Ryan",
            variation: .consistent,
            batchSeed: batchSeed
        )
    }

    // MARK: - Lines

    func testLinesSplitOnNewlinesTrimSpacesAndDropBlankRows() {
        let lines = MacLineBatchRequest.lines(from: "  First line \n\n\tSecond line\r\n   \nThird")
        XCTAssertEqual(lines, ["First line", "Second line", "Third"])
        XCTAssertEqual(MacLineBatchRequest.lines(from: "\n \n"), [])
    }

    // MARK: - Validation

    func testValidationReportsRecoveryDetailWhenTheModelIsMissing() {
        let request = makeRequest(mode: .custom)
        XCTAssertEqual(
            request.validationError(isModelAvailable: false, recoveryDetail: "Install the package"),
            "Install the package"
        )
        XCTAssertNil(request.validationError(isModelAvailable: true, recoveryDetail: "Install the package"))
    }

    func testValidationRequiresADesignBriefAndACloneReference() {
        XCTAssertEqual(
            makeRequest(mode: .design, voiceDescription: "").validationError(isModelAvailable: true, recoveryDetail: ""),
            MacInterfaceText.batchNeedsVoiceDescription
        )
        XCTAssertNil(makeRequest(mode: .design).validationError(isModelAvailable: true, recoveryDetail: ""))
        XCTAssertEqual(
            makeRequest(mode: .clone, refAudio: nil).validationError(isModelAvailable: true, recoveryDetail: ""),
            MacInterfaceText.batchNeedsReference
        )
        XCTAssertNil(makeRequest(mode: .clone).validationError(isModelAvailable: true, recoveryDetail: ""))
    }

    // MARK: - History naming

    func testHistoryVoiceAndEmotionFollowTheModeRules() {
        XCTAssertEqual(makeRequest(mode: .custom).historyVoice, "ryan")
        XCTAssertEqual(makeRequest(mode: .custom).historyEmotion, "Cheerful and bright")
        XCTAssertNil(makeRequest(mode: .custom, supportsInstructionControl: false).historyEmotion)

        XCTAssertEqual(makeRequest(mode: .design).historyVoice, "A warm narrator")
        XCTAssertEqual(makeRequest(mode: .design).historyEmotion, "Cheerful and bright")

        XCTAssertEqual(makeRequest(mode: .clone, voice: "Saved Voice").historyVoice, "Saved Voice")
        XCTAssertEqual(makeRequest(mode: .clone, voice: nil, refAudio: "/tmp/clips/my_reference.wav").historyVoice, "my_reference")
        XCTAssertNil(makeRequest(mode: .clone, voice: nil, refAudio: nil).historyVoice)
        XCTAssertNil(makeRequest(mode: .clone).historyEmotion)
    }

    // MARK: - Engine requests

    func testCustomLineRequestCarriesTheBatchSeedVariationLanguageAndDelivery() throws {
        let generationID = UUID()
        let request = try XCTUnwrap(
            makeRequest(mode: .custom).generationRequest(line: "Line one", outputPath: "/tmp/line1.wav", generationID: generationID)
        )
        XCTAssertEqual(request.mode, .custom)
        XCTAssertEqual(request.modelID, "model-custom")
        XCTAssertEqual(request.text, "Line one")
        XCTAssertEqual(request.outputPath, "/tmp/line1.wav")
        XCTAssertEqual(request.generationID, generationID)
        XCTAssertEqual(request.seed, 42)
        XCTAssertEqual(request.variation, .consistent)
        XCTAssertEqual(request.languageHint, Qwen3SupportedLanguage.french.rawValue)
        XCTAssertTrue(request.shouldStream)
        XCTAssertEqual(request.deliveryInstructionCellID, "happy.strong")
        guard case .custom(let speakerID, let deliveryStyle) = request.payload else {
            return XCTFail("Expected a custom payload")
        }
        XCTAssertEqual(speakerID, "ryan")
        XCTAssertEqual(deliveryStyle, "Cheerful and bright")
    }

    func testCustomLineRequestDropsDeliveryWhenThePackageHasNoInstructionControl() throws {
        let request = try XCTUnwrap(
            makeRequest(mode: .custom, supportsInstructionControl: false)
                .generationRequest(line: "Line one", outputPath: "/tmp/line1.wav")
        )
        XCTAssertNil(request.deliveryInstructionCellID)
        guard case .custom(_, let deliveryStyle) = request.payload else {
            return XCTFail("Expected a custom payload")
        }
        XCTAssertNil(deliveryStyle)
    }

    func testEveryLineOfABatchSharesOneSeedAndGetsItsOwnIdentity() throws {
        let request = makeRequest(mode: .design, batchSeed: 7)
        let first = try XCTUnwrap(request.generationRequest(line: "Line one", outputPath: "/tmp/1.wav"))
        let second = try XCTUnwrap(request.generationRequest(line: "Line two", outputPath: "/tmp/2.wav"))
        XCTAssertEqual(first.seed, 7)
        XCTAssertEqual(second.seed, 7)
        XCTAssertNotEqual(first.generationID, second.generationID)
        guard case .design(let brief, let deliveryStyle) = first.payload else {
            return XCTFail("Expected a design payload")
        }
        XCTAssertEqual(brief, "A warm narrator")
        XCTAssertEqual(deliveryStyle, "Cheerful and bright")
    }

    func testCloneLineRequestCarriesTheReferenceAndPreparedVoice() throws {
        let request = try XCTUnwrap(
            makeRequest(mode: .clone).generationRequest(line: "Line one", outputPath: "/tmp/1.wav")
        )
        guard case .clone(let reference) = request.payload else {
            return XCTFail("Expected a clone payload")
        }
        XCTAssertEqual(reference.audioPath, "/tmp/reference.wav")
        XCTAssertEqual(reference.transcript, "Reference transcript")
        XCTAssertEqual(reference.preparedVoiceID, "prepared-voice")
        XCTAssertNil(makeRequest(mode: .clone, refAudio: nil).generationRequest(line: "Line one", outputPath: "/tmp/1.wav"))
        XCTAssertNil(makeRequest(mode: .custom, voice: nil).generationRequest(line: "Line one", outputPath: "/tmp/1.wav"))
    }

    // MARK: - Outcomes

    func testOutcomeRetryDerivationsAndSavedPaths() {
        let items = [
            MacLineBatchItem(index: 0, line: "Saved", status: .saved(audioPath: "/tmp/saved.wav")),
            MacLineBatchItem(index: 1, line: "Failed", status: .failed(message: "boom")),
            MacLineBatchItem(index: 2, line: "Cancelled", status: .cancelled),
            MacLineBatchItem(index: 3, line: "Pending", status: .pending),
            MacLineBatchItem(index: 4, line: "Running", status: .running),
        ]
        let outcome = MacLineBatchOutcome.cancelled(items: items, restartFailedMessage: nil)
        XCTAssertEqual(outcome.items.count, 5)
        XCTAssertEqual(outcome.retryRemainingLines, ["Cancelled", "Pending", "Running"])
        XCTAssertEqual(outcome.retryFailedLines, ["Failed"])
        XCTAssertEqual(outcome.savedAudioPaths, ["/tmp/saved.wav"])
        XCTAssertTrue(items[0].isSaved)
        XCTAssertEqual(items[0].audioPath, "/tmp/saved.wav")
        XCTAssertFalse(items[1].isSaved)
        XCTAssertNil(items[1].audioPath)

        XCTAssertEqual(MacLineBatchOutcome.completed(items: items).retryFailedLines, ["Failed"])
        XCTAssertEqual(MacLineBatchOutcome.failed(items: items, message: "boom").savedAudioPaths, ["/tmp/saved.wav"])
    }

    func testProgressFractionIsBoundedByTheTotal() {
        XCTAssertEqual(MacLineBatchProgress().fraction, 0)
        XCTAssertEqual(MacLineBatchProgress(completedCount: 1, totalCount: 4).fraction, 0.25)
        XCTAssertEqual(MacLineBatchProgress(completedCount: 9, totalCount: 4).fraction, 1)
    }
}
