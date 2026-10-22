import Foundation
import Synchronization

/// `vocello mcp` (RF-29): serves Vocello to AI agents over the Model Context
/// Protocol on stdio, prints an MCP client's setup (`--print-config`), or
/// answers a scripted session in process (`--self-test`).
public enum MCPCommand {
    /// What `--print-config` reports.
    struct Setup: Encodable, Sendable {
        let client: String
        let command: [String]
        let config: String
    }

    struct SelfTest: Encodable, Sendable {
        struct Check: Encodable, Sendable {
            let name: String
            let ok: Bool
            let detail: String?
        }

        let ok: Bool
        let checks: [Check]
    }

    static let clients = ["claude-code", "claude-desktop"]

    @MainActor
    public static func run(_ args: Args, dispatch: @escaping MCPServer.Dispatch) async throws {
        let configuration = try configuration(args)
        if let client = args.string("print-config") {
            try printConfig(client: client, args)
            return
        }
        if args.flag("self-test") {
            try await selfTest(configuration, dispatch: dispatch)
            return
        }
        guard !CLIPresenter.isMachine else {
            throw CLIError(
                .usageError, "the server speaks JSON-RPC on stdout, so it takes no output format",
                hint: "omit --json, --ndjson and --output-format"
            )
        }
        try await serve(configuration, dispatch: dispatch, verbose: args.flag("verbose"))
    }

    static func configuration(_ args: Args) throws -> MCPServer.Configuration {
        var maxQueue = 4
        if let raw = args.string("max-queue") {
            guard let value = Int(raw), (0 ... 64).contains(value) else {
                throw CLIError(.usageError, "--max-queue takes 0 to 64 (got \(raw))")
            }
            maxQueue = value
        }
        return MCPServer.Configuration(
            dataDirectory: CLIPaths.dataDirectory(override: args.string("data-dir")),
            manifestOverride: args.string("manifest").map { URL(fileURLWithPath: ($0 as NSString).expandingTildeInPath) },
            allowedFolders: MCPPathPolicy.folders(args.string("allow-dir")),
            maxQueue: maxQueue,
            allowModelInstall: args.flag("allow-model-install"),
            concurrency: CLIEngineConcurrency(args)
        )
    }

    /// Serves until the client closes stdin (running calls are answered first),
    /// stops reading stdout, or a signal arrives (running calls are cancelled).
    @MainActor
    static func serve(_ configuration: MCPServer.Configuration, dispatch: @escaping MCPServer.Dispatch, verbose: Bool)
        async throws {
        CLIOutput.configureForServer(verbose: verbose)
        let stdio = try MCPStdio.reserve()
        let server = try MCPServer(configuration: configuration, dispatch: dispatch, send: { stdio.send($0) })
        let (lines, input) = AsyncStream.makeStream(of: String.self)
        let loop = Task { @MainActor in
            for await line in lines {
                server.receive(line)
            }
        }
        // Registered before any message can be written.
        stdio.onBroken {
            loop.cancel()
            Task { @MainActor in server.stop() }
        }
        MCPStdio.readLines(into: input)
        noteVerbose("serving MCP on stdio (data: \(configuration.dataDirectory.path))")
        await withTaskCancellationHandler {
            await loop.value
            // A line the loop took after a stop arrived started a call: it stops too.
            if Task.isCancelled || stdio.isBroken { server.stop() }
            await server.drain()
        } onCancel: {
            loop.cancel()
            Task { @MainActor in server.stop() }
        }
        stdio.finish(waitingAtMost: .seconds(5))
        if Task.isCancelled { throw CancellationError() }
    }

    // MARK: Setup

    @MainActor
    static func printConfig(client: String, _ args: Args) throws {
        guard clients.contains(client) else {
            throw CLIError(.usageError, "unknown client '\(client)'", hint: "use \(clients.joined(separator: " | "))")
        }
        // A development build finds the contract from the repository it runs in; the
        // client starts it elsewhere, so the setup names it.
        let manifest = CLIRuntime.locateShippedManifestURL() == nil ? try? CLIRuntime.locateManifestURL() : nil
        let command = [executablePath()] + serverArguments(args, unshippedManifest: manifest)
        let config: String
        if client == "claude-code" {
            config = (["claude", "mcp", "add", "--scope", "user", "vocello", "--"] + command).map(shellQuoted)
                .joined(separator: " ")
        } else {
            let document: CLIJSONValue = .object([
                "mcpServers": .object([
                    "vocello": .object([
                        "command": .string(command[0]),
                        "args": .array(command.dropFirst().map { .string($0) }),
                    ]),
                ]),
            ])
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
            config = String(decoding: try encoder.encode(document), as: UTF8.self)
        }
        if CLIPresenter.isMachine {
            CLIPresenter.succeed(Setup(client: client, command: command, config: config))
        } else {
            print(config)
        }
    }

    /// The server's own options, with absolute paths (a client starts it from
    /// anywhere), naming `unshippedManifest` when no `--manifest` was given.
    static func serverArguments(_ args: Args, unshippedManifest: URL? = nil) -> [String] {
        func absolute(_ path: String) -> String {
            URL(fileURLWithPath: (path as NSString).expandingTildeInPath).standardizedFileURL.path
        }
        var arguments = ["mcp"]
        if let folders = args.string("allow-dir") {
            arguments.append("--allow-dir=\(MCPPathPolicy.folders(folders).map { absolute($0.path) }.joined(separator: ":"))")
        }
        if let queue = args.string("max-queue") { arguments.append("--max-queue=\(queue)") }
        for name in ["data-dir", "manifest"] {
            if let path = args.string(name) { arguments.append("--\(name)=\(absolute(path))") }
        }
        if args.string("manifest") == nil, let unshippedManifest {
            arguments.append("--manifest=\(unshippedManifest.standardizedFileURL.path)")
        }
        for flag in ["allow-model-install", "allow-concurrent-engine", "wait-for-engine"] where args.flag(flag) {
            arguments.append("--\(flag)")
        }
        return arguments
    }

    /// This executable as the shell found it: a symlink such as
    /// /usr/local/bin/vocello is kept, so an upgrade keeps the setup working.
    static func executablePath() -> String {
        let invoked = CommandLine.arguments.first ?? "vocello"
        if invoked.contains("/") { return URL(fileURLWithPath: invoked).standardizedFileURL.path }
        let path = ProcessInfo.processInfo.environment["PATH"] ?? ""
        for folder in path.split(separator: ":") {
            let candidate = URL(fileURLWithPath: String(folder)).appendingPathComponent(invoked).path
            if FileManager.default.isExecutableFile(atPath: candidate) { return candidate }
        }
        return Bundle.main.executablePath ?? invoked
    }

    static func shellQuoted(_ word: String) -> String {
        let plain = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_./=:@%+,")
        guard !word.isEmpty, word.unicodeScalars.allSatisfy(plain.contains) else {
            return "'" + word.replacingOccurrences(of: "'", with: "'\\''") + "'"
        }
        return word
    }

    // MARK: Self-test

    /// A scripted session against in-process servers: both protocol eras, a
    /// read through a real command, and a path refusal. No engine starts.
    @MainActor
    static func selfTest(_ configuration: MCPServer.Configuration, dispatch: @escaping MCPServer.Dispatch) async throws {
        let modern: CLIJSONValue = .object([MCPProtocol.protocolVersionKey: .string(MCPProtocol.modernVersions[0])])
        var checks: [SelfTest.Check] = []
        func check(_ name: String, _ ok: Bool, _ detail: String? = nil) {
            checks.append(SelfTest.Check(name: name, ok: ok, detail: ok ? nil : detail))
        }

        let replies = Mutex<[CLIJSONValue]>([])
        let server = try MCPServer(configuration: configuration, dispatch: dispatch) { message in
            replies.withLock { $0.append(message) }
        }
        func request(_ id: Int, _ method: String, _ params: [String: CLIJSONValue]) async -> CLIJSONValue? {
            let message: CLIJSONValue = .object([
                "jsonrpc": "2.0", "id": .integer(id), "method": .string(method), "params": .object(params),
            ])
            server.receive(String(decoding: MCPOutgoing.line(message).dropLast(), as: UTF8.self))
            await server.drain()
            return replies.withLock { $0 }.first { $0.field("id") == .integer(id) }
        }
        func call(_ id: Int, _ tool: String, _ arguments: [String: CLIJSONValue]) async -> CLIJSONValue? {
            await request(id, "tools/call", ["name": .string(tool), "arguments": .object(arguments), "_meta": modern])?
                .field("result")
        }

        let discover = await request(1, "server/discover", ["_meta": modern])
        check(
            "server/discover", discover?.field("result")?.field("supportedVersions") == .array([.string(MCPProtocol.modernVersions[0])]),
            "no supported versions"
        )
        let listed = await request(2, "tools/list", ["_meta": modern])
        if case .array(let tools)? = listed?.field("result")?.field("tools") {
            check("tools/list", tools.count == server.tools.count, "\(tools.count) tools listed")
        } else {
            check("tools/list", false, "no tools")
        }
        let capabilities = await call(3, "get_capabilities", [:])
        check("get_capabilities", capabilities?.field("isError") == .bool(false), capabilities?.firstText)
        let speakers = await call(4, "list_speakers", [:])
        check("list_speakers", speakers?.field("isError") == .bool(false), speakers?.firstText)
        // A relative path is refused whatever folders are allowed, so this never reaches the engine.
        let outside = await call(5, "generate_speech", ["text": "Hello.", "out": "vocello-mcp-self-test.wav"])
        check(
            "path policy",
            outside?.field("structuredContent")?.field("error")?.field("code") == .string(VocelloErrorCode.pathNotAllowed.rawValue),
            outside?.firstText ?? "no refusal"
        )
        let unsupported = await request(6, "tools/list", [
            "_meta": .object([MCPProtocol.protocolVersionKey: "1999-01-01"]),
        ])
        check(
            "unsupported version",
            unsupported?.field("error")?.field("code") == .integer(MCPProtocol.ErrorCode.unsupportedProtocolVersion.rawValue),
            "no -32022 error"
        )

        let legacyReplies = Mutex<[CLIJSONValue]>([])
        let legacy = try MCPServer(configuration: configuration, dispatch: dispatch) { message in
            legacyReplies.withLock { $0.append(message) }
        }
        legacy.receive(#"{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"self-test","version":"1"}}}"#)
        legacy.receive(#"{"jsonrpc":"2.0","method":"notifications/initialized"}"#)
        legacy.receive(#"{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"list_languages"}}"#)
        await legacy.drain()
        let legacyMessages = legacyReplies.withLock { $0 }
        let initialized = legacyMessages.first { $0.field("id") == .integer(1) }
        check(
            "initialize", initialized?.field("result")?.field("protocolVersion") == .string("2025-06-18"),
            "the handshake chose no 2025-06-18"
        )
        let languages = legacyMessages.first { $0.field("id") == .integer(2) }?.field("result")
        check("initialize-era tools/call", languages?.field("isError") == .bool(false), languages?.firstText)

        let report = SelfTest(ok: checks.allSatisfy(\.ok), checks: checks)
        if CLIPresenter.isMachine {
            if report.ok { CLIPresenter.succeed(report) } else { CLIPresenter.recordPartialResult(report) }
        } else {
            for check in checks {
                print("\(check.ok ? "ok  " : "FAIL") \(check.name)\(check.detail.map { ": \($0)" } ?? "")")
            }
        }
        if !report.ok {
            let failed = checks.filter { !$0.ok }.map(\.name)
            throw CLIError(.internalError, "the MCP self-test failed: \(failed.joined(separator: ", "))")
        }
    }
}

extension CLIJSONValue {
    /// An object's field; nil for anything else.
    func field(_ key: String) -> CLIJSONValue? {
        if case .object(let fields) = self { return fields[key] }
        return nil
    }

    /// A tool result's first text content.
    var firstText: String? {
        guard case .array(let content)? = field("content"), case .string(let text)? = content.first?.field("text") else {
            return nil
        }
        return text
    }
}
