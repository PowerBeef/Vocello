import Foundation
import MLX
import MLXRandom
@testable import MLXAudioTTS
import XCTest

final class Qwen3DecoderPartitionTests: XCTestCase {
    private let maxAbsoluteTolerance: Float = 1e-5
    private let rmsTolerance: Float = 1e-6

    func testFixedAndRandomizedPartitionsAreWaveformInvariant() throws {
        MLXRandom.seed(0xC0DEC0DE)
        let decoder = Qwen3TTSSpeechTokenizerDecoder(config: try tinyConfig())
        let codes = fixtureCodes(tokenCount: 300)
        let baseline = decode(decoder, codes: codes, partitions: [300], timing: false)

        for size in [1, 2, 3, 4, 12, 25, 100, 300] {
            assertWaveform(
                decode(decoder, codes: codes, partitions: repeatedPartitions(total: 300, size: size), timing: false),
                matches: baseline,
                label: "fixed partition \(size)"
            )
        }

        var generator = SeededGenerator(seed: 0x5EED)
        for index in 0..<12 {
            var remaining = 300
            var partitions: [Int] = []
            while remaining > 0 {
                let next = min(remaining, Int(generator.next() % 37) + 1)
                partitions.append(next)
                remaining -= next
            }
            assertWaveform(
                decode(decoder, codes: codes, partitions: partitions, timing: false),
                matches: baseline,
                label: "random partition \(index)"
            )
        }
    }

    func testQualityFirstDecoderUsesBoundedInvariantPartition() throws {
        XCTAssertEqual(Qwen3TTSModel.qualityFirstDecoderChunkFrames, 25)

        MLXRandom.seed(0xC0DEC0DE)
        let decoder = Qwen3TTSSpeechTokenizerDecoder(config: try tinyConfig())
        let codes = fixtureCodes(tokenCount: 300)
        let baseline = decode(decoder, codes: codes, partitions: [300], timing: false)
        let bounded = decode(
            decoder,
            codes: codes,
            partitions: repeatedPartitions(
                total: 300,
                size: Qwen3TTSModel.qualityFirstDecoderChunkFrames
            ),
            timing: false
        )

        assertWaveform(bounded, matches: baseline, label: "quality-first bounded partition")
    }

    func testResetIsolationRestoresDeterministicWaveform() throws {
        MLXRandom.seed(0xC0DEC0DE)
        let decoder = Qwen3TTSSpeechTokenizerDecoder(config: try tinyConfig())
        let firstCodes = fixtureCodes(tokenCount: 40)
        let otherCodes = fixtureCodes(tokenCount: 17, offset: 3)
        let first = decode(decoder, codes: firstCodes, partitions: [3, 7, 11, 19], timing: false)
        _ = decode(decoder, codes: otherCodes, partitions: [1, 4, 12], timing: false)
        let repeated = decode(decoder, codes: firstCodes, partitions: [3, 7, 11, 19], timing: false)
        assertWaveform(repeated, matches: first, label: "reset isolation")
    }

    func testTimingInstrumentationDoesNotChangeWaveform() throws {
        MLXRandom.seed(0xC0DEC0DE)
        let decoder = Qwen3TTSSpeechTokenizerDecoder(config: try tinyConfig())
        let codes = fixtureCodes(tokenCount: 48)
        let partitions = [1, 2, 3, 4, 12, 25, 1]
        let withoutTimings = decode(decoder, codes: codes, partitions: partitions, timing: false)
        let withTimings = decode(decoder, codes: codes, partitions: partitions, timing: true)
        assertWaveform(withTimings, matches: withoutTimings, label: "timing parity")
    }

    func testDeferredMaterializationSurvivesAllocatorCacheClear() throws {
        MLXRandom.seed(0xC0DEC0DE)
        let decoder = Qwen3TTSSpeechTokenizerDecoder(config: try tinyConfig())
        let codes = fixtureCodes(tokenCount: 48)
        let firstCodes = codes[0..., 0..., 0..<12]
        let secondCodes = codes[0..., 0..., 12..<48]

        decoder.resetStreamingState()
        let eagerFirst = decoder.streamingStep(firstCodes)
        eval(eagerFirst)
        let eagerFirstSamples = eagerFirst.asArray(Float.self)
        let eagerSecond = decoder.streamingStep(secondCodes)
        eval(eagerSecond)
        let eagerSecondSamples = eagerSecond.asArray(Float.self)

        decoder.resetStreamingState()
        let deferredFirst = decoder.streamingStep(firstCodes)
        asyncEval(deferredFirst)
        Memory.clearCache()
        let deferredFirstSamples = deferredFirst.asArray(Float.self)
        let deferredSecond = decoder.streamingStep(secondCodes)
        eval(deferredSecond)
        let deferredSecondSamples = deferredSecond.asArray(Float.self)

        assertWaveform(
            deferredFirstSamples,
            matches: eagerFirstSamples,
            label: "deferred first chunk after cache clear"
        )
        assertWaveform(
            deferredSecondSamples,
            matches: eagerSecondSamples,
            label: "deferred continuation after cache clear"
        )
    }

    func testReplayCachePolicyPreservesBothPartitionsAndBoundsObservations() throws {
        MLXRandom.seed(0xC0DEC0DE)
        let decoder = Qwen3TTSSpeechTokenizerDecoder(config: try tinyConfig())
        let codes = fixtureCodes(tokenCount: 300)
        for size in [7, Qwen3TTSModel.qualityFirstDecoderChunkFrames] {
            let partitions = repeatedPartitions(total: 300, size: size)
            let baseline = decode(decoder, codes: codes, partitions: partitions, timing: false)
            let ranges = stride(from: 0, to: 300, by: size).map {
                Qwen3CodecFrameRange(start: $0, endExclusive: min(300, $0 + size))
            }
            for clear in [false, true] {
                var observations: [CodecReplayMemoryObservation] = []
                let replay = try Qwen3TTSModel.replayDecoderArm(
                    decoder, codes: codes.transposed(0, 2, 1), ranges: ranges,
                    arm: size == 7 ? .incremental : .full,
                    memoryPolicy: Qwen3RequestMemoryPolicy(
                        clearCacheOnStreamChunkEmit: clear, tokenMemoryClearCadence: 50,
                        talkerKVGeneratedWindow: nil
                    ), observe: { observations.append($0) }
                )
                assertWaveform(replay, matches: baseline, label: "replay \(size), cache clear \(clear)")
                XCTAssertEqual(observations.first?.stage, .started)
                XCTAssertEqual(observations.last?.stage, .finished)
                XCTAssertEqual(observations.last?.completedFrames, 300)
                XCTAssertLessThanOrEqual(observations.count, 36)
                let cleared = observations.filter { $0.stage == .afterCachePolicy }
                if clear { XCTAssertTrue(cleared.allSatisfy { $0.cacheBytes == 0 }) }
                for row in observations {
                    XCTAssertGreaterThanOrEqual(row.activeBytes, 0)
                    XCTAssertGreaterThanOrEqual(row.cacheBytes, 0)
                    XCTAssertGreaterThanOrEqual(row.peakBytes, row.activeBytes)
                }
            }
        }
    }

    func testReplayObservationScheduleIsBoundedAtMaximumTraceLength() throws {
        for count in [1, 16, 17, 293, 8192] {
            let indices = (0..<count).filter { CodecReplayMemoryObservation.shouldSample(index: $0, count: count) }
            XCTAssertEqual(indices.first, 0)
            XCTAssertEqual(indices.last, count - 1)
            XCTAssertLessThanOrEqual(indices.count, 17)
        }
        let data = try JSONEncoder().encode(CodecReplayMemoryObservation.capture(
            arm: .incremental, stage: .started, completedFrames: 0
        ))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(Set(object.keys), Set([
            "event", "arm", "stage", "completedFrames", "timestampUnixMS",
            "activeBytes", "cacheBytes", "peakBytes", "cacheLimitBytes"
        ]))
    }

    func testReplayObservationFailureResetsDecoderAndFailsClosed() throws {
        enum Failure: Error { case capture }
        MLXRandom.seed(0xC0DEC0DE)
        let decoder = Qwen3TTSSpeechTokenizerDecoder(config: try tinyConfig())
        let codes = fixtureCodes(tokenCount: 14)
        let baseline = decode(decoder, codes: codes, partitions: [7, 7], timing: false)
        XCTAssertThrowsError(try Qwen3TTSModel.replayDecoderArm(
            decoder, codes: codes.transposed(0, 2, 1),
            ranges: [.init(start: 0, endExclusive: 7), .init(start: 7, endExclusive: 14)],
            arm: .incremental, memoryPolicy: .compatibilityDefault,
            observe: { if $0.stage == .materialized { throw Failure.capture } }
        )) { XCTAssertTrue($0 is Failure) }
        // Do not manually reset: failure cleanup must make the decoder fresh.
        let afterFailure = decoder.streamingStep(codes)[0, 0].asArray(Float.self)
        assertWaveform(afterFailure, matches: baseline, label: "capture failure cleanup")
        decoder.resetStreamingState()
    }

    func testReplayCancellationStopsAtChunkBoundaryAndResetsDecoder() async throws {
        let config = try tinyConfig()
        let result = try await Task {
            MLXRandom.seed(0xC0DEC0DE)
            let decoder = Qwen3TTSSpeechTokenizerDecoder(config: config)
            let codes = MLXArray(Array(repeating: Int32(1), count: 28)).reshaped(1, 14, 2)
            let baseline = decoder.streamingStep(codes.transposed(0, 2, 1))[0, 0].asArray(Float.self)
            var materialized: [Int] = []
            var cancelled = false
            do {
                _ = try Qwen3TTSModel.replayDecoderArm(
                    decoder, codes: codes,
                    ranges: [.init(start: 0, endExclusive: 7), .init(start: 7, endExclusive: 14)],
                    arm: .incremental, memoryPolicy: .compatibilityDefault,
                    observe: {
                        if $0.stage == .materialized {
                            materialized.append($0.completedFrames)
                            withUnsafeCurrentTask { $0?.cancel() }
                        }
                    }
                )
            } catch is CancellationError { cancelled = true }
            let afterCancel = decoder.streamingStep(codes.transposed(0, 2, 1))[0, 0].asArray(Float.self)
            decoder.resetStreamingState()
            return (cancelled, materialized, baseline, afterCancel)
        }.value
        XCTAssertTrue(result.0)
        XCTAssertEqual(result.1, [7])
        assertWaveform(result.3, matches: result.2, label: "cancellation cleanup")
    }

    private func tinyConfig() throws -> Qwen3TTSTokenizerDecoderConfig {
        let json = """
        {
          "attention_bias": false,
          "latent_dim": 8,
          "codebook_dim": 8,
          "codebook_size": 16,
          "decoder_dim": 16,
          "hidden_size": 8,
          "intermediate_size": 16,
          "max_position_embeddings": 512,
          "head_dim": 4,
          "num_attention_heads": 2,
          "num_hidden_layers": 1,
          "num_key_value_heads": 2,
          "num_quantizers": 2,
          "num_semantic_quantizers": 1,
          "semantic_codebook_size": 16,
          "sliding_window": 512,
          "upsample_rates": [2],
          "upsampling_ratios": [2],
          "vector_quantization_hidden_dimension": 8
        }
        """
        return try JSONDecoder().decode(Qwen3TTSTokenizerDecoderConfig.self, from: Data(json.utf8))
    }

    private func fixtureCodes(tokenCount: Int, offset: Int = 0) -> MLXArray {
        var values: [Int32] = []
        values.reserveCapacity(tokenCount * 2)
        for quantizer in 0..<2 {
            for token in 0..<tokenCount {
                values.append(Int32((token * 7 + quantizer * 3 + offset) % 16))
            }
        }
        return MLXArray(values).reshaped(1, 2, tokenCount)
    }

    private func decode(
        _ decoder: Qwen3TTSSpeechTokenizerDecoder,
        codes: MLXArray,
        partitions: [Int],
        timing: Bool
    ) -> [Float] {
        decoder.resetStreamingState()
        var cursor = 0
        var output: [Float] = []
        for count in partitions where count > 0 {
            let end = min(codes.dim(2), cursor + count)
            guard cursor < end else { break }
            let chunk = codes[0..., 0..., cursor..<end]
            let audio = timing
                ? decoder.streamingStepWithTimings(chunk).audio
                : decoder.streamingStep(chunk)
            output.append(contentsOf: audio.asArray(Float.self))
            cursor = end
        }
        XCTAssertEqual(cursor, codes.dim(2), "partitions must consume every token")
        return output
    }

    private func repeatedPartitions(total: Int, size: Int) -> [Int] {
        var partitions: [Int] = []
        var remaining = total
        while remaining > 0 {
            let next = min(size, remaining)
            partitions.append(next)
            remaining -= next
        }
        return partitions
    }

    private func assertWaveform(_ actual: [Float], matches expected: [Float], label: String) {
        XCTAssertEqual(actual.count, expected.count, label)
        guard actual.count == expected.count, !actual.isEmpty else { return }
        var maxAbsolute: Float = 0
        var squared: Double = 0
        for (lhs, rhs) in zip(actual, expected) {
            let delta = abs(lhs - rhs)
            maxAbsolute = max(maxAbsolute, delta)
            squared += Double(delta * delta)
        }
        let rms = Float((squared / Double(actual.count)).squareRoot())
        XCTAssertLessThanOrEqual(maxAbsolute, maxAbsoluteTolerance, "\(label) max abs")
        XCTAssertLessThanOrEqual(rms, rmsTolerance, "\(label) RMS")
    }
}

private struct SeededGenerator: RandomNumberGenerator {
    private var state: UInt64

    init(seed: UInt64) { state = seed }

    mutating func next() -> UInt64 {
        state = state &* 6_364_136_223_846_793_005 &+ 1
        return state
    }
}
