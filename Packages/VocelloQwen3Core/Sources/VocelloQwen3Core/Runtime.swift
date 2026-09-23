import Foundation
import HuggingFace
import MLX
import MLXAudioTTS
import os

/// First-party cache selection for the owned runtime.
///
/// Hugging Face's concrete cache type remains an implementation detail. The
/// default case preserves the package's existing environment-aware cache
/// behavior; callers that own a fixed cache root can select it explicitly.
public enum VocelloQwen3CachePolicy: Hashable, Sendable {
    case systemDefault
    case directory(URL)

    var compatibilityValue: HubCache {
        switch self {
        case .systemDefault:
            return .default
        case .directory(let directory):
            return HubCache(cacheDirectory: directory)
        }
    }
}

/// Stable first-party entry point over the compatibility-preserved runtime
/// implementation modules.
public enum VocelloQwen3Runtime {
    public static func prepareModelBundle(_ bundle: VocelloQwen3PreparedModelBundle) throws {
        try prepareModelDirectory(
            at: bundle.preparedDirectory,
            repositoryID: bundle.identity.repositoryID,
            modelType: bundle.modelType
        )
    }

    public static func prepareModelDirectory(
        at directory: URL,
        repositoryID: String,
        modelType: String?
    ) throws {
        try TTS.preparePreparedDirectory(
            directory,
            modelRepo: repositoryID,
            modelType: modelType
        )
    }

    static func loadPreparedModel(
        _ bundle: VocelloQwen3PreparedModelBundle,
        loadBehavior: VocelloQwen3LoadBehavior? = nil,
        cachePolicy: VocelloQwen3CachePolicy = .systemDefault,
        diagnosticSink: VocelloQwen3DiagnosticSink? = nil,
        verboseDiagnosticSink: VocelloQwen3VerboseLoadDiagnosticSink? = nil,
        isolation: isolated (any Actor)? = #isolation
    ) async throws -> VocelloQwen3LoadedModel {
        let compatibilitySink: (@Sendable (String, [String: String]) async -> Void)?
        if diagnosticSink != nil || verboseDiagnosticSink != nil {
            compatibilitySink = { action, details in
                if let verboseDiagnosticSink {
                    await verboseDiagnosticSink(action, details)
                }
                if let diagnosticSink {
                    await diagnosticSink(typedDiagnosticEvent(forCompatibilityAction: action))
                }
            }
        } else {
            compatibilitySink = nil
        }

        let compatibilityModel = try await TTS.loadModel(
            fromPreparedDirectory: bundle.preparedDirectory,
            modelRepo: bundle.identity.repositoryID,
            modelType: bundle.modelType,
            trustPreparedCheckpoint: bundle.trustedPreparedCheckpoint,
            qwenPreparedLoadBehavior: loadBehavior?.compatibilityValue,
            diagnosticEventSink: compatibilitySink,
            cache: cachePolicy.compatibilityValue,
            isolation: isolation
        )
        return try VocelloQwen3LoadedModel(
            compatibilityModel: compatibilityModel,
            identity: bundle.identity,
            capabilities: bundle.capabilities
        )
    }

    /// Clears Qwen3-owned prepared, conditioning, and decoder caches after the
    /// host has proven that active generation terminated. The product controls
    /// when this lifecycle boundary is safe; cache implementation stays here.
    public static func clearRuntimeCaches(
        isolation: isolated (any Actor)? = #isolation
    ) async {
        await Qwen3TTSMemoryCaches.clearAll(isolation: isolation)
    }

    static func typedDiagnosticEvent(
        forCompatibilityAction action: String
    ) -> VocelloQwen3DiagnosticEvent {
        let lowercased = action.lowercased()
        let phase: VocelloQwen3DiagnosticPhase
        if lowercased.contains("load") {
            phase = .modelLoad
        } else if lowercased.contains("prepare") || lowercased.contains("tokenizer") {
            phase = .modelPreparation
        } else if lowercased.contains("prewarm") {
            phase = .prewarm
        } else if lowercased.contains("decode") || lowercased.contains("codec") {
            phase = .decode
        } else if lowercased.contains("final") || lowercased.contains("complete") {
            phase = .finalization
        } else {
            phase = .synthesis
        }

        let disposition: VocelloQwen3DiagnosticDisposition
        if lowercased.contains("before") || lowercased.contains("begin") || lowercased.contains("start") {
            disposition = .began
        } else if lowercased.contains("cancel") {
            disposition = .cancelled
        } else if lowercased.contains("fail") || lowercased.contains("error") {
            disposition = .failed
        } else if lowercased.contains("after") || lowercased.contains("complete") || lowercased.contains("finish") {
            disposition = .completed
        } else {
            disposition = .observed
        }

        return VocelloQwen3DiagnosticEvent(
            phase: phase,
            disposition: disposition,
            failureCode: disposition == .failed ? .runtime : nil
        )
    }
}

// MARK: - MLX error capture

/// Typed failure for an error MLX raised inside an owned-runtime entry point.
///
/// MLX reports C++ errors through one process-wide callback that carries only a
/// message, and mlx-swift answers an error raised outside a scoped handler with
/// `fatalError`. The facade scopes a handler around model load, prewarm,
/// priming, clone conditioning, audio marking and generation, classifies the
/// message once at this boundary and surfaces only this typed value; the raw
/// message never crosses the facade.
public enum VocelloQwen3RuntimeFailure: Error, Equatable, Sendable {
    /// MLX or Metal could not allocate memory: a buffer larger than the device
    /// allows, an exhausted resource limit, or a failed buffer allocation.
    case allocation
    /// Any other error MLX raised.
    case mlx

    /// The facade terminal failure code for a generation that ended with this
    /// failure.
    public var failureCode: VocelloQwen3FailureCode {
        switch self {
        case .allocation:
            return .memoryPressure
        case .mlx:
            return .runtime
        }
    }

    /// Maps an error thrown by mlx-swift's own `withError` scopes (for example
    /// array loading) to the typed failure. Returns `nil` for any other error.
    public init?(mlxError error: any Error) {
        guard let mlxError = error as? MLXError else { return nil }
        switch mlxError {
        case .caught(let message):
            self = Self.classifying(mlxMessage: message)
        }
    }

    /// Classifies an MLX error message. The message is the only information MLX
    /// provides, so this is the single place it is interpreted; everything
    /// downstream decides on the typed value.
    public static func classifying(mlxMessage message: String) -> VocelloQwen3RuntimeFailure {
        let lowercased = message.lowercased()
        let allocationMarkers = [
            "malloc",
            "allocate",
            "allocation",
            "out of memory",
            "outofmemory",
            "insufficient memory",
            "resource limit",
        ]
        return allocationMarkers.contains { lowercased.contains($0) } ? .allocation : .mlx
    }
}

/// Collects the first MLX error raised while one owned-runtime operation runs.
///
/// The handler is task-local (mlx-swift's `withErrorHandler`), so it covers MLX
/// work on the calling task and on every child or unstructured task it starts,
/// such as the Qwen3 producer tasks. MLX work on a detached task or a thread
/// outside the task tree still reaches mlx-swift's process-wide fallback. The
/// operation keeps running after an error (MLX returns without evaluating), so
/// callers check the scope at their next boundary and stop.
final class VocelloQwen3MLXErrorScope: Sendable {
    private let firstFailure = OSAllocatedUnfairLock<VocelloQwen3RuntimeFailure?>(
        initialState: nil
    )

    init() {}

    /// The first failure recorded in this scope, if any.
    var failure: VocelloQwen3RuntimeFailure? {
        firstFailure.withLock { $0 }
    }

    func record(mlxMessage message: String) {
        let failure = VocelloQwen3RuntimeFailure.classifying(mlxMessage: message)
        firstFailure.withLock { current in
            if current == nil {
                current = failure
            }
        }
    }

    /// Throws the first recorded failure.
    func check() throws {
        if let failure {
            throw failure
        }
    }

    /// The error a failed operation reports. Cancellation always wins so a
    /// cancelled operation stays a cancellation; otherwise a recorded MLX
    /// failure replaces whatever the operation threw after MLX stopped
    /// evaluating, and an `MLXError` thrown by mlx-swift is mapped to its typed
    /// failure.
    func resolvedError(for error: any Error) -> any Error {
        if error is CancellationError {
            return error
        }
        if let failure {
            return failure
        }
        return VocelloQwen3RuntimeFailure(mlxError: error) ?? error
    }

    /// Runs a synchronous operation with this scope as the MLX error handler
    /// and throws the recorded failure when the operation returns.
    func capture<R>(_ body: () throws -> R) throws -> R {
        do {
            let result = try withErrorHandler({ [self] message in
                record(mlxMessage: message)
            }) {
                try body()
            }
            try check()
            return result
        } catch {
            throw resolvedError(for: error)
        }
    }

    /// Runs an asynchronous operation with this scope as the MLX error handler
    /// and throws the recorded failure when the operation returns.
    func captureAsync<R: Sendable>(
        _ body: @Sendable () async throws -> R
    ) async throws -> R {
        do {
            let result = try await withErrorHandler({ [self] message in
                record(mlxMessage: message)
            }) {
                try await body()
            }
            try check()
            return result
        } catch {
            throw resolvedError(for: error)
        }
    }

    /// Runs a non-throwing operation with this scope as the MLX error handler.
    /// The operation owns the reaction: it checks `failure` at its boundaries.
    func scope(_ body: @Sendable () async -> Void) async {
        await withErrorHandler({ [self] message in
            record(mlxMessage: message)
        }) {
            await body()
        }
    }
}
