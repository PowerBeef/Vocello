import CryptoKit
import Foundation
@preconcurrency import VocelloQwen3Core

/// Privacy-safe description of one untracked startup-reliability artifact.
/// The local path and artifact bytes never enter telemetry or retained JSON.
public struct StartupReliabilityArtifactEvidence: Hashable, Codable, Sendable {
    public enum Kind: String, Hashable, Codable, Sendable {
        case rejectedAudio = "rejected_audio"
        case codecTrace = "codec_trace"
        case incrementalReplayAudio = "incremental_replay_audio"
        case fullReplayAudio = "full_replay_audio"
    }

    public struct CodeGroupRange: Hashable, Codable, Sendable {
        public let minimum: Int
        public let maximum: Int

        public init(minimum: Int, maximum: Int) {
            self.minimum = minimum
            self.maximum = maximum
        }
    }

    public let schemaVersion: Int
    public let kind: Kind
    public let sha256: String
    public let byteCount: Int
    public let durationSeconds: Double?
    public let codecFrameCount: Int?
    public let codeGroupRange: CodeGroupRange?
    public let codecChunkRanges: [StartupReliabilityCodecFrameRange]?
    public let complete: Bool?

    public init(
        kind: Kind,
        sha256: String,
        byteCount: Int,
        durationSeconds: Double? = nil,
        codecFrameCount: Int? = nil,
        codeGroupRange: CodeGroupRange? = nil,
        codecChunkRanges: [StartupReliabilityCodecFrameRange]? = nil,
        complete: Bool? = nil
    ) {
        self.schemaVersion = 1
        self.kind = kind
        self.sha256 = sha256
        self.byteCount = byteCount
        self.durationSeconds = durationSeconds
        self.codecFrameCount = codecFrameCount
        self.codeGroupRange = codeGroupRange
        self.codecChunkRanges = codecChunkRanges
        self.complete = complete
    }

    public var telemetryNotes: [String: String] {
        let prefix: String = switch kind {
        case .rejectedAudio: "rejectedAudio"
        case .codecTrace: "codecTrace"
        case .incrementalReplayAudio: "incrementalReplayAudio"
        case .fullReplayAudio: "fullReplayAudio"
        }
        var notes = [
            "\(prefix)SchemaVersion": String(schemaVersion),
            "\(prefix)SHA256": sha256,
            "\(prefix)ByteCount": String(byteCount),
        ]
        if let durationSeconds {
            notes["\(prefix)DurationSeconds"] = String(format: "%.6f", durationSeconds)
        }
        if let codecFrameCount {
            notes["\(prefix)FrameCount"] = String(codecFrameCount)
        }
        if let codeGroupRange {
            notes["\(prefix)CodeGroupsMinimum"] = String(codeGroupRange.minimum)
            notes["\(prefix)CodeGroupsMaximum"] = String(codeGroupRange.maximum)
        }
        if let codecChunkRanges {
            notes["\(prefix)ChunkRanges"] = codecChunkRanges
                .map { "\($0.start):\($0.endExclusive)" }
                .joined(separator: ",")
        }
        if let complete {
            notes["\(prefix)Complete"] = complete ? "true" : "false"
        }
        return notes
    }
}

/// Generation-scoped, bounded persistence for internal device/UI/CLI diagnostics.
/// Callers must additionally enforce TelemetryGate.
public enum StartupReliabilityDiagnosticEvidence {
    public static let maximumCodecFrames = 8_192

    /// The writer and pullable mirror must use one registered run identity.
    /// UI-only runs need no benchmark metadata. Conflicting or missing identities
    /// cannot fall back to a shared anonymous directory containing unrelated takes.
    public static func captureRunID(
        environment: [String: String],
        telemetryEnabled: Bool
    ) -> String? {
        guard telemetryEnabled else { return nil }
        var identity: String?
        for key in ["QVOICE_IOS_DEVICE_RUN_ID", "QVOICE_MAC_BENCH_RUN_ID"] {
            guard let raw = environment[key] else { continue }
            let value = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard isSafeIdentifier(value), value != "not-bench",
                  identity == nil || identity == value else { return nil }
            identity = value
        }
        return identity
    }

    public static func evidenceDirectory(
        appSupportDirectory: URL,
        runID: String,
        generationID: UUID
    ) throws -> URL {
        guard isSafeIdentifier(runID) else { throw EvidenceError.invalidIdentity }
        return appSupportDirectory
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent("startup-reliability-evidence", isDirectory: true)
            .appendingPathComponent(runID, isDirectory: true)
            .appendingPathComponent(generationID.uuidString, isDirectory: true)
    }

    public static func persistRejectedAudio(
        from stagedURL: URL,
        appSupportDirectory: URL,
        runID: String,
        generationID: UUID,
        durationSeconds: Double
    ) throws -> StartupReliabilityArtifactEvidence {
        let directory = try evidenceDirectory(
            appSupportDirectory: appSupportDirectory,
            runID: runID,
            generationID: generationID
        )
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let destination = directory.appendingPathComponent("rejected.wav", isDirectory: false)
        let data = try Data(contentsOf: stagedURL, options: .mappedIfSafe)
        try data.write(to: destination, options: .atomic)
        return StartupReliabilityArtifactEvidence(
            kind: .rejectedAudio,
            sha256: sha256(data),
            byteCount: data.count,
            durationSeconds: durationSeconds
        )
    }

    public static func persistCodecTrace(
        _ trace: VocelloQwen3CodecTrace,
        codecChunkRanges: [StartupReliabilityCodecFrameRange],
        appSupportDirectory: URL,
        runID: String,
        generationID: UUID
    ) throws -> StartupReliabilityArtifactEvidence {
        guard trace.frames.count <= maximumCodecFrames,
              trace.frames.allSatisfy({ !$0.isEmpty && $0.count <= 64 }) else {
            throw EvidenceError.traceOutOfBounds
        }
        try validate(ranges: codecChunkRanges, frameCount: trace.frames.count)
        let directory = try evidenceDirectory(
            appSupportDirectory: appSupportDirectory,
            runID: runID,
            generationID: generationID
        )
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let data = encode(trace)
        try data.write(
            to: directory.appendingPathComponent("codec-trace-v1.bin", isDirectory: false),
            options: .atomic
        )
        let groupCounts = trace.frames.map(\.count)
        return StartupReliabilityArtifactEvidence(
            kind: .codecTrace,
            sha256: sha256(data),
            byteCount: data.count,
            codecFrameCount: trace.frames.count,
            codeGroupRange: groupCounts.min().flatMap { minimum in
                groupCounts.max().map { maximum in
                    StartupReliabilityArtifactEvidence.CodeGroupRange(
                        minimum: minimum,
                        maximum: maximum
                    )
                }
            },
            codecChunkRanges: codecChunkRanges,
            complete: trace.isComplete
        )
    }

    public static func loadCodecTrace(
        appSupportDirectory: URL,
        runID: String,
        generationID: UUID
    ) throws -> VocelloQwen3CodecTrace {
        let directory = try evidenceDirectory(
            appSupportDirectory: appSupportDirectory,
            runID: runID,
            generationID: generationID
        )
        return try decode(Data(contentsOf: directory.appendingPathComponent("codec-trace-v1.bin")))
    }

    public static func persistReplayAudio(
        samples: [Float],
        sampleRate: Int,
        kind: StartupReliabilityArtifactEvidence.Kind,
        appSupportDirectory: URL,
        runID: String,
        generationID: UUID,
        expectedPauseCount: Int
    ) throws -> (StartupReliabilityArtifactEvidence, AudioQCReport) {
        guard kind == .incrementalReplayAudio || kind == .fullReplayAudio,
              !samples.isEmpty, sampleRate > 0 else {
            throw EvidenceError.invalidReplay
        }
        let directory = try evidenceDirectory(
            appSupportDirectory: appSupportDirectory,
            runID: runID,
            generationID: generationID
        )
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var limiter = PCM16StreamLimiter()
        var pcm: [Int16] = []
        limiter.append(samples, into: &pcm)
        let name = kind == .incrementalReplayAudio
            ? "incremental-replay.wav"
            : "full-replay.wav"
        let destination = directory.appendingPathComponent(name, isDirectory: false)
        try AtomicPCM16WAVWriter.write(
            pcmSamples: pcm,
            sampleRate: sampleRate,
            outputURL: destination
        )
        let data = try Data(contentsOf: destination, options: .mappedIfSafe)
        let report = try PersistedWAVAudioQCAnalyzer.evaluate(
            url: destination,
            expectedPauseCount: expectedPauseCount
        )
        return (
            StartupReliabilityArtifactEvidence(
                kind: kind,
                sha256: sha256(data),
                byteCount: data.count,
                durationSeconds: Double(pcm.count) / Double(sampleRate)
            ),
            report
        )
    }

    public static func encode(_ trace: VocelloQwen3CodecTrace) -> Data {
        var data = Data("VQCT".utf8)
        append(UInt32(1), to: &data)
        append(UInt32(trace.frames.count), to: &data)
        append(UInt32(max(0, trace.droppedFrameCount)), to: &data)
        for frame in trace.frames {
            append(UInt16(frame.count), to: &data)
            for code in frame { append(code, to: &data) }
        }
        return data
    }

    public static func decode(_ data: Data) throws -> VocelloQwen3CodecTrace {
        let storage = [UInt8](data)
        var cursor = 0
        func readBytes(_ count: Int) throws -> ArraySlice<UInt8> {
            guard count >= 0, cursor <= storage.count - count else {
                throw EvidenceError.corruptTrace
            }
            defer { cursor += count }
            return storage[cursor ..< cursor + count]
        }
        func readInteger<T: FixedWidthInteger>(_ type: T.Type) throws -> T {
            let bytes = try readBytes(MemoryLayout<T>.size)
            return bytes.enumerated().reduce(T.zero) { value, item in
                value | (T(item.element) << T(item.offset * 8))
            }
        }
        guard Data(try readBytes(4)) == Data("VQCT".utf8),
              try readInteger(UInt32.self) == 1 else {
            throw EvidenceError.corruptTrace
        }
        let frameCount = Int(try readInteger(UInt32.self))
        let dropped = Int(try readInteger(UInt32.self))
        guard frameCount <= maximumCodecFrames else { throw EvidenceError.traceOutOfBounds }
        var frames: [[Int32]] = []
        frames.reserveCapacity(frameCount)
        for _ in 0 ..< frameCount {
            let groupCount = Int(try readInteger(UInt16.self))
            guard (1...64).contains(groupCount) else { throw EvidenceError.traceOutOfBounds }
            var frame: [Int32] = []
            frame.reserveCapacity(groupCount)
            for _ in 0 ..< groupCount { frame.append(try readInteger(Int32.self)) }
            frames.append(frame)
        }
        guard cursor == storage.count else { throw EvidenceError.corruptTrace }
        return VocelloQwen3CodecTrace(frames: frames, droppedFrameCount: dropped)
    }

    private static func validate(
        ranges: [StartupReliabilityCodecFrameRange],
        frameCount: Int
    ) throws {
        guard !ranges.isEmpty, ranges.first?.start == 0,
              ranges.last?.endExclusive == frameCount else {
            throw EvidenceError.invalidRanges
        }
        var expected = 0
        for range in ranges {
            guard range.start == expected, range.endExclusive > range.start,
                  range.endExclusive <= frameCount else {
                throw EvidenceError.invalidRanges
            }
            expected = range.endExclusive
        }
    }

    public static func removeRun(
        appSupportDirectory: URL,
        runID: String
    ) throws {
        guard isSafeIdentifier(runID) else { throw EvidenceError.invalidIdentity }
        let url = appSupportDirectory
            .appendingPathComponent("diagnostics", isDirectory: true)
            .appendingPathComponent("startup-reliability-evidence", isDirectory: true)
            .appendingPathComponent(runID, isDirectory: true)
        try? FileManager.default.removeItem(at: url)
    }

    private static func append<T: FixedWidthInteger>(_ value: T, to data: inout Data) {
        var littleEndian = value.littleEndian
        withUnsafeBytes(of: &littleEndian) { data.append(contentsOf: $0) }
    }

    private static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static func isSafeIdentifier(_ value: String) -> Bool {
        value != "." && value != ".."
            && (1...96).contains(value.count) && value.unicodeScalars.allSatisfy {
            CharacterSet.alphanumerics.contains($0) || $0 == "." || $0 == "_" || $0 == "-"
        }
    }

    public enum EvidenceError: Error, Equatable {
        case invalidIdentity
        case traceOutOfBounds
        case corruptTrace
        case invalidRanges
        case invalidReplay
    }
}
