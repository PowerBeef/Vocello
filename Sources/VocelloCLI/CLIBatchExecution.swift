import Foundation
import QwenVoiceCore

/// Finite stop-on-first-failure batch. Every planned row survives failure; no
/// retry, replacement seed, or implicit resume is performed.
@MainActor
enum CLIBatchExecution {
    /// Every short-form line must hold one take; the error names the first
    /// line that does not.
    nonisolated static func validateShortFormLines(_ lines: [String]) throws {
        for (index, line) in lines.enumerated() {
            do {
                try GenerateCommand.validateSingleTakeText(line)
            } catch let error as CLIError {
                throw CLIError("line \(index + 1): \(error.description)")
            }
        }
    }

    /// Batch bookkeeping belongs to the CLI. Each request uses the ordinary
    /// single-take API; do not attach engine batch-only fields here.
    /// `captureCodecTrace` (`--capture-codec-trace`, internal diagnostics only)
    /// asks the engine for each take's bounded codec trace; it changes no
    /// sampled code or published sample.
    static func makeRequests(
        lines: [String], mode: GenerationMode, modelID: String,
        outputDirectory: URL, filenamePrefix: String,
        payload: GenerationRequest.Payload, seed: UInt64?, variation: Qwen3SamplingVariation?,
        deliveryInstructionCellID: String?, captureCodecTrace: Bool = false
    ) -> [GenerationRequest] {
        lines.enumerated().map { index, text in
            let name = "\(filenamePrefix)_\(mode.rawValue)_\(String(format: "%03d", index)).wav"
            return GenerationRequest(
                mode: mode, modelID: modelID, text: text,
                outputPath: outputDirectory.appendingPathComponent(name).path,
                shouldStream: false,
                payload: payload, generationID: UUID(), seed: seed, variation: variation,
                captureCodecTrace: captureCodecTrace ? true : nil,
                deliveryInstructionCellID: deliveryInstructionCellID
            )
        }
    }

    /// One segment of a long-form project as the apps' runner requests it: a
    /// streaming take at the app cadence with the planner's derived subseed;
    /// the delivery cell travels on Custom only.
    static func makeLongFormSegmentRequest(
        mode: GenerationMode, modelID: String, text: String, outputPath: String,
        payload: GenerationRequest.Payload, generationID: UUID, subseed: UInt64,
        variation: Qwen3SamplingVariation?, deliveryInstructionCellID: String?
    ) -> GenerationRequest {
        GenerationRequest(
            mode: mode, modelID: modelID, text: text, outputPath: outputPath,
            shouldStream: true,
            streamingInterval: GenerationSemantics.appStreamingInterval,
            payload: payload, generationID: generationID, seed: subseed, variation: variation,
            deliveryInstructionCellID: mode == .custom ? deliveryInstructionCellID : nil
        )
    }

    /// The apps' delivery for an item nobody styled (`--app-delivery`): a new
    /// Studio draft is the Neutral preset, so Custom and Design carry its
    /// instruction (the engine drops it on a model without instruction
    /// control). Without the flag, programmatic requests stay uninstructed
    /// (`EmotionPreset.neutralPresetInstruction`); an explicit --delivery or
    /// --delivery-cell always wins, and Clone has no instruction channel.
    static func applyingAppDefaultDelivery(to payload: GenerationRequest.Payload) -> GenerationRequest.Payload {
        switch payload {
        case .custom(let speakerID, .none):
            return .custom(speakerID: speakerID, deliveryStyle: EmotionPreset.neutralPresetInstruction)
        case .design(let voiceDescription, .none):
            return .design(voiceDescription: voiceDescription, deliveryStyle: EmotionPreset.neutralPresetInstruction)
        case .custom, .design, .clone:
            return payload
        }
    }

    enum Status: String, Codable { case completed, failed, cancelled, notAttempted = "not_attempted" }
    struct Row: Encodable {
        let index: Int
        let generationID: UUID?
        var status: Status = .notAttempted
        var audioPath: String?
        var durationSeconds: Double?
        var finishReason: String?
        var errorCode: String?
        /// Set only on a `failed` row whose failure coincided with a
        /// cancellation request; the failure is still the reported outcome.
        var cancellationRequested: Bool?
    }
    struct Outcome {
        let rows: [Row]
        let results: [GenerationResult]
        /// The engine stopped a take on its own (P15-02); that row is `failed`
        /// with the reason as its code, and the command exits with its status.
        var engineCancellation: CLIEngineCancellation?
        var passed: Bool { rows.allSatisfy { $0.status == .completed } }
        var cancelled: Bool { rows.contains { $0.status == .cancelled } }
    }

    static func run(
        _ requests: [GenerationRequest],
        progress: (Int, Int) -> Void = { _, _ in },
        generate: (GenerationRequest) async throws -> GenerationResult
    ) async -> Outcome {
        var rows = requests.enumerated().map { Row(index: $0.offset, generationID: $0.element.generationID) }
        var results: [GenerationResult] = []
        var engineCancellation: CLIEngineCancellation?
        for (index, request) in requests.enumerated() {
            do {
                try Task.checkCancellation()
                progress(index, requests.count)
                let result = try await generate(request)
                // Publication is an irreversible commit. Preserve a returned
                // successful result even if a signal arrived immediately after.
                guard FileManager.default.fileExists(atPath: result.audioPath) else {
                    rows[index].fail("published_output_missing")
                    break
                }
                rows[index].status = .completed
                rows[index].audioPath = result.audioPath
                rows[index].durationSeconds = result.durationSeconds
                rows[index].finishReason = result.finishReason?.rawValue
                results.append(result)
            } catch let stopped as CLIEngineCancellation {
                // The engine stopped the take on its own (memory pressure): a
                // failure with its reason, not the operator's interrupt.
                rows[index].fail(stopped.errorCode)
                engineCancellation = stopped
                break
            } catch is CancellationError {
                rows[index].status = .cancelled
                rows[index].errorCode = "cancelled"
                break
            } catch {
                // Typed: the engine reports cancellation only as
                // CancellationError, so a genuine failure that coincides with
                // a signal stays failed.
                rows[index].fail("generation_failed")
                break
            }
        }
        return Outcome(rows: rows, results: results, engineCancellation: engineCancellation)
    }
}

private extension CLIBatchExecution.Row {
    mutating func fail(_ code: String) {
        status = .failed
        errorCode = code
        if Task.isCancelled { cancellationRequested = true }
    }
}
