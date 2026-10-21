import Foundation
import Synchronization
import System

/// Every NDJSON event type v1 can write (`config/cli-contract/v1/event-types.json`).
/// Consumers ignore types they do not know.
public enum CLIEventType: String, Codable, Sendable, CaseIterable {
    case started
    case plan
    case engineBooting = "engine_booting"
    case engineReady = "engine_ready"
    case modelLoading = "model_loading"
    case modelLoaded = "model_loaded"
    case queued
    case generationStarted = "generation_started"
    case chunk
    case progress
    case downloadProgress = "download_progress"
    case qc
    case outputPublished = "output_published"
    case generationCompleted = "generation_completed"
    case generationFailed = "generation_failed"
    case generationCancelled = "generation_cancelled"
    case warning
    case log
    case result

    /// Only the newest unwritten record of these survives a busy writer: they
    /// report a running state, never a terminal one.
    var coalesces: Bool { self == .progress || self == .downloadProgress || self == .chunk }
}

/// stdout and stderr as file descriptors. SIGPIPE is ignored for the whole
/// process, so a write to a closed pipe returns `EPIPE` instead of ending it,
/// and these writes never raise (FileHandle's do).
public enum CLIStandardOutput {
    /// False only when stdout's reader is gone (EPIPE) or stdout is closed
    /// (EBADF); a busy non-blocking stdout is retried.
    public static func write(_ data: Data) -> Bool {
        write(data, to: .standardOutput)
    }

    static func write(_ data: Data, to descriptor: FileDescriptor) -> Bool {
        var remaining = data[...]
        var busyRetries = 0
        while !remaining.isEmpty {
            do {
                let written = unsafe try remaining.withUnsafeBytes { buffer in
                    unsafe try descriptor.write(buffer)
                }
                remaining = remaining.dropFirst(written)
            } catch Errno.brokenPipe, Errno.badFileDescriptor {
                return false
            } catch Errno.resourceTemporarilyUnavailable where busyRetries < 1000 {
                busyRetries += 1
                Thread.sleep(forTimeInterval: 0.001)
            } catch {
                // Any other failure loses this record but is not a closed reader.
                return true
            }
        }
        return true
    }
}

/// Human notes and errors on stderr. A closed stderr loses the note, never the process.
public enum CLIStandardError {
    public static func write(_ text: String) {
        _ = CLIStandardOutput.write(Data(text.utf8), to: .standardError)
    }
}

/// The NDJSON writer. Emitting never blocks the caller (an engine event
/// handler included): records queue under a lock and one writer thread puts
/// them on stdout. A running record (progress, chunk) replaces its unwritten
/// predecessor for the same take; terminal records are never dropped.
/// Sequence numbers count the records written, so they have no gaps.
public final class CLIEventStream: Sendable {
    struct Record: Sendable {
        let type: CLIEventType
        let generationID: String?
        var data: CLIJSONValue
        var elapsed: Double
    }

    private struct State: Sendable {
        var queue: [Record] = []
        var closing = false
        var broken = false
        /// The next record's number: a stream counts from 0.
        var seq = 0
        /// The last written `t`, which never decreases.
        var lastElapsed = 0.0
    }

    private struct Line: Encodable {
        let schemaVersion: Int
        let seq: Int
        let t: Double
        let requestID: String
        let type: CLIEventType
        let generationID: String?
        let data: CLIJSONValue

        private enum CodingKeys: String, CodingKey {
            case schemaVersion, seq, t, requestID, type, generationID, data
        }

        func encode(to encoder: any Encoder) throws {
            var container = encoder.container(keyedBy: CodingKeys.self)
            try container.encode(schemaVersion, forKey: .schemaVersion)
            try container.encode(seq, forKey: .seq)
            try container.encode(t, forKey: .t)
            try container.encode(requestID, forKey: .requestID)
            try container.encode(type, forKey: .type)
            try container.encodeIfPresent(generationID, forKey: .generationID)
            try container.encode(data, forKey: .data)
        }
    }

    /// Unwritten records allowed before running ones are dropped.
    static let queueBound = 256

    private let requestID: String
    private let started: ContinuousClock.Instant
    private let state = Mutex(State())
    private let wake = DispatchSemaphore(value: 0)
    private let drained = DispatchSemaphore(value: 0)
    private let sink: @Sendable (Data) -> Bool
    private let onBrokenOutput: @Sendable () -> Void

    public init(
        requestID: String,
        started: ContinuousClock.Instant = .now,
        sink: @escaping @Sendable (Data) -> Bool = CLIStandardOutput.write,
        onBrokenOutput: @escaping @Sendable () -> Void = {}
    ) {
        self.requestID = requestID
        self.started = started
        self.sink = sink
        self.onBrokenOutput = onBrokenOutput
        let thread = Thread { [self] in self.writeLoop() }
        thread.name = "vocello.cli.events"
        // The command may wait on it (finish), so it runs at the caller's priority.
        thread.qualityOfService = .userInitiated
        thread.start()
    }

    public func emit(_ type: CLIEventType, generationID: String? = nil, data: CLIJSONValue = .object([:])) {
        let record = Record(type: type, generationID: generationID, data: data, elapsed: elapsedSeconds())
        let accepted = state.withLock { state -> Bool in
            guard !state.closing, !state.broken else { return false }
            if type.coalesces,
               let index = state.queue.lastIndex(where: { $0.type == type && $0.generationID == generationID }) {
                state.queue[index].data = record.data
                state.queue[index].elapsed = record.elapsed
                return false
            }
            if state.queue.count >= Self.queueBound,
               let running = state.queue.firstIndex(where: { $0.type.coalesces }) {
                state.queue.remove(at: running)
            }
            state.queue.append(record)
            return true
        }
        if accepted { wake.signal() }
    }

    /// Stops the writer without a result (a superseded session); queued records are dropped.
    public func close() {
        let alreadyClosed = state.withLock { state -> Bool in
            defer { state.closing = true; state.queue.removeAll() }
            return state.closing
        }
        guard !alreadyClosed else { return }
        wake.signal()
        drained.wait()
    }

    /// Writes `envelope` as the final `result` record after every queued
    /// record, then stops the writer and waits for it.
    public func finish(result envelope: CLIEnvelope) {
        let data: CLIJSONValue
        do {
            data = try JSONDecoder().decode(CLIJSONValue.self, from: CLIJSONEncoding.encoder().encode(envelope))
        } catch {
            data = (try? JSONDecoder().decode(
                CLIJSONValue.self,
                from: CLIJSONEncoding.unencodableEnvelope(command: envelope.command, requestID: envelope.requestID)
            )) ?? .object([:])
        }
        let record = Record(type: .result, generationID: nil, data: data, elapsed: elapsedSeconds())
        let alreadyClosed = state.withLock { state -> Bool in
            guard !state.closing else { return true }
            if !state.broken { state.queue.append(record) }
            state.closing = true
            return false
        }
        guard !alreadyClosed else { return }
        wake.signal()
        drained.wait()
    }

    public var outputBroken: Bool { state.withLock { $0.broken } }

    private func elapsedSeconds() -> Double {
        let duration = started.duration(to: .now)
        let seconds = Double(duration.components.seconds) + Double(duration.components.attoseconds) / 1e18
        return (seconds * 1000).rounded() / 1000
    }

    private func writeLoop() {
        while true {
            wake.wait()
            while true {
                let next = state.withLock { state -> (Record, Int, Double)? in
                    guard !state.broken, !state.queue.isEmpty else { return nil }
                    return (state.queue.removeFirst(), state.seq, state.lastElapsed)
                }
                guard let (record, seq, lastElapsed) = next else { break }
                // A coalesced record keeps its slot but takes a newer time.
                let elapsed = max(record.elapsed, lastElapsed)
                let line = Line(
                    schemaVersion: CLIContract.schemaVersion, seq: seq, t: elapsed, requestID: requestID,
                    type: record.type, generationID: record.generationID, data: record.data
                )
                // A record that cannot be encoded takes no number, so the sequence has no gap.
                guard let encoded = try? CLIJSONEncoding.line(line) else { continue }
                state.withLock {
                    $0.seq += 1
                    $0.lastElapsed = elapsed
                }
                if !sink(encoded) {
                    let first = state.withLock { state -> Bool in
                        defer { state.broken = true; state.queue.removeAll() }
                        return !state.broken
                    }
                    if first { onBrokenOutput() }
                }
            }
            let done = state.withLock { $0.closing && ($0.queue.isEmpty || $0.broken) }
            if done {
                drained.signal()
                return
            }
        }
    }
}
