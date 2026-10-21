import Foundation
import QwenVoiceCore

/// A user-facing CLI error with its contract code. The message is printed
/// verbatim in text mode and carried as `error.message` in machine modes; it may
/// name a file the caller passed, never a staged one. `hint` says what to do next.
public struct CLIError: Error, CustomStringConvertible, LocalizedError, Equatable {
    public let code: VocelloErrorCode
    public let description: String
    public let hint: String?
    public let detail: [String: CLIJSONValue]?

    public init(
        _ code: VocelloErrorCode,
        _ message: String,
        hint: String? = nil,
        detail: [String: CLIJSONValue]? = nil
    ) {
        self.code = code
        self.description = message
        self.hint = hint
        self.detail = detail
    }

    public var errorDescription: String? { description }
}

/// A take the engine stopped on its own while no signal reached the command
/// (P15-02). In a CLI process memory pressure is the only such source: the
/// engine's kernel responder or, for a hosted take, the store's critical
/// footprint guard cancels the active take with reason `memory_pressure`. It is
/// reported apart from an operator interrupt (exit 130): `vocello` exits
/// `exitStatus` and a batch row ends `failed` with `errorCode`, never `cancelled`.
public struct CLIEngineCancellation: Error, LocalizedError, Equatable {
    /// sysexits.h `EX_TEMPFAIL`: a temporary failure that a later retry may clear.
    public static let exitStatus: Int32 = 75

    let reason: GenerationCancellationReason

    /// A batch row's `errorCode`: the typed reason (`memory_pressure`).
    public var errorCode: String { reason.rawValue }

    /// The contract code: memory pressure, or the engine shutting down or
    /// superseding the take (both clear once it is idle again).
    public var contractCode: VocelloErrorCode {
        reason == .memoryPressure ? .memoryPressure : .engineBusy
    }

    public var errorDescription: String? {
        switch reason {
        case .memoryPressure:
            return "the engine stopped this take under critical memory pressure, so no audio was written. "
                + "Free memory (quit other apps) or use --variant speed, then retry."
        case .user, .superseded, .shutdown:
            return "the engine stopped this take on its own (\(reason.rawValue)), so no audio was written."
        }
    }

    /// The error a command reports for `error`: a `CancellationError` that its own
    /// task never received (no SIGINT or SIGTERM cancelled it) is the engine's.
    /// `observedReason` is the typed reason a streaming run read off the take's
    /// `.cancelled` event; without one (or with the engine's `user` default) the
    /// reason is memory pressure, the engine's only cancellation of its own here.
    /// Every other error, and a signalled run's cancellation, passes through.
    static func classify(
        _ error: any Error,
        commandCancelled: Bool,
        observedReason: GenerationCancellationReason? = nil
    ) -> any Error {
        if let stopped = error as? CLIEngineCancellation {
            return stopped.refined(by: observedReason)
        }
        guard error is CancellationError, !commandCancelled else { return error }
        return CLIEngineCancellation(reason: .memoryPressure).refined(by: observedReason)
    }

    private func refined(by observedReason: GenerationCancellationReason?) -> CLIEngineCancellation {
        guard let observedReason, observedReason != .user else { return self }
        return CLIEngineCancellation(reason: observedReason)
    }
}
