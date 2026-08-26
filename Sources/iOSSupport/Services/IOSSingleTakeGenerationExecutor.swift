import Foundation
import QwenVoiceCore

/// Immutable identity and presentation metadata for one short-form Studio take.
///
/// The request remains the engine source of truth. This wrapper fails closed when
/// the app has not minted the generation identity required to correlate frontend,
/// middle-layer, engine, persistence, and diagnostics evidence.
struct IOSSingleTakeGenerationPlan: Hashable, Sendable {
    enum ValidationError: LocalizedError, Equatable {
        case missingGenerationID
        case emptyModelTier
        case emptyDisplayVoiceName
        case emptyModeLabel
        case emptyPersistenceCaller

        var errorDescription: String? {
            switch self {
            case .missingGenerationID:
                return "The generation request is missing its correlation identity."
            case .emptyModelTier:
                return "The generation plan is missing its model tier."
            case .emptyDisplayVoiceName:
                return "The generation plan is missing its display voice name."
            case .emptyModeLabel:
                return "The generation plan is missing its mode label."
            case .emptyPersistenceCaller:
                return "The generation plan is missing its persistence owner."
            }
        }
    }

    let generationID: UUID
    let request: GenerationRequest
    let modelTier: String
    let historyVoice: String?
    let historyEmotion: String?
    let displayVoiceName: String
    let modeLabel: String
    let waveformSeed: Int
    let persistenceCaller: String

    init(
        request: GenerationRequest,
        modelTier: String,
        historyVoice: String?,
        historyEmotion: String?,
        displayVoiceName: String,
        modeLabel: String,
        waveformSeed: Int,
        persistenceCaller: String
    ) throws {
        guard let generationID = request.generationID else {
            throw ValidationError.missingGenerationID
        }
        guard !modelTier.isEmpty else { throw ValidationError.emptyModelTier }
        guard !displayVoiceName.isEmpty else { throw ValidationError.emptyDisplayVoiceName }
        guard !modeLabel.isEmpty else { throw ValidationError.emptyModeLabel }
        guard !persistenceCaller.isEmpty else { throw ValidationError.emptyPersistenceCaller }

        self.generationID = generationID
        self.request = request
        self.modelTier = modelTier
        self.historyVoice = historyVoice
        self.historyEmotion = historyEmotion
        self.displayVoiceName = displayVoiceName
        self.modeLabel = modeLabel
        self.waveformSeed = waveformSeed
        self.persistenceCaller = persistenceCaller
    }
}

/// Side-effect boundary for the shared short-form generation pipeline.
///
/// Keeping this protocol MainActor-isolated preserves the app's existing
/// frontend ownership while allowing deterministic fakes to characterize the
/// ordering and cancellation contract without loading models or launching UI.
@MainActor
protocol IOSSingleTakeGenerationExecutionHooks: AnyObject {
    func generationSubmitted(_ plan: IOSSingleTakeGenerationPlan) async
    func generate(_ request: GenerationRequest) async throws -> GenerationResult
    func generationCompleted(
        _ result: GenerationResult,
        plan: IOSSingleTakeGenerationPlan
    ) async
    func generationCancelled(
        materializedResult: GenerationResult?,
        plan: IOSSingleTakeGenerationPlan
    ) async
    func generationFailed(_ plan: IOSSingleTakeGenerationPlan) async
}

/// Singular lifecycle authority for ordinary iOS Studio takes.
///
/// Clone reference preparation and mode-specific request construction happen
/// before this boundary. Successful UI publication happens after it. Everything
/// between those boundaries is identical across Built-in, Design, and Clone and
/// therefore must not drift among three view implementations.
@MainActor
enum IOSSingleTakeGenerationExecutor {
    static func run(
        plan: IOSSingleTakeGenerationPlan,
        hooks: any IOSSingleTakeGenerationExecutionHooks
    ) async throws -> GenerationResult {
        await hooks.generationSubmitted(plan)
        var cancellationWasHandled = false

        do {
            let result = try await hooks.generate(plan.request)
            if Task.isCancelled {
                cancellationWasHandled = true
                await hooks.generationCancelled(
                    materializedResult: result,
                    plan: plan
                )
                throw CancellationError()
            }

            await hooks.generationCompleted(result, plan: plan)
            return result
        } catch is CancellationError {
            if !cancellationWasHandled {
                await hooks.generationCancelled(
                    materializedResult: nil,
                    plan: plan
                )
            }
            throw CancellationError()
        } catch {
            // Engine cancellation can arrive wrapped in a backend error. Task
            // ownership, not error-string parsing, determines the terminal.
            if Task.isCancelled {
                await hooks.generationCancelled(
                    materializedResult: nil,
                    plan: plan
                )
                throw CancellationError()
            }

            await hooks.generationFailed(plan)
            throw error
        }
    }
}
