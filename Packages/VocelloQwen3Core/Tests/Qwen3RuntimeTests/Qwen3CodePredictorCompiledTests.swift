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

    // MARK: - Sampling inside a pass (RF-46)

    /// A plan whose passes sample must draw exactly the codes the eager
    /// sampler draws from the same passes' logits under the same random
    /// state: same keys, in the same order, frame after frame.
    func testPassesThatSampleDrawTheEagerSamplersCodes() throws {
        let config = try makeConfig(numCodeGroups: 16, hidden: 16)
        let passCount = config.numCodeGroups - 1
        let stage = Qwen3SamplingStage(temperature: 0.9, topP: 1, topK: 8, minP: 0)
        let sampling = try XCTUnwrap(CompiledPassSampling.eligible(
            stage: stage, castsLogitsToFloat32: true, vocabSize: config.vocabSize
        ))

        for dtype in [DType.float32, .bfloat16] {
            // The predictor's own weights take the dtype, as a shipped
            // checkpoint's do, so the bf16 leg samples from bf16 logits and
            // runs the float32 cast production runs.
            MLXRandom.seed(0x5A3D_0046)
            let predictor = Qwen3TTSCodePredictor(config: config, talkerHiddenSize: 16)
            predictor.update(parameters: predictor.parameters().mapValues { $0.asType(dtype) })
            eval(predictor)
            let probe = CodePredictorCompiledPlan(predictor: predictor, dtype: dtype).run(
                pass: 0,
                codeHidden: MLXArray.zeros([1, 1, 16], dtype: dtype),
                code0Embed: MLXArray.zeros([1, 1, 16], dtype: dtype),
                token: nil
            )
            XCTAssertEqual(probe.dtype, dtype, "the pass's logits carry the model's dtype")
            func frameInputs(_ frame: Int) -> (hidden: MLXArray, embed: MLXArray) {
                let keys = MLXRandom.split(key: MLXRandom.key(UInt64(31_000 + frame)), into: 2)
                return (
                    MLXRandom.normal([1, 1, 16], key: keys[0]).asType(dtype),
                    MLXRandom.normal([1, 1, 16], key: keys[1]).asType(dtype)
                )
            }

            // Reference: logits from a plan that does not sample, then the eager sampler.
            let logitsPlan = CodePredictorCompiledPlan(predictor: predictor, dtype: dtype)
            let scratch = Qwen3TTSModel.Qwen3SamplerScratch(vocabSize: config.vocabSize)
            var expected: [[UInt32]] = []
            withRandomState(MLXRandom.RandomState(seed: 20_261_111)) {
                for frame in 0 ..< 3 {
                    let inputs = frameInputs(frame)
                    var codes: [MLXArray] = []
                    for pass in 0 ..< passCount {
                        let logits = pass == 0
                            ? logitsPlan.run(pass: 0, codeHidden: inputs.hidden, code0Embed: inputs.embed, token: nil)
                            : logitsPlan.run(pass: pass, codeHidden: nil, code0Embed: nil, token: codes[pass - 1])
                        codes.append(Qwen3TTSModel.sampleToken(
                            logits, temperature: stage.temperature, topP: stage.topP, topK: stage.topK,
                            minP: stage.minP, scratch: scratch, castsLogitsToFloat32: true
                        ))
                    }
                    eval(codes)
                    expected.append(codes.map { $0.asType(.uint32).item(UInt32.self) })
                }
            }

            // The plan under test: each pass samples on a key resolved where
            // the eager sampler resolves its own.
            let samplingPlan = CodePredictorCompiledPlan(predictor: predictor, dtype: dtype, sampling: sampling)
            var drawn: [[UInt32]] = []
            withRandomState(MLXRandom.RandomState(seed: 20_261_111)) {
                for frame in 0 ..< 3 {
                    let inputs = frameInputs(frame)
                    var codes: [MLXArray] = []
                    for pass in 0 ..< passCount {
                        let key = resolve(key: MLXArray?.none)
                        codes.append(pass == 0
                            ? samplingPlan.run(
                                pass: 0, codeHidden: inputs.hidden, code0Embed: inputs.embed, token: nil, key: key)
                            : samplingPlan.run(
                                pass: pass, codeHidden: nil, code0Embed: nil, token: codes[pass - 1], key: key))
                    }
                    eval(codes)
                    XCTAssertTrue(codes.allSatisfy { $0.shape == [1, 1] })
                    drawn.append(codes.map { $0.asType(.uint32).item(UInt32.self) })
                }
            }

            XCTAssertEqual(drawn, expected, "\(dtype)")
            XCTAssertGreaterThan(Set(drawn.flatMap { $0 }).count, 3, "the draws are not degenerate")
        }
    }

    /// Only the plain temperature and top-k stage samples inside a pass; any
    /// other stage keeps the eager sampler, which implements all of them.
    func testOnlyThePlainTopKStageSamplesInsideAPass() {
        func eligible(_ temperature: Float, _ topP: Float, _ topK: Int, _ minP: Float) -> Bool {
            CompiledPassSampling.eligible(
                stage: Qwen3SamplingStage(temperature: temperature, topP: topP, topK: topK, minP: minP),
                castsLogitsToFloat32: true, vocabSize: 2_048
            ) != nil
        }
        XCTAssertTrue(eligible(0.9, 1, 50, 0), "the production subtalker stage")
        XCTAssertTrue(eligible(1, 1, 50, 0))
        XCTAssertTrue(eligible(0.9, 0, 50, 0), "top-p of 0 is off in the eager sampler too")
        XCTAssertFalse(eligible(0, 1, 50, 0), "greedy")
        XCTAssertFalse(eligible(0.9, 0.95, 50, 0), "nucleus")
        XCTAssertFalse(eligible(0.9, 1, 50, 0.05), "min-p")
        XCTAssertFalse(eligible(0.9, 1, 0, 0), "no top-k")
        XCTAssertFalse(eligible(0.9, 1, 2_048, 0), "a top-k that keeps everything")
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
