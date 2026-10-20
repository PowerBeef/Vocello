import XCTest
@testable import QwenVoiceCore
import VocelloQwen3Core

final class RequestLocalSamplingPolicyTests: XCTestCase {
    func testRequestedSeedAndVariationResolveIntoOneImmutablePolicy() throws {
        let policy = Qwen3TalkerSamplingOverride.samplingConfiguration(
            requestedSeed: 19_790_615,
            variation: .balanced,
            longFormSegment: false
        )

        XCTAssertEqual(policy.algorithmVersion, 2)
        XCTAssertEqual(policy.effectiveSeed, 19_790_615)
        XCTAssertEqual(policy.seed, 19_790_615)
        XCTAssertEqual(policy.talker.temperature, 0.8, accuracy: 0.0001)
        XCTAssertEqual(policy.talker.topP, 0.95, accuracy: 0.0001)
        XCTAssertEqual(policy.talker.topK, 50)
        // The subtalker keeps the reference sampling (RF-18 C1, ER-05).
        XCTAssertEqual(policy.subtalker, VocelloQwen3SamplingStage(temperature: 0.9, topP: 1, topK: 50, minP: 0))
        // Shipped default; a different value requires the Stage 0.4 bench A/B
        // to win on deterministic QC first.
        XCTAssertEqual(policy.repetitionPenalty, 1.05, accuracy: 0.0001)
        // Production requests carry no EOS hold (the audio QC GEN-NOEOS knob is unset).
        XCTAssertNil(policy.eosSuppressionFrames)
        // Nor any RF-14 reference-parity override (its knobs are unset), so the
        // runtime takes production: float32 sampling, EOS filtered and the whole
        // text up front (D3, D2, D1).
        XCTAssertNil(policy.referenceParity)
        XCTAssertNoThrow(try policy.validated())
    }

    /// The RF-14 D1-D3 knobs. Production samples from float32 logits, filters
    /// EOS and gives a single take its whole text (D3, D2, D1), so a knob setting
    /// that leaves that unchanged resolves to nil: an arm turns off only for an
    /// explicit off value.
    func testReferenceParityKnobsDepartFromProductionOnlyExplicitly() {
        func parse(_ fullText: String?, _ filtersEOS: String?, _ float32: String?) -> VocelloQwen3ReferenceParity? {
            Qwen3TalkerSamplingOverride.referenceParity(
                fullTextConditioning: fullText, filtersEOS: filtersEOS, float32Sampling: float32,
                longFormSegment: false
            )
        }
        XCTAssertEqual(
            VocelloQwen3ReferenceParity.production,
            VocelloQwen3ReferenceParity(fullTextConditioning: true, filtersEOS: true, float32Sampling: true)
        )
        XCTAssertNil(parse(nil, nil, nil))
        XCTAssertNil(parse("on", "on", "on"))
        for unrecognized in ["", "full", "maybe"] {
            XCTAssertNil(parse(unrecognized, unrecognized, unrecognized), unrecognized)
        }
        XCTAssertEqual(
            parse("off", nil, nil),
            VocelloQwen3ReferenceParity(fullTextConditioning: false, filtersEOS: true, float32Sampling: true)
        )
        XCTAssertEqual(
            parse(nil, " Off\n", nil),
            VocelloQwen3ReferenceParity(fullTextConditioning: true, filtersEOS: false, float32Sampling: true)
        )
        XCTAssertEqual(
            parse(nil, nil, " Off\n"),
            VocelloQwen3ReferenceParity(fullTextConditioning: true, filtersEOS: true, float32Sampling: false)
        )
        XCTAssertEqual(
            parse("0", "no", "no"),
            VocelloQwen3ReferenceParity(fullTextConditioning: false, filtersEOS: false, float32Sampling: false)
        )
    }

    /// RF-21: a single streamed take sees its whole text up front (production),
    /// while a long-form segment keeps the trailing-text layout RF-18 qualified.
    /// The D1 knob forces either layout for both; the other arms are unchanged.
    func testALongFormSegmentKeepsTrailingTextAndASingleTakeTheWholeText() {
        let trailingText = VocelloQwen3ReferenceParity(
            fullTextConditioning: false, filtersEOS: true, float32Sampling: true
        )
        func parity(longForm: Bool, knob: String? = nil) -> VocelloQwen3ReferenceParity? {
            Qwen3TalkerSamplingOverride.referenceParity(
                fullTextConditioning: knob, filtersEOS: nil, float32Sampling: nil, longFormSegment: longForm
            )
        }
        XCTAssertNil(parity(longForm: false))
        XCTAssertEqual(parity(longForm: true), trailingText)
        XCTAssertNil(parity(longForm: true, knob: "on"))
        XCTAssertEqual(parity(longForm: false, knob: "off"), trailingText)

        // The knobs are unset in tests, so the policy the engine resolves from a
        // request (every engine call site goes through it) carries exactly that.
        func request(longFormSegment: Bool?) -> GenerationRequest {
            GenerationRequest(
                mode: .custom, modelID: "fixture", text: "One segment.", outputPath: "take.wav",
                shouldStream: true, payload: .custom(speakerID: "aiden", deliveryStyle: nil), seed: 3,
                longFormSegment: longFormSegment
            )
        }
        let segment = Qwen3TalkerSamplingOverride.samplingConfiguration(for: request(longFormSegment: true))
        XCTAssertEqual(segment.referenceParity, trailingText)
        XCTAssertEqual(segment.effectiveSeed, 3)
        XCTAssertNil(Qwen3TalkerSamplingOverride.samplingConfiguration(for: request(longFormSegment: nil)).referenceParity)
        XCTAssertNil(Qwen3TalkerSamplingOverride.samplingConfiguration(for: request(longFormSegment: false)).referenceParity)
    }

    /// RF-18 C1 (ER-05): the variation shapes only the talker. The subtalker keeps
    /// the reference sampling for every variation, so Expressive, whose talker is
    /// the reference, leaves both stages equal.
    func testSubtalkerKeepsReferenceSamplingWhateverTheVariation() {
        let reference = VocelloQwen3SamplingStage(temperature: 0.9, topP: 1, topK: 50, minP: 0)
        let talkers: [(Qwen3SamplingVariation?, Float, Float)] = [
            (.expressive, 0.9, 1), (nil, 0.9, 1), (.balanced, 0.8, 0.95), (.consistent, 0.7, 0.9),
        ]
        for (variation, temperature, topP) in talkers {
            let policy = Qwen3TalkerSamplingOverride.samplingConfiguration(
                requestedSeed: 7, variation: variation, longFormSegment: false
            )
            let name = String(describing: variation)
            XCTAssertEqual(policy.talker.temperature, temperature, accuracy: 0.0001, name)
            XCTAssertEqual(policy.talker.topP, topP, accuracy: 0.0001, name)
            XCTAssertEqual(policy.subtalker, reference, name)
        }
    }

    /// The registered GEN-NOEOS knob's value: a whole number of codec frames
    /// inside the facade's bound, or no hold at all.
    func testEOSSuppressionKnobParsesOnlyBoundedWholeFrames() {
        let parse = Qwen3TalkerSamplingOverride.eosSuppressionFrames
        XCTAssertEqual(parse("0"), 0)
        XCTAssertEqual(parse(" 50\n"), 50)
        XCTAssertEqual(parse("256"), 256)
        for raw in [nil, "", "-1", "257", "6.5", "six", "0x10"] as [String?] {
            XCTAssertNil(parse(raw), String(describing: raw))
        }
    }

    func testUnseededRequestStillReceivesReplayableEffectiveSeed() {
        let first = Qwen3TalkerSamplingOverride.samplingConfiguration(
            requestedSeed: nil,
            variation: .expressive,
            longFormSegment: false
        )
        let second = Qwen3TalkerSamplingOverride.samplingConfiguration(
            requestedSeed: nil,
            variation: .expressive,
            longFormSegment: false
        )

        XCTAssertNil(first.seed)
        XCTAssertNil(second.seed)
        XCTAssertNotEqual(first.effectiveSeed, second.effectiveSeed)
    }
}
