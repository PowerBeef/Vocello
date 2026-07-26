import Foundation
@preconcurrency import MLX
@preconcurrency import MLXLMCommon
import MLXNN

// MARK: - Compiled static-shape talker decode (Stage 1 P1b, branch experiment)
//
// The talker's per-token decode rebuilds a 28-layer op graph on the host every
// step while the fused eval's GPU busy sits near 60% (§M stage-exit capture:
// batch-1 launch gaps). This plan compiles the decode step once per KV
// capacity block and replays it, following the P3 pattern.
//
// What makes a single compiled function per capacity possible:
// - The talker applies rotary embeddings from cos/sin ARRAYS (MRoPE), so the
//   position enters as a value-varying, shape-constant input — unlike the
//   code predictor's offset-baked fused RoPE.
// - K/V live in static per-layer buffers `[1, kvHeads, capacity, headDim]`;
//   the step writes at the current position via `putAlong` with the position
//   broadcast as an index array, and attends over the full buffer with an
//   in-trace validity mask (`arange <= t ? 0 : -finfo.max`), so padded lanes
//   contribute exactly zero.
// - Capacity grows in 256-token blocks; crossing a block re-traces once (the
//   per-capacity compiled function is cached), so padded-attention bandwidth
//   tracks actual usage instead of the token cap.
//
// The plan engages only for the production plain-cache path; quantized and
// rotating caches (debug-knob/policy experiments) keep the eager path.

final class TalkerCompiledDecodePlan {
    private let talker: Qwen3TTSTalkerForConditionalGeneration
    private let layerCount: Int
    private let kvHeads: Int
    private let headDim: Int
    private let dtype: DType
    private let blockSize = 256

    /// Next write position (prefill length + generated tokens so far).
    private(set) var position: Int
    private var capacity: Int
    private var keyBuffers: [MLXArray]
    private var valueBuffers: [MLXArray]
    private var compiledSteps: [Int: @Sendable ([MLXArray]) -> [MLXArray]] = [:]

    /// Builds the plan from the prefilled eager caches. Returns nil unless
    /// every layer cache is a plain `KVCacheSimple` at a common offset — the
    /// quantized/rotating experiments keep the eager path.
    init?(talker: Qwen3TTSTalkerForConditionalGeneration, prefillCache: [any KVCache], dtype: DType) {
        let config = talker.config
        self.talker = talker
        self.layerCount = talker.model.layers.count
        self.kvHeads = config.numKeyValueHeads
        self.headDim = config.headDim
        self.dtype = dtype

        var seededKeys: [MLXArray] = []
        var seededValues: [MLXArray] = []
        var commonOffset: Int?
        for cache in prefillCache {
            guard let simple = cache as? KVCacheSimple,
                  type(of: simple) == KVCacheSimple.self else { return nil }
            // `state` publicly exposes keys/values trimmed to the offset.
            let state = simple.state
            guard state.count == 2 else { return nil }
            if let commonOffset, commonOffset != simple.offset { return nil }
            commonOffset = simple.offset
            seededKeys.append(state[0])
            seededValues.append(state[1])
        }
        guard let prefillLength = commonOffset, prefillLength > 0,
              seededKeys.count == layerCount,
              seededKeys.allSatisfy({ $0.dim(2) == prefillLength }) else { return nil }

        self.position = prefillLength
        let initialCapacity = ((prefillLength / blockSize) + 1) * blockSize
        self.capacity = initialCapacity
        self.keyBuffers = []
        self.valueBuffers = []
        keyBuffers.reserveCapacity(layerCount)
        valueBuffers.reserveCapacity(layerCount)
        for index in 0 ..< layerCount {
            var kBuf = MLXArray.zeros([1, kvHeads, initialCapacity, headDim], dtype: dtype)
            var vBuf = MLXArray.zeros([1, kvHeads, initialCapacity, headDim], dtype: dtype)
            kBuf[.ellipsis, ..<prefillLength, 0...] = seededKeys[index][.ellipsis, ..<prefillLength, 0...]
            vBuf[.ellipsis, ..<prefillLength, 0...] = seededValues[index][.ellipsis, ..<prefillLength, 0...]
            keyBuffers.append(kBuf)
            valueBuffers.append(vBuf)
        }
    }

    /// One decode step at the current position. Mirrors the eager
    /// seqLen-1 talker forward op-for-op; returns (logits, hiddenStates).
    func step(_ inputEmbeds: MLXArray) -> (MLXArray, MLXArray) {
        growIfNeeded()
        // cos/sin come from the same rotary module and position values the
        // eager path would use; they feed the trace as shape-constant inputs.
        let pos = MLXArray([Int32(position)]).reshaped(1, 1)
        let posIds = stacked([pos, pos, pos], axis: 0)
        let (cosVal, sinVal) = talker.model.rotaryEmb(inputEmbeds, positionIds: posIds)
        let positionScalar = MLXArray(Int32(position))

        var inputs: [MLXArray] = [inputEmbeds, cosVal, sinVal, positionScalar]
        inputs.append(contentsOf: keyBuffers)
        inputs.append(contentsOf: valueBuffers)
        let outputs = compiledStep(capacity: capacity)(inputs)
        keyBuffers = Array(outputs[2 ..< (2 + layerCount)])
        valueBuffers = Array(outputs[(2 + layerCount) ..< (2 + 2 * layerCount)])
        position += 1
        return (outputs[0], outputs[1])
    }

    private func growIfNeeded() {
        guard position >= capacity else { return }
        let newCapacity = capacity + blockSize
        for index in 0 ..< layerCount {
            let extraK = MLXArray.zeros([1, kvHeads, blockSize, headDim], dtype: dtype)
            let extraV = MLXArray.zeros([1, kvHeads, blockSize, headDim], dtype: dtype)
            keyBuffers[index] = concatenated([keyBuffers[index], extraK], axis: 2)
            valueBuffers[index] = concatenated([valueBuffers[index], extraV], axis: 2)
        }
        capacity = newCapacity
    }

    private func compiledStep(capacity: Int) -> @Sendable ([MLXArray]) -> [MLXArray] {
        if let cached = compiledSteps[capacity] { return cached }
        let talker = self.talker
        let layerCount = self.layerCount
        let kvHeads = self.kvHeads
        let headDim = self.headDim
        let compiled = compile { [talker, layerCount, kvHeads, headDim] (inputs: [MLXArray]) -> [MLXArray] in
            Self.traceStep(
                capacity: capacity,
                talker: talker,
                layerCount: layerCount,
                kvHeads: kvHeads,
                headDim: headDim,
                inputs: inputs
            )
        }
        compiledSteps[capacity] = compiled
        return compiled
    }

    private static func traceStep(
        capacity: Int,
        talker: Qwen3TTSTalkerForConditionalGeneration,
        layerCount: Int,
        kvHeads: Int,
        headDim: Int,
        inputs: [MLXArray]
    ) -> [MLXArray] {
        let inputEmbeds = inputs[0]
        let cosVal = inputs[1]
        let sinVal = inputs[2]
        let position = inputs[3]
        var keyBuffers = Array(inputs[4 ..< 4 + layerCount])
        var valueBuffers = Array(inputs[4 + layerCount ..< 4 + 2 * layerCount])
        let dtype = inputEmbeds.dtype

        // Validity mask over the padded buffer: exactly zero for positions
        // <= t, -1e9 beyond (the MLXNN additive-mask convention; exp
        // underflows to exactly 0, so padded lanes contribute nothing to
        // the softmax).
        let lanes = MLXArray(Int32(0) ..< Int32(capacity))
        let mask = which(
            lanes .<= position,
            MLXArray.zeros([capacity], dtype: dtype),
            MLXArray(Float(-1e9)).asType(dtype)
        ).reshaped(1, 1, 1, capacity)

        let cosE = expandedDimensions(cosVal, axis: 1)
        let sinE = expandedDimensions(sinVal, axis: 1)
        func rotate(_ x: MLXArray) -> MLXArray {
            let half = x.dim(-1) / 2
            let x1 = x[.ellipsis, ..<half]
            let x2 = x[.ellipsis, half...]
            return concatenated([-x2, x1], axis: -1)
        }

        var x = inputEmbeds
        for (index, layer) in talker.model.layers.enumerated() {
            let attention = layer.selfAttn
            let attnInput = layer.inputLayernorm(x)
            var q = attention.qProj(attnInput).reshaped(1, 1, attention.numHeads, headDim)
            var k = attention.kProj(attnInput).reshaped(1, 1, kvHeads, headDim)
            var v = attention.vProj(attnInput).reshaped(1, 1, kvHeads, headDim)
            q = attention.qNorm(q)
            k = attention.kNorm(k)
            q = q.transposed(0, 2, 1, 3)
            k = k.transposed(0, 2, 1, 3)
            v = v.transposed(0, 2, 1, 3)
            q = q * cosE + rotate(q) * sinE
            k = k * cosE + rotate(k) * sinE

            let writeIndex = broadcast(
                position.reshaped(1, 1, 1, 1),
                to: [1, kvHeads, 1, headDim]
            )
            let kBuf = putAlong(keyBuffers[index], writeIndex, values: k, axis: 2)
            let vBuf = putAlong(valueBuffers[index], writeIndex, values: v, axis: 2)
            keyBuffers[index] = kBuf
            valueBuffers[index] = vBuf

            let attended = MLXFast.scaledDotProductAttention(
                queries: q, keys: kBuf, values: vBuf,
                scale: attention.scale, mask: mask
            )
            let attnOut = attention.oProj(
                attended.transposed(0, 2, 1, 3).reshaped(1, 1, -1)
            )
            x = x + attnOut
            // Inlined SwiGLU (the eager path's compiled helper is not traced
            // through; the fused trace subsumes it).
            let mlpInput = layer.postAttentionLayernorm(x)
            let mlp = layer.mlp
            x = x + mlp.downProj(silu(mlp.gateProj(mlpInput)) * mlp.upProj(mlpInput))
        }
        let hidden = talker.model.norm(x)
        let logits = talker.codecHead(hidden)
        return [logits, hidden] + keyBuffers + valueBuffers
    }
}
