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

    func testConstrainedCacheClearDisablesDeferredAudioMaterialization() {
        XCTAssertTrue(
            Qwen3StreamStepEvalPolicy.pipelined.shouldDeferAudioMaterialization(
                hasMaterializedSink: true,
                clearsAllocatorCacheAfterChunk: false
            )
        )
        XCTAssertFalse(
            Qwen3StreamStepEvalPolicy.pipelined.shouldDeferAudioMaterialization(
                hasMaterializedSink: true,
                clearsAllocatorCacheAfterChunk: true
            )
        )
        XCTAssertFalse(
            Qwen3StreamStepEvalPolicy.full.shouldDeferAudioMaterialization(
                hasMaterializedSink: true,
                clearsAllocatorCacheAfterChunk: false
            )
        )
        XCTAssertFalse(
            Qwen3StreamStepEvalPolicy.pipelined.shouldDeferAudioMaterialization(
                hasMaterializedSink: false,
                clearsAllocatorCacheAfterChunk: false
            )
        )
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
