import Foundation
import QwenVoiceCore

/// Finite stop-on-first-failure batch. Every planned row survives failure; no
/// retry, replacement seed, or implicit resume is performed.
@MainActor
enum CLIBatchExecution {
    enum Status: String, Codable { case completed, failed, cancelled, notAttempted = "not_attempted" }
    struct Row: Encodable {
        let index: Int
        let generationID: UUID?
        var status: Status = .notAttempted
        var audioPath: String?
        var durationSeconds: Double?
        var finishReason: String?
        var errorCode: String?
    }
    struct Outcome {
        let rows: [Row]
        let results: [GenerationResult]
        var passed: Bool { rows.allSatisfy { $0.status == .completed } }
        var cancelled: Bool { rows.contains { $0.status == .cancelled } }
    }

    static func run(
        _ requests: [GenerationRequest],
        generate: (GenerationRequest) async throws -> GenerationResult
    ) async -> Outcome {
        var rows = requests.enumerated().map { Row(index: $0.offset, generationID: $0.element.generationID) }
        var results: [GenerationResult] = []
        for (index, request) in requests.enumerated() {
            do {
                try Task.checkCancellation()
                let result = try await generate(request)
                // Publication is an irreversible commit. Preserve a returned
                // successful result even if a signal arrived immediately after.
                guard FileManager.default.fileExists(atPath: result.audioPath) else {
                    rows[index].status = .failed
                    rows[index].errorCode = "published_output_missing"
                    break
                }
                rows[index].status = .completed
                rows[index].audioPath = result.audioPath
                rows[index].durationSeconds = result.durationSeconds
                rows[index].finishReason = result.finishReason?.rawValue
                results.append(result)
            } catch {
                rows[index].status = Task.isCancelled || error is CancellationError ? .cancelled : .failed
                rows[index].errorCode = rows[index].status == .cancelled ? "cancelled" : "generation_failed"
                break
            }
        }
        return Outcome(rows: rows, results: results)
    }
}
