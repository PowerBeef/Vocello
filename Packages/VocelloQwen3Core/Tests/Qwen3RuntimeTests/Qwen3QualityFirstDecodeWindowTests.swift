import Foundation
import MLX
@testable import MLXAudioTTS
import XCTest

/// PA-13 / DECODE-002: quality-first decode, the in-context clone cut and
/// codec replay derive their sample window from explicit reference and
/// generated frame counts. Code 0 is a legal codec token, so a generated 0
/// (inside the take or at its tail) never shortens the output.
final class Qwen3QualityFirstDecodeWindowTests: XCTestCase {
    // MARK: - Recorded text conditioning (P05-08)

    /// Custom and Design record the mode they were asked for, which they
    /// honor; a clone records the layout it always uses, whatever was asked.
    func testRecordedTextConditioningNamesTheLayoutThePreparationUsed() {
        for requested in [Qwen3TextConditioningMode.streamingTrailingText, .fullTextNonStreaming] {
            XCTAssertEqual(
                Qwen3TextConditioningMode.recordedLabel(requested: requested, cloneInContextLearning: nil),
                requested.rawValue
            )
            XCTAssertEqual(
                Qwen3TextConditioningMode.recordedLabel(requested: requested, cloneInContextLearning: true),
                "icl_full_text_overlay"
            )
            XCTAssertEqual(
                Qwen3TextConditioningMode.recordedLabel(requested: requested, cloneInContextLearning: false),
                "streaming_trailing_text",
                "a quality-first speaker-only clone still streams its trailing text"
            )
        }
    }

    // MARK: - Window math

    func testWindowWithoutReferenceCoversEveryGeneratedFrame() {
        XCTAssertEqual(
            Qwen3TTSModel.qualityFirstSampleRange(
                referenceFrameCount: 0, generatedFrameCount: 10,
                decodedSampleCount: 40, upsampleRate: 4
            ),
            0 ..< 40
        )
    }

    func testReferenceCutUsesIntegerFrameStart() {
        XCTAssertEqual(
            Qwen3TTSModel.qualityFirstSampleRange(
                referenceFrameCount: 7, generatedFrameCount: 13,
                decodedSampleCount: 80, upsampleRate: 4
            ),
            28 ..< 80
        )
        // Production stride (24 kHz / 12.5 fps): 97 reference + 211 generated
        // frames decode to 591,360 samples; the cut is exactly 97 × 1,920.
        let production = Qwen3TTSModel.qualityFirstSampleRange(
            referenceFrameCount: 97, generatedFrameCount: 211,
            decodedSampleCount: 591_360, upsampleRate: 1_920
        )
        XCTAssertEqual(production, 186_240 ..< 591_360)
        XCTAssertEqual(production.count, 211 * 1_920)
    }

    func testWindowClampsToDecodedSamples() {
        // Decoder emitted more than the frames cover: keep only the frames.
        XCTAssertEqual(
            Qwen3TTSModel.qualityFirstSampleRange(
                referenceFrameCount: 7, generatedFrameCount: 13,
                decodedSampleCount: 90, upsampleRate: 4
            ),
            28 ..< 80
        )
        // Decoder emitted fewer: never index past the decoded samples.
        XCTAssertEqual(
            Qwen3TTSModel.qualityFirstSampleRange(
                referenceFrameCount: 7, generatedFrameCount: 13,
                decodedSampleCount: 70, upsampleRate: 4
            ),
            28 ..< 70
        )
        XCTAssertEqual(
            Qwen3TTSModel.qualityFirstSampleRange(
                referenceFrameCount: 7, generatedFrameCount: 13,
                decodedSampleCount: 20, upsampleRate: 4
            ),
            20 ..< 20
        )
        XCTAssertEqual(
            Qwen3TTSModel.qualityFirstSampleRange(
                referenceFrameCount: -1, generatedFrameCount: -1,
                decodedSampleCount: -1, upsampleRate: 4
            ),
            0 ..< 0
        )
    }

    /// The window assumes the tokenizer's decode stride equals the decoder's real
    /// upsample product; production checks only the stride (1_920), so pin the
    /// default decoder product to it here.
    func testDefaultDecoderUpsampleProductMatchesTheTokenizerStride() throws {
        let decoder = try JSONDecoder().decode(
            Qwen3TTSTokenizerDecoderConfig.self, from: Data("{}".utf8)
        )
        let product = (decoder.upsampleRates + decoder.upsamplingRatios).reduce(1, *)
        let config = try JSONDecoder().decode(Qwen3TTSTokenizerConfig.self, from: Data("{}".utf8))
        XCTAssertEqual(product, 1_920)
        XCTAssertEqual(product, config.decodeUpsampleRate)
    }

    // MARK: - Tiny decoder

    func testTinyDecoderEmitsExactlyFramesTimesUpsample() throws {
        let tokenizer = try makeTinyTokenizer()
        XCTAssertEqual(tokenizer.decodeUpsampleRate, tokenizer.decoder.totalUpsample)
        for frameCount in [1, 24, 25, 26, 63] {
            let codes = fixtureCodes(frameCount: frameCount, zeroFrames: [])
            let chunks = tokenizer.streamingDecode(
                codes, chunkTokens: Qwen3TTSModel.qualityFirstDecoderChunkFrames
            )
            let decoded = concatenated(chunks, axis: -1)[0]
            XCTAssertEqual(
                decoded.dim(0), frameCount * tokenizer.decodeUpsampleRate,
                "\(frameCount) frames"
            )
        }
    }

    func testGeneratedZeroCodesInsideAndAtTailKeepEveryFrame() throws {
        let tokenizer = try makeTinyTokenizer()
        let frameCount = 63
        // First-group code 0 inside the take and on the last two frames.
        let zeroFrames: Set<Int> = [5, 30, 61, 62]
        let codes = fixtureCodes(frameCount: frameCount, zeroFrames: zeroFrames)
        let firstGroupNonZero = frameCount - zeroFrames.count
        XCTAssertLessThan(firstGroupNonZero, frameCount, "fixture must contain generated code 0")

        let audio = Qwen3TTSModel.decodeQualityFirstWindow(
            tokenizer, codes: codes, referenceFrameCount: 0
        )
        XCTAssertEqual(audio.dim(0), frameCount * tokenizer.decodeUpsampleRate)
        // The former `> 0` count would have dropped the tail.
        XCTAssertGreaterThan(audio.dim(0), firstGroupNonZero * tokenizer.decodeUpsampleRate)
    }

    func testReferenceCutKeepsExactlyTheGeneratedWindow() throws {
        let tokenizer = try makeTinyTokenizer()
        let referenceFrames = 7
        let generatedFrames = 41
        let totalFrames = referenceFrames + generatedFrames
        // Code 0 inside the reference, inside the generated take and at its tail.
        let codes = fixtureCodes(frameCount: totalFrames, zeroFrames: [2, 20, totalFrames - 1])
        let rate = tokenizer.decodeUpsampleRate

        let full = Qwen3TTSModel.decodeQualityFirstWindow(
            tokenizer, codes: codes, referenceFrameCount: 0
        ).asArray(Float.self)
        XCTAssertEqual(full.count, totalFrames * rate)

        let generated = Qwen3TTSModel.decodeQualityFirstWindow(
            tokenizer, codes: codes, referenceFrameCount: referenceFrames
        ).asArray(Float.self)
        XCTAssertEqual(generated.count, generatedFrames * rate)
        let expectedTail = Array(full[(referenceFrames * rate)...])
        XCTAssertEqual(generated.count, expectedTail.count)
        XCTAssertTrue(generated.allSatisfy(\.isFinite), "decoded window must be finite")
        let maxAbsolute = zip(generated, expectedTail)
            .map { abs($0 - $1) }
            .max() ?? 0
        XCTAssertLessThanOrEqual(maxAbsolute, 1e-5, "reference cut must start exactly at frame \(referenceFrames)")
    }

    /// A-04 (RF-52): a streamed decode primed with the reference's codes gives
    /// the quality-first window of `[reference + generated]` in any streaming
    /// partition, and a cold streamed decode does not.
    func testAStreamPrimedWithTheReferenceDecodesAsTheQualityFirstWindow() throws {
        let tokenizer = try makeTinyTokenizer()
        let referenceFrames = 31
        let generatedFrames = 40
        let codes = fixtureCodes(frameCount: referenceFrames + generatedFrames, zeroFrames: [])
        let expected = Qwen3TTSModel.decodeQualityFirstWindow(
            tokenizer, codes: codes, referenceFrameCount: referenceFrames
        ).asArray(Float.self)
        // Quantizer-major `[1, groups, frames]`, as the prompt's reference
        // codes and the streamed chunks reach the decoder.
        let referenceCodes = codes[0..., 0 ..< referenceFrames, 0...].transposed(0, 2, 1)
        let generatedCodes = codes[0..., referenceFrames..., 0...].transposed(0, 2, 1)
        func streamed(primed: Bool, piece: Int) throws -> [Float] {
            tokenizer.decoder.resetStreamingState()
            defer { tokenizer.decoder.resetStreamingState() }
            if primed {
                XCTAssertEqual(try Qwen3TTSModel.primeStreamingDecoder(
                    tokenizer.decoder, referenceCodes: referenceCodes), referenceFrames)
            }
            var output: [Float] = []
            for start in stride(from: 0, to: generatedFrames, by: piece) {
                let end = min(generatedFrames, start + piece)
                output += tokenizer.decoder.streamingStep(generatedCodes[0..., 0..., start ..< end]).asArray(Float.self)
            }
            return output
        }
        for piece in [4, 8] {
            let primed = try streamed(primed: true, piece: piece)
            XCTAssertEqual(primed.count, expected.count)
            let difference = zip(primed, expected).map { abs($0 - $1) }.max() ?? .infinity
            XCTAssertLessThanOrEqual(difference, 1e-5, "primed, \(piece)-frame pieces")
        }
        let cold = try streamed(primed: false, piece: 4)
        XCTAssertGreaterThan(zip(cold, expected).map { abs($0 - $1) }.max() ?? 0, 1e-4,
                             "a cold decoder lacks the reference's history")
        // Priming in other piece sizes leaves the same state.
        tokenizer.decoder.resetStreamingState()
        _ = try Qwen3TTSModel.primeStreamingDecoder(tokenizer.decoder, referenceCodes: referenceCodes, pieceFrames: 7)
        let sevens = tokenizer.decoder.streamingStep(generatedCodes).asArray(Float.self)
        tokenizer.decoder.resetStreamingState()
        XCTAssertLessThanOrEqual(zip(sevens, expected).map { abs($0 - $1) }.max() ?? .infinity, 1e-5)
    }

    // MARK: - Fixtures

    private func makeTinyTokenizer() throws -> Qwen3TTSSpeechTokenizer {
        let decoderConfig = try Qwen3DecoderPartitionTests.tinyDecoderConfig()
        var config = try JSONDecoder().decode(
            Qwen3TTSTokenizerConfig.self, from: Data("{}".utf8)
        )
        config.decoderConfig = decoderConfig
        config.decodeUpsampleRate = (decoderConfig.upsampleRates + decoderConfig.upsamplingRatios)
            .reduce(1, *)
        return Qwen3TTSSpeechTokenizer(config: config, includeEncoder: false)
    }

    /// Codes `[1, frameCount, 2]` (time-major, two code groups, codebook 16).
    /// Frames listed in `zeroFrames` carry first-group code 0.
    private func fixtureCodes(frameCount: Int, zeroFrames: Set<Int>) -> MLXArray {
        var values: [Int32] = []
        values.reserveCapacity(frameCount * 2)
        for frame in 0 ..< frameCount {
            let first = zeroFrames.contains(frame) ? 0 : (frame * 7) % 15 + 1
            values.append(Int32(first))
            values.append(Int32((frame * 5 + 3) % 16))
        }
        return MLXArray(values).reshaped(1, frameCount, 2)
    }
}
