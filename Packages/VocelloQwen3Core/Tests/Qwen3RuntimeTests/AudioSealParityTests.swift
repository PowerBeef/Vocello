// Parity and structure tests for the MLXAudioMark AudioSeal port (CP-2).
//
// The numerical parity tests compare against fixtures minted from the
// PyTorch reference (facebookresearch/audioseal @ cc2700db) with the fixed
// 0x56C0 message. Weights and fixtures are not committed (no bundled
// weights); the tests locate them via QWENVOICE_AUDIOSEAL_FIXTURES and skip
// cleanly when the directory is absent (ordinary CI), so this suite stays
// deterministic-lane safe. The structural test always runs.

import Foundation
import MLX
import XCTest

@testable import MLXAudioMark

final class AudioSealParityTests: XCTestCase {
    private func fixturesDirectory() throws -> URL {
        guard let path = ProcessInfo.processInfo.environment["QWENVOICE_AUDIOSEAL_FIXTURES"],
              !path.isEmpty else {
            throw XCTSkip("QWENVOICE_AUDIOSEAL_FIXTURES unset; parity runs locally with exported weights")
        }
        let url = URL(fileURLWithPath: path, isDirectory: true)
        guard FileManager.default.fileExists(atPath: url.appendingPathComponent("parity-fixtures.safetensors").path) else {
            throw XCTSkip("fixtures not present at \(path)")
        }
        return url
    }

    private func snrDB(reference: [Float], error: [Float]) -> Float {
        let refPower = reference.reduce(Float(0)) { $0 + $1 * $1 }
        let errPower = error.reduce(Float(0)) { $0 + $1 * $1 }
        return 10 * log10(refPower / max(errPower, .leastNormalMagnitude))
    }

    func testWholeBufferParityAgainstReferenceFixtures() throws {
        let dir = try fixturesDirectory()
        let generator = try AudioSealGenerator(
            weightsURL: dir.appendingPathComponent("audioseal-generator-fused.safetensors"))
        let fixtures = try loadArrays(url: dir.appendingPathComponent("parity-fixtures.safetensors"))
        for index in 0 ..< 2 {
            guard let input = fixtures["in_\(index)"], let expected = fixtures["wm_\(index)"] else {
                return XCTFail("fixture \(index) missing")
            }
            let pcm = input.asArray(Float.self)
            let reference = expected.asArray(Float.self)
            let delta = generator.watermarkDelta(pcm: pcm)
            XCTAssertEqual(delta.count, reference.count, "delta length")
            let error = zip(delta, reference).map(-)
            let snr = snrDB(reference: reference, error: error)
            XCTAssertGreaterThanOrEqual(
                snr, 40, "fixture \(index): port-vs-reference SNR \(snr) dB below parity bar")
        }
    }

    func testWindowedPathMatchesWholeBufferExactly() throws {
        // The shipping windowed path (windowed convs + full-sequence LSTMs)
        // must be numerically equal to the whole-buffer reference:
        // convolutions are local, so frame-aligned margins make interior
        // outputs exact, and the sequential LSTM state runs unwindowed.
        let dir = try fixturesDirectory()
        let generator = try AudioSealGenerator(
            weightsURL: dir.appendingPathComponent("audioseal-generator-fused.safetensors"))
        let fixtures = try loadArrays(url: dir.appendingPathComponent("parity-fixtures.safetensors"))
        guard let input = fixtures["in_1"] else { return XCTFail("fixture 1 missing") }
        let pcm = input.asArray(Float.self)

        // Small cores force four windows on the 60 000-sample (188-frame)
        // fixture; margins stay far above the conv receptive field.
        let windowed = generator.watermark(pcm: pcm, coreFrames: 50, marginFrames: 64)
        let windowed2 = generator.watermark(pcm: pcm, coreFrames: 50, marginFrames: 64)
        XCTAssertEqual(windowed, windowed2, "windowed embedding must be deterministic")

        let wholeDelta = generator.watermarkDelta(pcm: pcm)
        let whole = zip(pcm, wholeDelta).map { max(-1, min(1, $0 + $1)) }
        let error = zip(windowed, whole).map(-)
        let snr = snrDB(reference: wholeDelta, error: error)
        XCTAssertGreaterThanOrEqual(snr, 55,
            "windowed-vs-whole SNR \(snr) dB — windowing is no longer exact")

        if ProcessInfo.processInfo.environment["QWENVOICE_AUDIOSEAL_EXPORT"] == "1" {
            // Design-parameter windowed run on a 10 s tiled signal for the
            // Python-detector adjudication of the shipping window geometry.
            let long = Array(repeating: pcm, count: 4).flatMap { $0 }
            let longWindowed = generator.watermark(pcm: long)
            var arrays: [String: MLXArray] = [
                "windowed_1": MLXArray(windowed),
                "whole_delta_1": MLXArray(wholeDelta),
                "long_in": MLXArray(long),
                "long_windowed_design": MLXArray(longWindowed),
            ]
            if let speech = fixtures["in_speech"] {
                let speechPCM = speech.asArray(Float.self)
                arrays["speech_windowed_design"] = MLXArray(generator.watermark(pcm: speechPCM))
            }
            try save(arrays: arrays, url: dir.appendingPathComponent("swift-windowed-out.safetensors"))
        }
    }

    func testStreamableConvPaddingPreservesFrameArithmetic() {
        // audiocraft's padding contract: output frames == ceil(T / stride),
        // independent of T alignment. Verify across the generator's stage
        // geometry with synthetic weights.
        for (kernel, stride) in [(7, 1), (4, 2), (8, 4), (10, 5), (16, 8)] {
            let conv = StreamableConv1d(
                weight: MLXArray.zeros([3, kernel, 2]),
                bias: MLXArray.zeros([3]),
                stride: stride, dilation: 1)
            for frames in [37, 48, 100, 24_000] {
                let out = conv(MLXArray.zeros([1, frames, 2]))
                let expected = Int((Double(frames) / Double(stride)).rounded(.up))
                XCTAssertEqual(out.dim(1), expected, "k\(kernel)/s\(stride) on T=\(frames)")
            }
        }
    }
}
