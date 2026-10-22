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

    /// RF-29: a command run for an MCP tool call reports to its call's capture
    /// instead of the process's session: as in json mode, and never on stdout.
    @TaskLocal public static var capture: CLIPresenterCapture?

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

    public static var format: CLIOutputFormat { capture != nil ? .json : state.withLock { $0.format } }
    public static var isMachine: Bool { format.isMachine }
    public static var requestID: String { capture?.requestID ?? state.withLock { $0.requestID } }

    /// An NDJSON event; nothing in the other formats.
    public static func event(_ type: CLIEventType, generationID: UUID? = nil, data: [String: CLIJSONValue] = [:]) {
        if let capture {
            capture.event(type, generationID: generationID?.uuidString.lowercased(), data: data)
            return
        }
        let events = state.withLock { $0.events }
        events?.emit(type, generationID: generationID?.uuidString.lowercased(), data: .object(data))
    }

    /// A warning: in the envelope's `warnings` and as a `warning` event, or a
    /// note on stderr in text mode.
    public static func warn(_ code: String, _ message: String, detail: [String: CLIJSONValue]? = nil) {
        let warning = CLIWarning(code: code, message: message, detail: detail)
        if let capture {
            capture.warn(warning)
            return
        }
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
        if let capture {
            capture.markReplayed()
            return
        }
        state.withLock { $0.replayed = true }
    }

    /// The rows a failing command keeps (a partial batch), reported with its error.
    public static func recordPartialResult(_ result: some Encodable & Sendable) {
        if let capture {
            capture.recordPartialResult(result)
            return
        }
        state.withLock { $0.partialResult = result }
    }

    /// Reports `error`: an envelope in the machine formats, `error: …` and its
    /// hint on stderr in text mode.
    public static func fail(_ error: CLIErrorObject) {
        if let capture {
            capture.report(ok: false, result: nil, error: error)
            return
        }
        let partial = state.withLock { $0.partialResult }
        report(ok: false, result: partial, error: error)
    }

    /// A machine-mode command that reported nothing gets an empty result.
    public static func finishSuccessIfUnreported() {
        if let capture {
            capture.finishSuccessIfUnreported()
            return
        }
        guard isMachine, !state.withLock({ $0.reported }) else { return }
        succeed(CLIEmptyResult())
    }

    public static var outputBroken: Bool {
        capture != nil ? false : state.withLock { $0.events?.outputBroken ?? false }
    }

    /// The result could not be encoded, so a fallback `internal_error` envelope
    /// went out instead and the process must exit as failed.
    public static var resultWasUnencodable: Bool { state.withLock { $0.unencodable } }

    private static func report(ok: Bool, result: (any Encodable & Sendable)?, error: CLIErrorObject?) {
        if let capture {
            capture.report(ok: ok, result: result, error: error)
            return
        }
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

/// One MCP tool call's report (RF-29): the command it ran reports here as it
/// would in json mode, and its events go to `onEvent` (the call's progress).
/// The first report wins, as in the process's session.
public final class CLIPresenterCapture: Sendable {
    public struct Report: Sendable {
        public let ok: Bool
        public let result: CLIJSONValue?
        public let error: CLIErrorObject?
        public let warnings: [CLIWarning]
        public let replayed: Bool
    }

    private struct State: Sendable {
        var warnings: [CLIWarning] = []
        var replayed = false
        var partialResult: CLIJSONValue?
        var report: Report?
    }

    public let requestID: String
    private let onEvent: @Sendable (CLIEventType, String?, [String: CLIJSONValue]) -> Void
    private let state = Mutex(State())

    public init(
        requestID: String = UUID().uuidString.lowercased(),
        onEvent: @escaping @Sendable (CLIEventType, String?, [String: CLIJSONValue]) -> Void = { _, _, _ in }
    ) {
        self.requestID = requestID
        self.onEvent = onEvent
    }

    /// What the command reported; nil while it has reported nothing.
    public var report: Report? { state.withLock { $0.report } }

    func event(_ type: CLIEventType, generationID: String?, data: [String: CLIJSONValue]) {
        onEvent(type, generationID, data)
    }

    func warn(_ warning: CLIWarning) {
        state.withLock { $0.warnings.append(warning) }
        var data: [String: CLIJSONValue] = ["code": .string(warning.code), "message": .string(warning.message)]
        if let detail = warning.detail { data["detail"] = .object(detail) }
        onEvent(.warning, nil, data)
    }

    func markReplayed() {
        state.withLock { $0.replayed = true }
    }

    func recordPartialResult(_ result: some Encodable & Sendable) {
        let value = try? CLIJSONValue(encoding: result)
        state.withLock { $0.partialResult = value }
    }

    func finishSuccessIfUnreported() {
        report(ok: true, result: CLIEmptyResult(), error: nil)
    }

    func report(ok: Bool, result: (any Encodable & Sendable)?, error: CLIErrorObject?) {
        // A result that cannot be encoded reports as the session would: internal_error.
        var ok = ok
        var error = error
        var value: CLIJSONValue?
        if let result {
            do {
                value = try CLIJSONValue(encoding: result)
            } catch {
                ok = false
                value = nil
            }
            if value == nil, error == nil {
                error = CLIErrorObject(code: .internalError, message: "the command's result could not be encoded as JSON")
            }
        }
        state.withLock { state in
            guard state.report == nil else { return }
            state.report = Report(
                ok: ok, result: ok ? value : (value ?? state.partialResult), error: error,
                warnings: state.warnings, replayed: state.replayed
            )
        }
    }
}
