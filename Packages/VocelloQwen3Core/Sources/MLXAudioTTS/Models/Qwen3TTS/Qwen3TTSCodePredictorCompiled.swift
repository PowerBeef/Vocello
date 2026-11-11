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
// RF-46: the frame as one function. When the request's subtalker stage is
// the plain temperature and top-k sampler (`CompiledPassSampling`), which
// production uses, `runFrame` runs the fifteen passes, each followed by its
// sampler, and the sum of the frame's code embeddings in one compiled
// function; the loop passes in the fifteen random keys it resolved from the
// request's state. The passes still run one after another, each on the code
// before it: nothing is pipelined. The per-pass functions serve every other
// stage and observed takes.

/// The sampler the frame function runs after each pass (RF-46): the plain
/// temperature and top-k sampler the code predictor uses in production.
/// Inside the compiled function MLX fuses its elementwise chains, and the
/// pass's code feeds the next pass without a round trip through Swift. The
/// random keys are inputs, resolved by the caller from the request's random
/// state exactly as the eager sampler resolves them, so the request draws
/// the same keys in the same order.
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
    /// The sampler `runFrame` runs after each pass, when the request's
    /// subtalker stage is one it reproduces; nil leaves only the per-pass
    /// `run`, whose logits the eager sampler takes.
    let sampling: CompiledPassSampling?
    private let dtype: DType
    private var compiledFrame: (@Sendable ([MLXArray]) -> [MLXArray])?
    /// Frames this plan ran through `runFrame`; the generate loop publishes
    /// it per take so a test can tell which path a take took.
    private(set) var frameFunctionCallCount = 0

    init(predictor: Qwen3TTSCodePredictor, dtype: DType, sampling: CompiledPassSampling? = nil) {
        self.predictor = predictor
        self.sampling = sampling
        self.dtype = dtype
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
        // Under an MLX error handler a failed compile or apply returns no
        // outputs. Keep the buffers and return placeholder logits of the pass
        // shape, so the step reaches its typed failure at the next error
        // check instead of trapping on the index.
        guard outputs.count == 1 + 2 * layerCount else {
            return MLXArray.zeros([1, 1, predictor.config.vocabSize], dtype: keyBuffers[0].dtype)
        }
        keyBuffers = Array(outputs[1 ..< (1 + layerCount)])
        valueBuffers = Array(outputs[(1 + layerCount) ..< (1 + 2 * layerCount)])
        return outputs[0]
    }

    /// The frame's fifteen codes and the sum of its sixteen code embeddings,
    /// from one compiled function (`traceFrame`). `keys` holds one random key
    /// per pass, resolved in pass order. Requires `sampling`.
    func runFrame(
        codeHidden: MLXArray, code0Embed: MLXArray, keys: [MLXArray]
    ) -> (codes: [MLXArray], embeddingSum: MLXArray) {
        // Both are the caller's contract, and a mismatch would otherwise trap
        // inside the trace with no hint of why.
        guard let sampling else {
            preconditionFailure("runFrame needs a plan built with a sampling stage")
        }
        precondition(keys.count == passCount, "runFrame takes one random key per pass")
        frameFunctionCallCount += 1
        let function: @Sendable ([MLXArray]) -> [MLXArray]
        if let compiledFrame {
            function = compiledFrame
        } else {
            let predictor = self.predictor
            let passCount = self.passCount
            let dtype = self.dtype
            let compiled = compile { [predictor, passCount, dtype, sampling] (inputs: [MLXArray]) -> [MLXArray] in
                Self.traceFrame(
                    predictor: predictor, passCount: passCount, sampling: sampling, dtype: dtype, inputs: inputs
                )
            }
            compiledFrame = compiled
            function = compiled
        }
        let outputs = function([codeHidden, code0Embed] + keys)
        // Under an MLX error handler a failed compile or apply returns no
        // outputs: placeholders of the right shapes let the step reach its
        // typed failure at the next error check instead of trapping here.
        guard outputs.count == passCount + 1 else {
            return (
                (0 ..< passCount).map { _ in MLXArray.zeros([1, 1], dtype: .uint32) },
                MLXArray.zeros(like: code0Embed)
            )
        }
        return (Array(outputs[..<passCount]), outputs[passCount])
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
        let embeds: MLXArray
        if pass == 0 {
            embeds = concatenated([inputs[0], inputs[1]], axis: 1)
        } else {
            embeds = predictor.codecEmbedding[pass - 1](inputs[0])
        }
        let logits = passLogits(
            pass, predictor: predictor, embeds: embeds,
            keyBuffers: &keyBuffers, valueBuffers: &valueBuffers
        )
        return [logits] + keyBuffers + valueBuffers
    }

    /// One pass's logits from its input embedding, writing the pass's K and V
    /// into the buffers. The body both the per-pass traces and the frame
    /// trace run.
    private static func passLogits(
        _ pass: Int,
        predictor: Qwen3TTSCodePredictor,
        embeds input: MLXArray,
        keyBuffers: inout [MLXArray],
        valueBuffers: inout [MLXArray]
    ) -> MLXArray {
        var embeds = input
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
        return predictor.lmHead[pass](x)
    }

    /// The whole frame as one trace (RF-46): fifteen passes, each sampling its
    /// code, and the sum of the frame's sixteen code embeddings that the
    /// talker's next step takes. Inputs: the talker hidden state, the first
    /// code's embedding, then one random key per pass. Outputs: the fifteen
    /// codes, then the sum.
    ///
    /// It is the per-pass traces laid end to end, with two things they could
    /// not share. The K and V buffers start as zeros inside the trace, since
    /// every position a pass reads was written earlier in the same frame, so
    /// nothing carries between frames. And each code's embedding is computed
    /// once, for the next pass's input and for the sum, where the loop
    /// computed it twice; the sum folds left in the loop's order.
    private static func traceFrame(
        predictor: Qwen3TTSCodePredictor,
        passCount: Int,
        sampling: CompiledPassSampling,
        dtype: DType,
        inputs: [MLXArray]
    ) -> [MLXArray] {
        let config = predictor.config
        let bufferShape = [1, config.numKeyValueHeads, passCount + 1, config.headDim]
        var keyBuffers = predictor.model.layers.map { _ in MLXArray.zeros(bufferShape, dtype: dtype) }
        var valueBuffers = predictor.model.layers.map { _ in MLXArray.zeros(bufferShape, dtype: dtype) }

        var codes: [MLXArray] = []
        var embeddingSum = inputs[1]
        var embeds = concatenated([inputs[0], inputs[1]], axis: 1)
        for pass in 0 ..< passCount {
            let logits = passLogits(
                pass, predictor: predictor, embeds: embeds,
                keyBuffers: &keyBuffers, valueBuffers: &valueBuffers
            )
            let code = sampling.sample(logits, key: inputs[2 + pass])
            codes.append(code)
            let embedded = predictor.codecEmbedding[pass](code)
            embeddingSum = embeddingSum + embedded
            embeds = embedded
        }
        return codes + [embeddingSum]
    }
}
