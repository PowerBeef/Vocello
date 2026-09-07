import MLX
@testable import MLXAudioTTS
import XCTest

/// Tests the same sampler invoked by the producer, with independently computed
/// expected distributions. No model weights, downloads or speech verdicts.
final class Qwen3SamplerBoundaryTests: XCTestCase {
    private func processed(_ values: [Float], temperature: Float = 1, topP: Float = 1,
        topK: Int = 0, penalty: Float = 1, history: Set<Int> = [], suppress: [Int] = [],
        eos: Int? = nil, minP: Float = 0, scratch: Qwen3TTSModel.Qwen3SamplerScratch? = nil,
        allowsEOS: Bool = true) -> [Float] {
        var observed: MLXArray?
        _ = Qwen3TTSModel.sampleToken(MLXArray(values).reshaped(1, 1, -1), temperature: temperature,
            topP: topP, topK: topK, repetitionPenalty: penalty, generatedTokenIDs: history,
            suppressTokens: suppress, eosTokenId: eos, minP: minP, scratch: scratch,
            allowsEOS: allowsEOS, observe: { _, filtered, _, _ in observed = filtered })
        return observed!.asArray(Float.self)
    }

    func testSuppressionSignedPenaltyAndDuplicateHistory() {
        let scratch = Qwen3TTSModel.Qwen3SamplerScratch(vocabSize: 5)
        scratch.prepareSuppressPairs(base: [4], withEOS: [3, 4], dtype: .float32)
        for id in [0, 1, 0, 1, 2] { scratch.appendRepetitionTokenID(id) }
        XCTAssertEqual(scratch.repetitionTokenIDsBuffer, [0, 1, 2])
        let expected: [Float] = [2, -4, 0, 1, -.infinity]
        XCTAssertEqual(processed([4, -2, 0, 1, 8], penalty: 2, history: [0, 1, 2], suppress: [4]), expected)
        XCTAssertEqual(processed([4, -2, 0, 1, 8], penalty: 2, scratch: scratch), expected)
        XCTAssertEqual(processed([4, -2, 0, 1, 8], penalty: 2, scratch: scratch, allowsEOS: false)[3], -.infinity)
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
                    tokens.append(value); history.insert(Int(value)); scratch?.appendRepetitionTokenID(Int(value))
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
