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
        XCTAssertEqual(receipt.modelFacingInstructionLanguage, "chinese")
        XCTAssertEqual(englishReceipt.modelFacingInstructionLanguage, "english")
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
        XCTAssertEqual(receipt.schemaVersion, 2)
        XCTAssertEqual(receipt.storedLanguageSelection, "english")
        XCTAssertEqual(receipt.detectedTargetLanguage, "english")
        XCTAssertEqual(receipt.finalModelLanguage, "english")
        XCTAssertEqual(receipt.languageTokenMode, "think")
        XCTAssertEqual(receipt.conditioningMode, "custom_voice")
        XCTAssertEqual(receipt.normalizedTargetTextCharacters, request.text.count)
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

    func testReceiptSeparatesCloneTargetAndReferenceLanguages() {
        let generationID = UUID()
        let request = GenerationRequest(
            mode: .clone,
            modelID: "pro_clone_speed",
            text: "This output must stay in English.",
            outputPath: "/tmp/clone.wav",
            shouldStream: true,
            languageHint: "auto",
            payload: .clone(reference: CloneReference(
                audioPath: "/tmp/reference.wav",
                conditioningMode: .transcriptBacked("Bonjour, ceci est la référence.")
            )),
            generationID: generationID,
            seed: 8,
            variation: .consistent
        )
        let receipt = GenerationRequestReceipt(
            request: request,
            modelFacingText: request.text,
            modelFacingLanguage: "english",
            conditioningMode: "clone_transcript_backed",
            referenceTranscript: "Bonjour, ceci est la référence.",
            referenceAudioDigest: String(repeating: "a", count: 64),
            generationID: generationID,
            effectiveSeed: 8,
            warmState: .warm,
            predecessorIdentityDigest: nil,
            retryAttempt: 0,
            operationGeneration: 3
        )

        XCTAssertEqual(receipt.storedLanguageSelection, "auto")
        XCTAssertEqual(receipt.detectedTargetLanguage, "english")
        XCTAssertEqual(receipt.referenceTranscriptLanguage, "french")
        XCTAssertEqual(receipt.finalModelLanguage, "english")
        XCTAssertEqual(receipt.conditioningMode, "clone_transcript_backed")
        XCTAssertNotNil(receipt.referenceTranscriptDigest)
        XCTAssertEqual(receipt.referenceAudioDigest, String(repeating: "a", count: 64))
    }

    func testReceiptV1StillDecodesWithoutV2Fields() throws {
        let generationID = UUID()
        let request = GenerationRequest(
            mode: .custom,
            modelID: "pro_custom_speed",
            text: "Compatibility.",
            outputPath: "/tmp/compat.wav",
            shouldStream: false,
            languageHint: "english",
            payload: .custom(speakerID: "aiden", deliveryStyle: nil),
            generationID: generationID,
            seed: 4
        )
        let current = GenerationRequestReceipt(
            request: request,
            generationID: generationID,
            effectiveSeed: 4,
            warmState: .cold,
            predecessorIdentityDigest: nil,
            retryAttempt: 0,
            operationGeneration: 1
        )
        var object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder().encode(current)) as? [String: Any]
        )
        object["schemaVersion"] = 1
        for key in [
            "storedLanguageSelection", "detectedTargetLanguage", "referenceTranscriptLanguage",
            "finalModelLanguage", "languageTokenMode", "conditioningMode",
            "normalizedTargetTextDigest", "normalizedTargetTextCharacters",
            "referenceTranscriptDigest", "referenceTranscriptCharacters", "referenceAudioDigest",
            "modelArtifactVersion", "modelIntegrityManifestDigest", "speechTokenizerDigest",
            "modelFacingInstructionLanguage",
        ] {
            object.removeValue(forKey: key)
        }
        let decoded = try JSONDecoder().decode(
            GenerationRequestReceipt.self,
            from: JSONSerialization.data(withJSONObject: object)
        )
        XCTAssertEqual(decoded.schemaVersion, 1)
        XCTAssertNil(decoded.finalModelLanguage)
        XCTAssertEqual(decoded.language, "english")
    }

    func testReceiptSeparatesVerbatimRoutingFromActualDesignInstructionLanguage() {
        let generationID = UUID()
        let request = GenerationRequest(
            mode: .design,
            modelID: "pro_design_speed",
            text: "Bonjour, cette sortie doit rester en français.",
            outputPath: "/tmp/design.wav",
            shouldStream: false,
            languageHint: "auto",
            payload: .design(
                voiceDescription: "A warm, clear narrator.",
                deliveryStyle: "Speak calmly with measured pacing."
            ),
            generationID: generationID,
            seed: 9,
            variation: .consistent
        )
        let instruction = GenerationSemantics.designInstruction(
            voiceDescription: "A warm, clear narrator.",
            emotion: "Speak calmly with measured pacing."
        )
        let receipt = GenerationRequestReceipt(
            request: request,
            resolvedInstruction: instruction,
            instructionLanguage: .verbatim,
            modelFacingText: request.text,
            modelFacingLanguage: "french",
            conditioningMode: "voice_design",
            generationID: generationID,
            effectiveSeed: 9,
            warmState: .cold,
            predecessorIdentityDigest: nil,
            retryAttempt: 0,
            operationGeneration: 1
        )

        XCTAssertEqual(receipt.instructionLanguage, "verbatim")
        XCTAssertEqual(receipt.modelFacingInstructionLanguage, "english")
        XCTAssertEqual(receipt.finalModelLanguage, "french")
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
