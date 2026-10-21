import Foundation
import QwenVoiceCore
import VocelloCLICore

/// `vocello run`: generation requests as JSON (RF-27), for agents. One request
/// reports exactly as `generate` does; JSONL requests run one after another on
/// one warm engine, each independent of the others' failures, and the result
/// lists every request.
enum RunCommand {
    struct Row: Encodable, Sendable {
        let index: Int
        let clientRequestID: String?
        let ok: Bool
        let replayed: Bool
        let result: CLIJSONValue?
        let error: CLIErrorObject?

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
    }

    @MainActor
    static func run(_ args: Args) async throws {
        let single = args.string("request")
        let many = args.string("requests")
        guard (single == nil) != (many == nil) else {
            throw CLIError(.usageError, "pass exactly one of --request <file|-> or --requests <file|->")
        }
        let source = single ?? many ?? ""
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
        if single != nil {
            documents = [text]
        } else {
            documents = text.split(whereSeparator: \.isNewline).map(String.init)
                .filter { !$0.trimmingCharacters(in: .whitespaces).isEmpty }
        }
        guard !documents.isEmpty else {
            throw CLIError(.usageError, "no requests: the input is empty")
        }

        // Global options of this invocation apply to every request.
        var shared: [String] = []
        for name in ["data-dir", "manifest"] {
            if let value = args.string(name) { shared.append("--\(name)=\(value)") }
        }
        let dataDirectory = CLIPaths.dataDirectory(override: args.string("data-dir"))
        let ledger = CLIRequestLedger(dataDirectory: dataDirectory)
        var runtime: CLIRuntime?
        var rows: [Row] = []

        for (index, document) in documents.enumerated() {
            try Task.checkCancellation()
            var clientRequestID: String?
            var reservation: CLIRequestLedger.Reservation?
            do {
                let value: CLIJSONValue
                do {
                    value = try JSONDecoder().decode(CLIJSONValue.self, from: Data(document.utf8))
                } catch {
                    throw CLIError(.invalidInput, "request \(index + 1) is not JSON")
                }
                let parsed = try CLIGenerateRequest.parse(value)
                clientRequestID = parsed.clientRequestID
                let requestArgs = try CLIParser.args(parsed.argv + shared, for: "generate")
                let take = try await GenerateCommand.prepare(requestArgs, interactive: false)
                if let id = parsed.clientRequestID {
                    switch try ledger.claim(id: id, request: parsed.identity) {
                    case .replay(let stored):
                        rows.append(Row(index: index, clientRequestID: id, ok: true, replayed: true, result: stored, error: nil))
                        continue
                    case .conflict:
                        throw CLIError(.idempotencyConflict, "client request id '\(id)' was used for a different request")
                    case .inProgress:
                        throw CLIError(.requestInProgress, "client request id '\(id)' is running in another process")
                    case .fresh(let held):
                        reservation = held
                    }
                }
                if runtime == nil {
                    note("booting engine (data: \(take.dataDirectory.path))")
                    CLIPresenter.event(.engineBooting)
                    runtime = try await CLIRuntime.bootstrap(
                        dataDirectory: take.dataDirectory, manifestOverride: take.manifestOverride,
                        voiceCloningConsent: take.consent
                    )
                    CLIPresenter.event(.engineReady)
                }
                guard let runtime else { throw CLIError(.internalError, "the engine did not start") }
                let report = try CLIJSONValue(encoding: try await GenerateCommand.execute(take, runtime: runtime))
                if let reservation { ledger.complete(reservation, result: report) }
                rows.append(Row(index: index, clientRequestID: clientRequestID, ok: true, replayed: false, result: report, error: nil))
            } catch {
                if let reservation { ledger.abandon(reservation) }
                // A signal stops every request; any other failure is this request's alone.
                if error is CancellationError || Task.isCancelled {
                    throw error
                }
                rows.append(Row(
                    index: index, clientRequestID: clientRequestID, ok: false, replayed: false, result: nil,
                    error: CLIFailure.classify(error)
                ))
            }
            CLIPresenter.event(.progress, data: [
                "requests": .integer(documents.count), "finished": .integer(index + 1),
            ])
        }

        if single != nil, let row = rows.first {
            // One request reports exactly as generate does.
            if let error = row.error {
                throw CLIError(error.code, error.message, hint: error.hint, detail: error.detail)
            }
            if row.replayed { CLIPresenter.markReplayed() }
            if CLIPresenter.isMachine, let result = row.result {
                CLIPresenter.succeed(result)
            } else if case .object(let fields)? = row.result, case .string(let path)? = fields["audioPath"] {
                print(path)
            }
            return
        }

        let failed = rows.filter { !$0.ok }.count
        let summary = Rows(requests: rows.count, succeeded: rows.count - failed, failed: failed, results: rows)
        if CLIPresenter.isMachine {
            if failed == 0 { CLIPresenter.succeed(summary) } else { CLIPresenter.recordPartialResult(summary) }
        } else {
            for row in rows {
                if let error = row.error {
                    print("\(row.index)\tfailed\t\(error.code.rawValue)\t\(error.message)")
                } else if case .object(let fields)? = row.result, case .string(let path)? = fields["audioPath"] {
                    print("\(row.index)\t\(row.replayed ? "replayed" : "ok")\t\(path)")
                }
            }
        }
        if failed > 0 {
            throw CLIError(
                .batchIncomplete, "\(failed) of \(rows.count) requests failed; the others completed",
                detail: ["failed": .integer(failed), "requests": .integer(rows.count)]
            )
        }
    }
}
