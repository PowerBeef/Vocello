import Foundation
import MLX
@testable import MLXAudioTTS
import VocelloQwen3Core
import XCTest

/// AQ-04 engine introspection (audit 2026-09-25, AQ-F09): the fixed-state
/// summary of codebook-0 token cycles, the talker's per-step entropy and EOS
/// probability, and the streaming seams. Its constants equal the record
/// `config/audio-qc-stage0-observations.json`, and every shared introspection
/// fixture in `scripts/tests/fixtures/audio_qc_stage0_observations.json` gives
/// the summary the Python mirror (`introspection_summary`) gives.
final class Qwen3GenerationIntrospectionTests: XCTestCase {
    private static var repositoryRoot: URL {
        // Tests/Qwen3RuntimeTests/<file> inside Packages/VocelloQwen3Core.
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
    }

    private func json(_ relativePath: String) throws -> [String: Any] {
        let data = try Data(contentsOf: Self.repositoryRoot.appendingPathComponent(relativePath))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any], relativePath)
    }

    private static func summarize(
        tokens: [Int],
        entropies: [Double] = [],
        eosProbabilities: [Double] = [],
        stoppedAtEOS: Bool = false,
        seamFrames: [Int] = []
    ) -> Qwen3GenerationIntrospectionSummary {
        var introspector = Qwen3GenerationIntrospector()
        for token in tokens {
            introspector.observeCodecToken(token)
        }
        let steps = max(entropies.count, eosProbabilities.count)
        for step in 0 ..< steps {
            introspector.observeStep(
                entropy: step < entropies.count ? Float(entropies[step]) : .nan,
                eosProbability: step < eosProbabilities.count ? Float(eosProbabilities[step]) : .nan,
                stopped: stoppedAtEOS && step == steps - 1
            )
        }
        for seam in seamFrames {
            introspector.recordSeam(codecFrame: seam)
        }
        return introspector.summary()
    }

    private static func optionalInt(_ value: Any?) -> Int? {
        (value as? NSNumber)?.intValue
    }

    private static func optionalDouble(_ value: Any?) -> Double? {
        (value as? NSNumber)?.doubleValue
    }

    func testConstantsEqualTheRecord() throws {
        let record = try json("config/audio-qc-stage0-observations.json")
        XCTAssertEqual(
            record["introspectionAlgorithmVersion"] as? Int,
            Qwen3GenerationIntrospectionSummary.algorithmVersion
        )
        let constants = try XCTUnwrap(record["introspection"] as? [String: Any])
        XCTAssertEqual(constants["maximumCyclePeriod"] as? Int, Qwen3GenerationIntrospector.maximumCyclePeriod)
        XCTAssertEqual(
            constants["entropyHistogramBinsPerNat"] as? Int,
            Qwen3GenerationIntrospector.entropyHistogramBinsPerNat
        )
        XCTAssertEqual(constants["entropyHistogramBins"] as? Int, Qwen3GenerationIntrospector.entropyHistogramBins)
        XCTAssertEqual(
            (constants["highEntropyNats"] as? NSNumber)?.doubleValue,
            Qwen3GenerationIntrospector.highEntropyNats
        )
        XCTAssertEqual(
            (constants["likelyEOSProbability"] as? NSNumber)?.doubleValue,
            Qwen3GenerationIntrospector.likelyEOSProbability
        )
        XCTAssertEqual(constants["maximumSeams"] as? Int, Qwen3GenerationIntrospector.maximumSeams)
        // The facade stamps its own constant; it must name the engine's version.
        XCTAssertEqual(
            VocelloQwen3GenerationIntrospection.currentAlgorithmVersion,
            Qwen3GenerationIntrospectionSummary.algorithmVersion
        )
    }

    func testSharedIntrospectionFixturesMatchThePythonMirror() throws {
        let fixtures = try json("scripts/tests/fixtures/audio_qc_stage0_observations.json")
        XCTAssertEqual(
            fixtures["introspectionAlgorithmVersion"] as? Int,
            Qwen3GenerationIntrospectionSummary.algorithmVersion
        )
        let cases = try XCTUnwrap(fixtures["introspectionFixtures"] as? [[String: Any]])
        XCTAssertGreaterThanOrEqual(cases.count, 6)
        for fixture in cases {
            let identifier = try XCTUnwrap(fixture["id"] as? String)
            let summary = Self.summarize(
                tokens: try XCTUnwrap(fixture["tokens"] as? [NSNumber]).map(\.intValue),
                entropies: (fixture["entropies"] as? [NSNumber])?.map(\.doubleValue) ?? [],
                eosProbabilities: (fixture["eosProbabilities"] as? [NSNumber])?.map(\.doubleValue) ?? [],
                stoppedAtEOS: fixture["stoppedAtEOS"] as? Bool ?? false,
                seamFrames: (fixture["seamFrames"] as? [NSNumber])?.map(\.intValue) ?? []
            )
            let expected = try XCTUnwrap(fixture["expected"] as? [String: Any])
            XCTAssertEqual(expected["algorithmVersion"] as? Int, Qwen3GenerationIntrospectionSummary.algorithmVersion)
            XCTAssertEqual(summary.codecFrameCount, Self.optionalInt(expected["codecFrameCount"]), identifier)
            XCTAssertEqual(
                summary.longestRepeatedTokenRunFrames,
                Self.optionalInt(expected["longestRepeatedTokenRunFrames"]),
                identifier
            )
            XCTAssertEqual(summary.tokenCyclePeriod, Self.optionalInt(expected["tokenCyclePeriod"]), identifier)
            XCTAssertEqual(summary.tokenCycleSpanFrames, Self.optionalInt(expected["tokenCycleSpanFrames"]), identifier)
            XCTAssertEqual(summary.tokenCycleRepeats, Self.optionalInt(expected["tokenCycleRepeats"]), identifier)
            XCTAssertEqual(summary.tokenCycleStartFrame, Self.optionalInt(expected["tokenCycleStartFrame"]), identifier)
            XCTAssertEqual(summary.observedStepCount, Self.optionalInt(expected["observedStepCount"]), identifier)
            XCTAssertEqual(summary.entropyMeanNats, Self.optionalDouble(expected["entropyMeanNats"]), identifier)
            XCTAssertEqual(summary.entropyP95Nats, Self.optionalDouble(expected["entropyP95Nats"]), identifier)
            XCTAssertEqual(
                summary.longestHighEntropyRunSteps,
                Self.optionalInt(expected["longestHighEntropyRunSteps"]),
                identifier
            )
            XCTAssertEqual(summary.eosProbabilityFinal, Self.optionalDouble(expected["eosProbabilityFinal"]), identifier)
            XCTAssertEqual(summary.eosProbabilityMax, Self.optionalDouble(expected["eosProbabilityMax"]), identifier)
            XCTAssertEqual(summary.eosProbabilityMaxStep, Self.optionalInt(expected["eosProbabilityMaxStep"]), identifier)
            XCTAssertEqual(summary.eosFirstLikelyStep, Self.optionalInt(expected["eosFirstLikelyStep"]), identifier)
            XCTAssertEqual(
                summary.eosLikelyStepsWithoutStop,
                Self.optionalInt(expected["eosLikelyStepsWithoutStop"]),
                identifier
            )
            XCTAssertEqual(
                summary.seamCodecFrames,
                (expected["seamCodecFrames"] as? [NSNumber])?.map(\.intValue),
                identifier
            )
        }
    }

    func testAStuckTokenIsARunAndALoopIsACycleOfItsShortestPeriod() {
        let stuck = Self.summarize(tokens: [Int](repeating: 7, count: 40))
        XCTAssertEqual(stuck.longestRepeatedTokenRunFrames, 40)
        XCTAssertNil(stuck.tokenCyclePeriod)
        let loop = Self.summarize(tokens: Array((100 ..< 108)) + Array((100 ..< 108)) + Array((100 ..< 108)) + Array((100 ..< 108)))
        XCTAssertEqual(loop.tokenCyclePeriod, 8)
        XCTAssertEqual(loop.tokenCycleRepeats, 4)
        XCTAssertEqual(loop.tokenCycleSpanFrames, 32)
        XCTAssertEqual(loop.tokenCycleStartFrame, 0)
        // A 40-frame phrase said twice is beyond the 32-frame window.
        XCTAssertNil(Self.summarize(tokens: Array(0 ..< 40) + Array(0 ..< 40)).tokenCyclePeriod)
        XCTAssertEqual(Self.summarize(tokens: []).longestRepeatedTokenRunFrames, 0)
    }

    /// The talker distribution the loop reads: the codec codebook and EOS from the
    /// raw logits, whatever the special ids hold.
    func testIntrospectionScalarsReadTheCodebookAndEOS() {
        let codebook = 16
        let vocabulary = codebook + 1_024
        let eos = 1_030
        let uniform = MLXArray.zeros([1, 1, vocabulary], type: Float.self)
        let flat = Qwen3TTSModel.introspectionScalars(uniform, codecVocabularySize: codebook, eosTokenId: eos)
        XCTAssertEqual(flat.entropy.item(Float.self), Float(log(17.0)), accuracy: 1e-5)
        XCTAssertEqual(flat.eosProbability.item(Float.self), 1 / 17, accuracy: 1e-6)

        // Special ids other than EOS never enter the distribution.
        var values = [Float](repeating: 0, count: vocabulary)
        values[codebook + 5] = 80
        values[3] = 20
        let peaked = MLXArray(values).reshaped(1, 1, vocabulary)
        let sharp = Qwen3TTSModel.introspectionScalars(peaked, codecVocabularySize: codebook, eosTokenId: eos)
        XCTAssertLessThan(sharp.entropy.item(Float.self), 1e-5)
        XCTAssertLessThan(sharp.eosProbability.item(Float.self), 1e-6)

        values = [Float](repeating: 0, count: vocabulary)
        values[eos] = 20
        let stopping = Qwen3TTSModel.introspectionScalars(
            MLXArray(values).reshaped(1, 1, vocabulary), codecVocabularySize: codebook, eosTokenId: eos
        )
        XCTAssertGreaterThan(stopping.eosProbability.item(Float.self), 0.999)
    }
}
