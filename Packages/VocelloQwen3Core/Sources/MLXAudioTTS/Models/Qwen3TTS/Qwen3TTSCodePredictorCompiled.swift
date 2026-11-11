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
//
// RF-46: a pass can also sample. When the request's subtalker stage is the
// plain temperature and top-k sampler (`CompiledPassSampling`), the traced
// function ends in the sampler and returns the code; the loop passes in the
// random key it resolved from the request's state. The passes still run one
// after another, each on the code before it: nothing is pipelined.

/// The sampler a pass can run inside its compiled function (RF-46): the plain
/// temperature and top-k sampler the code predictor uses in production. The
/// pass then returns the sampled code instead of its logits, one compiled
/// call where there were a compiled pass and an eager sampler, and MLX fuses
/// the sampler's elementwise chains. The random key is an input, resolved by
/// the caller from the request's random state exactly as the eager sampler
/// resolves it, so the request draws the same keys in the same order.
struct CompiledPassSampling: Equatable {
    let temperature: Float
    let topK: Int
    let castsLogitsToFloat32: Bool

    /// nil unless `stage` is the sampler this struct reproduces: a positive
    /// temperature, a top-k that applies, and neither top-p nor min-p. Any
    /// other stage keeps the eager sampler.
    static func eligible(
        stage: Qwen3SamplingStage, castsLogitsToFloat32: Bool, vocabSize: Int
    ) -> CompiledPassSampling? {
        guard stage.temperature > 0,
              stage.topK > 0, stage.topK < vocabSize,
              !(stage.topP > 0 && stage.topP < 1),
              !(stage.minP > 0)
        else { return nil }
        return CompiledPassSampling(
            temperature: stage.temperature, topK: stage.topK, castsLogitsToFloat32: castsLogitsToFloat32
        )
    }

    /// The eager sampler's graph for this configuration, op for op
    /// (`Qwen3TTSModel.sampleToken` with no suppression, penalty, EOS, top-p
    /// or min-p): last position, float32 cast, temperature, top-k mask,
    /// categorical draw on `key`.
    func sample(_ logits: MLXArray, key: MLXArray) -> MLXArray {
        var slice = logits[0..., (-1)..., 0...].squeezed(axis: 1)
        if castsLogitsToFloat32, slice.dtype != .float32 {
            slice = slice.asType(.float32)
        }
        if temperature != 1.0 {
            slice = slice / temperature
        }
        let vocabSize = slice.dim(-1)
        let maskIdx = argPartition(-slice, kth: topK - 1, axis: -1)[0..., topK...]
        let negInf = MLXArray.full(
            [1, vocabSize - topK], values: MLXArray(-Float.infinity), dtype: slice.dtype
        )
        let filtered = putAlong(slice, maskIdx, values: negInf, axis: -1)
        return categorical(filtered, key: key).reshaped(1, 1)
    }
}

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
    /// The sampler each pass runs inside its compiled function, when the
    /// request's subtalker stage is one it reproduces; nil keeps the passes
    /// returning logits for the eager sampler.
    let sampling: CompiledPassSampling?

    init(predictor: Qwen3TTSCodePredictor, dtype: DType, sampling: CompiledPassSampling? = nil) {
        self.predictor = predictor
        self.sampling = sampling
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
    ///
    /// With `sampling` set, `key` is required and the result is the sampled
    /// code (`[1, 1]`) instead of the logits.
    func run(
        pass: Int, codeHidden: MLXArray?, code0Embed: MLXArray?, token: MLXArray?, key: MLXArray? = nil
    ) -> MLXArray {
        let function = compiledPass(pass)
        var inputs: [MLXArray] = []
        if pass == 0 {
            inputs.append(codeHidden!)
            inputs.append(code0Embed!)
        } else {
            inputs.append(token!)
        }
        if sampling != nil {
            inputs.append(key!)
        }
        inputs.append(contentsOf: keyBuffers)
        inputs.append(contentsOf: valueBuffers)
        let outputs = function(inputs)
        // Under an MLX error handler a failed compile or apply returns no
        // outputs. Keep the buffers and return placeholder logits of the pass
        // shape, so the step reaches its typed failure at the next error
        // check instead of trapping on the index.
        guard outputs.count == 1 + 2 * layerCount else {
            if sampling != nil {
                return MLXArray.zeros([1, 1], dtype: .uint32)
            }
            return MLXArray.zeros([1, 1, predictor.config.vocabSize], dtype: keyBuffers[0].dtype)
        }
        keyBuffers = Array(outputs[1 ..< (1 + layerCount)])
        valueBuffers = Array(outputs[(1 + layerCount) ..< (1 + 2 * layerCount)])
        return outputs[0]
    }

    private func compiledPass(_ pass: Int) -> @Sendable ([MLXArray]) -> [MLXArray] {
        if let cached = compiledPasses[pass] { return cached }
        let predictor = self.predictor
        let layerCount = self.layerCount
        let sampling = self.sampling
        let compiled = compile { [predictor, layerCount, sampling] (inputs: [MLXArray]) -> [MLXArray] in
            Self.tracePass(
                pass,
                predictor: predictor,
                layerCount: layerCount,
                sampling: sampling,
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
        sampling: CompiledPassSampling?,
        inputs: [MLXArray]
    ) -> [MLXArray] {
        // Inputs: the pass's own (two for pass 0, one after), then the random
        // key when the pass samples, then the K and V buffers.
        let keyIndex = pass == 0 ? 2 : 1
        let cursor = keyIndex + (sampling == nil ? 0 : 1)
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
            let projected = attention.projectQKV(attnInput)
            var q = projected.q
                .reshaped(batch, seqLen, attention.numHeads, attention.headDim)
            var k = projected.k
                .reshaped(batch, seqLen, attention.numKvHeads, attention.headDim)
            var v = projected.v
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
            let gateUp = mlp.projectGateUp(mlpInput)
            x = x + mlp.downProj(silu(gateUp.gate) * gateUp.up)
        }
        x = predictor.model.norm(x)
        let logits = predictor.lmHead[pass](x)
        if let sampling {
            return [sampling.sample(logits, key: inputs[keyIndex])] + keyBuffers + valueBuffers
        }
        return [logits] + keyBuffers + valueBuffers
    }
}
