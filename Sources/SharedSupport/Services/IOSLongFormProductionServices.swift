import Foundation
import QwenVoiceCore

/// The long-form runner's shared collaborators in both apps: each member makes
/// exactly the call `IOSLongFormProject.swift` made inline before the PA-19
/// seam. Each app compiles its own `AudioService` and `AppPaths`, so the output
/// location, the auto-play preference and the History location stay per
/// platform. Not compiled into `VocelloCoreTests`, which substitutes a fake
/// over a private History.
@MainActor
final class IOSLongFormProductionServices: IOSLongFormProjectServices {
    init() {}

    var shouldAutoPlay: Bool { AudioService.shouldAutoPlay }

    func segmentOutputPath(subfolder: String, text: String) -> String {
        AudioService.makeOutputPath(subfolder: subfolder, text: text)
    }

    func recordSubmitted(id: UUID, mode: String) async {
        await AppGenerationTimeline.shared.recordSubmitted(id: id, mode: mode)
    }

    func recordCompleted(
        id: UUID,
        mode: String,
        usedStreaming: Bool,
        finishReason: String?,
        summary: TelemetrySummary?
    ) async {
        await AppGenerationTimeline.shared.recordCompleted(
            id: id,
            mode: mode,
            usedStreaming: usedStreaming,
            finishReason: finishReason,
            summary: summary
        )
    }

    func recordFailed(id: UUID, finishReason: GenerationTerminalReason) async {
        await AppGenerationTimeline.shared.recordFailed(id: id, finishReason: finishReason)
    }

    func persistSegment(_ record: Generation, caller: String) async -> GenerationHistoryPersistenceOutcome {
        await GenerationPersistence.persist(record, caller: caller)
    }

    func acceptLongFormProject(_ candidate: LongFormHistoryAcceptance) async throws -> Generation {
        try await DatabaseService.shared.acceptLongFormProject(candidate)
    }
}

extension IOSLongFormCoordinator {
    /// The coordinator both apps own, on the production services.
    convenience init(hooks: any IOSLongFormPlatformHooks) {
        self.init(hooks: hooks, services: IOSLongFormProductionServices())
    }
}
