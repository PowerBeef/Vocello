import Foundation
import XCTest
@testable import VocelloCLICore

/// RF-27: agents send generation requests as JSON objects that go through the
/// command line's own parser, and a client request id makes a request
/// idempotent across processes.
final class CLIRequestTests: XCTestCase {
    private func makeRoot() throws -> URL {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("CLIRequest-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }

    private func json(_ text: String) throws -> CLIJSONValue {
        try JSONDecoder().decode(CLIJSONValue.self, from: Data(text.utf8))
    }

    // MARK: - Requests

    func testARequestBecomesStrictGenerateArguments() throws {
        let parsed = try CLIGenerateRequest.parse(try json("""
            {"mode":"clone","text":"--looks like a flag","voice":"Nora","confirmConsent":true,"appDelivery":false,
             "seed":18446744073709551615,"stream":false,"variation":"balanced","clientRequestID":"agent-7"}
            """))
        XCTAssertEqual(parsed.clientRequestID, "agent-7")
        let args = try CLIParser.args(parsed.argv, for: "generate")
        XCTAssertEqual(args.string("mode"), "clone")
        XCTAssertEqual(args.string("text"), "--looks like a flag", "a value that starts with -- stays a value")
        XCTAssertEqual(args.string("seed"), "18446744073709551615")
        XCTAssertTrue(args.flag("confirm-consent"))
        XCTAssertFalse(args.flag("app-delivery"))
        XCTAssertTrue(args.flag("no-stream"), "stream: false")
        XCTAssertFalse(parsed.argv.contains { $0.contains("agent-7") }, "the id is not a generate option")
        XCTAssertEqual(try CLIGenerateRequest.parse(try json(#"{"seed":"42"}"#)).argv, ["--seed=42"])
        XCTAssertNil(try CLIGenerateRequest.parse(try json(#"{"clientRequestID":null}"#)).clientRequestID,
                     "null means absent, as for every field")
    }

    func testARequestIsRefusedForWhatTheCommandLineWouldRefuse() throws {
        func refusal(_ text: String) -> CLIError? {
            do {
                let parsed = try CLIGenerateRequest.parse(try json(text))
                _ = try CLIParser.args(parsed.argv, for: "generate")
                return nil
            } catch {
                return error as? CLIError
            }
        }
        XCTAssertEqual(refusal(#"{"txt":"typo"}"#)?.code, .usageError)
        XCTAssertEqual(refusal(#"{"txt":"typo"}"#)?.hint, "did you mean 'text'?")
        XCTAssertEqual(refusal(#"["not","an","object"]"#)?.code, .invalidInput)
        XCTAssertEqual(refusal(#"{"text":42}"#)?.code, .invalidInput)
        XCTAssertEqual(refusal(#"{"seed":-1}"#)?.code, .invalidInput)
        XCTAssertEqual(refusal(#"{"seed":"1.5"}"#)?.code, .invalidInput)
        XCTAssertEqual(refusal(#"{"confirmConsent":"yes"}"#)?.code, .invalidInput)
        XCTAssertEqual(refusal(#"{"text":"-"}"#)?.code, .invalidInput, "stdin carries the requests")
        XCTAssertEqual(refusal(#"{"clientRequestID":"has space"}"#)?.code, .usageError)
        XCTAssertNil(refusal(#"{"text":"Hello","speaker":null}"#), "null means absent")
    }

    func testTheRequestSchemaNamesExactlyTheFieldsARequestTakes() throws {
        let schemaURL = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("config/cli-contract/v1/generate-request.schema.json")
        let schema = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: schemaURL)) as? [String: Any]
        )
        let properties = try XCTUnwrap(schema["properties"] as? [String: Any])
        XCTAssertEqual(Set(properties.keys), CLIGenerateRequest.fieldNames)
        XCTAssertEqual(schema["additionalProperties"] as? Bool, false)
        for (field, option) in CLIGenerateRequest.fields {
            XCTAssertNotNil(
                VocelloCommandTree.spec(at: ["generate"])?.option(named: option.option),
                "\(field) maps to a generate option"
            )
        }
    }

    // MARK: - Identity

    private var contract: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
            .appendingPathComponent("Sources/Resources/qwenvoice_contract.json")
    }

    @MainActor
    private func take(_ argv: [String], root: URL) async throws -> GenerateCommand.PreparedTake {
        let args = try CLIParser.args(argv + ["--data-dir=\(root.path)", "--manifest=\(contract.path)"], for: "generate")
        return try await GenerateCommand.prepare(args, interactive: false)
    }

    @MainActor
    private func identity(_ argv: [String], root: URL) async throws -> CLIJSONValue {
        try GenerateCommand.identity(of: try await take(argv, root: root))
    }

    /// Review B1/N7: idempotency compares the take, so text that arrives through a
    /// file is identified by its content, and spellings of one request agree.
    @MainActor
    func testTheIdentityIsTheTakeNotItsSpelling() async throws {
        let root = try makeRoot()
        let script = root.appendingPathComponent("script.txt")
        try "Hello there.".write(to: script, atomically: true, encoding: .utf8)
        let hello = try await identity(["--text", "Hello there."], root: root)
        let fromFile = try await identity(["--text-file", script.path], root: root)
        XCTAssertEqual(fromFile, hello, "a file's text is its content")
        try "Goodbye.".write(to: script, atomically: true, encoding: .utf8)
        let edited = try await identity(["--text-file", script.path], root: root)
        XCTAssertNotEqual(edited, hello, "an edited script is a different request")

        let spelled = try await identity(
            ["--text", "Hello there.", "--variant", "fast", "--seed", "42", "--language", "auto"], root: root
        )
        let respelled = try await identity(
            ["--text", "Hello there.", "--variant", "speed", "--seed", "0042", "--stream"], root: root
        )
        XCTAssertEqual(spelled, respelled, "aliases, number spellings and defaults mean one request")
        let seeded = try await identity(["--text", "Hello there.", "--seed", "42"], root: root)
        XCTAssertNotEqual(seeded, hello)
        let reported = try await identity(["--text", "Hello there.", "--quiet", "--client-request-id", "a"], root: root)
        XCTAssertEqual(reported, hello, "how a command reports is not what it asks for")
        let accumulated = try await identity(["--text", "Hello there.", "--no-stream"], root: root)
        XCTAssertNotEqual(accumulated, hello)

        let request = try CLIGenerateRequest.parse(try json(#"{"text":"Hello there.","seed":42,"variant":"speed"}"#))
        let asRequest = try await identity(request.argv, root: root)
        let asCommandLine = try await identity(["--text", "Hello there.", "--seed", "42", "--variant", "speed"], root: root)
        XCTAssertEqual(asRequest, asCommandLine, "a run request and the same generate command line are one request")
    }

    /// Review S4: a request with no text never takes unnamed stdin.
    func testARequestNeverReadsUnnamedStdin() throws {
        let args = try CLIParser.args([], for: "generate")
        XCTAssertThrowsError(try GenerateCommand.resolveText(args, implicitStdin: false)) {
            XCTAssertEqual(($0 as? CLIError)?.code, .usageError)
        }
    }

    // MARK: - Ledger

    func testTheLedgerRunsOnceThenReplaysAndRefusesADifferentRequest() throws {
        let ledger = CLIRequestLedger(dataDirectory: try makeRoot())
        let request = try json(#"{"text":"Hello"}"#)
        guard case .fresh(let reservation) = try ledger.claim(id: "job-1", request: request) else {
            return XCTFail("a new id runs")
        }
        guard case .inProgress = try ledger.claim(id: "job-1", request: request) else {
            return XCTFail("the same id while it runs is in progress")
        }
        let result = try json(#"{"audioPath":"/x.wav","seed":"18446744073709551615"}"#)
        ledger.complete(reservation, result: result)

        guard case .replay(let stored) = try ledger.claim(id: "job-1", request: request) else {
            return XCTFail("the same id and request replays")
        }
        XCTAssertEqual(stored, result, "a large seed survives storage exactly")
        guard case .conflict = try ledger.claim(id: "job-1", request: try json(#"{"text":"Other"}"#)) else {
            return XCTFail("the same id for another request conflicts")
        }
        let entry = try XCTUnwrap(
            FileManager.default.contentsOfDirectory(at: ledger.directory, includingPropertiesForKeys: nil)
                .first { $0.pathExtension == "json" }
        )
        let mode = try FileManager.default.attributesOfItem(atPath: entry.path)[.posixPermissions] as? NSNumber
        XCTAssertEqual(mode?.intValue, 0o600, "a stored result names an output path: private")
        XCTAssertFalse(entry.lastPathComponent.contains("job-1"), "files are named by the id's digest")
    }

    func testAFailedRequestKeepsNothingAndOldEntriesArePruned() throws {
        let ledger = CLIRequestLedger(dataDirectory: try makeRoot())
        let request = try json(#"{"text":"Hello"}"#)
        guard case .fresh(let failed) = try ledger.claim(id: "job-2", request: request) else { return XCTFail() }
        ledger.abandon(failed)
        guard case .fresh(let retry) = try ledger.claim(id: "job-2", request: request) else {
            return XCTFail("a failed request runs again")
        }
        let longAgo = Date(timeIntervalSinceNow: -(CLIRequestLedger.retention + 60))
        XCTAssertTrue(ledger.complete(retry, result: try json(#"{"ok":true}"#), now: longAgo))
        func files() throws -> [String] {
            try FileManager.default.contentsOfDirectory(atPath: ledger.directory.path)
                .filter { $0 != "ledger.lock" }.sorted()
        }
        XCTAssertEqual(try files().count, 2, "an entry and its lock file")
        guard case .fresh(let next) = try ledger.claim(id: "job-3", request: request) else { return XCTFail() }
        ledger.complete(next, result: try json(#"{"ok":true}"#))
        XCTAssertEqual(try files().count, 2, "the old entry is pruned with its lock file; job-3's remain")
        guard case .fresh(let again) = try ledger.claim(id: "job-2", request: request) else {
            return XCTFail("an entry past retention is pruned, so the id runs again")
        }
        ledger.abandon(again)
        XCTAssertThrowsError(try ledger.claim(id: "", request: request))
        XCTAssertThrowsError(try ledger.claim(id: String(repeating: "a", count: 129), request: request))
    }

    /// Review S1, S2, N4: a replay never claims a missing take, a result that
    /// cannot be kept is reported, and a damaged entry fails instead of running again.
    func testTheLedgerFailsClosed() throws {
        let root = try makeRoot()
        let ledger = CLIRequestLedger(dataDirectory: root)
        let request = try json(#"{"text":"Hello"}"#)
        let take = root.appendingPathComponent("take.wav")
        try Data([1]).write(to: take)

        guard case .run(let first) = try ledger.start(id: "job-1", request: request) else { return XCTFail() }
        XCTAssertTrue(ledger.complete(first, result: .object(["audioPath": .string(take.path)])))
        guard case .replay = try ledger.start(id: "job-1", request: request) else { return XCTFail("replays") }
        XCTAssertEqual(code { try ledger.start(id: "job-1", request: try self.json(#"{"text":"Other"}"#)) },
                       .idempotencyConflict)
        try FileManager.default.removeItem(at: take)
        XCTAssertEqual(code { try ledger.start(id: "job-1", request: request) }, .outputMissing,
                       "a replay never claims a take whose file is gone")

        guard case .run(let held) = try ledger.start(id: "job-2", request: request) else { return XCTFail() }
        XCTAssertEqual(code { try ledger.start(id: "job-2", request: request) }, .requestInProgress)
        try FileManager.default.setAttributes([.posixPermissions: 0o500], ofItemAtPath: ledger.directory.path)
        let kept = ledger.complete(held, result: try json(#"{"ok":true}"#))
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: ledger.directory.path)
        XCTAssertFalse(kept, "a result that could not be written is reported")
        guard case .run(let retry) = try ledger.start(id: "job-2", request: request) else {
            return XCTFail("nothing was kept, so the id runs again")
        }
        ledger.abandon(retry)

        let entry = try XCTUnwrap(
            FileManager.default.contentsOfDirectory(at: ledger.directory, includingPropertiesForKeys: nil)
                .first { $0.pathExtension == "json" }
        )
        try Data("{".utf8).write(to: entry)
        XCTAssertEqual(code { try ledger.start(id: "job-1", request: request) }, .ioError,
                       "a damaged entry fails rather than run a completed request again")
    }

    private func code(_ body: () throws -> CLIRequestLedger.Start) -> VocelloErrorCode? {
        do {
            _ = try body()
            return nil
        } catch {
            return (error as? CLIError)?.code
        }
    }

    // MARK: - run

    /// Review S3/S6: requests fail on their own, a repeated id replays, and a
    /// signal stops the run with every planned row.
    @MainActor
    func testRunKeepsEachRequestApartAndEveryRowWhenStopped() async throws {
        let root = try makeRoot()
        let take = root.appendingPathComponent("take.wav")
        try Data([1]).write(to: take)
        let ledger = CLIRequestLedger(dataDirectory: root)
        let shared = ["--data-dir=\(root.path)", "--manifest=\(contract.path)"]
        var executed = 0
        let execute: (GenerateCommand.PreparedTake) async throws -> CLIJSONValue = { _ in
            executed += 1
            return .object(["audioPath": .string(take.path)])
        }
        let documents = [
            #"{"text":"One.","clientRequestID":"r-1"}"#,
            "not json",
            #"{"text":"One.","clientRequestID":"r-1"}"#,
            #"{"txt":"typo"}"#,
        ]
        let outcome = await RunCommand.runRequests(documents, shared: shared, ledger: ledger, execute: execute)
        XCTAssertFalse(outcome.stopped)
        XCTAssertEqual(outcome.rows.map(\.ok), [true, false, true, false])
        XCTAssertEqual(outcome.rows.map(\.replayed), [false, false, true, false])
        XCTAssertEqual(outcome.rows.map { $0.error?.code }, [nil, .invalidInput, nil, .usageError])
        XCTAssertEqual(executed, 1, "the repeated id replays instead of running again")

        var calls = 0
        let stopping: (GenerateCommand.PreparedTake) async throws -> CLIJSONValue = { _ in
            calls += 1
            if calls == 2 { throw CancellationError() }
            return .object(["audioPath": .string(take.path)])
        }
        let stopped = await RunCommand.runRequests(
            [#"{"text":"A."}"#, #"{"text":"B.","clientRequestID":"r-2"}"#, #"{"text":"C."}"#],
            shared: shared, ledger: ledger, execute: stopping
        )
        XCTAssertTrue(stopped.stopped)
        XCTAssertEqual(stopped.rows.map(\.index), [0, 1, 2], "every planned row")
        XCTAssertEqual(stopped.rows.map { $0.error?.code }, [nil, .cancelled, .cancelled])
        XCTAssertEqual(stopped.rows[1].clientRequestID, "r-2")
        guard case .run(let retry) = try ledger.start(id: "r-2", request: CLIJSONValue.null) else {
            return XCTFail("a stopped request kept nothing")
        }
        ledger.abandon(retry)
        XCTAssertThrowsError(try RunCommand.report(stopped, single: false)) { XCTAssertTrue($0 is CancellationError) }

        let failing = await RunCommand.runRequests(
            [#"{"text":"A."}"#], shared: shared, ledger: ledger,
            execute: { _ in throw CLIError(.engineBusy, "busy", hint: "wait") }
        )
        XCTAssertThrowsError(try RunCommand.report(failing, single: true)) {
            XCTAssertEqual($0 as? CLIError, CLIError(.engineBusy, "busy", hint: "wait"),
                           "one request fails exactly as generate would")
        }
    }

    func testRequestsSplitOnNewlinesOnly() throws {
        let file = try makeRoot().appendingPathComponent("requests.jsonl")
        try "{\"text\":\"a\u{2028}b\"}\r\n\n{\"text\":\"c\"}\n".write(to: file, atomically: true, encoding: .utf8)
        XCTAssertEqual(try RunCommand.readDocuments(from: file.path, single: false).count, 2,
                       "a raw U+2028 inside a string never splits a request")
    }
}
