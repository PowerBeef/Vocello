import Foundation
@testable import QwenVoiceCore
import XCTest

final class GenerationStartupDiagnosticsTests: XCTestCase {
    func testRawPresetTextDoesNotGainCanonicalCellIdentity() {
        let generationID = UUID()
        let request = GenerationRequest(
            mode: .custom,
            modelID: "pro_custom_speed",
            text: "Raw legacy request.",
            outputPath: "/tmp/raw.wav",
            shouldStream: false,
            languageHint: "english",
            payload: .custom(
                speakerID: "aiden",
                deliveryStyle: EmotionPreset.angryBilingualV3English
            ),
            generationID: generationID,
            seed: 1
        )
        let receipt = GenerationRequestReceipt(
            request: request,
            generationID: generationID,
            effectiveSeed: 1,
            warmState: .cold,
            predecessorIdentityDigest: nil,
            retryAttempt: 0,
            operationGeneration: 1
        )
        XCTAssertNil(receipt.deliveryID)
    }

    func testReceiptAndWarmIdentitiesUseTheResolvedMandarinInstruction() throws {
        let cell = try DeliveryInstructionCell.resolveStrict("angry.normal")
        let generationID = UUID(uuidString: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")!
        let request = GenerationRequest(
            mode: .custom,
            modelID: "pro_custom_speed",
            text: "这个错误无法接受。",
            outputPath: "/private/angry.wav",
            shouldStream: true,
            languageHint: "chinese",
            payload: .custom(speakerID: "vivian", deliveryStyle: cell.instruction),
            generationID: generationID,
            seed: 32_060_828,
            variation: .expressive,
            deliveryInstructionCellID: cell.id
        )
        let receipt = GenerationRequestReceipt(
            request: request,
            resolvedInstruction: EmotionPreset.angryBilingualV3Mandarin,
            instructionLanguage: .mandarin,
            generationID: generationID,
            effectiveSeed: 32_060_828,
            warmState: .cold,
            predecessorIdentityDigest: nil,
            retryAttempt: 0,
            operationGeneration: 1
        )
        let englishReceipt = GenerationRequestReceipt(
            request: request,
            resolvedInstruction: EmotionPreset.angryBilingualV3English,
            instructionLanguage: .english,
            generationID: generationID,
            effectiveSeed: 32_060_828,
            warmState: .cold,
            predecessorIdentityDigest: nil,
            retryAttempt: 0,
            operationGeneration: 1
        )

        XCTAssertEqual(receipt.deliveryID, "angry.normal")
        XCTAssertEqual(receipt.instructionLanguage, "mandarin")
        XCTAssertEqual(receipt.instructionCharacters, 46)
        XCTAssertEqual(receipt.instructionDigest, "5d08a1b31bfa30c53741656f259ab0184c36f192b35b647afa78349735e9606d")
        XCTAssertNotEqual(receipt.requestIdentityDigest, englishReceipt.requestIdentityDigest)
        XCTAssertNotEqual(receipt.sessionIdentityDigest, englishReceipt.sessionIdentityDigest)
        XCTAssertNotEqual(receipt.prewarmIdentityDigest, englishReceipt.prewarmIdentityDigest)
    }

    func testReceiptBindsExactRequestWithoutRetainingScript() throws {
        let cell = try DeliveryInstructionCell.resolveStrict("calm.strong")
        let generationID = UUID(uuidString: "11111111-2222-3333-4444-555555555555")!
        let request = GenerationRequest(
            mode: .custom,
            modelID: "pro_custom_speed",
            text: "A private exact script that must not appear in the receipt.",
            outputPath: "/private/output.wav",
            shouldStream: true,
            languageHint: "english",
            payload: .custom(speakerID: "vivian", deliveryStyle: cell.instruction),
            generationID: generationID,
            seed: 38_112_001,
            variation: .balanced,
            deliveryInstructionCellID: cell.id
        )
        let receipt = GenerationRequestReceipt(
            request: request,
            generationID: generationID,
            effectiveSeed: 38_112_001,
            warmState: .cold,
            predecessorIdentityDigest: String(repeating: "b", count: 64),
            retryAttempt: 0,
            operationGeneration: 9
        )

        XCTAssertEqual(receipt.deliveryID, "calm.strong")
        XCTAssertEqual(receipt.speakerID, "vivian")
        XCTAssertEqual(receipt.language, "english")
        XCTAssertEqual(receipt.seed, 38_112_001)
        XCTAssertEqual(receipt.seedSource, "requested")
        XCTAssertEqual(receipt.retryAttempt, 0)
        XCTAssertEqual(receipt.operationGeneration, 9)
        XCTAssertEqual(receipt.predecessorIdentityDigest, String(repeating: "b", count: 64))
        let encoded = try String(data: JSONEncoder().encode(receipt), encoding: .utf8)!
        XCTAssertFalse(encoded.contains(request.text))
        XCTAssertFalse(encoded.contains(request.outputPath))
        XCTAssertFalse(encoded.contains(cell.instruction))
    }

    func testReceiptIdentityIsStableAcrossAllocationRetry() throws {
        let cell = try DeliveryInstructionCell.resolveStrict("calm.strong")
        let generationID = UUID()
        let request = GenerationRequest(
            mode: .custom,
            modelID: "pro_custom_speed",
            text: "Stable retry request.",
            outputPath: "/tmp/retry.wav",
            shouldStream: false,
            languageHint: "english",
            payload: .custom(speakerID: "vivian", deliveryStyle: cell.instruction),
            generationID: generationID,
            seed: 38_112_001,
            variation: .consistent,
            deliveryInstructionCellID: cell.id
        )
        let first = GenerationRequestReceipt(
            request: request,
            generationID: generationID,
            effectiveSeed: 38_112_001,
            warmState: .warm,
            predecessorIdentityDigest: nil,
            retryAttempt: 0,
            operationGeneration: 12
        )
        let retry = GenerationRequestReceipt(
            request: request,
            generationID: generationID,
            effectiveSeed: 38_112_001,
            warmState: .cold,
            predecessorIdentityDigest: nil,
            retryAttempt: 1,
            operationGeneration: 12
        )

        XCTAssertEqual(first.generationIdentityDigest, retry.generationIdentityDigest)
        XCTAssertEqual(first.requestIdentityDigest, retry.requestIdentityDigest)
        XCTAssertEqual(first.sessionIdentityDigest, retry.sessionIdentityDigest)
        XCTAssertEqual(first.prewarmIdentityDigest, retry.prewarmIdentityDigest)
        XCTAssertEqual(first.seed, retry.seed)
        XCTAssertEqual(first.operationGeneration, retry.operationGeneration)
        XCTAssertNotEqual(first.retryAttempt, retry.retryAttempt)
    }

    func testHistoricalStartupMarksSortByObservedTimeThenSequence() async {
        let recorder = NativeTelemetryRecorder(clock: NativeTelemetryClock())
        await recorder.mark(stage: GenerationStartupBoundary.engineOpened.telemetryStage)
        await recorder.mark(
            stage: GenerationStartupBoundary.firstDecodedAudioFrame.telemetryStage,
            atMilliseconds: 25
        )
        await recorder.mark(
            stage: GenerationStartupBoundary.firstModelToken.telemetryStage,
            atMilliseconds: 20
        )
        let startup = await recorder.snapshot().filter { $0.stage.hasPrefix("startup.") }
        XCTAssertEqual(startup.map(\.stage), [
            GenerationStartupBoundary.engineOpened.telemetryStage,
            GenerationStartupBoundary.firstModelToken.telemetryStage,
            GenerationStartupBoundary.firstDecodedAudioFrame.telemetryStage,
        ])
    }

    func testStartupBoundariesAreOneShotAndResettable() async {
        let recorder = NativeTelemetryRecorder(clock: NativeTelemetryClock())
        let stage = GenerationStartupBoundary.firstDecodedAudioFrame.telemetryStage

        await recorder.mark(stage: stage, atMilliseconds: 25)
        await recorder.mark(stage: stage, atMilliseconds: 30)
        let initialSnapshot = await recorder.snapshot()
        XCTAssertEqual(initialSnapshot.filter { $0.stage == stage }.count, 1)

        await recorder.reset()
        await recorder.mark(stage: stage, atMilliseconds: 35)
        let resetSnapshot = await recorder.snapshot()
        XCTAssertEqual(resetSnapshot.filter { $0.stage == stage }.count, 1)
    }

    func testAudioQCRejectionRemainsPostGenerationWhenSurfacedByEngine() {
        let rejection = StreamingExecutionContext.finalAudioQCRejectionError(
            flags: ["dropout:2725ms"]
        )
        let surfaced = MLXTTSEngine.surfacedGenerationError(
            rejection,
            allocationRetryAttempted: false
        )

        XCTAssertEqual(surfaced.stage, .streamFailed)
        XCTAssertEqual(surfaced.failureCode, .audioQualityRejected)
        XCTAssertEqual(surfaced.diagnosticDetail, "dropout:2725ms")
        XCTAssertEqual(surfaced.telemetryNotes["audioQCFlags"], "dropout:2725ms")
        XCTAssertTrue(surfaced.localizedDescription.contains("long silent gap"))
        XCTAssertFalse(surfaced.localizedDescription.contains("could not start"))

        let metadata = GenerationFailureDiagnosticLogger.errorMetadata(for: surfaced)
        XCTAssertEqual(metadata.code, "audio.quality_rejected")
        XCTAssertEqual(metadata.classification, .audio)
    }

    func testGenericGenerationFailureKeepsStartupPresentation() {
        let surfaced = MLXTTSEngine.surfacedGenerationError(
            TTSEngineError.generationFailed("private detail"),
            allocationRetryAttempted: true
        )

        XCTAssertEqual(surfaced.stage, .streamStartup)
        XCTAssertEqual(surfaced.failureCode, .runtimeFailed)
        XCTAssertTrue(surfaced.localizedDescription.contains("after one allocation retry"))
    }

    func testMaximumTokenLimitRemainsPostGenerationWhenSurfacedByEngine() {
        let surfaced = MLXTTSEngine.surfacedGenerationError(
            NativeRuntimeError.maximumTokenLimit(),
            allocationRetryAttempted: true
        )

        XCTAssertEqual(surfaced.stage, .streamGenerationEnded)
        XCTAssertEqual(surfaced.failureCode, .generationIncomplete)
        XCTAssertEqual(surfaced.diagnosticDetail, "maximum_tokens_before_eos")
        XCTAssertTrue(surfaced.localizedDescription.contains("generation limit"))
        XCTAssertTrue(surfaced.localizedDescription.contains("incomplete audio was not saved"))
        XCTAssertFalse(surfaced.localizedDescription.contains("could not start"))

        let metadata = GenerationFailureDiagnosticLogger.errorMetadata(for: surfaced)
        XCTAssertEqual(metadata.code, "generation.incomplete")
        XCTAssertEqual(metadata.classification, .model)
    }
}
