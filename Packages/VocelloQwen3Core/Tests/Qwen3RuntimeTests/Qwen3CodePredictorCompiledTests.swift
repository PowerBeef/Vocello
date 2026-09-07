import Foundation
import MLX
@testable import MLXAudioTTS
import MLXLMCommon
import MLXNN
import XCTest

/// Stage 1 P3: the compiled per-pass code-predictor plan must reproduce the
/// eager module path within the declared fp32 tolerance, across repeated
/// frames (the eager path trims its cache to zero per frame; the compiled
/// plan overwrites baked buffer slices).
final class Qwen3CodePredictorCompiledTests: XCTestCase {
    private func makeConfig(numCodeGroups: Int, hidden: Int) throws -> Qwen3TTSTalkerCodePredictorConfig {
        let json: [String: Any] = [
            "vocab_size": 32,
            "hidden_size": hidden,
            "intermediate_size": 2 * hidden,
            "num_hidden_layers": 2,
            "num_attention_heads": 2,
            "num_key_value_heads": 1,
            "head_dim": 8,
            "hidden_act": "silu",
            "max_position_embeddings": 128,
            "rms_norm_eps": 1e-6,
            "rope_theta": 10_000,
            "attention_bias": false,
            "attention_dropout": 0,
            "num_code_groups": numCodeGroups,
        ]
        return try JSONDecoder().decode(
            Qwen3TTSTalkerCodePredictorConfig.self,
            from: JSONSerialization.data(withJSONObject: json)
        )
    }

    private func runEagerFrame(
        predictor: Qwen3TTSCodePredictor,
        cache: [any KVCache],
        constants: CodePredictorStepConstants,
        codeHidden: MLXArray,
        code0Embed: MLXArray,
        followTokens: [MLXArray]
    ) -> [MLXArray] {
        for layerCache in cache {
            _ = layerCache.trim(layerCache.offset)
        }
        var logits: [MLXArray] = []
        for pass in 0 ..< predictor.numCodeGroups - 1 {
            let input: MLXArray
            if pass == 0 {
                input = concatenated([codeHidden, code0Embed], axis: 1)
            } else {
                input = predictor.codecEmbedding[pass - 1](followTokens[pass - 1])
            }
            let (passLogits, _, _) = predictor(
                input, cache: cache, generationStep: pass, stepConstants: constants
            )
            logits.append(passLogits)
        }
        return logits
    }

    private func runCompiledFrame(
        plan: CodePredictorCompiledPlan,
        codeHidden: MLXArray,
        code0Embed: MLXArray,
        followTokens: [MLXArray],
        passCount: Int
    ) -> [MLXArray] {
        var logits: [MLXArray] = []
        for pass in 0 ..< passCount {
            let passLogits: MLXArray
            if pass == 0 {
                passLogits = plan.run(
                    pass: 0, codeHidden: codeHidden, code0Embed: code0Embed, token: nil
                )
            } else {
                passLogits = plan.run(
                    pass: pass, codeHidden: nil, code0Embed: nil, token: followTokens[pass - 1]
                )
            }
            logits.append(passLogits)
        }
        return logits
    }

    private func assertFramesMatch(talkerHidden: Int, cpHidden: Int) throws {
        let config = try makeConfig(numCodeGroups: 16, hidden: cpHidden)
        let predictor = Qwen3TTSCodePredictor(config: config, talkerHiddenSize: talkerHidden)
        eval(predictor)
        let passCount = config.numCodeGroups - 1

        let cache = predictor.makeCache()
        let constants = CodePredictorStepConstants()
        let plan = CodePredictorCompiledPlan(predictor: predictor, dtype: .float32)

        // Three frames with distinct inputs: later frames check per-frame
        // replay (eager trim-to-zero vs compiled slice overwrite) agrees.
        for frame in 0 ..< 3 {
            let key = MLXRandom.key(UInt64(20_260_726 + frame))
            let keys = MLXRandom.split(key: key, into: 2)
            let codeHidden = MLXRandom.normal([1, 1, talkerHidden], key: keys[0])
            let code0Embed = MLXRandom.normal([1, 1, talkerHidden], key: keys[1])
            let followTokens = (0 ..< passCount - 1).map { index in
                MLXArray([Int32((frame * 7 + index * 5) % config.vocabSize)]).reshaped(1, 1)
            }

            let eager = runEagerFrame(
                predictor: predictor, cache: cache, constants: constants,
                codeHidden: codeHidden, code0Embed: code0Embed, followTokens: followTokens
            )
            let compiled = runCompiledFrame(
                plan: plan, codeHidden: codeHidden, code0Embed: code0Embed,
                followTokens: followTokens, passCount: passCount
            )

            // One materialization boundary per complete frame, not per pass.
            // Forced codes isolate predictor arithmetic from categorical draws.
            eval(eager + compiled)

            for pass in 0 ..< passCount {
                XCTAssertEqual(eager[pass].shape, compiled[pass].shape, "frame \(frame) pass \(pass)")
                // MLX compile fuses elementwise/reduction chains, which
                // reorders fp32 rounding. This fixture does not establish
                // low-precision shipping-code or end-to-end audio identity.
                let eagerValues = eager[pass].asArray(Float.self)
                let compiledValues = compiled[pass].asArray(Float.self)
                for (index, (e, c)) in zip(eagerValues, compiledValues).enumerated() {
                    XCTAssertEqual(
                        e, c, accuracy: 2e-6,
                        "frame \(frame) pass \(pass) logit \(index) diverged"
                    )
                }
            }
        }
    }

    func testCompiledPlanMatchesEagerPathWithoutProjection() throws {
        try assertFramesMatch(talkerHidden: 16, cpHidden: 16)
    }

    func testCompiledPlanMatchesEagerPathWithProjection() throws {
        try assertFramesMatch(talkerHidden: 24, cpHidden: 16)
    }

    func testLowPrecisionAllPassesOverwritePriorFrameState() throws {
        // Bit identity is asserted only between fresh and reused *compiled*
        // plans. Eager/compiled production-dtype differences are measured by the
        // opt-in real-weight probe, not waived by an invented fp16 tolerance.
        for dtype: DType in [.float16, .bfloat16] {
            for talkerHidden in [16, 24] {
                let config = try makeConfig(numCodeGroups: 16, hidden: 16)
                let predictor = Qwen3TTSCodePredictor(config: config, talkerHiddenSize: talkerHidden)
                predictor.update(parameters: predictor.parameters().mapValues { $0.asType(dtype) })
                eval(predictor)
                let reused = CodePredictorCompiledPlan(predictor: predictor, dtype: dtype)
                for frame in 0..<3 {
                    let hidden = MLXRandom.normal([1, 1, talkerHidden], key: MLXRandom.key(UInt64(100 + frame))).asType(dtype)
                    let first = hidden * 0.5
                    let tokens = (0..<14).map { MLXArray([Int32(($0 + frame * 7) % 32)]).reshaped(1, 1) }
                    let a = runCompiledFrame(plan: reused, codeHidden: hidden, code0Embed: first,
                        followTokens: tokens, passCount: 15)
                    let fresh = CodePredictorCompiledPlan(predictor: predictor, dtype: dtype)
                    let b = runCompiledFrame(plan: fresh, codeHidden: hidden, code0Embed: first,
                        followTokens: tokens, passCount: 15)
                    eval(a + b)
                    for pass in 0..<15 {
                        let values = a[pass].asType(.float32).asArray(Float.self)
                        XCTAssertEqual(a[pass].dtype, dtype)
                        XCTAssertTrue(values.allSatisfy(\.isFinite))
                        XCTAssertEqual(values, b[pass].asType(.float32).asArray(Float.self),
                            "\(dtype) projection \(talkerHidden != 16) frame \(frame) pass \(pass)")
                    }
                }
            }
        }
    }
}
