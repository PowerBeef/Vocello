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
        XCTAssertEqual(policy.subtalker, policy.talker)
        // Shipped default; a different value requires the Stage 0.4 bench A/B
        // to win on deterministic QC first.
        XCTAssertEqual(policy.repetitionPenalty, 1.05, accuracy: 0.0001)
        // Production requests carry no EOS hold (the audio QC GEN-NOEOS knob is unset).
        XCTAssertNil(policy.eosSuppressionFrames)
        // Nor any RF-14 reference-parity arm (its knobs are unset).
        XCTAssertNil(policy.referenceParity)
        XCTAssertNoThrow(try policy.validated())
    }

    /// The RF-14 D1-D3 knobs: each turns its arm on only for an explicit on
    /// value, and no arm at all is the production configuration (nil).
    func testReferenceParityKnobsTurnOnOnlyTheirOwnArms() {
        let parse = Qwen3TalkerSamplingOverride.referenceParity
        XCTAssertNil(parse(nil, nil, nil))
        for off in ["", "off", "0", "false", "no", "full"] {
            XCTAssertNil(parse(off, off, off), off)
        }
        XCTAssertEqual(
            parse("on", nil, nil),
            VocelloQwen3ReferenceParity(fullTextConditioning: true, filtersEOS: false, float32Sampling: false)
        )
        XCTAssertEqual(
            parse(nil, " TRUE\n", nil),
            VocelloQwen3ReferenceParity(fullTextConditioning: false, filtersEOS: true, float32Sampling: false)
        )
        XCTAssertEqual(
            parse("1", "yes", "on"),
            VocelloQwen3ReferenceParity(fullTextConditioning: true, filtersEOS: true, float32Sampling: true)
        )
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
