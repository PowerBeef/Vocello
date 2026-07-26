import Foundation
import MLX
@testable import MLXAudioTTS
import MLXLMCommon
import XCTest

/// Stage 1 P1b: the static-shape compiled talker decode must reproduce the
/// eager growing-cache path — same logits and hidden states for every step,
/// including across a 256-token capacity-block crossing (re-trace) — and must
/// refuse to engage for non-plain cache experiments.
final class Qwen3TalkerCompiledTests: XCTestCase {
    private func makeTalker() throws -> Qwen3TTSTalkerForConditionalGeneration {
        let json: [String: Any] = [
            "vocab_size": 64,
            "hidden_size": 32,
            "intermediate_size": 64,
            "num_hidden_layers": 2,
            "num_attention_heads": 4,
            "num_key_value_heads": 2,
            "head_dim": 8,
            "text_hidden_size": 16,
            "text_vocab_size": 32,
            "code_predictor_config": [
                "vocab_size": 16,
                "hidden_size": 32,
                "intermediate_size": 64,
                "num_hidden_layers": 1,
                "num_attention_heads": 2,
                "num_key_value_heads": 1,
                "head_dim": 8,
                "num_code_groups": 2,
            ],
        ]
        let config = try JSONDecoder().decode(
            Qwen3TTSTalkerConfig.self,
            from: JSONSerialization.data(withJSONObject: json)
        )
        let talker = Qwen3TTSTalkerForConditionalGeneration(config: config)
        eval(talker)
        return talker
    }

    func testCompiledPlanMatchesEagerAcrossBlockCrossing() throws {
        let talker = try makeTalker()
        let hidden = talker.config.hiddenSize
        let prefillLength = 3

        // Shared prefill through the eager path, then clone the cache state
        // so both paths continue from identical positions.
        let key = MLXRandom.key(20_260_726)
        let keys = MLXRandom.split(key: key, into: 2)
        let prefillEmbeds = MLXRandom.normal([1, prefillLength, hidden], key: keys[0])
        let eagerCache = talker.makeCache()
        _ = talker(prefillEmbeds, cache: eagerCache)
        eval(eagerCache.flatMap { $0.innerState() })

        let planCache = talker.makeCache()
        for (source, target) in zip(eagerCache, planCache) {
            (target as! KVCacheSimple).state = (source as! KVCacheSimple).state
        }
        let plan = try XCTUnwrap(TalkerCompiledDecodePlan(
            talker: talker, prefillCache: planCache, dtype: .float32
        ))

        // 258 steps: positions 3...260 cross the initial 256 capacity block.
        var stepKey = keys[1]
        for step in 0 ..< 258 {
            let split = MLXRandom.split(key: stepKey, into: 2)
            stepKey = split[0]
            let embeds = MLXRandom.normal([1, 1, hidden], key: split[1])

            let (eagerLogits, eagerHidden) = talker(embeds, cache: eagerCache)
            let (planLogits, planHidden) = plan.step(embeds)
            eval(eagerLogits, eagerHidden, planLogits, planHidden)

            XCTAssertEqual(eagerLogits.shape, planLogits.shape, "step \(step)")
            // fp32 fusion-level tolerance only (P3 precedent): MLX compile
            // reorders fp32 rounding ~1e-6; the shipping bf16 model remains
            // byte-identical end-to-end (verified by the WAV identity gate).
            for (index, (e, c)) in zip(
                eagerLogits.asArray(Float.self), planLogits.asArray(Float.self)
            ).enumerated() {
                XCTAssertEqual(e, c, accuracy: 5e-5, "step \(step) logit \(index)")
            }
            for (index, (e, c)) in zip(
                eagerHidden.asArray(Float.self), planHidden.asArray(Float.self)
            ).enumerated() {
                XCTAssertEqual(e, c, accuracy: 5e-5, "step \(step) hidden \(index)")
            }
        }
    }

    func testPlanRefusesNonPlainCaches() throws {
        let talker = try makeTalker()
        let quantized: [any KVCache] = talker.model.layers.map { _ in
            QuantizedKVCache(groupSize: 64, bits: 4)
        }
        XCTAssertNil(TalkerCompiledDecodePlan(
            talker: talker, prefillCache: quantized, dtype: .float32
        ))
        let empty: [any KVCache] = talker.model.layers.map { _ in KVCacheSimple() }
        XCTAssertNil(TalkerCompiledDecodePlan(
            talker: talker, prefillCache: empty, dtype: .float32
        ))
    }
}
