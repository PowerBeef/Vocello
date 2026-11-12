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
        XCTAssertEqual(Qwen3TTSReferenceAudio.legacyTrailingSilenceSamples, 12_000)

        for audio in layouts {
            let padded = try Qwen3TTSReferenceAudio.encoderInput(audio, trailingSilenceSamples: 12_000)
            XCTAssertEqual(padded.shape, [1, 1, samples.count + 12_000])
            XCTAssertEqual(padded.dtype, audio.dtype)
            let values = padded.asArray(Float.self)
            XCTAssertEqual(Array(values.prefix(samples.count)), samples)
            XCTAssertTrue(values.dropFirst(samples.count).allSatisfy { $0 == 0 })
        }
    }

    /// A-12: the reference reaches the encoder as it is, as upstream encodes
    /// it, the default since the clone screen's rule `reference-padding-none`
    /// adopted it; the gated key restores the half second of zeros.
    func testCodecEncoderInputWithoutTrailingSilenceIsTheReferenceItself() throws {
        let samples: [Float] = [0.25, -0.5, 0.75, -1]
        let unpadded = try Qwen3TTSReferenceAudio.encoderInput(MLXArray(samples), trailingSilenceSamples: 0)
        XCTAssertEqual(unpadded.shape, [1, 1, samples.count])
        XCTAssertEqual(unpadded.asArray(Float.self), samples)
        XCTAssertEqual(Qwen3TTSReferenceAudio.codecEncodeTrailingSilenceSamples, 0)
        XCTAssertEqual(Qwen3LoadTimeDiagnosticOverrides.production.referenceTrailingSilenceSamples, 0)
        let requested = ["QWENVOICE_DEBUG": "1", "QWENVOICE_REFERENCE_PADDING": " Half-Second "]
        XCTAssertEqual(
            Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: true, environment: requested)
                .referenceTrailingSilenceSamples, 12_000)
        XCTAssertEqual(
            Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: false, environment: requested)
                .referenceTrailingSilenceSamples, 0)
        for mistyped in ["none", "0", "500ms", ""] {
            var environment = requested
            environment["QWENVOICE_REFERENCE_PADDING"] = mistyped
            XCTAssertEqual(
                Qwen3LoadTimeDiagnosticOverrides.resolve(internalDiagnosticsAvailable: true, environment: environment)
                    .referenceTrailingSilenceSamples, 0, mistyped)
        }
    }

    /// G-07 (RF-52): the trim keeps 100 ms around the first and last window
    /// with sound, fades both ends over 10 ms, and returns a reference with no
    /// sound, or too short to judge, unchanged.
    func testEdgeTrimKeepsAMarginAroundTheSoundAndFadesBothEnds() throws {
        let rate = Qwen3TTSReferenceAudio.sampleRate
        let tone = (0 ..< rate).map { Float(0.3 * sin(2 * Double.pi * 220 * Double($0) / Double(rate))) }
        let silence = [Float](repeating: 0, count: rate / 2)
        let quietNoise = (0 ..< rate / 2).map { Float(1e-5 * sin(Double($0) * 1.7)) }
        let trimmed = Qwen3TTSReferenceAudio.edgesTrimmedAndFaded(silence + quietNoise + tone + silence)
        // The sound starts at 1 s and runs 1 s: 100 ms either side survives.
        XCTAssertEqual(trimmed.count, rate + 2 * (rate / 10))
        XCTAssertEqual(trimmed.first, 0, "faded in from zero")
        XCTAssertEqual(Array(trimmed[(rate / 10 + 240) ..< (rate / 10 + 480)]),
                       Array(tone[240 ..< 480]), "the sound itself is untouched past the fade")
        XCTAssertLessThan(abs(trimmed[trimmed.count - 1]), 1e-6, "faded out to zero")

        // A clip cut mid-sound keeps every sample and gains only the fades:
        // half-raised-cosine ramps of 10 ms, at half gain halfway in, from a
        // tone whose first and last samples are not zero.
        let shifted = (0 ..< rate).map { Float(0.3 * sin(2 * Double.pi * 220 * Double($0) / Double(rate) + 1)) }
        let cut = Qwen3TTSReferenceAudio.edgesTrimmedAndFaded(shifted)
        let ramp = rate / 100
        XCTAssertEqual(cut.count, shifted.count)
        XCTAssertNotEqual(shifted[0], 0)
        XCTAssertNotEqual(shifted[shifted.count - 1], 0)
        XCTAssertEqual(cut[0], 0, "faded in from zero")
        XCTAssertEqual(cut[cut.count - 1], 0, "faded out to zero")
        XCTAssertEqual(cut[ramp / 2], shifted[ramp / 2] * 0.5, accuracy: 1e-6)
        XCTAssertEqual(cut[cut.count - 1 - ramp / 2], shifted[shifted.count - 1 - ramp / 2] * 0.5, accuracy: 1e-6)
        XCTAssertEqual(Array(cut[ramp ..< cut.count - ramp]), Array(shifted[ramp ..< shifted.count - ramp]),
                       "untouched between the fades")

        XCTAssertEqual(Qwen3TTSReferenceAudio.edgesTrimmedAndFaded(silence), silence, "no sound: as given")
        let short = Array(tone.prefix(300))
        XCTAssertEqual(Qwen3TTSReferenceAudio.edgesTrimmedAndFaded(short), short, "under two windows: as given")
        let viaArray = try Qwen3TTSReferenceAudio.edgesTrimmedAndFaded(
            MLXArray(silence + tone).reshaped(1, 1, -1)).asArray(Float.self)
        XCTAssertEqual(viaArray, Qwen3TTSReferenceAudio.edgesTrimmedAndFaded(silence + tone))
    }

    func testCodecEncoderInputRejectsNonCanonicalLayouts() {
        XCTAssertThrowsError(
            try Qwen3TTSReferenceAudio.encoderInput(MLXArray.zeros([2, 64]), trailingSilenceSamples: 0)
        )
    }

    func testConditioningVersionBindsReferenceEncodePreprocessing() {
        // Any change to the ICL reference-encode preprocessing or to the MLX
        // build (F-06) must move this composite so persisted artifacts and
        // prompt caches rebuild.
        XCTAssertEqual(
            Qwen3TTSVoiceClonePrompt.speakerFeatureVersion,
            "qwen-speaker-mel-v1+icl-ref-unpadded-v3+mlx-swift-0.32.3"
        )
        XCTAssertTrue(
            Qwen3TTSVoiceClonePrompt.speakerFeatureVersion
                .contains("+\(Qwen3TTSReferenceAudio.codecEncodeConditioningVersion)+")
        )
        XCTAssertTrue(
            Qwen3TTSVoiceClonePrompt.speakerFeatureVersion
                .hasSuffix("+\(Qwen3TTSVoiceClonePrompt.mlxNumericsVersion)")
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
