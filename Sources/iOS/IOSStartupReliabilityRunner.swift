import AVFoundation
import CryptoKit
import Foundation
import QwenVoiceCore

/// Physical-device-only characterization for Built-in Voice startup.
///
/// The launch input is composed by `scripts/ios_startup_reliability.py` from a
/// tracked identity-only plan and an untracked exact script. The script exists
/// only in the process environment and generated request; retained records carry
/// its digest and character count, never its bytes.
@MainActor
enum IOSStartupReliabilityRunner {
    static let environmentKey = "QVOICE_IOS_DEVICE_DELIVERY_RELIABILITY_SPEC"

    static var isRequested: Bool {
        guard let value = ProcessInfo.processInfo.environment[environmentKey]?
            .trimmingCharacters(in: .whitespacesAndNewlines) else { return false }
        return !value.isEmpty
    }

    static func runIfRequested(engine: TTSEngineStore) -> Bool {
        guard let rawSpec = ProcessInfo.processInfo.environment[environmentKey],
              !rawSpec.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return false
        }
        Task { @MainActor in
            await run(rawSpec: rawSpec, engine: engine)
        }
        return true
    }

    private static func run(rawSpec: String, engine: TTSEngineStore) async {
        var environmentRunID = "startup-reliability-invalid"
        if let object = try? JSONSerialization.jsonObject(with: Data(rawSpec.utf8)) as? [String: Any],
           let candidate = object["runID"] as? String,
           isSafeIdentifier(candidate) {
            environmentRunID = candidate
        }

        do {
            let launch = try IOSStartupReliabilityLaunchSpec.decodeAndValidate(rawSpec)
            environmentRunID = launch.runID
            guard TelemetryGate.resolvedEnabled, NativeTelemetryMode.current() == .verbose else {
                throw RunnerError.telemetryUnavailable
            }
            guard ProcessInfo.processInfo.environment["QVOICE_IOS_DEVICE_RUN_ID"] == launch.runID,
                  BenchRunContext.runID == launch.runID else {
                throw RunnerError.runIdentityMismatch
            }
            guard let model = ModelDescriptor.model(for: .custom),
                  model.preferredVariant(for: .iOS)?.kind == .speed else {
                throw RunnerError.speedModelUnavailable
            }
            let speakers = Set(ModelDescriptor.allSpeakers)
            guard launch.plan.takes.allSatisfy({ speakers.contains($0.speakerID) }) else {
                throw RunnerError.speakerUnavailable
            }

            let startedAt = ISO8601DateFormatter().string(from: Date())
            let startingDeviceState = deviceState(engine: engine, model: model)
            var takeResults: [TakeResult] = []
            var predecessorSessionDigest: String?
            defer { BenchRunContext.clearCurrentTakeFile() }

            for take in launch.plan.takes {
                let result = await execute(
                    take: take,
                    script: launch.script,
                    runID: launch.runID,
                    model: model,
                    predecessorSessionDigest: predecessorSessionDigest,
                    engine: engine
                )
                takeResults.append(result)
                if let digest = result.requestReceipt?.sessionIdentityDigest {
                    predecessorSessionDigest = digest
                } else {
                    predecessorSessionDigest = nil
                }
                try writeTake(result, runID: launch.runID)
            }

            try exportFailureJournal(runID: launch.runID, generationIDs: Set(takeResults.map(\.generationID)))
            let terminal = ResultRecord(
                status: takeResults.allSatisfy { $0.status == "pass" } ? "pass" : "diagnosed_failure",
                runID: launch.runID,
                scriptSHA256: launch.plan.scriptSHA256,
                scriptCharacters: launch.plan.scriptCharacters,
                plannedTakeCount: launch.plan.takes.count,
                representedTakeCount: takeResults.count,
                startedAt: startedAt,
                finishedAt: ISO8601DateFormatter().string(from: Date()),
                startingDeviceState: startingDeviceState,
                finishingDeviceState: deviceState(engine: engine, model: model),
                takes: takeResults
            )
            try writeTerminal(terminal, runID: launch.runID)
            print("[startup-reliability] \(terminal.status) takes=\(takeResults.count)")
        } catch {
            let metadata = GenerationFailureDiagnosticLogger.errorMetadata(for: error)
            let failure = FailureRecord(
                runID: environmentRunID,
                failedAt: ISO8601DateFormatter().string(from: Date()),
                failureCode: runnerFailureCode(error, fallback: metadata.code)
            )
            try? writeRecord(
                failure,
                name: "startup-reliability-failure.json",
                runID: environmentRunID,
                maximumBytes: 4_096
            )
            print("[startup-reliability] harness failure code=\(failure.failureCode)")
        }
    }

    private static func execute(
        take: IOSStartupReliabilityTake,
        script: String,
        runID: String,
        model: ModelDescriptor,
        predecessorSessionDigest: String?,
        engine: TTSEngineStore
    ) async -> TakeResult {
        let generationID = UUID()
        let cell = "startup/\(take.takeID)"
        let outputURL = startupOutputURL(runID: runID, take: take)
        var submitted = false
        defer { try? FileManager.default.removeItem(at: outputURL) }

        do {
            try await prepare(take.preparation, engine: engine)
            let actualWarmState = engine.loadState.currentModelID == model.id ? "warm" : "cold"
            try BenchRunContext.writeCurrentTakeFile(
                takeIndex: take.takeIndex,
                cell: cell,
                intendedWarmState: actualWarmState,
                startupPredecessorIdentityDigest: predecessorSessionDigest
            )
            let delivery = try take.deliveryCell
            let language = try take.resolvedLanguage
            let variation = try take.resolvedVariation
            let request = GenerationRequest(
                mode: .custom,
                modelID: model.id,
                text: script,
                outputPath: outputURL.path,
                shouldStream: take.streaming,
                streamingInterval: take.streaming ? GenerationSemantics.appStreamingInterval : nil,
                languageHint: language == .auto ? nil : language.rawValue,
                payload: .custom(speakerID: take.speakerID, deliveryStyle: delivery.instruction),
                generationID: generationID,
                seed: take.seed,
                variation: variation
            )

            await AppGenerationTimeline.shared.recordSubmitted(id: generationID, mode: GenerationMode.custom.rawValue)
            submitted = true
            let generationResult = try await engine.generate(request)
            await AppGenerationTimeline.shared.recordCompleted(
                id: generationID,
                mode: GenerationMode.custom.rawValue,
                usedStreaming: generationResult.usedStreaming,
                finishReason: generationResult.finishReason?.rawValue,
                summary: generationResult.telemetrySummary
            )
            submitted = false
            IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(generationID: generationID)

            let records = telemetryRecords(generationID: generationID)
            guard let final = terminalTelemetryRecord(in: records),
                  let receipt = final.requestReceipt else {
                return missingReceiptResult(take: take, generationID: generationID, preparation: take.preparation)
            }
            let evidence = try outputEvidence(at: outputURL)
            let audioQCPassed = final.audioQC.map {
                $0.verdict != .fail && $0.instabilityVerdict != .fail && $0.writtenOutputVerdict != .fail
            } ?? false
            let preparationVerified = take.preparation != .prewarmDisabled
                || generationResult.diagnosticBooleanFlags["custom_dedicated_prewarm_skipped"] == true
            guard audioQCPassed, preparationVerified else {
                return makeResult(
                    take: take,
                    generationID: generationID,
                    status: "failed",
                    receipt: receipt,
                    records: records,
                    failureCode: audioQCPassed ? "prewarm_disable_unverified" : "audio_qc_failed",
                    classification: "post_generation_qc",
                    output: evidence
                )
            }
            return makeResult(
                take: take,
                generationID: generationID,
                status: "pass",
                receipt: receipt,
                records: records,
                failureCode: nil,
                classification: "success",
                output: evidence
            )
        } catch {
            if submitted {
                await AppGenerationTimeline.shared.recordFailed(id: generationID)
            }
            IOSPullableDiagnosticsMirror.syncGenerationTelemetryIfEnabled(generationID: generationID)
            let records = telemetryRecords(generationID: generationID)
            let receipt = terminalTelemetryRecord(in: records)?.requestReceipt
            let metadata = GenerationFailureDiagnosticLogger.errorMetadata(for: error)
            let output = try? outputEvidence(at: outputURL)
            return makeResult(
                take: take,
                generationID: generationID,
                status: "failed",
                receipt: receipt,
                records: records,
                failureCode: receipt == nil ? "request_receipt_unavailable" : metadata.code,
                classification: classifyFailure(metadata: metadata, records: records, output: output),
                output: output
            )
        }
    }

    private static func prepare(
        _ preparation: IOSStartupReliabilityPreparation,
        engine: TTSEngineStore
    ) async throws {
        switch preparation {
        case .production, .prewarmDisabled:
            return
        case .fullRuntimeUnload:
            try await engine.unloadModel()
        case .preparedCacheClear:
            await engine.trimMemory(
                level: .hardTrim,
                reason: "startup_reliability_prepared_cache_clear"
            )
        }
    }

    private static func makeResult(
        take: IOSStartupReliabilityTake,
        generationID: UUID,
        status: String,
        receipt: GenerationRequestReceipt?,
        records: [GenerationTelemetryRecord],
        failureCode: String?,
        classification: String,
        output: OutputDigest?
    ) -> TakeResult {
        var attemptsByIndex: [Int: AttemptResult] = [:]
        for record in records {
            guard let receipt = record.requestReceipt else { continue }
            attemptsByIndex[receipt.retryAttempt] = AttemptResult(
                retryAttempt: receipt.retryAttempt,
                finishReason: safeIdentifier(record.finishReason) ?? "unknown",
                requestReceipt: receipt,
                startupTimeline: startupTimeline(record.stageMarks)
            )
        }
        for entry in failureJournalEntries(generationID: generationID) {
            guard let receipt = entry.requestReceipt,
                  attemptsByIndex[receipt.retryAttempt] == nil else { continue }
            attemptsByIndex[receipt.retryAttempt] = AttemptResult(
                retryAttempt: receipt.retryAttempt,
                finishReason: safeIdentifier(entry.errorCode) ?? "unknown",
                requestReceipt: receipt,
                startupTimeline: []
            )
        }
        let attempts = attemptsByIndex.values.sorted { $0.retryAttempt < $1.retryAttempt }
        let terminalTimeline = attempts.last?.startupTimeline ?? []
        return TakeResult(
            takeIndex: take.takeIndex,
            takeID: take.takeID,
            generationID: generationID.uuidString,
            status: status,
            preparation: take.preparation.rawValue,
            requestReceipt: receipt,
            attempts: attempts,
            startupTimeline: terminalTimeline,
            failureCode: failureCode,
            classification: classification,
            output: output
        )
    }

    private static func missingReceiptResult(
        take: IOSStartupReliabilityTake,
        generationID: UUID,
        preparation: IOSStartupReliabilityPreparation
    ) -> TakeResult {
        TakeResult(
            takeIndex: take.takeIndex,
            takeID: take.takeID,
            generationID: generationID.uuidString,
            status: "failed",
            preparation: preparation.rawValue,
            requestReceipt: nil,
            attempts: [],
            startupTimeline: [],
            failureCode: "request_receipt_unavailable",
            classification: "unmaterialized_unknown",
            output: nil
        )
    }

    private static func classifyFailure(
        metadata: GenerationFailureDiagnosticLogger.ErrorMetadata,
        records: [GenerationTelemetryRecord],
        output: OutputDigest?
    ) -> String {
        if metadata.classification == .cancelled { return "cancelled" }
        if metadata.classification == .memory { return "memory_failure" }
        if metadata.code.contains("timeout") { return "timeout" }
        let stages = records.flatMap(\.stageMarks).map(\.stage)
        if output != nil || stages.contains(GenerationStartupBoundary.firstDecodedAudioFrame.telemetryStage) {
            return "post_generation_qc"
        }
        if stages.contains(where: { $0.hasPrefix("startup.") }) { return "pre_audio_startup" }
        return "unmaterialized_unknown"
    }

    private static func telemetryRecords(generationID: UUID) -> [GenerationTelemetryRecord] {
        let url = AppPaths.appSupportDir
            .appendingPathComponent("diagnostics/engine/generations.jsonl", isDirectory: false)
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return [] }
        let decoder = JSONDecoder()
        return text.split(separator: "\n").compactMap { line in
            guard line.contains(generationID.uuidString),
                  let data = line.data(using: .utf8),
                  let record = try? decoder.decode(GenerationTelemetryRecord.self, from: data),
                  record.layer == .engine,
                  record.generationID == generationID.uuidString else { return nil }
            return record
        }
    }

    private static func failureJournalEntries(
        generationID: UUID
    ) -> [GenerationFailureJournalEntry] {
        GenerationFailureDiagnosticLogger.shared
            .read(appSupportDirectory: AppPaths.appSupportDir)
            .filter { $0.generationID == generationID.uuidString }
    }

    private static func terminalTelemetryRecord(
        in records: [GenerationTelemetryRecord]
    ) -> GenerationTelemetryRecord? {
        records.max {
            let lhs = $0.requestReceipt?.retryAttempt ?? -1
            let rhs = $1.requestReceipt?.retryAttempt ?? -1
            return lhs < rhs
        }
    }

    private static func startupTimeline(_ marks: [NativeTelemetryStageMark]) -> [BoundaryResult] {
        marks.compactMap { mark in
            guard mark.stage.hasPrefix("startup."),
                  let boundary = GenerationStartupBoundary(
                    rawValue: String(mark.stage.dropFirst("startup.".count))
                  ) else { return nil }
            return BoundaryResult(boundary: boundary.rawValue, tMS: mark.tMS)
        }.sorted { lhs, rhs in
            lhs.tMS == rhs.tMS ? lhs.boundary < rhs.boundary : lhs.tMS < rhs.tMS
        }
    }

    private static func outputEvidence(at url: URL) throws -> OutputDigest {
        let audio = try AVAudioFile(forReading: url)
        guard audio.length > 0, audio.fileFormat.sampleRate > 0 else {
            throw RunnerError.outputInvalid
        }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        var byteCount = 0
        while let chunk = try handle.read(upToCount: 256 * 1_024), !chunk.isEmpty {
            hasher.update(data: chunk)
            byteCount += chunk.count
        }
        return OutputDigest(
            sha256: hasher.finalize().map { String(format: "%02x", $0) }.joined(),
            byteCount: byteCount,
            durationSeconds: Double(audio.length) / audio.fileFormat.sampleRate
        )
    }

    private static func startupOutputURL(runID: String, take: IOSStartupReliabilityTake) -> URL {
        let directory = AppPaths.outputsDir
            .appendingPathComponent("startup-reliability", isDirectory: true)
            .appendingPathComponent(runID, isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory.appendingPathComponent(
            String(format: "take-%03d.wav", take.takeIndex),
            isDirectory: false
        )
    }

    private static func deviceState(engine: TTSEngineStore, model: ModelDescriptor) -> DeviceState {
        let process = ProcessInfo.processInfo
        return DeviceState(
            lowPowerModeEnabled: process.isLowPowerModeEnabled,
            thermalState: thermalState(process.thermalState),
            modelInstalled: model.isAvailable(in: AppPaths.modelsDir),
            loadedModelID: safeIdentifier(engine.loadState.currentModelID)
        )
    }

    private static func thermalState(_ value: ProcessInfo.ThermalState) -> String {
        switch value {
        case .nominal: "nominal"
        case .fair: "fair"
        case .serious: "serious"
        case .critical: "critical"
        @unknown default: "unknown"
        }
    }

    private static func exportFailureJournal(runID: String, generationIDs: Set<String>) throws {
        let rows = GenerationFailureDiagnosticLogger.shared
            .read(appSupportDirectory: AppPaths.appSupportDir)
            .filter { entry in entry.generationID.map(generationIDs.contains) == true }
        guard !rows.isEmpty else { return }
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        encoder.dateEncodingStrategy = .iso8601
        let data = try rows.reduce(into: Data()) { payload, row in
            payload.append(try encoder.encode(row))
            payload.append(0x0A)
        }
        try writeData(
            data,
            name: "generation-failures.jsonl",
            runID: runID,
            maximumBytes: GenerationFailureDiagnosticLogger.defaultMaxBytes
        )
    }

    private static func writeTake(_ result: TakeResult, runID: String) throws {
        try writeRecord(
            result,
            name: String(format: "startup-reliability-take-%03d.json", result.takeIndex),
            runID: runID,
            maximumBytes: 128 * 1_024
        )
    }

    private static func writeTerminal(_ result: ResultRecord, runID: String) throws {
        try writeRecord(
            result,
            name: "startup-reliability-result.json",
            runID: runID,
            maximumBytes: 4 * 1_024 * 1_024
        )
    }

    private static func writeRecord<T: Encodable>(
        _ record: T,
        name: String,
        runID: String,
        maximumBytes: Int
    ) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        let data = try encoder.encode(record)
        try writeData(data, name: name, runID: runID, maximumBytes: maximumBytes)
    }

    private static func writeData(
        _ data: Data,
        name: String,
        runID: String,
        maximumBytes: Int
    ) throws {
        guard data.count <= maximumBytes,
              isSafeIdentifier(runID),
              !name.contains("/") else { throw RunnerError.recordInvalid }
        let destinations = [
            AppPaths.appSupportDir
                .appendingPathComponent("diagnostics", isDirectory: true)
                .appendingPathComponent(runID, isDirectory: true)
                .appendingPathComponent(name, isDirectory: false),
            IOSPullableDiagnosticsMirror.pullableRoot?
                .appendingPathComponent(runID, isDirectory: true)
                .appendingPathComponent(name, isDirectory: false),
        ].compactMap { $0 }
        guard destinations.count == 2 else { throw RunnerError.pullableDirectoryUnavailable }
        for destination in destinations {
            try FileManager.default.createDirectory(
                at: destination.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            try data.write(to: destination, options: .atomic)
        }
    }

    private static func safeIdentifier(_ value: String?) -> String? {
        guard let value, isSafeIdentifier(value) else { return nil }
        return value
    }

    private static func isSafeIdentifier(_ value: String) -> Bool {
        guard (1...96).contains(value.count) else { return false }
        return value.unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics.contains($0) || $0 == "." || $0 == "_" || $0 == "-"
        }
    }

    private static func runnerFailureCode(_ error: Error, fallback: String) -> String {
        (error as? RunnerError)?.rawValue ?? fallback
    }

    private struct BoundaryResult: Codable {
        let boundary: String
        let tMS: Int
    }

    private struct AttemptResult: Codable {
        let retryAttempt: Int
        let finishReason: String
        let requestReceipt: GenerationRequestReceipt
        let startupTimeline: [BoundaryResult]
    }

    private struct OutputDigest: Codable {
        let sha256: String
        let byteCount: Int
        let durationSeconds: Double
    }

    private struct DeviceState: Codable {
        let lowPowerModeEnabled: Bool
        let thermalState: String
        let modelInstalled: Bool
        let loadedModelID: String?
    }

    private struct TakeResult: Codable {
        let takeIndex: Int
        let takeID: String
        let generationID: String
        let status: String
        let preparation: String
        let requestReceipt: GenerationRequestReceipt?
        let attempts: [AttemptResult]
        let startupTimeline: [BoundaryResult]
        let failureCode: String?
        let classification: String
        let output: OutputDigest?
    }

    private struct ResultRecord: Codable {
        var schemaVersion = 1
        let status: String
        let runID: String
        let scriptSHA256: String
        let scriptCharacters: Int
        let plannedTakeCount: Int
        let representedTakeCount: Int
        let startedAt: String
        let finishedAt: String
        let startingDeviceState: DeviceState
        let finishingDeviceState: DeviceState
        let takes: [TakeResult]
    }

    private struct FailureRecord: Codable {
        var schemaVersion = 1
        let runID: String
        let failedAt: String
        let failureCode: String
    }

    private enum RunnerError: String, LocalizedError {
        case telemetryUnavailable = "telemetry_unavailable"
        case runIdentityMismatch = "run_identity_mismatch"
        case speedModelUnavailable = "speed_model_unavailable"
        case speakerUnavailable = "speaker_unavailable"
        case outputInvalid = "output_invalid"
        case recordInvalid = "record_invalid"
        case pullableDirectoryUnavailable = "pullable_directory_unavailable"

        var errorDescription: String? { rawValue }
    }
}
