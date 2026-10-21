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
        guard case .object(let identity) = parsed.identity else { return XCTFail("identity is an object") }
        XCTAssertNil(identity["clientRequestID"], "the id is not part of what idempotency compares")
        XCTAssertEqual(try CLIGenerateRequest.parse(try json(#"{"seed":"42"}"#)).argv, ["--seed=42"])
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
        ledger.complete(retry, result: try json(#"{"ok":true}"#), now: longAgo)
        guard case .fresh(let next) = try ledger.claim(id: "job-3", request: request) else { return XCTFail() }
        ledger.complete(next, result: try json(#"{"ok":true}"#))
        guard case .fresh(let again) = try ledger.claim(id: "job-2", request: request) else {
            return XCTFail("an entry past retention is pruned, so the id runs again")
        }
        ledger.abandon(again)
        XCTAssertThrowsError(try ledger.claim(id: "", request: request))
        XCTAssertThrowsError(try ledger.claim(id: String(repeating: "a", count: 129), request: request))
    }
}
