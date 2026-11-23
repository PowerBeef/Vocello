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

    // MARK: - The frame as one function (RF-46)

    /// The frame function must draw exactly the codes the eager sampler draws
    /// from the per-pass logits under the same random state (same keys, same
    /// order, frame after frame) and return the loop's embedding sum.
    func testTheFrameFunctionDrawsTheEagerSamplersCodesAndTheLoopsEmbeddingSum() throws {
        let config = try makeConfig(numCodeGroups: 16, hidden: 16)
        let passCount = config.numCodeGroups - 1
        let stage = Qwen3SamplingStage(temperature: 0.9, topP: 1, topK: 8, minP: 0)
        let sampling = try XCTUnwrap(CompiledPassSampling.eligible(
            stage: stage, castsLogitsToFloat32: true, vocabSize: config.vocabSize
        ))

        // Equal widths, and a wider talker, whose hidden state the predictor
        // projects before every pass (the shipped models' shape).
        for (dtype, talkerHidden) in [(DType.float32, 16), (.bfloat16, 16), (.bfloat16, 24)] {
            // The predictor's own weights take the dtype, as a shipped
            // checkpoint's do, so the bf16 legs sample from bf16 logits and
            // run the float32 cast production runs.
            MLXRandom.seed(0x5A3D_0046)
            let predictor = Qwen3TTSCodePredictor(config: config, talkerHiddenSize: talkerHidden)
            XCTAssertEqual(predictor.projection != nil, talkerHidden != 16)
            predictor.update(parameters: predictor.parameters().mapValues { $0.asType(dtype) })
            eval(predictor)
            let probe = CodePredictorCompiledPlan(predictor: predictor, dtype: dtype).run(
                pass: 0,
                codeHidden: MLXArray.zeros([1, 1, talkerHidden], dtype: dtype),
                code0Embed: MLXArray.zeros([1, 1, talkerHidden], dtype: dtype),
                token: nil
            )
            XCTAssertEqual(probe.dtype, dtype, "the pass's logits carry the model's dtype")
            func frameInputs(_ frame: Int) -> (hidden: MLXArray, embed: MLXArray) {
                let keys = MLXRandom.split(key: MLXRandom.key(UInt64(31_000 + frame)), into: 2)
                return (
                    MLXRandom.normal([1, 1, talkerHidden], key: keys[0]).asType(dtype),
                    MLXRandom.normal([1, 1, talkerHidden], key: keys[1]).asType(dtype)
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

            // The plan under test: the frame function, on keys resolved in
            // pass order where the eager sampler resolves its own. Its sum
            // must be the loop's left fold over the same embeddings.
            let samplingPlan = CodePredictorCompiledPlan(predictor: predictor, dtype: dtype, sampling: sampling)
            var drawn: [[UInt32]] = []
            withRandomState(MLXRandom.RandomState(seed: 20_261_111)) {
                for frame in 0 ..< 3 {
                    let inputs = frameInputs(frame)
                    let keys = (0 ..< passCount).map { _ in resolve(key: MLXArray?.none) }
                    let result = samplingPlan.runFrame(
                        codeHidden: inputs.hidden, code0Embed: inputs.embed, keys: keys
                    )
                    var expectedSum = inputs.embed
                    for (index, code) in result.codes.enumerated() {
                        expectedSum = expectedSum + predictor.codecEmbedding[index](code)
                    }
                    eval(result.codes + [result.embeddingSum, expectedSum])
                    XCTAssertEqual(result.codes.count, passCount)
                    XCTAssertTrue(result.codes.allSatisfy { $0.shape == [1, 1] })
                    XCTAssertEqual(result.embeddingSum.shape, inputs.embed.shape)
                    XCTAssertEqual(result.embeddingSum.dtype, expectedSum.dtype)
                    XCTAssertEqual(
                        result.embeddingSum.asType(.float32).asArray(Float.self).map(\.bitPattern),
                        expectedSum.asType(.float32).asArray(Float.self).map(\.bitPattern),
                        "the embedding sum, frame \(frame), \(dtype)"
                    )
                    drawn.append(result.codes.map { $0.asType(.uint32).item(UInt32.self) })
                }
            }

            XCTAssertEqual(drawn, expected, "\(dtype), talker width \(talkerHidden)")
            XCTAssertGreaterThan(Set(drawn.flatMap { $0 }).count, 3, "the draws are not degenerate")
        }
    }

    /// Only the plain temperature and top-k stage runs as the frame function;
    /// any other stage keeps the eager sampler, which implements all of them.
    func testOnlyThePlainTopKStageRunsAsTheFrameFunction() {
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

    /// RF-68 (B1.4): `CompiledPassSampling` must be `Hashable` for plan cache
    /// keys, `CodePredictorCompiledPlan` must not eagerly allocate unused
    /// per-pass KV buffers on `init` or `runFrame`, and `releasePerPassBuffers`
    /// must drop lazy buffers cleanly while allowing subsequent `run` calls.
    func testCompiledPassSamplingHashableAndLazyPerPassBuffers() throws {
        let firstSampling = CompiledPassSampling(temperature: 0.9, topK: 8, castsLogitsToFloat32: true)
        let equalSampling = CompiledPassSampling(temperature: 0.9, topK: 8, castsLogitsToFloat32: true)
        let otherSampling = CompiledPassSampling(temperature: 0.7, topK: 4, castsLogitsToFloat32: true)
        let samplingSet: Set<CompiledPassSampling> = [firstSampling, equalSampling, otherSampling]
        XCTAssertEqual(samplingSet.count, 2)

        let config = try makeConfig(numCodeGroups: 4, hidden: 16)
        let predictor = Qwen3TTSCodePredictor(config: config, talkerHiddenSize: 16)
        eval(predictor)
        let passCount = config.numCodeGroups - 1

        let framePlan = CodePredictorCompiledPlan(
            predictor: predictor, dtype: .float32, sampling: firstSampling
        )
        XCTAssertFalse(framePlan.hasAllocatedPerPassBuffers, "init must not eagerly allocate per-pass KV buffers")
        XCTAssertFalse(framePlan.hasCompiledFrame)

        let hidden = MLXRandom.normal([1, 1, 16], key: MLXRandom.key(1))
        let embed = MLXRandom.normal([1, 1, 16], key: MLXRandom.key(2))
        let keys = (0 ..< passCount).map { MLXRandom.key(UInt64(10 + $0)) }
        let frame = framePlan.runFrame(codeHidden: hidden, code0Embed: embed, keys: keys)
        eval(frame.codes + [frame.embeddingSum])
        XCTAssertTrue(framePlan.hasCompiledFrame)
        XCTAssertFalse(framePlan.hasAllocatedPerPassBuffers, "runFrame must never allocate per-pass KV buffers")

        let perPassPlan = CodePredictorCompiledPlan(predictor: predictor, dtype: .float32)
        XCTAssertFalse(perPassPlan.hasAllocatedPerPassBuffers, "per-pass KV buffers must allocate lazily")
        let firstLogits = perPassPlan.run(pass: 0, codeHidden: hidden, code0Embed: embed, token: nil)
        eval(firstLogits)
        XCTAssertTrue(perPassPlan.hasAllocatedPerPassBuffers)

        perPassPlan.releasePerPassBuffers()
        XCTAssertFalse(perPassPlan.hasAllocatedPerPassBuffers, "releasePerPassBuffers must drop transient KV arrays")

        let replayLogits = perPassPlan.run(pass: 0, codeHidden: hidden, code0Embed: embed, token: nil)
        eval(replayLogits)
        XCTAssertTrue(perPassPlan.hasAllocatedPerPassBuffers)
        XCTAssertEqual(
            firstLogits.asArray(Float.self).map(\.bitPattern),
            replayLogits.asArray(Float.self).map(\.bitPattern),
            "re-allocating lazy per-pass buffers must reproduce identical pass-0 logits"
        )
    }

    /// RF-68: tracing a hoisted `CodePredictorCompiledPlan` on one OS thread and
    /// releasing the model/plan on another OS thread (as Swift Concurrency
    /// cooperative threads routinely do across load/prewarm/unload) must release
    /// 100% of predictor and fused-projection weights from `Memory.activeMemory`
    /// even while the tracing thread stays alive.
    func testCrossThreadPlanDeinitReleasesPredictorWeightsWhileTraceThreadStaysAlive() throws {
        let json: [String: Any] = [
            "vocab_size": 1024,
            "hidden_size": 256,
            "intermediate_size": 512,
            "num_hidden_layers": 2,
            "num_attention_heads": 4,
            "num_key_value_heads": 2,
            "head_dim": 64,
            "hidden_act": "silu",
            "max_position_embeddings": 128,
            "rms_norm_eps": 1e-6,
            "rope_theta": 10_000,
            "attention_bias": false,
            "attention_dropout": 0,
            "num_code_groups": 4,
        ]
        let config = try JSONDecoder().decode(
            Qwen3TTSTalkerCodePredictorConfig.self,
            from: JSONSerialization.data(withJSONObject: json)
        )
        let sampling = CompiledPassSampling(temperature: 0.9, topK: 8, castsLogitsToFloat32: true)

        Memory.clearCache()
        let baselineActive = Memory.activeMemory

        final class Holder: @unchecked Sendable {
            var predictor: Qwen3TTSCodePredictor?
            var framePlan: CodePredictorCompiledPlan?
            var perPassPlan: CodePredictorCompiledPlan?
            var traceThreadID: ObjectIdentifier?
            var deinitThreadID: ObjectIdentifier?
            var peakActiveDuringTrace: Int = 0
        }
        let holder = Holder()
        let traceDone = DispatchSemaphore(value: 0)
        let allowTraceThreadExit = DispatchSemaphore(value: 0)
        let traceExited = DispatchSemaphore(value: 0)

        let traceThread = Thread {
            defer { traceExited.signal() }
            holder.traceThreadID = ObjectIdentifier(Thread.current)
            // Run in a nested function so ARC releases all local references on
            // `traceThread`'s stack before `allowTraceThreadExit.wait()`, even
            // under `-Onone` test builds.
            func buildAndTrace() {
                // `talkerHiddenSize: 512 != hidden_size: 256` exercises
                // `small_to_mtp_projection` (quantized `Linear` with `bias: true`),
                // matching the shipped 1.7B models' `2048 -> 1024` layout.
                let predictor = Qwen3TTSCodePredictor(config: config, talkerHiddenSize: 512)
                XCTAssertNotNil(predictor.projection)
                quantize(model: predictor, groupSize: 64, bits: 4)
                eval(predictor)
                let summary = predictor.fuseProjections()
                XCTAssertGreaterThan(summary.fusedGroupCount, 0)

                let framePlan = CodePredictorCompiledPlan(
                    predictor: predictor, dtype: .float32, sampling: sampling
                )
                let perPassPlan = CodePredictorCompiledPlan(predictor: predictor, dtype: .float32)

                let hidden = MLXRandom.normal([1, 1, 512], key: MLXRandom.key(7))
                let embed = MLXRandom.normal([1, 1, 512], key: MLXRandom.key(8))
                let keys = (0 ..< 3).map { MLXRandom.key(UInt64(20 + $0)) }
                let frame = framePlan.runFrame(codeHidden: hidden, code0Embed: embed, keys: keys)
                let pass0Logits = perPassPlan.run(
                    pass: 0, codeHidden: hidden, code0Embed: embed, token: nil
                )
                // Pass 1 has seqLen == 1, exercising both `fusedQKV`/`fusedGateUp`
                // and `codecEmbedding[0]` inside `compiledPass`.
                let pass1Logits = perPassPlan.run(
                    pass: 1, codeHidden: nil, code0Embed: nil,
                    token: MLXArray([Int32(0)]).reshaped(1, 1)
                )
                eval(frame.codes + [frame.embeddingSum, pass0Logits, pass1Logits])
                perPassPlan.releasePerPassBuffers()

                holder.peakActiveDuringTrace = Memory.activeMemory
                holder.predictor = predictor
                holder.framePlan = framePlan
                holder.perPassPlan = perPassPlan
            }
            buildAndTrace()
            traceDone.signal()
            // Keep the tracing thread (and its thread_local MLX CompileCache)
            // alive until after the memory assertion, matching Swift's
            // long-lived cooperative worker threads.
            allowTraceThreadExit.wait()
        }
        traceThread.start()
        traceDone.wait()
        defer {
            allowTraceThreadExit.signal()
            traceExited.wait()
        }

        let loadedDelta = holder.peakActiveDuringTrace - baselineActive
        XCTAssertGreaterThan(
            loadedDelta, 2 * 1024 * 1024,
            "synthetic quantized predictor must occupy > 2 MiB active MLX memory so retention is unmistakable"
        )

        let deinitDone = DispatchSemaphore(value: 0)
        let deinitThread = Thread {
            holder.deinitThreadID = ObjectIdentifier(Thread.current)
            holder.framePlan = nil
            holder.perPassPlan = nil
            holder.predictor = nil
            Memory.clearCache()
            deinitDone.signal()
        }
        deinitThread.start()
        deinitDone.wait()

        XCTAssertNotEqual(holder.traceThreadID, holder.deinitThreadID)
        let retainedAfterCrossThreadDeinit = Memory.activeMemory - baselineActive
        // Fused projections alone occupy 480 KiB on this fixture; `< 64 KiB`
        // fails decisively if either `parameters()` or `fusedQKV`/`fusedGateUp`
        // stops flowing through `compile(inputs:)`.
        XCTAssertLessThan(
            retainedAfterCrossThreadDeinit,
            64 * 1024,
            "cross-thread plan deinit leaked \(retainedAfterCrossThreadDeinit) bytes while tracing thread stayed alive"
        )
    }
}
