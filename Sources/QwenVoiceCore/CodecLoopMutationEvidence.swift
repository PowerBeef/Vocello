import CryptoKit
import Foundation
import VocelloQwen3Core

/// The bounded inputs and outputs of the diagnostic codec-loop replay
/// (`vocello bench --codec-loop`): audio QC construction COD-LOOP, tier T2 of
/// the 2026-09-25 audit (section 5.2), the class I token-loop detector's
/// positives.
///
/// A job names generated takes' recorded codec traces (codec-trace v1, the
/// binary `StartupReliabilityDiagnosticEvidence` writes) by digest, with one
/// loop recipe per item: the codec frames `startFrame ..< startFrame +
/// spanFrames` (all codebooks) are repeated `extraCopies` more times right
/// after themselves, so the talker's codebook 0 carries an exact cycle of
/// period `spanFrames`. A sham recipe (no span, no copy) leaves the trace
/// untouched. The mutated trace decodes on the replay's production
/// non-streaming 25-frame schedule and sample window (`fullAudio`), and the
/// output stands where a published take stands: the production PCM16 output
/// limiter, then (in the CLI) the publication marking.
///
/// The recipe's catalog (which variant repeats how many frames) belongs to the
/// job's author; here a recipe is only checked for shape and bounds.
public enum CodecLoopMutationEvidence {
    public static let jobKind = "audio-qc-codec-loop-job"
    public static let resultKind = "audio-qc-codec-loop-result"
    public static let injector = "COD-LOOP@1"
    public static let sampleRate = 24_000
    public static let codebookCount = 16
    /// A confirmation cohort's takes times four variants fit in one job.
    public static let maximumItems = 8_192
    public static let maximumJobBytes = 4 * 1_048_576
    public static let maximumSpanFrames = 64
    public static let maximumExtraCopies = 8
    public static let variants: Set<String> = ["sham", "mild", "moderate", "severe"]
    /// The production quality-first decoder's chunk (`fullAudio`'s schedule).
    public static let decodeChunkFrames = 25
    /// A codec-trace v1 binary of at most `maximumCodecFrames` frames of 16 codes.
    public static let maximumTraceBytes = 16
        + StartupReliabilityDiagnosticEvidence.maximumCodecFrames * (2 + codebookCount * 4)

    public struct Recipe: Codable, Equatable, Sendable {
        public let injector: String
        public let variant: String
        public let startFrame: Int
        public let spanFrames: Int
        public let extraCopies: Int

        public init(injector: String, variant: String, startFrame: Int, spanFrames: Int, extraCopies: Int) {
            self.injector = injector
            self.variant = variant
            self.startFrame = startFrame
            self.spanFrames = spanFrames
            self.extraCopies = extraCopies
        }

        /// A sham has neither span nor copy; a loop has both, within bounds.
        public var isWellFormed: Bool {
            guard injector == CodecLoopMutationEvidence.injector,
                  CodecLoopMutationEvidence.variants.contains(variant), startFrame >= 0 else {
                return false
            }
            if variant == "sham" {
                return spanFrames == 0 && extraCopies == 0
            }
            return (1 ... CodecLoopMutationEvidence.maximumSpanFrames).contains(spanFrames)
                && (1 ... CodecLoopMutationEvidence.maximumExtraCopies).contains(extraCopies)
        }
    }

    public struct Item: Codable, Equatable, Sendable {
        public let id: String
        public let tracePath: String
        public let traceSHA256: String
        public let recipe: Recipe

        public init(id: String, tracePath: String, traceSHA256: String, recipe: Recipe) {
            self.id = id
            self.tracePath = tracePath
            self.traceSHA256 = traceSHA256
            self.recipe = recipe
        }
    }

    public struct Job: Equatable, Sendable {
        public let items: [Item]
        /// The speech tokenizer the source takes were generated with, when the
        /// builder could read it from their engine rows; the replay refuses to
        /// decode on another.
        public let tokenizerSHA256: String?
    }

    /// One written output: the file's digest and what the limiter did.
    public struct OutputEvidence: Codable, Equatable, Sendable {
        public let sha256: String
        public let byteCount: Int
        public let sampleCount: Int
        /// Samples the production limiter found above its ceiling.
        public let samplesAboveCeiling: Int
    }

    public enum EvidenceError: Error, Equatable {
        case invalidJob
        case invalidItem
        case duplicateItem
        case inputOutOfBounds
        case digestMismatch
        case invalidTrace
        case invalidRecipe
        case invalidOutput
    }

    private struct JobFile: Decodable {
        let schemaVersion: Int
        let kind: String
        let sampleRate: Int
        let tokenizerSHA256: String?
        let items: [Item]
    }

    /// A schema-1 job of 1...`maximumItems` items with safe, case-insensitively
    /// unique ids (each names `<id>.wav` and `<id>.codes.bin` in the output),
    /// relative trace paths, SHA-256 digests and well-formed recipes.
    public static func decodeJob(_ data: Data) throws -> Job {
        guard data.count <= maximumJobBytes else { throw EvidenceError.inputOutOfBounds }
        let job: JobFile
        do {
            job = try JSONDecoder().decode(JobFile.self, from: data)
        } catch {
            throw EvidenceError.invalidJob
        }
        guard job.schemaVersion == 1, job.kind == jobKind, job.sampleRate == sampleRate,
              !job.items.isEmpty, job.items.count <= maximumItems,
              job.tokenizerSHA256.map(CodecRoundTripEvidence.isSHA256) ?? true else {
            throw EvidenceError.invalidJob
        }
        var seen: Set<String> = []
        for item in job.items {
            guard CodecRoundTripEvidence.isSafeIdentifier(item.id),
                  CodecRoundTripEvidence.isSafeRelativePath(item.tracePath),
                  CodecRoundTripEvidence.isSHA256(item.traceSHA256) else {
                throw EvidenceError.invalidItem
            }
            guard item.recipe.isWellFormed else { throw EvidenceError.invalidRecipe }
            guard seen.insert(item.id.lowercased()).inserted else {
                throw EvidenceError.duplicateItem
            }
        }
        return Job(items: job.items, tokenizerSHA256: job.tokenizerSHA256)
    }

    /// The item's trace under the job's directory; a symbolic link out of it
    /// is refused.
    public static func traceURL(for item: Item, jobDirectory: URL) throws -> URL {
        do {
            return try CodecRoundTripEvidence.inputURL(
                for: CodecRoundTripEvidence.Item(id: item.id, wavPath: item.tracePath, wavSHA256: item.traceSHA256),
                jobDirectory: jobDirectory
            )
        } catch {
            throw EvidenceError.invalidItem
        }
    }

    /// Reads at most `maximumTraceBytes` of one trace.
    public static func readBoundedTrace(at url: URL) throws -> Data {
        guard let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize,
              size <= maximumTraceBytes else {
            throw EvidenceError.inputOutOfBounds
        }
        let data = try Data(contentsOf: url)
        guard data.count <= maximumTraceBytes else { throw EvidenceError.inputOutOfBounds }
        return data
    }

    /// Binds the exact bytes to the job's digest before parsing them, then
    /// requires a complete trace of whole 16-code frames inside each codebook
    /// (the replay's bounds).
    public static func verifiedFrames(_ data: Data, expectedSHA256: String) throws -> [[Int32]] {
        guard data.count <= maximumTraceBytes else { throw EvidenceError.inputOutOfBounds }
        guard sha256(data) == expectedSHA256 else { throw EvidenceError.digestMismatch }
        let trace: VocelloQwen3CodecTrace
        do {
            trace = try StartupReliabilityDiagnosticEvidence.decode(data)
        } catch {
            throw EvidenceError.invalidTrace
        }
        guard trace.droppedFrameCount == 0, validFrames(trace.frames) else {
            throw EvidenceError.invalidTrace
        }
        return trace.frames
    }

    /// The recipe applied to the frames: the span, then `extraCopies` more
    /// copies of it, then the rest. A sham returns the frames unchanged.
    public static func mutated(_ frames: [[Int32]], by recipe: Recipe) throws -> [[Int32]] {
        guard recipe.isWellFormed, recipe.startFrame + recipe.spanFrames <= frames.count else {
            throw EvidenceError.invalidRecipe
        }
        let end = recipe.startFrame + recipe.spanFrames
        let span = frames[recipe.startFrame ..< end]
        var output = Array(frames[..<end])
        output.reserveCapacity(frames.count + recipe.spanFrames * recipe.extraCopies)
        for _ in 0 ..< recipe.extraCopies {
            output.append(contentsOf: span)
        }
        output.append(contentsOf: frames[end...])
        guard output.count <= StartupReliabilityDiagnosticEvidence.maximumCodecFrames else {
            throw EvidenceError.invalidRecipe
        }
        return output
    }

    /// The frames as the codec-trace v1 binary (complete, no dropped frame).
    public static func traceData(_ frames: [[Int32]]) throws -> Data {
        guard validFrames(frames) else { throw EvidenceError.invalidTrace }
        return StartupReliabilityDiagnosticEvidence.encode(
            VocelloQwen3CodecTrace(frames: frames, droppedFrameCount: 0)
        )
    }

    /// Contiguous `decodeChunkFrames` ranges over the whole trace: the full
    /// arm's schedule, handed to both replay arms.
    public static func decodeRanges(frameCount: Int) -> [StartupReliabilityCodecFrameRange] {
        stride(from: 0, to: max(0, frameCount), by: decodeChunkFrames).map {
            StartupReliabilityCodecFrameRange(start: $0, endExclusive: min(frameCount, $0 + decodeChunkFrames))
        }
    }

    /// Writes the decoded Float PCM through the production PCM16 output
    /// limiter, atomically, and returns the digest of the written bytes.
    public static func writeLimitedWAV(samples: [Float], sampleRate: Int, to url: URL) throws -> OutputEvidence {
        guard sampleRate == Self.sampleRate, !samples.isEmpty, samples.allSatisfy(\.isFinite) else {
            throw EvidenceError.invalidOutput
        }
        var limiter = PCM16StreamLimiter()
        var pcm: [Int16] = []
        pcm.reserveCapacity(samples.count)
        limiter.append(samples, into: &pcm)
        guard pcm.count == samples.count else { throw EvidenceError.invalidOutput }
        try AtomicPCM16WAVWriter.write(pcmSamples: pcm, sampleRate: sampleRate, outputURL: url)
        let data = try Data(contentsOf: url)
        return OutputEvidence(
            sha256: sha256(data), byteCount: data.count, sampleCount: pcm.count,
            samplesAboveCeiling: limiter.metrics.samplesAboveCeiling
        )
    }

    public static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }

    private static func validFrames(_ frames: [[Int32]]) -> Bool {
        !frames.isEmpty && frames.count <= StartupReliabilityDiagnosticEvidence.maximumCodecFrames
            && frames.allSatisfy { frame in
                frame.count == codebookCount && frame.enumerated().allSatisfy {
                    $0.element >= 0 && $0.element < ($0.offset == 0 ? 4_096 : 2_048)
                }
            }
    }
}
