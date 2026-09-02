import Foundation
@preconcurrency import MLX
import MLXNN

// MARK: - Compiled code-predictor execution (Stage 1 P3)
//
// The eager code-predictor path rebuilds ~15 small op graphs on the host for
// every generated frame while the GPU sits near-idle (§H P0: 15.4% of wall at
// <1% GPU busy). This plan compiles one function per pass index instead, so
// steady-state frames replay cached compiled graphs.
//
// Two correctness constraints shape the design:
//
// 1. The fused RoPE `offset` is a trace-time constant, and passes 1–14 share
//    input shapes while differing in offset. Compiled functions are therefore
//    keyed by pass index — 15 stable entries per generation — never by shape.
// 2. `KVCacheSimple` advances a host-side `offset` inside `update`, which a
//    cached compiled call would never re-execute. The compiled path therefore
//    owns explicit per-layer K/V buffers threaded through each function as
//    pure inputs/outputs, with the write/read slices baked per pass index.
//    Every frame replays identical positions (the eager path's per-frame
//    trim-to-zero contract), so the baked slices are correct by construction.
//
// The math replicates the eager modules op-for-op (same kernels, same order),
// so fixed-seed output remains byte-identical — enforced by the runtime
// equivalence test and the end-to-end identity gate.

/// Per-generation compiled plan. Built lazily on the first frame; the 15
/// compiled functions and the K/V buffers live for exactly one generation
/// (request-local, like the sampler scratch).
final class CodePredictorCompiledPlan {
    private let predictor: Qwen3TTSCodePredictor
    private let passCount: Int
    private let layerCount: Int
    /// One K and one V buffer per layer, sized to the exact per-frame token
    /// budget (2 positions from pass 0 + one per remaining pass).
    private var keyBuffers: [MLXArray]
    private var valueBuffers: [MLXArray]
    private var compiledPasses: [Int: @Sendable ([MLXArray]) -> [MLXArray]] = [:]

    init(predictor: Qwen3TTSCodePredictor, dtype: DType) {
        self.predictor = predictor
        self.passCount = predictor.numCodeGroups - 1
        let layers = predictor.model.layers
        self.layerCount = layers.count
        let config = predictor.config
        let totalPositions = passCount + 1
        self.keyBuffers = layers.map { _ in
            MLXArray.zeros(
                [1, config.numKeyValueHeads, totalPositions, config.headDim],
                dtype: dtype
            )
        }
        self.valueBuffers = layers.map { _ in
            MLXArray.zeros(
                [1, config.numKeyValueHeads, totalPositions, config.headDim],
                dtype: dtype
            )
        }
    }

    /// Pass 0 consumes the talker hidden state plus the already-embedded
    /// first-codebook token (built in the loop exactly as the eager path
    /// does); later passes consume the previous raw code token, embedded
    /// inside the compiled function through `codecEmbedding[pass - 1]`.
    /// Returns the pass logits. Buffer state advances internally.
    func run(pass: Int, codeHidden: MLXArray?, code0Embed: MLXArray?, token: MLXArray?) -> MLXArray {
        let function = compiledPass(pass)
        var inputs: [MLXArray] = []
        if pass == 0 {
            inputs.append(codeHidden!)
            inputs.append(code0Embed!)
        } else {
            inputs.append(token!)
        }
        inputs.append(contentsOf: keyBuffers)
        inputs.append(contentsOf: valueBuffers)
        let outputs = function(inputs)
        keyBuffers = Array(outputs[1 ..< (1 + layerCount)])
        valueBuffers = Array(outputs[(1 + layerCount) ..< (1 + 2 * layerCount)])
        return outputs[0]
    }

    private func compiledPass(_ pass: Int) -> @Sendable ([MLXArray]) -> [MLXArray] {
        if let cached = compiledPasses[pass] { return cached }
        let predictor = self.predictor
        let layerCount = self.layerCount
        let compiled = compile { [predictor, layerCount] (inputs: [MLXArray]) -> [MLXArray] in
            Self.tracePass(
                pass,
                predictor: predictor,
                layerCount: layerCount,
                inputs: inputs
            )
        }
        compiledPasses[pass] = compiled
        return compiled
    }

    /// Traced once per pass index per generation; replayed for every frame.
    private static func tracePass(
        _ pass: Int,
        predictor: Qwen3TTSCodePredictor,
        layerCount: Int,
        inputs: [MLXArray]
    ) -> [MLXArray] {
        let cursor = pass == 0 ? 2 : 1
        var keyBuffers = Array(inputs[cursor ..< cursor + layerCount])
        var valueBuffers = Array(inputs[cursor + layerCount ..< cursor + 2 * layerCount])

        // Input embedding, matching the eager loop exactly: pass 0 prepends
        // the talker hidden state to the pre-embedded first-codebook token;
        // later passes embed the previous code through codecEmbedding.
        var embeds: MLXArray
        if pass == 0 {
            embeds = concatenated([inputs[0], inputs[1]], axis: 1)
        } else {
            embeds = predictor.codecEmbedding[pass - 1](inputs[0])
        }
        if let projection = predictor.projection {
            embeds = projection(embeds)
        }

        // Positions replay identically every frame: pass 0 writes [0, 2) at
        // RoPE offset 0 with the 2-token causal mask; pass i writes
        // [i + 1, i + 2) at offset i + 1 with no mask.
        let seqLen = pass == 0 ? 2 : 1
        let offset = pass == 0 ? 0 : pass + 1
        let mask: MLXArray? = pass == 0
            ? MultiHeadAttention.createAdditiveCausalMask(seqLen).asType(embeds.dtype)
            : nil

        var x = embeds
        for (index, layer) in predictor.model.layers.enumerated() {
            let attnInput = layer.inputLayernorm(x)
            let attention = layer.selfAttn
            let (batch, _, _) = (attnInput.dim(0), attnInput.dim(1), attnInput.dim(2))
            var q = attention.qProj(attnInput)
                .reshaped(batch, seqLen, attention.numHeads, attention.headDim)
            var k = attention.kProj(attnInput)
                .reshaped(batch, seqLen, attention.numKvHeads, attention.headDim)
            var v = attention.vProj(attnInput)
                .reshaped(batch, seqLen, attention.numKvHeads, attention.headDim)
            q = attention.qNorm(q)
            k = attention.kNorm(k)
            q = q.transposed(0, 2, 1, 3)
            k = k.transposed(0, 2, 1, 3)
            v = v.transposed(0, 2, 1, 3)
            q = MLXFast.RoPE(
                q, dimensions: attention.headDim, traditional: false,
                base: attention.ropeBase, scale: 1.0, offset: offset
            )
            k = MLXFast.RoPE(
                k, dimensions: attention.headDim, traditional: false,
                base: attention.ropeBase, scale: 1.0, offset: offset
            )

            let keyBuffer = keyBuffers[index]
            let valueBuffer = valueBuffers[index]
            keyBuffer[.ellipsis, offset ..< (offset + seqLen), 0...] = k
            valueBuffer[.ellipsis, offset ..< (offset + seqLen), 0...] = v
            keyBuffers[index] = keyBuffer
            valueBuffers[index] = valueBuffer
            let keys = keyBuffer[.ellipsis, ..<(offset + seqLen), 0...]
            let values = valueBuffer[.ellipsis, ..<(offset + seqLen), 0...]

            let attended = MLXFast.scaledDotProductAttention(
                queries: q, keys: keys, values: values,
                scale: attention.scale, mask: mask
            )
            let attnOut = attention.oProj(
                attended.transposed(0, 2, 1, 3).reshaped(batch, seqLen, -1)
            )
            x = x + attnOut
            // Inlined MLP: the eager path routes silu(gate) * up through a
            // file-scope compiled helper; tracing through a nested compiled
            // function is avoided here, and the fused trace subsumes it.
            let mlpInput = layer.postAttentionLayernorm(x)
            let mlp = layer.mlp
            x = x + mlp.downProj(silu(mlp.gateProj(mlpInput)) * mlp.upProj(mlpInput))
        }
        x = predictor.model.norm(x)
        let logits = predictor.lmHead[pass](x)
        return [logits] + keyBuffers + valueBuffers
    }
}
