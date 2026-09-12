import Foundation
@preconcurrency import VocelloQwen3Core

enum AtomicWAVGenerationOutputSinkError: Error, Equatable, Sendable {
    case invalidAudioFormat
    case generationIdentityMismatch
    case nonContiguousSequence(expected: Int, actual: Int)
    case terminalFrameCountMismatch(expected: Int, actual: Int)
    case emptyOutput
    case fastQCFailed
}

struct AtomicWAVGenerationOutputResult: Sendable {
    let outputURL: URL
    let frameCount: Int
    let sampleRate: Int
    let audioQC: AudioQCReport
}

/// Product-owned sink for the actor runtime's mandatory audio drain.
///
/// Every chunk is limited, converted, and appended to the staged WAV before a
/// limited PCM copy can reach preview. The staged file is reopened for Fast QC
/// before atomic destination publication.
final class AtomicWAVGenerationOutputSink: VocelloQwen3ProductOutputSink, Sendable {
    private actor State {
        private let outputURL: URL
        private let sampleRate: Int
        private let expectedPauseCount: Int
        private let writer: IncrementalPCM16WAVFileWriter
        private let scratch = PCM16ScratchBuffer()
        private var frameCount = 0
        private var generationID: UUID?
        private var nextSequence = 0
        private var finalized: AtomicWAVGenerationOutputResult?
        private var aborted = false

        init(
            outputURL: URL,
            sampleRate: Int,
            expectedPauseCount: Int,
            signpostCorrelation: NativeSignpostCorrelation
        ) throws {
            self.outputURL = outputURL
            self.sampleRate = sampleRate
            self.expectedPauseCount = max(0, expectedPauseCount)
            try FileManager.default.createDirectory(
                at: outputURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            writer = try IncrementalPCM16WAVFileWriter(
                sampleRate: sampleRate,
                outputURL: outputURL,
                signpostCorrelation: signpostCorrelation
            )
        }

        func consume(
            _ chunk: VocelloQwen3AudioChunkEvent
        ) throws -> VocelloQwen3PreviewAudioChunk {
            guard !aborted, finalized == nil,
                  chunk.sampleRate == sampleRate,
                  chunk.channelCount == 1,
                  chunk.frameCount > 0 else {
                throw AtomicWAVGenerationOutputSinkError.invalidAudioFormat
            }
            if let generationID {
                guard generationID == chunk.generationID else {
                    throw AtomicWAVGenerationOutputSinkError.generationIdentityMismatch
                }
            } else {
                generationID = chunk.generationID
            }
            guard chunk.sequence == nextSequence else {
                throw AtomicWAVGenerationOutputSinkError.nonContiguousSequence(
                    expected: nextSequence,
                    actual: chunk.sequence
                )
            }
            let limitedPCM = scratch.convertLimited(chunk.samples)
            try writer.append(pcmSamples: limitedPCM)
            frameCount += limitedPCM.count
            nextSequence += 1
            return VocelloQwen3PreviewAudioChunk(
                generationID: chunk.generationID,
                sequence: chunk.sequence,
                pcm16LittleEndian: scratch.pcm16LittleEndianData(from: limitedPCM),
                frameCount: limitedPCM.count,
                sampleRate: chunk.sampleRate,
                channelCount: chunk.channelCount
            )
        }

        func finalize(
            modelTerminal: VocelloQwen3TerminalEvent
        ) throws -> AtomicWAVGenerationOutputResult {
            guard !aborted, frameCount > 0 else {
                throw AtomicWAVGenerationOutputSinkError.emptyOutput
            }
            guard generationID == modelTerminal.generationID else {
                throw AtomicWAVGenerationOutputSinkError.generationIdentityMismatch
            }
            guard modelTerminal.emittedAudioFrameCount == frameCount else {
                throw AtomicWAVGenerationOutputSinkError.terminalFrameCountMismatch(
                    expected: frameCount,
                    actual: modelTerminal.emittedAudioFrameCount
                )
            }
            if let finalized { return finalized }
            let stagingURL = try writer.finishStaging()
            let report = try StreamingExecutionContext.makePersistedWAVAudioQCReport(
                at: stagingURL,
                preWriteMetrics: scratch.limiterMetrics,
                expectedPauseCount: expectedPauseCount,
                expectedSampleRate: sampleRate,
                expectedChannelCount: 1,
                expectedFrameCount: frameCount
            )
            guard report.verdict != .fail else {
                writer.discard()
                throw AtomicWAVGenerationOutputSinkError.fastQCFailed
            }
            try writer.publish()
            let value = AtomicWAVGenerationOutputResult(
                outputURL: outputURL,
                frameCount: frameCount,
                sampleRate: sampleRate,
                audioQC: report
            )
            finalized = value
            return value
        }

        func abort() {
            guard finalized == nil else { return }
            aborted = true
            writer.discard()
        }

        func result() -> AtomicWAVGenerationOutputResult? { finalized }
    }

    private let state: State

    init(
        outputURL: URL,
        sampleRate: Int,
        expectedPauseCount: Int,
        signpostCorrelation: NativeSignpostCorrelation = .unscoped
    ) throws {
        state = try State(
            outputURL: outputURL,
            sampleRate: sampleRate,
            expectedPauseCount: expectedPauseCount,
            signpostCorrelation: signpostCorrelation
        )
    }

    func consume(
        _ chunk: VocelloQwen3AudioChunkEvent
    ) async throws -> VocelloQwen3PreviewAudioChunk {
        try await state.consume(chunk)
    }

    func finalize(
        modelTerminal: VocelloQwen3TerminalEvent
    ) async throws -> VocelloQwen3ProductFinalizationDisposition {
        _ = try await state.finalize(modelTerminal: modelTerminal)
        return .published
    }

    func abort() async {
        await state.abort()
    }

    func result() async -> AtomicWAVGenerationOutputResult? {
        await state.result()
    }
}
