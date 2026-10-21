import Foundation
import Synchronization

/// The invocation's output session. In text mode commands print for people
/// and this only reports a failure on stderr. In json mode stdout carries
/// exactly one envelope; in ndjson mode it carries events ending in one
/// `result` record. Commands report results and events here, never by
/// printing JSON themselves.
public enum CLIPresenter {
    private struct State: Sendable {
        var format: CLIOutputFormat = .text
        var command = "vocello"
        var requestID = ""
        var started = ContinuousClock.now
        var warnings: [CLIWarning] = []
        var reported = false
        var unencodable = false
        var replayed = false
        var partialResult: (any Encodable & Sendable)?
        var events: CLIEventStream?
        var stdoutSink: @Sendable (Data) -> Bool = CLIStandardOutput.write
    }

    private static let state = Mutex(State())

    /// Begins the session once the command is known. `onBrokenOutput` runs once
    /// when stdout's reader goes away, so the command can stop.
    public static func begin(
        format: CLIOutputFormat,
        command: String,
        requestID: String = UUID().uuidString.lowercased(),
        stdoutSink: @escaping @Sendable (Data) -> Bool = CLIStandardOutput.write,
        onBrokenOutput: @escaping @Sendable () -> Void = {}
    ) {
        let started = ContinuousClock.now
        let events = format == .ndjson
            ? CLIEventStream(requestID: requestID, started: started, sink: stdoutSink, onBrokenOutput: onBrokenOutput)
            : nil
        let superseded = state.withLock { $0.reported ? nil : $0.events }
        superseded?.close()
        state.withLock {
            $0 = State(
                format: format, command: command, requestID: requestID, started: started,
                events: events, stdoutSink: stdoutSink
            )
        }
        events?.emit(.started, data: .object(["command": .string(command)]))
    }

    public static var format: CLIOutputFormat { state.withLock { $0.format } }
    public static var isMachine: Bool { format.isMachine }
    public static var requestID: String { state.withLock { $0.requestID } }

    /// An NDJSON event; nothing in the other formats.
    public static func event(_ type: CLIEventType, generationID: UUID? = nil, data: [String: CLIJSONValue] = [:]) {
        let events = state.withLock { $0.events }
        events?.emit(type, generationID: generationID?.uuidString.lowercased(), data: .object(data))
    }

    /// A warning: in the envelope's `warnings` and as a `warning` event, or a
    /// note on stderr in text mode.
    public static func warn(_ code: String, _ message: String, detail: [String: CLIJSONValue]? = nil) {
        let warning = CLIWarning(code: code, message: message, detail: detail)
        let (format, events) = state.withLock { state -> (CLIOutputFormat, CLIEventStream?) in
            state.warnings.append(warning)
            return (state.format, state.events)
        }
        if format == .text {
            note("warning: \(message)")
        }
        var data: [String: CLIJSONValue] = ["code": .string(code), "message": .string(message)]
        if let detail { data["detail"] = .object(detail) }
        events?.emit(.warning, data: .object(data))
    }

    /// The command's result. Text mode prints nothing here: the command prints
    /// its own human output.
    public static func succeed(_ result: some Encodable & Sendable) {
        report(ok: true, result: result, error: nil)
    }

    /// The result about to be reported is a stored one replayed for a repeated
    /// client request id (`meta.replayed`).
    public static func markReplayed() {
        state.withLock { $0.replayed = true }
    }

    /// The rows a failing command keeps (a partial batch), reported with its error.
    public static func recordPartialResult(_ result: some Encodable & Sendable) {
        state.withLock { $0.partialResult = result }
    }

    /// Reports `error`: an envelope in the machine formats, `error: …` and its
    /// hint on stderr in text mode.
    public static func fail(_ error: CLIErrorObject) {
        let partial = state.withLock { $0.partialResult }
        report(ok: false, result: partial, error: error)
    }

    /// A machine-mode command that reported nothing gets an empty result.
    public static func finishSuccessIfUnreported() {
        guard isMachine, !state.withLock({ $0.reported }) else { return }
        succeed(CLIEmptyResult())
    }

    public static var outputBroken: Bool { state.withLock { $0.events?.outputBroken ?? false } }

    /// The result could not be encoded, so a fallback `internal_error` envelope
    /// went out instead and the process must exit as failed.
    public static var resultWasUnencodable: Bool { state.withLock { $0.unencodable } }

    private static func report(ok: Bool, result: (any Encodable & Sendable)?, error: CLIErrorObject?) {
        let snapshot = state.withLock { state -> State? in
            guard !state.reported else { return nil }
            state.reported = true
            return state
        }
        guard let snapshot else { return }
        switch snapshot.format {
        case .text:
            if let error {
                CLIStandardError.write("error: \(error.message)\n")
                if let hint = error.hint {
                    CLIStandardError.write("hint: \(hint)\n")
                }
            }
        case .json, .ndjson:
            let envelope = CLIEnvelope(
                ok: ok, command: snapshot.command, requestID: snapshot.requestID, result: result, error: error,
                warnings: snapshot.warnings,
                meta: CLIEnvelopeMeta(
                    vocelloVersion: vocelloCLIVersion, build: vocelloCLIBuild,
                    contractRevision: CLIContract.revision,
                    durationMs: Int((snapshot.started.duration(to: .now) / .milliseconds(1)).rounded()),
                    replayed: snapshot.replayed
                )
            )
            let encodes = (try? CLIJSONEncoding.encoder().encode(envelope)) != nil
            if !encodes { state.withLock { $0.unencodable = true } }
            if let events = snapshot.events {
                events.finish(result: envelope)
            } else {
                let line = (try? CLIJSONEncoding.line(envelope))
                    ?? CLIJSONEncoding.unencodableEnvelope(command: snapshot.command, requestID: snapshot.requestID)
                _ = snapshot.stdoutSink(line)
            }
        }
    }
}

/// The build number embedded beside the marketing version.
public let vocelloCLIBuild: String =
    (Bundle.main.object(forInfoDictionaryKey: kCFBundleVersionKey as String) as? String)
        .flatMap { $0.isEmpty ? nil : $0 } ?? "unknown"
