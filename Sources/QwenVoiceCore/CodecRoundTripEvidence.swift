import CryptoKit
import Foundation
import VocelloQwen3Core

/// The bounded inputs and outputs of the diagnostic codec round trip
/// (`vocello bench --codec-roundtrip`, audio QC population N2, audit P9).
///
/// A job lists mono PCM16 24 kHz WAVs by digest. Each output is written as
/// plain PCM16, deliberately without the production output limiter: QC measures
/// the limiter's own clamps (clicks, ceiling) on an engine's raw float output,
/// so an N2 file must stand where that raw output stands, as an N1 recording
/// does. A pre-limited file would hide exactly the events whose false-alarm
/// rate N2 bounds.
public enum CodecRoundTripEvidence {
    public static let jobKind = "audio-qc-n2-roundtrip-job"
    public static let sampleRate = 24_000
    public static let codebookCount = 16
    /// A cohort per job, so one model load serves it: the largest FLEURS split
    /// holds 3,718 eligible recordings, and 4,096 items stay well inside
    /// `maximumJobBytes` (about 150 bytes each).
    public static let maximumItems = 4_096
    public static let maximumJobBytes = 1_048_576
    /// One minute at 24 kHz, the facade's own input bound.
    public static let maximumInputSamples = 24_000 * 60
    public static let maximumWAVBytes = 44 + 2 * maximumInputSamples + 4_096

    public struct Item: Codable, Equatable, Sendable {
        public let id: String
        public let wavPath: String
        public let wavSHA256: String

        public init(id: String, wavPath: String, wavSHA256: String) {
            self.id = id
            self.wavPath = wavPath
            self.wavSHA256 = wavSHA256
        }
    }

    public struct OutputEvidence: Codable, Equatable, Sendable {
        public let sha256: String
        public let byteCount: Int
        public let sampleCount: Int
        /// Samples outside [-1, 1] that PCM16 had to clamp.
        public let clampedSampleCount: Int
    }

    public enum EvidenceError: Error, Equatable {
        case invalidJob
        case invalidItem
        case duplicateItem
        case inputOutOfBounds
        case digestMismatch
        case unsupportedWAV
        case invalidCodes
        case invalidOutput
    }

    private struct JobFile: Decodable {
        let schemaVersion: Int
        let kind: String
        let sampleRate: Int
        let items: [Item]
    }

    /// A schema-1 job of 1...`maximumItems` items with safe, case-insensitively
    /// unique ids (each names `<id>.wav` in the output), relative input paths
    /// and SHA-256 digests.
    public static func decodeJob(_ data: Data) throws -> [Item] {
        guard data.count <= maximumJobBytes else { throw EvidenceError.inputOutOfBounds }
        let job: JobFile
        do {
            job = try JSONDecoder().decode(JobFile.self, from: data)
        } catch {
            throw EvidenceError.invalidJob
        }
        guard job.schemaVersion == 1, job.kind == jobKind, job.sampleRate == sampleRate,
              !job.items.isEmpty, job.items.count <= maximumItems else {
            throw EvidenceError.invalidJob
        }
        var seen: Set<String> = []
        for item in job.items {
            guard isSafeIdentifier(item.id), isSafeRelativePath(item.wavPath),
                  isSHA256(item.wavSHA256) else {
                throw EvidenceError.invalidItem
            }
            guard seen.insert(item.id.lowercased()).inserted else {
                throw EvidenceError.duplicateItem
            }
        }
        return job.items
    }

    /// The item's input under the job's directory; a symbolic link out of it
    /// is refused.
    public static func inputURL(for item: Item, jobDirectory: URL) throws -> URL {
        guard isSafeRelativePath(item.wavPath) else { throw EvidenceError.invalidItem }
        let root = jobDirectory.standardizedFileURL.resolvingSymlinksInPath()
        let url = item.wavPath.split(separator: "/").reduce(root) {
            $0.appendingPathComponent(String($1), isDirectory: false)
        }.resolvingSymlinksInPath()
        guard url.path.hasPrefix(root.path + "/") else { throw EvidenceError.invalidItem }
        return url
    }

    /// Reads at most `maximumWAVBytes` of one input.
    public static func readBoundedInput(at url: URL) throws -> Data {
        guard let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize,
              size <= maximumWAVBytes else {
            throw EvidenceError.inputOutOfBounds
        }
        let data = try Data(contentsOf: url)
        guard data.count <= maximumWAVBytes else { throw EvidenceError.inputOutOfBounds }
        return data
    }

    /// Binds the exact bytes to the job's digest before parsing them, then
    /// scales PCM16 to Float at 1/32768 (Core Audio's Int16 conversion).
    public static func verifiedInputSamples(_ data: Data, expectedSHA256: String) throws -> [Float] {
        guard data.count <= maximumWAVBytes else { throw EvidenceError.inputOutOfBounds }
        guard sha256(data) == expectedSHA256 else { throw EvidenceError.digestMismatch }
        return try monoPCM16Samples(wav: data).map { Float($0) / 32_768 }
    }

    /// Strict RIFF/WAVE: one `fmt ` chunk (integer PCM, mono, 24 kHz, 16-bit)
    /// before one non-empty `data` chunk and an exact RIFF size. Other chunks
    /// are skipped; a truncated chunk, a second `fmt ` or `data`, or anything
    /// longer than `maximumInputSamples` is refused.
    public static func monoPCM16Samples(wav data: Data) throws -> [Int16] {
        let bytes = [UInt8](data)
        func uint16(_ offset: Int) -> Int { Int(bytes[offset]) | Int(bytes[offset + 1]) << 8 }
        func uint32(_ offset: Int) -> Int { uint16(offset) | uint16(offset + 2) << 16 }
        func tag(_ offset: Int) -> String { String(decoding: bytes[offset ..< offset + 4], as: UTF8.self) }
        guard bytes.count >= 12, tag(0) == "RIFF", tag(8) == "WAVE", uint32(4) + 8 == bytes.count else {
            throw EvidenceError.unsupportedWAV
        }
        var cursor = 12
        var sawFormat = false
        var samples: [Int16]?
        while cursor < bytes.count {
            guard bytes.count - cursor >= 8 else { throw EvidenceError.unsupportedWAV }
            let identifier = tag(cursor)
            let size = uint32(cursor + 4)
            let body = cursor + 8
            guard size <= bytes.count - body else { throw EvidenceError.unsupportedWAV }
            switch identifier {
            case "fmt ":
                guard !sawFormat, samples == nil, size >= 16,
                      uint16(body) == 1, uint16(body + 2) == 1,
                      uint32(body + 4) == sampleRate, uint32(body + 8) == sampleRate * 2,
                      uint16(body + 12) == 2, uint16(body + 14) == 16 else {
                    throw EvidenceError.unsupportedWAV
                }
                sawFormat = true
            case "data":
                guard sawFormat, samples == nil, size > 0, size % 2 == 0 else {
                    throw EvidenceError.unsupportedWAV
                }
                guard size / 2 <= maximumInputSamples else { throw EvidenceError.inputOutOfBounds }
                samples = stride(from: body, to: body + size, by: 2).map {
                    Int16(bitPattern: UInt16(bytes[$0]) | UInt16(bytes[$0 + 1]) << 8)
                }
            default:
                break
            }
            // RIFF chunks are word aligned: an odd-sized body carries one pad byte.
            cursor = body + size + (size & 1)
        }
        guard cursor == bytes.count, let samples else { throw EvidenceError.unsupportedWAV }
        return samples
    }

    /// The codes as the codec-trace v1 binary the replay reads, after checking
    /// they are complete: at least one frame of exactly `codebookCount` codes,
    /// each inside its codebook (the replay's bounds).
    public static func codesData(_ codes: [[Int32]]) throws -> Data {
        guard !codes.isEmpty, codes.count <= StartupReliabilityDiagnosticEvidence.maximumCodecFrames,
              codes.allSatisfy({ frame in
                  frame.count == codebookCount && frame.enumerated().allSatisfy {
                      $0.element >= 0 && $0.element < ($0.offset == 0 ? 4_096 : 2_048)
                  }
              }) else {
            throw EvidenceError.invalidCodes
        }
        return StartupReliabilityDiagnosticEvidence.encode(
            VocelloQwen3CodecTrace(frames: codes, droppedFrameCount: 0)
        )
    }

    /// Float PCM to PCM16 at x 32767 with the engine's rounding, clamping to
    /// [-1, 1] and counting what it clamped; no limiter (see the type comment).
    public static func pcm16(_ samples: [Float]) throws -> (pcm: [Int16], clamped: Int) {
        guard !samples.isEmpty, samples.allSatisfy(\.isFinite) else { throw EvidenceError.invalidOutput }
        var clamped = 0
        let pcm = samples.map { sample -> Int16 in
            if abs(sample) > 1 { clamped += 1 }
            return Int16((min(1, max(-1, sample)) * Float(Int16.max)).rounded())
        }
        return (pcm, clamped)
    }

    /// Writes one output WAV atomically and returns the digest of its bytes.
    public static func writeOutputWAV(samples: [Float], sampleRate: Int, to url: URL) throws -> OutputEvidence {
        guard sampleRate == Self.sampleRate else { throw EvidenceError.invalidOutput }
        let (pcm, clamped) = try pcm16(samples)
        try AtomicPCM16WAVWriter.write(pcmSamples: pcm, sampleRate: sampleRate, outputURL: url)
        let data = try Data(contentsOf: url)
        return OutputEvidence(sha256: sha256(data), byteCount: data.count, sampleCount: pcm.count,
                              clampedSampleCount: clamped)
    }

    public static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    /// `[A-Za-z0-9][A-Za-z0-9._-]{0,95}`.
    static func isSafeIdentifier(_ value: String) -> Bool {
        guard (1...96).contains(value.utf8.count), let first = value.unicodeScalars.first,
              isASCIIAlphanumeric(first) else {
            return false
        }
        return value.unicodeScalars.allSatisfy(isSafeScalar)
    }

    /// Relative `/`-separated components of safe characters; no empty, `.`
    /// or `..` component.
    static func isSafeRelativePath(_ value: String) -> Bool {
        guard (1...512).contains(value.utf8.count) else { return false }
        return value.split(separator: "/", omittingEmptySubsequences: false).allSatisfy { component in
            !component.isEmpty && component != "." && component != ".."
                && component.unicodeScalars.allSatisfy(isSafeScalar)
        }
    }

    private static func isASCIIAlphanumeric(_ scalar: Unicode.Scalar) -> Bool {
        switch scalar.value {
        case 0x30...0x39, 0x41...0x5A, 0x61...0x7A: true
        default: false
        }
    }

    private static func isSafeScalar(_ scalar: Unicode.Scalar) -> Bool {
        isASCIIAlphanumeric(scalar) || scalar == "." || scalar == "_" || scalar == "-"
    }

    static func isSHA256(_ value: String) -> Bool {
        value.utf8.count == 64 && value.unicodeScalars.allSatisfy { "0123456789abcdef".unicodeScalars.contains($0) }
    }
}
