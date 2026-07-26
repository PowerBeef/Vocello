import MLX
@testable import MLXAudioTTS
import XCTest

final class Qwen3SpeakerMelFrontendTests: XCTestCase {
    func testContractConstantsMatchQwenSpeakerFrontend() {
        XCTAssertEqual(Qwen3TTSSpeakerMelFrontend.featureVersion, "qwen-speaker-mel-v1")
        XCTAssertEqual(Qwen3TTSSpeakerMelFrontend.sampleRate, 24_000)
        XCTAssertEqual(Qwen3TTSSpeakerMelFrontend.fftSize, 1_024)
        XCTAssertEqual(Qwen3TTSSpeakerMelFrontend.hopLength, 256)
        XCTAssertEqual(Qwen3TTSSpeakerMelFrontend.reflectPadding, 384)
        XCTAssertEqual(Qwen3TTSSpeakerMelFrontend.melBinCount, 128)
        XCTAssertEqual(Qwen3TTSSpeakerMelFrontend.minimumFrequency, 0)
        XCTAssertEqual(Qwen3TTSSpeakerMelFrontend.maximumFrequency, 12_000)
    }

    func testPeriodicHannWindowUsesQwenConvention() {
        let values = Qwen3TTSSpeakerMelFrontend.periodicHannWindow().asArray(Float.self)

        XCTAssertEqual(values.count, 1_024)
        XCTAssertEqual(values[0], 0, accuracy: 1e-7)
        XCTAssertEqual(values[256], 0.5, accuracy: 1e-6)
        XCTAssertEqual(values[512], 1, accuracy: 1e-7)
        XCTAssertEqual(values[768], 0.5, accuracy: 1e-6)
        XCTAssertGreaterThan(values[1_023], 0)
    }

    func testDeterministicBatchProducesFiniteTimeMajorFeatures() throws {
        let sampleCount = 2_048
        let first = (0 ..< sampleCount).map { index in
            let time = Float(index) / Float(Qwen3TTSSpeakerMelFrontend.sampleRate)
            return Float(0.4) * sin(2 * Float.pi * Float(440) * time)
                + Float(0.1) * cos(2 * Float.pi * Float(880) * time)
        }
        let second = first.map { -$0 }
        let audio = MLXArray(first + second).reshaped(2, sampleCount)

        let features = try Qwen3TTSSpeakerMelFrontend()(audio)
        eval(features)
        let values = features.asArray(Float.self)

        XCTAssertEqual(features.shape, [2, 8, 128])
        XCTAssertTrue(values.allSatisfy(\.isFinite))
        XCTAssertEqual(Array(values[..<1_024]), Array(values[1_024...]))

        // Golden cells agree with an independent NumPy/librosa-compatible
        // Slaney reference. The tolerance allows backend FFT rounding only.
        let golden: [(index: Int, value: Float)] = [
            (0, -1.3832518),
            (1, -1.3714788),
            (63, -4.3432070),
            (64, -4.4610415),
            (127, -7.0807137),
            (128, -3.1574974),
            (511, -11.512925),
            (512, -8.540497),
            (1_023, -6.9307680),
        ]
        for expected in golden {
            XCTAssertEqual(values[expected.index], expected.value, accuracy: 1e-3, "feature index \(expected.index)")
        }
    }

    func testInvalidShapesAndShortAudioFailWithoutTrapping() {
        XCTAssertThrowsError(
            try Qwen3TTSSpeakerMelFrontend()(MLXArray.zeros([1, 1, 1]))
        )
        XCTAssertThrowsError(
            try Qwen3TTSSpeakerMelFrontend()(MLXArray.zeros([384]))
        )
    }

    func testReferenceAudioNormalizationAcceptsOnlyCanonicalMonoLayouts() throws {
        let samples: [Float] = [0.25, -0.5, 0.75, -1]
        let accepted = [
            MLXArray(samples),
            MLXArray(samples).reshaped(1, samples.count),
            MLXArray(samples).reshaped(1, 1, samples.count),
        ]

        for audio in accepted {
            let canonical = try Qwen3TTSReferenceAudio.canonicalMonoBatch(audio)
            XCTAssertEqual(canonical.shape, [1, samples.count])
            XCTAssertEqual(canonical.asArray(Float.self), samples)
        }
    }

    func testReferenceAudioNormalizationRejectsBatchAndChannelTruncation() {
        let rejected = [
            MLXArray.zeros([0]),
            MLXArray.zeros([2, 64]),
            MLXArray.zeros([64, 1]),
            MLXArray.zeros([2, 1, 64]),
            MLXArray.zeros([1, 2, 64]),
            MLXArray.zeros([1, 64, 1]),
            MLXArray.zeros([1, 1, 1, 64]),
        ]

        for audio in rejected {
            XCTAssertThrowsError(
                try Qwen3TTSReferenceAudio.canonicalMonoBatch(audio),
                "unexpectedly accepted reference-audio shape \(audio.shape)"
            )
        }
    }

    func testCodecEncoderInputAppendsExactTrailingSilence() throws {
        let samples: [Float] = [0.25, -0.5, 0.75, -1]
        let layouts = [
            MLXArray(samples),
            MLXArray(samples).reshaped(1, samples.count),
            MLXArray(samples).reshaped(1, 1, samples.count),
        ]

        XCTAssertEqual(Qwen3TTSReferenceAudio.sampleRate, 24_000)
        XCTAssertEqual(Qwen3TTSReferenceAudio.codecEncodeTrailingSilenceSamples, 12_000)

        for audio in layouts {
            let padded = try Qwen3TTSReferenceAudio.encoderInputWithTrailingSilence(audio)
            XCTAssertEqual(padded.shape, [1, 1, samples.count + 12_000])
            XCTAssertEqual(padded.dtype, audio.dtype)
            let values = padded.asArray(Float.self)
            XCTAssertEqual(Array(values.prefix(samples.count)), samples)
            XCTAssertTrue(values.dropFirst(samples.count).allSatisfy { $0 == 0 })
        }
    }

    func testCodecEncoderInputRejectsNonCanonicalLayouts() {
        XCTAssertThrowsError(
            try Qwen3TTSReferenceAudio.encoderInputWithTrailingSilence(MLXArray.zeros([2, 64]))
        )
    }

    func testConditioningVersionBindsReferenceEncodePreprocessing() {
        // Any change to the ICL reference-encode preprocessing must move this
        // composite so persisted artifacts and prompt caches rebuild.
        XCTAssertEqual(
            Qwen3TTSVoiceClonePrompt.speakerFeatureVersion,
            "qwen-speaker-mel-v1+icl-ref-silence500ms-v2"
        )
        XCTAssertTrue(
            Qwen3TTSVoiceClonePrompt.speakerFeatureVersion
                .hasSuffix(Qwen3TTSReferenceAudio.codecEncodeConditioningVersion)
        )
    }

    func testSpeakerEmbeddingValidationCanonicalizesOfficialVectorShape() throws {
        let vector = MLXArray([Float(0.25), -0.5, 0.75])
        let canonical = try Qwen3TTSVoiceClonePrompt.validateSpeakerEmbedding(
            vector,
            expectedDimension: 3,
            allowOfficialVectorShape: true
        )

        XCTAssertEqual(canonical.shape, [1, 3])
        XCTAssertEqual(canonical.dtype, .float32)
        XCTAssertEqual(canonical.asArray(Float.self), [0.25, -0.5, 0.75])
    }

    func testSpeakerEmbeddingValidationRejectsMalformedValues() {
        let invalid: [MLXArray] = [
            MLXArray([Float(1), 2, 3]).reshaped(1, 3).asType(.float16),
            MLXArray([Float(1), 2, 3]).reshaped(3, 1),
            MLXArray([Float(1), 2, 3, 4, 5, 6]).reshaped(2, 3),
            MLXArray([Float(1), .nan, 3]).reshaped(1, 3),
            MLXArray([Float(1), .infinity, 3]).reshaped(1, 3),
            MLXArray([Float(1), -Float.infinity, 3]).reshaped(1, 3),
        ]

        for embedding in invalid {
            XCTAssertThrowsError(
                try Qwen3TTSVoiceClonePrompt.validateSpeakerEmbedding(
                    embedding,
                    expectedDimension: 3,
                    allowOfficialVectorShape: false
                )
            )
        }
    }
}
