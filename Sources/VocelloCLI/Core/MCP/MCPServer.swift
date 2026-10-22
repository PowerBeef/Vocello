import Foundation
import Synchronization

/// `vocello mcp`'s dispatcher (RF-29). Messages arrive in order through
/// `receive`; every request but tools/call is answered at once. Each tools/call
/// runs in its own task: reads beside each other, engine requests one at a time
/// through `MCPEngineGate`, each command under its own capture (nothing it
/// reports reaches stdout) and on the server's one warm engine. A call the
/// client cancels stops through its command's cancellation (a take through the
/// engine's typed barrier) and is not answered.
@MainActor
public final class MCPServer {
    public struct Configuration: Sendable {
        public var dataDirectory: URL
        public var manifestOverride: URL?
        public var allowedFolders: [URL]
        public var maxQueue: Int
        public var allowModelInstall: Bool
        public var concurrency: CLIEngineConcurrency

        public init(
            dataDirectory: URL, manifestOverride: URL? = nil, allowedFolders: [URL] = [], maxQueue: Int = 4,
            allowModelInstall: Bool = false, concurrency: CLIEngineConcurrency = CLIEngineConcurrency()
        ) {
            self.dataDirectory = dataDirectory
            self.manifestOverride = manifestOverride
            self.allowedFolders = allowedFolders
            self.maxQueue = maxQueue
            self.allowModelInstall = allowModelInstall
            self.concurrency = concurrency
        }
    }

    /// Runs one parsed command: the executable's dispatcher.
    public typealias Dispatch = @MainActor (CLIInvocation) async throws -> Void
    /// Writes one message; called from any thread.
    public typealias Send = @Sendable (CLIJSONValue) -> Void

    let configuration: Configuration
    let tools: [MCPTool]
    let policy: MCPPathPolicy
    let gate: MCPEngineGate
    let warm: CLIWarmEngine
    private let dispatch: Dispatch
    private let send: Send
    /// The revision an `initialize` chose; nil until one arrives.
    private(set) var negotiatedVersion: String?
    private var calls: [String: Task<Void, Never>] = [:]
    private var cancelledCalls: Set<String> = []
    /// Set once the server is stopping: it starts no call after that.
    private var stopping = false

    public init(configuration: Configuration, dispatch: @escaping Dispatch, send: @escaping Send) throws {
        self.configuration = configuration
        tools = MCPTools.catalog(allowModelInstall: configuration.allowModelInstall)
        policy = try MCPPathPolicy(dataDirectory: configuration.dataDirectory, allowedFolders: configuration.allowedFolders)
        gate = MCPEngineGate(maxQueue: configuration.maxQueue)
        warm = CLIWarmEngine(
            dataDirectory: configuration.dataDirectory, manifestOverride: configuration.manifestOverride,
            concurrency: configuration.concurrency
        )
        self.dispatch = dispatch
        self.send = send
    }

    public var runningCalls: Int { calls.count }

    /// Handles one line from the client.
    public func receive(_ line: String) {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }
        switch MCPIncoming.parse(trimmed) {
        case .failure(let error):
            send(MCPOutgoing.error(error))
        case .success(let message):
            switch message.kind {
            case .response: return
            case .notification: notify(message)
            case .request(let id): request(id: id, message)
            }
        }
    }

    /// Stops: cancels every running call and waits for each to end; none is answered.
    public func shutdown() async {
        stop()
        await drain()
    }

    /// Starts no further call and cancels every running one; none is answered.
    public func stop() {
        stopping = true
        for (key, task) in calls {
            cancelledCalls.insert(key)
            task.cancel()
        }
    }

    /// Waits until no call is running.
    public func drain() async {
        while let task = calls.values.first {
            await task.value
        }
    }

    // MARK: Messages

    private func notify(_ message: MCPIncoming) {
        // notifications/initialized and the rest ask for nothing.
        guard message.method == "notifications/cancelled",
              let id = message.params["requestId"], let key = Self.key(id), let task = calls[key] else { return }
        cancelledCalls.insert(key)
        task.cancel()
    }

    private func request(id: CLIJSONValue, _ message: MCPIncoming) {
        if message.method == "initialize" {
            var requested: String?
            if case .string(let version)? = message.params["protocolVersion"] { requested = version }
            let version = MCPProtocol.legacyVersion(answering: requested)
            negotiatedVersion = version
            send(MCPOutgoing.result(id: id, .object([
                "protocolVersion": .string(version),
                "capabilities": capabilities,
                "serverInfo": serverInfo,
                "instructions": .string(instructions),
            ])))
            return
        }
        let modern: Bool
        if let version = message.protocolVersion {
            guard MCPProtocol.modernVersions.contains(version) else {
                send(MCPOutgoing.error(MCPRPCError(
                    code: .unsupportedProtocolVersion, message: "protocol version \(version) is not supported",
                    data: .object([
                        "supported": .array(MCPProtocol.modernVersions.map { .string($0) }),
                        "requested": .string(version),
                    ]),
                    id: id
                )))
                return
            }
            modern = true
        } else if negotiatedVersion != nil {
            modern = false
        } else if message.method == "server/discover" || message.method == "ping" {
            modern = true
        } else {
            send(MCPOutgoing.error(MCPRPCError(
                code: .invalidRequest,
                message: "send initialize first, or name the protocol version in _meta (\(MCPProtocol.protocolVersionKey))",
                data: .object(["supported": .array(MCPProtocol.allVersions.map { .string($0) })]),
                id: id
            )))
            return
        }
        switch message.method {
        case "server/discover":
            reply(id, modern: true, [
                "supportedVersions": .array(MCPProtocol.modernVersions.map { .string($0) }),
                "capabilities": capabilities,
                "instructions": .string(instructions),
                "ttlMs": .integer(Self.cacheMilliseconds),
                "cacheScope": "private",
            ])
        case "ping":
            reply(id, modern: modern, [:])
        case "tools/list":
            var result: [String: CLIJSONValue] = ["tools": .array(tools.map(\.definition))]
            if modern {
                result["ttlMs"] = .integer(Self.cacheMilliseconds)
                result["cacheScope"] = "private"
            }
            reply(id, modern: modern, result)
        case "tools/call":
            call(id: id, message, modern: modern)
        default:
            send(MCPOutgoing.error(MCPRPCError(code: .methodNotFound, message: "no method \(message.method)", id: id)))
        }
    }

    private func reply(_ id: CLIJSONValue, modern: Bool, _ result: [String: CLIJSONValue]) {
        var result = result
        if modern {
            result["resultType"] = "complete"
            result["_meta"] = .object([MCPProtocol.serverInfoKey: serverInfo])
        }
        send(MCPOutgoing.result(id: id, .object(result)))
    }

    // MARK: Tool calls

    private func call(id: CLIJSONValue, _ message: MCPIncoming, modern: Bool) {
        // A stopping server answers nothing more.
        guard !stopping else { return }
        guard case .string(let name)? = message.params["name"], let tool = tools.first(where: { $0.name == name }) else {
            send(MCPOutgoing.error(MCPRPCError(code: .invalidParams, message: "no such tool (see tools/list)", id: id)))
            return
        }
        var arguments: [String: CLIJSONValue] = [:]
        switch message.params["arguments"] {
        case nil, .null?: break
        case .object(let given)?: arguments = given
        default:
            send(MCPOutgoing.error(MCPRPCError(code: .invalidParams, message: "arguments is an object", id: id)))
            return
        }
        guard let key = Self.key(id), calls[key] == nil else {
            send(MCPOutgoing.error(MCPRPCError(code: .invalidRequest, message: "a request with this id is running", id: id)))
            return
        }
        let progress = MCPProgress(token: message.meta["progressToken"], send: send)
        calls[key] = Task {
            let result = await self.execute(tool, arguments, progress: progress)
            // Nothing the command still reports (a downloader's late callback) follows the call.
            progress.close()
            self.calls[key] = nil
            guard self.cancelledCalls.remove(key) == nil else { return }
            self.reply(id, modern: modern, result)
        }
    }

    private func execute(
        _ tool: MCPTool, _ arguments: [String: CLIJSONValue], progress: MCPProgress
    ) async -> [String: CLIJSONValue] {
        if tool.kind == .server {
            return Self.toolResult(CLIPresenterCapture.Report(
                ok: true, result: status(), error: nil, warnings: [], replayed: false
            ))
        }
        let capture = CLIPresenterCapture { type, _, data in progress.event(type, data) }
        do {
            // Arguments and paths are checked before the gate, so a refusal never waits.
            let line = try tool.commandLine(arguments, policy: policy)
            let invocation = try CLIParser.parse(
                line.path + globalOptions + line.options + (line.operands.isEmpty ? [] : ["--"] + line.operands)
            )
            if tool.kind == .engine {
                try await gate.enter()
                defer { gate.leave() }
                try await run(invocation, capture: capture)
            } else {
                try await run(invocation, capture: capture)
            }
        } catch {
            capture.report(ok: false, result: nil, error: CLIFailure.classify(error))
        }
        return Self.toolResult(capture.report ?? CLIPresenterCapture.Report(
            ok: false, result: nil, error: CLIErrorObject(code: .internalError, message: "the command reported nothing"),
            warnings: [], replayed: false
        ))
    }

    private func run(_ invocation: CLIInvocation, capture: CLIPresenterCapture) async throws {
        try await CLIPresenter.$capture.withValue(capture) {
            try await CLIEngineScope.$warm.withValue(warm) {
                try await dispatch(invocation)
            }
        }
        capture.finishSuccessIfUnreported()
    }

    /// A command's report as a tool result: its result as structured content
    /// and as JSON text, warnings as text; a failure is a tool error whose
    /// structured content holds the contract's error object.
    static func toolResult(_ report: CLIPresenterCapture.Report) -> [String: CLIJSONValue] {
        func text(_ string: String) -> CLIJSONValue { .object(["type": "text", "text": .string(string)]) }
        guard report.ok else {
            let error = report.error ?? CLIErrorObject(code: .internalError, message: "the command failed")
            var structured: [String: CLIJSONValue] = ["error": (try? CLIJSONValue(encoding: error)) ?? .null]
            if let partial = report.result { structured["result"] = partial }
            var message = "\(error.code.rawValue): \(error.message)"
            if let hint = error.hint { message += " (\(hint))" }
            return ["content": .array([text(message)]), "structuredContent": .object(structured), "isError": true]
        }
        let structured: CLIJSONValue
        if case .object? = report.result, let result = report.result {
            structured = result
        } else {
            structured = .object(["value": report.result ?? .null])
        }
        var content = [text(String(decoding: MCPOutgoing.line(structured).dropLast(), as: UTF8.self))]
        if report.replayed { content.append(text("replayed: the stored result of this clientRequestID")) }
        for warning in report.warnings { content.append(text("warning \(warning.code): \(warning.message)")) }
        return ["content": .array(content), "structuredContent": structured, "isError": false]
    }

    // MARK: Server facts

    static let cacheMilliseconds = 300_000

    private var globalOptions: [String] {
        ["--data-dir=\(configuration.dataDirectory.path)"]
            + (configuration.manifestOverride.map { ["--manifest=\($0.path)"] } ?? [])
    }

    private var capabilities: CLIJSONValue { .object(["tools": .object(["listChanged": false])]) }

    private var serverInfo: CLIJSONValue {
        .object(["name": "vocello", "title": "Vocello", "version": .string(vocelloCLIVersion)])
    }

    var instructions: String {
        """
        Vocello speaks text on this Mac with local Qwen3-TTS models; nothing leaves the Mac. Start with \
        get_capabilities, list_speakers or list_voices. generate_speech writes a WAV file and returns its \
        audioPath. Engine requests (generate_speech, enroll_voice, delete_voice\
        \(configuration.allowModelInstall ? ", install_model" : "")) run one at a time; engine_busy means retry \
        later. Paths are absolute: clips are read from inside \(policy.readRoots.joined(separator: " or ")), and \
        audio is written inside \(policy.writeRoots.joined(separator: " or ")). Cloning or saving a voice \
        needs confirmConsent true, given only when the user owns the voice or has permission to clone it.
        """
    }

    private func status() -> CLIJSONValue {
        .object([
            "server": .object([
                "name": "vocello", "version": .string(vocelloCLIVersion), "build": .string(vocelloCLIBuild),
                "protocolVersions": .array(MCPProtocol.allVersions.map { .string($0) }),
                "negotiatedVersion": negotiatedVersion.map { .string($0) } ?? .null,
            ]),
            "dataDirectory": .string(configuration.dataDirectory.path),
            "readableFolders": .array(policy.readRoots.map { .string($0) }),
            "writableFolders": .array(policy.writeRoots.map { .string($0) }),
            "engine": .object(["started": .bool(warm.isBooted), "holdsLease": .bool(warm.holdsLease)]),
            "queue": .object([
                "running": .bool(gate.isRunning), "waiting": .integer(gate.waiting), "maxQueue": .integer(gate.maxQueue),
            ]),
            "calls": .integer(calls.count),
            "modelInstall": .bool(configuration.allowModelInstall),
        ])
    }

    /// A request id as a dictionary key: a string and the integer it spells stay apart.
    static func key(_ id: CLIJSONValue) -> String? {
        switch id {
        case .string(let value): return "s:\(value)"
        case .integer(let value): return "n:\(value)"
        case .unsigned(let value): return "n:\(value)"
        default: return nil
        }
    }
}

/// A call's progress (RF-29): when the request carried a progress token, each
/// event its command reports becomes `notifications/progress`, counting up,
/// with chunk events at most twice a second.
final class MCPProgress: Sendable {
    private struct State: Sendable {
        var count = 0
        var lastChunk: ContinuousClock.Instant?
        var closed = false
    }

    private let token: CLIJSONValue?
    private let send: MCPServer.Send
    private let state = Mutex(State())

    init(token: CLIJSONValue?, send: @escaping MCPServer.Send) {
        switch token {
        case .string?, .integer?, .unsigned?: self.token = token
        default: self.token = nil
        }
        self.send = send
    }

    func event(_ type: CLIEventType, _ data: [String: CLIJSONValue]) {
        guard let token else { return }
        let now = ContinuousClock.now
        let count = state.withLock { state -> Int? in
            guard !state.closed else { return nil }
            if type == .chunk {
                if let last = state.lastChunk, last.duration(to: now) < .milliseconds(500) { return nil }
                state.lastChunk = now
            }
            state.count += 1
            return state.count
        }
        guard let count else { return }
        send(MCPOutgoing.notification("notifications/progress", [
            "progressToken": token, "progress": .integer(count), "message": .string(Self.message(type, data)),
        ]))
    }

    /// The call ended: later events send nothing.
    func close() {
        state.withLock { $0.closed = true }
    }

    /// A short message: the event, and the counts it carries.
    static func message(_ type: CLIEventType, _ data: [String: CLIJSONValue]) -> String {
        var parts = [type.rawValue]
        if case .string(let model)? = data["modelID"] { parts.append(model) }
        if case .integer(let finished)? = data["finished"] {
            let total = ["requests", "lines", "segments"].lazy.compactMap { key -> Int? in
                if case .integer(let value)? = data[key] { return value }
                return nil
            }.first
            parts.append(total.map { "\(finished)/\($0)" } ?? "\(finished)")
        }
        if case .integer(let chunks)? = data["chunks"] { parts.append("\(chunks) chunks") }
        if case .string(let done)? = data["downloadedBytes"], case .string(let total)? = data["totalBytes"],
           let done = Double(done), let total = Double(total), total > 0 {
            parts.append("\(Int(done / total * 100))%")
        }
        if case .string(let message)? = data["message"], type == .warning { parts.append(message) }
        return parts.joined(separator: " ")
    }
}
