import MLX
@testable import MLXAudioTTS
import XCTest

/// Tests the same sampler invoked by the producer, with independently computed
/// expected distributions. No model weights, downloads or speech verdicts.
final class Qwen3SamplerBoundaryTests: XCTestCase {
    private func processed(_ values: [Float], temperature: Float = 1, topP: Float = 1,
        topK: Int = 0, penalty: Float = 1, history: Set<Int> = [], suppress: [Int] = [],
        eos: Int? = nil, minP: Float = 0, scratch: Qwen3TTSModel.Qwen3SamplerScratch? = nil,
        allowsEOS: Bool = true, castsToFloat32: Bool = false, reinsertsEOS: Bool = true) -> [Float] {
        var observed: MLXArray?
        _ = Qwen3TTSModel.sampleToken(MLXArray(values).reshaped(1, 1, -1), temperature: temperature,
            topP: topP, topK: topK, repetitionPenalty: penalty, generatedTokenIDs: history,
            suppressTokens: suppress, eosTokenId: eos, minP: minP, scratch: scratch,
            allowsEOS: allowsEOS, castsLogitsToFloat32: castsToFloat32,
            reinsertsEOSAfterFiltering: reinsertsEOS, observe: { _, filtered, _, _ in observed = filtered })
        return observed!.asArray(Float.self)
    }

    func testSuppressionSignedPenaltyAndDuplicateHistory() {
        let scratch = Qwen3TTSModel.Qwen3SamplerScratch(vocabSize: 5)
        scratch.prepareSuppressPairs(base: [4], withEOS: [3, 4], dtype: .float32)
        for id in [0, 1, 0, 1, 2] { scratch.appendRepetitionTokenID(id) }
        XCTAssertEqual(
            scratch.repetitionSeenMask(vocabUpperBound: 5)?.asArray(Bool.self),
            [true, true, true, false, false]
        )
        let expected: [Float] = [2, -4, 0, 1, -.infinity]
        XCTAssertEqual(processed([4, -2, 0, 1, 8], penalty: 2, history: [0, 1, 2], suppress: [4]), expected)
        XCTAssertEqual(processed([4, -2, 0, 1, 8], penalty: 2, scratch: scratch), expected)
        XCTAssertEqual(processed([4, -2, 0, 1, 8], penalty: 2, scratch: scratch, allowsEOS: false)[3], -.infinity)
    }

    /// RF-68 narrow A3 / AUD-11: fixed-shape GPU `seenMask` stays nil until the
    /// first in-range token, ignores out-of-range IDs, updates only for newly
    /// seen IDs, and accepts `nextToken` directly from greedy/stochastic draws.
    func testRepetitionSeenMaskUpdatesOnlyForNewInRangeIDsAndMatchesSetPath() {
        let scratch = Qwen3TTSModel.Qwen3SamplerScratch(vocabSize: 16)
        XCTAssertNil(scratch.repetitionSeenMask(vocabUpperBound: 16))
        scratch.appendRepetitionTokenID(-1)
        scratch.appendRepetitionTokenID(16)
        XCTAssertNil(scratch.repetitionSeenMask(vocabUpperBound: 16))

        var reference = Set<Int>()
        var cached: MLXArray?
        var updates = 0
        for step in 0..<96 {
            let id = (step * 7 + step / 5) % 13
            let isNew = reference.insert(id).inserted
            let tokenArray = step.isMultiple(of: 2)
                ? MLXArray([UInt32(id)]).reshaped(1, 1)
                : nil
            scratch.appendRepetitionTokenID(id, tokenArray: tokenArray)
            let mask = scratch.repetitionSeenMask(vocabUpperBound: 16)
            if isNew {
                XCTAssertFalse(mask === cached, "A new ID must update the GPU mask (step \(step))")
                updates += 1
            } else {
                XCTAssertTrue(mask === cached, "A repeated ID must keep the cached GPU mask (step \(step))")
            }
            cached = mask
        }
        XCTAssertEqual(updates, reference.count)
        XCTAssertEqual(cached?.shape, [1, 16])
        XCTAssertEqual(
            cached?.asArray(Bool.self),
            (0..<16).map { reference.contains($0) }
        )
        XCTAssertNil(scratch.repetitionSeenMask(vocabUpperBound: 0))
        XCTAssertEqual(
            scratch.repetitionSeenMask(vocabUpperBound: 8)?.asArray(Bool.self),
            (0..<8).map { reference.contains($0) }
        )
        XCTAssertEqual(
            scratch.repetitionSeenMask(vocabUpperBound: 20)?.asArray(Bool.self),
            (0..<20).map { $0 < 16 && reference.contains($0) }
        )

        // Wrong-shape or non-integer `tokenArray` falls back safely to the Int32 index.
        let fallbackScratch = Qwen3TTSModel.Qwen3SamplerScratch(vocabSize: 6)
        fallbackScratch.appendRepetitionTokenID(2, tokenArray: MLXArray([Int32(2), Int32(3)]).reshaped(1, 2))
        fallbackScratch.appendRepetitionTokenID(4, tokenArray: MLXArray([Float(4)]).reshaped(1, 1))
        XCTAssertEqual(
            fallbackScratch.repetitionSeenMask(vocabUpperBound: 6)?.asArray(Bool.self),
            [false, false, true, false, true, false]
        )

        // Greedy (argMax -> uint32) and stochastic (categorical -> uint32) `nextToken`
        // arrays update `seenMask` identically to `generatedTokenIDs: Set<Int>`,
        // preserving exact IEEE 754 bit patterns across positive, negative, +0.0,
        // -0.0, unseen, and suppressed -inf logits (float32, bfloat16, and batch > 1).
        let logits: [Float] = [2.5, -1.25, 0.0, -0.0, 4.0, -3.5, 1.0, 9.0]
        let greedyScratch = Qwen3TTSModel.Qwen3SamplerScratch(vocabSize: logits.count)
        greedyScratch.prepareSuppressPairs(base: [7], withEOS: [7], dtype: .float32)
        let greedyToken = Qwen3TTSModel.sampleToken(
            MLXArray(logits).reshaped(1, 1, -1),
            temperature: 0,
            repetitionPenalty: 1.5,
            scratch: greedyScratch
        )
        let greedyID = Int(greedyToken[0, 0].item(Int32.self))
        greedyScratch.appendRepetitionTokenID(greedyID, tokenArray: greedyToken)
        let stochasticToken = withRandomState(MLXRandom.RandomState(seed: 42)) {
            Qwen3TTSModel.sampleToken(
                MLXArray(logits).reshaped(1, 1, -1),
                temperature: 0.9,
                topP: 1.0,
                topK: 4,
                repetitionPenalty: 1.5,
                scratch: greedyScratch
            )
        }
        let stochasticID = Int(stochasticToken[0, 0].item(Int32.self))
        greedyScratch.appendRepetitionTokenID(stochasticID, tokenArray: stochasticToken)
        // Also mark negative, +0.0, -0.0, and suppressed -inf indices seen so every
        // IEEE 754 branch is verified bit-for-bit against `generatedTokenIDs`.
        let extraSeen = [1, 2, 3, 7]
        for id in extraSeen {
            greedyScratch.appendRepetitionTokenID(id)
        }
        let seenSet = Set([greedyID, stochasticID] + extraSeen)
        XCTAssertEqual(
            processed(logits, penalty: 1.5, scratch: greedyScratch).map(\.bitPattern),
            processed(logits, penalty: 1.5, history: seenSet, suppress: [7]).map(\.bitPattern)
        )

        // bfloat16 (`castsLogitsToFloat32: false`) and batch == 2 broadcast parity
        // (`temperature: 0` keeps `argMax` batch-preserving for `[2, 1, V]`).
        let batchLogits = MLXArray(logits + logits.reversed()).reshaped(2, 1, logits.count).asType(.bfloat16)
        let bf16Scratch = Qwen3TTSModel.Qwen3SamplerScratch(vocabSize: logits.count)
        for id in seenSet { bf16Scratch.appendRepetitionTokenID(id) }
        var scratchBF16: MLXArray?
        var setBF16: MLXArray?
        _ = Qwen3TTSModel.sampleToken(
            batchLogits,
            temperature: 0,
            topP: 1,
            topK: 0,
            repetitionPenalty: 1.5,
            scratch: bf16Scratch,
            castsLogitsToFloat32: false,
            observe: { _, filtered, _, _ in scratchBF16 = filtered }
        )
        _ = Qwen3TTSModel.sampleToken(
            batchLogits,
            temperature: 0,
            topP: 1,
            topK: 0,
            repetitionPenalty: 1.5,
            generatedTokenIDs: seenSet,
            castsLogitsToFloat32: false,
            observe: { _, filtered, _, _ in setBF16 = filtered }
        )
        XCTAssertEqual(scratchBF16?.shape, [2, logits.count])
        XCTAssertEqual(scratchBF16?.dtype, .bfloat16)
        XCTAssertEqual(setBF16?.dtype, .bfloat16)
        XCTAssertEqual(
            scratchBF16?.asType(.float32).asArray(Float.self).map(\.bitPattern),
            setBF16?.asType(.float32).asArray(Float.self).map(\.bitPattern)
        )
    }

    func testTemperaturePrecedesNucleusAndMinP() {
        // At T=.5 the top probability is .867: a .7 nucleus has one token.
        // At T=2 the top probability is .506: that nucleus needs two.
        XCTAssertEqual(processed([0, 1, 2], temperature: 0.5, topP: 0.7), [-.infinity, -.infinity, 4])
        XCTAssertEqual(processed([0, 1, 2], temperature: 2, topP: 0.7), [-.infinity, 0.5, 1])
        XCTAssertEqual(processed([0, 1, 2], temperature: 0.5, minP: 0.2), [-.infinity, -.infinity, 4])
        XCTAssertEqual(processed([0, 1, 2], temperature: 2, minP: 0.5), [-.infinity, 0.5, 1])
    }

    func testTopKTiesNucleusBoundaryAndEligibleEOSRestoration() {
        let tied = processed([1, 1, 1, 0], topK: 2)
        XCTAssertEqual(tied.filter(\.isFinite).count, 2)
        XCTAssertEqual(tied[3], -.infinity)
        XCTAssertEqual(processed([0, 0, 0, 0], topP: 0.5).filter(\.isFinite).count, 2)
        XCTAssertEqual(processed([4, 2, -4], topP: 0.1, topK: 1, eos: 2, minP: 0.9), [4, -.infinity, -4])
        XCTAssertEqual(processed([4, 2, -4], topK: 1, suppress: [2], eos: 2), [4, -.infinity, -.infinity])
        XCTAssertEqual(processed([4, 2, -4], temperature: 0, topK: 1, suppress: [0]), [-.infinity, 2, -4])
    }

    /// RF-14 D2: production filters EOS like any token, as the reference does
    /// (RF-18, 2026-10-20); the re-insertion arm puts an eligible EOS back after
    /// top-k, top-p and min-p. Without an EOS id the two paths are the same filter.
    func testReferenceEOSFilteringDropsTheReinsertion() {
        XCTAssertEqual(processed([4, 2, -4], topK: 1, eos: 2), [4, -.infinity, -4])
        XCTAssertEqual(processed([4, 2, -4], topK: 1, eos: 2, reinsertsEOS: false), [4, -.infinity, -.infinity])
        // An EOS inside the top-k survives either way.
        XCTAssertEqual(processed([4, 2, -4], topK: 2, eos: 1, reinsertsEOS: false), [4, 2, -.infinity])
        XCTAssertEqual(processed([4, 2, -4, 1], topK: 2, reinsertsEOS: false), processed([4, 2, -4, 1], topK: 2))
    }

    /// RF-14 D3: production and the reference cast logits to float32 whatever
    /// the model's precision; the model-precision arm keeps the model's dtype,
    /// and float32 logits are untouched either way.
    func testFloat32SamplingCastsOnlyLowerPrecisionLogits() {
        func filteredDType(_ logits: MLXArray, casts: Bool) -> DType {
            var observed: MLXArray?
            _ = Qwen3TTSModel.sampleToken(logits, temperature: 0.9, topP: 0.9, topK: 2, eosTokenId: 1,
                castsLogitsToFloat32: casts, observe: { _, filtered, _, _ in observed = filtered })
            return observed!.dtype
        }
        let bf16 = MLXArray([Float](arrayLiteral: 0.5, 1.25, -2, 3)).reshaped(1, 1, 4).asType(.bfloat16)
        XCTAssertEqual(filteredDType(bf16, casts: false), .bfloat16)
        XCTAssertEqual(filteredDType(bf16, casts: true), .float32)
        XCTAssertEqual(
            processed([0.5, 1.25, -2, 3], temperature: 0.9, topP: 0.9, topK: 2, castsToFloat32: true),
            processed([0.5, 1.25, -2, 3], temperature: 0.9, topP: 0.9, topK: 2)
        )

        // Through a scratch prepared as the generate loop prepares it (float32
        // suppress rows), cast bf16 logits stay float32 and match the float32 path.
        func throughScratch(_ logits: MLXArray, casts: Bool) -> MLXArray {
            let scratch = Qwen3TTSModel.Qwen3SamplerScratch(vocabSize: 4)
            scratch.prepareSuppressPairs(base: [3], withEOS: [2, 3], dtype: .float32)
            var observed: MLXArray?
            _ = Qwen3TTSModel.sampleToken(logits, temperature: 0.9, topP: 0.9, topK: 2, eosTokenId: 2,
                scratch: scratch, castsLogitsToFloat32: casts, observe: { _, filtered, _, _ in observed = filtered })
            return observed!
        }
        let cast = throughScratch(bf16, casts: true)
        XCTAssertEqual(cast.dtype, .float32)
        XCTAssertEqual(
            cast.asArray(Float.self),
            throughScratch(bf16.asType(.float32), casts: false).asArray(Float.self)
        )
        XCTAssertEqual(cast.asArray(Float.self)[3], -.infinity)
    }

    func testScratchAndObservationDoNotChangeSeededSequenceOrNextKey() {
        func run(observe: Bool, useScratch: Bool) -> ([Int32], [UInt32]) {
            withRandomState(MLXRandom.RandomState(seed: 38112001)) {
                let scratch = useScratch ? Qwen3TTSModel.Qwen3SamplerScratch(vocabSize: 8) : nil
                scratch?.prepareSuppressPairs(base: [7], withEOS: [7], dtype: .float32)
                var tokens: [Int32] = []
                var history: Set<Int> = []
                for _ in 0..<32 {
                    let token = Qwen3TTSModel.sampleToken(MLXArray([Float](arrayLiteral: 0, 1, 2, 3, 4, 3, 2, 9)).reshaped(1, 1, 8),
                        temperature: 0.9, topP: 0.9, topK: 5, repetitionPenalty: 1.05,
                        generatedTokenIDs: history, suppressTokens: [7], minP: 0.01, scratch: scratch,
                        observe: observe ? { raw, filtered, key, token in
                            eval(raw, filtered, key!, token)
                        } : nil)
                    let value = token.item(Int32.self)
                    tokens.append(value)
                    history.insert(Int(value))
                    scratch?.appendRepetitionTokenID(Int(value), tokenArray: token)
                }
                return (tokens, resolve(key: MLXArray?.none).asArray(UInt32.self))
            }
        }
        let baseline = run(observe: false, useScratch: false)
        for pair in [(true, false), (false, true), (true, true)] {
            let actual = run(observe: pair.0, useScratch: pair.1)
            XCTAssertEqual(actual.0, baseline.0)
            XCTAssertEqual(actual.1, baseline.1, "Observer must consume exactly one key per categorical draw")
        }
    }

    @MainActor
    func testOverlappingAsyncScopesPreserveActualSamplerDraws() async {
        // Cooperative suspension overlaps two request scopes, while all MLX work
        // stays on one actor. No arrays are transferred across tasks.
        func run(seed: UInt64, barrier: SamplerRoundBarrier? = nil) async -> ([Int32], [[UInt32]]) {
            let stage = Qwen3SamplingStage(temperature: 0.9, topP: 0.9, topK: 3, minP: 0)
            let policy = Qwen3RequestSamplingPolicy(effectiveSeed: seed, talker: stage,
                subtalker: stage, repetitionPenalty: 1.05, maximumCodecTokens: 32)
            return await policy.runWithRandomState(isolation: MainActor.shared) { @MainActor in
                var result: [Int32] = []
                var keys: [[UInt32]] = []
                for _ in 0..<32 {
                    let value = Qwen3TTSModel.sampleToken(MLXArray([Float](arrayLiteral: 0, 1, 2, 1)).reshaped(1, 1, 4),
                        temperature: stage.temperature, topP: stage.topP, topK: stage.topK,
                        observe: { _, _, key, _ in keys.append(key!.asArray(UInt32.self)) }).item(Int32.self)
                    result.append(value)
                    if let barrier { await barrier.wait() }
                }
                return (result, keys)
            }
        }
        let a = await run(seed: 123)
        let b = await run(seed: 456)
        let barrier = SamplerRoundBarrier()
        let first = Task { @MainActor in await run(seed: 123, barrier: barrier) }
        let second = Task { @MainActor in await run(seed: 456, barrier: barrier) }
        for _ in 0..<32 {
            _ = MLXRandom.categorical(MLXArray([Float](arrayLiteral: 1, 2, 3))).item(Int32.self)
            await barrier.wait()
        }
        let actualA = await first.value
        let actualB = await second.value
        XCTAssertEqual(actualA.0, a.0); XCTAssertEqual(actualB.0, b.0)
        XCTAssertEqual(actualA.1, a.1); XCTAssertEqual(actualB.1, b.1)
    }
}

/// Both request scopes and the unrelated caller must reach each round before
/// any advances. Unlike Task.yield, this proves overlapping suspension.
@MainActor
private final class SamplerRoundBarrier {
    private var waiters: [CheckedContinuation<Void, Never>] = []
    func wait() async {
        await withCheckedContinuation { continuation in
            waiters.append(continuation)
            if waiters.count == 3 {
                let ready = waiters
                waiters.removeAll(keepingCapacity: true)
                for waiter in ready { waiter.resume() }
            }
        }
    }
}
