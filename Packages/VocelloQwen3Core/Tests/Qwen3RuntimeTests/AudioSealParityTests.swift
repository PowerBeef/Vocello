// Parity and structure tests for the MLXAudioMark AudioSeal port (CP-2).
//
// The numerical parity tests compare against fixtures minted from the
// PyTorch reference (facebookresearch/audioseal, the audioseal 0.2.0 package;
// the exact upstream commit was not recorded, see ORIGINS.md) with the fixed
// 0x56C0 message. Weights and fixtures are not committed (no bundled
// weights); the tests locate them via QWENVOICE_AUDIOSEAL_FIXTURES and skip
// cleanly when the directory is absent (ordinary CI), so this suite stays
// deterministic-lane safe. The structural test always runs, and so do the
// synthetic-weight tests (PA-19): a seeded random generator written with the
// shipping tensor names and layouts drives the weight loader, the windowed
// embedder against the whole-buffer reference, and the facade transform the
// product's publication marker calls (`VocelloQwen3AudioMarking.markedPCM`).

import Foundation
import MLX
import VocelloQwen3Core
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

        // Zero-peak geometry: the conv stacks' receptive field is a handful
        // of frames, so small margins must stay exact too — this is the
        // shipping window shape (small transients bound the marking pass's
        // Metal-heap high-water).
        let tight = generator.watermark(pcm: pcm, coreFrames: 64, marginFrames: 8)
        let tightError = zip(tight, windowed).map(-)
        let tightSNR = snrDB(reference: windowed.map { $0 }, error: tightError)
        XCTAssertGreaterThanOrEqual(tightSNR, 55,
            "tight-margin windowing (64/8) SNR \(tightSNR) dB — margins no longer cover the receptive field")

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

    // MARK: - Synthetic weights (always run)

    /// 32 000 samples = 100 frames, more than the default 64/8 window geometry
    /// needs (80), so the shipping path really windows.
    private func syntheticPCM(count: Int = 32_000) -> [Float] {
        (0 ..< count).map { index in
            let t = Float(index)
            return 0.3 * sin(t * 0.05) + 0.05 * sin(t * 0.31)
        }
    }

    private func syntheticWeightsURL(omitting omitted: String? = nil) throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("AudioSealSynthetic-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
        let url = directory.appendingPathComponent("audioseal_wm16_generator_fp16.safetensors")
        var arrays = SyntheticAudioSealWeights.arrays()
        if let omitted {
            XCTAssertNotNil(arrays.removeValue(forKey: omitted), "fixture has no tensor \(omitted)")
        }
        try save(arrays: arrays, url: url)
        return url
    }

    func testSyntheticGeneratorWindowedEmbeddingMatchesTheWholeBufferReference() throws {
        let generator = try AudioSealGenerator(weightsURL: try syntheticWeightsURL())
        let pcm = syntheticPCM()

        let wholeDelta = generator.watermarkDelta(pcm: pcm)
        XCTAssertEqual(wholeDelta.count, pcm.count)
        XCTAssertTrue(wholeDelta.allSatisfy(\.isFinite))
        XCTAssertTrue(wholeDelta.contains { $0 != 0 }, "the message must reach the watermark delta")
        let whole = zip(pcm, wholeDelta).map { max(-1, min(1, $0 + $1)) }

        // The shipping geometry and two finer ones: convolutions are local and
        // the LSTMs run over the full frame sequence, so every window geometry
        // with margins above the receptive field reproduces the whole buffer.
        for (coreFrames, marginFrames) in [(64, 8), (16, 8), (24, 12)] {
            let windowed = generator.watermark(pcm: pcm, coreFrames: coreFrames, marginFrames: marginFrames)
            XCTAssertEqual(windowed.count, pcm.count)
            XCTAssertTrue(windowed.allSatisfy { $0 >= -1 && $0 <= 1 }, "embedding clamps to full scale")
            let error = zip(windowed, whole).map(-)
            let snr = snrDB(reference: wholeDelta, error: error)
            XCTAssertGreaterThanOrEqual(
                snr, 55, "\(coreFrames)/\(marginFrames) windowing SNR \(snr) dB — windowing is no longer exact")
        }
        XCTAssertEqual(generator.watermark(pcm: pcm), generator.watermark(pcm: pcm), "embedding is deterministic")
    }

    func testFacadeTransformMarksWithTheShippingEmbedderAndKeepsTheSampleCount() throws {
        let url = try syntheticWeightsURL()
        let pcm = syntheticPCM()

        let marked = try VocelloQwen3AudioMarking.markedPCM(pcm, weightsURL: url)
        XCTAssertEqual(marked.count, pcm.count, "the publication marker rejects any length change")
        XCTAssertTrue(marked.allSatisfy { $0.isFinite && $0 >= -1 && $0 <= 1 })
        XCTAssertNotEqual(marked, pcm, "marking must change the audio")

        let reference = try AudioSealGenerator(weightsURL: url).watermark(pcm: pcm)
        let difference = zip(marked, reference).map { abs($0 - $1) }.max() ?? .infinity
        XCTAssertLessThanOrEqual(difference, 1e-6, "the facade runs the shipping windowed embedder")
        XCTAssertEqual(VocelloQwen3AudioMarking.payload, AudioSealGenerator.messagePayload)
        XCTAssertEqual(VocelloQwen3AudioMarking.payload, 0x56C0)
    }

    func testMissingGeneratorTensorFailsClosed() throws {
        let missing = "msg_processor.msg_processor.weight"
        let url = try syntheticWeightsURL(omitting: missing)

        XCTAssertThrowsError(try AudioSealGenerator(weightsURL: url)) { error in
            guard case .missingTensor(let name)? = error as? AudioSealError else {
                return XCTFail("unexpected error \(error)")
            }
            XCTAssertEqual(name, missing)
        }
        XCTAssertThrowsError(
            try VocelloQwen3AudioMarking.markedPCM(syntheticPCM(count: 3_200), weightsURL: url),
            "incomplete marking weights must never produce unmarked output"
        )
    }
}

/// Seeded random AudioSeal generator weights with the shipping tensor names and
/// layouts (torch Conv1d `[cOut, cIn, K]`, ConvTranspose1d `[cIn, cOut, K]`, fp16
/// like the delivered file). The convolution widths are reduced; the LSTM width
/// (512), the bottleneck (128) and the 32-row message table are the
/// architecture's own, because the generator hard-codes them.
private enum SyntheticAudioSealWeights {
    private static let lstmWidth = 512
    private static let bottleneck = 128
    /// Encoder stage input widths; the last stage widens to the LSTM.
    private static let encoderWidths = [4, 8, 16, 32]
    /// Decoder stage output widths after the LSTM.
    private static let decoderWidths = [32, 16, 8, 4]
    private static let strides = [2, 4, 5, 8]

    static func arrays() -> [String: MLXArray] {
        var arrays: [String: MLXArray] = [:]
        var nextKey: UInt64 = 0xA5EA_1000

        func random(_ shape: [Int], scale: Float) -> MLXArray {
            nextKey += 1
            return (MLXRandom.normal(shape, key: MLXRandom.key(nextKey)) * scale).asType(.float16)
        }
        func conv(_ prefix: String, out: Int, in inputs: Int, kernel: Int, scale: Float? = nil) {
            let weightScale = scale ?? 1 / Float(inputs * kernel).squareRoot()
            arrays["\(prefix).conv.conv.inner_conv.weight"] = random([out, inputs, kernel], scale: weightScale)
            arrays["\(prefix).conv.conv.inner_conv.bias"] = random([out], scale: 0.01)
        }
        func convTranspose(_ prefix: String, in inputs: Int, out: Int, stride: Int) {
            let kernel = 2 * stride
            arrays["\(prefix).convtr.convtr.inner_conv.weight"] = random(
                [inputs, out, kernel], scale: 1 / Float(inputs * 2).squareRoot())
            arrays["\(prefix).convtr.convtr.inner_conv.bias"] = random([out], scale: 0.01)
        }
        func resnet(_ prefix: String, width: Int) {
            conv("\(prefix).block.1", out: width / 2, in: width, kernel: 3)
            conv("\(prefix).block.3", out: width, in: width / 2, kernel: 1)
        }
        func lstm(_ prefix: String) {
            let scale = 1 / Float(lstmWidth).squareRoot()
            for layer in 0 ..< 2 {
                arrays["\(prefix).lstm.weight_ih_l\(layer)"] = random([4 * lstmWidth, lstmWidth], scale: scale)
                arrays["\(prefix).lstm.weight_hh_l\(layer)"] = random([4 * lstmWidth, lstmWidth], scale: scale)
                arrays["\(prefix).lstm.bias_ih_l\(layer)"] = random([4 * lstmWidth], scale: 0.01)
                arrays["\(prefix).lstm.bias_hh_l\(layer)"] = random([4 * lstmWidth], scale: 0.01)
            }
        }

        // Encoder: 0 input conv; stages (resnet, strided conv) at (1,3), (4,6),
        // (7,9), (10,12); 13 LSTM; 15 output conv to the bottleneck.
        conv("encoder.model.0", out: encoderWidths[0], in: 1, kernel: 7)
        for (stage, stride) in strides.enumerated() {
            let base = 1 + stage * 3
            let width = encoderWidths[stage]
            let next = stage + 1 < encoderWidths.count ? encoderWidths[stage + 1] : lstmWidth
            resnet("encoder.model.\(base)", width: width)
            conv("encoder.model.\(base + 2)", out: next, in: width, kernel: 2 * stride)
        }
        lstm("encoder.model.13")
        conv("encoder.model.15", out: bottleneck, in: lstmWidth, kernel: 7)
        arrays["msg_processor.msg_processor.weight"] = random([32, bottleneck], scale: 0.05)

        // Decoder: 0 input conv; 1 LSTM; stages (transposed conv, resnet) at
        // (3,4), (6,7), (9,10), (12,13); 15 output conv to one channel, scaled
        // so the delta stays a small additive mark.
        conv("decoder.model.0", out: lstmWidth, in: bottleneck, kernel: 7)
        lstm("decoder.model.1")
        for (stage, stride) in strides.reversed().enumerated() {
            let base = 2 + stage * 3
            let inputs = stage == 0 ? lstmWidth : decoderWidths[stage - 1]
            let width = decoderWidths[stage]
            convTranspose("decoder.model.\(base + 1)", in: inputs, out: width, stride: stride)
            resnet("decoder.model.\(base + 2)", width: width)
        }
        conv("decoder.model.15", out: 1, in: decoderWidths[decoderWidths.count - 1], kernel: 7, scale: 0.05)
        return arrays
    }
}
