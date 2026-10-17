import Foundation
import QwenVoiceCore

/// The desktop Saved Voices delete, on the iPhone's rule (`IOSVoicesView`,
/// F-01; BKL-13). The engine refuses a delete only during a take, but a Clone
/// line batch and a long-form Clone project read their saved voice again for
/// every line or segment, between which no take is active: the delete waits
/// while either runs. Once the voice is gone, the retained long-form project
/// that reads it can no longer resume or regenerate a segment; its History
/// stays. `MacVoicesScreen` deletes through it; `VocelloCoreTests` compiles it
/// by path and drives it over the shared long-form coordinator.
@MainActor
struct MacSavedVoiceDeletion {
    enum Refusal: Error, Equatable {
        /// A take, a line batch or a long-form project may still read the voice.
        case generationUsingVoices
    }

    let engine: TTSEngineStore
    let longForm: IOSLongFormCoordinator
    /// `MacLineBatchRunner.isProcessing`, read where this value is made.
    let isLineBatchProcessing: Bool

    /// A take, a line batch or a long-form project may still read a saved
    /// voice. The iPhone asks the same of its take and project.
    var isGenerationUsingVoices: Bool {
        engine.hasActiveGeneration || isLineBatchProcessing || longForm.isProcessing
    }

    /// Deletes the voice through the engine transaction, then releases the
    /// retained long-form project that reads it. Refused, with nothing
    /// deleted, while `isGenerationUsingVoices`.
    func delete(voiceID: String) async throws {
        guard !isGenerationUsingVoices else { throw Refusal.generationUsingVoices }
        try await engine.deletePreparedVoice(id: voiceID)
        longForm.releaseRetainedProject(usingSavedVoiceID: voiceID)
    }
}
