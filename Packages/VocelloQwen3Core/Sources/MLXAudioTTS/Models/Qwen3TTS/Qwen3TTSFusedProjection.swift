import Foundation
@preconcurrency import MLX
import MLXNN

/// Several bias-free, affine-quantized projections of one input, kept as one
/// matrix so a step runs one quantized product where it ran one per
/// projection (RF-46).
///
/// A quantized matrix is packed, scaled and accumulated one output row at a
/// time. For a single input row MLX runs a one-row kernel that it picks from
/// the input width and from whether the output width is a multiple of eight
/// (`qmv` in its Metal backend), never from the output width itself; `fuse`
/// requires every projection's width to be a multiple of eight, so the fused
/// product runs the kernel the separate products ran and its rows are their
/// rows, bit for bit. With more input rows MLX picks the kernel from the row
/// count and the output width together (`get_qmv_batch_limit`), so a fused
/// prefill could take another kernel and round differently: `projects(_:)`
/// therefore admits one row only, and a prefill keeps the separate products.
/// The fixed-seed PCM digests are the arbiter; the unit tests pin bit
/// equality on small layers. These are couplings to the pinned MLX
/// (`docs/reference/mlx-guide.md` section 9).
///
/// The value is not a `Module` and holds no checkpoint key: the fused arrays
/// are the layers' own rows laid end to end, and `fuse` re-points each layer
/// at its rows of them, so the weights exist once in memory and the layers
/// stay usable on their own. Nothing updates a loaded talker's parameters
/// today (a reload builds a new one); code that ever does must fuse again,
/// because a holder keeps the arrays it was built from.
struct FusedQuantizedProjection {
    let weight: MLXArray
    let scales: MLXArray
    let biases: MLXArray
    let groupSize: Int
    let bits: Int
    /// Each projection's output range in the fused output, in the order the
    /// layers were given.
    let outputRanges: [Range<Int>]

    /// Fuses `layers`. Returns nil and changes nothing unless every layer is
    /// a bias-free `QuantizedLinear` of one affine recipe and one input width,
    /// which is what a quantized checkpoint loads; a float layer (the test
    /// fixtures, an unquantized conversion) keeps the separate products.
    ///
    /// Call it once the layers' parameters are loaded and evaluated.
    static func fuse(_ layers: [Linear]) -> FusedQuantizedProjection? {
        let quantized = layers.compactMap { $0 as? QuantizedLinear }
        guard quantized.count == layers.count, let first = quantized.first, quantized.count > 1 else {
            return nil
        }
        var rowBiases: [MLXArray] = []
        for layer in quantized {
            guard layer.bias == nil,
                  layer.globalScale == nil,
                  layer.mode == .affine,
                  layer.groupSize == first.groupSize,
                  layer.bits == first.bits,
                  layer.weight.ndim == 2,
                  layer.weight.dim(0) % 8 == 0,
                  layer.weight.dim(1) == first.weight.dim(1),
                  layer.scales.dtype == first.scales.dtype,
                  let biases = layer.biases
            else { return nil }
            rowBiases.append(biases)
        }

        let weight = concatenated(quantized.map(\.weight), axis: 0)
        let scales = concatenated(quantized.map(\.scales), axis: 0)
        let biases = concatenated(rowBiases, axis: 0)
        eval(weight, scales, biases)

        var ranges: [Range<Int>] = []
        var start = 0
        for layer in quantized {
            let rows = layer.weight.dim(0)
            let range = start ..< (start + rows)
            ranges.append(range)
            start += rows
            // Row slices share the fused buffers, so once the layer holds
            // them its own arrays are released and one copy of the weights
            // remains.
            let weightRows = weight[range]
            let scaleRows = scales[range]
            let biasRows = biases[range]
            eval(weightRows, scaleRows, biasRows)
            layer.update(parameters: ModuleParameters.unflattened([
                ("weight", weightRows), ("scales", scaleRows), ("biases", biasRows),
            ]))
        }
        return FusedQuantizedProjection(
            weight: weight,
            scales: scales,
            biases: biases,
            groupSize: first.groupSize,
            bits: first.bits,
            outputRanges: ranges
        )
    }

    /// Whether `x` is a single row of the fused input width: the one shape
    /// whose fused product is the separate products bit for bit.
    func projects(_ x: MLXArray) -> Bool {
        x.ndim > 0 && x.size == x.dim(-1)
    }

    /// One product, split into each projection's output along the last axis.
    /// Call it only for an `x` that `projects(_:)` admits.
    func callAsFunction(_ x: MLXArray) -> [MLXArray] {
        let fused = quantizedMM(
            x,
            weight,
            scales: scales,
            biases: biases,
            transpose: true,
            groupSize: groupSize,
            bits: bits,
            mode: .affine
        )
        return outputRanges.map { fused[.ellipsis, $0] }
    }
}
