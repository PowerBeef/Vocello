import Foundation
import MLX
@testable import MLXAudioTTS
import XCTest

/// PA-13 / DECODE-002: quality-first decode, the in-context clone cut and
/// codec replay derive their sample window from explicit reference and
/// generated frame counts. Code 0 is a legal codec token, so a generated 0
/// (inside the take or at its tail) never shortens the output.
final class Qwen3QualityFirstDecodeWindowTests: XCTestCase {
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
