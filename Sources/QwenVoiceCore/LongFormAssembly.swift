import AVFoundation
import CryptoKit
import Foundation
import VocelloQwen3Core

public enum LongFormAssemblyError: Error, Equatable, Sendable {
    case noSegments
    case invalidConfiguration(String)
    case invalidAudioFormat(segmentID: String)
    case emptyOrSilentSegment(segmentID: String)
    case duplicateSegmentID(String)
    case unreadablePublishedOutput
}

public struct LongFormAssemblyConfiguration: Codable, Equatable, Sendable {
    public static let currentAlgorithmVersion = 1

    public let algorithmVersion: Int
    public let sampleRate: Int
    public let blockFrames: Int
    public let silenceThreshold: Int16
    public let maximumTrimMillisecondsPerEdge: Int
    public let maximumFadeMillisecondsPerEdge: Int
    public let targetRMS: Double
    public let minimumGain: Double
    public let maximumGain: Double

    public init(
        algorithmVersion: Int = Self.currentAlgorithmVersion,
        sampleRate: Int = 24_000,
        blockFrames: Int = 4_096,
        silenceThreshold: Int16 = 192,
        maximumTrimMillisecondsPerEdge: Int = 500,
        maximumFadeMillisecondsPerEdge: Int = 10,
        targetRMS: Double = 0.10,
        minimumGain: Double = 0.75,
        maximumGain: Double = 1.25
    ) {
        self.algorithmVersion = algorithmVersion
        self.sampleRate = sampleRate
        self.blockFrames = blockFrames
        self.silenceThreshold = silenceThreshold
        self.maximumTrimMillisecondsPerEdge = maximumTrimMillisecondsPerEdge
        self.maximumFadeMillisecondsPerEdge = maximumFadeMillisecondsPerEdge
        self.targetRMS = targetRMS
        self.minimumGain = minimumGain
        self.maximumGain = maximumGain
    }

    fileprivate func validated() throws -> Self {
        guard algorithmVersion == Self.currentAlgorithmVersion else {
            throw LongFormAssemblyError.invalidConfiguration("algorithmVersion")
        }
        guard sampleRate > 0, blockFrames > 0 else {
            throw LongFormAssemblyError.invalidConfiguration("sampleRateOrBlockFrames")
        }
        guard silenceThreshold >= 0,
              maximumTrimMillisecondsPerEdge >= 0,
              maximumFadeMillisecondsPerEdge >= 0 else {
            throw LongFormAssemblyError.invalidConfiguration("silenceOrEdgeDuration")
        }
        guard targetRMS.isFinite, targetRMS > 0, targetRMS <= 1,
              minimumGain.isFinite, maximumGain.isFinite,
              minimumGain > 0, maximumGain >= minimumGain else {
            throw LongFormAssemblyError.invalidConfiguration("gain")
        }
        return self
    }
}

/// Private, in-process input to the bounded assembler. Paths are deliberately
/// absent from `LongFormAssemblyEvidence` so local project locations cannot
/// leak into tracked telemetry or benchmark history.
public struct LongFormAssemblySegmentSource: Sendable {
    public let segmentID: String
    public let lineage: LongFormRevisionLineage
    public let audioURL: URL
    public let boundary: LongFormBoundaryKind
    public let intendedPauseMilliseconds: Int

    public var revision: Int { lineage.revision }

    public init(
        segmentID: String,
        lineage: LongFormRevisionLineage = LongFormRevisionLineage(),
        audioURL: URL,
        boundary: LongFormBoundaryKind,
        intendedPauseMilliseconds: Int? = nil
    ) {
        self.segmentID = segmentID
        self.lineage = lineage
        self.audioURL = audioURL
        self.boundary = boundary
        self.intendedPauseMilliseconds = intendedPauseMilliseconds
            ?? boundary.intendedPauseMilliseconds
    }
}

public struct LongFormOutputFrameRange: Codable, Equatable, Hashable, Sendable {
    public let lowerBound: Int64
    public let upperBound: Int64

    public init(lowerBound: Int64, upperBound: Int64) {
        self.lowerBound = lowerBound
        self.upperBound = upperBound
    }

    public var count: Int64 { upperBound - lowerBound }
}

public struct LongFormSegmentOutputFrameMap: Codable, Equatable, Sendable {
    public let segmentID: String
    public let lineage: LongFormRevisionLineage
    public let boundary: LongFormBoundaryKind
    public let sourceFrameCount: Int64
    public let trimmedLeadingFrames: Int64
    public let trimmedTrailingFrames: Int64
    public let contentOutputRange: LongFormOutputFrameRange
    public let insertedPauseOutputRange: LongFormOutputFrameRange
    public let sourceRMS: Double
    public let appliedGain: Double
    public let verifiedNonSpeechFadeInFrames: Int
    public let verifiedNonSpeechFadeOutFrames: Int
}

public struct LongFormAssemblyEvidence: Codable, Equatable, Sendable {
    public static let currentSchemaVersion = 1

    /// Advisory ceiling for `maximumSegmentBoundaryJump`, in PCM16 amplitude
    /// units (~12.5% of full scale). Edge-trimmed, fade-managed joins should
    /// stay well below it; a larger adjacent-sample step at a boundary is an
    /// audible click. Warn-first: a breach records `advisoryWarnings` in the
    /// manifest and never fails a run, until a measured distribution across
    /// real projects justifies a hard threshold.
    public static let advisoryMaximumSegmentBoundaryJump = 4_096

    public let schemaVersion: Int
    public let algorithmVersion: Int
    public let sampleRate: Int
    public let blockFrames: Int
    public let segmentCount: Int
    public let outputFrameCount: Int64
    /// Deterministic upper bound for the simultaneous source, transformed,
    /// and reusable writer PCM blocks. This is a structural bound, not a
    /// claim that process memory was sampled by the assembler.
    public let workingSetFrameUpperBound: Int
    public let outputDigest: String
    public let outputReadable: Bool
    public let maximumSegmentBoundaryJump: Int
    /// Warn-first advisory verdicts recorded by the assembler (absent in
    /// pre-advisory manifests and for clean joins). Currently the only token
    /// is `boundary_jump:<value>` when the maximum boundary jump exceeds the
    /// advisory ceiling.
    public let advisoryWarnings: [String]?
    public let segments: [LongFormSegmentOutputFrameMap]

    public var exceedsAdvisoryBoundaryJump: Bool {
        maximumSegmentBoundaryJump > Self.advisoryMaximumSegmentBoundaryJump
    }

    static func advisoryWarnings(maximumSegmentBoundaryJump: Int) -> [String]? {
        maximumSegmentBoundaryJump > advisoryMaximumSegmentBoundaryJump
            ? ["boundary_jump:\(maximumSegmentBoundaryJump)"]
            : nil
    }

    /// Typed `longFormContinuity` gate for the quality registry (Stage 3),
    /// derived deterministically from this assembly's recorded evidence.
    /// Warn-first, matching the advisory contract above: a boundary-jump
    /// breach is a `.warning`, never a `.fail`, until a measured distribution
    /// across real projects justifies a hard threshold. The joined output's
    /// digest is the gate evidence.
    public func longFormContinuityGateResult() -> GenerationQualityGateResult {
        GenerationQualityGateResult(
            gate: .longFormContinuity,
            outcome: exceedsAdvisoryBoundaryJump ? .warning : .pass,
            algorithmVersion: algorithmVersion,
            evidenceDigest: outputDigest,
            measurements: [
                GenerationQualityMeasurement(
                    key: .boundaryDiscontinuity,
                    value: Double(maximumSegmentBoundaryJump)
                ),
            ]
        )
    }
}

/// Manifest-v4 assembly, consumed by both shipping long-form runners. It
/// performs two bounded passes per source segment: one for edge/RMS analysis
/// and one for incremental output.
public enum BoundedLongFormAssembler {
    public static func assemble(
        segments: [LongFormAssemblySegmentSource],
        outputURL: URL,
        configuration: LongFormAssemblyConfiguration = LongFormAssemblyConfiguration(),
        provenanceModelID: String? = nil,
        provenanceMode: String? = nil
    ) async throws -> LongFormAssemblyEvidence {
        try Task.checkCancellation()
        let configuration = try configuration.validated()
        guard !segments.isEmpty else { throw LongFormAssemblyError.noSegments }
        guard Set(segments.map(\.segmentID)).count == segments.count else {
            let duplicate = Dictionary(grouping: segments, by: \.segmentID)
                .first(where: { $0.value.count > 1 })?.key ?? "duplicate"
            throw LongFormAssemblyError.duplicateSegmentID(duplicate)
        }

        try FileManager.default.createDirectory(
            at: outputURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        let writer = try IncrementalPCM16WAVFileWriter(
            sampleRate: configuration.sampleRate,
            outputURL: outputURL
        )
        var maps: [LongFormSegmentOutputFrameMap] = []
        maps.reserveCapacity(segments.count)
        var outputFramePosition: Int64 = 0
        var previousLastFrame: Int16?
        var maximumSegmentBoundaryJump = 0

        do {
            for (index, segment) in segments.enumerated() {
                try Task.checkCancellation()
                let analysis = try analyze(
                    segment: segment,
                    configuration: configuration
                )
                let contentStart = outputFramePosition
                let written = try write(
                    segment: segment,
                    analysis: analysis,
                    configuration: configuration,
                    writer: writer,
                    previousLastFrame: &previousLastFrame,
                    maximumSegmentBoundaryJump: &maximumSegmentBoundaryJump
                )
                outputFramePosition += written

                let pauseFrames: Int
                if index == segments.indices.last {
                    pauseFrames = 0
                } else {
                    pauseFrames = max(
                        0,
                        Int(
                            (Double(configuration.sampleRate)
                                * Double(segment.intendedPauseMilliseconds)
                                / 1_000.0).rounded()
                        )
                    )
                }
                let pauseStart = outputFramePosition
                try writeSilence(
                    frameCount: pauseFrames,
                    blockFrames: configuration.blockFrames,
                    writer: writer
                )
                outputFramePosition += Int64(pauseFrames)
                if pauseFrames > 0 { previousLastFrame = 0 }

                maps.append(
                    LongFormSegmentOutputFrameMap(
                        segmentID: segment.segmentID,
                        lineage: segment.lineage,
                        boundary: segment.boundary,
                        sourceFrameCount: analysis.sourceFrameCount,
                        trimmedLeadingFrames: analysis.contentStart,
                        trimmedTrailingFrames: analysis.sourceFrameCount - analysis.contentEnd,
                        contentOutputRange: LongFormOutputFrameRange(
                            lowerBound: contentStart,
                            upperBound: pauseStart
                        ),
                        insertedPauseOutputRange: LongFormOutputFrameRange(
                            lowerBound: pauseStart,
                            upperBound: outputFramePosition
                        ),
                        sourceRMS: analysis.rms,
                        appliedGain: analysis.gain,
                        verifiedNonSpeechFadeInFrames: analysis.fadeInFrames,
                        verifiedNonSpeechFadeOutFrames: analysis.fadeOutFrames
                    )
                )
            }

            try Task.checkCancellation()
            let stagingURL = try writer.finishStaging()
            // Article 50 provenance on the joined output (CP-2): the PCM is
            // already watermarked — every segment was marked at its own
            // publication — so the join needs only the machine-readable
            // provenance chunk before atomic publication. Re-embedding here
            // would stack watermark deltas for no detection gain.
            if let provenanceModelID, let provenanceMode,
               AudioMarkingPolicy.resolvedEnabled() {
                try WAVProvenanceChunk.append(
                    toWAVAt: stagingURL,
                    software: WAVProvenanceChunk.generatorSoftware(),
                    comment: WAVProvenanceChunk.comment(
                        modelID: provenanceModelID,
                        mode: provenanceMode,
                        createdAt: Date(),
                        watermarkPayload: VocelloQwen3AudioMarking.payload
                    )
                )
            }
            try writer.publish()
        } catch {
            writer.discard()
            throw error
        }

        do {
            try Task.checkCancellation()
        } catch {
            // Publication is the terminal commit point. Cancellation observed
            // after it cannot turn a readable atomic result into an error.
        }
        guard let published = try? AVAudioFile(forReading: outputURL),
              Int(published.fileFormat.sampleRate.rounded()) == configuration.sampleRate,
              published.length == outputFramePosition else {
            throw LongFormAssemblyError.unreadablePublishedOutput
        }

        return LongFormAssemblyEvidence(
            schemaVersion: LongFormAssemblyEvidence.currentSchemaVersion,
            algorithmVersion: configuration.algorithmVersion,
            sampleRate: configuration.sampleRate,
            blockFrames: configuration.blockFrames,
            segmentCount: maps.count,
            outputFrameCount: outputFramePosition,
            workingSetFrameUpperBound: configuration.blockFrames * 3,
            outputDigest: try digestFile(at: outputURL, blockBytes: configuration.blockFrames * 2),
            outputReadable: true,
            maximumSegmentBoundaryJump: maximumSegmentBoundaryJump,
            advisoryWarnings: LongFormAssemblyEvidence.advisoryWarnings(
                maximumSegmentBoundaryJump: maximumSegmentBoundaryJump
            ),
            segments: maps
        )
    }
}

private extension BoundedLongFormAssembler {
    struct SegmentAnalysis {
        let sourceFrameCount: Int64
        let contentStart: Int64
        let contentEnd: Int64
        let rms: Double
        let gain: Double
        let fadeInFrames: Int
        let fadeOutFrames: Int
    }

    static func openReader(
        for segment: LongFormAssemblySegmentSource,
        configuration: LongFormAssemblyConfiguration
    ) throws -> AVAudioFile {
        let file = try AVAudioFile(
            forReading: segment.audioURL,
            commonFormat: .pcmFormatInt16,
            interleaved: false
        )
        guard file.processingFormat.channelCount == 1,
              Int(file.processingFormat.sampleRate.rounded()) == configuration.sampleRate,
              file.length > 0 else {
            throw LongFormAssemblyError.invalidAudioFormat(segmentID: segment.segmentID)
        }
        return file
    }

    static func analyze(
        segment: LongFormAssemblySegmentSource,
        configuration: LongFormAssemblyConfiguration
    ) throws -> SegmentAnalysis {
        let file = try openReader(for: segment, configuration: configuration)
        let capacity = AVAudioFrameCount(configuration.blockFrames)
        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: file.processingFormat,
            frameCapacity: capacity
        ) else {
            throw LongFormAssemblyError.invalidAudioFormat(segmentID: segment.segmentID)
        }
        var absoluteFrame: Int64 = 0
        var firstAudible: Int64?
        var lastAudibleExclusive: Int64?
        var audibleSquareSum = 0.0
        var audibleCount = 0
        let threshold = Int(configuration.silenceThreshold)

        while absoluteFrame < file.length {
            try Task.checkCancellation()
            let request = AVAudioFrameCount(
                min(Int64(configuration.blockFrames), file.length - absoluteFrame)
            )
            buffer.frameLength = 0
            try file.read(into: buffer, frameCount: request)
            guard let samples = buffer.int16ChannelData?[0], buffer.frameLength > 0 else {
                throw LongFormAssemblyError.invalidAudioFormat(segmentID: segment.segmentID)
            }
            for offset in 0..<Int(buffer.frameLength) {
                let value = Int(samples[offset])
                if abs(value) > threshold {
                    let position = absoluteFrame + Int64(offset)
                    if firstAudible == nil { firstAudible = position }
                    lastAudibleExclusive = position + 1
                    let normalized = Double(value) / Double(Int16.max)
                    audibleSquareSum += normalized * normalized
                    audibleCount += 1
                }
            }
            absoluteFrame += Int64(buffer.frameLength)
        }

        guard let firstAudible, let lastAudibleExclusive, audibleCount > 0 else {
            throw LongFormAssemblyError.emptyOrSilentSegment(segmentID: segment.segmentID)
        }
        let maximumTrimFrames = Int64(
            (Double(configuration.sampleRate)
                * Double(configuration.maximumTrimMillisecondsPerEdge)
                / 1_000.0).rounded()
        )
        let contentStart = min(firstAudible, maximumTrimFrames)
        let trailingSilence = file.length - lastAudibleExclusive
        let contentEnd = file.length - min(trailingSilence, maximumTrimFrames)
        let rms = sqrt(audibleSquareSum / Double(audibleCount))
        let unclampedGain = configuration.targetRMS / max(rms, Double.leastNonzeroMagnitude)
        let gain = min(configuration.maximumGain, max(configuration.minimumGain, unclampedGain))

        let remainingLeadingSilence = max(0, firstAudible - contentStart)
        let remainingTrailingSilence = max(0, contentEnd - lastAudibleExclusive)
        let maximumFadeFrames = Int(
            (Double(configuration.sampleRate)
                * Double(configuration.maximumFadeMillisecondsPerEdge)
                / 1_000.0).rounded()
        )
        return SegmentAnalysis(
            sourceFrameCount: file.length,
            contentStart: contentStart,
            contentEnd: contentEnd,
            rms: rms,
            gain: gain,
            fadeInFrames: min(maximumFadeFrames, Int(remainingLeadingSilence)),
            fadeOutFrames: min(maximumFadeFrames, Int(remainingTrailingSilence))
        )
    }

    static func write(
        segment: LongFormAssemblySegmentSource,
        analysis: SegmentAnalysis,
        configuration: LongFormAssemblyConfiguration,
        writer: IncrementalPCM16WAVFileWriter,
        previousLastFrame: inout Int16?,
        maximumSegmentBoundaryJump: inout Int
    ) throws -> Int64 {
        let file = try openReader(for: segment, configuration: configuration)
        file.framePosition = analysis.contentStart
        let contentFrames = analysis.contentEnd - analysis.contentStart
        let capacity = AVAudioFrameCount(configuration.blockFrames)
        guard let buffer = AVAudioPCMBuffer(
            pcmFormat: file.processingFormat,
            frameCapacity: capacity
        ) else {
            throw LongFormAssemblyError.invalidAudioFormat(segmentID: segment.segmentID)
        }
        var sourceOffset: Int64 = 0
        var isFirstOutputBlock = true

        while sourceOffset < contentFrames {
            try Task.checkCancellation()
            let request = AVAudioFrameCount(
                min(Int64(configuration.blockFrames), contentFrames - sourceOffset)
            )
            buffer.frameLength = 0
            try file.read(into: buffer, frameCount: request)
            guard let source = buffer.int16ChannelData?[0], buffer.frameLength > 0 else {
                throw LongFormAssemblyError.invalidAudioFormat(segmentID: segment.segmentID)
            }

            var output = [Int16]()
            output.reserveCapacity(Int(buffer.frameLength))
            for index in 0..<Int(buffer.frameLength) {
                let absoluteContentOffset = sourceOffset + Int64(index)
                var scale = analysis.gain
                if analysis.fadeInFrames > 0,
                   absoluteContentOffset < Int64(analysis.fadeInFrames) {
                    // Analysis proved this interval is non-speech. No audible
                    // sample is ever attenuated merely to hide a discontinuity.
                    scale *= Double(absoluteContentOffset + 1)
                        / Double(analysis.fadeInFrames)
                }
                let trailingOffset = contentFrames - absoluteContentOffset - 1
                if analysis.fadeOutFrames > 0,
                   trailingOffset < Int64(analysis.fadeOutFrames) {
                    scale *= Double(trailingOffset + 1)
                        / Double(analysis.fadeOutFrames)
                }
                let scaled = (Double(source[index]) * scale).rounded()
                output.append(
                    Int16(
                        min(
                            Double(Int16.max),
                            max(Double(Int16.min), scaled)
                        )
                    )
                )
            }

            if isFirstOutputBlock,
               let first = output.first,
               let previousLastFrame {
                maximumSegmentBoundaryJump = max(
                    maximumSegmentBoundaryJump,
                    abs(Int(first) - Int(previousLastFrame))
                )
            }
            try writer.append(pcmSamples: output)
            previousLastFrame = output.last
            sourceOffset += Int64(buffer.frameLength)
            isFirstOutputBlock = false
        }
        return contentFrames
    }

    static func writeSilence(
        frameCount: Int,
        blockFrames: Int,
        writer: IncrementalPCM16WAVFileWriter
    ) throws {
        var remaining = frameCount
        while remaining > 0 {
            try Task.checkCancellation()
            let count = min(blockFrames, remaining)
            try writer.append(pcmSamples: [Int16](repeating: 0, count: count))
            remaining -= count
        }
    }

    static func digestFile(at url: URL, blockBytes: Int) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hasher = SHA256()
        while true {
            let data = try handle.read(upToCount: max(1, blockBytes)) ?? Data()
            if data.isEmpty { break }
            hasher.update(data: data)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }
}
