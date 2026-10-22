import Foundation
import QwenVoiceCore
import Synchronization
import XCTest
@testable import VocelloCLICore
import VocelloDesktopCore

/// RF-29: `vocello mcp` answers both protocol eras, turns tool arguments into
/// the command line's own arguments, confines paths, runs engine requests one
/// at a time, and stops a cancelled call without answering it. The commands
/// are fakes here; a real take and cancellation ran over stdio on the Mac.
@MainActor
final class MCPServerTests: XCTestCase {
    /// What the fake commands saw, and what the server wrote.
    private final class Session: Sendable {
        let sent = Mutex<[CLIJSONValue]>([])
        let invocations = Mutex<[CLIInvocation]>([])

        func reply(_ id: Int) -> CLIJSONValue? {
            sent.withLock { $0 }.first { $0.field("id") == .integer(id) }
        }

        func progress(_ token: String) -> [CLIJSONValue] {
            sent.withLock { $0 }.filter {
                $0.field("method") == "notifications/progress" && $0.field("params")?.field("progressToken") == .string(token)
            }
        }
    }

    private struct Echo: Encodable, Sendable {
        let command: String
        let args: CLIJSONValue
        let machine: Bool
        let warmScope: Bool
    }

    private func makeFolder(_ name: String) throws -> URL {
        let folder = FileManager.default.temporaryDirectory
            .appendingPathComponent("MCPServer-\(name)-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: folder) }
        return folder
    }

    /// A server over `dispatch`; by default every command echoes what it was asked.
    private func makeServer(
        _ session: Session, allowed: [URL] = [], maxQueue: Int = 4, allowModelInstall: Bool = false,
        dispatch: MCPServer.Dispatch? = nil
    ) throws -> MCPServer {
        let data = try makeFolder("data")
        let echo: MCPServer.Dispatch = { invocation in
            CLIPresenter.succeed(Echo(
                command: invocation.commandName, args: invocation.args.canonicalForm(excluding: ["data-dir"]),
                machine: CLIPresenter.isMachine, warmScope: CLIEngineScope.warm != nil
            ))
        }
        let run = dispatch ?? echo
        return try MCPServer(
            configuration: MCPServer.Configuration(
                dataDirectory: data, allowedFolders: allowed, maxQueue: maxQueue, allowModelInstall: allowModelInstall
            ),
            dispatch: { invocation in
                session.invocations.withLock { $0.append(invocation) }
                try await run(invocation)
            },
            send: { message in session.sent.withLock { $0.append(message) } }
        )
    }

    private func send(_ server: MCPServer, _ message: CLIJSONValue) {
        server.receive(String(decoding: MCPOutgoing.line(message).dropLast(), as: UTF8.self))
    }

    private func request(
        _ server: MCPServer, _ id: Int, _ method: String, _ params: [String: CLIJSONValue] = [:],
        modern: Bool = true
    ) {
        var params = params
        if modern {
            var meta: [String: CLIJSONValue] = [:]
            if case .object(let given)? = params["_meta"] { meta = given }
            meta[MCPProtocol.protocolVersionKey] = "2026-07-28"
            params["_meta"] = .object(meta)
        }
        send(server, .object(["jsonrpc": "2.0", "id": .integer(id), "method": .string(method), "params": .object(params)]))
    }

    private func call(
        _ server: MCPServer, _ id: Int, _ tool: String, _ arguments: [String: CLIJSONValue] = [:],
        progressToken: String? = nil
    ) {
        var params: [String: CLIJSONValue] = ["name": .string(tool), "arguments": .object(arguments)]
        if let progressToken { params["_meta"] = .object(["progressToken": .string(progressToken)]) }
        request(server, id, "tools/call", params)
    }

    /// Waits for `condition`, failing after five seconds.
    private func until(_ what: String, _ condition: () -> Bool) async throws {
        let deadline = ContinuousClock.now + .seconds(5)
        while !condition() {
            guard ContinuousClock.now < deadline else {
                XCTFail("timed out waiting for \(what)")
                throw CancellationError()
            }
            try await Task.sleep(for: .milliseconds(2))
        }
    }

    private func errorCode(_ result: CLIJSONValue?) -> String? {
        guard case .string(let code)? = result?.field("structuredContent")?.field("error")?.field("code") else { return nil }
        return code
    }

    // MARK: Protocol eras

    func testDiscoverAnswersTheStatelessRevision() throws {
        let session = Session()
        let server = try makeServer(session)
        request(server, 1, "server/discover")
        let result = try XCTUnwrap(session.reply(1)?.field("result"))
        XCTAssertEqual(result.field("supportedVersions"), .array(["2026-07-28"]))
        XCTAssertEqual(result.field("resultType"), "complete")
        XCTAssertEqual(result.field("cacheScope"), "private")
        XCTAssertEqual(result.field("_meta")?.field(MCPProtocol.serverInfoKey)?.field("name"), "vocello")
        XCTAssertEqual(result.field("capabilities")?.field("tools")?.field("listChanged"), .bool(false))
        XCTAssertNotNil(result.field("ttlMs"))

        request(server, 2, "tools/list")
        let listed = try XCTUnwrap(session.reply(2)?.field("result"))
        XCTAssertEqual(listed.field("resultType"), "complete")
        XCTAssertNotNil(listed.field("ttlMs"))
        guard case .array(let tools)? = listed.field("tools") else { return XCTFail("no tools") }
        XCTAssertEqual(tools.count, server.tools.count)
    }

    func testAnUnsupportedRevisionNamesTheSupportedOnes() throws {
        let session = Session()
        let server = try makeServer(session)
        send(server, .object([
            "jsonrpc": "2.0", "id": 1, "method": "tools/list",
            "params": .object(["_meta": .object([MCPProtocol.protocolVersionKey: "2025-06-18"])]),
        ]))
        let error = try XCTUnwrap(session.reply(1)?.field("error"))
        XCTAssertEqual(error.field("code"), .integer(-32022))
        XCTAssertEqual(error.field("data")?.field("supported"), .array(["2026-07-28"]))
        XCTAssertEqual(error.field("data")?.field("requested"), "2025-06-18")
    }

    func testInitializeSelectsAnEarlierRevisionForTheProcess() throws {
        let session = Session()
        let server = try makeServer(session)
        request(server, 1, "tools/list", modern: false)
        XCTAssertEqual(session.reply(1)?.field("error")?.field("code"), .integer(-32600), "no handshake and no _meta")

        request(server, 2, "initialize", ["protocolVersion": "2025-03-26", "capabilities": .object([:])], modern: false)
        let initialized = try XCTUnwrap(session.reply(2)?.field("result"))
        XCTAssertEqual(initialized.field("protocolVersion"), "2025-03-26")
        XCTAssertEqual(initialized.field("serverInfo")?.field("name"), "vocello")
        XCTAssertNotNil(initialized.field("instructions"))

        send(server, .object(["jsonrpc": "2.0", "method": "notifications/initialized"]))
        request(server, 3, "tools/list", modern: false)
        let listed = try XCTUnwrap(session.reply(3)?.field("result"))
        XCTAssertNotNil(listed.field("tools"))
        XCTAssertNil(listed.field("resultType"), "an initialize-era result keeps its own shape")

        request(server, 4, "initialize", ["protocolVersion": "2031-01-01"], modern: false)
        XCTAssertEqual(session.reply(4)?.field("result")?.field("protocolVersion"), .string(MCPProtocol.legacyVersions[0]))
    }

    func testMalformedMessagesGetJSONRPCErrors() throws {
        let session = Session()
        let server = try makeServer(session)
        server.receive("not json")
        server.receive("[1, 2]")
        server.receive(#"{"jsonrpc":"1.0","id":7,"method":"ping"}"#)
        request(server, 8, "resources/list")
        request(server, 9, "tools/call", ["name": "no_such_tool"])
        request(server, 10, "tools/call", ["name": "list_voices", "arguments": "nope"])
        let errors = session.sent.withLock { $0 }.compactMap { message -> (CLIJSONValue?, CLIJSONValue?)? in
            guard let error = message.field("error") else { return nil }
            return (message.field("id"), error.field("code"))
        }
        XCTAssertEqual(errors.map(\.0), [.null, .null, .integer(7), .integer(8), .integer(9), .integer(10)])
        XCTAssertEqual(
            errors.map(\.1),
            [.integer(-32700), .integer(-32600), .integer(-32600), .integer(-32601), .integer(-32602), .integer(-32602)]
        )
    }

    // MARK: Tools

    func testToolArgumentsBecomeTheCommandLine() async throws {
        let session = Session()
        let server = try makeServer(session)
        call(server, 1, "list_history", ["query": "-dash words", "mode": "clone", "limit": 5])
        call(server, 2, "get_history_item", ["id": 42])
        call(server, 3, "list_history", ["mood": "x"])
        call(server, 4, "get_voice")
        await server.drain()

        let searched = try XCTUnwrap(session.reply(1)?.field("result"))
        XCTAssertEqual(searched.field("isError"), .bool(false))
        let echo = try XCTUnwrap(searched.field("structuredContent"))
        XCTAssertEqual(echo.field("command"), "history.search")
        XCTAssertEqual(echo.field("machine"), .bool(true), "a captured command reports as in json mode")
        XCTAssertEqual(echo.field("warmScope"), .bool(true), "a command runs on the server's warm engine")
        XCTAssertEqual(echo.field("args")?.field("operands"), .array(["-dash words"]))
        XCTAssertEqual(echo.field("args")?.field("values")?.field("mode"), "clone")
        XCTAssertEqual(echo.field("args")?.field("values")?.field("limit"), "5")
        XCTAssertEqual(session.reply(2)?.field("result")?.field("structuredContent")?.field("args")?.field("operands"), .array(["42"]))

        XCTAssertEqual(errorCode(session.reply(3)?.field("result")), "usage_error")
        XCTAssertEqual(errorCode(session.reply(4)?.field("result")), "usage_error")
        XCTAssertEqual(session.invocations.withLock { $0.count }, 2, "a refused call runs no command")
    }

    func testAGenerationRequestGoesThroughTheRequestParser() async throws {
        let session = Session()
        let server = try makeServer(session)
        call(server, 1, "generate_speech", [
            "text": "Hello.", "mode": "custom", "seed": 12, "stream": false, "clientRequestID": "take-1",
        ])
        call(server, 2, "generate_speech", ["text": "Hello.", "textFile": "/tmp/script.txt"])
        call(server, 3, "generate_speech", ["text": "-"])
        await server.drain()

        let args = try XCTUnwrap(session.reply(1)?.field("result")?.field("structuredContent")?.field("args"))
        XCTAssertEqual(args.field("values")?.field("text"), "Hello.")
        XCTAssertEqual(args.field("values")?.field("seed"), "12")
        XCTAssertEqual(args.field("values")?.field("client-request-id"), "take-1")
        XCTAssertEqual(args.field("flags"), .array(["no-stream"]))
        XCTAssertEqual(errorCode(session.reply(2)?.field("result")), "usage_error", "an agent passes its text, not a file")
        XCTAssertEqual(errorCode(session.reply(3)?.field("result")), "invalid_input")
    }

    func testPathsStayInsideTheAllowedFolders() async throws {
        let session = Session()
        let allowed = try makeFolder("allowed")
        let outside = try makeFolder("outside")
        let sibling = URL(fileURLWithPath: allowed.path + "-x", isDirectory: true)
        try FileManager.default.createDirectory(at: sibling, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: sibling) }
        let clip = allowed.appendingPathComponent("clip.wav")
        try Data("RIFF".utf8).write(to: clip)
        try Data("RIFF".utf8).write(to: outside.appendingPathComponent("secret.wav"))
        try FileManager.default.createSymbolicLink(
            at: allowed.appendingPathComponent("escape"), withDestinationURL: outside
        )
        try FileManager.default.createSymbolicLink(
            at: allowed.appendingPathComponent("dangling.wav"), withDestinationURL: outside.appendingPathComponent("gone.wav")
        )
        try FileManager.default.createSymbolicLink(
            at: outside.appendingPathComponent("dangling.wav"), withDestinationURL: outside.appendingPathComponent("gone.wav")
        )
        let server = try makeServer(session, allowed: [allowed])
        let outputs = server.configuration.dataDirectory.appendingPathComponent("outputs", isDirectory: true)
        let take = outputs.appendingPathComponent("custom/take.wav")
        try FileManager.default.createDirectory(at: take.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("RIFF".utf8).write(to: take)

        let refused: [(Int, String)] = [
            (1, "take.wav"),
            (2, outside.appendingPathComponent("take.wav").path),
            (3, allowed.path + "/../take.wav"),
            (4, allowed.appendingPathComponent("escape/take.wav").path),
            (5, allowed.appendingPathComponent("dangling.wav").path),
            (6, sibling.appendingPathComponent("take.wav").path),
            (7, take.path),
        ]
        for (id, out) in refused {
            call(server, id, "generate_speech", ["text": "Hello.", "out": .string(out)])
        }
        let inside = allowed.appendingPathComponent("new/folder/take.wav").path
        let cli = outputs.appendingPathComponent("cli/take.wav").path
        call(server, 10, "generate_speech", ["text": "Hello.", "out": .string(inside)])
        call(server, 11, "generate_speech", ["text": "Hello.", "out": .string(cli)])
        call(server, 12, "generate_speech", ["text": "Hello.", "mode": "clone", "reference": .string(take.path)])
        call(server, 13, "enroll_voice", [
            "name": "Ann", "audio": .string(allowed.appendingPathComponent("missing.wav").path), "confirmConsent": true,
        ])
        call(server, 14, "enroll_voice", ["name": "Ann", "audio": .string(clip.path), "confirmConsent": true])
        call(server, 17, "generate_speech", ["text": "Hello.", "out": .string(outside.appendingPathComponent("dangling.wav").path)])
        for (id, audio) in [(15, "secret.wav"), (16, "absent.wav")] {
            call(server, id, "enroll_voice", [
                "name": "Ann", "audio": .string(outside.appendingPathComponent(audio).path), "confirmConsent": true,
            ])
        }
        await server.drain()

        for (id, out) in refused {
            XCTAssertEqual(errorCode(session.reply(id)?.field("result")), "path_not_allowed", out)
        }
        func value(_ id: Int, _ name: String) -> CLIJSONValue? {
            session.reply(id)?.field("result")?.field("structuredContent")?.field("args")?.field("values")?.field(name)
        }
        XCTAssertEqual(value(10, "out"), .string(try XCTUnwrap(MCPPathPolicy.resolve(inside))))
        XCTAssertEqual(value(11, "out"), .string(try XCTUnwrap(MCPPathPolicy.resolve(cli))), "the CLI's own outputs are writable")
        XCTAssertEqual(value(12, "reference"), .string(try XCTUnwrap(MCPPathPolicy.resolve(take.path))), "a History take is readable")
        XCTAssertEqual(errorCode(session.reply(13)?.field("result")), "input_file_not_found")
        XCTAssertEqual(value(14, "audio"), .string(try XCTUnwrap(MCPPathPolicy.resolve(clip.path))))
        XCTAssertEqual(errorCode(session.reply(15)?.field("result")), "path_not_allowed")
        XCTAssertEqual(
            errorCode(session.reply(16)?.field("result")), "path_not_allowed",
            "a refusal outside never says whether the file exists"
        )
        XCTAssertEqual(errorCode(session.reply(17)?.field("result")), "path_not_allowed")
        XCTAssertEqual(
            session.reply(5)?.field("result")?.firstText?.contains("symbolic link to nothing"), true,
            "inside, a link to nothing is named"
        )
        XCTAssertEqual(
            session.reply(17)?.field("result")?.firstText?.contains("is outside"), true,
            "outside, it is only outside"
        )
        XCTAssertEqual(session.invocations.withLock { $0.count }, 4, "a refused path runs no command")
    }

    func testAnAllowedFolderMustExist() throws {
        let missing = FileManager.default.temporaryDirectory.appendingPathComponent("MCPServer-missing-\(UUID().uuidString)")
        XCTAssertThrowsError(try makeServer(Session(), allowed: [missing])) { error in
            XCTAssertEqual((error as? CLIError)?.code, .configError)
        }
    }

    // MARK: The engine gate

    func testEngineRequestsRunOneAtATimeAndTheQueueIsBounded() async throws {
        let session = Session()
        let running = Mutex((now: 0, most: 0))
        let permits = Mutex(0)
        let server = try makeServer(session, maxQueue: 1) { invocation in
            guard invocation.commandName == "generate" else { return CLIPresenter.succeed(CLIEmptyResult()) }
            running.withLock { $0.now += 1; $0.most = max($0.most, $0.now) }
            defer { running.withLock { $0.now -= 1 } }
            while !permits.withLock({ permits in
                guard permits > 0 else { return false }
                permits -= 1
                return true
            }) {
                try await Task.sleep(for: .milliseconds(2))
            }
            CLIPresenter.succeed(CLIEmptyResult())
        }
        call(server, 1, "generate_speech", ["text": "One."])
        call(server, 2, "generate_speech", ["text": "Two."])
        call(server, 3, "generate_speech", ["text": "Three."])
        call(server, 4, "list_voices")
        try await until("the refusal and the read") { session.reply(3) != nil && session.reply(4) != nil }

        XCTAssertEqual(errorCode(session.reply(3)?.field("result")), "engine_busy", "one runs, one waits, the next is refused")
        XCTAssertEqual(session.reply(4)?.field("result")?.field("isError"), .bool(false), "a read never waits for the engine")
        XCTAssertTrue(server.gate.isRunning)
        XCTAssertEqual(server.gate.waiting, 1)
        permits.withLock { $0 += 1 }
        try await until("the first take") { session.reply(1) != nil }
        permits.withLock { $0 += 1 }
        await server.drain()

        XCTAssertEqual(session.reply(2)?.field("result")?.field("isError"), .bool(false))
        XCTAssertEqual(running.withLock { $0.most }, 1)
        XCTAssertFalse(server.gate.isRunning)
    }

    func testACancelledCallStopsAndIsNotAnswered() async throws {
        let session = Session()
        let stopped = Mutex(false)
        let server = try makeServer(session, maxQueue: 2) { invocation in
            guard invocation.commandName == "generate" else { return CLIPresenter.succeed(CLIEmptyResult()) }
            CLIPresenter.event(.generationStarted)
            do {
                while true { try await Task.sleep(for: .milliseconds(10)) }
            } catch {
                stopped.withLock { $0 = true }
                throw error
            }
        }
        call(server, 1, "generate_speech", ["text": "Long."], progressToken: "p")
        call(server, 2, "generate_speech", ["text": "Waiting."])
        try await until("the take to start") { !session.progress("p").isEmpty }
        send(server, .object([
            "jsonrpc": "2.0", "method": "notifications/cancelled", "params": .object(["requestId": 1, "reason": "test"]),
        ]))
        send(server, .object([
            "jsonrpc": "2.0", "method": "notifications/cancelled", "params": .object(["requestId": 2]),
        ]))
        await server.drain()

        XCTAssertTrue(stopped.withLock { $0 }, "the running command saw its cancellation")
        XCTAssertNil(session.reply(1), "a cancelled call is not answered")
        XCTAssertNil(session.reply(2), "a waiting call leaves the queue")
        XCTAssertFalse(server.gate.isRunning)
        XCTAssertEqual(server.gate.waiting, 0)
        XCTAssertEqual(session.invocations.withLock { $0.count }, 1, "the cancelled waiter never ran")

        // The engine is free for the next request.
        call(server, 3, "generate_speech", ["text": "Next."], progressToken: "p3")
        try await until("the next take to start") { !session.progress("p3").isEmpty }
        XCTAssertTrue(server.gate.isRunning)
        send(server, .object(["jsonrpc": "2.0", "method": "notifications/cancelled", "params": .object(["requestId": 3])]))
        await server.drain()
        XCTAssertEqual(session.invocations.withLock { $0.count }, 2)
    }

    func testTheEngineStaysHeldUntilACancelledCommandHasStopped() async throws {
        let session = Session()
        let log = Mutex<[String]>([])
        let server = try makeServer(session) { invocation in
            guard invocation.commandName == "generate" else { return CLIPresenter.succeed(CLIEmptyResult()) }
            guard case .string(let text)? = invocation.args.canonicalForm(excluding: []).field("values")?.field("text") else {
                return
            }
            log.withLock { $0.append("\(text) started") }
            do {
                while true { try await Task.sleep(for: .milliseconds(5)) }
            } catch {
                // The engine's barrier takes a while to settle: others run meanwhile.
                for _ in 0 ..< 20 { await Task.yield() }
                log.withLock { $0.append("\(text) stopped") }
                throw error
            }
        }
        call(server, 1, "generate_speech", ["text": "first"], progressToken: "a")
        call(server, 2, "generate_speech", ["text": "second"], progressToken: "b")
        try await until("the first take") { log.withLock { $0 } == ["first started"] }
        send(server, .object(["jsonrpc": "2.0", "method": "notifications/cancelled", "params": .object(["requestId": 1])]))
        try await until("the second take") { log.withLock { $0 }.count == 3 }
        XCTAssertEqual(log.withLock { $0 }, ["first started", "first stopped", "second started"])
        send(server, .object(["jsonrpc": "2.0", "method": "notifications/cancelled", "params": .object(["requestId": 2])]))
        await server.drain()
    }

    // MARK: Reports

    func testProgressFollowsTheCommandsEvents() async throws {
        let session = Session()
        let server = try makeServer(session) { _ in
            CLIPresenter.event(.modelLoading, data: ["modelID": "pro_custom_speed"])
            CLIPresenter.event(.chunk, data: ["chunks": 1])
            CLIPresenter.event(.chunk, data: ["chunks": 2])
            CLIPresenter.event(.progress, data: ["finished": 2, "lines": 5])
            CLIPresenter.warn("concurrent_engine", "another engine runs")
            CLIPresenter.succeed(CLIEmptyResult())
        }
        call(server, 1, "list_voices", progressToken: "t")
        call(server, 2, "list_voices")
        await server.drain()

        let notes = session.progress("t")
        XCTAssertEqual(notes.map { $0.field("params")?.field("progress") }, [1, 2, 3, 4].map { .integer($0) })
        XCTAssertEqual(
            notes.map { $0.field("params")?.field("message") },
            ["model_loading pro_custom_speed", "chunk 1 chunks", "progress 2/5", "warning another engine runs"].map { .string($0) },
            "a chunk within half a second of the last is not repeated"
        )
        XCTAssertEqual(session.sent.withLock { $0 }.filter { $0.field("method") != nil }.count, 4, "no token, no progress")
        guard case .array(let content)? = session.reply(1)?.field("result")?.field("content") else { return XCTFail() }
        XCTAssertEqual(content.last?.field("text"), "warning concurrent_engine: another engine runs")
    }

    func testAFailureIsAToolErrorWithTheContractsError() async throws {
        let session = Session()
        let server = try makeServer(session) { _ in
            CLIPresenter.recordPartialResult(["kept": 1])
            throw CLIError(.voiceNotFound, "no saved voice 'Ann'", hint: "see list_voices")
        }
        call(server, 1, "get_voice", ["voice": "Ann"])
        await server.drain()
        let result = try XCTUnwrap(session.reply(1)?.field("result"))
        XCTAssertEqual(result.field("isError"), .bool(true))
        XCTAssertEqual(result.firstText, "voice_not_found: no saved voice 'Ann' (see list_voices)")
        let error = try XCTUnwrap(result.field("structuredContent")?.field("error"))
        XCTAssertEqual(error.field("category"), "not_found")
        XCTAssertEqual(error.field("exitCode"), 66)
        XCTAssertEqual(result.field("structuredContent")?.field("result"), .object(["kept": 1]))
    }

    func testGetStatusAndInstallModelAreTheServers() async throws {
        let session = Session()
        let server = try makeServer(session)
        XCTAssertFalse(server.tools.contains { $0.name == "install_model" })
        call(server, 1, "get_status")
        call(server, 2, "install_model", ["id": "pro_custom_speed"])
        await server.drain()
        let status = try XCTUnwrap(session.reply(1)?.field("result")?.field("structuredContent"))
        XCTAssertEqual(status.field("engine")?.field("started"), .bool(false))
        XCTAssertEqual(status.field("modelInstall"), .bool(false))
        XCTAssertEqual(session.reply(2)?.field("error")?.field("code"), .integer(-32602), "install_model is not offered")

        let installing = try makeServer(Session(), allowModelInstall: true)
        let install = try XCTUnwrap(installing.tools.first { $0.name == "install_model" })
        XCTAssertEqual(install.kind, .engine)
        XCTAssertTrue(install.hints.openWorld)
    }

    // MARK: Schemas and the capture

    func testTheGenerationSchemaIsTheContractsRequestWithoutTextFile() throws {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("config/cli-contract/v1/generate-request.schema.json")
        let contract = try JSONDecoder().decode(CLIJSONValue.self, from: Data(contentsOf: url))
        guard case .object(var properties)? = contract.field("properties") else { return XCTFail("no properties") }
        properties["textFile"] = nil
        XCTAssertEqual(MCPTools.generationRequestSchema.field("properties"), .object(properties))
        XCTAssertEqual(MCPTools.generationRequestSchema.field("additionalProperties"), .bool(false))
    }

    func testEveryToolSchemaIsAClosedObjectNamingItsRequiredArguments() throws {
        for tool in MCPTools.catalog(allowModelInstall: true) {
            let schema = tool.inputSchema
            XCTAssertEqual(schema.field("type"), "object", tool.name)
            XCTAssertEqual(schema.field("additionalProperties"), .bool(false), tool.name)
            guard case .array(let required)? = schema.field("required"), case .object(let properties)? = schema.field("properties")
            else { return XCTFail(tool.name) }
            for case .string(let name) in required { XCTAssertNotNil(properties[name], "\(tool.name).\(name)") }
            if tool.kind != .server, !tool.takesGenerationRequest {
                XCTAssertNotNil(VocelloCommandTree.spec(at: tool.path), "\(tool.name) runs an existing command")
            }
        }
    }

    func testTheCaptureReportsAsJsonModeAndKeepsTheFirstReport() throws {
        let capture = CLIPresenterCapture()
        CLIPresenter.$capture.withValue(capture) {
            XCTAssertTrue(CLIPresenter.isMachine)
            XCTAssertEqual(CLIPresenter.requestID, capture.requestID)
            CLIPresenter.warn("w", "a warning")
            CLIPresenter.markReplayed()
            CLIPresenter.succeed(["first": 1])
            CLIPresenter.fail(CLIErrorObject(code: .internalError, message: "late"))
        }
        let report = try XCTUnwrap(capture.report)
        XCTAssertTrue(report.ok)
        XCTAssertEqual(report.result, .object(["first": 1]))
        XCTAssertEqual(report.warnings.map(\.code), ["w"])
        XCTAssertTrue(report.replayed)
    }

    func testAStoppingServerStartsNoCallAndAnUnencodableReplyStillAnswers() async throws {
        let session = Session()
        let server = try makeServer(session)
        server.stop()
        call(server, 1, "list_voices")
        await server.drain()
        XCTAssertNil(session.reply(1))
        XCTAssertEqual(session.invocations.withLock { $0.count }, 0)

        let unencodable = MCPOutgoing.result(id: 7, .object(["value": .number(.nan)]))
        let line = try JSONDecoder().decode(CLIJSONValue.self, from: MCPOutgoing.line(unencodable))
        XCTAssertEqual(line.field("id"), 7)
        XCTAssertEqual(line.field("error")?.field("code"), .integer(-32603))
        XCTAssertTrue(MCPOutgoing.line(MCPOutgoing.notification("notifications/progress", ["n": .number(.nan)])).isEmpty)
    }

    func testTheServerNeverReadsStdinOrPrompts() throws {
        CLIOutput.configureForServer(verbose: false)
        defer { CLIOutput.configure(try! CLIParser.parse(["version"])) }
        XCTAssertFalse(CLIOutput.implicitStdinAllowed, "stdin carries the protocol")
        XCTAssertFalse(CLIOutput.promptsAllowed)
        XCTAssertEqual(CLIOutput.verbosity, .quiet)
    }

    func testTheWarmEngineServesEveryCommandUnderItsOwnConsent() async throws {
        let root = try makeFolder("warm")
        let contract = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
        let consented = CLIVoiceCloningConsent.policy(confirmed: true)
        let warm = CLIWarmEngine(dataDirectory: root, manifestOverride: contract, concurrency: CLIEngineConcurrency())
        var engine: MLXTTSEngine?
        defer { engine?.stop() }
        try await CLIEngineScope.$warm.withValue(warm) {
            func boot(_ consent: VoiceCloningConsentPolicy, hosted: Bool) async throws -> CLIRuntime {
                try await CLIRuntime.bootstrap(
                    dataDirectory: root, manifestOverride: contract, voiceCloningConsent: consent,
                    hostedLikeTheApp: hosted, takesEngineLease: false
                )
            }
            // Two first calls together boot one engine.
            async let first = boot(consented, hosted: true)
            async let second = boot(CLIVoiceCloningConsent.notConfirmed, hosted: false)
            let (clone, read) = try await (first, second)
            XCTAssertTrue(clone.engine === read.engine)
            engine = clone.engine
            let host = try XCTUnwrap(clone.host)

            let plain = try await boot(CLIVoiceCloningConsent.notConfirmed, hosted: true)
            XCTAssertTrue(plain.engine === clone.engine)
            XCTAssertFalse(plain.voiceCloningConsent.isConsentRecorded)
            XCTAssertFalse(host.consent.isConsentRecorded, "a hosted request's consent becomes the host's")

            let again = try await boot(consented, hosted: true)
            XCTAssertTrue(host.consent.isConsentRecorded)
            let reading = try await boot(CLIVoiceCloningConsent.notConfirmed, hosted: false)
            XCTAssertTrue(reading.engine === again.engine)
            XCTAssertFalse(reading.voiceCloningConsent.isConsentRecorded)
            XCTAssertTrue(host.consent.isConsentRecorded, "a read leaves the host's consent alone")
            XCTAssertFalse(warm.holdsLease)

            let other = try makeFolder("other")
            do {
                _ = try await CLIRuntime.bootstrap(dataDirectory: other, manifestOverride: contract, hostedLikeTheApp: true)
                XCTFail("another data folder is refused")
            } catch {
                XCTAssertEqual((error as? CLIError)?.code, .internalError)
            }
        }
        XCTAssertTrue(warm.isBooted)
    }

    func testTheSetupNamesThisExecutableAndTheServersOptions() throws {
        let args = try CLIParser.args(["--allow-dir=/tmp/a:/tmp/b", "--allow-model-install", "--max-queue=2"], for: "mcp")
        XCTAssertEqual(
            MCPCommand.serverArguments(args),
            ["mcp", "--allow-dir=/tmp/a:/tmp/b", "--max-queue=2", "--allow-model-install"]
        )
        XCTAssertEqual(
            MCPCommand.serverArguments(
                try CLIParser.args([], for: "mcp"), unshippedManifest: URL(fileURLWithPath: "/repo/Sources/Resources/c.json")
            ),
            ["mcp", "--manifest=/repo/Sources/Resources/c.json"], "a development build names the contract it found"
        )
        XCTAssertEqual(MCPCommand.shellQuoted("/Users/example/My Tools/vocello"), "'/Users/example/My Tools/vocello'")
        XCTAssertEqual(MCPCommand.shellQuoted("--allow-dir=/tmp/a"), "--allow-dir=/tmp/a")
        XCTAssertEqual(MCPCommand.shellQuoted("it's"), "'it'\\''s'")
    }
}
