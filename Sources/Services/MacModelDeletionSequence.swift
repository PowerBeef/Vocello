import Foundation
import QwenVoiceCore

/// What a model deletion needs from the in-process engine (MAC-20).
@MainActor
protocol MacModelEngineCoordinating: AnyObject {
    /// A take is generating.
    var hasActiveGeneration: Bool { get }
    /// A line batch or long-form project holds the engine for its whole run,
    /// including the moments between two takes, when no take is generating.
    var hasSustainedPerformanceActivity: Bool { get }
    /// A load, warm or clone-reference prime is under way. A cold load
    /// publishes `.starting`, which names no model, so it holds off the
    /// deletion of any model.
    var hasModelOperationInFlight: Bool { get }
    /// The model whose weights are resident.
    var loadedModelID: String? { get }
    func unloadModel() async throws
}

extension TTSEngineStore: MacModelEngineCoordinating {
    var hasModelOperationInFlight: Bool {
        MacModelDeletionSequence.showsModelOperation(
            loadState: loadState,
            clonePreparationPhase: clonePreparationState.phase
        )
    }

    var loadedModelID: String? { loadState.currentModelID }
}

/// The engine side of a model deletion (MAC-20), driven over a fake engine in
/// `VocelloCoreTests`.
///
/// A model's files are never removed while the engine generates, holds a line
/// batch or long-form project between two takes, or loads, warms or primes a
/// model, and the model's weights are released first when they are loaded.
/// Every await lets a take or a warm start, so the engine is read again after
/// each one, and the files are removed in the same main-actor turn as the last
/// read.
enum MacModelDeletionSequence {
    enum Failure: Equatable, Sendable {
        /// The engine refused to release the model's weights (a generation got
        /// there first); the files were kept.
        case engineRelease
        /// The files could not be removed.
        case fileRemoval
    }

    enum Outcome: Equatable, Sendable {
        case deleted
        /// The engine is busy with a take, a multi-take run or a model load;
        /// the model's files were kept.
        case blockedByActiveGeneration
        case failed(Failure)

        /// A busy engine, including an unload it refused, shows the localized
        /// "Generation in Progress" alert. A removal failure is reported on the
        /// model's row instead.
        var showsEngineBusyAlert: Bool {
            switch self {
            case .blockedByActiveGeneration, .failed(.engineRelease):
                true
            case .deleted, .failed(.fileRemoval):
                false
            }
        }
    }

    /// What the engine allows for one model right now.
    enum EngineGate: Equatable, Sendable {
        /// Generating, between the takes of a multi-take run, or loading.
        case busy
        /// Idle with this model's weights resident: release them first.
        case loaded
        /// Nothing in the engine reads this model's files.
        case clear
    }

    @MainActor
    static func gate(for modelID: String, engine: (any MacModelEngineCoordinating)?) -> EngineGate {
        guard let engine else { return .clear }
        if engine.hasActiveGeneration
            || engine.hasSustainedPerformanceActivity
            || engine.hasModelOperationInFlight {
            return .busy
        }
        return engine.loadedModelID == modelID ? .loaded : .clear
    }

    /// The load states in which the engine is still loading or priming: a cold
    /// load's `.starting` and every `.running` state, plus a clone reference
    /// being prepared.
    static func showsModelOperation(
        loadState: EngineLoadState,
        clonePreparationPhase: ClonePreparationPhase
    ) -> Bool {
        if clonePreparationPhase == .preparing { return true }
        switch loadState {
        case .starting, .running:
            return true
        case .idle, .loaded, .failed:
            return false
        }
    }

    /// Deletes one model's files unless the engine is using it.
    ///
    /// - Parameters:
    ///   - stopDownloads: stops the model's download and its staging; runs only
    ///     once the engine allowed the deletion and released the weights.
    ///   - removeFiles: removes the installed files and reports whether that
    ///     worked; runs synchronously right after the last engine read.
    ///   - unloadFailed: receives the error of a refused unload, for diagnostics.
    @MainActor
    static func run(
        modelID: String,
        engine: (any MacModelEngineCoordinating)?,
        stopDownloads: () async -> Void,
        removeFiles: () -> Bool,
        unloadFailed: (any Error) -> Void = { _ in }
    ) async -> Outcome {
        // Before anything changes: a busy engine leaves everything as it was.
        let initialGate = gate(for: modelID, engine: engine)
        guard initialGate != .busy else { return .blockedByActiveGeneration }
        if initialGate == .loaded, let engine {
            do {
                try await engine.unloadModel()
            } catch {
                unloadFailed(error)
                return .failed(.engineRelease)
            }
            guard gate(for: modelID, engine: engine) == .clear else { return .blockedByActiveGeneration }
        }
        await stopDownloads()
        // The last read and the removal share one main-actor turn, so nothing
        // can start in between.
        guard gate(for: modelID, engine: engine) == .clear else { return .blockedByActiveGeneration }
        return removeFiles() ? .deleted : .failed(.fileRemoval)
    }
}
