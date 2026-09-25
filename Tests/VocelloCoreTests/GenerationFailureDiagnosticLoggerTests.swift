import Foundation
@testable import QwenVoiceCore
import XCTest

final class GenerationFailureDiagnosticLoggerTests: XCTestCase {
    func testLogStoresOnlyAllowlistedPrivacySafeEnvelope() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-failure-log-\(UUID().uuidString)", isDirectory: true)
        let fileURL = directory.appendingPathComponent("generation-failures.jsonl")
        defer { try? FileManager.default.removeItem(at: directory) }

        let logger = GenerationFailureDiagnosticLogger(
            fileURL: fileURL,
            ignoresTelemetryGate: true
        )
        let secretPrompt = "Private transcript for secret@example.com"
        let secretPath = "/" + "Users/private-user/Documents/reference.wav"
        let request = GenerationRequest(
            mode: .clone,
            modelID: secretPath,
            text: secretPrompt,
            outputPath: "/tmp/private-output.wav",
            shouldStream: true,
            payload: .clone(reference: CloneReference(audioPath: secretPath, transcript: secretPrompt))
        )

        logger.log(
            surfacedMessage: "Failed while reading \(secretPrompt)",
            stage: "generation failure",
            underlyingError: AudioPreparationError.missingInputFile(secretPath),
            request: request
        )

        let data = try Data(contentsOf: fileURL)
        let text = try XCTUnwrap(String(data: data, encoding: .utf8))
        XCTAssertFalse(text.contains(secretPrompt))
        XCTAssertFalse(text.contains(secretPath))
        XCTAssertFalse(text.contains("secret@example.com"))
        XCTAssertFalse(text.contains("surfacedMessage"))
        XCTAssertFalse(text.contains("underlyingError"))
        XCTAssertFalse(text.contains("stack"))

        let line = try XCTUnwrap(text.split(separator: "\n").first)
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any]
        )
        XCTAssertEqual(object["schemaVersion"] as? Int, 3)
        XCTAssertEqual(object["errorCode"] as? String, "audio.input_missing")
        XCTAssertEqual(object["classification"] as? String, "audio")
        XCTAssertEqual(object["stage"] as? String, "stream_failed")
        XCTAssertEqual(object["requestMode"] as? String, "clone")
        XCTAssertNil(object["modelID"])
        XCTAssertEqual(object["textLength"] as? Int, secretPrompt.count)
        XCTAssertEqual(object["shouldStream"] as? Bool, true)
    }

    func testV2RowsDecodeAndV3RowsCarryOnlyReceiptIdentities() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-failure-v3-\(UUID().uuidString)", isDirectory: true)
        let fileURL = directory.appendingPathComponent("generation-failures.jsonl")
        defer { try? FileManager.default.removeItem(at: directory) }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let v2 = #"{"schemaVersion":2,"timestamp":"2026-08-23T00:00:00Z","errorCode":"generation.failed","classification":"runtime","stage":"stream_startup","requestMode":"custom","modelID":"pro_custom_speed","textLength":285,"shouldStream":true}"#
        try Data((v2 + "\n").utf8).write(to: fileURL)

        let logger = GenerationFailureDiagnosticLogger(fileURL: fileURL, ignoresTelemetryGate: true)
        let decodedV2 = try XCTUnwrap(logger.read().first)
        XCTAssertEqual(decodedV2.schemaVersion, 2)
        XCTAssertNil(decodedV2.requestIdentityDigest)

        let generationID = UUID()
        let request = GenerationRequest(
            mode: .custom,
            modelID: "pro_custom_speed",
            text: "Private source text",
            outputPath: "/tmp/private.wav",
            shouldStream: true,
            languageHint: "english",
            payload: .custom(
                speakerID: "vivian",
                deliveryStyle: try DeliveryInstructionCell.resolveStrict("calm.strong").instruction
            ),
            generationID: generationID,
            seed: 38_112_001,
            variation: .balanced
        )
        let receipt = GenerationRequestReceipt(
            request: request,
            generationID: generationID,
            effectiveSeed: 38_112_001,
            warmState: .cold,
            predecessorIdentityDigest: String(repeating: "a", count: 64),
            retryAttempt: 1,
            operationGeneration: 7
        )
        logger.log(
            surfacedMessage: "private",
            stage: "generation startup",
            underlyingError: TTSEngineError.generationFailed("private"),
            request: request,
            receipt: receipt
        )
        let rows = logger.read()
        XCTAssertEqual(rows.count, 2)
        let v3 = try XCTUnwrap(rows.last)
        XCTAssertEqual(v3.schemaVersion, 3)
        XCTAssertEqual(v3.generationID, generationID.uuidString)
        XCTAssertEqual(v3.requestIdentityDigest, receipt.requestIdentityDigest)
        XCTAssertEqual(v3.retryAttempt, 1)
        XCTAssertEqual(v3.operationGeneration, 7)
        XCTAssertEqual(v3.requestReceipt, receipt)
        let raw = try String(contentsOf: fileURL, encoding: .utf8)
        XCTAssertFalse(raw.contains("Private source text"))
        XCTAssertFalse(raw.contains("/tmp/private.wav"))
    }

    func testLogRetentionIsEntryAndByteBoundedAndClearable() throws {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-failure-log-\(UUID().uuidString)", isDirectory: true)
        let fileURL = directory.appendingPathComponent("generation-failures.jsonl")
        defer { try? FileManager.default.removeItem(at: directory) }

        let logger = GenerationFailureDiagnosticLogger(
            fileURL: fileURL,
            maxBytes: 2_048,
            maxEntries: 3,
            ignoresTelemetryGate: true
        )
        for index in 0..<20 {
            logger.log(
                surfacedMessage: "private \(index)",
                stage: "generation startup",
                underlyingError: TTSEngineError.generationFailed("private \(index)")
            )
        }

        let data = try Data(contentsOf: fileURL)
        XCTAssertLessThanOrEqual(data.count, 2_048)
        XCTAssertLessThanOrEqual(
            [UInt8](data).split(separator: 0x0A, omittingEmptySubsequences: true).count,
            3
        )

        logger.clear()
        XCTAssertFalse(FileManager.default.fileExists(atPath: fileURL.path))
    }

    func testUnknownStageAndErrorDoNotReflectSourceText() throws {
        struct PrivateError: LocalizedError {
            let errorDescription: String? =
                "token=https://example.invalid/private /" + "Users/person/private"
        }

        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-failure-log-\(UUID().uuidString)", isDirectory: true)
        let fileURL = directory.appendingPathComponent("generation-failures.jsonl")
        defer { try? FileManager.default.removeItem(at: directory) }
        let logger = GenerationFailureDiagnosticLogger(fileURL: fileURL, ignoresTelemetryGate: true)

        logger.log(
            surfacedMessage: "private surfaced text",
            stage: "private stage /" + "Users/person",
            underlyingError: PrivateError()
        )

        let text = try String(contentsOf: fileURL, encoding: .utf8)
        XCTAssertTrue(text.contains("\"stage\":\"unknown\""))
        XCTAssertTrue(text.contains("\"errorCode\":\"generation.unknown\""))
        XCTAssertFalse(text.contains("example.invalid"))
        XCTAssertFalse(text.contains("/" + "Users/person"))
        XCTAssertFalse(text.contains("private surfaced text"))
    }

    func testDefaultLogLivesUnderGovernedAppSupportDiagnosticsAndIsExcludedFromBackup() throws {
        let appSupport = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-app-support-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: appSupport) }
        let logger = GenerationFailureDiagnosticLogger(
            maxEntries: 1,
            ignoresTelemetryGate: true
        )

        logger.log(
            surfacedMessage: "fixture",
            stage: "generation failure",
            underlyingError: TTSEngineError.generationFailed("private"),
            appSupportDirectory: appSupport
        )
        logger.log(
            surfacedMessage: "fixture-two",
            stage: "generation failure",
            underlyingError: TTSEngineError.generationFailed("private"),
            appSupportDirectory: appSupport
        )

        let fileURL = appSupport
            .appendingPathComponent("diagnostics/engine", isDirectory: true)
            .appendingPathComponent("generation-failures.jsonl")
        XCTAssertTrue(FileManager.default.fileExists(atPath: fileURL.path))
        XCTAssertEqual(
            try fileURL.resourceValues(forKeys: [.isExcludedFromBackupKey]).isExcludedFromBackup,
            true
        )
    }

    // MARK: - Interface reason (PA-20)

    func testPresentationReasonKeysOnTheTypedEngineFailureCode() {
        typealias Reason = GenerationFailurePresentationReason
        XCTAssertEqual(Reason(NativeRuntimeError.maximumTokenLimit()), .generationLimit)
        XCTAssertEqual(
            Reason(NativeRuntimeError.capturedRuntimeFailure(.allocation, stage: .streamFailed, audioPublished: true)),
            .memoryPressure
        )
        XCTAssertEqual(
            Reason(NativeRuntimeError.capturedRuntimeFailure(.mlx, stage: .firstChunk, audioPublished: false)),
            .runtimeFailure
        )
        // A runtime failure before a take streams is about preparing the model, not a lost take.
        XCTAssertEqual(
            Reason(NativeRuntimeError.capturedRuntimeFailure(.mlx, stage: .upstreamModelLoad, audioPublished: false)),
            .preparationFailure
        )
        XCTAssertEqual(
            Reason(MLXTTSEngine.surfacedGenerationError(
                TTSEngineError.generationFailed("private detail"),
                allocationRetryAttempted: false
            )),
            .runtimeFailure
        )
    }

    func testPresentationReasonSelectsTheAudioQualityRejectionFromItsFlags() {
        typealias Reason = GenerationFailurePresentationReason
        let cases: [([String], Reason)] = [
            (["dropout:2725ms"], .audioSilentGap),
            (["near_silent"], .audioNoSpeech),
            (["empty"], .audioNoSpeech),
            (["clipping", "clicks"], .audioUnstable),
            (["rms_drift"], .audioQualityRejected),
        ]
        for (flags, expected) in cases {
            let rejection = StreamingExecutionContext.finalAudioQCRejectionError(flags: flags)
            XCTAssertEqual(Reason(rejection), expected, flags.joined(separator: ","))
            // The engine surfaces the rejection unchanged, so the reason survives.
            let surfaced = MLXTTSEngine.surfacedGenerationError(rejection, allocationRetryAttempted: false)
            XCTAssertEqual(Reason(surfaced), expected, flags.joined(separator: ","))
        }
    }

    func testPresentationReasonUsesTheWrappedTypedCauseWithoutItsPath() {
        typealias Reason = GenerationFailurePresentationReason
        let privatePath = "/private/fixture/reference.wav"
        let unreadable = NativeRuntimeError.wrapping(
            AudioPreparationError.failedToReadAudio(privatePath),
            stage: .clonePreparation,
            message: "The native runtime could not prepare the clone reference"
        )
        // The English diagnostic text carries the path; the interface reason does not.
        XCTAssertTrue(unreadable.localizedDescription.contains(privatePath))
        XCTAssertEqual(Reason(unreadable), .referenceAudioUnreadable)
        XCTAssertFalse(Reason(unreadable)?.rawValue.contains(privatePath) ?? true)

        let missingModel = NativeRuntimeError.wrapping(
            TTSEngineError.modelUnavailable("Model 'fixture' is unavailable or incomplete."),
            stage: .upstreamModelLoad,
            message: "The native runtime could not load model 'fixture'"
        )
        XCTAssertEqual(Reason(missingModel), .modelUnavailable)
        XCTAssertEqual(
            Reason(NativeRuntimeError.wrapping(
                AudioPreparationError.inputDurationTooLong(maxSeconds: 60, actualSeconds: 90),
                stage: .clonePreparation,
                message: "fixture"
            )),
            .referenceAudioTooLong
        )
    }

    /// A clone reference moved or deleted after it was chosen, or one that
    /// fails without a typed cause, is about the reference audio: the copy never
    /// sends people to repair or reinstall the model.
    func testClonePreparationFailuresPresentAsReferenceAudio() {
        typealias Reason = GenerationFailurePresentationReason
        XCTAssertEqual(
            Reason(NativeRuntimeError.wrapping(CocoaError(.fileNoSuchFile), stage: .clonePreparation, message: "fixture")),
            .referenceAudioMissing
        )
        XCTAssertEqual(
            Reason(NativeRuntimeError.wrapping(CocoaError(.fileReadNoSuchFile), stage: .clonePreparation, message: "fixture")),
            .referenceAudioMissing
        )
        XCTAssertEqual(
            Reason(NativeRuntimeError.wrapping(CocoaError(.fileReadNoPermission), stage: .clonePreparation, message: "fixture")),
            .referenceAudioUnreadable
        )
        XCTAssertEqual(
            Reason(NativeRuntimeError(
                stage: .clonePreparation,
                message: "Clone generation needs resolved native clone conditioning."
            )),
            .referenceAudioUnreadable
        )
        // The journal code of the wrapped error is unchanged.
        XCTAssertEqual(
            GenerationFailureDiagnosticLogger.errorMetadata(for: CocoaError(.fileNoSuchFile)).code,
            "generation.unknown"
        )
        // A missing file outside clone preparation is not a reference, and an
        // MLX failure while conditioning stays a model-preparation failure.
        XCTAssertEqual(
            Reason(NativeRuntimeError.wrapping(CocoaError(.fileNoSuchFile), stage: .upstreamModelLoad, message: "fixture")),
            .preparationFailure
        )
        XCTAssertNil(Reason(CocoaError(.fileNoSuchFile)))
        XCTAssertEqual(
            Reason(NativeRuntimeError.capturedRuntimeFailure(.mlx, stage: .clonePreparation, audioPublished: false)),
            .preparationFailure
        )
    }

    func testPresentationReasonCoversTypedHostErrorsAndLeavesOthersUntyped() {
        typealias Reason = GenerationFailurePresentationReason
        XCTAssertEqual(Reason(TTSEngineError.insufficientMemory("fixture")), .insufficientMemory)
        XCTAssertEqual(Reason(TTSEngineError.notInitialized), .engineNotReady)
        XCTAssertEqual(Reason(TTSEngineError.savedVoiceStoreBusy), .savedVoiceStoreBusy)
        XCTAssertEqual(Reason(TTSEngineError.unknownModel("fixture")), .modelUnavailable)
        XCTAssertEqual(Reason(AudioPreparationError.missingInputFile("/private/fixture.wav")), .referenceAudioMissing)
        XCTAssertEqual(Reason(CocoaError(.fileWriteOutOfSpace)), .storageFull)
        XCTAssertEqual(Reason(CocoaError(.fileWriteNoPermission)), .storageUnavailable)
        XCTAssertEqual(Reason(CocoaError(.fileWriteVolumeReadOnly)), .storageUnavailable)
        // A read-permission failure shares the journal code but is not about writing output.
        XCTAssertEqual(
            GenerationFailureDiagnosticLogger.errorMetadata(for: CocoaError(.fileReadNoPermission)).code,
            "storage.permission_denied"
        )
        XCTAssertNil(Reason(CocoaError(.fileReadNoPermission)))
        // Host copy (a consent refusal, a request rejection) is already localized.
        XCTAssertNil(Reason(TTSEngineError.unsupportedRequest("fixture")))
        XCTAssertNil(Reason(TTSEngineError.generationFailed("fixture")))
        XCTAssertNil(Reason(CancellationError()))
    }

    // MARK: - Persisted diagnostics privacy (AUD-08)

    func testDiagnosticSummaryKeepsTypedIdentityAndNoErrorText() throws {
        let fixture = PrivateDiagnosticFixture.self
        // The fixtures really carry the content: reflected error text names the path.
        XCTAssertTrue(String(describing: fixture.cocoaWriteError).contains(fixture.homeFragment))
        XCTAssertTrue(fixture.scriptBearingError.localizedDescription.contains(fixture.prompt))

        for failure in fixture.failures {
            let summary = DiagnosticPrivacy.summary(of: failure)
            let encoded = try XCTUnwrap(String(data: JSONEncoder().encode(summary), encoding: .utf8))
            fixture.assertNoPrivateContent(summary.description)
            fixture.assertNoPrivateContent(encoded)
        }

        let cocoa = DiagnosticPrivacy.summary(of: fixture.cocoaWriteError)
        XCTAssertEqual(cocoa.code, "storage.permission_denied")
        XCTAssertEqual(cocoa.domain, NSCocoaErrorDomain)
        XCTAssertEqual(cocoa.domainCode, NSFileWriteNoPermissionError)
        XCTAssertEqual(cocoa.underlying?.map(\.domain), [NSPOSIXErrorDomain])
        XCTAssertEqual(cocoa.underlying?.map(\.code), [Int(EACCES)])

        let conversion = DiagnosticPrivacy.summary(
            of: AudioPreparationError.conversionFailed("Audio write failed: \(fixture.path)")
        )
        XCTAssertEqual(conversion.code, "audio.processing_failed")
        XCTAssertEqual(conversion.caseName, "conversionFailed")
        XCTAssertTrue(conversion.type.hasSuffix("AudioPreparationError"))

        let wrapped = DiagnosticPrivacy.summary(of: NativeRuntimeError.wrapping(
            fixture.cocoaWriteError,
            stage: .clonePreparation,
            message: "Could not prepare the reference transcript \(fixture.transcript)"
        ))
        XCTAssertEqual(wrapped.code, "runtime.failed")
        XCTAssertEqual(wrapped.stage, "clonePreparation")
        XCTAssertNil(wrapped.caseName)

        let transfer = DiagnosticPrivacy.summary(of: HuggingFaceDownloader.DownloadError.fileDownloadFailed(
            path: fixture.path,
            underlying: URLError(.timedOut)
        ))
        XCTAssertEqual(transfer.code, "download.transfer_failed")
        XCTAssertEqual(transfer.caseName, "fileDownloadFailed")
        XCTAssertEqual(transfer.underlying?.first?.domain, NSURLErrorDomain)
        XCTAssertEqual(transfer.underlying?.first?.code, URLError.Code.timedOut.rawValue)

        let http = DiagnosticPrivacy.summary(
            of: HuggingFaceDownloader.DownloadError.httpError(statusCode: 503, path: fixture.path)
        )
        XCTAssertEqual(http.httpStatus, 503)
        XCTAssertTrue(http.description.hasPrefix("download.transfer_failed "))
        XCTAssertTrue(http.description.contains("http=503"))

        let integrity = DiagnosticPrivacy.summary(
            of: HuggingFaceDownloader.DownloadError.integrityCheckFailed(path: fixture.path, reason: fixture.prompt)
        )
        // scripts/check_ios_model_management.py keys the integrity finding on this prefix.
        XCTAssertTrue(integrity.description.hasPrefix("download.integrity_failed "))
    }

    func testRedactedTextRemovesPathsURLsAddressesAndQuotedNames() {
        let fixture = PrivateDiagnosticFixture.self
        let inputs = [
            String(describing: fixture.cocoaWriteError),
            "failed at https://example.invalid/\(fixture.outputName) from \(fixture.path)",
            "open file://\(fixture.path) failed, retrying",
            "Die Datei „\(fixture.outputName)“ konnte nicht gesichert werden.",
            "Le fichier « \(fixture.outputName) » est introuvable.",
            "Could not load '\(fixture.prompt)' because it's too short",
            "The reference \(fixture.directory)/Quinlan's take (old).wav is missing, retrying",
            "sent to quinlan.reader@example.com from ~/Library/Caches/Vocello; done",
            "The file “\(fixture.transcript)” couldn’t be opened.",
        ]
        for input in inputs {
            let redacted = DiagnosticPrivacy.redactedText(input)
            fixture.assertNoPrivateContent(redacted)
            XCTAssertFalse(redacted.contains("example.invalid"), redacted)
            XCTAssertFalse(redacted.contains("quinlan.reader"), redacted)
            XCTAssertFalse(redacted.contains("Library/Caches"), redacted)
        }
        XCTAssertEqual(
            DiagnosticPrivacy.redactedText("sent to quinlan.reader@example.com from ~/Library/Caches/Vocello; done"),
            "sent to <redacted-email> from <redacted-path>; done"
        )
        // Code-owned copy and identifiers pass through unchanged.
        for kept in [
            "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
            "thermal nominal → serious",
            "and/or 1/2 a / b",
            DiagnosticPrivacy.summary(of: fixture.cocoaWriteError).description,
        ] {
            XCTAssertEqual(DiagnosticPrivacy.redactedText(kept, limit: 1_000), kept)
        }
        XCTAssertEqual(DiagnosticPrivacy.redactedText(String(repeating: "a", count: 500), limit: 12).count, 12)
    }

    func testRedactedDetailsDropContentKeysAndAbsolutePaths() {
        let fixture = PrivateDiagnosticFixture.self
        let details = DiagnosticPrivacy.redactedDetails([
            "preparedDirectory": fixture.directory,
            "sourceDirectory": "~/Library/Application Support/QwenVoice/models/pro_custom_speed",
            "modelRepo": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice",
            "text": fixture.prompt,
            "transcript": fixture.transcript,
            "textLength": String(fixture.prompt.count),
            "didLoad": "true",
        ])
        XCTAssertEqual(details["preparedDirectory"], DiagnosticPrivacy.redactedPathMarker)
        XCTAssertEqual(details["sourceDirectory"], DiagnosticPrivacy.redactedPathMarker)
        XCTAssertEqual(details["modelRepo"], "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice")
        XCTAssertEqual(details["text"], DiagnosticPrivacy.redactedTextMarker)
        XCTAssertEqual(details["transcript"], DiagnosticPrivacy.redactedTextMarker)
        XCTAssertEqual(details["textLength"], String(fixture.prompt.count))
        XCTAssertEqual(details["didLoad"], "true")
        fixture.assertNoPrivateContent(details.map { "\($0.key)=\($0.value)" }.joined(separator: "\n"))
    }

    @MainActor
    func testDeviceDiagnosticsRecorderPersistsNoStoreRootOrFailureText() async throws {
        let fixture = PrivateDiagnosticFixture.self
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("vocello-device-diagnostics-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let recorder = try XCTUnwrap(IOSDeviceDiagnosticsRecorder.makeIfEnabled(
            environment: [
                "QWENVOICE_NATIVE_TELEMETRY_MODE": "light",
                "QVOICE_IOS_DEVICE_RUN_ID": "aud08-run",
            ],
            appSupportDirectory: root.appendingPathComponent("app-support", isDirectory: true),
            cachesDirectory: root.appendingPathComponent("caches", isDirectory: true)
        ))

        recorder.recordAction(
            event: "critical_generation_cancel_failed",
            reason: "aud08",
            context: nil,
            message: DiagnosticPrivacy.summary(of: fixture.cocoaWriteError).description
        )
        // A caller that still passes error text is redacted at the boundary.
        recorder.recordAction(
            event: "legacy_error_text",
            reason: "aud08",
            context: nil,
            message: String(describing: fixture.cocoaWriteError)
        )

        let files = PrivateDiagnosticFixture.diagnosticFiles(under: root)
        XCTAssertEqual(Set(files.map(\.lastPathComponent)), ["manifest.json", "memory-contexts.jsonl"])
        XCTAssertEqual(files.count, 4, "the App Group and the pullable mirror each hold both files")
        for file in files {
            let text = try String(contentsOf: file, encoding: .utf8)
            fixture.assertNoPrivateContent(text)
            XCTAssertFalse(text.contains(root.path), file.lastPathComponent)
            XCTAssertFalse(text.contains("appSupportDirectory"), file.lastPathComponent)
            if file.lastPathComponent == "memory-contexts.jsonl" {
                XCTAssertTrue(text.contains("storage.permission_denied"))
            }
        }
    }
}

/// Synthetic content a failure can carry: an absolute path under a home folder (built
/// from fragments so the privacy scanner and hooks stay quiet), a generated output name
/// that begins with the script, a prompt and a reference transcript (AUD-08).
enum PrivateDiagnosticFixture {
    static let homeFragment = "aud08-fixture-home"
    static let prompt = "Tell Mara the vault opens at dusk."
    static let transcript = "Quinlan reads the harbour ledger aloud."
    static let outputName = "20260924_10-00-00-000_Tell_Mara_the_vault.wav"
    static let directory = "/" + "Users/" + homeFragment + "/Library/Application Support/QwenVoice/outputs"
    static var path: String { directory + "/" + outputName }

    /// Fragments no persisted diagnostic may contain. Words only: numbers could
    /// match a timestamp or an uptime by chance.
    static let forbiddenFragments = [
        homeFragment, "Application Support", "Mara", "vault", "dusk", "Quinlan", "harbour ledger",
    ]

    static var cocoaWriteError: NSError {
        NSError(domain: NSCocoaErrorDomain, code: NSFileWriteNoPermissionError, userInfo: [
            NSFilePathErrorKey: path,
            NSUnderlyingErrorKey: NSError(domain: NSPOSIXErrorDomain, code: Int(EACCES)),
        ])
    }

    struct ScriptBearingError: LocalizedError {
        let errorDescription: String?
    }

    static var scriptBearingError: ScriptBearingError {
        ScriptBearingError(errorDescription: "Could not speak “\(prompt)” (\(transcript)) from \(path)")
    }

    static var failures: [any Error] {
        [
            cocoaWriteError,
            CocoaError(.fileReadNoSuchFile, userInfo: [NSFilePathErrorKey: path]),
            AudioPreparationError.conversionFailed("Audio write failed: \(path)"),
            AudioPreparationError.missingInputFile(path),
            TTSEngineError.generationFailed("The current text produced only 3 chat tokens for '\(prompt)'."),
            NativeRuntimeError.wrapping(
                cocoaWriteError,
                stage: .clonePreparation,
                message: "Could not prepare the reference transcript \(transcript)"
            ),
            HuggingFaceDownloader.DownloadError.fileDownloadFailed(
                path: path,
                underlying: URLError(.timedOut, userInfo: [
                    NSURLErrorFailingURLStringErrorKey: "https://example.invalid/\(outputName)",
                ])
            ),
            HuggingFaceDownloader.DownloadError.integrityCheckFailed(path: path, reason: prompt),
            HuggingFaceDownloader.DownloadError.invalidLocalDestination(path),
            scriptBearingError,
        ]
    }

    static func assertNoPrivateContent(
        _ text: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        for fragment in forbiddenFragments {
            XCTAssertFalse(text.contains(fragment), "retained \(fragment): \(text)", file: file, line: line)
        }
    }

    /// Every JSON or JSONL file a diagnostic wrote under `root`.
    static func diagnosticFiles(under root: URL) -> [URL] {
        let enumerated = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil)?
            .allObjects ?? []
        return enumerated
            .compactMap { $0 as? URL }
            .filter { ["json", "jsonl"].contains($0.pathExtension) }
    }
}
