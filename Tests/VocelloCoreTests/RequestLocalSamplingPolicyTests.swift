import XCTest
@testable import QwenVoiceCore
import VocelloQwen3Core

final class RequestLocalSamplingPolicyTests: XCTestCase {
    func testRequestedSeedAndVariationResolveIntoOneImmutablePolicy() throws {
        let policy = Qwen3TalkerSamplingOverride.samplingConfiguration(
            requestedSeed: 19_790_615,
            variation: .balanced
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
        // runtime takes production: float32 sampling and EOS filtered (D3, D2), D1 off.
        XCTAssertNil(policy.referenceParity)
        XCTAssertNoThrow(try policy.validated())
    }

    /// The RF-14 D1-D3 knobs. Production samples from float32 logits and filters
    /// EOS (D3 and D2) with D1 off, so a knob setting that leaves that unchanged
    /// resolves to nil: D1 turns on only for an explicit on value, and D2 and D3
    /// turn off only for an explicit off value.
    func testReferenceParityKnobsDepartFromProductionOnlyExplicitly() {
        let parse = Qwen3TalkerSamplingOverride.referenceParity
        XCTAssertEqual(
            VocelloQwen3ReferenceParity.production,
            VocelloQwen3ReferenceParity(fullTextConditioning: false, filtersEOS: true, float32Sampling: true)
        )
        XCTAssertNil(parse(nil, nil, nil))
        XCTAssertNil(parse("off", "on", "on"))
        for unrecognized in ["", "full", "maybe"] {
            XCTAssertNil(parse(unrecognized, unrecognized, unrecognized), unrecognized)
        }
        XCTAssertEqual(
            parse("on", nil, nil),
            VocelloQwen3ReferenceParity(fullTextConditioning: true, filtersEOS: true, float32Sampling: true)
        )
        XCTAssertEqual(
            parse(nil, " Off\n", nil),
            VocelloQwen3ReferenceParity(fullTextConditioning: false, filtersEOS: false, float32Sampling: true)
        )
        XCTAssertEqual(
            parse(nil, nil, " Off\n"),
            VocelloQwen3ReferenceParity(fullTextConditioning: false, filtersEOS: true, float32Sampling: false)
        )
        XCTAssertEqual(
            parse("1", "no", "no"),
            VocelloQwen3ReferenceParity(fullTextConditioning: true, filtersEOS: false, float32Sampling: false)
        )
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
            let policy = Qwen3TalkerSamplingOverride.samplingConfiguration(requestedSeed: 7, variation: variation)
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
            variation: .expressive
        )
        let second = Qwen3TalkerSamplingOverride.samplingConfiguration(
            requestedSeed: nil,
            variation: .expressive
        )

        XCTAssertNil(first.seed)
        XCTAssertNil(second.seed)
        XCTAssertNotEqual(first.effectiveSeed, second.effectiveSeed)
    }
}
