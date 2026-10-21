import Foundation
import QwenVoiceCore

/// `vocello run`: generation requests as JSON (RF-27), for agents. One request
/// reports exactly as `generate` does; JSONL requests run one after another on
/// one warm engine, each independent of the others' failures, and the result
/// lists every request. A signal stops the run and keeps every row: the
/// requests that finished, the one it interrupted and those it never reached.
public enum RunCommand {
    struct Row: Encodable, Sendable {
        let index: Int
        let clientRequestID: String?
        let ok: Bool
        let replayed: Bool
        let result: CLIJSONValue?
        let error: CLIErrorObject?
        /// The failure as thrown, so one request reports exactly as `generate` would.
        var cause: (any Error)? = nil

        private enum CodingKeys: String, CodingKey { case index, clientRequestID, ok, replayed, result, error }

        /// Every key is present; an absent value is null, as in the envelope.
        func encode(to encoder: any Encoder) throws {
            var container = encoder.container(keyedBy: CodingKeys.self)
            try container.encode(index, forKey: .index)
            if let clientRequestID {
                try container.encode(clientRequestID, forKey: .clientRequestID)
            } else {
                try container.encodeNil(forKey: .clientRequestID)
            }
            try container.encode(ok, forKey: .ok)
            try container.encode(replayed, forKey: .replayed)
            try container.encode(result ?? .null, forKey: .result)
            if let error { try container.encode(error, forKey: .error) } else { try container.encodeNil(forKey: .error) }
        }
    }

    struct Rows: Encodable, Sendable {
        let requests: Int
        let succeeded: Int
        let failed: Int
        let results: [Row]

        init(_ rows: [Row]) {
            requests = rows.count
            failed = rows.filter { !$0.ok }.count
            succeeded = rows.count - failed
            results = rows
        }
    }

    /// How a run of requests ended.
    struct Outcome: Sendable {
        /// One row per request, in order; a stopped run marks the rest cancelled.
        let rows: [Row]
        /// The signal that stopped the run.
        let stopped: Bool
    }

    @MainActor
    public static func run(_ args: Args) async throws {
        let single = args.string("request")
        let many = args.string("requests")
        guard (single == nil) != (many == nil) else {
            throw CLIError(.usageError, "pass exactly one of --request <file|-> or --requests <file|->")
        }
        let documents = try readDocuments(from: single ?? many ?? "", single: single != nil)

        // Global options of this invocation apply to every request.
        var shared: [String] = []
        for name in ["data-dir", "manifest"] {
            if let value = args.string(name) { shared.append("--\(name)=\(value)") }
        }
        let ledger = CLIRequestLedger(dataDirectory: CLIPaths.dataDirectory(override: args.string("data-dir")))
        var runtime: CLIRuntime?
        let outcome = await runRequests(documents, shared: shared, ledger: ledger) { take in
            // Checked before boot, so a request whose path cannot hold its take
            // never costs an engine start (P15-09).
            try GenerateCommand.prepareOutputFolder(of: take.output.path)
            if runtime == nil {
                note("booting engine (data: \(take.dataDirectory.path))")
                CLIPresenter.event(.engineBooting)
                runtime = try await CLIRuntime.bootstrap(
                    dataDirectory: take.dataDirectory, manifestOverride: take.manifestOverride,
                    voiceCloningConsent: take.consent, hostedLikeTheApp: true,
                    concurrency: CLIEngineConcurrency(args)
                )
                CLIPresenter.event(.engineReady)
            }
            guard let runtime else { throw CLIError(.internalError, "the engine did not start") }
            return try CLIJSONValue(encoding: try await GenerateCommand.execute(take, runtime: runtime))
        }
        try report(outcome, single: single != nil)
    }

    /// The request documents: the whole input for `--request`, one per line for
    /// `--requests` (JSONL: lines end at `\n`, blank lines are skipped).
    static func readDocuments(from source: String, single: Bool) throws -> [String] {
        let text: String
        if source == "-" {
            text = readStdinText() ?? ""
        } else {
            let path = (source as NSString).expandingTildeInPath
            do { text = try String(contentsOfFile: path, encoding: .utf8) } catch {
                let code: VocelloErrorCode = FileManager.default.fileExists(atPath: path) ? .ioError : .inputFileNotFound
                throw CLIError(code, "could not read \(path): \(error.localizedDescription)")
            }
        }
        let documents: [String]
        if single {
            documents = text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? [] : [text]
        } else {
            // Only `\n` ends a line: JSON strings may hold a raw U+2028 or U+2029.
            documents = text.split(separator: "\n", omittingEmptySubsequences: true)
                .map { $0.hasSuffix("\r") ? String($0.dropLast()) : String($0) }
                .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        }
        guard !documents.isEmpty else {
            throw CLIError(.usageError, "no requests: the input is empty")
        }
        return documents
    }

    /// Runs each request through `execute` (one prepared take to its encoded
    /// result), with idempotency through `ledger`. A failure stays its request's
    /// own; a signal stops the run.
    @MainActor
    static func runRequests(
        _ documents: [String], shared: [String], ledger: CLIRequestLedger,
        execute: (GenerateCommand.PreparedTake) async throws -> CLIJSONValue
    ) async -> Outcome {
        var rows: [Row] = []
        for (index, document) in documents.enumerated() {
            if Task.isCancelled { return stopped(rows, documents: documents) }
            var clientRequestID: String?
            var reservation: CLIRequestLedger.Reservation?
            do {
                let value: CLIJSONValue
                do {
                    value = try JSONDecoder().decode(CLIJSONValue.self, from: Data(document.utf8))
                } catch {
                    throw CLIError(.invalidInput, "the request at index \(index) is not JSON")
                }
                let parsed = try CLIGenerateRequest.parse(value)
                clientRequestID = parsed.clientRequestID
                let take = try await GenerateCommand.prepare(
                    try CLIParser.args(parsed.argv + shared, for: "generate"), interactive: false
                )
                var replayed: CLIJSONValue?
                if let id = parsed.clientRequestID {
                    switch try ledger.start(id: id, request: try GenerateCommand.identity(of: take)) {
                    case .replay(let stored): replayed = stored
                    case .run(let held): reservation = held
                    }
                }
                if let replayed {
                    rows.append(Row(
                        index: index, clientRequestID: clientRequestID, ok: true, replayed: true, result: replayed,
                        error: nil
                    ))
                } else {
                    let report = try await execute(take)
                    if let held = reservation {
                        reservation = nil
                        if !ledger.complete(held, result: report) {
                            CLIPresenter.warn(
                                "idempotency_not_recorded",
                                "request \(index) succeeded but its result could not be kept: a retry with its client request id runs again",
                                detail: ["index": .integer(index)]
                            )
                        }
                    }
                    rows.append(Row(
                        index: index, clientRequestID: clientRequestID, ok: true, replayed: false, result: report,
                        error: nil
                    ))
                }
            } catch {
                if let reservation { ledger.abandon(reservation) }
                // A signal stops every request; a genuine failure that coincides
                // with it stays this request's failure. A cancellation no signal
                // caused is the engine's own stop (P15-02): this request's failure.
                let failure = CLIEngineCancellation.classify(error, commandCancelled: Task.isCancelled)
                if failure is CancellationError {
                    rows.append(Row(
                        index: index, clientRequestID: clientRequestID, ok: false, replayed: false, result: nil,
                        error: CLIErrorObject(code: .cancelled, message: "the run was stopped during this request")
                    ))
                    return stopped(rows, documents: documents)
                }
                rows.append(Row(
                    index: index, clientRequestID: clientRequestID, ok: false, replayed: false, result: nil,
                    error: CLIFailure.classify(failure), cause: failure
                ))
                if Task.isCancelled { return stopped(rows, documents: documents) }
            }
            CLIPresenter.event(.progress, data: [
                "requests": .integer(documents.count), "finished": .integer(index + 1),
            ])
        }
        return Outcome(rows: rows, stopped: false)
    }

    /// Every planned row of a stopped run: those never reached are cancelled,
    /// each with the client request id its document names, if any.
    private static func stopped(_ rows: [Row], documents: [String]) -> Outcome {
        var all = rows
        for index in rows.count ..< documents.count {
            all.append(Row(
                index: index, clientRequestID: namedClientRequestID(documents[index]), ok: false, replayed: false,
                result: nil, error: CLIErrorObject(code: .cancelled, message: "not attempted: the run was stopped")
            ))
        }
        return Outcome(rows: all, stopped: true)
    }

    private static func namedClientRequestID(_ document: String) -> String? {
        guard case .object(let fields)? = try? JSONDecoder().decode(CLIJSONValue.self, from: Data(document.utf8)),
              case .string(let id)? = fields[CLIGenerateRequest.clientRequestIDField] else { return nil }
        return id
    }

    /// Reports `outcome`: one request exactly as `generate` would, several as rows.
    @MainActor
    static func report(_ outcome: Outcome, single: Bool) throws {
        if single, let row = outcome.rows.first {
            // A genuine failure reports itself even when a signal arrived with it,
            // as `generate` does (the signal's exit status, the failure in its detail).
            if let cause = row.cause { throw cause }
            if outcome.stopped { throw CancellationError() }
            if row.replayed { CLIPresenter.markReplayed() }
            if CLIPresenter.isMachine, let result = row.result {
                CLIPresenter.succeed(result)
            } else if let path = GenerateCommand.audioPath(of: row.result) {
                print(path)
            }
            return
        }

        let summary = Rows(outcome.rows)
        if CLIPresenter.isMachine {
            if summary.failed == 0 { CLIPresenter.succeed(summary) } else { CLIPresenter.recordPartialResult(summary) }
        } else {
            for row in outcome.rows {
                if let error = row.error {
                    print("\(row.index)\tfailed\t\(error.code.rawValue)\t\(error.message)")
                } else if let path = GenerateCommand.audioPath(of: row.result) {
                    print("\(row.index)\t\(row.replayed ? "replayed" : "ok")\t\(path)")
                }
            }
        }
        if outcome.stopped { throw CancellationError() }
        if summary.failed > 0 {
            throw CLIError(
                .batchIncomplete, "\(summary.failed) of \(summary.requests) requests failed; the others completed",
                detail: ["failed": .integer(summary.failed), "requests": .integer(summary.requests)]
            )
        }
    }
}
