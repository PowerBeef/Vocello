// AudioSeal watermark generator — MLX port of Meta's audioseal_wm_16bits
// (facebookresearch/audioseal @ cc2700db, MIT, code and weights).
//
// Architecture: EnCodec-style SEANet encoder (conv stack + 2-layer LSTM,
// bottleneck 128) → additive 16-bit message embedding → SEANet decoder
// (2-layer LSTM + transposed conv stack) producing an imperceptible additive
// watermark delta. Non-causal convolutions (constant padding, split
// left/right per audiocraft's StreamableConv1d); LSTMs carry the only
// sequential state. Weight layouts are permuted from the PyTorch checkpoint
// at load time; numerical parity against the reference implementation is
// enforced by fixtures in Qwen3RuntimeTests.
//
// Compliance context: EU AI Act Article 50(2) machine-readable marking —
// see docs/reference/eu-ai-act-article50-assessment.md and roadmap CP-2.

import Foundation
import MLX

public enum AudioSealError: Error, CustomStringConvertible {
    case missingTensor(String)
    case badShape(String)

    public var description: String {
        switch self {
        case .missingTensor(let name): return "AudioSeal weights missing tensor \(name)"
        case .badShape(let detail): return "AudioSeal weight shape mismatch: \(detail)"
        }
    }
}

/// Non-causal "streamable" 1-d convolution with audiocraft's exact padding
/// arithmetic. Input/output are channels-last `[1, T, C]`.
struct StreamableConv1d {
    let weight: MLXArray  // [cOut, K, cIn]
    let bias: MLXArray    // [cOut]
    let stride: Int
    let dilation: Int

    func callAsFunction(_ x: MLXArray) -> MLXArray {
        let kernel = weight.dim(1)
        let effectiveKernel = (kernel - 1) * dilation + 1
        let paddingTotal = effectiveKernel - stride
        let length = x.dim(1)
        // get_extra_padding_for_conv1d: make the last window full.
        let frames = Double(length - effectiveKernel + paddingTotal) / Double(stride) + 1
        let idealLength = (Int(frames.rounded(.up)) - 1) * stride + (effectiveKernel - paddingTotal)
        let extra = idealLength - length
        let right = paddingTotal / 2
        let left = paddingTotal - right
        let padded = MLX.padded(x, widths: [.init((0, 0)), .init((left, right + extra)), .init((0, 0))])
        return conv1d(padded, weight, stride: stride, dilation: dilation) + bias
    }
}

/// Non-causal transposed 1-d convolution with symmetric unpadding.
struct StreamableConvTranspose1d {
    let weight: MLXArray  // [cOut, K, cIn]
    let bias: MLXArray
    let stride: Int

    func callAsFunction(_ x: MLXArray) -> MLXArray {
        let kernel = weight.dim(1)
        let paddingTotal = kernel - stride
        let y = convTransposed1d(x, weight, stride: stride) + bias
        let right = paddingTotal / 2
        let left = paddingTotal - right
        return y[0..., left ..< (y.dim(1) - right), 0...]
    }
}

/// Two-layer LSTM matching torch gate order (i, f, g, o) with the
/// StreamableLSTM residual skip. Input `[1, T, C]`.
struct SkipLSTM {
    struct Layer {
        let wIH: MLXArray  // [4H, C]
        let wHH: MLXArray  // [4H, H]
        let bias: MLXArray // [4H] (b_ih + b_hh, fused at load)
    }

    let layers: [Layer]
    let hidden: Int

    func callAsFunction(_ x: MLXArray) -> MLXArray {
        var sequence = x
        for layer in layers {
            let frames = sequence.dim(1)
            var h = MLXArray.zeros([1, hidden])
            var c = MLXArray.zeros([1, hidden])
            let projected = matmul(sequence[0], layer.wIH.T) + layer.bias  // [T, 4H]
            var outputs = [MLXArray]()
            outputs.reserveCapacity(frames)
            for t in 0 ..< frames {
                let gates = projected[t ..< (t + 1), 0...] + matmul(h, layer.wHH.T)
                let i = sigmoid(gates[0..., 0 ..< hidden])
                let f = sigmoid(gates[0..., hidden ..< (2 * hidden)])
                let g = tanh(gates[0..., (2 * hidden) ..< (3 * hidden)])
                let o = sigmoid(gates[0..., (3 * hidden) ..< (4 * hidden)])
                c = f * c + i * g
                h = o * tanh(c)
                outputs.append(h)
            }
            sequence = stacked(outputs, axis: 0).reshaped([1, frames, hidden])
        }
        return sequence + x
    }
}

/// SEANet residual block: ELU → k3 conv (dim → dim/2) → ELU → k1 conv
/// (dim/2 → dim), identity shortcut (true_skip).
struct ResnetBlock {
    let conv1: StreamableConv1d
    let conv2: StreamableConv1d

    func callAsFunction(_ x: MLXArray) -> MLXArray {
        var y = elu(x)
        y = conv1(y)
        y = elu(y)
        y = conv2(y)
        return x + y
    }
}

private func elu(_ x: MLXArray) -> MLXArray {
    which(x .> 0, x, expm1(x))
}

/// The AudioSeal watermark generator. Whole-buffer forward is the parity
/// reference; `watermark(pcm:)` is the shipping windowed path with bounded
/// memory (CP-2 zero-peak constraint).
public final class AudioSealGenerator {
    /// Fixed 16-bit payload: deterministic across processes and attributable
    /// to Vocello. The upstream API draws a random message per process when
    /// none is supplied — never call it that way.
    public static let messagePayload: UInt16 = 0x56C0
    public static let sampleRate = 24_000

    // ratios reversed for the encoder: strides 2, 4, 5, 8 (total 320×).
    static let encoderStrides = [2, 4, 5, 8]
    static let filters = 32
    static let bottleneck = 128
    static let lstmDim = 512

    private let encoderInput: StreamableConv1d
    private let encoderStages: [(ResnetBlock, StreamableConv1d)]
    private let encoderLSTM: SkipLSTM
    private let encoderOutput: StreamableConv1d
    private let messageTable: MLXArray  // [32, 128]
    private let decoderInput: StreamableConv1d
    private let decoderLSTM: SkipLSTM
    private let decoderStages: [(StreamableConvTranspose1d, ResnetBlock)]
    private let decoderOutput: StreamableConv1d

    public init(weightsURL: URL) throws {
        let raw = try loadArrays(url: weightsURL)
        func tensor(_ name: String) throws -> MLXArray {
            guard let value = raw[name] else { throw AudioSealError.missingTensor(name) }
            return value.asType(.float32)
        }
        // torch Conv1d weight [cOut, cIn, K] → mlx [cOut, K, cIn]
        func conv(_ prefix: String, stride: Int = 1, dilation: Int = 1) throws -> StreamableConv1d {
            StreamableConv1d(
                weight: try tensor("\(prefix).conv.conv.inner_conv.weight").transposed(0, 2, 1),
                bias: try tensor("\(prefix).conv.conv.inner_conv.bias"),
                stride: stride, dilation: dilation)
        }
        // torch ConvTranspose1d weight [cIn, cOut, K] → mlx [cOut, K, cIn]
        func convT(_ prefix: String, stride: Int) throws -> StreamableConvTranspose1d {
            StreamableConvTranspose1d(
                weight: try tensor("\(prefix).convtr.convtr.inner_conv.weight").transposed(1, 2, 0),
                bias: try tensor("\(prefix).convtr.convtr.inner_conv.bias"),
                stride: stride)
        }
        func lstm(_ prefix: String) throws -> SkipLSTM {
            var layers = [SkipLSTM.Layer]()
            for l in 0 ..< 2 {
                layers.append(.init(
                    wIH: try tensor("\(prefix).lstm.weight_ih_l\(l)"),
                    wHH: try tensor("\(prefix).lstm.weight_hh_l\(l)"),
                    bias: try tensor("\(prefix).lstm.bias_ih_l\(l)") + tensor("\(prefix).lstm.bias_hh_l\(l)")))
            }
            return SkipLSTM(layers: layers, hidden: Self.lstmDim)
        }
        func resnet(_ prefix: String) throws -> ResnetBlock {
            ResnetBlock(conv1: try conv("\(prefix).block.1"), conv2: try conv("\(prefix).block.3"))
        }

        // Encoder: 0 input conv; per stage (resnet, ELU, strided conv) at
        // indices (1,3), (4,6), (7,9), (10,12); 13 LSTM; 14 ELU; 15 output.
        encoderInput = try conv("encoder.model.0")
        var stages = [(ResnetBlock, StreamableConv1d)]()
        for (stage, stride) in Self.encoderStrides.enumerated() {
            let base = 1 + stage * 3
            stages.append((try resnet("encoder.model.\(base)"),
                           try conv("encoder.model.\(base + 2)", stride: stride)))
        }
        encoderStages = stages
        encoderLSTM = try lstm("encoder.model.13")
        encoderOutput = try conv("encoder.model.15")
        messageTable = try tensor("msg_processor.msg_processor.weight")

        // Decoder mirrors: 0 input conv; 1 LSTM; per stage (ELU, convT,
        // resnet) at (3,4), (6,7), (9,10), (12,13); 14 ELU; 15 output conv.
        decoderInput = try conv("decoder.model.0")
        decoderLSTM = try lstm("decoder.model.1")
        var dstages = [(StreamableConvTranspose1d, ResnetBlock)]()
        for (stage, stride) in Self.encoderStrides.reversed().enumerated() {
            let base = 2 + stage * 3
            dstages.append((try convT("decoder.model.\(base + 1)", stride: stride),
                            try resnet("decoder.model.\(base + 2)")))
        }
        decoderStages = dstages
        decoderOutput = try conv("decoder.model.15")
    }

    /// Message bias vector: sum of per-bit embedding rows at indices
    /// 2·i + bit_i, matching MsgProcessor.
    private func messageBias() -> MLXArray {
        var rows = [MLXArray]()
        for bit in 0 ..< 16 {
            let value = (Int(Self.messagePayload) >> (15 - bit)) & 1
            rows.append(messageTable[2 * bit + value])
        }
        return stacked(rows, axis: 0).sum(axis: 0)  // [128]
    }

    static let totalStride = 320  // product of encoder strides

    /// Sample-rate encoder convolutions: pcm `[1, T, 1]` → pre-LSTM
    /// bottleneck sequence `[1, F, 512]`.
    private func encoderConvs(_ x: MLXArray) -> MLXArray {
        var h = encoderInput(x)
        for (block, down) in encoderStages {
            h = down(elu(block(h)))
        }
        return h
    }

    /// Frame-rate sequential middle: encoder LSTM, output conv, message,
    /// decoder input conv, decoder LSTM. Cheap (75 Hz), runs whole-sequence
    /// so the LSTM state is exact regardless of conv windowing.
    private func frameStages(_ sequence: MLXArray) -> MLXArray {
        var h = encoderLSTM(sequence)
        h = encoderOutput(elu(h))
        h = h + messageBias().reshaped([1, 1, Self.bottleneck])
        var d = decoderInput(h)
        d = decoderLSTM(d)
        return d
    }

    /// Frame-rate decoder tail: LSTM output `[1, F, 512]` → delta samples
    /// `[1, ~F·320, 1]`.
    private func decoderConvs(_ sequence: MLXArray) -> MLXArray {
        var d = sequence
        for (up, block) in decoderStages {
            d = block(up(elu(d)))
        }
        return decoderOutput(elu(d))
    }

    /// Whole-buffer watermark delta — the parity reference. `[T]` in, `[T]` out.
    public func watermarkDelta(pcm: [Float]) -> [Float] {
        let x = MLXArray(pcm).reshaped([1, pcm.count, 1])
        let d = decoderConvs(frameStages(encoderConvs(x)))
        let count = min(pcm.count, d.dim(1))
        let delta = d[0..., 0 ..< count, 0].reshaped([count])
        delta.eval()
        return delta.asArray(Float.self)
    }

    /// Shipping path: bounded-memory embedding that is numerically equal to
    /// the whole-buffer pass (CP-2 zero-peak constraint). The sample-rate
    /// convolution stages are windowed with frame-aligned context margins —
    /// convolutions are local, so interior frames/samples are exact — while
    /// the LSTMs and other frame-rate stages run over the full 75 Hz
    /// sequence, keeping sequential state exact. Only bottleneck-rate
    /// buffers span the whole take (128× smaller than audio).
    // Default geometry 64/8 (was 150/64): the conv stacks' receptive field
    // is a handful of frames, so 8-frame margins stay exact (parity-tested
    // ≥55 dB against whole-buffer), and the ~3.5× smaller windows bound the
    // marking pass's per-window conv workspaces — the Metal-heap high-water
    // this leaves behind is what the fail-closed peak-equality lane meters.
    public func watermark(pcm: [Float], coreFrames: Int = 64, marginFrames: Int = 8) -> [Float] {
        let stride = Self.totalStride
        let totalFrames = (pcm.count + stride - 1) / stride
        guard totalFrames > coreFrames + 2 * marginFrames else {
            let delta = watermarkDelta(pcm: pcm)
            return zip(pcm, delta).map { max(-1, min(1, $0 + $1)) }
        }

        // Every stage drains an explicit autoreleasepool: eval commits Metal
        // command buffers and other autoreleased ObjC objects, and the Swift
        // Concurrency thread that runs publication-time marking never drains
        // the thread pool's implicit pool — without this, each marked take
        // leaves its command-buffer graph resident until process idle, which
        // the retained-memory lane meters as a permanent per-take leak.

        // Stage 1: windowed encoder convolutions → exact bottleneck sequence.
        var bottleneckParts = [MLXArray]()
        var frame = 0
        while frame < totalFrames {
            autoreleasepool {
                let coreEnd = min(frame + coreFrames, totalFrames)
                let windowStartFrame = max(0, frame - marginFrames)
                let windowStart = windowStartFrame * stride
                let windowEnd = min(pcm.count, (coreEnd + marginFrames) * stride)
                let x = MLXArray(Array(pcm[windowStart ..< windowEnd]))
                    .reshaped([1, windowEnd - windowStart, 1])
                let window = encoderConvs(x)
                let lo = frame - windowStartFrame
                let hi = min(lo + (coreEnd - frame), window.dim(1))
                let core = window[0..., lo ..< hi, 0...]
                core.eval()
                bottleneckParts.append(core)
                // Zero-peak: return each window's conv temporaries to the OS
                // instead of letting the allocator cache accumulate across
                // windows — the resident-peak budget for publication-time
                // marking is a rounding error, not a working set.
                Memory.clearCache()
                frame = coreEnd
            }
        }
        let bottleneck = concatenated(bottleneckParts, axis: 1)

        // Stage 2: exact full-sequence frame-rate stages (LSTMs + message).
        let lstmOut = autoreleasepool { () -> MLXArray in
            let out = frameStages(bottleneck)
            out.eval()
            Memory.clearCache()
            return out
        }

        // Stage 3: windowed decoder convolutions → delta samples.
        var out = [Float](repeating: 0, count: pcm.count)
        frame = 0
        while frame < totalFrames {
            autoreleasepool {
                let coreEnd = min(frame + coreFrames, totalFrames)
                let windowStartFrame = max(0, frame - marginFrames)
                let windowEndFrame = min(totalFrames, coreEnd + marginFrames)
                let window = decoderConvs(lstmOut[0..., windowStartFrame ..< windowEndFrame, 0...])
                let sampleLo = (frame - windowStartFrame) * stride
                let coreStart = frame * stride
                let coreSampleEnd = min(coreEnd * stride, pcm.count)
                let span = coreSampleEnd - coreStart
                let deltaSlice = window[0..., sampleLo ..< min(sampleLo + span, window.dim(1)), 0]
                    .reshaped([-1])
                deltaSlice.eval()
                let delta = deltaSlice.asArray(Float.self)
                for i in 0 ..< min(span, delta.count) {
                    out[coreStart + i] = max(-1, min(1, pcm[coreStart + i] + delta[i]))
                }
                Memory.clearCache()
                frame = coreEnd
            }
        }
        return out
    }
}
