// Token sampling of the Qwen3-TTS runtime: the sampler scratch and `sampleToken`.
// Moved out of Qwen3TTS.swift unchanged (RF-46).

import CryptoKit
import Foundation
import Hub
import HuggingFace
@preconcurrency import MLX
import MLXAudioCore
@preconcurrency import MLXLMCommon
import MLXNN
import os
import Tokenizers

extension Qwen3TTSModel {
    final class Qwen3SamplerScratch {
        let vocabSize: Int
        let negInfScalar: MLXArray
        let arangeIndices: MLXArray

        private var suppressBaseArr: MLXArray?
        private var suppressBaseNegInf: MLXArray?
        private var suppressWithEOSArr: MLXArray?
        private var suppressWithEOSNegInf: MLXArray?

        /// First-seen order of the penalized token IDs; the cached MLX index
        /// array is built from it. The set answers membership in constant time
        /// and always holds exactly the buffer's elements.
        private(set) var repetitionTokenIDsBuffer: [Int32] = []
        private var repetitionTokenIDSet: Set<Int32> = []
        private var repetitionTokenIDsMLX: MLXArray?

        init(vocabSize: Int) {
            self.vocabSize = vocabSize
            negInfScalar = MLXArray(-Float.infinity)
            arangeIndices = MLXArray(0 ..< vocabSize).reshaped(1, -1).asType(Int32.self)
        }

        func prepareSuppressPairs(base: [Int], withEOS: [Int], dtype: DType) {
            if base.isEmpty {
                suppressBaseArr = nil
                suppressBaseNegInf = nil
            } else {
                suppressBaseArr = MLXArray(base.map { Int32($0) }).reshaped(1, -1)
                suppressBaseNegInf = MLXArray.full(
                    [1, base.count],
                    values: negInfScalar,
                    dtype: dtype
                )
            }
            if withEOS.isEmpty {
                suppressWithEOSArr = nil
                suppressWithEOSNegInf = nil
            } else {
                suppressWithEOSArr = MLXArray(withEOS.map { Int32($0) }).reshaped(1, -1)
                suppressWithEOSNegInf = MLXArray.full(
                    [1, withEOS.count],
                    values: negInfScalar,
                    dtype: dtype
                )
            }
        }

        func suppressArrays(allowsEOS: Bool) -> (MLXArray, MLXArray)? {
            // When EOS is *allowed*, we must not include it in the suppress list,
            // otherwise the model can never terminate and runs to maxTokens.
            if allowsEOS {
                guard let suppressBaseArr, let suppressBaseNegInf else { return nil }
                return (suppressBaseArr, suppressBaseNegInf)
            }
            guard let suppressWithEOSArr, let suppressWithEOSNegInf else { return nil }
            return (suppressWithEOSArr, suppressWithEOSNegInf)
        }

        func appendRepetitionTokenID(_ tokenID: Int) {
            let value = Int32(tokenID)
            // A repeated ID keeps the order and the cached index array.
            guard repetitionTokenIDSet.insert(value).inserted else { return }
            repetitionTokenIDsBuffer.append(value)
            repetitionTokenIDsMLX = nil
        }

        func repetitionTokenMLXArray(vocabUpperBound: Int) -> MLXArray? {
            guard !repetitionTokenIDsBuffer.isEmpty else { return nil }
            if repetitionTokenIDsMLX == nil {
                let filtered = repetitionTokenIDsBuffer.filter { Int($0) < vocabUpperBound }
                guard !filtered.isEmpty else { return nil }
                repetitionTokenIDsMLX = MLXArray(filtered).reshaped(1, -1)
            }
            return repetitionTokenIDsMLX
        }

        // Single-slot/per-count caches below: sampler shapes are constant for a
        // whole generation (batch 1, fixed vocab, fixed topK), so the per-token
        // rebuilds were pure allocator + graph-build churn. All consumers
        // (putAlong/which/takeAlong) are functional — cached inputs are never
        // mutated.
        private var zerosCache: MLXArray?
        private var zerosCacheShape: [Int] = []

        func zerosInt32(matching shape: [Int]) -> MLXArray {
            if shape == zerosCacheShape, let zerosCache { return zerosCache }
            let zeros = MLXArray.zeros(shape, type: Int32.self)
            zerosCache = zeros
            zerosCacheShape = shape
            return zeros
        }

        private var negInfRowCache: [Int: MLXArray] = [:]
        private var negInfRowDType: DType?

        /// `[1, count]` of -inf in the logits dtype (topK mask block / topP full row).
        func negInfRow(count: Int, dtype: DType) -> MLXArray {
            if negInfRowDType != dtype {
                negInfRowCache.removeAll()
                negInfRowDType = dtype
            }
            if let cached = negInfRowCache[count] { return cached }
            let row = MLXArray.full([1, count], values: negInfScalar, dtype: dtype)
            negInfRowCache[count] = row
            return row
        }

        private var eosIndexCache: MLXArray?
        private var eosIndexValue: Int = .min

        func eosIndex(_ tokenID: Int) -> MLXArray {
            if tokenID == eosIndexValue, let eosIndexCache { return eosIndexCache }
            let index = MLXArray([Int32(tokenID)]).reshaped(1, 1)
            eosIndexCache = index
            eosIndexValue = tokenID
            return index
        }
    }

    /// AQ-04: the entropy (nats) and EOS probability of one step's talker
    /// distribution over the codec codebook and EOS, from the raw logits (before
    /// suppression, repetition penalty, temperature or truncation): the model's
    /// own belief, whatever the sampler then does. Two lazy scalars; the caller
    /// evaluates them with the step's graph. Sampling never reads them.
    static func introspectionScalars(
        _ logits: MLXArray,
        codecVocabularySize: Int,
        eosTokenId: Int
    ) -> (entropy: MLXArray, eosProbability: MLXArray) {
        let step = logits[0..., (-1)..., 0...].squeezed(axis: 1).asType(.float32)
        let joint = concatenated(
            [step[0..., 0 ..< codecVocabularySize], step[0..., eosTokenId ..< (eosTokenId + 1)]],
            axis: -1
        )
        let logProbabilities = joint - logSumExp(joint, axis: -1, keepDims: true)
        let entropy = -(exp(logProbabilities) * logProbabilities).sum()
        let eosProbability = exp(logProbabilities[0..., codecVocabularySize...]).sum()
        return (entropy, eosProbability)
    }

    /// `introspectionScalars` compiled for one generation's vocabulary layout:
    /// `[logits]` in, `[entropy, eosProbability]` out. Built once per generation.
    static func compiledIntrospectionScalars(
        codecVocabularySize: Int,
        eosTokenId: Int
    ) -> @Sendable ([MLXArray]) -> [MLXArray] {
        compile { (arrays: [MLXArray]) -> [MLXArray] in
            let scalars = Qwen3TTSModel.introspectionScalars(
                arrays[0],
                codecVocabularySize: codecVocabularySize,
                eosTokenId: eosTokenId
            )
            return [scalars.entropy, scalars.eosProbability]
        }
    }

    static func sampleToken(
        _ logits: MLXArray,
        temperature: Float = 0.9,
        topP: Float = 1.0,
        topK: Int = 50,
        repetitionPenalty: Float = 1.0,
        generatedTokenIDs: Set<Int>? = nil,
        suppressTokens: [Int]? = nil,
        eosTokenId: Int? = nil,
        minP: Float = 0.0,
        scratch: Qwen3SamplerScratch? = nil,
        allowsEOS: Bool = true,
        castsLogitsToFloat32: Bool = true,
        reinsertsEOSAfterFiltering: Bool = !Qwen3ReferenceParity.production.filtersEOS,
        observe: ((MLXArray, MLXArray, MLXArray?, MLXArray) -> Void)? = nil
    ) -> MLXArray {
        var logitsSlice = logits[0..., (-1)..., 0...].squeezed(axis: 1) // [batch, vocab_size]
        // RF-14 D3: the reference samples from float32 logits, and so does
        // production since 2026-10-13 (the generate loop passes true).
        if castsLogitsToFloat32, logitsSlice.dtype != .float32 {
            logitsSlice = logitsSlice.asType(.float32)
        }

        // Suppress tokens by setting to -inf
        if let scratch {
            if let (suppressArr, negInf) = scratch.suppressArrays(allowsEOS: allowsEOS) {
                logitsSlice = putAlong(logitsSlice, suppressArr, values: negInf, axis: -1)
            }
        } else if let suppress = suppressTokens, !suppress.isEmpty {
            let suppressArr = MLXArray(suppress.map { Int32($0) }).reshaped(1, -1)
            let negInf = MLXArray.full(
                [1, suppress.count],
                values: MLXArray(-Float.infinity),
                dtype: logitsSlice.dtype
            )
            logitsSlice = putAlong(logitsSlice, suppressArr, values: negInf, axis: -1)
        }

        // Repetition penalty
        if repetitionPenalty != 1.0 {
            let tokenIds: MLXArray?
            if let scratch {
                tokenIds = scratch.repetitionTokenMLXArray(vocabUpperBound: logitsSlice.dim(-1))
            } else if let tokenIDs = generatedTokenIDs, !tokenIDs.isEmpty {
                let unique = tokenIDs.filter { $0 < logitsSlice.dim(-1) }
                tokenIds = unique.isEmpty
                    ? nil
                    : MLXArray(unique.map { Int32($0) }).reshaped(1, -1)
            } else {
                tokenIds = nil
            }
            if let tokenIds {
                let selected = takeAlong(logitsSlice, tokenIds, axis: -1)
                let penalized = which(
                    selected .< 0,
                    selected * repetitionPenalty,
                    selected / repetitionPenalty
                )
                logitsSlice = putAlong(logitsSlice, tokenIds, values: penalized, axis: -1)
            }
        }

        // Greedy if temperature 0
        if temperature <= 0 {
            let token = argMax(logitsSlice, axis: -1, keepDims: true)
            observe?(logits, logitsSlice, nil, token)
            return token
        }

        // Sampling-order fix (ported from upstream mlx-audio a730a68, #735):
        // scale by temperature BEFORE the truncation filters so top-p/min-p
        // operate on the tempered distribution that is actually sampled.
        // Filtering raw logits and dividing by temperature only at the final
        // categorical() made the nucleus temperature-blind — wrong (too
        // narrow/wide) truncation for any temperature ≠ 1 once topP < 1 or
        // minP > 0 is in play. top-k is rank-based and unaffected either way.
        // The final categorical() therefore samples at T = 1.0 below.
        if temperature != 1.0 {
            logitsSlice = logitsSlice / temperature
        }

        // RF-14 D2: production filters EOS like any token, as the reference does
        // (RF-18 follow-up screen, 2026-10-20). Re-insertion keeps the EOS logit
        // past top-k/top-p/min-p; it remains for QWENVOICE_TALKER_FILTER_EOS=off.
        let eosLogit: MLXArray? = if reinsertsEOSAfterFiltering,
            let eosTokenId, eosTokenId >= 0, eosTokenId < logitsSlice.dim(-1) {
            logitsSlice[0..., eosTokenId ..< (eosTokenId + 1)]
        } else {
            nil
        }

        // Apply top-k filtering (match mlx_lm.apply_top_k ordering and masking semantics)
        var filteredLogits = logitsSlice
        let vocabSize = logitsSlice.dim(-1)
        if topK > 0, topK < vocabSize {
            let kth = min(topK - 1, max(vocabSize - 1, 0))
            if kth >= 0 {
                let maskIdx = argPartition(-logitsSlice, kth: kth, axis: -1)[0..., topK...]
                let negInf: MLXArray
                if let scratch, maskIdx.dim(0) == 1 {
                    negInf = scratch.negInfRow(count: maskIdx.dim(-1), dtype: logitsSlice.dtype)
                } else {
                    negInf = MLXArray.full(
                        maskIdx.shape,
                        values: scratch?.negInfScalar ?? MLXArray(-Float.infinity),
                        dtype: logitsSlice.dtype
                    )
                }
                filteredLogits = putAlong(filteredLogits, maskIdx, values: negInf, axis: -1)
            }
        }

        // Apply top-p (nucleus) sampling
        if topP > 0, topP < 1.0 {
            let probs = softmax(filteredLogits, axis: -1)

            // Sort in ASCENDING order (like Python)
            let sortedIndices = argSort(filteredLogits, axis: -1)
            let sortedProbs = takeAlong(probs, sortedIndices, axis: -1)

            // Cumulative probabilities
            let cumProbs = cumsum(sortedProbs, axis: -1)

            // Rearrange cumulative probs back to original order
            // Create inverse index mapping using putAlong
            let sortedVocabSize = sortedIndices.dim(-1)
            let arangeIndices = scratch?.arangeIndices[0..., 0 ..< sortedVocabSize]
                ?? MLXArray(0 ..< sortedVocabSize).reshaped(1, -1).asType(Int32.self)
            let zeros = scratch?.zerosInt32(matching: sortedIndices.shape)
                ?? MLXArray.zeros(sortedIndices.shape, type: Int32.self)
            let inverseIndices = putAlong(zeros, sortedIndices, values: arangeIndices, axis: -1)
            let cumProbsOrigOrder = takeAlong(cumProbs, inverseIndices, axis: -1)

            // Mask tokens where cumulative prob > (1 - top_p)
            // Keep tokens that are in the top_p nucleus
            let threshold = 1.0 - topP
            let mask = cumProbsOrigOrder .> threshold
            let negInf: MLXArray
            if let scratch, filteredLogits.dim(0) == 1 {
                negInf = scratch.negInfRow(count: filteredLogits.dim(-1), dtype: filteredLogits.dtype)
            } else {
                negInf = MLXArray.full(
                    filteredLogits.shape,
                    values: scratch?.negInfScalar ?? MLXArray(-Float.infinity),
                    dtype: filteredLogits.dtype
                )
            }
            filteredLogits = which(mask, filteredLogits, negInf)
        }

        // Apply min-p sampling behavior (default kept at 0.0 for now)
        if minP > 0.0 {
            let scaledMinP = Float(log(Double(minP)))
            // Indices sorted in descending order (like Python `argsort(-logits)`)
            let sortedIndices = argSort(-filteredLogits, axis: -1)
            let sortedLogits = takeAlong(filteredLogits, sortedIndices, axis: -1)
            let topLogits = sortedLogits[0..., 0 ..< 1]
            let scaledMinPArray = MLXArray.full(
                topLogits.shape,
                values: MLXArray(scaledMinP),
                dtype: sortedLogits.dtype
            ) + topLogits
            let removeMask = sortedLogits .< scaledMinPArray
            let negInf = MLXArray.full(
                sortedLogits.shape,
                values: scratch?.negInfScalar ?? MLXArray(-Float.infinity),
                dtype: sortedLogits.dtype
            )
            let filteredSortedLogits = which(removeMask, negInf, sortedLogits)

            let invArange = scratch?.arangeIndices
                ?? MLXArray(0 ..< vocabSize).reshaped(1, -1).asType(Int32.self)
            let inverseIndices = putAlong(
                scratch?.zerosInt32(matching: sortedIndices.shape)
                    ?? MLXArray.zeros(sortedIndices.shape, type: Int32.self),
                sortedIndices,
                values: invArange,
                axis: -1
            )
            filteredLogits = takeAlong(filteredSortedLogits, inverseIndices, axis: -1)
        }

        if let eosLogit, let eosTokenId {
            let eosIdx = scratch?.eosIndex(eosTokenId) ?? MLXArray([Int32(eosTokenId)]).reshaped(1, 1)
            filteredLogits = putAlong(filteredLogits, eosIdx, values: eosLogit, axis: -1)
        }

        // Logits are already temperature-scaled above — sample at T = 1.0.
        // Internal test observation resolves exactly the key categorical would
        // consume, once. The ordinary path and lazy evaluation remain unchanged.
        let token: MLXArray
        if let observe {
            let key = resolve(key: MLXArray?.none)
            token = categorical(filteredLogits, key: key)
            observe(logits, filteredLogits, key, token)
        } else {
            token = categorical(filteredLogits)
        }
        return token.reshaped(1, 1)
    }
}
